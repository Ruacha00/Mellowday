"""Local-time rendering shared by every user-facing surface.

Timestamps are stored in UTC; anything a person reads must be converted with
:func:`to_local_iso`. Keeping the rule in one module is deliberate: it was
previously implemented in the assistant tool payloads only, which let the web
records API hand out raw UTC while the chat surface showed local time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

__all__ = ["to_local_iso", "localize_record", "LOCAL_TIME_FIELD"]

LOCAL_TIME_FIELD = "due_at_local"


def to_local_iso(value: Any) -> str | None:
    """Render a stored UTC timestamp in the machine's local timezone.

    Returns None when the value is missing or not a parseable timestamp, so
    callers can simply omit the field.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().isoformat()


def localize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Copy a record and add the local rendering of its due_at, when present."""
    local = to_local_iso(record.get("due_at"))
    if local is None:
        return record
    return {**record, LOCAL_TIME_FIELD: local}
