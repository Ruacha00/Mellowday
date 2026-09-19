"""Session persistence: runtime state, folded memory, the raw trace and tool artifacts.

Everything lives under mellowday.paths.sessions_dir() (runtime state and the raw
record) or mellowday.paths.data_dir() (the over-long tool results), never inside
the source tree. Four kinds of state are kept apart on purpose:

* `{session_id}.json` - the runtime message list. Context folding replaces it
  and the runtime auto-saves over it, so it only ever holds the *current*
  state of one session.
* `{session_id}.folded-memory.*` - the folded summaries; runtime state too.
* `{session_id}.trace.jsonl` - the append-only raw execution record: every
  user message, assistant text, tool call, tool result and error, in the order
  they happened. Nothing in the runtime ever rewrites, truncates or reorders it,
  which is what makes the original conversation recoverable after a fold. Long
  values are stored **complete**; a short preview and the original length travel
  next to them, so a display can stay bounded without anyone losing the original.
* `tool_results/{session_id}/{ref}.txt` - the complete text of one tool result
  that was too long to put in the conversation. The model is given a bounded
  placeholder carrying the ref and can page through the original with
  read_tool_artifact(); every read resolves inside that one session directory, so
  nothing here can address a file the runtime did not write itself.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from mellowday import paths

TRACE_SUFFIX = ".trace.jsonl"
"""Suffix of the append-only raw execution record of one session."""

TRACE_TEXT_LIMIT = 4000
"""How much of one text field a *display* view keeps; the record itself is complete.

The stored entry always carries the whole value (that is what makes a long tool
result JSON parseable again); this limit only shapes trace_entry_for_display(),
so a history page can render an entry without shipping megabytes to a browser.
"""

TRACE_PREVIEW_CHARS = 200
"""Leading characters stored next to a long value as a ready-made summary."""

TRACE_DISPLAY_NOTE = "[... display shortened: {omitted} of {total} chars are in the stored text ...]"
"""Marker the display view inserts where a long field was folded for reading."""

ARTIFACT_DIR_NAME = "tool_results"
"""Directory under the data directory holding the complete over-long tool results."""

ARTIFACT_SUFFIX = ".txt"
"""Suffix of one stored tool result."""

ARTIFACT_REF_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,200}")
"""A ref is a bare name, never a path: letters, digits, `_` and `-` only."""

ARTIFACT_PREVIEW_CHARS = 400
"""Leading characters of an artifact kept in its metadata, for a quick look."""

ARTIFACT_DEFAULT_CHARS = 4000
"""Characters returned by one read_tool_artifact call when no limit is given."""

ARTIFACT_MAX_CHARS = 20000
"""Upper bound of one read, so one call cannot pull in a whole huge result."""

TRACE_TEXT_FIELDS = ("text", "message", "result", "arguments")
"""Trace fields whose value is a string that must be bounded."""


def _session_dir() -> Path:
    return paths.sessions_dir()


def get_project_session_dir() -> Path:
    """Directory holding the folded-memory records of every session."""
    return paths.sessions_dir()


def save_session(session_id: str, data: dict[str, Any]) -> None:
    d = _session_dir()
    (d / f"{session_id}.json").write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


def save_folded_session_memory(session_id: str, record: dict[str, Any]) -> None:
    d = get_project_session_dir()
    line = json.dumps(record, ensure_ascii=False, default=str)
    with (d / f"{session_id}.folded-memory.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    (d / f"{session_id}.folded-memory.latest.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def load_session(session_id: str) -> dict[str, Any] | None:
    path = _session_dir() / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_sessions() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for f in _session_dir().glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "metadata" in data:
                results.append(data["metadata"])
        except Exception:
            pass
    return results


def get_latest_session_id() -> str | None:
    sessions = list_sessions()
    if not sessions:
        return None
    sessions.sort(key=lambda s: s.get("startTime", ""), reverse=True)
    return sessions[0].get("id")

# --------------------------------------------------------------------------
# Raw execution trace
# --------------------------------------------------------------------------
# One JSON object per line, appended for the lifetime of the session:
#
#   {"ts": 1758300000.123, "time": "2026-09-19T12:00:00Z", "turn": 2,
#    "type": "tool_call", "name": "create_todo", "arguments": "{\"title\": ...}"}
#
# The type is one of the record kinds the contract names:
#   user         the user message of this turn          -> text
#   message      assistant text produced in the turn    -> text, partial
#   assistant    the reply committed to the display     -> text
#   tool_call    a tool the model asked for             -> name, arguments (JSON text)
#   tool_result  what that tool returned                -> name, result
#   error        an error the turn produced             -> message, phase
#
# The record is written by appending only; folding the context, re-saving the
# runtime session and restarting the process never rewrite, truncate or reorder
# it. Every text field is stored *complete* - a truncated tool result is not
# even parseable JSON any more - and a long one additionally carries
# <field>_length and <field>_preview. Display code uses trace_entry_for_display()
# to get a bounded view without touching what is stored.


def trace_path(session_id: str) -> Path:
    """Path of the append-only execution record of one session."""
    return _session_dir() / f"{session_id}{TRACE_SUFFIX}"


def trace_record(kind: str, *, turn: int | None = None, **fields: Any) -> dict[str, Any]:
    """Build one trace entry, storing every text field complete.

    Nothing is shortened here: a 12,000 character tool result used to arrive as
    a head+tail preview that no longer parsed as JSON, which made the record
    useless as the source of truth. A long value now travels with
    <field>_length (the original length) and <field>_preview (its first
    characters); a reader that wants something short calls
    trace_entry_for_display(), and a reader that wants the original has it.
    """
    record: dict[str, Any] = {
        "ts": time.time(),
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "turn": turn,
        "type": str(kind),
    }
    for key, value in fields.items():
        if value is None:
            continue
        if key == "arguments" and isinstance(value, Mapping):
            # Stored as JSON text rather than a nested object: the record stays
            # one flat, greppable line per entry, and a reader can json.loads it.
            value = json.dumps(dict(value), ensure_ascii=False, default=str)
        if key in TRACE_TEXT_FIELDS and isinstance(value, str):
            record[key] = value
            if len(value) > TRACE_PREVIEW_CHARS:
                record[f"{key}_length"] = len(value)
                record[f"{key}_preview"] = value[:TRACE_PREVIEW_CHARS]
            continue
        record[key] = value
    return record


def trace_entry_for_display(
    entry: Mapping[str, Any], *, limit: int = TRACE_TEXT_LIMIT
) -> dict[str, Any]:
    """Return a bounded view of one entry for a history page.

    Long text fields are replaced by a head+tail preview with a marker in the
    middle, so the payload stays small and the reader can see that the stored
    entry still holds the whole value. The stored record is never modified.
    """
    view = dict(entry)
    shortened: list[str] = []
    for field in TRACE_TEXT_FIELDS:
        value = view.get(field)
        if not isinstance(value, str) or len(value) <= limit:
            continue
        note = TRACE_DISPLAY_NOTE.format(omitted=len(value) - limit, total=len(value))
        keep = max(1, (limit - len(note) - 8) // 2)
        omitted = len(value) - keep * 2
        note = TRACE_DISPLAY_NOTE.format(omitted=omitted, total=len(value))
        keep = max(1, (limit - len(note) - 8) // 2)
        view[field] = value[:keep] + "\n\n" + note + "\n\n" + value[-keep:]
        view[f"{field}_length"] = len(value)
        view.setdefault(f"{field}_preview", value[:TRACE_PREVIEW_CHARS])
        shortened.append(field)
    if shortened:
        view["display_shortened"] = shortened
    return view


def trace_for_display(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Shorthand for trace_entry_for_display() over a whole record."""
    return [trace_entry_for_display(entry) for entry in entries]


def append_trace(session_id: str, record: dict[str, Any]) -> bool:
    """Append one entry to the raw record; returns False when it could not.

    Appending is the only operation this module offers on the record, and it
    never raises into a conversation: a full disk must not break a turn.
    """
    try:
        path = trace_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False


def read_trace(session_id: str) -> list[dict[str, Any]]:
    """Every entry of the raw record, oldest first; unreadable lines are skipped."""
    path = trace_path(session_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    entries: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def delete_trace(session_id: str) -> bool:
    """Remove the raw record of a session; True when a file was deleted."""
    path = trace_path(session_id)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


def next_trace_turn(session_id: str) -> int:
    """Turn number the next turn of this session must use (1 when empty).

    Turn numbers therefore stay unique and ordered across a process restart,
    which is what lets a restored session append to the same record instead of
    reusing turn 1.
    """
    highest = 0
    for entry in read_trace(session_id):
        turn = entry.get("turn")
        if isinstance(turn, int) and turn > highest:
            highest = turn
    return highest + 1


# --------------------------------------------------------------------------
# Over-long tool results
# --------------------------------------------------------------------------
# One file per over-long tool result, kept under
#
#   data_dir()/tool_results/<session>/<ref>.txt
#
# The session directory is what scopes a read: a ref is resolved inside the
# caller's own directory only, so one session can never reach another session's
# artifacts, and no parameter ever becomes a filesystem path. A ref is a bare
# name (letters, digits, "_" and "-"), the file carries a random suffix and is
# created with mode "x", so an existing artifact is never overwritten - folding,
# auto-saving and restarting the process all leave it exactly as it was.


def tool_artifacts_dir() -> Path:
    """Directory holding every session's tool artifacts (created on demand)."""
    d = paths.data_dir() / ARTIFACT_DIR_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _artifact_name(value: object, *, fallback: str, limit: int) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "")).strip("-")
    return text[:limit] or fallback


def _artifact_dir_path(session_id: str) -> Path:
    """Where the artifacts of one session live (not created here)."""
    if not isinstance(session_id, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session_id) is None:
        raise ValueError("invalid session id: only [A-Za-z0-9_-]{1,64} is allowed")
    return tool_artifacts_dir() / session_id


def session_artifact_dir(session_id: str) -> Path:
    """Artifact directory of one session, created on demand (writing path)."""
    d = _artifact_dir_path(session_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_tool_artifact(
    session_id: str,
    tool_name: str,
    text: str,
    *,
    preview_chars: int = ARTIFACT_PREVIEW_CHARS,
) -> dict[str, Any]:
    """Store one complete tool result and return its reference.

    Returns {ref, path, chars, preview}. The write is exclusive and the name
    carries a random suffix, so two results of the same tool never collide and
    an existing artifact is never replaced.
    """
    payload = str(text)
    directory = session_artifact_dir(session_id)
    tool = _artifact_name(tool_name, fallback="tool", limit=40)
    for _ in range(5):
        ref = f"{int(time.time() * 1000)}-{tool}-{uuid.uuid4().hex[:8]}"
        path = directory / f"{ref}{ARTIFACT_SUFFIX}"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(payload)
        except FileExistsError:
            continue
        return {
            "ref": ref,
            "path": str(path),
            "chars": len(payload),
            "preview": payload[: max(0, int(preview_chars))],
        }
    raise OSError("could not allocate a free artifact name")


def read_tool_artifact(
    session_id: str,
    ref: str,
    *,
    offset: int = 0,
    limit: int = ARTIFACT_DEFAULT_CHARS,
    query: str | None = None,
) -> dict[str, Any]:
    """Read one stored tool result, by paging or around a searched passage.

    Restricted reference read: `ref` must be a bare name that this session's
    runtime produced, and the lookup is confined to that session's artifact
    directory. There is deliberately no path parameter, so this cannot be used
    to read an arbitrary file (that capability was removed from the assistant on
    purpose). A missing or foreign ref is reported as data, never raised.
    """
    name = str(ref or "").strip()
    if not ARTIFACT_REF_PATTERN.fullmatch(name):
        return {
            "ok": False,
            "error": "invalid_ref",
            "message": "ref 只能是字母、数字、下划线和连字符组成的名称，不是路径",
        }
    path = _artifact_dir_path(session_id) / f"{name}{ARTIFACT_SUFFIX}"
    if not path.is_file():
        return {
            "ok": False,
            "error": "unknown_ref",
            "message": f"本会话没有这个工具产物的 ref：{name}",
        }
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "error": "unreadable", "message": f"{type(exc).__name__}: {exc}"}

    total = len(text)
    if query is not None:
        needle = str(query)
        if not needle:
            return {"ok": False, "error": "invalid_arguments", "message": "query 不能为空"}
        index = text.find(needle)
        if index < 0:
            index = text.casefold().find(needle.casefold())
        if index < 0:
            return {
                "ok": False,
                "error": "not_found",
                "message": f"原文里没有找到 {needle!r}；可以用 offset 分页继续查看",
                "ref": name,
                "total_chars": total,
            }
        window = max(200, min(int(limit), ARTIFACT_MAX_CHARS))
        start = max(0, index - window // 2)
        end = min(total, start + window)
        start = max(0, end - window)
        return {
            "ok": True,
            "ref": name,
            "query": needle,
            "match_offset": index,
            "window_start": start,
            "window_end": end,
            "total_chars": total,
            "has_more_before": start > 0,
            "has_more_after": end < total,
            "text": text[start:end],
        }

    start = max(0, int(offset))
    window = max(1, min(int(limit), ARTIFACT_MAX_CHARS))
    if start >= total:
        return {
            "ok": True,
            "ref": name,
            "total_chars": total,
            "offset": start,
            "returned": 0,
            "next_offset": None,
            "has_more": False,
            "text": "",
            "note": "offset 已经到原文结尾",
        }
    end = min(total, start + window)
    return {
        "ok": True,
        "ref": name,
        "total_chars": total,
        "offset": start,
        "returned": end - start,
        "next_offset": end if end < total else None,
        "has_more": end < total,
        "text": text[start:end],
    }


def delete_tool_artifacts(session_id: str) -> int:
    """Remove every artifact one session produced; returns how many went away.

    Deleting a session must not leave its long tool results behind, so the
    session lifecycle calls this alongside delete_trace().
    """
    directory = _artifact_dir_path(session_id)
    if not directory.is_dir():
        return 0
    removed = 0
    for path in sorted(directory.glob(f"*{ARTIFACT_SUFFIX}")):
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    try:
        directory.rmdir()
    except OSError:
        pass
    return removed
