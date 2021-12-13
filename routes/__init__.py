"""
routes
~~~~~~~~~
The routes collection for Spotilava

:copyright: (c) 2021-present noaione
:license: MIT, see LICENSE for more details.
"""

# flake8: noqa

from .episodes import episodes_bp
from .meta import meta_bp
from .playlists import playlists_bp
from .tidal import *
from .tracks import tracks_bp
