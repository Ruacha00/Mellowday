"""Fact provider and recall_memories tests (I22).

The business layer exposes the SQLite "memories" records to the runtime through
build_fact_provider(store). These tests pin down what that provider returns and
that both recall paths work for Chinese input, which carries no whitespace.
"""
from __future__ import annotations

import json

import pytest

from mellowday.personal_assistant.tools import build_fact_provider, execute_tool
from mellowday.storage.store import Store


async def _call(store: Store, name: str, arguments: dict) -> dict:
    payload = json.loads(await execute_tool(store, name, arguments))
    assert isinstance(payload, dict)
    return payload


async def _remember(store: Store, content: str, label: str | None = None) -> str:
    payload = await _call(store, "remember_fact", {"content": content, "label": label})
    assert payload["ok"] is True
    return payload["id"]


# --- provider ---------------------------------------------------------------

@pytest.mark.anyio
async def test_provider_returns_active_facts_only() -> None:
    store = Store()
    kept = await _remember(store, "用户每天 18:00 下班", "下班时间")
    expired = await _remember(store, "用户以前养过猫", "旧宠物")
    forgotten = await _remember(store, "用户旧手机号是 12345", "旧号码")
    await _call(store, "update_memory", {"id": expired, "status": "expired"})
    await _call(store, "forget_memory", {"id": forgotten})

    provider = build_fact_provider(store)
    candidates = await provider("我几点下班")

    assert [record["id"] for record in candidates] == [kept]
    assert all(record["status"] == "active" for record in candidates)
    assert all(set(record) >= {"id", "title", "detail", "status"} for record in candidates)


@pytest.mark.anyio
async def test_provider_ranks_chinese_input_without_whitespace() -> None:
    store = Store()
    work = await _remember(store, "用户每天 18:00 下班", "下班时间")
    await _remember(store, "用户不喜欢咖啡", "饮品偏好")

    provider = build_fact_provider(store)
    candidates = await provider("我几点下班")      # 中文，没有空格

    assert [record["id"] for record in candidates] == [work]


@pytest.mark.anyio
async def test_provider_reflects_updates_and_deletions() -> None:
    store = Store()
    memory_id = await _remember(store, "用户住在北京", "居住地")
    provider = build_fact_provider(store)

    assert "北京" in json.dumps(await provider("我住在哪里"), ensure_ascii=False)

    updated = await _call(store, "update_memory", {"id": memory_id, "content": "用户住在上海"})
    assert updated["ok"] is True
    after_update = json.dumps(await provider("我住在哪里"), ensure_ascii=False)
    assert "上海" in after_update
    assert "北京" not in after_update

    forgotten = await _call(store, "forget_memory", {"id": memory_id})
    assert forgotten["ok"] is True
    assert await provider("我住在哪里") == []


@pytest.mark.anyio
async def test_provider_without_facts_returns_an_empty_list() -> None:
    store = Store()
    provider = build_fact_provider(store)
    assert await provider("我几点下班") == []
    assert await provider("") == []


def test_provider_factory_rejects_a_non_store() -> None:
    with pytest.raises(TypeError):
        build_fact_provider("not-a-store")  # type: ignore[arg-type]


# --- recall_memories tool ---------------------------------------------------

@pytest.mark.anyio
async def test_recall_memories_tool_handles_chinese_without_whitespace() -> None:
    store = Store()
    memory_id = await _remember(store, "用户每天 18:00 下班", "下班时间")
    await _remember(store, "用户不喜欢咖啡", "饮品偏好")

    payload = await _call(store, "recall_memories", {"query": "我几点下班"})

    assert payload["ok"] is True
    assert [memory["id"] for memory in payload["memories"]] == [memory_id]
    assert payload["count"] == 1

    # 没有词项命中的查询不会凭空返回事实。
    miss = await _call(store, "recall_memories", {"query": "今天下午的安排"})
    assert miss["memories"] == []


@pytest.mark.anyio
async def test_recall_memories_tool_only_returns_active_facts() -> None:
    store = Store()
    memory_id = await _remember(store, "用户每天 18:00 下班", "下班时间")

    assert len((await _call(store, "recall_memories", {}))["memories"]) == 1

    expired = await _call(store, "update_memory", {"id": memory_id, "status": "expired"})
    assert expired["ok"] is True

    assert (await _call(store, "recall_memories", {}))["memories"] == []
    assert (await _call(store, "recall_memories", {"query": "我几点下班"}))["memories"] == []

    # 恢复为 active 后重新可以被召回（管理面可以救回被停用的事实）。
    restored = await _call(store, "update_memory", {"id": memory_id, "status": "active"})
    assert restored["ok"] is True
    assert [m["id"] for m in (await _call(store, "recall_memories", {"query": "我几点下班"}))["memories"]] == [memory_id]
