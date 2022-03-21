from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from http.cookies import Morsel
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional
from urllib.parse import quote as url_quote

import aiohttp
import orjson
from Crypto.Cipher import Blowfish
from Crypto.Hash import MD5
from mutagen.flac import FLAC
from mutagen.mp3 import EasyMP3

if TYPE_CHECKING:
    from Crypto.Cipher._mode_cbc import CbcMode

from .models import DeezerAlbum, DeezerPlaylist, DeezerTrack, DeezerUser

BASE_DIR = Path(__file__).absolute().parent.parent.parent

__all__ = ("DeezerTrackStream", "DeezerClient", "should_inject_metadata")

_log = logging.getLogger("Internals.Deezer")

UserAgent = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) " "Chrome/79.0.3945.130 Safari/537.36"
)


def generate_blowfish_key(track_id: str):
    def hash_md5(data: str):
        h = MD5.new()
        h.update(data.encode() if isinstance(data, str) else data)
        return h.hexdigest()

    secret = "g4el58wc0zvf9na1"
    track_md5 = hash_md5(track_id)
    bf_key = ""
    for i in range(16):
        bf_key += chr(ord(track_md5[i]) ^ ord(track_md5[i + 16]) ^ ord(secret[i]))
    return str.encode(bf_key)


@dataclass
class DeezerTrackStream:
    track: DeezerTrack
    format: str
    url: str

    session: aiohttp.ClientSession
    request: aiohttp.ClientResponse = None
    read: int = 0
    key: bytes = None
    cipher: CbcMode = None
    loop: asyncio.AbstractEventLoop = None

    def __post_init__(self):
        if self.format.lower().startswith("mp3"):
            self.format = "MP3"
        self.read = 0
        self.key = generate_blowfish_key(self.track.id)
        self.loop = self.loop or asyncio.get_event_loop()
        self.cipher = Blowfish.new(self.key, Blowfish.MODE_CBC, b"\x00\x01\x02\x03\x04\x05\x06\x07")

    async def init(self):
        self.request = await self.session.get(self.url)

    @property
    def encrypted(self):
        return "/mobile/" in self.url or "/media/" in self.url

    @property
    def closed(self):
        return self.request._closed

    def empty(self):
        return self.request.content.at_eof()

    def available(self):
        content_length = self.request.content_length
        return content_length - self.read

    async def _decrypt_chunk(self, chunk: bytes):
        if not self.encrypted:
            return chunk
        if len(chunk) >= 2048:
            decrypted = await self.loop.run_in_executor(None, self.cipher.decrypt, chunk[0:2048])
            chunk = decrypted + chunk[2048:]
        return chunk

    async def read_bytes(self, size: int = 4096):
        streamer = self.request.content
        if self.empty():
            self.request.close()
            return b""

        data = await streamer.read(size)
        first_run = self.read == 0
        self.read += len(data)
        if self.empty():
            self.request.close()
        data = await self._decrypt_chunk(data)
        if first_run and data[0] == 0:
            for i, byte in enumerate(data):
                if byte != 0:
                    data = data[i:]
                    break
        return data

    async def read_all(self):
        complete_data = b""
        while not self.empty():
            complete_data += await self.read_bytes()
        return complete_data

    async def close(self):
        self.request.close()


class DeezerClient:
    """
    Deezer API client and more
    """

    GW_API = "http://www.deezer.com/ajax/gw-light.php"

    def __init__(self, arl: str, *, loop: asyncio.AbstractEventLoop = None):
        self.session: aiohttp.ClientSession = None
        self.logger = logging.getLogger("DeezerClient")
        self._config_path = BASE_DIR / "config" / "deezer.json"
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._loop = loop or asyncio.get_event_loop()

        self.__arl = arl

        self.__is_ready = False
        self.__current_user: DeezerUser = None

    async def close(self):
        if self.session:
            await self.session.close()

    @property
    def ready(self):
        return self.__is_ready

    async def _gw_api_call(self, method: str, json: dict = None, params: dict = None):
        if json is None:
            json = {}
        if params is None:
            params = {}

        base_param = {
            "api_version": "1.0",
            "api_token": "null",
            "input": "3",
            "method": method,
        }
        if method != "deezer.getUserData":
            base_param["api_token"] = await self._gw_get_user_token()

        base_param.update(params)
        async with self.session.post(self.GW_API, params=base_param, json=json) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Deezer: API call failed with status {resp.status}")
            res = await resp.text()

        as_json = orjson.loads(res)
        if as_json["error"]:
            raise RuntimeError(f"Deezer: API call failed with error {orjson.dumps(as_json['error']).decode('utf-8')}")
        return as_json["results"]

    async def _gw_get_user_token(self):
        token_data = await self._gw_get_user_data()
        return token_data["checkForm"]

    async def _gw_get_user_data(self):
        return await self._gw_api_call("deezer.getUserData")

    async def _load_config(self) -> Optional[DeezerUser]:
        if self._config_path.exists():
            f = await self._loop.run_in_executor(None, open, self._config_path, "r")
            data = await self._loop.run_in_executor(None, f.read)
            await self._loop.run_in_executor(None, f.close)
            parsed_data = orjson.loads(data)
            self.logger.info("Loaded config from file")
            return DeezerUser.from_dict(parsed_data)
        self.logger.info("No config file found, skipping...")
        return None

    async def _save_config(self, user: DeezerUser):
        data = user.to_json()
        json_data = orjson.dumps(data)
        f = await self._loop.run_in_executor(None, open, self._config_path, "w")
        await self._loop.run_in_executor(None, f.write, json_data.decode("utf-8"))
        await self._loop.run_in_executor(None, f.close)

    async def create(self):
        self.session = aiohttp.ClientSession(loop=self._loop, headers={"User-Agent": UserAgent})
        self.logger.info("Deezer: Creating new session, trying to authenticate with ARL")
        self.__current_user = await self._load_config()

        arl_cookie = Morsel()
        arl_cookie.set("arl", self.__arl, url_quote(self.__arl))
        arl_cookie["domain"] = ".deezer.com"
        arl_cookie["path"] = "/"
        arl_cookie["httponly"] = True
        self.session.cookie_jar.update_cookies({"arl": arl_cookie})
        if self.__current_user is not None:
            self.logger.info("Deezer: Found saved user, skipping authentication")
            self.__is_ready = True
            return

        self.logger.info("Deezer: Trying to login via ARL cookie")
        try:
            user_data = await self._gw_get_user_data()
        except Exception:
            self.logger.info("Deezer: Failed to login via ARL cookie")
            return
        self.logger.info("Deezer: Login successful")
        as_current_user = DeezerUser.from_user_data(user_data, self.__arl)
        self.__current_user = as_current_user
        self.__is_ready = True
        await self._save_config(as_current_user)

    async def get_track(self, track_id: str):
        self.logger.info(f"Deezer: Requesting <{track_id}> into Tracks GW API")
        try:
            track_info = await self._gw_api_call("song.getData", {"sng_id": track_id})
        except Exception:
            self.logger.info(f"Deezer: Unable to find specified track <{track_id}>")
            return None

        return DeezerTrack.from_gw_track(track_info)

    async def _get_track_url(self, track: DeezerTrack, quality_format: str):
        request_data = {
            "license_token": self.__current_user.token,
            "media": [{"type": "FULL", "formats": [{"cipher": "BF_CBC_STRIPE", "format": quality_format}]}],
            "track_tokens": [track.track_token],
        }
        async with self.session.post("https://media.deezer.com/v1/get_url", json=request_data) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Deezer: Failed to get track URL with status {resp.status}")
            res = await resp.text()

        as_json = orjson.loads(res)
        track_data = as_json.get("data", [])
        if not track_data:
            return None
        return track_data[0]["media"][0]["sources"][0]["url"]

    async def get_track_stream(self, track_id: str):
        track_info = await self.get_track(track_id)
        if track_info is None:
            return None

        best_quality = track_info.best_quality()
        if best_quality is None:
            self.logger.error(f"DeezerTrack: No available quality for track <{track_id}>")
            return None
        self.logger.info(f"DeezerTrack: Requesting stream for <{track_id}> [{best_quality}]")
        track_url = await self._get_track_url(track_info, best_quality.value)
        if track_url is None:
            self.logger.error(f"DeezerTrack: No available stream for track <{track_id}>, falling back...")
            track_url = track_info.get_encrypted_url()
        if track_url is None:
            self.logger.error(f"DeezerTrack: No available stream for track <{track_id}>")
            return None

        track_stream = DeezerTrackStream(track_info, best_quality.value, track_url, self.session)
        self.logger.info(f"DeezerTrack: Fetched track <{track_id}>, now fetching stream...")
        await track_stream.init()
        self.logger.info(f"DeezerTrack: Track <{track_id}> loaded, returning data")
        return track_stream

    async def _get_tracks_content(self, method: str, key: str, value: str):
        tracks_array: List[DeezerTrack] = []
        body = await self._gw_api_call(method, {key: value, "nb": -1})
        for track in body.get("data", []):
            tracks_array.append(DeezerTrack.from_gw_track(track))
        return tracks_array

    async def get_album(self, album_id: str):
        self.logger.info(f"Deezer: Requesting <{album_id}> into Album GW API")
        try:
            album_data = await self._gw_api_call("album.getData", {"alb_id": album_id})
        except Exception:
            self.logger.info(f"Deezer: Unable to find specified album <{album_id}>")
            return None

        album_info = DeezerAlbum.from_gw_album(album_data)
        album_tracks = await self._get_tracks_content("song.getListByAlbum", "alb_id", album_id)
        album_info.tracks = album_tracks
        return album_info

    async def get_playlist(self, playlist_id: str):
        self.logger.info(f"Deezer: Requesting <{playlist_id}> into Playlist GW API")
        try:
            playlist_data = await self._gw_api_call(
                "deezer.pagePlaylist", {"playlist_id": playlist_id, "header": True, "lang": "en", "tab": 0}
            )
        except Exception:
            self.logger.info(f"Deezer: Unable to find specified playlist <{playlist_id}>")
            return None

        playlist_info = DeezerPlaylist.from_gw_playlist(playlist_data)
        playlist_tracks = await self._get_tracks_content("playlist.getSongs", "playlist_id", playlist_id)
        playlist_info.tracks = playlist_tracks
        return playlist_info

    async def get_artist_top_tracks(self, artist_id: str):
        self.logger.info(f"Deezer: Requesting <{artist_id}> into Artist Top Tracks GW API")
        try:
            playlist_data = await self._gw_api_call("artist.getTopTrack", {"art_id": artist_id, "nb": 25})
        except Exception:
            self.logger.info(f"Deezer: Unable to find specified Artist <{artist_id}>")
            return None

        all_tracks: List[DeezerTrack] = []
        for track_data in playlist_data.get("data", []):
            all_tracks.append(DeezerTrack.from_gw_track(track_data))
        return all_tracks


def inject_flac_metadata(bita: bytes, track: DeezerTrackStream):
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


def inject_mp3_metadata(bita: bytes, track: DeezerTrackStream):
    _log.debug(f"MP3Inject: Trying to inject metadata for track <{track.track.id}>")
    io_bita = BytesIO(bita)
    io_bita.seek(0)
    try:
        mp3_metadata = EasyMP3(io_bita)
    except Exception as e:
        _log.error(f"MP3Inject: Unable to open track <{track.track.id}>", exc_info=e)
        return bita

    track_meta = track.track
    mp3_metadata["title"] = track_meta.title
    if track_meta.album:
        mp3_metadata["album"] = track_meta.album
    if track_meta.artists:
        mp3_metadata["artist"] = track_meta.artists
    io_bita.seek(0)
    try:
        mp3_metadata.save(io_bita)
    except Exception as e:
        _log.error(f"MP3Inject: Unable to save track <{track.track.id}>", exc_info=e)
        return bita
    io_bita.seek(0)
    return io_bita.read()


def should_inject_metadata(bita: bytes, track: DeezerTrackStream):
    metadata = track.format
    if "flac" in metadata.lower():
        _log.info("MetaInjectTest: Detected mimetype as FLAC, injecting metadata...")
        return inject_flac_metadata(bita, track), metadata, ".flac"
    _log.info("MetaInjectTest: Defaulting to MP3, injecting metadata...")
    return inject_mp3_metadata(bita, track), metadata, ".mp3"
