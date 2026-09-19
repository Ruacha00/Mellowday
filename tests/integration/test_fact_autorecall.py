"""Integration: a stored fact reaches the model without any tool call.

This is the I22 acceptance that the unit tests cannot cover on their own: the
runtime recall logic was tested in isolation, but nothing proved the web layer
actually passes a fact_provider into the agent. Without this test the feature
looks finished while being dead code on the real path.
"""
from __future__ import annotations

import json

import pytest

from mellowday.storage.store import Store
from mellowday.web_app.service import SessionRegistry
# pytest puts this directory on sys.path (no __init__.py here), so the fake
# model transport is imported as a sibling module.
from test_p1_loop import _final, _text_chunks, scripted_model  # noqa: F401


FACT = "用户通常六点（18:00）下班。"


async def _store_fact(store: Store) -> None:
    from mellowday.personal_assistant.tools import execute_tool

    result = await execute_tool(
        store,
        "remember_fact",
        {"content": FACT, "label": "下班时间", "kind": "preference"},
    )
    assert json.loads(result)["ok"] is True


@pytest.mark.anyio
async def test_stored_fact_is_injected_without_a_tool_call(tmp_path, scripted_model):
    store = Store(data_dir=tmp_path / "data")
    await _store_fact(store)

    script = [_text_chunks("你通常六点下班。") + [_final("stop")]]
    created = scripted_model(script)

    registry = SessionRegistry(store=store)
    events = [event async for event in registry.run_turn("f1", "我几点下班")]

    # The turn must answer from the injected fact, not by calling a tool.
    assert not [e for e in events if e["type"] == "tool_start"], "recall must not need a tool call"

    assert len(created) >= 1
    first_messages = created[0].chat.completions.calls[0]["messages"]
    rendered = json.dumps(first_messages, ensure_ascii=False)
    assert FACT in rendered, "the stored fact must be present in the very first model request"


@pytest.mark.anyio
async def test_updated_fact_replaces_the_old_value_in_context(tmp_path, scripted_model):
    store = Store(data_dir=tmp_path / "data")
    await _store_fact(store)

    from mellowday.personal_assistant.tools import execute_tool

    memories = store.list_records("memories", include_done=False)
    memory_id = memories[0]["id"]
    updated = await execute_tool(
        store, "update_memory", {"id": memory_id, "content": "用户通常五点（17:00）下班。"}
    )
    assert json.loads(updated)["ok"] is True

    script = [_text_chunks("你通常五点下班。") + [_final("stop")]]
    created = scripted_model(script)

    registry = SessionRegistry(store=store)
    [event async for event in registry.run_turn("f2", "我几点下班")]

    rendered = json.dumps(created[0].chat.completions.calls[0]["messages"], ensure_ascii=False)
    assert "五点" in rendered
    assert "六点" not in rendered, "the superseded value must not reach the model"


@pytest.mark.anyio
async def test_forgotten_fact_disappears_from_context(tmp_path, scripted_model):
    store = Store(data_dir=tmp_path / "data")
    await _store_fact(store)

    from mellowday.personal_assistant.tools import execute_tool

    memory_id = store.list_records("memories", include_done=False)[0]["id"]
    forgotten = await execute_tool(store, "forget_memory", {"id": memory_id})
    assert json.loads(forgotten)["ok"] is True

    script = [_text_chunks("我不知道你的下班时间。") + [_final("stop")]]
    created = scripted_model(script)

    registry = SessionRegistry(store=store)
    [event async for event in registry.run_turn("f3", "我几点下班")]

    rendered = json.dumps(created[0].chat.completions.calls[0]["messages"], ensure_ascii=False)
    assert "18:00" not in rendered and "六点" not in rendered, "a forgotten fact must not be recalled"
