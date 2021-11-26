import asyncio
import logging
import os
import sys
from pathlib import Path

import coloredlogs
import sanic
from dotenv import load_dotenv
from sanic.response import HTTPResponse, file, text

from internals.logger import RollingFileHandler
from internals.monke import monkeypatch_load
from internals.sanic import SpotilavaSanic
from internals.spotify import LIBRESpotifyWrapper, should_inject_metadata
from internals.tidal.tidal import TidalAPI
from routes import (episodes_bp, meta_bp, playlists_bp, tidal_tracks_bp,
                    tracks_bp)

# Monkeypatch librespot
monkeypatch_load()
CURRENT_PATH = Path(__file__).parent
log_path = CURRENT_PATH / "logs"
log_path.mkdir(exist_ok=True)
load_dotenv(str(CURRENT_PATH / ".env"))

file_handler = RollingFileHandler(log_path / "spotilava.log", maxBytes=5_242_880, backupCount=5, encoding="utf-8")
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


async def connect_tidal(app: SpotilavaSanic):
    if app.tidal is not None:
        return

    if os.getenv("ENABLE_TIDAL", "0") != "1":
        logger.info("App: Tidal is disabled.")
        return
    logger.info("App: Creating Tidal wrapper...")
    tidal = TidalAPI(loop=app.loop)
    try:
        await tidal.create()
    except Exception as e:
        logger.error(f"App: Failed to create tidal wrapper: {e}", exc_info=e)
        sys.exit(69)
    app.tidal = tidal


logger.info("App: Initiating spotilava webserver...")
loop = asyncio.get_event_loop()
app = SpotilavaSanic("Spotilava")
try:
    CHUNK_SIZE = int(os.getenv("SPOTILAVA_CHUNK_SIZE", "4096"))
except Exception:
    CHUNK_SIZE = 4096

PORT = os.getenv("PORT")
if PORT is None:
    PORT = 37784
else:
    PORT = int(PORT)

app.add_task(connect_spotify)
app.add_task(connect_tidal)

# For metadata tagging purpose
if CHUNK_SIZE < 4096:
    raise ValueError("Chunk size must be at least 4096 (Metadata purpose).")
if CHUNK_SIZE % 8 != 0:
    raise ValueError("Chunk size must be a multiple of 8.")
app.chunk_size = CHUNK_SIZE


@app.get("/")
async def index(request: sanic.Request) -> HTTPResponse:
    return text("</>")


@app.get("/favicon.ico")
async def favicon(request: sanic.Request) -> HTTPResponse:
    return await file(str(CURRENT_PATH / "static" / "favicon.ico"))


# Register blueprint
app.blueprint(tracks_bp)
app.blueprint(episodes_bp)
app.blueprint(playlists_bp)
app.blueprint(meta_bp)

# Tidal extension
if os.getenv("ENABLE_TIDAL", "0") == "1":
    app.blueprint(tidal_tracks_bp)


if __name__ == "__main__":
    try:
        app.run("0.0.0.0", PORT)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        app.spotify.clsoe()
        if app.tidal:
            app.loop.run_until_complete(app.tidal.close())
        app.stop()
