import logging

import sanic
from sanic.response import HTTPResponse, json

from internals.sanic import SpotilavaBlueprint, SpotilavaSanic

logger = logging.getLogger("Tidal.Playlists")

tidal_playlists_bp = SpotilavaBlueprint("tidal-playlists", url_prefix="/tidal/")


@tidal_playlists_bp.get("/album/<album_id>")
async def get_album_contents(request: sanic.Request, album_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"AlbumContents: Received request for album <{album_id}>")
    if not app.tidal:
        logger.warning(f"AlbumContents: Unable to fetch <{album_id}> because Tidal is not ready yet!")
        return json({"error": "Tidal not connected.", "code": 500, "data": None}, status=500)
    if not app.tidal.ready:
        logger.warning(f"AlbumContents: Unable to fetch <{album_id}> because Tidal is not ready yet!")
        return json({"error": "Tidal not connected.", "code": 500, "data": None}, status=500)
    if not album_id.isalnum():
        logger.warning(f"AlbumContents: Album <{album_id}> is invalid, expected alphanumeric, got {album_id} instead")
        return json({"error": "Invalid album id, must be alphanumerical", "code": 400, "data": None}, status=500)

    album_info = await app.tidal.get_album(album_id)
    if album_info is None:
        logger.warning(f"AlbumContents: Unable to find album <{album_id}>")
        return json({"error": "Album not found.", "code": 404, "data": None}, status=404)

    album_meta = album_info.to_json()
    return json({"error": "Success", "code": 200, "data": album_meta})


@tidal_playlists_bp.get("/playlist/<playlist_id>")
async def get_playlist_contents(request: sanic.Request, playlist_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"PlaylistContents: Received request for album <{playlist_id}>")
    if not app.tidal:
        logger.warning(f"PlaylistContents: Unable to fetch <{playlist_id}> because Tidal is not ready yet!")
        return json({"error": "Tidal not connected.", "code": 500, "data": None}, status=500)
    if not app.tidal.ready:
        logger.warning(f"PlaylistContents: Unable to fetch <{playlist_id}> because Tidal is not ready yet!")
        return json({"error": "Tidal not connected.", "code": 500, "data": None}, status=500)

    playlist_info = await app.tidal.get_playlists(playlist_id)
    if playlist_info is None:
        logger.warning(f"PlaylistContents: Unable to find album <{playlist_id}>")
        return json({"error": "Album not found.", "code": 404, "data": None}, status=404)

    playlist_meta = playlist_info.to_json()
    return json({"error": "Success", "code": 200, "data": playlist_meta})
