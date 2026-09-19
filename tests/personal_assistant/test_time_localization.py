"""Regression tests for time localisation and prompt truthfulness.

Both behaviours were found broken by the real-model gate: due_at was shown to
the user in UTC (wrong by the timezone offset), and the memory section told the
model to use a tool that does not exist while leaking a filesystem path.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime

import pytest

from mellowday.personal_assistant.tools import execute_tool
from mellowday.runtime.prompt import build_system_prompt
from mellowday.storage.store import Store


def _run(store: Store, name: str, arguments: dict) -> dict:
    return json.loads(asyncio.run(execute_tool(store, name, arguments)))


def test_due_at_is_returned_in_local_time_alongside_utc(tmp_path):
    store = Store(data_dir=tmp_path / "data")
    created = _run(store, "create_todo", {"title": "复习", "due_at": "2026-09-19T19:00:00+08:00"})
    assert created["ok"] is True

    stored = created["record"]["due_at"]
    local = created["record"]["due_at_local"]

    # The stored instant stays UTC and comparable.
    assert stored == "2026-09-19T11:00:00+00:00"

    # The local rendering is the same instant, expressed with an offset.
    expected = datetime.fromisoformat(stored).astimezone().isoformat()
    assert local == expected
    assert datetime.fromisoformat(local) == datetime.fromisoformat(stored)

    listed = _run(store, "list_todos", {})
    assert listed["records"][0]["due_at_local"] == expected


def test_records_without_a_due_date_have_no_local_field(tmp_path):
    store = Store(data_dir=tmp_path / "data")
    created = _run(store, "create_note", {"title": "会议纪要"})
    assert "due_at_local" not in created["record"]


def test_current_time_reports_timezone(tmp_path):
    store = Store(data_dir=tmp_path / "data")
    payload = _run(store, "current_time", {})
    assert payload["ok"] is True
    assert payload["timezone"]
    assert payload["local"] and payload["utc"]


def test_system_prompt_states_local_time_and_timezone():
    prompt = build_system_prompt()
    assert "{{" not in prompt and "}}" not in prompt, "every placeholder must be substituted"
    assert "Current time:" in prompt
    assert "timezone" in prompt
    assert "due_at_local" in prompt


def test_memory_section_names_real_tools_and_hides_storage_path():
    prompt = build_system_prompt()
    assert "remember_fact" in prompt and "recall_memories" in prompt
    assert "Save to:" not in prompt, "the prompt must not leak a filesystem path"
