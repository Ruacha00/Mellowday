"""Contract tests for the business tool layer (I06).

The tools must be declared for the runtime, write through the shared store and
answer every failure as a JSON payload instead of raising.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from mellowday.personal_assistant.tools import execute_tool, tool_definitions
from mellowday.storage.store import Store

EXPECTED_TOOLS = {
    "list_todos",
    "create_todo",
    "update_todo",
    "delete_todo",
    "list_calendar",
    "create_calendar_event",
    "update_calendar_event",
    "delete_calendar_event",
    "list_reminders",
    "create_reminder",
    "update_reminder",
    "delete_reminder",
    "list_notes",
    "create_note",
    "update_note",
    "delete_note",
    "remember_fact",
    "recall_memories",
    "update_memory",
    "forget_memory",
    "current_time",
}

CRUD_TOOLS = [
    ("todos", "create_todo", "list_todos", "update_todo", "delete_todo"),
    ("calendar", "create_calendar_event", "list_calendar", "update_calendar_event", "delete_calendar_event"),
    ("reminders", "create_reminder", "list_reminders", "update_reminder", "delete_reminder"),
    ("notes", "create_note", "list_notes", "update_note", "delete_note"),
]

FORBIDDEN_FRAGMENTS = ("shell", "bash", "exec", "file", "read_file", "write_file", "code", "python")


async def _call(store: Store, name: str, arguments: dict) -> dict:
    raw = await execute_tool(store, name, arguments)
    assert isinstance(raw, str)
    payload = json.loads(raw)
    assert isinstance(payload, dict)
    assert isinstance(payload.get("ok"), bool)
    return payload


# ------------------------------------------------------------------ definitions

def test_tool_definitions_match_contract() -> None:
    definitions = tool_definitions()
    names = [definition["name"] for definition in definitions]
    assert set(names) == EXPECTED_TOOLS
    assert len(names) == len(set(names))

    for definition in definitions:
        assert set(definition) == {"name", "description", "input_schema"}
        assert definition["name"].islower()
        assert definition["description"].strip()
        schema = definition["input_schema"]
        assert schema["type"] == "object"
        assert isinstance(schema["properties"], dict)
        assert not any(fragment in definition["name"] for fragment in FORBIDDEN_FRAGMENTS)
        # Every definition must be JSON serializable for the model request.
        json.dumps(definition, ensure_ascii=False)


def test_tool_definitions_are_copied() -> None:
    first = tool_definitions()
    first[0]["name"] = "mutated"
    assert tool_definitions()[0]["name"] != "mutated"


def test_required_fields_are_declared() -> None:
    by_name = {definition["name"]: definition for definition in tool_definitions()}
    assert by_name["create_todo"]["input_schema"]["required"] == ["title"]
    assert by_name["delete_todo"]["input_schema"]["required"] == ["id"]
    assert by_name["remember_fact"]["input_schema"]["required"] == ["content"]
    assert by_name["current_time"]["input_schema"]["properties"] == {}


# ------------------------------------------------------------------------ CRUD

@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind,create_name,list_name,update_name,delete_name", CRUD_TOOLS
)
async def test_create_list_update_delete_round_trip(
    kind: str, create_name: str, list_name: str, update_name: str, delete_name: str
) -> None:
    store = Store()

    created = await _call(store, create_name, {"title": "标题", "detail": "内容"})
    assert created["ok"] is True
    record_id = created["id"]
    assert isinstance(record_id, str) and record_id
    assert created["operation_id"].startswith("op_")
    # The row really landed in the shared store.
    assert store.get_record(kind, record_id) is not None

    listed = await _call(store, list_name, {})
    assert listed["ok"] is True
    assert [record["id"] for record in listed["records"]] == [record_id]

    updated = await _call(store, update_name, {"id": record_id, "title": "新标题", "status": "done"})
    assert updated["ok"] is True
    assert updated["record"]["title"] == "新标题"
    assert store.get_record(kind, record_id)["title"] == "新标题"

    deleted = await _call(store, delete_name, {"id": record_id})
    assert deleted["ok"] is True
    assert deleted["deleted"] is True
    assert deleted["record"]["id"] == record_id
    assert store.get_record(kind, record_id) is None

    # The reported operation is what makes the deletion reversible.
    undone = store.undo(deleted["operation_id"])
    assert undone["ok"] is True
    assert store.get_record(kind, record_id) is not None


@pytest.mark.anyio
async def test_due_at_and_meta_reach_the_store() -> None:
    store = Store()
    created = await _call(
        store,
        "create_reminder",
        {
            "title": "吃药",
            "due_at": "2026-09-20T09:00:00+08:00",
            "meta": {"repeat": "daily"},
        },
    )
    assert created["ok"] is True
    stored = store.get_record("reminders", created["id"])
    assert stored["due_at"] == "2026-09-20T01:00:00+00:00"
    assert stored["meta"] == {"repeat": "daily"}


# ------------------------------------------------------------------- failures

@pytest.mark.anyio
async def test_invalid_input_never_raises() -> None:
    store = Store()
    cases = [
        ("create_todo", {}),
        ("create_todo", {"title": "   "}),
        ("create_todo", {"title": 42}),
        ("create_todo", {"title": "x", "due_at": "not-a-date"}),
        ("update_todo", {}),
        ("update_todo", {"id": "missing"}),
        ("update_todo", {"id": "missing", "title": "x"}),
        ("delete_todo", {}),
        ("delete_todo", {"id": "missing"}),
        ("list_todos", {"limit": 0}),
        ("list_todos", {"limit": "many"}),
        ("list_todos", {"include_done": "yes"}),
        ("create_note", {"title": "x", "meta": "not-json"}),
        ("remember_fact", {}),
        ("remember_fact", {"content": "x", "kind": "nonsense"}),
        ("update_memory", {"id": "missing", "status": "active"}),
        ("update_memory", {"id": "missing", "status": "wrong"}),
        ("recall_memories", {"limit": -3}),
        ("forget_memory", {}),
        ("forget_memory", {"id": "missing"}),
        ("no_such_tool", {}),
    ]
    for name, arguments in cases:
        payload = await _call(store, name, arguments)
        assert payload["ok"] is False, (name, arguments)
        assert isinstance(payload["error"], str) and payload["error"]
        assert isinstance(payload.get("message"), str)

    # Not-an-object arguments and a missing store are reported too.
    raw = await execute_tool(store, "create_note", None)  # type: ignore[arg-type]
    assert json.loads(raw)["ok"] is False
    raw = await execute_tool("not-a-store", "list_todos", {})  # type: ignore[arg-type]
    assert json.loads(raw)["ok"] is False


@pytest.mark.anyio
async def test_unknown_tool_is_reported_by_name() -> None:
    store = Store()
    payload = await _call(store, "run_shell", {"command": "rm -rf /"})
    assert payload["ok"] is False
    assert payload["error"] == "unknown_tool"


# --------------------------------------------------------------------- memory

@pytest.mark.anyio
async def test_remember_recall_and_forget() -> None:
    store = Store()

    remembered = await _call(
        store, "remember_fact", {"content": "用户喜欢无糖咖啡", "kind": "preference"}
    )
    assert remembered["ok"] is True
    memory_id = remembered["id"]
    assert store.get_record("memories", memory_id)["detail"] == "用户喜欢无糖咖啡"

    recalled = await _call(store, "recall_memories", {"query": "咖啡"})
    assert recalled["ok"] is True
    assert [memory["id"] for memory in recalled["memories"]] == [memory_id]
    assert recalled["count"] == 1

    browsed = await _call(store, "recall_memories", {})
    assert [memory["id"] for memory in browsed["memories"]] == [memory_id]

    forgotten = await _call(store, "forget_memory", {"id": memory_id})
    assert forgotten["ok"] is True
    assert forgotten["forgotten"] is True
    assert forgotten["operation_id"].startswith("op_")

    assert (await _call(store, "recall_memories", {"query": "咖啡"}))["memories"] == []
    assert (await _call(store, "recall_memories", {}))["memories"] == []

    # Forgetting is reversible through the reported operation.
    assert store.undo(forgotten["operation_id"])["ok"] is True
    assert [memory["id"] for memory in (await _call(store, "recall_memories", {}))["memories"]] == [
        memory_id
    ]


@pytest.mark.anyio
async def test_update_memory_replaces_recalled_value() -> None:
    store = Store()
    remembered = await _call(store, "remember_fact", {"content": "用户住北京"})
    memory_id = remembered["id"]

    updated = await _call(
        store, "update_memory", {"id": memory_id, "content": "用户住上海"}
    )
    assert updated["ok"] is True
    assert updated["record"]["detail"] == "用户住上海"

    assert (await _call(store, "recall_memories", {"query": "北京"}))["memories"] == []
    assert [memory["id"] for memory in (await _call(store, "recall_memories", {"query": "上海"}))["memories"]] == [
        memory_id
    ]

    expired = await _call(store, "update_memory", {"id": memory_id, "status": "expired"})
    assert expired["ok"] is True
    assert (await _call(store, "recall_memories", {}))["memories"] == []


# ---------------------------------------------------------------------- clock

@pytest.mark.anyio
async def test_current_time_returns_iso_timestamps() -> None:
    store = Store()
    payload = await _call(store, "current_time", {})
    assert payload["ok"] is True
    assert datetime.fromisoformat(payload["iso"]).tzinfo is not None
    assert datetime.fromisoformat(payload["local"]).tzinfo is not None
    assert payload["weekday"].startswith("星期")


@pytest.mark.anyio
async def test_tools_never_reach_outside_the_store(isolated_data_dir: Path) -> None:
    store = Store()
    await _call(store, "create_todo", {"title": "只写数据库"})
    # The only file the tool layer may create is the store's SQLite database.
    written = sorted(path.name for path in isolated_data_dir.iterdir())
    assert set(written) <= {"mellowday.sqlite3", "mellowday.sqlite3-wal", "mellowday.sqlite3-shm"}
