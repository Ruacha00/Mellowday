"""t22 (N6): a list tool must never answer "nothing here" because of a status word.

The reported defect: list_calendar(status="open") returned {"ok": true, "count": 0}
while the 09:30 standup really existed (status "scheduled"), so the model told the
user there was no schedule. A silent empty set from a tool is a wrong user-visible
statement, not a neutral result.

Fixed in mellowday.personal_assistant.tools: generic not-done/done words are
resolved, the applied filter is echoed back, and an unrecognised status word is a
structured invalid_arguments error that lists the type's real status words.

It lives under tests/runtime because t22 owns personal_assistant/tools.py and
tests/runtime/** - the business tool layer has no separate test directory in this
unit's path list.
"""
from __future__ import annotations

import json

import pytest

from mellowday.personal_assistant.tools import execute_tool, tool_definitions
from mellowday.storage.store import Store

#: kind -> (create tool, update tool, list tool, a status that counts as finished)
KINDS: dict[str, tuple[str, str, str, str]] = {
    "todos": ("create_todo", "update_todo", "list_todos", "done"),
    "calendar": ("create_calendar_event", "update_calendar_event", "list_calendar", "cancelled"),
    "reminders": ("create_reminder", "update_reminder", "list_reminders", "delivered"),
    "notes": ("create_note", "update_note", "list_notes", "archived"),
}
NOT_DONE_WORDS = ("open", "pending", "active", "todo", "未完成", "进行中")
DONE_WORDS = ("done", "completed", "已完成")


async def call(store: Store, name: str, arguments: dict) -> dict:
    return json.loads(await execute_tool(store, name, arguments))


async def seed_two(store: Store, kind: str) -> tuple[str, str]:
    """一条未完成记录 + 一条已完成记录，返回两个 id。"""
    create, update, _list_tool, done_status = KINDS[kind]
    live = await call(store, create, {"title": "活跃记录"})
    finished = await call(store, create, {"title": "已完成记录"})
    assert live["ok"] and finished["ok"]
    moved = await call(store, update, {"id": finished["id"], "status": done_status})
    assert moved["ok"] is True, moved
    return live["id"], finished["id"]


def titles(result: dict) -> list[str]:
    return [str(record.get("title")) for record in result.get("records") or []]


# --- 1. the reported defect --------------------------------------------------


@pytest.mark.anyio
async def test_a_scheduled_calendar_event_is_found_with_the_word_open():
    store = Store()
    created = await call(store, "create_calendar_event", {
        "title": "每日站会", "due_at": "2026-09-19T09:30:00+08:00",
    })
    assert created["ok"] is True

    naive = await call(store, "list_calendar", {"status": "open"})

    assert naive["ok"] is True
    assert naive["count"] == 1, naive
    assert titles(naive) == ["每日站会"]
    assert naive["status_filter"] == {"requested": "open", "applied": "not-done"}

    # 对照：同一份数据不传 status 也是这条记录（修复前 open 返回 0）
    plain = await call(store, "list_calendar", {})
    assert [record["id"] for record in plain["records"]] == [created["id"]]


@pytest.mark.anyio
@pytest.mark.parametrize("kind", sorted(KINDS))
async def test_every_generic_not_done_word_finds_the_live_record(kind: str):
    store = Store()
    _live_id, _finished_id = await seed_two(store, kind)
    list_tool = KINDS[kind][2]

    for word in NOT_DONE_WORDS:
        result = await call(store, list_tool, {"status": word})
        assert result["ok"] is True, (kind, word, result)
        assert "活跃记录" in titles(result), (kind, word, result)
        assert "已完成记录" not in titles(result), (kind, word, result)
        assert result["status_filter"] == {"requested": word, "applied": "not-done"}, result


@pytest.mark.anyio
@pytest.mark.parametrize("kind", sorted(KINDS))
async def test_every_generic_done_word_returns_the_finished_records(kind: str):
    store = Store()
    await seed_two(store, kind)
    list_tool = KINDS[kind][2]

    for word in DONE_WORDS:
        result = await call(store, list_tool, {"status": word})
        assert result["ok"] is True, (kind, word, result)
        assert "已完成记录" in titles(result), (kind, word, result)
        assert "活跃记录" not in titles(result), (kind, word, result)
        assert result["status_filter"] == {"requested": word, "applied": "done"}, result


# --- 2. an unknown word is a structured error, never an empty set ------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kind, words",
    [
        ("todos", ("open", "done", "cancelled")),
        ("calendar", ("scheduled", "cancelled", "done")),
        ("reminders", ("scheduled", "delivered", "dismissed", "cancelled", "expired")),
        ("notes", ("active", "archived")),
    ],
)
async def test_an_unknown_status_word_lists_the_legal_values(kind: str, words: tuple):
    store = Store()
    await seed_two(store, kind)
    list_tool = KINDS[kind][2]

    result = await call(store, list_tool, {"status": "soon"})

    assert result["ok"] is False
    assert result["error"] == "invalid_arguments"
    assert "可用状态" in result["message"]
    for word in words:
        assert word in result["message"], (kind, word, result["message"])
    assert "未完成" in result["message"], result["message"]
    assert "records" not in result, "错误结果不能顺带返回一个空集"


# --- 3. existing behaviour is unchanged --------------------------------------


@pytest.mark.anyio
async def test_no_status_include_done_and_exact_words_behave_as_before():
    store = Store()
    live = await call(store, "create_todo", {"title": "未完成"})
    finished = await call(store, "create_todo", {"title": "已完成"})
    await call(store, "update_todo", {"id": finished["id"], "status": "done"})

    # 不传 status：两条都在，且没有 status_filter 回显
    both = await call(store, "list_todos", {})
    assert sorted(titles(both)) == ["已完成", "未完成"]
    assert "status_filter" not in both

    # include_done=False：只剩未完成，并在结果里回显这个参数
    open_only = await call(store, "list_todos", {"include_done": False})
    assert titles(open_only) == ["未完成"]
    assert open_only["include_done"] is False

    # 精确状态词：cancelled 仍然精确匹配
    event = await call(store, "create_calendar_event", {"title": "客户复盘会"})
    await call(store, "update_calendar_event", {"id": event["id"], "status": "cancelled"})
    cancelled = await call(store, "list_calendar", {"status": "cancelled"})
    assert titles(cancelled) == ["客户复盘会"]
    assert cancelled["status_filter"] == {"requested": "cancelled", "applied": "cancelled"}

    # 精确状态词命不中时仍然可以是空集（那是真的没有这条记录）
    scheduled = await call(store, "list_calendar", {"status": "scheduled"})
    assert scheduled["ok"] is True and scheduled["count"] == 0
    assert scheduled["status_filter"] == {"requested": "scheduled", "applied": "scheduled"}

    # limit 仍然生效
    limited = await call(store, "list_todos", {"limit": 1})
    assert len(limited["records"]) == 1


@pytest.mark.anyio
async def test_the_memories_recall_contract_is_untouched():
    store = Store()
    active = await call(store, "remember_fact", {"content": "用户住在北京", "label": "住址"})
    stale = await call(store, "remember_fact", {"content": "用户住在上海", "label": "旧住址"})
    await call(store, "update_memory", {"id": stale["id"], "status": "expired"})

    recalled = await call(store, "recall_memories", {"query": ""})

    assert [record["id"] for record in recalled["memories"]] == [active["id"]]


# --- 4. the descriptions name the words per type -----------------------------


def test_the_list_descriptions_name_the_status_words_of_their_type():
    definitions = {tool["name"]: tool for tool in tool_definitions()}
    expected = {
        "list_todos": ("open", "done"),
        "list_calendar": ("scheduled", "cancelled", "done"),
        "list_reminders": ("scheduled", "delivered", "dismissed", "cancelled", "expired"),
        "list_notes": ("active", "archived"),
    }
    for tool_name, words in expected.items():
        description = definitions[tool_name]["input_schema"]["properties"]["status"]["description"]
        for word in words:
            assert word in description, (tool_name, word)
        assert "未完成" in description, tool_name
        assert "status_filter" in description, tool_name
