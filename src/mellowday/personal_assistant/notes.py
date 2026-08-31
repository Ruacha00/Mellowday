"""Note application service and local persistence."""

from __future__ import annotations

import sqlite3
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict


@dataclass(frozen=True, slots=True)
class Note:
    id: str
    title: str | None
    content: str
    created_at: float
    updated_at: float


class NoteValidationError(ValueError):
    """Raised when Note input is invalid."""


class NoteNotFoundError(LookupError):
    """Raised by a Tool adapter when a requested Note does not exist."""

    def __init__(self, note_id: str) -> None:
        self.note_id = note_id
        super().__init__(f"Note not found: {note_id}")


NoteOperation = Literal["created", "updated", "deleted"]


@dataclass(frozen=True, slots=True)
class NoteChange:
    operation: NoteOperation
    note_id: str
    occurred_at: float
    conversation_id: str | None


class NoteChangeNotificationError(RuntimeError):
    """Report a committed Note change whose listener could not record it."""

    def __init__(self, operation: NoteOperation, note_id: str) -> None:
        self.operation = operation
        self.note_id = note_id
        self.committed = True
        super().__init__(
            f"Note {operation} but its change notification could not be recorded"
        )


class NoteUpdates(TypedDict, total=False):
    title: str | None
    content: str


_UNSET = object()


class SQLiteNoteService:
    """Manage the User's Notes in the local application database."""

    def __init__(
        self,
        path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        change_listener: Callable[[NoteChange], None] | None = None,
    ) -> None:
        self._path = Path(path)
        self._clock = clock
        self._id_factory = id_factory
        self._change_listener = change_listener
        self._initialize()

    def create(
        self,
        *,
        content: str,
        title: str | None = None,
        conversation_id: str | None = None,
    ) -> Note:
        now = self._clock()
        note = Note(
            id=self._id_factory(),
            title=_optional_text(title),
            content=_required_text("content", content),
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO notes (id, title, content, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (note.id, note.title, note.content, note.created_at, note.updated_at),
            )
        self._emit("created", note.id, now, conversation_id)
        return note

    def get(self, note_id: str) -> Note | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, content, created_at, updated_at
                FROM notes WHERE id = ?
                """,
                (note_id,),
            ).fetchone()
        return _note_from_row(row) if row is not None else None

    def list(self) -> tuple[Note, ...]:
        return self.search("")

    def search(self, query: str) -> tuple[Note, ...]:
        needle = f"%{query.strip()}%"
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, content, created_at, updated_at
                FROM notes
                WHERE title LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE
                ORDER BY updated_at DESC, id ASC
                """,
                (needle, needle),
            ).fetchall()
        return tuple(_note_from_row(row) for row in rows)

    def update(
        self,
        note_id: str,
        *,
        title: str | None | object = _UNSET,
        content: str | object = _UNSET,
        conversation_id: str | None = None,
    ) -> Note | None:
        if title is _UNSET and content is _UNSET:
            raise NoteValidationError("at least one Note field must be updated")
        current = self.get(note_id)
        if current is None:
            return None
        if title is _UNSET:
            normalized_title = current.title
        elif title is None or isinstance(title, str):
            normalized_title = _optional_text(title)
        else:
            raise NoteValidationError("title must be text or null")
        if content is _UNSET:
            normalized_content = current.content
        elif isinstance(content, str):
            normalized_content = _required_text("content", content)
        else:
            raise NoteValidationError("content must be text")
        if (
            normalized_title == current.title
            and normalized_content == current.content
        ):
            return current
        now = self._clock()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE notes SET title = ?, content = ?, updated_at = ?
                WHERE id = ?
                """,
                (normalized_title, normalized_content, now, note_id),
            )
        self._emit("updated", note_id, now, conversation_id)
        return self.get(note_id)

    def delete(
        self, note_id: str, *, conversation_id: str | None = None
    ) -> Note | None:
        current = self.get(note_id)
        if current is None:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        self._emit("deleted", note_id, self._clock(), conversation_id)
        return current

    def _emit(
        self,
        operation: NoteOperation,
        note_id: str,
        occurred_at: float,
        conversation_id: str | None,
    ) -> None:
        if self._change_listener is not None:
            try:
                self._change_listener(
                    NoteChange(operation, note_id, occurred_at, conversation_id)
                )
            except Exception as error:
                raise NoteChangeNotificationError(operation, note_id) from error

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    content TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )


def _required_text(field: str, value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise NoteValidationError(f"{field} must not be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _note_from_row(row: sqlite3.Row) -> Note:
    return Note(
        id=str(row["id"]),
        title=str(row["title"]) if row["title"] is not None else None,
        content=str(row["content"]),
        created_at=float(row["created_at"]),
        updated_at=float(row["updated_at"]),
    )


__all__ = [
    "Note",
    "NoteChange",
    "NoteChangeNotificationError",
    "NoteNotFoundError",
    "NoteOperation",
    "NoteUpdates",
    "NoteValidationError",
    "SQLiteNoteService",
]
