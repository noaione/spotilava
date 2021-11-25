import logging

import sanic
from sanic.response import HTTPResponse, json

from internals.sanic import SpotilavaBlueprint, SpotilavaSanic

logger = logging.getLogger("Spotify.Playlists")

playlists_bp = SpotilavaBlueprint("spotify:playlists", url_prefix="/")


@playlists_bp.get("/album/<album_id>")
async def get_album_contents(request: sanic.Request, album_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"AlbumContents: Received request for album <{album_id}>")
    if not app.spotify:
        logger.warning(f"AlbumContents: Unable to fetch <{album_id}> because Spotify is not ready yet!")
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(album_id) != 22:
        logger.warning(f"AlbumContents: Album <{album_id}> is invalid, expected 22 length, got {len(album_id)} instead")
        return json(
            {
                "error": f"Invalid album id, expected 22 char length, got {len(album_id)} instead",
                "code": 400,
                "data": None,
            },
            status=500,
        )
    if not album_id.isalnum():
        logger.warning(f"AlbumContents: Album <{album_id}> is invalid, expected alphanumeric, got {album_id} instead")
        return json({"error": "Invalid album id, must be alphanumerical", "code": 400, "data": None}, status=500)

    album_info = await app.spotify.get_album(album_id)
    if album_info is None:
        logger.warning(f"AlbumContents: Unable to find album <{album_id}>")
        return json({"error": "Album not found.", "code": 404, "data": None}, status=404)

    album_meta = album_info.to_json()
    return json({"error": "Success", "code": 200, "data": album_meta})


@playlists_bp.get("/playlist/<playlist_id>")
async def get_playlist_contents(request: sanic.Request, playlist_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"PlaylistContents: Received request for playlist <{playlist_id}>")
    if not app.spotify:
        logger.warning(f"PlaylistContents: Unable to fetch <{playlist_id}> because Spotify is not ready yet!")
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(playlist_id) != 22:
        logger.warning(
            f"PlaylistContents: Playlist <{playlist_id}> is invalid, expected 22 length, got {len(playlist_id)} instead"
        )
        return json(
            {
                "error": f"Invalid playlist id, expected 22 char length, got {len(playlist_id)} instead",
                "code": 400,
                "data": None,
            },
            status=500,
        )
    if not playlist_id.isalnum():
        logger.warning(
            f"PlaylistContents: Playlist <{playlist_id}> is invalid, expected alphanumeric, got {playlist_id} instead"
        )
        return json({"error": "Invalid playlist id, must be alphanumerical", "code": 400, "data": None}, status=500)

    playlist_info = await app.spotify.get_playlist(playlist_id)
    if playlist_info is None:
        logger.warning(f"PlaylistContents: Unable to find playlist <{playlist_id}>")
        return json({"error": "Playlist not found.", "code": 404, "data": None}, status=404)

    playlist_meta = playlist_info.to_json()
    return json({"error": "Success", "code": 200, "data": playlist_meta})


@playlists_bp.get("/show/<show_id>")
async def get_show_information(request: sanic.Request, show_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"ShowInfo: Received request for show <{show_id}>")
    if not app.spotify:
        logger.warning(f"ShowInfo: Unable to fetch <{show_id}> because Spotify is not ready yet!")
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(show_id) != 22:
        logger.warning(f"ShowInfo: Show <{show_id}> is invalid, expected 22 length, got {len(show_id)} instead")
        return json(
            {
                "error": f"Invalid show id, expected 22 char length, got {len(show_id)} instead",
                "code": 400,
                "data": None,
            },
            status=500,
        )
    if not show_id.isalnum():
        logger.warning(f"ShowInfo: Show <{show_id}> is invalid, expected alphanumeric, got {show_id} instead")
        return json({"error": "Invalid show id, must be alphanumerical", "code": 400, "data": None}, status=500)

    show_info = await app.spotify.get_show(show_id)
    if show_info is None:
        logger.warning(f"ShowInfo: Unable to find show <{show_id}>")
        return json({"error": "Show not found.", "code": 404, "data": None}, status=404)

    show_data = show_info.to_json()
    return json({"error": "Success", "code": 200, "data": show_data})
