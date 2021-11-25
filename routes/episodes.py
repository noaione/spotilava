import logging

import sanic
from sanic.response import HTTPResponse, StreamingHTTPResponse, json, stream, text

from internals.sanic import SpotilavaBlueprint, SpotilavaSanic
from internals.spotify import should_inject_metadata

logger = logging.getLogger("Routes.Episodes")

episodes_bp = SpotilavaBlueprint("spotify:episodes", url_prefix="/episode")


@episodes_bp.get("/<episode_id>")
async def get_episode_metadata(request: sanic.Request, episode_id: str) -> HTTPResponse:
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


@episodes_bp.get("/<episode_id>/listen")
async def get_episode_listen(request: sanic.Request, episode_id: str) -> HTTPResponse:
    app: SpotilavaSanic = request.app
    CHUNK_SIZE = app.chunk_size
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

    episode_info = await app.spotify.get_episode(episode_id)
    if episode_info is None:
        logger.warning(f"EpisodeListen: Unable to find episode <{episode_id}>")
        return text("Episode not found.", status=404)
    if episode_info.episode is None:
        logger.warning(f"EpisodeListen: Unable to find episode <{episode_id}>, track meta is missing")
        return text("Episode not found.", status=404)

    logger.debug(f"EpisodeListen: Reading first {CHUNK_SIZE} bytes of <{episode_id}>")
    first_data = await episode_info.read_bytes(CHUNK_SIZE)
    first_data, content_type, file_ext = should_inject_metadata(first_data, episode_info)

    # Streaming function
    async def episode_stream(response: StreamingHTTPResponse):
        await response.write(first_data)
        while episode_info.input_stream.available() > 0:
            data = await episode_info.read_bytes(CHUNK_SIZE)
            await response.write(data)

    content_length = len(first_data) + episode_info.input_stream.available()
    headers = {
        "Content-Length": str(content_length),
        "Content-Disposition": f'inline; filename="episode_{episode_id}{file_ext}"',
    }

    logger.info(f"EpisodeListen: Sending episode <{episode_id}>")
    # OGG vorbis stream
    return stream(
        episode_stream,
        status=200,
        content_type=content_type,
        headers=headers,
    )
