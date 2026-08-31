"""Local append-only storage for neutral Agent Core runtime events."""

import json
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from threading import Lock
from typing import cast

from .types import EventType, RuntimeEvent


class AuditLog:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = Lock()
        self._events = self._read_events()

    @property
    def last_sequence(self) -> int:
        return max((event.sequence for event in self._events), default=0)

    def append(self, event: RuntimeEvent) -> None:
        stored = deepcopy(event)
        with self._lock:
            if self._path is not None:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                with self._path.open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            asdict(stored),
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
            self._events.append(stored)

    def events(self) -> tuple[RuntimeEvent, ...]:
        with self._lock:
            return deepcopy(tuple(self._events))

    def _read_events(self) -> list[RuntimeEvent]:
        if self._path is None or not self._path.exists():
            return []
        events: list[RuntimeEvent] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
                details = payload.get("details", {})
                events.append(
                    RuntimeEvent(
                        sequence=int(payload["sequence"]),
                        type=cast(EventType, str(payload["type"])),
                        occurred_at=float(payload["occurred_at"]),
                        conversation_id=(
                            str(payload["conversation_id"])
                            if payload.get("conversation_id") is not None
                            else None
                        ),
                        details=dict(details) if isinstance(details, dict) else {},
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
        return events


__all__ = ["AuditLog"]
