"""Event stream encoding for the web layer.

The runtime emits structured events through :mod:`mellowday.runtime.events`.
This module turns that stream into something HTTP clients can consume without
understanding anything about the runtime internals.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

Event = dict[str, Any]


def encode(event: Event) -> str:
    return json.dumps(event, ensure_ascii=False)


def to_sse(event: Event) -> str:
    """Server-sent events: one named event per runtime event."""
    name = str(event.get("type") or "message")
    return f"event: {name}\ndata: {encode(event)}\n\n"


def to_ndjson(event: Event) -> str:
    return encode(event) + "\n"


class EventChannel:
    """An event sink backed by an asyncio queue.

    Used as the sink for one conversation turn and iterated by the HTTP
    response generator. `close()` always terminates the iteration, even when a
    runtime error escapes the agent loop.
    """

    _SENTINEL = None

    def __init__(self, *, maxsize: int = 0) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._closed = False

    def sink(self, event: Event) -> None:
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._queue.put_nowait(self._SENTINEL)
        except asyncio.QueueFull:
            pass

    @property
    def closed(self) -> bool:
        return self._closed

    async def _iterate(self) -> AsyncIterator[Event]:
        while True:
            item = await self._queue.get()
            if item is self._SENTINEL:
                break
            yield item

    def __aiter__(self) -> AsyncIterator[Event]:
        return self._iterate()

    async def drain(self) -> list[Event]:
        return [event async for event in self]
