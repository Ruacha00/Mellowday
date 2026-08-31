"""Versioned local persistence for Conversation History."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .events import RuntimeEventLog
from .types import ChatContent, EventType


_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    conversation_id: str
    message_count: int
    character_count: int
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class StoredConversation:
    summary: ConversationSummary
    messages: tuple[ChatContent, ...]


class ConversationHistory(Protocol):
    """Agent Core's product-neutral Conversation History boundary."""

    def recent(
        self,
        conversation_id: str,
        *,
        message_limit: int,
        character_limit: int,
    ) -> tuple[ChatContent, ...]: ...

    def append(
        self, conversation_id: str, messages: tuple[ChatContent, ...]
    ) -> None: ...

    def reset(self, conversation_id: str) -> int: ...


class ConversationHistoryError(RuntimeError):
    """A diagnosable failure at the Conversation History boundary."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"Conversation History operation failed: {operation}")


class SQLiteConversationHistory:
    """Persist isolated conversations in a local, versioned SQLite database."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        events: RuntimeEventLog | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database_path = Path(database_path)
        self._events = events
        self._clock = clock
        with self._diagnose("initialize"):
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version > _SCHEMA_VERSION:
                raise RuntimeError(
                    "Conversation History database version "
                    f"{version} is newer than supported version {_SCHEMA_VERSION}"
                )
            if version == 0:
                connection.executescript(
                    """
                    CREATE TABLE conversations (
                        conversation_id TEXT PRIMARY KEY,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    CREATE TABLE conversation_messages (
                        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                        content TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        FOREIGN KEY (conversation_id)
                            REFERENCES conversations(conversation_id)
                            ON DELETE CASCADE
                    );
                    CREATE INDEX conversation_messages_by_conversation
                        ON conversation_messages(conversation_id, message_id);
                    PRAGMA user_version = 1;
                    """
                )
        self._emit(
            "conversation_history_initialized",
            from_version=version,
            schema_version=_SCHEMA_VERSION,
        )

    def _emit(
        self, event_type: EventType, *, conversation_id: str = "", **details: object
    ) -> None:
        if self._events is not None:
            self._events.emit(
                event_type, conversation_id=conversation_id, **details
            )

    @contextmanager
    def _diagnose(
        self, operation: str, *, conversation_id: str = ""
    ) -> Iterator[None]:
        try:
            yield
        except (OSError, RuntimeError, sqlite3.Error) as error:
            self._emit(
                "conversation_history_failed",
                conversation_id=conversation_id,
                operation=operation,
                error_type=type(error).__name__,
                message=str(error),
                database_path=str(self.database_path),
            )
            raise ConversationHistoryError(operation) from error

    def append(
        self, conversation_id: str, messages: tuple[ChatContent, ...]
    ) -> None:
        if not messages:
            return
        occurred_at = self._clock()
        with self._diagnose("append", conversation_id=conversation_id):
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO conversations(conversation_id, created_at, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(conversation_id) DO NOTHING
                    """,
                    (conversation_id, occurred_at, occurred_at),
                )
                connection.executemany(
                    """
                    INSERT INTO conversation_messages(
                        conversation_id, role, content, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        (conversation_id, message.role, message.content, occurred_at)
                        for message in messages
                    ),
                )
                connection.execute(
                    """
                    UPDATE conversations
                    SET updated_at = ?
                    WHERE conversation_id = ?
                    """,
                    (occurred_at, conversation_id),
                )
        self._emit(
            "conversation_history_appended",
            conversation_id=conversation_id,
            messages_added=len(messages),
        )

    def recent(
        self,
        conversation_id: str,
        *,
        message_limit: int,
        character_limit: int,
    ) -> tuple[ChatContent, ...]:
        with self._diagnose("load", conversation_id=conversation_id):
            with self._connect() as connection:
                rows = connection.execute(
                    """
                    SELECT role, content
                    FROM conversation_messages
                    WHERE conversation_id = ?
                    ORDER BY message_id DESC
                    LIMIT ?
                    """,
                    (conversation_id, message_limit),
                ).fetchall()

        selected: list[ChatContent] = []
        used_characters = 0
        for row in rows:
            content = str(row["content"])
            if used_characters + len(content) > character_limit:
                break
            selected.append(ChatContent(role=row["role"], content=content))
            used_characters += len(content)
        selected.reverse()
        self._emit(
            "conversation_history_loaded",
            conversation_id=conversation_id,
            message_count=len(selected),
            character_count=used_characters,
        )
        return tuple(selected)

    def list_conversations(self) -> tuple[ConversationSummary, ...]:
        with self._diagnose("list"):
            with self._connect() as connection:
                rows = self._conversation_summaries(connection)
        summaries = tuple(self._summary_from_row(row) for row in rows)
        self._emit("conversation_history_listed", conversation_count=len(summaries))
        return summaries

    def count_conversations(self) -> int:
        """Return a status count without adding noise to the runtime event trail."""

        with self._diagnose("list"):
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT COUNT(*) AS conversation_count FROM conversations"
                ).fetchone()
        return int(row["conversation_count"])

    def get_conversation(self, conversation_id: str) -> StoredConversation | None:
        with self._diagnose("read", conversation_id=conversation_id):
            with self._connect() as connection:
                rows = self._conversation_summaries(
                    connection, conversation_id=conversation_id
                )
                row = rows[0] if rows else None
                if row is None:
                    self._emit(
                        "conversation_history_read",
                        conversation_id=conversation_id,
                        found=False,
                    )
                    return None
                message_rows = connection.execute(
                    """
                    SELECT role, content
                    FROM conversation_messages
                    WHERE conversation_id = ?
                    ORDER BY message_id
                    """,
                    (conversation_id,),
                ).fetchall()
        conversation = StoredConversation(
            summary=self._summary_from_row(row),
            messages=tuple(
                ChatContent(role=message["role"], content=message["content"])
                for message in message_rows
            ),
        )
        self._emit(
            "conversation_history_read",
            conversation_id=conversation_id,
            found=True,
            message_count=len(conversation.messages),
        )
        return conversation

    def reset(self, conversation_id: str) -> int:
        with self._diagnose("reset", conversation_id=conversation_id):
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT COUNT(*) AS message_count
                    FROM conversation_messages
                    WHERE conversation_id = ?
                    """,
                    (conversation_id,),
                ).fetchone()
                removed_messages = int(row["message_count"])
                connection.execute(
                    "DELETE FROM conversations WHERE conversation_id = ?",
                    (conversation_id,),
                )
        self._emit(
            "conversation_history_reset",
            conversation_id=conversation_id,
            removed_messages=removed_messages,
        )
        return removed_messages

    @staticmethod
    def _conversation_summaries(
        connection: sqlite3.Connection,
        *,
        conversation_id: str | None = None,
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT
                conversations.conversation_id,
                COUNT(conversation_messages.message_id) AS message_count,
                COALESCE(SUM(LENGTH(conversation_messages.content)), 0)
                    AS character_count,
                conversations.created_at,
                conversations.updated_at
            FROM conversations
            LEFT JOIN conversation_messages USING (conversation_id)
            WHERE (? IS NULL OR conversations.conversation_id = ?)
            GROUP BY conversations.conversation_id
            ORDER BY conversations.updated_at DESC,
                     conversations.conversation_id ASC
            """,
            (conversation_id, conversation_id),
        ).fetchall()

    @staticmethod
    def _summary_from_row(row: sqlite3.Row) -> ConversationSummary:
        return ConversationSummary(
            conversation_id=str(row["conversation_id"]),
            message_count=int(row["message_count"]),
            character_count=int(row["character_count"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
        )


__all__ = [
    "ConversationHistory",
    "ConversationHistoryError",
    "ConversationSummary",
    "SQLiteConversationHistory",
    "StoredConversation",
]
