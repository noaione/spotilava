from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import List, Optional, Type

from internals.utils import complex_walk

__all__ = (
    "SpotifyTrack",
    "SpotifyArtist",
    "SpotifyAlbum",
    "SpotifyPlaylist",
    "SpotifyEpisode",
    "SpotifyShow",
    "SpotifyArtistWithTrack",
)


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
class SpotifyArtistWithTrack(SpotifyArtist):
    tracks: List[SpotifyTrack] = field(default_factory=list)

    @classmethod
    def from_artist(cls: Type[SpotifyArtistWithTrack], artist: dict) -> SpotifyArtistWithTrack:
        return super().from_artist(artist)

    def to_json(self):
        base = super().to_json()
        base["tracks"] = [track.to_json() for track in self.tracks]
        return base


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


@dataclass
class SpotifyEpisode:
    id: str
    title: str
    description: str
    show: str
    image: Optional[str]
    publisher: str
    duration: Optional[int] = None

    @classmethod
    def from_episode(cls: Type[SpotifyEpisode], episode: dict, parent_show: Optional[dict] = {}) -> SpotifyEpisode:
        show_name = complex_walk(episode, "show.name") or complex_walk(parent_show, "name")
        show_art = complex_walk(episode, "images.0.url")

        publisher = complex_walk(episode, "show.publisher") or complex_walk(parent_show, "publisher")
        duration = int(ceil(episode.get("duration_ms", 0) / 1000))
        description = complex_walk(episode, "description")
        return cls(
            id=episode["id"],
            title=episode["name"],
            description=description,
            show=show_name,
            image=show_art,
            publisher=publisher,
            duration=duration,
        )

    def to_json(self):
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "show": self.show,
            "image": self.image,
            "publisher": self.publisher,
            "duration": self.duration,
        }


@dataclass
class SpotifyShow:
    id: str
    name: str
    image: str
    episodes: List[SpotifyEpisode]

    @classmethod
    def from_show(cls: Type[SpotifyShow], show: dict) -> SpotifyShow:
        image = complex_walk(show, "images.0.url")
        episodes_set = complex_walk(show, "episodes.items") or []
        yoinked_data = {
            "name": show["name"],
            "publisher": complex_walk(show, "publisher"),
        }
        episodes = [SpotifyEpisode.from_episode(episode, yoinked_data) for episode in episodes_set]
        return cls(
            id=show["id"],
            name=show["name"],
            image=image,
            episodes=episodes,
        )

    def to_json(self):
        return {
            "id": self.id,
            "name": self.name,
            "image": self.image,
            "episodes": [episode.to_json() for episode in self.episodes],
        }
