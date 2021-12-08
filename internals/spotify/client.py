"""
MIT License

Copyright (c) 2021-present noaione

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from time import time as ctime
from typing import List, Literal, Optional, Tuple

import aiohttp
from librespot.audio import CdnManager, NormalizationData, PlayableContentFeeder
from librespot.audio.decoders import AudioQuality
from librespot.core import ApResolver
from librespot.core import Session as SpotifySession
from librespot.metadata import EpisodeId, TrackId
from librespot.proto import Authentication_pb2 as Authentication
from librespot.proto import Metadata_pb2 as Metadata
from mutagen.mp3 import MP3
from mutagen.oggvorbis import OggVorbis

from internals.errors import NoAudioFound, NoTrackFound
from internals.utils import complex_walk

from .models import *

BASE_DIR = Path(__file__).absolute().parent.parent.parent
_log = logging.getLogger("Internals.Spotify")

__all__ = ("LIBRESpotifyTrack", "LIBRESpotifyWrapper", "should_inject_metadata")


@dataclass
class LIBRESpotifyTrack:
    id: str
    episode: Optional[Metadata.Episode]
    track: Optional[Metadata.Track]
    input_stream: CdnManager.Streamer.InternalStream
    normalization_data: NormalizationData
    metrics: PlayableContentFeeder.Metrics

    loop: Optional[asyncio.AbstractEventLoop] = None
    is_track: bool = False

    def __post_init__(self):
        if self.track is not None:
            self.is_track = True
        if self.loop is None:
            self.loop = asyncio.get_event_loop()

    async def read_bytes(self, size: int) -> bytes:
        if size <= 0:
            return b""
        execute = self.loop.run_in_executor(
            None,
            self.input_stream.read,
            size,
        )
        return await execute

    async def seek_to(self, location: int) -> None:
        """
        Skip to the given location.
        """
        await self.loop.run_in_executor(None, self.input_stream.seek, location)

    async def close(self) -> None:
        """
        Close the track.
        """
        await self.loop.run_in_executor(None, self.input_stream.close)


class SpotifySessionAsync(SpotifySession):
    """
    A wrapped class that wrap some stuff with async related functions.
    """

    def __init__(self, inner: SpotifySession.Inner, address: str, *, loop: asyncio.AbstractEventLoop = None) -> None:
        super().__init__(inner, address)
        self._loop = loop or asyncio.get_event_loop()

        self._actual_reconnect_task: Optional[asyncio.Task] = None

    @property
    def country(self) -> Optional[str]:
        """Country code for the connected account"""
        fallbacks: List[Optional[str]] = [
            getattr(self, "__country_code", None),
            getattr(self, "SpotifySessionAsync__country_code", None),
            getattr(self, "Session__country_code", None),
            getattr(self, "_Session__country_code", None),
            getattr(self, "SpotifySession__country_code", None),
            getattr(self, "_SpotifySession__country_code", None),
            getattr(self, "_Receiver__country_code", None),
        ]
        # First non None occurence
        return next(filter(None, fallbacks), None)

    async def _reconnect(self) -> None:
        """
        Reconnect to the server.
        """
        if self.connection is not None:
            self.logger.info("SpotifyReconnect: Closing existing connection...")
            await self._loop.run_in_executor(None, self.connection.close)
            self.__receiver.stop()

        self.logger.info("SpotifyReconnect: Fetching random access point")
        ap_endpoint = await self._loop.run_in_executor(None, ApResolver.get_random_accesspoint)
        self.logger.info("SpotifyReconnect: Creating connection socket...")
        self.connection = await self._loop.run_in_executor(
            None, SpotifySession.ConnectionHolder.create, ap_endpoint, self.__inner.conf
        )
        self.logger.info("SpotifyReconnect: Connecting to Spotify...")
        await self._loop.run_in_executor(None, self.connect)
        self.logger.info("SpotifyReconnect: Connected to Spotify, authenticating...")
        log_credentials = Authentication.LoginCredentials(
            typ=self.__ap_welcome.reusable_auth_credentials_type,
            username=self.__ap_welcome.canonical_username,
            auth_data=self.__ap_welcome.reusable_auth_credentials,
        )
        await self._loop.run_in_executor(None, self.__authenticate_partial, log_credentials)
        try:
            canon_username = self.__ap_welcome.canonical_username
            self.logger.info(f"SpotifyReconnect: Authenticated! Now connecting as {canon_username}!")
        except Exception:
            self.logger.info("SpotifyReconnect: Reauthenticated!")

    def _reconnect_done(self):
        self.logger.info("Connection reestablished again, removing task...")
        if self._actual_reconnect_task:
            self._actual_reconnect_task = None

    def close(self) -> None:
        """
        Close the session.
        """
        super().close()
        if self._actual_reconnect_task:
            self._actual_reconnect_task.cancel()

    def reconnect(self) -> None:
        """
        Reconnect to the Spotify API.
        This will actuall do schedule with loop.call_soon_threadsafe.
        """
        self.logger.info("Reconnecting to Spotify API with task...")
        dt = int(ctime())
        task = self._loop.create_task(self._reconnect(), name=f"librespot-reconnect-{dt}")
        task.add_done_callback(self._reconnect_done)
        self._actual_reconnect_task = task


class LIBRESpotifyWrapper:
    def __init__(self, username: str, password: str, *, loop: asyncio.AbstractEventLoop = None):
        self.username = username
        self.password = password
        self.logger = logging.getLogger("SpotifyWrapper")

        self._config_path = BASE_DIR / "config" / "spotify.json"
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._loop = loop or asyncio.get_event_loop()

        session_config = SpotifySession.Configuration.Builder()
        session_config.set_stored_credential_file(str(self._config_path))

        builder = SpotifySession.Builder(session_config.build())
        if os.path.exists(self._config_path):
            self.logger.info(f"Spotify: Using saved credentials <{self._config_path}>")
            builder.stored_file(str(self._config_path))
        else:
            self.logger.info(f"Spotify: Using provided credentials <{username}>")
            builder.user_pass(username, password)
        builder.set_device_name("LIBRESpotify-Spotilava")

        self.builder = builder
        self.session: SpotifySessionAsync = None

    def clsoe(self):
        self.logger.info("Spotify: Closing session")
        self.session.close()

    async def create(self):
        self.logger.info("Spotify: Fetching random access point")
        ap_endpoint = await self._loop.run_in_executor(None, ApResolver.get_random_accesspoint)
        self.logger.info("Spotify: Creating session")
        session = SpotifySessionAsync(
            SpotifySession.Inner(
                self.builder.device_type,
                self.builder.device_name,
                self.builder.preferred_locale,
                self.builder.conf,
                self.builder.device_id,
            ),
            ap_endpoint,
            loop=self._loop,
        )
        self.logger.info(f"Spotify: Connecting to session <{self.builder.device_id}> [{self.builder.device_name}]")
        await self._loop.run_in_executor(None, session.connect)
        self.logger.info("Spotify: Connected, authenticating...")
        await self._loop.run_in_executor(None, session.authenticate, self.builder.login_credentials)
        self.logger.info("Spotify: Authenticated")
        self.session = session

    async def get_track(self, track_id: str):
        track_real = TrackId.from_uri(f"spotify:track:{track_id}")
        self.logger.info(f"SpotifyTrack: Fetching track <{track_id}>")
        try:
            track = await self._loop.run_in_executor(
                None,
                self.session.content_feeder().load,
                track_real,
                AudioQuality.VERY_HIGH,
                False,
                None,
            )
        except NoAudioFound as naf:
            self.logger.error(
                f"SpotifyTrack: Unable find suitable audio for {track_id}, please report to maintainer with logs!",
                exc_info=naf,
            )
            return None
        except NoTrackFound:
            self.logger.error(
                f"SpotifyTrack: No track (including alt track) found for {track_id}. "
                "It's possible that your account cannot view this track at all."
            )
            return None
        except RuntimeError as re:
            self.logger.error(
                f"SpotifyTrack: RuntimeError while fetching track <{track_id}>, report to maintainer with logs!",
                exc_info=re,
            )
            return None
        if track is None:
            return None
        self.logger.info(f"SpotifyTrack: Fetching track <{track_id}> complete, now fetching stream...")
        init_stream = await self._loop.run_in_executor(None, track.input_stream.stream)
        self.logger.info(f"SpotifyTrack: Track <{track_id}> loaded, returning data")
        return LIBRESpotifyTrack(
            track_id, track.episode, track.track, init_stream, track.normalization_data, track.metrics, loop=self._loop
        )

    async def get_episode(self, episode_id: str):
        episode_real = EpisodeId.from_uri(f"spotify:episode:{episode_id}")
        self.logger.info(f"SpotifyEpisode: Fetching episode <{episode_id}>")
        try:
            episode = await self._loop.run_in_executor(
                None,
                self.session.content_feeder().load,
                episode_real,
                AudioQuality.VERY_HIGH,
                False,
                None,
            )
        except NoAudioFound as naf:
            self.logger.error(
                f"SpotifyEpisode: Unable find suitable audio for {episode_id}, please report to maintainer with logs!",
                exc_info=naf,
            )
            return None
        except RuntimeError as re:
            self.logger.error(
                f"SpotifyEpisode: RuntimeError while fetching episode <{episode_id}>, report to maintainer with logs!",
                exc_info=re,
            )
            return None
        if episode is None:
            return None
        self.logger.info(f"SpotifyEpisode: Fetching episode <{episode_id}> complete, now fetching stream...")
        init_stream = await self._loop.run_in_executor(None, episode.input_stream.stream)
        self.logger.info(f"SpotifyEpisode: Episode <{episode_id}> loaded, returning data")
        return LIBRESpotifyTrack(
            episode_id,
            episode.episode,
            episode.track,
            init_stream,
            episode.normalization_data,
            episode.metrics,
            loop=self._loop,
            is_track=False,
        )

    async def _get_token(self):
        self.logger.info("Spotify: Fetching token provider")
        token_provider = await self._loop.run_in_executor(None, self.session.tokens)
        self.logger.info("Spotify: Fetching token for playlist-read")
        token = await self._loop.run_in_executor(None, token_provider.get_token, "playlist-read")
        return token.access_token

    async def _fetch_all_tracks(self, next: str, token: str):
        header_token = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        merged_items = []
        next_url = next
        async with aiohttp.ClientSession(headers=header_token) as session:
            while True:
                async with session.get(next_url) as resp:
                    if resp.status != 200:
                        break
                    res = await resp.json()
                    next_url = complex_walk(res, "next")
                    if not next_url:
                        merged_items.extend(res.get("items", []))
                        break
                    merged_items.extend(res.get("items", []))
        return merged_items

    async def get_track_metadata(self, track_id: str) -> Optional[SpotifyTrack]:
        token = await self._get_token()

        header_token = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession(headers=header_token) as client:
            self.logger.info(f"Spotify: Requesting <{track_id}> into Tracks API")
            async with client.get(f"https://api.spotify.com/v1/tracks/{track_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if data:
            return SpotifyTrack.from_track(data)
        return None

    async def get_album(self, album_id: str) -> Optional[SpotifyAlbum]:
        token = await self._get_token()

        header_token = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession(headers=header_token) as client:
            self.logger.info(f"Spotify: Requesting <{album_id}> into Album API")
            async with client.get(f"https://api.spotify.com/v1/albums/{album_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        next_token = complex_walk(data, "tracks.next")
        merged_items = None
        if next_token:
            self.logger.info(f"Spotify: Album <{album_id}> has next data, fetching...")
            merged_items = await self._fetch_all_tracks(next_token, token)

        if data:
            album_data = SpotifyAlbum.from_album(data)
            if merged_items:
                parsed_data = []
                for item in merged_items:
                    tipe = complex_walk(item, "track.type")
                    if tipe == "track":
                        parsed_data.append(SpotifyTrack.from_track(item["track"]))
                current_tracks = album_data.tracks
                current_tracks.extend(parsed_data)
                album_data.tracks = current_tracks
            return album_data
        return None

    async def get_playlist(self, playlist_id: str) -> Optional[SpotifyPlaylist]:
        token = await self._get_token()

        header_token = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession(headers=header_token) as client:
            self.logger.info(f"Spotify: Requesting <{playlist_id}> into Playlist API")
            async with client.get(f"https://api.spotify.com/v1/playlists/{playlist_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        next_token = complex_walk(data, "tracks.next")
        merged_items = None
        if next_token:
            self.logger.info(f"Spotify: Playlist <{playlist_id}> has next data, fetching...")
            merged_items = await self._fetch_all_tracks(next_token, token)

        if data:
            playlist_data = SpotifyPlaylist.from_playlist(data)
            if merged_items:
                parsed_data = []
                for item in merged_items:
                    tipe = complex_walk(item, "track.type")
                    if tipe == "track":
                        parsed_data.append(SpotifyTrack.from_track(item["track"]))
                current_tracks = playlist_data.tracks
                current_tracks.extend(parsed_data)
                playlist_data.tracks = current_tracks
            return playlist_data
        return None

    async def get_artist_tracks(self, artist_id: str):
        token = await self._get_token()

        header_token = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession(headers=header_token) as client:
            self.logger.info(f"Spotify: Requesting <{artist_id}> into Artist API")
            async with client.get(f"https://api.spotify.com/v1/artists/{artist_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if complex_walk(data, "type") != "artist":
            self.logger.warning(f"Spotify: Artist <{artist_id}> is not an artist")
            return None

        artist_info = SpotifyArtistWithTrack.from_artist(data)
        country_code = self.session.country

        async with aiohttp.ClientSession(headers=header_token) as client:
            self.logger.info(f"Spotify: Requesting <{artist_id}> into Artist Top Tracks API")
            async with client.get(
                f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks",
                params={"market": country_code},
            ) as resp:
                tracks_data = await resp.json()

        tracks: List[SpotifyTrack] = []
        for item in tracks_data.get("tracks", []):
            tracks.append(SpotifyTrack.from_track(item))
        artist_info.tracks = tracks
        return artist_info

    async def get_show(self, show_id: str):
        token = await self._get_token()

        header_token = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession(headers=header_token) as client:
            self.logger.info(f"Spotify: Requesting <{show_id}> into Shows API")
            async with client.get(f"https://api.spotify.com/v1/shows/{show_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        next_token = complex_walk(data, "episodes.next")
        merged_items = None
        if next_token:
            self.logger.info(f"Spotify: Shows <{show_id}> has next data, fetching...")
            merged_items = await self._fetch_all_tracks(next_token, token)

        if data:
            show_data = SpotifyShow.from_show(data)
            if merged_items:
                parsed_data = []
                for item in merged_items:
                    parsed_data.append(SpotifyEpisode.from_episode(item))
                current_episodes = show_data.episodes
                current_episodes.extend(parsed_data)
                show_data.episodes = current_episodes
            return show_data
        return None

    async def get_episode_metadata(self, episode_id: str):
        token = await self._get_token()

        header_token = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession(headers=header_token) as client:
            self.logger.info(f"Spotify: Requesting <{episode_id}> into Episodes API")
            async with client.get(f"https://api.spotify.com/v1/episodes/{episode_id}") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

        if data:
            return SpotifyEpisode.from_episode(data)
        return None


def inject_ogg_metadata(bita: bytes, track: LIBRESpotifyTrack) -> bytes:
    _log.debug(f"OggInject: Trying to inject metadata for track/episode <{track.id}>")
    io_bita = BytesIO(bita)
    io_bita.seek(0)
    try:
        ogg_metadata = OggVorbis(io_bita)
    except Exception as e:
        _log.warning(f"OggInject: Unable to open track/episode <{track.id}>", exc_info=e)
        return bita
    track_meta = track.track
    if not track.is_track:
        track_meta = track.episode
    ogg_metadata["TITLE"] = track_meta.name
    if not track.is_track:
        ogg_metadata["ALBUM"] = track_meta.show.name
    else:
        ogg_metadata["ALBUM"] = track_meta.album.name
    artists_list = []
    if track.is_track:
        for artist in track_meta.artist:
            artists_list.append(artist.name)
    else:
        # Use show name temporarily
        artists_list = [track_meta.show.name]
    ogg_metadata["ARTIST"] = artists_list
    try:
        ogg_metadata.save(io_bita)
    except Exception as e:
        _log.warning(f"OggInject: Unable to inject metadata for track/episode <{track.id}>", exc_info=e)
        return bita
    io_bita.seek(0)
    return io_bita.read()


def test_mp3_meta(bita: bytes):
    io_bita = BytesIO(bita)
    io_bita.seek(0)
    try:
        MP3(io_bita)
        return True
    except Exception:
        _log.warning("Unable to find MP3 header")
        return False


def inject_mp3_metadata(bita: bytes, track: LIBRESpotifyTrack) -> bytes:
    io_bita = BytesIO(bita)
    io_bita.seek(0)
    try:
        mp3_metadata = MP3(io_bita)
    except Exception as e:
        _log.warning(f"MP3Inject: Unable to open track/episode <{track.id}>", exc_info=e)
        return bita

    track_meta = track.track
    if not track.is_track:
        track_meta = track.episode
    mp3_metadata["TITLE"] = track_meta.name
    if not track.is_track:
        mp3_metadata["ALBUM"] = track_meta.show.name
    artists_list = []
    if track.is_track:
        for artist in track_meta.artist:
            artists_list.append(artist.name)
    else:
        # Use show name temporarily
        artists_list = [track_meta.show.name]
    mp3_metadata["ARTIST"] = artists_list
    try:
        mp3_metadata.save(io_bita)
    except Exception as e:
        _log.warning(f"MP3Inject: Unable to inject metadata for track/episode <{track.id}>", exc_info=e)
        return bita
    io_bita.seek(0)
    return io_bita.read()


FileContentType = Literal["audio/ogg", "audio/mpeg", "audio/aac"]
FileContentExt = Literal[".ogg", ".mp3", ".m4a"]


def should_inject_metadata(bita: bytes, track: LIBRESpotifyTrack) -> Tuple[bytes, FileContentType, FileContentExt]:
    _log.info("MetaInjectTest: Checking bytes header for OggS...")
    ogg_bita = bita[:4]
    if ogg_bita == b"OggS":
        _log.info("MetaInjectTest: Found OggS header, injecting metadata...")
        return inject_ogg_metadata(bita, track), "audio/ogg", ".ogg"
    _log.info("MetaInjectTest: No OggS header found, trying to check ID3 meta...")
    id3_bita = bita[:3]
    if id3_bita == b"ID3":
        _log.info("MetaInjectTest: Found ID3 header, returning immediatly...")
        return bita, "audio/mpeg", ".mp3"
    _log.info("MetaInjectTest: No ID3 header found, trying to find MP3 header...")
    is_mp3 = test_mp3_meta(bita)
    if is_mp3:
        _log.info("MetaInjectTest: Found MP3 header, injecting metadata...")
        return inject_mp3_metadata(bita, track), "audio/mpeg", ".mp3"
    _log.info("MetaInjectTest: No match for metadata, returning immediatly with ogg meta...")
    return bita, "audio/ogg", ".ogg"
