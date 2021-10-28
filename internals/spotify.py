import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from librespot.audio import (CdnManager, NormalizationData,
                             PlayableContentFeeder)
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.core import ApResolver
from librespot.core import Session as SpotifySession
from librespot.metadata import TrackId
from librespot.proto import Metadata_pb2 as Metadata

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

    async def ping(self):
        # Ping with random track
        await self.get_track("spotify:track:5Z9Z9pQ7WlRXQZ6K5iZJqB")
