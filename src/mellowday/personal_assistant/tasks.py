"""Task application service and local persistence."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    title: str
    details: str | None
    completed: bool
    deadline: str | None
    created_at: float
    updated_at: float
    completed_at: float | None


class TaskValidationError(ValueError):
    """Raised when Task input is invalid."""


TaskOperation = Literal["created", "updated", "completed", "reopened", "deleted"]


@dataclass(frozen=True, slots=True)
class TaskChange:
    operation: TaskOperation
    task_id: str
    occurred_at: float
    conversation_id: str | None


_UNSET = object()


class SQLiteTaskService:
    """Manage the User's Tasks in the local application database."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        change_listener: Callable[[TaskChange], None] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._id_factory = id_factory
        self._change_listener = change_listener
        self._initialize()

    def create(
        self,
        *,
        title: str,
        details: str | None = None,
        deadline: str | None = None,
        conversation_id: str | None = None,
    ) -> Task:
        normalized_title = _required_text("title", title)
        normalized_details = _optional_text(details)
        normalized_deadline = _deadline(deadline)
        now = self._clock()
        task = Task(
            id=self._id_factory(),
            title=normalized_title,
            details=normalized_details,
            completed=False,
            deadline=normalized_deadline,
            created_at=now,
            updated_at=now,
            completed_at=None,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    id, title, details, completed, deadline,
                    created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.id,
                    task.title,
                    task.details,
                    task.completed,
                    task.deadline,
                    task.created_at,
                    task.updated_at,
                    task.completed_at,
                ),
            )
        self._emit("created", task.id, now, conversation_id)
        return task

    def get(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, details, completed, deadline,
                       created_at, updated_at, completed_at
                FROM tasks WHERE id = ?
                """,
                (task_id,),
            ).fetchone()
        return _task_from_row(row) if row is not None else None

    def list(self) -> tuple[Task, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, details, completed, deadline,
                       created_at, updated_at, completed_at
                FROM tasks
                ORDER BY completed ASC, created_at DESC, id ASC
                """
            ).fetchall()
        return tuple(_task_from_row(row) for row in rows)

    def update(
        self,
        task_id: str,
        *,
        title: str | object = _UNSET,
        details: str | None | object = _UNSET,
        deadline: str | None | object = _UNSET,
        conversation_id: str | None = None,
    ) -> Task | None:
        current = self.get(task_id)
        if current is None:
            return None
        if title is _UNSET:
            normalized_title = current.title
        elif isinstance(title, str):
            normalized_title = _required_text("title", title)
        else:
            raise TaskValidationError("title must be text")
        if details is _UNSET:
            normalized_details = current.details
        elif details is None or isinstance(details, str):
            normalized_details = _optional_text(details)
        else:
            raise TaskValidationError("details must be text or null")
        if deadline is _UNSET:
            normalized_deadline = current.deadline
        elif deadline is None or isinstance(deadline, str):
            normalized_deadline = _deadline(deadline)
        else:
            raise TaskValidationError("deadline must be text or null")
        now = self._clock()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET title = ?, details = ?, deadline = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_title,
                    normalized_details,
                    normalized_deadline,
                    now,
                    task_id,
                ),
            )
        self._emit("updated", task_id, now, conversation_id)
        return self.get(task_id)

    def complete(
        self, task_id: str, *, conversation_id: str | None = None
    ) -> Task | None:
        return self._set_completion(task_id, True, conversation_id)

    def reopen(
        self, task_id: str, *, conversation_id: str | None = None
    ) -> Task | None:
        return self._set_completion(task_id, False, conversation_id)

    def delete(
        self, task_id: str, *, conversation_id: str | None = None
    ) -> Task | None:
        current = self.get(task_id)
        if current is None:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._emit("deleted", task_id, self._clock(), conversation_id)
        return current

    def _set_completion(
        self, task_id: str, completed: bool, conversation_id: str | None
    ) -> Task | None:
        current = self.get(task_id)
        if current is None:
            return None
        now = self._clock()
        completed_at = now if completed else None
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET completed = ?, completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (completed, completed_at, now, task_id),
            )
        operation: TaskOperation = "completed" if completed else "reopened"
        self._emit(operation, task_id, now, conversation_id)
        return self.get(task_id)

    def _emit(
        self,
        operation: TaskOperation,
        task_id: str,
        occurred_at: float,
        conversation_id: str | None,
    ) -> None:
        if self._change_listener is not None:
            self._change_listener(
                TaskChange(
                    operation=operation,
                    task_id=task_id,
                    occurred_at=occurred_at,
                    conversation_id=conversation_id,
                )
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
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    details TEXT,
                    completed INTEGER NOT NULL DEFAULT 0,
                    deadline TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )


def _required_text(field: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TaskValidationError(f"{field} must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _deadline(value: str | None) -> str | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise TaskValidationError("deadline must be an ISO 8601 date or date-time") from error
    if parsed.tzinfo is None and "T" in normalized:
        raise TaskValidationError("deadline date-time must include a UTC offset")
    return normalized


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=str(row["id"]),
        title=str(row["title"]),
        details=str(row["details"]) if row["details"] is not None else None,
        completed=bool(row["completed"]),
        deadline=str(row["deadline"]) if row["deadline"] is not None else None,
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
        completed_at=(
            float(row["completed_at"])
            if row["completed_at"] is not None
            else None
        ),
    )


__all__ = [
    "SQLiteTaskService",
    "Task",
    "TaskChange",
    "TaskOperation",
    "TaskValidationError",
]
