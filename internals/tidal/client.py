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
from base64 import b64decode
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

import aiohttp
import orjson
from Crypto.Cipher import AES
from Crypto.Util import Counter
from mutagen.flac import FLAC
from mutagen.mp4 import MP4 as ALAC

from .enums import TidalAudioQuality
from .models import TidalAlbum, TidalPlaylist, TidalTrack, TidalUser
from .mpd import TidalMPDMeta, parse_mpd_string
from .stream import TidalBTS, TidalMPD

if TYPE_CHECKING:
    from Crypto.Cipher._mode_ctr import CtrMode

BASE_DIR = Path(__file__).absolute().parent.parent.parent

__all__ = ("TidalTrackStream", "TidalAPI", "should_inject_metadata")

_log = logging.getLogger("Internals.Tidal")


class TidalConfig:
    def __init__(self):
        import random

        cc_s = [
            86,
            74,
            75,
            104,
            68,
            70,
            113,
            74,
            80,
            113,
            118,
            115,
            80,
            86,
            78,
            66,
            86,
            54,
            117,
            107,
            88,
            84,
            74,
            109,
            119,
            108,
            118,
            98,
            116,
            116,
            80,
            55,
            119,
            108,
            77,
            108,
            114,
            99,
            55,
            50,
            115,
            101,
            52,
        ]
        cc_id = [122, 85, 52, 88, 72, 86, 86, 107, 99, 50, 116, 68, 80, 111, 52, 116]
        i = random.randint(0, len(cc_s) - 1)
        for _ in range(i):
            cc_s.reverse()
        j = random.randint(0, len(cc_id) - 1)
        for _ in range(j):
            cc_id.reverse()

        cc_s = "".join(chr(c) for c in cc_s)
        cc_id = "".join(chr(c) for c in cc_id)

        self.client_id: str = cc_id
        self.client_secret: str = cc_s

        for _ in range(i):
            self.client_secret = self.client_secret[::-1]
        self.client_secret += "="
        for _ in range(j):
            self.client_id = self.client_id[::-1]


@dataclass
class TidalTrackDecryptor:
    encryption_key: Optional[str] = None

    decryptor: CtrMode = None
    loop: asyncio.AbstractEventLoop = None

    def __post_init__(self):
        loop = asyncio.get_event_loop() or self.loop
        self.loop = loop
        if self.encryption_key:
            # Do not change
            master_key = "UIlTTEMmmLfGowo/UC60x2H45W6MdGgTRfo/umg4754="

            # Decode the base64 strings to ascii strings
            master_key = b64decode(master_key)
            security_token = b64decode(self.encryption_key)

            # Get the IV from the first 16 bytes of the securityToken
            iv = security_token[:16]
            encrypted_st = security_token[16:]

            # Initialize decryptor
            decryptor = AES.new(master_key, AES.MODE_CBC, iv)

            # Decrypt the security token
            decrypted_st = decryptor.decrypt(encrypted_st)

            # Get the audio stream decryption key and nonce from the decrypted security token
            key = decrypted_st[:16]
            nonce = decrypted_st[16:24]

            counter = Counter.new(64, prefix=nonce, initial_value=0)
            self.decryptor = AES.new(key, AES.MODE_CTR, counter=counter)

    async def decrypt(self, data: bytes) -> bytes:
        if self.decryptor is None:
            return data

        execute = await self.loop.run_in_executor(None, self.decryptor.decrypt, data)
        return execute


@dataclass
class TidalTrackStream:
    track: TidalTrack
    streamer: Union[TidalBTS, TidalMPD]
    decryptor: TidalTrackDecryptor
    is_mpd: bool = False

    def __post_init__(self):
        if isinstance(self.streamer, TidalMPD):
            self.is_mpd = True

    async def init(self):
        await self.streamer.init()

    def empty(self):
        return self.streamer.empty()

    def available(self):
        if isinstance(self.streamer, TidalMPD):
            # TODO: figure out how to check total MPD length
            return -1
        return self.streamer.available()

    async def read_bytes(self, size: int = 4096):
        if self.empty():
            await self.streamer.close()
            return b""

        data = await self.streamer.read_bytes(size)
        return await self.decryptor.decrypt(data)

    async def read_all(self):
        data = await self.streamer.read_all()
        await self.streamer.close()
        return await self.decryptor.decrypt(data)

    async def as_chunks(self, read_every: bytes):
        async for chunks in self.streamer.as_chunks(read_every):
            yield await self.decryptor.decrypt(chunks)


class TidalAPI:
    PATH = "https://api.tidalhifi.com/v1"
    AUTH_PATH = "https://auth.tidal.com/v1/oauth2"

    def __init__(self, *, loop: asyncio.AbstractEventLoop = None):
        self.session: aiohttp.ClientSession = None
        self.logger = logging.getLogger("TidalAPI")

        self._config_path = BASE_DIR / "config" / "tidal.json"
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._loop = loop or asyncio.get_event_loop()

        self.__conf = TidalConfig()
        self.__is_ready = False
        self.__user: TidalUser = None

    async def close(self):
        if self.session:
            await self.session.close()

    @property
    def ready(self):
        return self.__is_ready

    async def _load_config(self) -> Optional[TidalUser]:
        if self._config_path.exists():
            f = await self._loop.run_in_executor(None, open, self._config_path, "r")
            data = await self._loop.run_in_executor(None, f.read)
            await self._loop.run_in_executor(None, f.close)
            parsed_data = orjson.loads(data)
            self.logger.info("Loaded config from file")
            return TidalUser.from_dict(parsed_data)
        self.logger.info("No config file found, skipping...")
        return None

    async def _save_config(self, user: TidalUser):
        data = user.to_dict()
        json_data = orjson.dumps(data)
        f = await self._loop.run_in_executor(None, open, self._config_path, "w")
        await self._loop.run_in_executor(None, f.write, json_data.decode("utf-8"))
        await self._loop.run_in_executor(None, f.close)

    async def _link_login(self) -> Optional[TidalUser]:
        data = {"client_id": self.__conf.client_id, "scope": "r_usr+w_usr+w_sub"}

        async with self.session.post(self.AUTH_PATH + "/device_authorization", data=data) as sesi:
            res = await sesi.json()

        device_code = res["deviceCode"]
        user_code = res["userCode"]
        verif_url = res["verificationUri"]
        expires_in = res["expiresIn"]
        req_interval = res["interval"]
        self.logger.info(f"Please visit https://{verif_url} and enter {user_code} to authorize")
        self.logger.info(f"The above link is valid for {expires_in} seconds")

        data = await self._authorize_link_login(device_code, expires_in, req_interval)

        if data is None:
            self.logger.error("Failed to authorize, you took to long to authorize this device!")
            return None

        ctime = datetime.now(tz=timezone.utc).timestamp()

        access_token = data["access_token"]
        refresh_token = data["refresh_token"]
        expires_after = ctime + data["expires_in"]

        uuid = data["user"]["userId"]
        country_code = data["user"]["countryCode"]

        user = TidalUser(uuid, country_code, access_token, refresh_token, expires_after)
        return user

    async def _authorize_link_login(self, device_code: str, expires_in: int, req_interval: int):
        auth_url = self.AUTH_PATH + "/token"
        data = {
            "client_id": self.__conf.client_id,
            "client_secret": self.__conf.client_secret,
            "device_code": device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "scope": "r_usr+w_usr+w_sub",
        }

        while expires_in > 0:
            async with self.session.post(auth_url, data=data) as sesi:
                res = await sesi.json()
                if sesi.ok:
                    return res

                if res["error"] == "expired_token":
                    break
            await asyncio.sleep(req_interval)
            expires_in -= req_interval

        return None

    async def _verify_and_refresh_token(self):
        user = self.__user
        current_time = datetime.now(tz=timezone.utc).timestamp()
        if user.expires_at > current_time:
            # Token still valid
            return True
        url = self.AUTH_PATH + "/token"
        data = {
            "client_id": self.__conf.client_id,
            "client_secret": self.__conf.client_secret,
            "refresh_token": user.refresh,
            "grant_type": "refresh_token",
        }

        self.logger.info("Tidal: Access token expired, refreshing token...")
        async with self.session.post(url, data=data) as sesi:
            res = await sesi.json()
            if sesi.ok:
                self.__user.token = res["access_token"]
                self.__user.expires_at = datetime.now(tz=timezone.utc).timestamp() + res["expires_in"]
                return True
        self.logger.error("Tidal: The refresh token has already expired, please relogin!")
        content = await self._link_login()
        if not content:
            self.logger.error("Tidal: Failed to login via device auth, disabling Tidal extension!")
            self.__is_ready = False
        self.__user = content
        self.logger.info("Tidal: Successfully refreshed token")
        await self._save_config(content)
        return False

    async def create(self):
        self.session = aiohttp.ClientSession(loop=self._loop)
        self.logger.info("Tidal: Creating new session, trying to login...")
        self.__user = await self._load_config()
        if self.__user is not None:
            # refresh token if possible
            is_success = await self._verify_and_refresh_token()
            if is_success:
                self.logger.info("Logged in via saved token!")
                await self._save_config(self.__user)
                self.__is_ready = True
                return

        self.logger.info("Tidal: Trying to login via device auth...")
        data = await self._link_login()
        if data is None:
            self.logger.error("Tidal: Failed to login via device auth!")
            return
        self.logger.info("Tidal: User authorized!")
        self.__is_ready = True
        self.logger.info(f"Tidal: User ID: {data.id}")
        self.logger.info(f"Tidal: Country Code: {data.cc}")
        await self._save_config(data)

    async def _get(self, url: str, params: Dict[str, Any] = None):
        await self._verify_and_refresh_token()
        headers = {"Authorization": f"Bearer {self.__user.token}"}
        if params is None:
            params = {}
        params["countryCode"] = self.__user.cc
        async with self.session.get(url, params=params, headers=headers) as sesi:
            resp = await sesi.json()
            if sesi.ok:
                return resp
        return None

    async def _get_items(self, url: str):
        offset = 0
        limit = 100
        all_tracks: List[dict] = []
        while True:
            params = {"limit": limit, "offset": offset}
            tracks = await self._get(url, params)
            if tracks is None:
                break

            items = tracks["items"]
            all_tracks.extend(items)
            if len(items) < limit:
                break
        return all_tracks

    async def get_track(self, track_id: str):
        url_path = self.PATH + f"/tracks/{track_id}"

        self.logger.info(f"Tidal: Requesting <{track_id}> into Tracks API")
        track_info = await self._get(url_path)
        if track_info is None:
            self.logger.error(f"Tidal: Unable to find specified track <{track_id}>!")
            return None

        return TidalTrack.from_track(track_info)

    async def _get_stream_info(self, track: TidalTrack, want: str = "OFFLINE", override: str = None):
        url_path = self.PATH + f"/tracks/{track.id}/playbackinfopostpaywall"
        params = {
            "audioquality": track.audio_quality.value,
            "playbackmode": want,
            "assetpresentation": "FULL",
        }
        if override is not None:
            params["audioquality"] = override
        self.logger.info(f"TidalTrack: Fetching {want} URL information for <{track.id}>")
        stream_info = await self._get(url_path, params)
        return stream_info

    async def get_track_stream(self, track_id: str):
        self.logger.info(f"TidalTrack: Fetching track <{track_id}>")
        track_info = await self.get_track(track_id)
        if not track_info:
            self.logger.error(f"Tidal: Unable to find specified track <{track_id}>!")
            return None

        stream_info = await self._get_stream_info(track_info, override="HIGH")
        if stream_info is None:
            stream_info = await self._get_stream_info(track_info, "STREAM", "HIGH")
            if stream_info is None:
                self.logger.error(f"Tidal: Unable to find any stream URL for track <{track_id}>!")
                return None
        else:
            audio_qual = TidalAudioQuality(stream_info["audioQuality"])
            if audio_qual != track_info.audio_quality:
                self.logger.warning(
                    f"Tidal: Audio quality <{audio_qual}> is not available for track <{track_id}>, trying STREAM"
                )
                stream_info_st_mode = await self._get_stream_info(track_info, "STREAM")
                if stream_info_st_mode is None:
                    self.logger.error(
                        f"Tidal: Unable to find any stream URL for track <{track_id}> with STREAM mode!"
                        f" using <{audio_qual}> quality"
                    )
                else:
                    audio_qual_stream = TidalAudioQuality(stream_info_st_mode["audioQuality"])
                    if audio_qual_stream > audio_qual:
                        stream_info = stream_info_st_mode
                        self.logger.info(
                            f"Tidal(Stream): Audio quality <{audio_qual_stream}> is available "
                            f"for track <{track_id}>, using it"
                        )
                    else:
                        self.logger.info(
                            f"Tidal(Offline): Audio quality <{track_info.audio_quality}> is unavailable "
                            f"for track <{track_id}>, using <{audio_qual}> quality"
                        )

        mf_type = stream_info["manifestMimeType"]
        manifest = None
        if "vnd.tidal.bts" in mf_type:
            self.logger.info(f"TidalTrack: Detected manifest type for <{track_id}> ({mf_type})")
            manifest = orjson.loads(b64decode(stream_info["manifest"]))
        elif "dash+xml" in mf_type:
            self.logger.info(f"TidalTrack: Detected manifest type for <{track_id}> ({mf_type})")
            manifest = parse_mpd_string(b64decode(stream_info["manifest"]).decode("utf-8"))
        else:
            self.logger.error(f"TidalTrack: Unknown manifest type for <{track_id}> ({mf_type})")
            return None

        if manifest is None:
            self.logger.error(f"TidalTrack: Unable to parse manifest for <{track_id}>")
            return None

        tidal_key = None
        if not isinstance(manifest, TidalMPDMeta) and "keyId" in manifest:
            tidal_key = manifest["keyId"]

        tidal_streamer = None
        if isinstance(manifest, TidalMPDMeta):
            tidal_streamer = TidalMPD(manifest, session=self.session, loop=self._loop)
        else:
            codecs = manifest.get("codecs", "unknown")
            mimetype = manifest.get("mimeType", "unknown")
            url = manifest["urls"][0]
            tidal_streamer = TidalBTS(codecs, mimetype, url, session=self.session, loop=self._loop)

        decryption = TidalTrackDecryptor(tidal_key, loop=self._loop)
        track_stream = TidalTrackStream(
            track=track_info,
            streamer=tidal_streamer,
            decryptor=decryption,
        )
        self.logger.info(f"TidalTrack: Fetched track <{track_id}>, now fetching stream...")
        await track_stream.init()
        self.logger.info(f"TidalTrack: Track <{track_id}> loaded, returning data")
        return track_stream

    async def get_album(self, album_id: str):
        url_path = self.PATH + f"/albums/{album_id}"

        self.logger.info(f"Tidal: Requesting <{album_id}> into Album API")
        album_info = await self._get(url_path)
        if album_info is None:
            return None

        album = TidalAlbum.from_album(album_info)
        self.logger.info(f"Tidal: Fetched album <{album_id}>, now fetching tracks...")
        all_tracks = await self._get_items(url_path + "/items")

        parsed_tracks: List[TidalTrack] = []
        for track in all_tracks:
            actual_track = track.get("item") or track
            parsed_tracks.append(TidalTrack.from_track(actual_track))
        album.tracks = parsed_tracks
        return album

    async def get_playlists(self, playlist_id: str):
        url_path = self.PATH + f"/playlists/{playlist_id}"

        self.logger.info(f"Tidal: Requesting <{playlist_id}> into Playlist API")
        playlist_info = await self._get(url_path)
        if playlist_info is None:
            return None

        playlist = TidalPlaylist.from_playlist(playlist_info)
        self.logger.info(f"Tidal: Fetched playlist <{playlist_id}>, now fetching tracks...")
        all_tracks = await self._get_items(url_path + "/items")

        parsed_tracks: List[TidalTrack] = []
        for track in all_tracks:
            actual_track = track.get("item") or track
            parsed_tracks.append(TidalTrack.from_track(actual_track))
        playlist.tracks = parsed_tracks
        return playlist


def inject_flac_metadata(bita: bytes, track: TidalTrackStream):
    _log.debug(f"FlacInject: Trying to inject metadata for track <{track.track.id}>")
    io_bita = BytesIO(bita)
    io_bita.seek(0)
    try:
        flac_metadata = FLAC(io_bita)
    except Exception as e:
        _log.error(f"FlacInject: Unable to open track <{track.track.id}>", exc_info=e)
        return bita

    track_meta = track.track
    flac_metadata["TITLE"] = track_meta.title
    if track_meta.album:
        flac_metadata["ALBUM"] = track_meta.album
    if track_meta.artists:
        flac_metadata["ARTIST"] = track_meta.artists
    # Seek again to zero
    io_bita.seek(0)
    try:
        flac_metadata.save(io_bita)
    except Exception as e:
        _log.error(f"FlacInject: Unable to save track <{track.track.id}>", exc_info=e)
        return bita
    io_bita.seek(0)
    return io_bita.read()


def inject_mpX_metadata(bita: bytes, track: TidalTrackStream):
    _log.debug(f"MPXInject: Trying to inject metadata for track <{track.track.id}>")
    io_bita = BytesIO(bita)
    io_bita.seek(0)
    try:
        aac_metadata = ALAC(io_bita)
    except Exception as e:
        _log.error(f"MPXInject: Unable to open track <{track.track.id}>", exc_info=e)
        return bita

    track_meta = track.track
    aac_metadata["title"] = track_meta.title
    if track_meta.album:
        aac_metadata["album"] = track_meta.album
    if track_meta.artists:
        aac_metadata["artist"] = track_meta.artists
    io_bita.seek(0)
    try:
        aac_metadata.save(io_bita)
    except Exception as e:
        _log.error(f"MPXInject: Unable to save track <{track.track.id}>", exc_info=e)
        return bita
    io_bita.seek(0)
    return io_bita.read()


map_codecs = {
    "eac3": ".eac3",
    "ac3": ".ac3",
    "alac": ".alac",
    "ac4": ".ac4",
    "mha1": ".mp4",
}


def should_inject_metadata(bita: bytes, track: TidalTrackStream):
    metadata = track.streamer.mimetype
    if "flac" in metadata:
        _log.info("MetaInjectTest: Detected mimetype as FLAC, injecting metadata...")
        return inject_flac_metadata(bita, track), metadata, ".flac"
    _log.info("MetaInjectTest: Defaulting to AAC/M4A/ALAC, injecting metadata...")
    return inject_mpX_metadata(bita, track), metadata, map_codecs.get(track.streamer.codecs, ".m4a")
