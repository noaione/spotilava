import logging
import re

import sanic
from sanic.response import HTTPResponse, json, raw, text

from internals.sanic import SpotilavaBlueprint, SpotilavaSanic, stream_response
from internals.spotify import should_inject_metadata

from ._utils import get_spotify_audio_format, get_spotify_audio_quality

logger = logging.getLogger("Routes.Episodes")

episodes_bp = SpotilavaBlueprint("spotify-episodes", url_prefix="/episode")


@episodes_bp.get("/<episode_id>")
async def get_episode_metadata(request: sanic.Request, episode_id: str):
    app: SpotilavaSanic = request.app
    logger.info(f"EpisodeMeta: Received request for episode <{episode_id}>")
    if not app.spotify:
        logger.warning(f"EpisodeMeta: Unable to fetch <{episode_id}> because Spotify is not ready yet!")
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(episode_id) != 22:
        logger.warning(
            f"EpisodeMeta: Episode <{episode_id}> is invalid, expected 22 length, got {len(episode_id)} instead"
        )
        return json(
            {
                "error": f"Invalid episode id, expected 22 char length, got {len(episode_id)} instead",
                "code": 400,
                "data": None,
            },
            status=500,
        )
    if not episode_id.isalnum():
        logger.warning(
            f"EpisodeMeta: Episode <{episode_id}> is invalid, expected alphanumeric, got {episode_id} instead"
        )
        return json({"error": "Invalid episode id, must be alphanumerical", "code": 400, "data": None}, status=500)

    metadata = await app.spotify.get_episode_metadata(episode_id)
    if metadata is None:
        logger.warning(f"EpisodeMeta: Unable to find episode <{episode_id}>")
        return json({"error": "Episode not found.", "code": 404, "data": None}, status=404)

    logger.info(f"EpisodeMeta: Sending episode <{episode_id}> metadata")
    return json({"error": "Success", "code": 200, "data": metadata.to_json()}, status=200, ensure_ascii=False)


@episodes_bp.route("/<episode_id>/listen", methods=["GET", "HEAD"])
async def get_episode_listen(request: sanic.Request, episode_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    CHUNK_SIZE = app.chunk_size
    meth = request.method.lower()
    logger.info(f"EpisodeListen: Received request for episode <{episode_id}>")
    if not app.spotify:
        logger.warning(f"EpisodeListen: Unable to fetch <{episode_id}> because Spotify is not ready yet!")
        return text("Spotify not connected.", status=500)
    if len(episode_id) != 22:
        logger.warning(
            f"EpisodeListen: Episode <{episode_id}> is invalid, expected 22 length, got {len(episode_id)} instead"
        )
        return text("Invalid episode id.", status=400)
    if not episode_id.isalnum():
        logger.warning(
            f"EpisodeListen: Episode <{episode_id}> is invalid, expected alphanumeric, got {episode_id} instead"
        )
        return text("Invalid episode id.", status=400)

    force_format = get_spotify_audio_format(request)
    force_quality = get_spotify_audio_quality(request)
    episode_info = await app.spotify.get_episode(episode_id, force_format, force_quality)
    if episode_info is None:
        logger.warning(f"EpisodeListen: Unable to find episode <{episode_id}>")
        if meth == "head":
            return raw(b"", status=404)
        return text("Episode not found.", status=404)
    if episode_info.episode is None:
        logger.warning(f"EpisodeListen: Unable to find episode <{episode_id}>, track meta is missing")
        if meth == "head":
            return raw(b"", status=404)
        return text("Episode not found.", status=404)

    header_range = request.headers.get("Range") or request.headers.get("range")
    start_read = 0
    end_read = -1
    if header_range is not None:
        range_search = re.search(r"^bytes\=(?P<start>[0-9]+?)-(?P<end>[0-9]+?)?$", header_range)
        if range_search is not None:
            start_read = int(range_search.group("start"))
            end_read = range_search.group("end")
            if end_read is not None:
                end_read = int(end_read)

    logger.debug(f"EpisodeListen: Reading first {CHUNK_SIZE} bytes of <{episode_id}>")
    first_data = await episode_info.read_bytes(CHUNK_SIZE)
    first_data, content_type, file_ext = should_inject_metadata(first_data, episode_info)
    # Opus silence frame
    extra_frame = b"\xF8\xFF\xFE"

    content_length = len(first_data) + episode_info.input_stream.available()
    if "ogg" in file_ext:
        content_length += len(extra_frame)

    if meth == "head":
        logger.info(f"EpisodeListen(HEAD): Sending track <{episode_id}> metadata")
        # Response to a HEAD request with some header metadata
        return raw(
            b"",
            headers={
                "Accept": f"{content_type}, application/octet-stream;q=0.9",
                "Accept-Ranges": "bytes",
                "Content-Type": content_type,
                "Content-Length": str(content_length),
            },
            status=200,
        )

    should_check_bytes = True
    if end_read == -1:
        should_check_bytes = False
        end_read = content_length or -1

    if start_read >= end_read and should_check_bytes:
        logger.warning(f"EpisodeListen: Sending empty track <{episode_id}> since range is invalid")
        return raw(
            b"",
            status=206,
            headers={"Content-Range": f"bytes {start_read}-{start_read}/{content_length}"},
            content_type="audio/ogg",
        )

    headers = {
        "Content-Length": str(content_length),
        "Content-Disposition": f'inline; filename="episode_{episode_id}{file_ext}"',
    }
    if header_range is not None:
        headers["Content-Range"] = f"bytes {start_read}-{end_read}/{content_length}"
        headers["Accept-Ranges"] = "bytes"
        headers["Content-Length"] = str(end_read - start_read)

    # Streaming function
    async def episode_stream(response: HTTPResponse):
        maximum_read = episode_info.input_stream.available()
        logger.info(f"EpisodeListen: Streaming track <{episode_id}> with bytes {start_read}-{end_read}")
        if start_read == 0:
            await response.send(first_data)
        else:
            # Seek to target start
            logger.debug(f"EpisodeListen: Seeking to bytes {start_read} in <{episode_id}>")
            await episode_info.seek_to(start_read)
            maximum_read = end_read - start_read
        while episode_info.input_stream.available() > 0:
            THIS_MUCH = CHUNK_SIZE
            if THIS_MUCH > maximum_read and should_check_bytes:
                THIS_MUCH = maximum_read
            data = await episode_info.read_bytes(THIS_MUCH)
            maximum_read -= len(data)
            await response.send(data)
        # Pad with silence frame if it's ogg
        if "ogg" in file_ext:
            await response.send(extra_frame)
        try:
            await episode_info.close()
        except Exception as e:
            logger.error(f"EpisodeListen: Error closing track <{episode_id}>", exc_info=e)

    logger.info(f"EpisodeListen: Sending episode <{episode_id}>")
    # Stream track to client
    return await stream_response(request, episode_stream, status=200, content_type=content_type, headers=headers)
