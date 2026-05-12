"""Server-Sent Events broadcast bus for pipeline progress."""

import asyncio
import json
from collections import deque
from typing import AsyncIterator

MAX_REPLAY = 50

_subscribers: list[asyncio.Queue] = []
_replay_buffer: deque[str] = deque(maxlen=MAX_REPLAY)


def publish(event_type: str, data: dict) -> None:
    """Publish an event to all connected SSE subscribers.

    Safe to call from synchronous code. Appends to replay buffer so
    late-joining clients receive recent pipeline state on connect.
    Drops events for slow subscribers rather than blocking the pipeline.
    """
    message = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
    _replay_buffer.append(message)
    for q in _subscribers:
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            pass  # Drop for slow subscribers (backpressure)


class _Subscriber:
    """Async iterator over SSE messages.

    Registers its queue immediately at construction time so events published
    between subscribe() and the first iteration are never lost.
    Pre-fills from the replay buffer so late-joining clients receive the
    current pipeline state without waiting for the next event.
    """

    def __init__(self) -> None:
        self._q: asyncio.Queue = asyncio.Queue(maxsize=100)
        # Register before replay so no live events slip through the window
        _subscribers.append(self._q)
        for msg in list(_replay_buffer):
            try:
                self._q.put_nowait(msg)
            except asyncio.QueueFull:
                break

    def __aiter__(self) -> "_Subscriber":
        return self

    async def __anext__(self) -> str:
        return await self._q.get()

    async def aclose(self) -> None:
        try:
            _subscribers.remove(self._q)
        except ValueError:
            pass


def subscribe() -> _Subscriber:
    """Return a pre-registered SSE subscriber.

    The subscriber queue is active from this call — events published between
    subscribe() and the first iteration are NOT lost. Recent events from the
    replay buffer (up to MAX_REPLAY) are delivered immediately on first iteration.
    """
    return _Subscriber()
