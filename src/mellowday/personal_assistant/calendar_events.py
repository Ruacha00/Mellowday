"""Calendar Event application service and local persistence."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    id: str
    title: str
    start_at: str
    end_at: str | None
    details: str | None
    created_at: float
    updated_at: float


class CalendarEventValidationError(ValueError):
    """Raised when Calendar Event input is invalid."""


class CalendarEventTimeClarificationRequired(CalendarEventValidationError):
    """Raised when a local Calendar Event time needs User clarification."""


class CalendarEventNotFoundError(LookupError):
    """Raised by a Tool adapter when a Calendar Event does not exist."""

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(f"Calendar Event not found: {event_id}")


CalendarEventOperation = Literal["created", "updated", "deleted"]


@dataclass(frozen=True, slots=True)
class CalendarEventChange:
    operation: CalendarEventOperation
    event_id: str
    occurred_at: float
    conversation_id: str | None


class CalendarEventUpdates(TypedDict, total=False):
    title: str
    start_at: str
    end_at: str | None
    details: str | None


_UNSET = object()


class SQLiteCalendarEventService:
    """Manage the User's Calendar Events in the local application database."""

    def __init__(
        self,
        path: str | Path,
        *,
        installation_timezone: str,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        change_listener: Callable[[CalendarEventChange], None] | None = None,
    ) -> None:
        self._path = Path(path)
        try:
            self._timezone = ZoneInfo(installation_timezone)
        except ZoneInfoNotFoundError as error:
            raise CalendarEventValidationError(
                f"unknown installation timezone: {installation_timezone}"
            ) from error
        self._clock = clock
        self._id_factory = id_factory
        self._change_listener = change_listener
        self._initialize()

    def create(
        self,
        *,
        title: str,
        start_at: str,
        end_at: str | None = None,
        details: str | None = None,
        conversation_id: str | None = None,
    ) -> CalendarEvent:
        normalized_start, start_timestamp = self._date_time("start_at", start_at)
        normalized_end, end_timestamp = self._optional_date_time("end_at", end_at)
        _validate_range(start_timestamp, end_timestamp)
        now = self._clock()
        event = CalendarEvent(
            id=self._id_factory(),
            title=_required_text("title", title),
            start_at=normalized_start,
            end_at=normalized_end,
            details=_optional_text(details),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO calendar_events (
                    id, title, start_at, start_timestamp, end_at, end_timestamp,
                    details, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.title,
                    event.start_at,
                    start_timestamp,
                    event.end_at,
                    end_timestamp,
                    event.details,
                    event.created_at,
                    event.updated_at,
                ),
            )
        self._emit("created", event.id, now, conversation_id)
        return event

    def get(self, event_id: str) -> CalendarEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, start_at, end_at, details, created_at, updated_at
                FROM calendar_events WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
        return _event_from_row(row) if row is not None else None

    def list(self) -> tuple[CalendarEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, start_at, end_at, details, created_at, updated_at
                FROM calendar_events
                ORDER BY start_timestamp ASC, id ASC
                """
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def conflicts_for(self, event_id: str) -> tuple[CalendarEvent, ...]:
        event = self.get(event_id)
        if event is None:
            return ()
        return tuple(
            candidate
            for candidate in self.list()
            if candidate.id != event_id and _overlaps(event, candidate)
        )

    def update(
        self,
        event_id: str,
        *,
        title: str | object = _UNSET,
        start_at: str | object = _UNSET,
        end_at: str | None | object = _UNSET,
        details: str | None | object = _UNSET,
        conversation_id: str | None = None,
    ) -> CalendarEvent | None:
        if all(value is _UNSET for value in (title, start_at, end_at, details)):
            raise CalendarEventValidationError(
                "at least one Calendar Event field must be updated"
            )
        current = self.get(event_id)
        if current is None:
            return None
        normalized_title = (
            current.title
            if title is _UNSET
            else _required_text("title", _as_text("title", title))
        )
        if start_at is _UNSET:
            normalized_start, start_timestamp = self._date_time(
                "start_at", current.start_at
            )
        else:
            normalized_start, start_timestamp = self._date_time(
                "start_at", _as_text("start_at", start_at)
            )
        if end_at is _UNSET:
            normalized_end, end_timestamp = self._optional_date_time(
                "end_at", current.end_at
            )
        elif end_at is None or isinstance(end_at, str):
            normalized_end, end_timestamp = self._optional_date_time(
                "end_at", end_at
            )
        else:
            raise CalendarEventValidationError("end_at must be text or null")
        if details is _UNSET:
            normalized_details = current.details
        elif details is None or isinstance(details, str):
            normalized_details = _optional_text(details)
        else:
            raise CalendarEventValidationError("details must be text or null")
        _validate_range(start_timestamp, end_timestamp)
        if (
            normalized_title == current.title
            and normalized_start == current.start_at
            and normalized_end == current.end_at
            and normalized_details == current.details
        ):
            return current
        now = self._clock()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE calendar_events
                SET title = ?, start_at = ?, start_timestamp = ?, end_at = ?,
                    end_timestamp = ?, details = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_title,
                    normalized_start,
                    start_timestamp,
                    normalized_end,
                    end_timestamp,
                    normalized_details,
                    now,
                    event_id,
                ),
            )
        self._emit("updated", event_id, now, conversation_id)
        return self.get(event_id)

    def delete(
        self, event_id: str, *, conversation_id: str | None = None
    ) -> CalendarEvent | None:
        current = self.get(event_id)
        if current is None:
            return None
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM calendar_events WHERE id = ?", (event_id,)
            )
        self._emit("deleted", event_id, self._clock(), conversation_id)
        return current

    def _date_time(self, field: str, value: str) -> tuple[str, float]:
        normalized = _required_text(field, value)
        if "T" not in normalized and " " not in normalized:
            raise CalendarEventValidationError(
                f"{field} must be an ISO 8601 date-time"
            )
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise CalendarEventValidationError(
                f"{field} must be an ISO 8601 date-time"
            ) from error
        if parsed.tzinfo is None:
            parsed = self._resolve_local_time(field, parsed)
        else:
            parsed = parsed.astimezone(self._timezone)
        return parsed.isoformat(timespec="seconds"), parsed.timestamp()

    def _resolve_local_time(self, field: str, parsed: datetime) -> datetime:
        first = parsed.replace(tzinfo=self._timezone, fold=0)
        second = parsed.replace(tzinfo=self._timezone, fold=1)

        def round_trips(candidate: datetime) -> bool:
            return (
                candidate.astimezone(timezone.utc)
                .astimezone(self._timezone)
                .replace(tzinfo=None)
                == parsed
            )

        first_valid = round_trips(first)
        second_valid = round_trips(second)
        if not first_valid and not second_valid:
            raise CalendarEventTimeClarificationRequired(
                f"{field} does not exist in {self._timezone}; choose another time"
            )
        if (
            first_valid
            and second_valid
            and first.utcoffset() != second.utcoffset()
        ):
            raise CalendarEventTimeClarificationRequired(
                f"{field} is ambiguous in {self._timezone}; include a UTC offset"
            )
        return first if first_valid else second

    def _optional_date_time(
        self, field: str, value: str | None
    ) -> tuple[str | None, float | None]:
        normalized = _optional_text(value)
        if normalized is None:
            return None, None
        return self._date_time(field, normalized)

    def _emit(
        self,
        operation: CalendarEventOperation,
        event_id: str,
        occurred_at: float,
        conversation_id: str | None,
    ) -> None:
        if self._change_listener is not None:
            self._change_listener(
                CalendarEventChange(operation, event_id, occurred_at, conversation_id)
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS calendar_events (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    start_timestamp REAL NOT NULL,
                    end_at TEXT,
                    end_timestamp REAL,
                    details TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )


def _required_text(field: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise CalendarEventValidationError(f"{field} must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _as_text(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise CalendarEventValidationError(f"{field} must be text")
    return value


def _validate_range(start_timestamp: float, end_timestamp: float | None) -> None:
    if end_timestamp is not None and end_timestamp <= start_timestamp:
        raise CalendarEventValidationError("end_at must be after start_at")


def _event_from_row(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent(
        id=str(row["id"]),
        title=str(row["title"]),
        start_at=str(row["start_at"]),
        end_at=str(row["end_at"]) if row["end_at"] is not None else None,
        details=str(row["details"]) if row["details"] is not None else None,
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


def _overlaps(left: CalendarEvent, right: CalendarEvent) -> bool:
    left_start = datetime.fromisoformat(left.start_at).timestamp()
    right_start = datetime.fromisoformat(right.start_at).timestamp()
    left_end = (
        datetime.fromisoformat(left.end_at).timestamp()
        if left.end_at is not None
        else None
    )
    right_end = (
        datetime.fromisoformat(right.end_at).timestamp()
        if right.end_at is not None
        else None
    )
    if left_end is None and right_end is None:
        return left_start == right_start
    if left_end is None:
        assert right_end is not None
        return right_start <= left_start < right_end
    if right_end is None:
        return left_start <= right_start < left_end
    return left_start < right_end and right_start < left_end


__all__ = [
    "CalendarEvent",
    "CalendarEventChange",
    "CalendarEventNotFoundError",
    "CalendarEventOperation",
    "CalendarEventTimeClarificationRequired",
    "CalendarEventUpdates",
    "CalendarEventValidationError",
    "SQLiteCalendarEventService",
]
