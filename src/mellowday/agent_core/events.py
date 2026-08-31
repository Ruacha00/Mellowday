"""Bounded structured runtime events for neutral diagnostics."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import cast

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
        conversation_id: str | None = "",
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

    @property
    def cursor(self) -> int:
        return self._sequence

    def query(
        self,
        *,
        since: int = 0,
        limit: int = 100,
        event_type: str = "",
        conversation_id: str = "",
    ) -> tuple[RuntimeEvent, ...]:
        matched = [
            event
            for event in self._events
            if event.sequence > since
            and (not event_type or event.type == cast(EventType, event_type))
            and (
                not conversation_id
                or event.conversation_id == conversation_id
            )
        ]
        bounded_limit = max(1, limit)
        selected = matched[:bounded_limit] if since else matched[-bounded_limit:]
        return tuple(selected)


__all__ = ["RuntimeEventLog"]
