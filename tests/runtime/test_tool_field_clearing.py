"""Clearing a field from a chat tool must work the same way as from the page.

The management page clears a value by sending detail: "" or due_at: null, which
Store normalizes to NULL. The chat tools used to swallow an empty value as "not
supplied", so "把备注清空" changed nothing, and clearing a single field raised
missing_argument ("至少需要提供 ... 之一"). Both are fixed in
mellowday.personal_assistant.tools; this file is the behaviour-level check that
a cleared field is really NULL when the store reads it back.

It lives under tests/runtime because t2 owns runtime/agent.py,
personal_assistant/tools.py and tests/runtime/** - the business tool layer has no
separate test directory of its own in this unit's path list.
"""
from __future__ import annotations

import json

import pytest

from mellowday.personal_assistant.tools import execute_tool, tool_definitions
from mellowday.storage.store import Store


async def call(store: Store, name: str, arguments: dict) -> dict:
    return json.loads(await execute_tool(store, name, arguments))


def tool_named(name: str) -> dict:
    return next(tool for tool in tool_definitions() if tool["name"] == name)


KIND_TOOLS = (
    ("todos", "create_todo", "update_todo"),
    ("calendar", "create_calendar_event", "update_calendar_event"),
    ("reminders", "create_reminder", "update_reminder"),
    ("notes", "create_note", "update_note"),
)


@pytest.mark.anyio
async def test_a_chat_tool_can_clear_the_detail_of_every_kind():
    store = Store()
    for kind, create_tool, update_tool in KIND_TOOLS:
        created = await call(store, create_tool, {"title": "标题", "detail": "原始备注"})
        assert created["ok"] is True, created
        record_id = created["id"]

        cleared = await call(store, update_tool, {"id": record_id, "detail": ""})
        assert cleared["ok"] is True, cleared
        assert store.get_record(kind, record_id)["detail"] is None, kind

        # 只清一个字段不能再被当成「什么都没提供」
        again = await call(store, update_tool, {"id": record_id, "detail": "重新写上的备注"})
        assert again["ok"] is True
        restored = await call(store, update_tool, {"id": record_id, "detail": None})
        assert restored["ok"] is True
        assert store.get_record(kind, record_id)["detail"] is None


@pytest.mark.anyio
async def test_a_chat_tool_can_clear_a_due_date_without_touching_the_title():
    store = Store()
    created = await call(store, "create_todo", {
        "title": "交周报", "detail": "记得带上数据", "due_at": "2026-09-20T09:00:00+08:00",
    })
    record_id = created["id"]
    assert store.get_record("todos", record_id)["due_at"] is not None

    cleared = await call(store, "update_todo", {"id": record_id, "due_at": None})
    assert cleared["ok"] is True, cleared
    record = store.get_record("todos", record_id)
    assert record["due_at"] is None
    assert record["title"] == "交周报" and record["detail"] == "记得带上数据"

    # 空字符串与管理页的 null 等价
    await call(store, "update_todo", {"id": record_id, "due_at": "2026-09-21T09:00:00+08:00"})
    await call(store, "update_todo", {"id": record_id, "due_at": ""})
    assert store.get_record("todos", record_id)["due_at"] is None


@pytest.mark.anyio
async def test_absent_fields_are_still_left_untouched():
    store = Store()
    created = await call(store, "create_note", {"title": "会议纪要", "detail": "第一版"})
    record_id = created["id"]

    updated = await call(store, "update_note", {"id": record_id, "status": "archived"})
    assert updated["ok"] is True
    record = store.get_record("notes", record_id)
    assert record["status"] == "archived"
    assert record["detail"] == "第一版", "没有出现的字段不得被清空"


@pytest.mark.anyio
async def test_an_update_without_any_field_still_reports_a_missing_argument():
    store = Store()
    created = await call(store, "create_todo", {"title": "只有标题"})
    result = await call(store, "update_todo", {"id": created["id"]})
    assert result["ok"] is False
    assert result["error"] == "missing_argument"


@pytest.mark.anyio
async def test_a_bad_type_is_still_rejected_rather_than_treated_as_clearing():
    store = Store()
    created = await call(store, "create_todo", {"title": "类型校验"})
    result = await call(store, "update_todo", {"id": created["id"], "detail": 123})
    assert result["ok"] is False
    assert result["error"] == "invalid_arguments"
    assert store.get_record("todos", created["id"])["detail"] is None


def test_the_tool_descriptions_tell_the_model_how_to_clear():
    for name in ("update_todo", "update_note", "update_reminder"):
        assert "清空" in tool_named(name)["description"]
    assert "清空" in tool_named("update_calendar_event")["description"]
    detail = tool_named("update_note")["input_schema"]["properties"]["detail"]["description"]
    due = tool_named("update_todo")["input_schema"]["properties"]["due_at"]["description"]
    assert "空字符串" in detail
    assert "null" in due
