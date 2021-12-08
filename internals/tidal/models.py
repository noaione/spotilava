from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Type

from .enums import TidalAudioQuality

__all__ = ("TidalTrack", "TidalArtist", "TidalAlbum", "TidalPlaylist", "TidalUser")


@dataclass
class TidalUser:
    id: str
    cc: str
    token: str
    refresh: str
    # Unix timestamp
    expires_at: int

    def to_dict(self):
        return {
            "id": self.id,
            "cc": self.cc,
            "token": self.token,
            "refresh": self.refresh,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls: Type[TidalUser], data: dict) -> TidalUser:
        return cls(
            id=data["id"], cc=data["cc"], token=data["token"], refresh=data["refresh"], expires_at=data["expires_at"]
        )


@dataclass
class TidalTrack:
    id: str
    title: str
    album: Optional[str]
    image: Optional[str]
    artists: List[str]
    duration: int
    audio_quality: Optional[TidalAudioQuality]

    @classmethod
    def from_track(cls: Type[TidalTrack], track: dict) -> TidalTrack:
        album_name = track.get("album", {}).get("title", None)
        image = track.get("album", {}).get("cover", None)
        if image is not None:
            image = image.replace("-", "/")
            image = f"https://resources.tidal.com/images/{image}/1280x1280.jpg"

        artists = []
        for artist in track.get("artists", []):
            artists.append(artist["name"])
        if not artists:
            artists = [track["artist"]["name"]]
        duration = track.get("duration", -1)
        audio_quality = track.get("audioQuality", None)
        if audio_quality is not None:
            audio_quality = TidalAudioQuality(audio_quality)

        return cls(
            id=str(track["id"]),
            title=track["title"],
            album=album_name,
            image=image,
            artists=artists,
            duration=duration,
            audio_quality=audio_quality,
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
class TidalArtist:
    id: str
    name: str
    image: Optional[str]

    @classmethod
    def from_artist(cls: Type[TidalArtist], artist: dict) -> TidalArtist:
        picture = artist.get("picture", None)
        if picture is not None:
            picture = picture.replace("-", "/")
            picture = f"https://resources.tidal.com/images/{picture}/1280x1280.jpg"

        return cls(id=str(artist["id"]), name=artist["name"], image=picture)

    def to_json(self):
        return {"id": self.id, "name": self.name, "image": self.image}


@dataclass
class TidalAlbum:
    id: str
    name: str
    image: Optional[str]
    artists: List[TidalArtist]
    tracks: List[TidalTrack]

    @classmethod
    def from_album(cls: Type[TidalAlbum], album: dict) -> TidalAlbum:
        image = album.get("cover", None)
        if image is not None:
            image = image.replace("-", "/")
            image = f"https://resources.tidal.com/images/{image}/1280x1280.jpg"

        artists: List[TidalArtist] = []
        for artist in album.get("artists", []):
            artists.append(TidalArtist.from_artist(artist))
        if not artists:
            artists = [TidalArtist.from_artist(album["artist"])]

        return cls(id=str(album["id"]), name=album["title"], image=image, artists=artists, tracks=[])

    def to_json(self):
        tracks = []
        for track in self.tracks:
            tracks.append(track.to_json())
        artists = []
        for artist in self.artists:
            artists.append(artist.to_json())
        return {"id": self.id, "name": self.name, "image": self.image, "artists": artists, "tracks": tracks}


@dataclass
class TidalPlaylist:
    id: str
    name: str
    image: Optional[str]
    creator: Optional[str]
    tracks: List[TidalTrack]

    @classmethod
    def from_playlist(cls: Type[TidalPlaylist], playlist: dict) -> TidalPlaylist:
        image = playlist.get("image", None) or playlist.get("squareImage", None) or playlist.get("cover", None)
        if image is not None:
            image = image.replace("-", "/")
            image = f"https://resources.tidal.com/images/{image}/1280x1280.jpg"
        creator = playlist.get("creator", {}).get("name", None)
        if creator is None:
            creator_id = playlist.get("creator", {}).get("id", None)
            if creator_id == 0:
                creator = "TIDAL"

        return cls(id=str(playlist["uuid"]), name=playlist["title"], image=image, creator=creator, tracks=[])

    def to_json(self):
        tracks = []
        for track in self.tracks:
            tracks.append(track.to_json())
        return {"id": self.id, "name": self.name, "image": self.image, "creator": self.creator, "tracks": tracks}
