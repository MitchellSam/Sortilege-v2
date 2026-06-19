"""Thread-safe SSE event bus.

router.py calls push_event() from a background thread; the SSE endpoint
fans out to all connected async consumers.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_clients: list[asyncio.Queue] = []


def init(loop: asyncio.AbstractEventLoop) -> None:
    """Store the running event loop so push_event can bridge the thread boundary."""
    global _loop
    _loop = loop


def push_event(event_type: str, data: dict) -> None:
    """Broadcast an event to all connected SSE clients. Thread-safe."""
    if not _clients or _loop is None or _loop.is_closed():
        return
    msg = {"event": event_type, "data": data}
    for q in list(_clients):
        try:
            _loop.call_soon_threadsafe(q.put_nowait, msg)
        except Exception:
            pass


async def _subscribe() -> tuple[asyncio.Queue, int]:
    q: asyncio.Queue = asyncio.Queue()
    _clients.append(q)
    return q, id(q)


def _unsubscribe(client_id: int) -> None:
    global _clients
    _clients = [q for q in _clients if id(q) != client_id]


async def event_generator(request) -> AsyncGenerator[dict, None]:
    """Async generator consumed by EventSourceResponse."""
    q, client_id = await _subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                yield {"event": msg["event"], "data": json.dumps(msg["data"])}
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": ""}
    finally:
        _unsubscribe(client_id)
