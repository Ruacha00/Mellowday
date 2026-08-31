"""Reminder application service, persistence, and controlled delivery."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

ReminderState = Literal["scheduled", "delivered", "failed", "dismissed", "cancelled"]
ReminderOperation = Literal[
    "created", "updated", "delivered", "failed", "dismissed", "cancelled", "deleted"
]


@dataclass(frozen=True, slots=True)
class Reminder:
    id: str
    message: str
    due_at: str
    delivery_state: ReminderState
    task_id: str | None
    conversation_id: str
    created_at: float
    updated_at: float
    delivery_attempted_at: float | None
    delivered_at: float | None
    dismissed_at: float | None
    cancelled_at: float | None
    delivery_error: str | None


@dataclass(frozen=True, slots=True)
class ReminderDelivery:
    reminder_id: str
    message: str
    conversation_id: str
    task_id: str | None
    due_at: str


@dataclass(frozen=True, slots=True)
class ReminderChange:
    operation: ReminderOperation
    reminder_id: str
    occurred_at: float
    conversation_id: str | None


class ReminderUpdates(TypedDict, total=False):
    message: str
    due_at: str
    task_id: str | None
    conversation_id: str


class ReminderValidationError(ValueError):
    """Raised when Reminder input is invalid."""


_UNSET = object()
_REMINDER_COLUMNS = """
    id, message, due_at, delivery_state, task_id, conversation_id,
    created_at, updated_at, delivery_attempted_at, delivered_at,
    dismissed_at, cancelled_at, delivery_error
"""


class SQLiteReminderService:
    """Manage the User's Reminders in the local application database."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        change_listener: Callable[[ReminderChange], None] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._id_factory = id_factory
        self._change_listener = change_listener
        self._initialize()

    def create(
        self,
        *,
        message: str,
        due_at: str,
        task_id: str | None = None,
        conversation_id: str = "main",
    ) -> Reminder:
        normalized_message = _required_text("message", message)
        normalized_due_at, due_timestamp = _due_time(due_at)
        normalized_conversation = _required_text("conversation_id", conversation_id)
        now = self._clock()
        reminder = Reminder(
            id=self._id_factory(), message=normalized_message,
            due_at=normalized_due_at, delivery_state="scheduled", task_id=task_id,
            conversation_id=normalized_conversation, created_at=now, updated_at=now,
            delivery_attempted_at=None, delivered_at=None, dismissed_at=None,
            cancelled_at=None, delivery_error=None,
        )
        self._validate_task_reference(task_id)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO reminders (
                        id, message, due_at, due_timestamp, delivery_state,
                        task_id, conversation_id, created_at, updated_at,
                        delivery_attempted_at, delivered_at, dismissed_at,
                        cancelled_at, delivery_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reminder.id, reminder.message, reminder.due_at, due_timestamp,
                        reminder.delivery_state, reminder.task_id,
                        reminder.conversation_id, reminder.created_at,
                        reminder.updated_at, None, None, None, None, None,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ReminderValidationError(
                "task_id must identify an existing Task"
            ) from error
        self._emit("created", reminder, now)
        return reminder

    def get(self, reminder_id: str) -> Reminder | None:
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {_REMINDER_COLUMNS} FROM reminders WHERE id = ?",
                (reminder_id,),
            ).fetchone()
        return _reminder_from_row(row) if row is not None else None

    def list(self) -> tuple[Reminder, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT {_REMINDER_COLUMNS} FROM reminders "
                "ORDER BY due_timestamp ASC, created_at ASC, id ASC"
            ).fetchall()
        return tuple(_reminder_from_row(row) for row in rows)

    def update(
        self,
        reminder_id: str,
        *,
        message: str | object = _UNSET,
        due_at: str | object = _UNSET,
        task_id: str | None | object = _UNSET,
        conversation_id: str | object = _UNSET,
    ) -> Reminder | None:
        current = self.get(reminder_id)
        if current is None:
            return None
        normalized_message = current.message if message is _UNSET else _required_text(
            "message", _as_text("message", message)
        )
        normalized_due_at, due_timestamp = _due_time(
            current.due_at if due_at is _UNSET else _as_text("due_at", due_at)
        )
        normalized_task_id = current.task_id if task_id is _UNSET else task_id
        if normalized_task_id is not None and not isinstance(normalized_task_id, str):
            raise ReminderValidationError("task_id must be text or null")
        self._validate_task_reference(normalized_task_id)
        normalized_conversation = current.conversation_id if conversation_id is _UNSET else _required_text(
            "conversation_id", _as_text("conversation_id", conversation_id)
        )
        now = self._clock()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE reminders
                    SET message = ?, due_at = ?, due_timestamp = ?, task_id = ?,
                        conversation_id = ?, delivery_state = 'scheduled',
                        updated_at = ?, delivery_attempted_at = NULL,
                        delivered_at = NULL, dismissed_at = NULL,
                        cancelled_at = NULL, delivery_error = NULL
                    WHERE id = ?
                    """,
                    (
                        normalized_message, normalized_due_at, due_timestamp,
                        normalized_task_id, normalized_conversation, now, reminder_id,
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise ReminderValidationError(
                "task_id must identify an existing Task"
            ) from error
        updated = self.get(reminder_id)
        assert updated is not None
        self._emit("updated", updated, now)
        return updated

    def dismiss(self, reminder_id: str) -> Reminder | None:
        return self._set_state(reminder_id, "dismissed")

    def cancel(self, reminder_id: str) -> Reminder | None:
        return self._set_state(reminder_id, "cancelled")

    def delete(self, reminder_id: str) -> Reminder | None:
        current = self.get(reminder_id)
        if current is None:
            return None
        now = self._clock()
        with self._connect() as connection:
            connection.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self._emit("deleted", current, now)
        return current

    def claim_due(self, now: float) -> tuple[Reminder, ...]:
        """Atomically claim due Reminders so a restart cannot redeliver them."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                f"SELECT {_REMINDER_COLUMNS} FROM reminders "
                "WHERE delivery_state = 'scheduled' AND due_timestamp <= ? "
                "ORDER BY due_timestamp ASC, created_at ASC, id ASC",
                (now,),
            ).fetchall()
            reminder_ids = [str(row["id"]) for row in rows]
            connection.executemany(
                """
                UPDATE reminders
                SET delivery_state = 'delivered', delivery_attempted_at = ?,
                    delivered_at = ?, updated_at = ?, delivery_error = NULL
                WHERE id = ? AND delivery_state = 'scheduled'
                """,
                ((now, now, now, reminder_id) for reminder_id in reminder_ids),
            )
        claimed = tuple(self.get(reminder_id) for reminder_id in reminder_ids)
        delivered = tuple(item for item in claimed if item is not None)
        for reminder in delivered:
            self._emit("delivered", reminder, now)
        return delivered

    def record_delivery_failure(
        self, reminder_id: str, error: Exception, *, occurred_at: float
    ) -> Reminder | None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE reminders
                SET delivery_state = 'failed', delivered_at = NULL,
                    updated_at = ?, delivery_error = ?
                WHERE id = ? AND delivery_state = 'delivered'
                """,
                (occurred_at, type(error).__name__, reminder_id),
            )
        reminder = self.get(reminder_id)
        if reminder is not None:
            self._emit("failed", reminder, occurred_at)
        return reminder

    def _set_state(
        self, reminder_id: str, state: Literal["dismissed", "cancelled"]
    ) -> Reminder | None:
        current = self.get(reminder_id)
        if current is None:
            return None
        now = self._clock()
        timestamp_column = "dismissed_at" if state == "dismissed" else "cancelled_at"
        with self._connect() as connection:
            connection.execute(
                f"UPDATE reminders SET delivery_state = ?, {timestamp_column} = ?, "
                "updated_at = ? WHERE id = ?",
                (state, now, now, reminder_id),
            )
        changed = self.get(reminder_id)
        assert changed is not None
        self._emit(state, changed, now)
        return changed

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _validate_task_reference(self, task_id: str | None) -> None:
        if task_id is None:
            return
        with self._connect() as connection:
            task_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tasks'"
            ).fetchone()
            task = (
                connection.execute(
                    "SELECT 1 FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                if task_table is not None
                else None
            )
        if task is None:
            raise ReminderValidationError(
                "task_id must identify an existing Task"
            )

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY, message TEXT NOT NULL, due_at TEXT NOT NULL,
                    due_timestamp REAL NOT NULL,
                    delivery_state TEXT NOT NULL CHECK (delivery_state IN (
                        'scheduled', 'delivered', 'failed', 'dismissed', 'cancelled'
                    )),
                    task_id TEXT,
                    conversation_id TEXT NOT NULL, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, delivery_attempted_at REAL,
                    delivered_at REAL, dismissed_at REAL, cancelled_at REAL,
                    delivery_error TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS reminders_due "
                "ON reminders(delivery_state, due_timestamp)"
            )

    def _emit(
        self, operation: ReminderOperation, reminder: Reminder, occurred_at: float
    ) -> None:
        if self._change_listener is not None:
            self._change_listener(ReminderChange(
                operation=operation, reminder_id=reminder.id,
                occurred_at=occurred_at, conversation_id=reminder.conversation_id,
            ))


class ReminderScheduler:
    """Claim and deliver due Reminders through the public delivery callback."""

    def __init__(
        self,
        service: SQLiteReminderService,
        delivery: Callable[[ReminderDelivery], Awaitable[None]],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._service = service
        self._delivery = delivery
        self._clock = clock

    async def run_due(self) -> tuple[Reminder, ...]:
        occurred_at = self._clock()
        reminders = self._service.claim_due(occurred_at)
        for reminder in reminders:
            delivery = ReminderDelivery(
                reminder_id=reminder.id, message=reminder.message,
                conversation_id=reminder.conversation_id,
                task_id=reminder.task_id, due_at=reminder.due_at,
            )
            try:
                await self._delivery(delivery)
            except Exception as error:
                self._service.record_delivery_failure(
                    reminder.id, error, occurred_at=occurred_at
                )
        return reminders


def _reminder_from_row(row: sqlite3.Row) -> Reminder:
    return Reminder(
        id=str(row["id"]), message=str(row["message"]), due_at=str(row["due_at"]),
        delivery_state=row["delivery_state"],
        task_id=str(row["task_id"]) if row["task_id"] is not None else None,
        conversation_id=str(row["conversation_id"]),
        created_at=float(row["created_at"]), updated_at=float(row["updated_at"]),
        delivery_attempted_at=_optional_float(row["delivery_attempted_at"]),
        delivered_at=_optional_float(row["delivered_at"]),
        dismissed_at=_optional_float(row["dismissed_at"]),
        cancelled_at=_optional_float(row["cancelled_at"]),
        delivery_error=str(row["delivery_error"]) if row["delivery_error"] is not None else None,
    )


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _required_text(field: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ReminderValidationError(f"{field} must not be empty")
    return normalized


def _as_text(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise ReminderValidationError(f"{field} must be text")
    return value


def _due_time(value: str) -> tuple[str, float]:
    normalized = _required_text("due_at", value)
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ReminderValidationError(
            "due_at must be an ISO 8601 date-time with a UTC offset"
        ) from error
    if parsed.tzinfo is None:
        raise ReminderValidationError("due_at must include a UTC offset")
    return normalized, parsed.timestamp()


__all__ = [
    "Reminder", "ReminderChange", "ReminderDelivery", "ReminderOperation",
    "ReminderScheduler", "ReminderState", "ReminderUpdates",
    "ReminderValidationError", "SQLiteReminderService",
]
