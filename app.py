import asyncio
import logging
import os
import sys
from io import BytesIO
from pathlib import Path

import coloredlogs
import sanic
from dotenv import load_dotenv
from mutagen.oggvorbis import OggVorbis
from sanic.response import (HTTPResponse, StreamingHTTPResponse, json, stream,
                            text)

from internals.logger import RollingFileHandler
from internals.sanic import SpotilavaSanic
from internals.spotify import LIBRESpotifyWrapper

CURRENT_PATH = Path(__file__).parent
log_path = CURRENT_PATH / "logs"
log_path.mkdir(exist_ok=True)
load_dotenv(str(CURRENT_PATH / ".env"))

file_handler = RollingFileHandler(
    log_path / "spotilava.log",
    maxBytes=5_242_880,
    backupCount=5,
    encoding="utf-8"
)
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[file_handler],
    format="[%(asctime)s] - (%(name)s)[%(levelname)s](%(funcName)s): %(message)s",  # noqa: E501
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger()
coloredlogs.install(
    fmt="[%(asctime)s %(hostname)s][%(levelname)s] (%(name)s[%(process)d]): %(funcName)s: %(message)s",
    level=logging.INFO,
    logger=logger,
    stream=sys.stdout,
)


async def connect_spotify(app: SpotilavaSanic):
    """
    Connect to spotify and return the wrapper.
    """
    if app.spotify is not None:
        return
    username = os.getenv("SPOTILAVA_USERNAME", "").strip()
    password = os.getenv("SPOTILAVA_PASSWORD", "").strip()
    if not username or not password:
        logger.error("Username or password not set.")
        sys.exit(69)
    logger.info("App: Creating spotify wrapper...")
    spotify = LIBRESpotifyWrapper(username, password, loop=app.loop)
    try:
        await spotify.create()
    except Exception as e:
        logger.error(f"App: Failed to create spotify wrapper: {e}", exc_info=e)
        sys.exit(69)
    app.spotify = spotify


logger.info("App: Initiating spotilava webserver...")
loop = asyncio.get_event_loop()
app = SpotilavaSanic("Spotilava")
try:
    CHUNK_SIZE = int(os.getenv("SPOTILAVA_CHUNK_SIZE", "4096"))
except Exception:
    CHUNK_SIZE = 4096

app.add_task(connect_spotify)

# For metadata tagging purpose
if CHUNK_SIZE < 4096:
    raise ValueError("Chunk size must be at least 4096 (Metadata purpose).")
if CHUNK_SIZE % 8 != 0:
    raise ValueError("Chunk size must be a multiple of 8.")


@app.get("/")
async def index(request: sanic.Request) -> HTTPResponse:
    return text("</>")


@app.get("/<track_id>")
async def get_track_metadata(request: sanic.Request, track_id: str) -> HTTPResponse:
    logger.info(f"TrackMeta: Received request for track <{track_id}>")
    if not app.spotify:
        logger.warning(
            f"TrackMeta: Unable to fetch <{track_id}> because Spotify is not ready yet!"
        )
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(track_id) != 22:
        logger.warning(
            f"TrackMeta: Track <{track_id}> is invalid, expected 22 length, got {len(track_id)} instead"
        )
        return json(
            {
                "error": f"Invalid track id, expected 22 char length, got {len(track_id)} instead",
                "code": 400,
                "data": None
            },
            status=500
        )
    if not track_id.isalnum():
        logger.warning(
            f"TrackMeta: Track <{track_id}> is invalid, expected alphanumeric, got {track_id} instead"
        )
        return json(
            {
                "error": "Invalid track id, must be alphanumerical",
                "code": 400,
                "data": None
            },
            status=500
        )

    metadata = await app.spotify.get_track(track_id)
    if metadata is None:
        logger.warning(f"TrackMeta: Unable to find track <{track_id}>")
        return json({"error": "Track not found.", "code": 404, "data": None}, status=404)
    if metadata.track is None:
        logger.warning(f"TrackListen: Unable to find track <{track_id}>, track meta is missing")
        return json({"error": "Track not found, possibly not a track?", "code": 404, "data": None}, status=404)

    track_meta = metadata.track
    metadata = {
        "id": track_id,
        "title": track_meta.name,
        "album": track_meta.album.name,
        "duration": track_meta.duration,
    }

    artists = []
    for artist in track_meta.artist:
        artists.append(artist.name)
    metadata["artists"] = artists

    logger.info(f"TrackMeta: Sending track <{track_id}> metadata")
    return json({"error": "Success", "code": 200, "data": metadata}, status=200, ensure_ascii=False)


@app.get("/<track_id>/listen")
async def get_track_listen(request: sanic.Request, track_id: str):
    logger.info(f"TrackListen: Received request for track <{track_id}>")
    if not app.spotify:
        logger.warning(
            f"TrackListen: Unable to fetch <{track_id}> because Spotify is not ready yet!"
        )
        return text("Spotify not connected.", status=500)
    if len(track_id) != 22:
        logger.warning(
            f"TrackListen: Track <{track_id}> is invalid, expected 22 length, got {len(track_id)} instead"
        )
        return text("Invalid track id.", status=400)
    if not track_id.isalnum():
        logger.warning(
            f"TrackMeta: Track <{track_id}> is invalid, expected alphanumeric, got {track_id} instead"
        )
        return text("Invalid track id.", status=400)

    find_track = await app.spotify.get_track(track_id)
    if find_track is None:
        logger.warning(f"TrackListen: Unable to find track <{track_id}>")
        return text("Track not found.", status=404)
    if find_track.track is None:
        logger.warning(f"TrackListen: Unable to find track <{track_id}>, track meta is missing")
        return text("Track not found.", status=404)

    track_meta = find_track.track

    def inject_ogg_metadata(bita: bytes) -> bytes:
        logger.debug(f"TrackListen: Trying to inject metadata for track <{track_id}>")
        io_bita = BytesIO(bita)
        io_bita.seek(0)
        ogg_metadata = OggVorbis(io_bita)
        ogg_metadata["TITLE"] = track_meta.name
        ogg_metadata["ALBUM"] = track_meta.album.name
        artists_list = []
        for artist in track_meta.artist:
            artists_list.append(artist.name)
        ogg_metadata["ARTIST"] = artists_list
        ogg_metadata.save(io_bita)
        io_bita.seek(0)
        return io_bita.read()

    logger.debug(f"TrackListen: Reading first {CHUNK_SIZE} bytes of <{track_id}>")
    first_data = await find_track.read_bytes(CHUNK_SIZE)
    first_data = inject_ogg_metadata(first_data)

    # Streaming function
    async def track_stream(response: StreamingHTTPResponse):
        await response.write(first_data)
        while find_track.input_stream.available() > 0:
            data = await find_track.read_bytes(CHUNK_SIZE)
            await response.write(data)

    content_length = len(first_data) + find_track.input_stream.available()

    headers = {
        "Content-Length": str(content_length),
        "Content-Disposition": f"inline; filename=\"{track_id}.ogg\""
    }

    logger.info(f"TrackListen: Sending track <{track_id}>")

    # OGG vorbis stream
    return stream(
        track_stream,
        status=200,
        content_type="audio/ogg",
        headers=headers,
    )


@app.get("/album/<album_id>")
async def get_album_contents(request: sanic.Request, album_id: str) -> HTTPResponse:
    logger.info(f"AlbumContents: Received request for album <{album_id}>")
    if not app.spotify:
        logger.warning(
            f"AlbumContents: Unable to fetch <{album_id}> because Spotify is not ready yet!"
        )
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(album_id) != 22:
        logger.warning(
            f"AlbumContents: Album <{album_id}> is invalid, expected 22 length, got {len(album_id)} instead"
        )
        return json(
            {
                "error": f"Invalid album id, expected 22 char length, got {len(album_id)} instead",
                "code": 400,
                "data": None
            },
            status=500
        )
    if not album_id.isalnum():
        logger.warning(
            f"AlbumContents: Album <{album_id}> is invalid, expected alphanumeric, got {album_id} instead"
        )
        return json(
            {
                "error": "Invalid album id, must be alphanumerical",
                "code": 400,
                "data": None
            },
            status=500
        )

    album_info = await app.spotify.get_album(album_id)
    if album_info is None:
        logger.warning(f"AlbumContents: Unable to find album <{album_id}>")
        return json({"error": "Album not found.", "code": 404, "data": None}, status=404)

    album_meta = album_info.to_json()
    return json({"error": "Success", "code": 200, "data": album_meta})


@app.get("/playlist/<playlist_id>")
async def get_playlist_contents(request: sanic.Request, playlist_id: str) -> HTTPResponse:
    logger.info(f"PlaylistContents: Received request for playlist <{playlist_id}>")
    if not app.spotify:
        logger.warning(
            f"PlaylistContents: Unable to fetch <{playlist_id}> because Spotify is not ready yet!"
        )
        return json({"error": "Spotify not connected.", "code": 500, "data": None}, status=500)
    if len(playlist_id) != 22:
        logger.warning(
            f"PlaylistContents: Playlist <{playlist_id}> is invalid, expected 22 length, got {len(playlist_id)} instead"
        )
        return json(
            {
                "error": f"Invalid playlist id, expected 22 char length, got {len(playlist_id)} instead",
                "code": 400,
                "data": None
            },
            status=500
        )
    if not playlist_id.isalnum():
        logger.warning(
            f"PlaylistContents: Playlist <{playlist_id}> is invalid, expected alphanumeric, got {playlist_id} instead"
        )
        return json(
            {
                "error": "Invalid playlist id, must be alphanumerical",
                "code": 400,
                "data": None
            },
            status=500
        )

    playlist_info = await app.spotify.get_playlist(playlist_id)
    if playlist_info is None:
        logger.warning(f"PlaylistContents: Unable to find playlist <{playlist_id}>")
        return json({"error": "Playlist not found.", "code": 404, "data": None}, status=404)

    playlist_meta = playlist_info.to_json()
    return json({"error": "Success", "code": 200, "data": playlist_meta})


if __name__ == "__main__":
    try:
        app.run("0.0.0.0", 37784)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        app.spotify.clsoe()
        app.stop()
