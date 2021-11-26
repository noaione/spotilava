from typing import ClassVar, Optional

from sanic import Sanic
from sanic.blueprints import Blueprint

from .spotify import LIBRESpotifyWrapper
from .tidal import TidalAPI


class SpotilavaSanic(Sanic):
    spotify: ClassVar[Optional[LIBRESpotifyWrapper]]
    tidal: ClassVar[Optional[TidalAPI]]
    chunk_size: ClassVar[int] = 4096

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spotify = None
        self.tidal = None


class SpotilavaBlueprint(Blueprint):
    @property
    def app(self) -> SpotilavaSanic:
        apps = self._apps
        return apps[0]
