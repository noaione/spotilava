from __future__ import annotations

import hashlib
from binascii import hexlify
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Type

from Crypto.Cipher import AES

__all__ = ("DeezerAudioQuality", "DeezerUser", "DeezerTrack", "DeezerAlbum", "DeezerArtist", "DeezerPlaylist")

DeezerAlbumFmt = "https://e-cdns-images.dzcdn.net/images/{}/{}/1024x1024-000000-80-0-0.jpg"


class DeezerAudioQuality(Enum):
    low = "MP3_128"
    medium = "MP3_256"
    high = "MP3_320"
    lossless = "FLAC"

    def __int__(self):
        mapping = {"low": 0, "medium": 1, "high": 2, "lossless": 3}
        return mapping.get(self.name, -1)

    def __str__(self):
        return self.name.capitalize()

    def __eq__(self, other: DeezerAudioQuality):
        return int(self) == int(other)

    def __ne__(self, other: DeezerAudioQuality):
        return not self.__eq__(other)

    def __lt__(self, other: DeezerAudioQuality):
        return int(self) < int(other)

    def __gt__(self, other: DeezerAudioQuality):
        return int(self) > int(other)

    def __le__(self, other: DeezerAudioQuality):
        return int(self) <= int(other)

    def __ge__(self, other: DeezerAudioQuality):
        return int(self) >= int(other)


@dataclass
class DeezerUser:
    id: str
    cc: str
    token: str
    arl: str
    lossless: bool
    high_quality: bool

    @classmethod
    def from_user_data(cls: Type[DeezerUser], data: dict, arl: str) -> DeezerUser:
        user_info = data["USER"]
        user_opts = user_info["OPTIONS"]
        uuid = str(user_info["USER_ID"])
        token = user_opts["license_token"]
        hq_possible = user_opts.get("web_hq", False) or user_opts.get("mobile_hq", False)
        lossless_possible = user_opts.get("mobile_lossless", False) or user_opts.get("web_lossless", False)
        country = user_opts["license_country"]
        return cls(
            id=uuid,
            cc=country,
            token=token,
            arl=arl,
            lossless=lossless_possible,
            high_quality=hq_possible,
        )

    def to_json(self):
        return {
            "id": self.id,
            "cc": self.cc,
            "token": self.token,
            "arl": self.arl,
            "lossless": self.lossless,
            "high_quality": self.high_quality,
        }

    @classmethod
    def from_dict(cls, data: dict) -> DeezerUser:
        return cls(**data)


@dataclass
class DeezerTrack:
    id: str
    title: str
    album: Optional[str]
    image: Optional[str]
    artists: List[str]
    duration: int
    md5_origin: str
    track_token: str
    media_version: str
    available_formats: List[DeezerAudioQuality]

    @classmethod
    def from_gw_track(cls: Type[DeezerTrack], track: dict) -> DeezerTrack:
        track_id = track["SNG_ID"]
        track_title = track["SNG_TITLE"]
        artists = []
        for artist in track.get("ARTISTS", []):
            artists.append(artist["ART_NAME"])
        if not artists:
            artists.append(track["ART_NAME"])
        album_name = track.get("ALB_TITLE")
        duration = int(track["DURATION"])
        image_url = track.get("ALB_PICTURE")
        if image_url:
            image_url = DeezerAlbumFmt.format("cover", image_url)

        md5_origin = track["MD5_ORIGIN"]
        track_token = track["TRACK_TOKEN"]
        media_version = track["MEDIA_VERSION"]

        available_formats = []
        qual_low = int(track.get("FILESIZE_MP3_128", "0")) > 0
        qual_medium = int(track.get("FILESIZE_MP3_256", "0")) > 0
        qual_high = int(track.get("FILESIZE_MP3_320", "0")) > 0
        qual_lossless = int(track.get("FILESIZE_FLAC", "0")) > 0
        if qual_low:
            available_formats.append(DeezerAudioQuality.low)
        if qual_medium:
            available_formats.append(DeezerAudioQuality.medium)
        if qual_high:
            available_formats.append(DeezerAudioQuality.high)
        if qual_lossless:
            available_formats.append(DeezerAudioQuality.lossless)

        return cls(
            id=track_id,
            title=track_title,
            album=album_name,
            image=image_url,
            artists=artists,
            duration=duration,
            md5_origin=md5_origin,
            track_token=track_token,
            media_version=media_version,
            available_formats=available_formats,
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

    def get_encrypted_url(self):
        format_number = 1
        url_bytes = b"\xa4".join(
            (
                self.md5_origin.encode(),
                str(format_number).encode(),
                str(self.id).encode(),
                str(self.media_version).encode(),
            )
        )
        url_hash = hashlib.md5(url_bytes).hexdigest()
        info_bytes = bytearray(url_hash.encode())
        info_bytes.extend(b"\xa4")
        info_bytes.extend(url_bytes)
        info_bytes.extend(b"\xa4")
        # Pad the bytes so that len(info_bytes) % 16 == 0
        padding_len = 16 - (len(info_bytes) % 16)
        info_bytes.extend(b"." * padding_len)

        path = self._gen_url_path(info_bytes)
        return f"https://e-cdns-proxy-{self.md5_origin[0]}.dzcdn.net/mobile/1/{path}"

    def _gen_url_path(self, data: dict) -> str:
        data_enc = AES.new("jo6aey6haid2Teih".encode(), AES.MODE_ECB).encrypt(data)
        return hexlify(data_enc).decode("utf-8")

    def best_quality(self) -> Optional[DeezerAudioQuality]:
        if not self.available_formats:
            return None
        return max(self.available_formats)


@dataclass
class DeezerArtist:
    id: str
    title: str
    image: Optional[str]

    @classmethod
    def from_gw_artist(cls: Type[DeezerArtist], artist: dict) -> DeezerArtist:
        artist_id = artist["ART_ID"]
        artist_title = artist["ART_NAME"]
        image_url = artist.get("ART_PICTURE")
        if image_url:
            image_url = DeezerAlbumFmt.format("user", image_url)
        return cls(
            id=artist_id,
            title=artist_title,
            image=image_url,
        )

    def to_json(self):
        return {
            "id": self.id,
            "title": self.title,
            "image": self.image,
        }


@dataclass
class DeezerAlbum:
    id: str
    name: str
    image: Optional[str]
    artists: List[DeezerArtist]
    tracks: List[DeezerTrack]

    @classmethod
    def from_gw_album(cls: Type[DeezerAlbum], album: dict) -> DeezerAlbum:
        album_id = album["ALB_ID"]
        album_name = album["ALB_TITLE"]
        image_url = album.get("ALB_PICTURE")
        if image_url:
            image_url = DeezerAlbumFmt.format("cover", image_url)
        artists = []
        for artist in album.get("ARTISTS", []):
            artists.append(DeezerArtist.from_gw_artist(artist))
        if not artists:
            artists.append(DeezerArtist.from_gw_artist(album))
        return cls(
            id=album_id,
            name=album_name,
            image=image_url,
            artists=artists,
            tracks=[],
        )

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "artists": self.artists,
            "tracks": self.tracks,
        }


@dataclass
class DeezerPlaylist:
    id: str
    name: str
    image: Optional[str]
    creator: Optional[str]
    tracks: List[DeezerTrack]

    @classmethod
    def from_gw_playlist(cls: Type[DeezerPlaylist], playlist: dict) -> DeezerPlaylist:
        playlist_data = playlist["DATA"]
        playlist_id = playlist_data["PLAYLIST_ID"]
        playlist_name = playlist_data["TITLE"]
        creator = playlist_data.get("PARENT_USERNAME")
        image_url = playlist_data.get("PLAYLIST_PICTURE")
        if image_url:
            image_url = DeezerAlbumFmt.format("playlist", image_url)

        tracks: List[DeezerTrack] = []
        for track in playlist.get("SONGS", {}).get("data", []):
            tracks.append(DeezerTrack.from_gw_track(track))

        return cls(
            id=playlist_id,
            name=playlist_name,
            image=image_url,
            creator=creator,
            tracks=tracks,
        )

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "creator": self.creator,
            "tracks": self.tracks,
        }
