from types import SimpleNamespace
from typing import Optional

from sanic import Sanic
from sanic.blueprints import Blueprint

from .spotify import LIBRESpotifyWrapper
from .tidal import TidalAPI


class SpotilavaContext(SimpleNamespace):
    """
    A context object that is used to pass data between different parts of the
    application.
    """

    spotify: Optional[LIBRESpotifyWrapper] = None
    tidal: Optional[TidalAPI] = None
    chunk_size: int = 4096


class SpotilavaSanic(Sanic):
    ctx: SpotilavaContext

    def __init__(self, *args, **kwargs):
        super().__init__(ctx=SpotilavaContext(), *args, **kwargs)

    @property
    def spotify(self):
        return self.ctx.spotify

    @spotify.setter
    def spotify(self, value: LIBRESpotifyWrapper):
        self.ctx.spotify = value

    @property
    def tidal(self):
        return self.ctx.tidal

    @tidal.setter
    def tidal(self, value: TidalAPI):
        self.ctx.tidal = value

    @property
    def chunk_size(self):
        return self.ctx.chunk_size

    @chunk_size.setter
    def chunk_size(self, value: int):
        self.ctx.chunk_size = value


class SpotilavaBlueprint(Blueprint):
    @property
    def app(self) -> SpotilavaSanic:
        apps = self._apps
        return apps[0]
