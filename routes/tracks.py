import logging

import sanic
from sanic.response import HTTPResponse, StreamingHTTPResponse, json, stream, text

from internals.sanic import SpotilavaBlueprint, SpotilavaSanic
from internals.spotify import should_inject_metadata

logger = logging.getLogger("Routes.Tracks")

tracks_bp = SpotilavaBlueprint("spotify:tracks", url_prefix="/")


@tracks_bp.get("/<track_id>")
async def get_track_metadata(request: sanic.Request, track_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"TrackMeta: Received request for track <{track_id}>")
    if not app.spotify:
        logger.warning(f"TrackMeta: Unable to fetch <{track_id}> because Spotify is not ready yet!")
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(track_id) != 22:
        logger.warning(f"TrackMeta: Track <{track_id}> is invalid, expected 22 length, got {len(track_id)} instead")
        return json(
            {
                "error": f"Invalid track id, expected 22 char length, got {len(track_id)} instead",
                "code": 400,
                "data": None,
            },
            status=500,
        )
    if not track_id.isalnum():
        logger.warning(f"TrackMeta: Track <{track_id}> is invalid, expected alphanumeric, got {track_id} instead")
        return json({"error": "Invalid track id, must be alphanumerical", "code": 400, "data": None}, status=500)

    metadata = await app.spotify.get_track_metadata(track_id)
    if metadata is None:
        logger.warning(f"TrackMeta: Unable to find track <{track_id}>")
        return json({"error": "Track not found.", "code": 404, "data": None}, status=404)

    logger.info(f"TrackMeta: Sending track <{track_id}> metadata")
    return json({"error": "Success", "code": 200, "data": metadata.to_json()}, status=200, ensure_ascii=False)


@tracks_bp.get("/<track_id>/listen")
async def get_track_listen(request: sanic.Request, track_id: str):
    app: SpotilavaSanic = request.app
    CHUNK_SIZE = app.chunk_size
    logger.info(f"TrackListen: Received request for track <{track_id}>")
    if not app.spotify:
        logger.warning(f"TrackListen: Unable to fetch <{track_id}> because Spotify is not ready yet!")
        return text("Spotify not connected.", status=500)
    if len(track_id) != 22:
        logger.warning(f"TrackListen: Track <{track_id}> is invalid, expected 22 length, got {len(track_id)} instead")
        return text("Invalid track id.", status=400)
    if not track_id.isalnum():
        logger.warning(f"TrackListen: Track <{track_id}> is invalid, expected alphanumeric, got {track_id} instead")
        return text("Invalid track id.", status=400)

    find_track = await app.spotify.get_track(track_id)
    if find_track is None:
        logger.warning(f"TrackListen: Unable to find track <{track_id}>")
        return text("Track not found.", status=404)
    if find_track.track is None:
        logger.warning(f"TrackListen: Unable to find track <{track_id}>, track meta is missing")
        return text("Track not found.", status=404)

    logger.debug(f"TrackListen: Reading first {CHUNK_SIZE} bytes of <{track_id}>")
    first_data = await find_track.read_bytes(CHUNK_SIZE)
    first_data, content_type, file_ext = should_inject_metadata(first_data, find_track)
    # Opus silence frame
    extra_frame = b"\xF8\xFF\xFE"

    # Streaming function
    async def track_stream(response: StreamingHTTPResponse):
        await response.write(first_data)
        while find_track.input_stream.available() > 0:
            data = await find_track.read_bytes(CHUNK_SIZE)
            await response.write(data)
        # Pad with silence frame if it's ogg
        if "ogg" in file_ext:
            await response.write(extra_frame)

    content_length = len(first_data) + find_track.input_stream.available()
    if "ogg" in file_ext:
        content_length += len(extra_frame)

    headers = {
        "Content-Length": str(content_length),
        "Content-Disposition": f'inline; filename="track_{track_id}{file_ext}"',
    }

    logger.info(f"TrackListen: Sending track <{track_id}>")
    # OGG vorbis stream
    return stream(
        track_stream,
        status=200,
        content_type=content_type,
        headers=headers,
    )
