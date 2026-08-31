"""Durable local Memory owned by the Personal Assistant."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
import time
from typing import Literal, TypedDict, cast
from uuid import uuid4


MemoryKind = Literal["preference", "fact", "important"]
MemoryProvenance = Literal["explicit", "automatic", "settings"]
MemoryChangeOperation = Literal["created", "updated", "deleted"]


class MemoryUpdates(TypedDict, total=False):
    content: str
    kind: MemoryKind


@dataclass(frozen=True, slots=True)
class Memory:
    id: str
    content: str
    kind: MemoryKind
    provenance: MemoryProvenance
    source_conversation_id: str | None
    created_at: float
    updated_at: float


@dataclass(frozen=True, slots=True)
class MemoryChange:
    operation: MemoryChangeOperation
    memory_id: str
    conversation_id: str | None


class MemoryValidationError(ValueError):
    """Raised when a Memory record would be invalid."""


class MemoryNotFoundError(LookupError):
    """Raised when a requested Memory no longer exists."""


class SQLiteMemoryService:
    """Shared application service for durable User information."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], str] = lambda: uuid4().hex,
        change_listener: Callable[[MemoryChange], None] | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._clock = clock
        self._id_factory = id_factory
        self._change_listener = change_listener
        self._initialize()

    def remember(
        self,
        *,
        content: str,
        kind: MemoryKind,
        provenance: MemoryProvenance,
        source_conversation_id: str | None = None,
    ) -> Memory:
        normalized_content = content.strip()
        if not normalized_content:
            raise MemoryValidationError("content must not be empty")
        now = self._clock()
        memory = Memory(
            id=self._id_factory(),
            content=normalized_content,
            kind=kind,
            provenance=provenance,
            source_conversation_id=source_conversation_id,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO memories (
                    id, content, kind, provenance, source_conversation_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    memory.id,
                    memory.content,
                    memory.kind,
                    memory.provenance,
                    memory.source_conversation_id,
                    memory.created_at,
                    memory.updated_at,
                ),
            )
        self._notify(MemoryChange("created", memory.id, source_conversation_id))
        return memory

    def list(self, query: str = "") -> tuple[Memory, ...]:
        normalized_query = query.strip().casefold()
        statement = """
            SELECT id, content, kind, provenance, source_conversation_id,
                   created_at, updated_at
            FROM memories
        """
        parameters: tuple[object, ...] = ()
        if normalized_query:
            statement += " WHERE lower(content) LIKE ?"
            parameters = (f"%{normalized_query}%",)
        statement += " ORDER BY updated_at DESC, id ASC"
        with self._connect() as connection:
            rows = connection.execute(statement, parameters).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def get(self, memory_id: str) -> Memory | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, content, kind, provenance, source_conversation_id,
                       created_at, updated_at
                FROM memories
                WHERE id = ?
                """,
                (memory_id,),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        kind: MemoryKind | None = None,
        conversation_id: str | None = None,
    ) -> Memory | None:
        current = self.get(memory_id)
        if current is None:
            return None
        updated_content = current.content if content is None else content.strip()
        if not updated_content:
            raise MemoryValidationError("content must not be empty")
        updated_kind = current.kind if kind is None else kind
        if updated_content == current.content and updated_kind == current.kind:
            return current
        updated = Memory(
            id=current.id,
            content=updated_content,
            kind=updated_kind,
            provenance=current.provenance,
            source_conversation_id=current.source_conversation_id,
            created_at=current.created_at,
            updated_at=self._clock(),
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE memories
                SET content = ?, kind = ?, updated_at = ?
                WHERE id = ?
                """,
                (updated.content, updated.kind, updated.updated_at, updated.id),
            )
        self._notify(MemoryChange("updated", memory_id, conversation_id))
        return updated

    def delete(
        self, memory_id: str, *, conversation_id: str | None = None
    ) -> Memory | None:
        memory = self.get(memory_id)
        if memory is None:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._notify(MemoryChange("deleted", memory_id, conversation_id))
        return memory

    def remember_automatic(
        self,
        *,
        content: str,
        kind: Literal["preference", "fact"],
        evidence: str,
        source_conversation_id: str,
    ) -> Memory | None:
        """Persist only a directly supported, stable User fact or preference."""

        normalized_content = _normalized_claim(content)
        normalized_evidence = _normalized_claim(evidence)
        if not normalized_content or normalized_content not in normalized_evidence:
            return None
        rejected_markers = (
            " just kidding ",
            " joking ",
            " haha ",
            " lol ",
            " today ",
            " right now ",
            " this morning ",
            " this evening ",
            " feel sad ",
            " feel angry ",
            " feel tired ",
            " feel upset ",
            " feel stressed ",
        )
        padded_evidence = f" {normalized_evidence} "
        if any(marker in padded_evidence for marker in rejected_markers):
            return None
        stable_cues = (
            " i prefer ",
            " i like ",
            " i love ",
            " i dislike ",
            " i hate ",
            " i don t ",
            " i do not ",
            " i use ",
            " i work ",
            " i am ",
            " i m ",
            " my ",
        )
        if not any(cue in padded_evidence for cue in stable_cues):
            return None
        return self.remember(
            content=content,
            kind=kind,
            provenance="automatic",
            source_conversation_id=source_conversation_id,
        )

    def relevant(self, query: str, *, limit: int = 5) -> tuple[Memory, ...]:
        terms = _search_terms(query)
        if not terms:
            return ()
        scored = []
        for memory in self.list():
            score = len(terms & _search_terms(memory.content))
            if score:
                scored.append((score, memory.updated_at, memory))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return tuple(item[2] for item in scored[:limit])

    def context_instructions(self, query: str) -> str:
        memories = self.relevant(query)
        if not memories:
            return ""
        rendered = "\n".join(f"- {memory.content}" for memory in memories)
        return (
            "Relevant Memory about the User for this turn only:\n"
            f"{rendered}\n"
            "Use it only when it helps answer the current message. Do not expose "
            "Memory identifiers, provenance, or unrelated stored information."
        )

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    source_conversation_id TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def _notify(self, change: MemoryChange) -> None:
        if self._change_listener is not None:
            self._change_listener(change)

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> Memory:
        return Memory(
            id=str(row[0]),
            content=str(row[1]),
            kind=cast(MemoryKind, row[2]),
            provenance=cast(MemoryProvenance, row[3]),
            source_conversation_id=(None if row[4] is None else str(row[4])),
            created_at=cast(float, row[5]),
            updated_at=cast(float, row[6]),
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


def _normalized_claim(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


_SEARCH_STOP_WORDS = frozenset(
    {
        "a",
        "about",
        "am",
        "an",
        "and",
        "are",
        "do",
        "for",
        "i",
        "in",
        "is",
        "me",
        "my",
        "of",
        "the",
        "to",
        "what",
    }
)


def _search_terms(value: str) -> frozenset[str]:
    return frozenset(
        term
        for term in _normalized_claim(value).split()
        if len(term) > 1 and term not in _SEARCH_STOP_WORDS
    )


__all__ = [
    "Memory",
    "MemoryChange",
    "MemoryKind",
    "MemoryNotFoundError",
    "MemoryProvenance",
    "MemoryUpdates",
    "MemoryValidationError",
    "SQLiteMemoryService",
]
