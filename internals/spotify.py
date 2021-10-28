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
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
from typing import List, Optional, Type

import aiohttp
from librespot.audio import (CdnManager, NormalizationData,
                             PlayableContentFeeder)
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.core import ApResolver
from librespot.core import Session as SpotifySession
from librespot.metadata import TrackId
from librespot.proto import Metadata_pb2 as Metadata

from .utils import complex_walk

BASE_DIR = Path(__name__).parent.parent


@dataclass
class LIBRESpotifyTrack:
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
        execute = self.loop.run_in_executor(
            None,
            self.input_stream.read,
            size,
        )
        return await execute


@dataclass
class SpotifyTrack:
    id: str
    title: str
    album: Optional[str]
    image: Optional[str]
    artists: List[str] = field(default_factory=list)
    duration: Optional[int] = None

    @classmethod
    def from_track(cls: Type[SpotifyTrack], track: dict) -> SpotifyTrack:
        album_name = complex_walk(track, "album.name")
        image_album = complex_walk(track, "album.images.0.url")

        artists = []
        for artist in track.get("artists", []):
            artists.append(artist["name"])
        duration = int(ceil(track.get("duration_ms", 0) / 1000))
        return cls(
            id=track["id"],
            title=track["name"],
            album=album_name,
            image=image_album,
            artists=artists,
            duration=duration,
        )

    def to_json(self):
        return {
            "id": self.id,
            "title": self.title,
            "album": self.album,
            "image": self.image,
            "artists": self.artists,
            "duration": self.duration,
        }


@dataclass
class SpotifyArtist:
    id: str
    name: str
    image: Optional[str]

    @classmethod
    def from_artist(cls: Type[SpotifyArtist], artist: dict) -> SpotifyArtist:
        image = complex_walk(artist, "images.0.url")
        return cls(
            id=artist["id"],
            name=artist["name"],
            image=image,
        )

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
        }


@dataclass
class SpotifyAlbum:
    id: str
    name: str
    image: str
    artists: List[SpotifyArtist]
    tracks: List[SpotifyTrack]

    @classmethod
    def from_album(cls: Type[SpotifyAlbum], album: dict) -> SpotifyAlbum:
        image = complex_walk(album, "images.0.url")
        artists = [SpotifyArtist.from_artist(artist) for artist in album.get("artists", [])]
        tracks_set = complex_walk(album, "tracks.items") or []
        tracks = [SpotifyTrack.from_track(track) for track in tracks_set]
        return cls(
            id=album["id"],
            name=album["name"],
            image=image,
            artists=artists,
            tracks=tracks,
        )

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "artists": [artist.to_json() for artist in self.artists],
            "tracks": [track.to_json() for track in self.tracks],
        }


@dataclass
class SpotifyPlaylist:
    id: str
    name: str
    image: str
    tracks: List[SpotifyTrack]

    @classmethod
    def from_playlist(cls: Type[SpotifyPlaylist], playlist: dict) -> SpotifyPlaylist:
        image = complex_walk(playlist, "images.0.url")
        tracks_set = complex_walk(playlist, "tracks.items") or []
        valid_tracks = []
        for track in tracks_set:
            track_meta = complex_walk(track, "track")
            if track_meta:
                valid_tracks.append(SpotifyTrack.from_track(track_meta))
        return cls(
            id=playlist["id"],
            name=playlist["name"],
            image=image,
            tracks=valid_tracks,
        )

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "tracks": [track.to_json() for track in self.tracks],
        }


class LIBRESpotifyWrapper:
    def __init__(
        self,
        username: str,
        password: str,
        *,
        loop: asyncio.AbstractEventLoop = None
    ):
        self.username = username
        self.password = password
        self.logger = logging.getLogger("SpotifyWrapper")

        self._config_path = BASE_DIR / "config" / "spotify.json"
        os.makedirs(self._config_path.parent, exist_ok=True)
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
        self.session: SpotifySession = None

    def clsoe(self):
        self.logger.info("Spotify: Closing session")
        self.session.close()

    async def create(self):
        self.logger.info("Spotify: Fetching random access point")
        ap_endpoint = await self._loop.run_in_executor(None, ApResolver.get_random_accesspoint)
        self.logger.info("Spotify: Creating session")
        session = SpotifySession(
            SpotifySession.Inner(
                self.builder.device_type,
                self.builder.device_name,
                self.builder.preferred_locale,
                self.builder.conf,
                self.builder.device_id
            ),
            ap_endpoint,
        )
        self.logger.info(f"Spotify: Connecting to session <{self.builder.device_id}> [{self.builder.device_name}]")
        await self._loop.run_in_executor(None, session.connect)
        self.logger.info("Spotify: Connected, authenticating...")
        await self._loop.run_in_executor(None, session.authenticate, self.builder.login_credentials)
        self.logger.info(f"Spotify: Authenticated")
        self.session = session

    async def get_track(self, track_id: str):
        track_real = TrackId.from_uri(f"spotify:track:{track_id}")
        self.logger.info(f"Spotify: Fetching track <{track_id}>")
        track = await self._loop.run_in_executor(
            None,
            self.session.content_feeder().load,
            track_real,
            VorbisOnlyAudioQuality(AudioQuality.VERY_HIGH),
            False,
            None
        )
        if track is None:
            return None
        self.logger.info(
            f"Spotify: Fetching track <{track_id}> complete, now fetching stream..."
        )
        init_stream = await self._loop.run_in_executor(
            None,
            track.input_stream.stream
        )
        self.logger.info(
            f"Spotify: Track <{track_id}> loaded, returning data"
        )
        return LIBRESpotifyTrack(
            track.episode, 
            track.track,
            init_stream,
            track.normalization_data,
            track.metrics,
            loop=self._loop
        )

    async def _get_token(self):
        self.logger.info("Spotify: Fetching token provider")
        token_provider = await self._loop.run_in_executor(
            None,
            self.session.tokens
        )
        self.logger.info("Spotify: Fetching token for playlist-read")
        token = await self._loop.run_in_executor(
            None,
            token_provider.get_token,
            "playlist-read"
        )
        return token.access_token

    async def _fetch_all_tracks(self, next: str, token: str):
        header_token = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

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

    async def get_album(self, album_id: str) -> Optional[SpotifyAlbum]:
        token = await self._get_token()

        header_token = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

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

        header_token = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

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
