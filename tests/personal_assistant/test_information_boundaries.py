"""Explicit memory routing and source-snapshot migration, without text heuristics."""
import json

import pytest

from mellowday.personal_assistant.tools import (
    build_fact_provider,
    execute_tool,
    supersede_rule_facts,
    tool_definitions,
)
from mellowday.storage.store import Store


@pytest.mark.anyio
async def test_workflow_routing_rejects_fact_write():
    store = Store()
    result = json.loads(await execute_tool(store, "remember_fact", {
        "content": "先检查固定日程，再列三个重点任务", "kind": "workflow",
    }))
    assert result["ok"] is False
    assert result["error"] == "workflow_requires_skill"
    assert result["suggested_tools"] == ["skill_create", "skill_evolve"]
    assert store.list_records("memories") == []
    definition = next(d for d in tool_definitions() if d["name"] == "remember_fact")
    assert "workflow" in definition["input_schema"]["properties"]["kind"]["enum"]


@pytest.mark.anyio
async def test_fact_and_preference_remain_valid_with_procedural_words():
    store = Store()
    ids = []
    for content, kind in [
        ("我每个工作日六点下班，之后去运动", "fact"),
        ("我喜欢先喝咖啡再吃早饭", "preference"),
    ]:
        result = json.loads(await execute_tool(store, "remember_fact", {
            "content": content, "kind": kind,
        }))
        assert result["ok"] is True
        ids.append(result["id"])
    assert {f["id"] for f in await build_fact_provider(store)("")} == set(ids)


def _source(store):
    return store.create_record("memories", {
        "title": "旧流程", "detail": "先列日程，再排三个重点",
        "meta": {"memory_kind": "preference"},
    })


def test_explicit_migration_changes_only_unchanged_selected_snapshot():
    store = Store()
    source = _source(store)
    other = _source(store)
    changed = supersede_rule_facts(store, [source], skill="daily-plan")
    assert [f["id"] for f in changed] == [source["id"]]
    current = store.get_record("memories", source["id"])
    assert current["status"] == "superseded"
    assert current["meta"]["superseded_by_skill"] == "daily-plan"
    assert store.get_record("memories", other["id"])["status"] == "active"
    assert supersede_rule_facts(store, [source], skill="daily-plan") == []


@pytest.mark.parametrize("change", [
    {"title": "新的标题"},
    {"detail": "工作日六点下班"},
    {"meta": {"memory_kind": "fact"}},
    {"status": "deleted"},
])
def test_migration_does_not_apply_confirmation_to_changed_record(change):
    store = Store()
    source = _source(store)
    store.update_record("memories", source["id"], change)
    assert supersede_rule_facts(store, [source], skill="daily-plan") == []
    current = store.get_record("memories", source["id"])
    for key, value in change.items():
        assert current[key] == value


def test_id_alone_or_missing_target_does_not_authorize_migration():
    store = Store()
    source = _source(store)
    assert supersede_rule_facts(store, [{"id": source["id"]}], skill="daily-plan") == []
    assert supersede_rule_facts(store, [source], skill="") == []
    assert store.get_record("memories", source["id"])["status"] == "active"


@pytest.mark.anyio
async def test_ordinary_correction_and_forgetting_work_but_manual_supersession_does_not():
    store = Store()
    source = _source(store)
    migration = json.loads(await execute_tool(store, "update_memory", {
        "id": source["id"], "status": "superseded",
    }))
    assert migration["ok"] is False
    assert store.get_record("memories", source["id"])["status"] == "active"
    corrected = json.loads(await execute_tool(store, "update_memory", {
        "id": source["id"], "content": "现在下午五点下班",
    }))
    assert corrected["ok"] is True
    assert corrected["record"]["detail"] == "现在下午五点下班"
    forgotten = json.loads(await execute_tool(store, "forget_memory", {"id": source["id"]}))
    assert forgotten["ok"] is True
    assert forgotten["record"]["status"] == "deleted"
    assert await build_fact_provider(store)("") == []
