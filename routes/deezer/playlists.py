import logging

import sanic
from sanic.response import HTTPResponse, json

from internals.sanic import SpotilavaBlueprint, SpotilavaSanic

logger = logging.getLogger("Deezer.Playlists")

deezer_playlists_bp = SpotilavaBlueprint("deezer:playlists", url_prefix="/deezer/")


@deezer_playlists_bp.get("/album/<album_id>")
async def get_album_contents(request: sanic.Request, album_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"AlbumContents: Received request for album <{album_id}>")
    if not app.deezer:
        logger.warning(f"AlbumContents: Unable to fetch <{album_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)
    if not app.deezer.ready:
        logger.warning(f"AlbumContents: Unable to fetch <{album_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)
    if not album_id.isalnum():
        logger.warning(f"AlbumContents: Album <{album_id}> is invalid, expected alphanumeric, got {album_id} instead")
        return json({"error": "Invalid album id, must be alphanumerical", "code": 400, "data": None}, status=500)

    album_info = await app.deezer.get_album(album_id)
    if album_info is None:
        logger.warning(f"AlbumContents: Unable to find album <{album_id}>")
        return json({"error": "Album not found.", "code": 404, "data": None}, status=404)

    album_meta = album_info.to_json()
    return json({"error": "Success", "code": 200, "data": album_meta})


@deezer_playlists_bp.get("/playlist/<playlist_id>")
async def get_playlist_contents(request: sanic.Request, playlist_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"PlaylistContents: Received request for playlist <{playlist_id}>")
    if not app.deezer:
        logger.warning(f"PlaylistContents: Unable to fetch <{playlist_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)
    if not app.deezer.ready:
        logger.warning(f"PlaylistContents: Unable to fetch <{playlist_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)

    playlist_info = await app.deezer.get_playlist(playlist_id)
    if playlist_info is None:
        logger.warning(f"PlaylistContents: Unable to find playlist <{playlist_id}>")
        return json({"error": "Playlist not found.", "code": 404, "data": None}, status=404)

    playlist_meta = playlist_info.to_json()
    return json({"error": "Success", "code": 200, "data": playlist_meta})


@deezer_playlists_bp.get("/artist/<artist_id>")
async def get_artist_top_tracks_contents(request: sanic.Request, artist_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"ArtistContents: Received request for artist <{artist_id}>")
    if not app.deezer:
        logger.warning(f"ArtistContents: Unable to fetch <{artist_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)
    if not app.deezer.ready:
        logger.warning(f"ArtistContents: Unable to fetch <{artist_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)

    playlist_info = await app.deezer.get_artist_top_tracks(artist_id)
    if playlist_info is None:
        logger.warning(f"ArtistContents: Unable to find artist <{artist_id}>")
        return json({"error": "Artist not found.", "code": 404, "data": None}, status=404)

    playlist_data = []
    for track in playlist_info:
        playlist_data.append(track.to_json())
    return json({"error": "Success", "code": 200, "data": playlist_data})
