"""Transactional record storage for MellowDay.

Every business object the personal assistant manages - todos, calendar events,
reminders, notes and remembered facts - lives in one SQLite database so that the
web layer and the assistant always read the same source of truth.  The layout is
deliberately generic: a record carries the same columns for every kind, and the
kind column decides which lifecycle rules apply.

Writes are transactional and reversible.  Each of Store.create_record,
Store.update_record and Store.delete_record stores an operation row together
with the data needed to invert it.  Store.undo replays that inverse exactly
once: calling it again returns the very same result without touching the
database a second time.

An undo restores the state its own write left behind, so it is only applied
while the record still holds that state.  When a later write changed the same
record, the undo is refused instead (ok=False, error='conflict', plus a
displayable 'message'): a whole-row snapshot must never roll back a change
the user made after the operation.

Return shapes
-------------
Reads (list_records, get_record, search_records) return plain record
dictionaries.  Writes return the same record dictionary plus an "operation_id"
key that can be handed to undo.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mellowday import paths

__all__ = [
    "KINDS",
    "MEMORY_STATUSES",
    "DEFAULT_STATUS",
    "DONE_STATUSES",
    "Store",
]

#: Record kinds accepted by Store; anything else raises ValueError.
KINDS: tuple[str, ...] = ("todos", "calendar", "reminders", "notes", "memories")

_KIND_SET = frozenset(KINDS)
_KIND_OPTIONS = ", ".join(KINDS)

#: Status assigned to a new record when the caller does not supply one.
DEFAULT_STATUS: dict[str, str] = {
    "todos": "open",
    "calendar": "scheduled",
    "reminders": "scheduled",
    "notes": "active",
    "memories": "active",
}

#: Statuses meaning "this record is finished / no longer current".  They are
#: hidden when include_done=False and never enter memory recall.
DONE_STATUSES: dict[str, frozenset[str]] = {
    "todos": frozenset({"done", "completed", "cancelled", "archived", "deleted"}),
    "calendar": frozenset({"done", "completed", "cancelled", "archived", "deleted"}),
    "reminders": frozenset(
        {"done", "delivered", "dismissed", "cancelled", "expired", "deleted"}
    ),
    "notes": frozenset({"archived", "deleted"}),
    "memories": frozenset({"expired", "deleted", "superseded"}),
}

#: Lifecycle of a remembered fact.
MEMORY_STATUSES: frozenset[str] = frozenset({"active", "expired", "deleted"})

_RECORD_COLUMNS = (
    "id, kind, title, detail, due_at, status, created_at, updated_at, source, meta"
)
_WRITABLE_FIELDS = ("title", "detail", "due_at", "status", "source", "meta")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT,
    detail TEXT,
    due_at TEXT,
    status TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    source TEXT,
    meta TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS records_kind_created
    ON records(kind, created_at);

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    action TEXT NOT NULL,
    record_id TEXT NOT NULL,
    before TEXT,
    after TEXT,
    undone INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    result TEXT
);
"""


def _utc_now() -> str:
    """Current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _normalize_due_at(value: Any) -> str | None:
    """Normalize a deadline or start value to a UTC ISO 8601 string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(
                f"due_at must be an ISO 8601 date-time, got {value!r}"
            ) from exc
    else:
        raise ValueError("due_at must be a datetime, an ISO 8601 string or None")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _normalize_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string or None")
    text = value.strip()
    return text or None


def _normalize_meta(value: Any) -> str:
    """Return meta serialized as a JSON object string."""
    if value is None:
        return "{}"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "{}"
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise ValueError("meta string must contain a JSON object") from exc
    if not isinstance(value, Mapping):
        raise ValueError("meta must be a mapping or a JSON object string")
    payload = {str(key): item for key, item in value.items()}
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("meta must be JSON serializable") from exc


def _load_meta(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _like_pattern(token: str) -> str:
    escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


#: Fields an undo compares before it replaces a row.  A record's id, kind and
#: creation time never change, so they carry no conflict signal.
_CONFLICT_FIELDS = ("title", "detail", "due_at", "status", "source", "meta")

#: Field names as the management page prints them.
_FIELD_LABELS = {
    "title": "标题",
    "detail": "备注",
    "due_at": "时间",
    "status": "状态",
    "source": "来源",
    "meta": "附加信息",
}


def _decode_snapshot(raw: Any) -> dict[str, Any] | None:
    """Decode the before/after snapshot stored on an operation row."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _changed_fields(expected: Mapping[str, Any], current: Mapping[str, Any]) -> list[str]:
    """The mutable fields that differ between two snapshots of one record."""
    return sorted(
        field for field in _CONFLICT_FIELDS if expected.get(field) != current.get(field)
    )


def _undo_conflict(
    action: str,
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Describe what replaying this operation would overwrite, or None if safe.

    An undo restores the state its own write left behind, so it is only applied
    while the record still holds exactly that state.  A later write to the same
    record is a conflict: replaying the whole-row snapshot would silently roll
    that change back (edit a title, then edit the note detail, then undo the
    title edit - the detail used to be rolled back with it, without a word).
    """
    if action == "create":
        # The undo deletes the created row.  Nothing is destroyed when it is
        # already gone; a row that changed since the create must survive.
        if current is None or after is None or current == after:
            return None
        return {"reason": "record_changed", "changed_fields": _changed_fields(after, current)}
    if action == "update":
        if after is None:
            # No recorded expected state: keep the historical replay.
            return None
        if current is None:
            return {"reason": "record_deleted", "changed_fields": []}
        expected = after
    else:
        # delete: the undo re-inserts the snapshot taken before the deletion.
        if current is None or before is None:
            return None
        expected = before
    if current == expected:
        return None
    return {"reason": "record_changed", "changed_fields": _changed_fields(expected, current)}


def _conflict_message(action: str, reason: str, changed_fields: list[str]) -> str:
    """Human readable refusal; the web layer prints this string to the user."""
    if reason == "record_deleted":
        return (
            "撤销被拒绝：这条记录在本次操作之后已被删除，"
            "现在撤销会把旧内容重新写回去。请先撤销那次删除。"
        )
    labels = "、".join(_FIELD_LABELS.get(field, field) for field in changed_fields)
    what = f"（{labels}）" if labels else ""
    return (
        f"撤销被拒绝：这条记录在本次操作之后又被修改过{what}，"
        "本次撤销没有执行，后面的修改保持不变。请先撤销那次修改。"
    )


def _conflict_result(
    operation_id: str,
    action: str,
    kind: str,
    record_id: str,
    conflict: Mapping[str, Any],
    current: dict[str, Any] | None,
) -> dict[str, Any]:
    """Refusal payload: ok=False plus everything a UI needs to explain it."""
    reason = str(conflict.get("reason") or "record_changed")
    changed = [str(field) for field in conflict.get("changed_fields") or []]
    return {
        "ok": False,
        "error": "conflict",
        "operation_id": operation_id,
        "action": action,
        "kind": kind,
        "record_id": record_id,
        "undone": False,
        "record": None,
        "current_record": current,
        "reason": reason,
        "changed_fields": changed,
        "message": _conflict_message(action, reason, changed),
    }



class Store:
    """SQLite-backed record store with single-use undo.

    An undo is refused - ok=False, error="conflict" - when the record changed
    after the operation it would replay, so a later edit is never silently
    rolled back.  A refused operation is not consumed and stays undoable.

    Parameters
    ----------
    data_dir:
        Directory holding "mellowday.sqlite3".  Defaults to
        mellowday.paths.data_dir().
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        base = Path(data_dir) if data_dir is not None else paths.data_dir()
        base.mkdir(parents=True, exist_ok=True)
        self.data_dir = base
        self.path = base / "mellowday.sqlite3"
        self._initialize()

    # ------------------------------------------------------------ connections

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a short-lived connection; commit on success, roll back on error.

        A connection per call keeps the store usable from several threads and
        from both the web layer and the assistant loop without sharing a
        connection object across threads.
        """
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=30000")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    # ------------------------------------------------------------- validation

    @staticmethod
    def _check_kind(kind: str) -> str:
        if kind not in _KIND_SET:
            raise ValueError(
                f"unknown record kind: {kind!r}; expected one of {_KIND_OPTIONS}"
            )
        return kind

    def _prepare_data(
        self, kind: str, data: Mapping[str, Any], base: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Merge caller supplied fields over base into a storable row."""
        if not isinstance(data, Mapping):
            raise ValueError("record data must be a mapping")
        current: dict[str, Any] = dict(
            base
            if base is not None
            else {
                "title": None,
                "detail": None,
                "due_at": None,
                "status": DEFAULT_STATUS[kind],
                "source": None,
                "meta": {},
            }
        )
        prepared = dict(current)
        for field in _WRITABLE_FIELDS:
            if field not in data:
                continue
            value = data[field]
            if field == "meta":
                prepared["meta"] = _load_meta(_normalize_meta(value))
            elif field == "due_at":
                prepared["due_at"] = _normalize_due_at(value)
            elif field == "status":
                prepared["status"] = (
                    _normalize_text(value, "status") or DEFAULT_STATUS[kind]
                )
            else:
                prepared[field] = _normalize_text(value, field)
        return prepared

    # ------------------------------------------------------------------ writes

    def create_record(self, kind: str, data: Mapping[str, Any]) -> dict[str, Any]:
        """Insert a record and return it together with its operation_id."""
        kind = self._check_kind(kind)
        prepared = self._prepare_data(kind, data)
        now = _utc_now()
        record_id = uuid.uuid4().hex
        record = {
            "id": record_id,
            "kind": kind,
            "title": prepared["title"],
            "detail": prepared["detail"],
            "due_at": prepared["due_at"],
            "status": prepared["status"],
            "created_at": now,
            "updated_at": now,
            "source": prepared["source"],
            "meta": prepared["meta"],
        }
        operation_id = self._new_operation_id()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._insert_record(connection, record)
            self._insert_operation(
                connection, operation_id, kind, "create", record_id, None, record, now
            )
        return {**record, "operation_id": operation_id}

    def update_record(
        self, kind: str, record_id: str, data: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Patch a record and return the stored row plus its operation_id.

        Raises KeyError when the record does not exist.
        """
        kind = self._check_kind(kind)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select(connection, kind, record_id)
            if row is None:
                raise KeyError(record_id)
            before = self._row_to_record(row)
            prepared = self._prepare_data(kind, data, base=before)
            record = {
                **before,
                "title": prepared["title"],
                "detail": prepared["detail"],
                "due_at": prepared["due_at"],
                "status": prepared["status"],
                "source": prepared["source"],
                "meta": prepared["meta"],
                "updated_at": _utc_now(),
            }
            operation_id = self._new_operation_id()
            self._insert_record(connection, record, replace=True)
            self._insert_operation(
                connection,
                operation_id,
                kind,
                "update",
                record_id,
                before,
                record,
                record["updated_at"],
            )
        return {**record, "operation_id": operation_id}

    def delete_record(self, kind: str, record_id: str) -> dict[str, Any]:
        """Remove a record and return the deleted snapshot plus operation_id.

        Raises KeyError when the record does not exist.
        """
        kind = self._check_kind(kind)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._select(connection, kind, record_id)
            if row is None:
                raise KeyError(record_id)
            before = self._row_to_record(row)
            operation_id = self._new_operation_id()
            connection.execute(
                "DELETE FROM records WHERE kind = ? AND id = ?", (kind, record_id)
            )
            self._insert_operation(
                connection,
                operation_id,
                kind,
                "delete",
                record_id,
                before,
                None,
                _utc_now(),
            )
        return {**before, "operation_id": operation_id}

    # ------------------------------------------------------------------- reads

    def list_records(
        self, kind: str, *, include_done: bool = True
    ) -> list[dict[str, Any]]:
        """List records of one kind, newest first.

        include_done=False hides records whose status marks them as finished;
        for memories that means only active facts remain.
        """
        kind = self._check_kind(kind)
        statement = f"SELECT {_RECORD_COLUMNS} FROM records WHERE kind = ?"
        parameters: list[Any] = [kind]
        if not include_done:
            done = sorted(DONE_STATUSES[kind])
            placeholders = ", ".join("?" for _ in done)
            statement += f" AND lower(coalesce(status, '')) NOT IN ({placeholders})"
            parameters.extend(done)
        statement += " ORDER BY created_at DESC, id ASC"
        with self._connect() as connection:
            rows = connection.execute(statement, parameters).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_record(self, kind: str, record_id: str) -> dict[str, Any] | None:
        """Return one record, or None when it does not exist."""
        kind = self._check_kind(kind)
        with self._connect() as connection:
            row = self._select(connection, kind, record_id)
        return None if row is None else self._row_to_record(row)

    def search_records(self, kind: str, query: str) -> list[dict[str, Any]]:
        """Case-insensitive token search over title, detail and meta.

        Whitespace separated tokens must all match; each token may match any of
        the searchable fields.  Memory searches only ever return active facts,
        so expired or forgotten facts cannot be recalled.
        """
        kind = self._check_kind(kind)
        text = query.strip() if isinstance(query, str) else ""
        if not text:
            return self.list_records(kind, include_done=kind != "memories")
        tokens = [token.casefold() for token in text.split() if token]
        statement = f"SELECT {_RECORD_COLUMNS} FROM records WHERE kind = ?"
        parameters: list[Any] = [kind]
        for token in tokens:
            statement += (
                " AND (lower(coalesce(title, '')) LIKE ? ESCAPE '\\'"
                " OR lower(coalesce(detail, '')) LIKE ? ESCAPE '\\'"
                " OR lower(coalesce(meta, '')) LIKE ? ESCAPE '\\')"
            )
            pattern = _like_pattern(token)
            parameters.extend((pattern, pattern, pattern))
        if kind == "memories":
            statement += " AND lower(coalesce(status, 'active')) = 'active'"
        statement += " ORDER BY created_at DESC, id ASC"
        with self._connect() as connection:
            rows = connection.execute(statement, parameters).fetchall()
        return [self._row_to_record(row) for row in rows]

    # -------------------------------------------------------------------- undo

    def undo(self, operation_id: str) -> dict[str, Any]:
        """Invert one write operation exactly once.

        The first call applies the inverse (removing a created record or
        restoring a previous snapshot) and returns a result describing it.
        Repeating the call returns that same stored result without touching the
        data again, so the operation is idempotent.

        The inverse is only applied while the record still holds the state this
        operation left behind.  When a later write changed the record, the undo
        is refused: it returns ok=False with error="conflict", a machine
        readable "reason", the "changed_fields" and a user facing "message"
        (plus the current row, so a UI can refresh).  The refusal writes
        nothing and leaves the operation undoable, so it can be retried after
        the later change has been undone first.
        """
        if not isinstance(operation_id, str) or not operation_id:
            return {
                "ok": False,
                "error": "unknown_operation_id",
                "operation_id": operation_id,
            }
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if row is None:
                return {
                    "ok": False,
                    "error": "unknown_operation_id",
                    "operation_id": operation_id,
                }
            if row["undone"]:
                stored = row["result"]
                if stored:
                    return json.loads(stored)
                return {
                    "ok": True,
                    "operation_id": operation_id,
                    "action": str(row["action"]),
                    "kind": str(row["kind"]),
                    "record_id": str(row["record_id"]),
                    "undone": True,
                    "record": None,
                }
            action = str(row["action"])
            kind = str(row["kind"])
            record_id = str(row["record_id"])
            before = _decode_snapshot(row["before"])
            after = _decode_snapshot(row["after"])
            existing = self._select(connection, kind, record_id)
            current = None if existing is None else self._row_to_record(existing)

            conflict = _undo_conflict(
                action, before=before, after=after, current=current
            )
            if conflict is not None:
                # Refuse instead of replaying a stale snapshot: the row no
                # longer holds the state this operation left behind, so the
                # inverse would roll back a change made after it.  Nothing is
                # written and "undone" stays 0, so the operation can still be
                # undone once the later change has been undone first.
                return _conflict_result(
                    operation_id, action, kind, record_id, conflict, current
                )

            record: dict[str, Any] | None = None
            if action == "create":
                record = current
                connection.execute(
                    "DELETE FROM records WHERE kind = ? AND id = ?", (kind, record_id)
                )
            elif before is not None:
                record = dict(before)
                self._insert_record(connection, record, replace=True)
            result = {
                "ok": True,
                "operation_id": operation_id,
                "action": action,
                "kind": kind,
                "record_id": record_id,
                "undone": True,
                "record": record,
            }
            connection.execute(
                "UPDATE operations SET undone = 1, result = ? WHERE operation_id = ?",
                (json.dumps(result, ensure_ascii=False), operation_id),
            )
        return result

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _new_operation_id() -> str:
        return "op_" + uuid.uuid4().hex

    @staticmethod
    def _select(
        connection: sqlite3.Connection, kind: str, record_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            f"SELECT {_RECORD_COLUMNS} FROM records WHERE kind = ? AND id = ?",
            (kind, record_id),
        ).fetchone()

    @staticmethod
    def _insert_record(
        connection: sqlite3.Connection,
        record: Mapping[str, Any],
        *,
        replace: bool = False,
    ) -> None:
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        connection.execute(
            f"""
            {verb} INTO records (
                id, kind, title, detail, due_at, status,
                created_at, updated_at, source, meta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["id"],
                record["kind"],
                record.get("title"),
                record.get("detail"),
                record.get("due_at"),
                record.get("status"),
                record["created_at"],
                record["updated_at"],
                record.get("source"),
                json.dumps(
                    record.get("meta") or {}, ensure_ascii=False, sort_keys=True
                ),
            ),
        )

    @staticmethod
    def _insert_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        kind: str,
        action: str,
        record_id: str,
        before: Mapping[str, Any] | None,
        after: Mapping[str, Any] | None,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO operations (
                operation_id, kind, action, record_id, before, after,
                undone, created_at, result
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL)
            """,
            (
                operation_id,
                kind,
                action,
                record_id,
                None
                if before is None
                else json.dumps(before, ensure_ascii=False, sort_keys=True),
                None
                if after is None
                else json.dumps(after, ensure_ascii=False, sort_keys=True),
                created_at,
            ),
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "kind": str(row["kind"]),
            "title": row["title"],
            "detail": row["detail"],
            "due_at": row["due_at"],
            "status": row["status"],
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "source": row["source"],
            "meta": _load_meta(row["meta"]),
        }
