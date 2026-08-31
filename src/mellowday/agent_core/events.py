"""Bounded structured runtime events for neutral diagnostics."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from .types import EventType, RuntimeEvent


class RuntimeEventLog:
    def __init__(
        self,
        *,
        capacity: int = 1_000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._events: deque[RuntimeEvent] = deque(maxlen=max(1, capacity))
        self._clock = clock
        self._sequence = 0

    def emit(
        self,
        event_type: EventType,
        *,
        conversation_id: str = "",
        **details: object,
    ) -> RuntimeEvent:
        self._sequence += 1
        event = RuntimeEvent(
            sequence=self._sequence,
            type=event_type,
            occurred_at=self._clock(),
            conversation_id=conversation_id,
            details=details,
        )
        self._events.append(event)
        return event

    def recent(self, *, limit: int = 100) -> tuple[RuntimeEvent, ...]:
        return tuple(self._events)[-max(1, limit) :]


__all__ = ["RuntimeEventLog"]
