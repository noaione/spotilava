import logging

import sanic
from sanic.response import HTTPResponse, json

from internals.sanic import SpotilavaBlueprint, SpotilavaSanic

logger = logging.getLogger("Spotify.Meta")

meta_bp = SpotilavaBlueprint("spotify:meta", url_prefix="/meta")


@meta_bp.get("/region")
async def get_meta_region_code(request: sanic.Request) -> HTTPResponse:
    """
    Get the region code for the current user.
    """
    app: SpotilavaSanic = request.app
    logger.info("SpotiMeta: Received request to fetch country code of the account")
    if not app.spotify:
        logger.warning("SpotiMeta: Unable to fetch country code because Spotify is not ready yet!")
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)

    cc_code = app.spotify.session.country
    return json({"code": 200, "data": cc_code, "error": "Success"})
