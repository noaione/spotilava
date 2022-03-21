import logging
from io import BytesIO

import sanic
from sanic.response import HTTPResponse, StreamingHTTPResponse, json, stream, text

from internals.deezer import should_inject_metadata
from internals.sanic import SpotilavaBlueprint, SpotilavaSanic

logger = logging.getLogger("Routes.Deezer.Tracks")

deezer_tracks_bp = SpotilavaBlueprint("deezer:tracks", url_prefix="/deezer/")


@deezer_tracks_bp.get("/<track_id>")
async def get_track_metadata(request: sanic.Request, track_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    logger.info(f"TrackMeta: Received request for track <{track_id}>")
    if not app.deezer:
        logger.warning(f"TrackMeta: Unable to fetch <{track_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)
    if not app.deezer.ready:
        logger.warning(f"TrackListen: Unable to fetch <{track_id}> because Deezer is not ready yet!")
        return json({"error": "Deezer not connected.", "code": 500, "data": None}, status=500)
    if not track_id.isalnum():
        logger.warning(f"TrackMeta: Track <{track_id}> is invalid, expected alphanumeric, got {track_id} instead")
        return json({"error": "Invalid track id, must be alphanumerical", "code": 400, "data": None}, status=500)

    metadata = await app.deezer.get_track(track_id)
    if metadata is None:
        logger.warning(f"TrackMeta: Unable to find track <{track_id}>")
        return json({"error": "Track not found.", "code": 404, "data": None}, status=404)

    logger.info(f"TrackMeta: Sending track <{track_id}> metadata")
    return json({"error": "Success", "code": 200, "data": metadata.to_json()}, status=200, ensure_ascii=False)


@deezer_tracks_bp.get("/<track_id>/listen")
async def get_track_listen(request: sanic.Request, track_id: str):
    app: SpotilavaSanic = request.app
    CHUNK_SIZE = app.chunk_size
    logger.info(f"TrackListen: Received request for track <{track_id}>")
    if not app.deezer:
        logger.warning(f"TrackListen: Unable to fetch <{track_id}> because Deezer is not ready yet!")
        return text("Deezer not connected.", status=500)
    if not app.deezer.ready:
        logger.warning(f"TrackListen: Unable to fetch <{track_id}> because Deezer is not ready yet!")
        return text("Deezer not connected.", status=500)
    if not track_id.isalnum():
        logger.warning(f"TrackListen: Track <{track_id}> is invalid, expected alphanumeric, got {track_id} instead")
        return text("Invalid track id.", status=400)

    track = await app.deezer.get_track_stream(track_id)
    if track is None:
        logger.warning(f"TrackListen: Unable to find track <{track_id}>")
        return text("Track not found.", status=404)

    logger.debug(f"TrackListen: Reading first {CHUNK_SIZE} bytes of <{track_id}>")
    # Let's do a hack!
    # HACK: CHeck if it's not FLAC, after that download all chunks
    complete_data: BytesIO = None
    first_data: bytes = None
    if "flac" not in track.format.lower():
        # ALAC and Normal/Low hopefully are not memory consuming
        logger.info(f"TrackListen: Detected <{track_id}> as MP3 format!")
        read_whole = await track.read_all()
        read_whole, content_type, file_ext = should_inject_metadata(read_whole, track)
        complete_data = BytesIO(read_whole)
        complete_data.seek(0)
    else:
        logger.info(f"TrackListen: Detected <{track_id}> as FLAC format!")
        first_data = await track.read_bytes(CHUNK_SIZE)
        first_data, content_type, file_ext = should_inject_metadata(first_data, track)

    # Streaming function
    async def track_stream(response: StreamingHTTPResponse):
        if complete_data is not None:
            complete_data.seek(0)
            await response.write(complete_data.read())
        else:
            await response.write(first_data)
            while not track.empty():
                data = await track.read_bytes(CHUNK_SIZE)
                await response.write(data)

    headers = {
        "Content-Disposition": f'inline; filename="track_deezer_{track_id}{file_ext}"',
    }
    if complete_data is not None:
        headers["Content-Length"] = len(complete_data.getvalue())
    else:
        headers["Content-Type"] = len(first_data) + track.available()

    logger.info(f"TrackListen: Sending track <{track_id}>")
    # OGG vorbis stream
    return stream(
        track_stream,
        status=200,
        content_type=content_type,
        headers=headers,
    )