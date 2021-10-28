from typing import ClassVar, Optional

from sanic import Sanic

from .spotify import LIBRESpotifyWrapper


class SpotilavaSanic(Sanic):
    spotify: ClassVar[Optional[LIBRESpotifyWrapper]]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.spotify = None
