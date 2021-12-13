"""
MIT License

Copyright (c) 2021-present noaione

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

MPD and direct link streams loader
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from io import SEEK_SET, BytesIO
from typing import TYPE_CHECKING, Dict, Optional

import aiohttp

from .mpd import TidalMPDMeta

if TYPE_CHECKING:
    from _typeshed import ReadableBuffer


class TidalStreamer:
    """
    MPD and direct link streams loader
    """

    logger = logging.getLogger("Tidal:Streamer")

    def __init__(
        self, codecs: str, mimetype: str, *, session: aiohttp.ClientSession, loop: asyncio.AbstractEventLoop = None
    ):
        self._session: aiohttp.ClientSession = session
        self.codecs: str = codecs
        self.mimetype: str = mimetype
        self._loop: asyncio.AbstractEventLoop = loop or asyncio.get_event_loop()
        self.read = 0

    @property
    def closed(self) -> bool:
        """Check if the stream is closed"""
        return True

    def empty(self) -> bool:
        """
        Check if the stream is empty
        """
        return True

    def available(self) -> int:
        """
        Check if the stream still have available data
        """
        return 0

    async def init(self):
        """
        Initialize the streamer
        """
        raise NotImplementedError

    async def read_bytes(self, size: int):
        """
        Read the stream
        """
        raise NotImplementedError

    async def read_all(self):
        """
        Read all the stream
        """
        raise NotImplementedError

    async def close(self):
        """
        Close the stream
        """
        raise NotImplementedError

    async def as_chunks(self, read_every: bytes):
        """Request the stream as chunks

        Returns a async generator that yields chunks of the stream.
        """
        yield b""


class AsyncBytesIO(BytesIO):
    """
    BytesIO but async
    """

    def __init__(self, *, loop: asyncio.AbstractEventLoop = None):
        super().__init__()
        self._loop = loop or asyncio.get_event_loop()

        self._check_closed = False

    async def close(self) -> None:
        if self._check_closed:
            return
        await self._loop.run_in_executor(None, super().close)
        self._check_closed = True

    @property
    def size(self) -> int:
        return len(self.getvalue_sync())

    def close_sync(self) -> None:
        super().close()

    async def clear(self):
        await self.seek(0)
        await self.truncate(0)

    async def read(self, size: Optional[int] = None) -> bytes:
        return await self._loop.run_in_executor(None, super().read, size)

    async def getvalue(self) -> bytes:
        return await self._loop.run_in_executor(None, super().getvalue)

    def getvalue_sync(self) -> bytes:
        return super().getvalue()

    async def write(self, buffer: ReadableBuffer) -> int:
        return await self._loop.run_in_executor(None, super().write, buffer)

    async def tell(self) -> int:
        return await self._loop.run_in_executor(None, super().tell)

    async def seek(self, offset: int, whence: int = SEEK_SET) -> int:
        if whence != SEEK_SET:
            offset = 0
        return await self._loop.run_in_executor(None, super().seek, offset, whence)

    async def truncate(self, size: Optional[int] = None) -> int:
        return await self._loop.run_in_executor(None, super().truncate, size)


@dataclass
class TidalMPD(TidalStreamer):
    def __init__(
        self,
        metadata: TidalMPDMeta,
        *,
        session: aiohttp.ClientSession,
        loop: asyncio.AbstractEventLoop = None,
    ):
        super().__init__(metadata.codecs, metadata.mimetype, session=session, loop=loop)
        self.metadata: TidalMPDMeta = metadata

        self._loop: asyncio.AbstractEventLoop = loop or asyncio.get_event_loop()

        self._queue: AsyncBytesIO = AsyncBytesIO(loop=self._loop)
        self._current_chunks: int = -1
        self._requested_chunks: Dict[int, int] = {}
        self._expected_available: int = -1
        self._read: int = 0
        self._chunk_read: int = 0
        self._init = False

    def empty(self) -> bool:
        is_last_chunk_requested = len(self.metadata.chunks) <= 0
        return self.chunk_empty() and is_last_chunk_requested

    def chunk_empty(self) -> bool:
        size_left = self._queue.size - self._chunk_read
        return size_left <= 0

    def available(self) -> int:
        if self._expected_available == -1:
            return -1
        return self._expected_available - self._read

    def _adjust_expected(self):
        self._expected_available = self._requested_chunks[0]
        skip_chunk = []
        for chunk_no, chunk_size in self._requested_chunks.items():
            if chunk_no == 0:
                continue
            self._expected_available += chunk_size
            skip_chunk.append(chunk_no)
        for chunk in self.metadata.chunks:
            if chunk.number in skip_chunk:
                continue
            self._expected_available += chunk.size
        self.logger.debug(f"MPD: Adjusted expected available to {self._expected_available} bytes")

    async def _request_chunk(self):
        # Clean the queue first
        await self._queue.clear()
        if self._current_chunks == -1:
            self._current_chunks = 0
            self.logger.debug("MPD: Trying to request initial MPD chunks")
            async with self._session.get(self.metadata.initial) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Error requesting initial chunk: {resp.status}")
                await self._queue.write(await resp.read())
                content_length = resp.content_length
                if content_length is not None:
                    self._requested_chunks[0] = content_length
                else:
                    self._requested_chunks[0] = self.metadata.chunks[0].size
                await self._queue.seek(0)
                self._chunk_read = 0
            return

        chunk = self.metadata.chunks.pop(0)
        self._current_chunks = chunk.number
        self.logger.debug(f"MPD: Trying to request chunk {self._current_chunks}")
        async with self._session.get(chunk.as_url(self.metadata.template)) as resp:
            if resp.status != 200:
                raise RuntimeError(f"Error requesting chunk {chunk.number}: {resp.status}")
            content_length = resp.content_length
            if content_length is not None:
                self._requested_chunks[chunk.number] = content_length
            else:
                self._requested_chunks[chunk.number] = chunk.size
            self._adjust_expected()
            await self._queue.write(await resp.read())
            self._chunk_read = 0
            await self._queue.seek(0)

    async def init(self):
        """
        Initialize the streamer
        """
        await self._request_chunk()
        await self._queue.seek(0)
        self._adjust_expected()
        self._init = True

    async def read_bytes(self, size: int):
        """
        Read the stream
        """
        await self._queue.seek(0)
        if self.empty():
            self.logger.debug("MPD: All chunk exhausted, returning empty")
            return b""

        if self.chunk_empty():
            self.logger.debug(f"MPD: Current chunk {self._current_chunks} exhausted, requesting next chunk")
            await self._request_chunk()

        data = await self._queue.read(size)
        self._read += len(data)
        self._chunk_read += len(data)
        return data

    async def read_all(self):
        """
        Read all the stream
        """
        await self._queue.seek(0)
        if self.empty():
            self.logger.debug("MPD: All chunk exhausted, returning empty")
            return b""

        all_bytes = AsyncBytesIO()
        while not self.empty():
            if self.chunk_empty():
                self.logger.debug(f"MPD: Current chunk {self._current_chunks} exhausted, requesting next chunk")
                await self._request_chunk()
            self.logger.debug(f"MPD: Reading chunk {self._current_chunks}")
            await all_bytes.write(await self._queue.read())
            self._chunk_read += self._queue.size
        self.logger.debug("MPD: All chunk exhausted, returning all bytes")
        await self.close()
        return await all_bytes.getvalue()

    async def close(self):
        await self._queue.close()

    async def as_chunks(self, read_every: bytes):
        if not self._init:
            await self.init()

        while not self.empty():
            yield await self.read_bytes(read_every)


class TidalBTS(TidalStreamer):
    def __init__(
        self,
        codecs: str,
        mimetype: str,
        url: str,
        *,
        session: aiohttp.ClientSession,
        loop: asyncio.AbstractEventLoop = None,
    ):
        super().__init__(codecs, mimetype, session=session, loop=loop)
        self.url: str = url
        self._request: aiohttp.ClientResponse = None
        self._init = False

    async def init(self):
        self._request = await self._session.get(self.url)
        self._init = True

    @property
    def closed(self):
        if self._request is None:
            return True
        return self._request._closed

    def empty(self):
        if self._request is None:
            return True
        return self._request.content.at_eof()

    def available(self):
        if self._request is None:
            return 0
        content_length = self._request.content_length
        return content_length - self.read

    async def read_bytes(self, size: int = 4096):
        streamer = self._request.content
        if self.empty():
            self._request.close()
            return b""

        data = await streamer.read(size)
        self.read += len(data)
        if self.empty():
            self._request.close()
        return data

    async def read_all(self):
        data = await self._request.read()
        self.read += len(data)
        self._request.close()
        return data

    async def close(self):
        self._request.close()

    async def as_chunks(self, read_every: bytes):
        if not self._init:
            await self.init()

        while self.available() > 0:
            yield await self.read_bytes(read_every)
