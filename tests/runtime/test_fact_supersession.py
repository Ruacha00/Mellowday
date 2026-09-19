"""D: an invalidated fact must never be handed over as the current one.

History keeps what really happened: an assistant reply that quoted a fact value,
a tool result that returned it and a folded summary that describes it are never
rewritten. What the runtime owns is a second thing - the values it actually
handed to the model - and when one of those is updated or deleted, the old value
is listed in the same per-turn injection as "not current any more", with the
replacement and the time. That is the minimal "current value / source /
invalidation" relation the round asked for, not a knowledge graph.

The chain these tests follow: recall and answer an old fact -> the store changes
(the management page does the same thing through Store.update_record) ->
continue in the same session -> fold -> restore and continue.

The model transport is a scripted in-process fake: no network, no credential.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from mellowday.personal_assistant.tools import build_fact_provider, execute_tool
from mellowday.runtime import events
from mellowday.runtime import sessions as session_store
from mellowday.runtime.agent import Agent
from mellowday.runtime.memory import (
    FACT_PRECEDENCE_RULE,
    FACT_REMINDER_MARKER,
    SUPERSEDED_FACTS_MARKER,
    SUPERSEDED_FACTS_RULE,
    strip_fact_reminders,
)
from mellowday.storage.store import Store

API_BASE = "http://127.0.0.1:9/v1"
SESSION_ID = "fact-session"

FACT = {
    "id": "fact-1",
    "title": "下班时间",
    "detail": "用户每天 18:00 下班",
    "status": "active",
    "meta": {"memory_kind": "preference"},
}

FOLD_REPLY = json.dumps(
    {
        "episode_memory": {
            "task_description": "用户问下班时间，助手回答 18:00",
            "key_events": [{"step": "1", "description": "回答下班时间 18:00", "outcome": "完成"}],
            "current_progress": "已经告诉用户 18:00 下班",
        },
        "working_memory": {
            "immediate_goal": "继续回答",
            "current_challenges": "",
            "next_actions": [{"type": "planning", "description": "继续"}],
        },
        "tool_memory": {"tools_used": [], "derived_rules": []},
    },
    ensure_ascii=False,
)


# --- scripted OpenAI-compatible transport ------------------------------------


class _Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


class _Completions:
    """Streamed turns are consumed in order; non-streamed calls are side queries."""

    def __init__(self, turns, fold_reply: str) -> None:
        self._turns = list(turns)
        self.fold_reply = fold_reply
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs.get("stream"):
            text = self.fold_reply if int(kwargs.get("max_tokens") or 0) >= 6000 else ""
            return NS(choices=[NS(message=NS(content=text), finish_reason="stop")])
        chunks = self._turns.pop(0) if self._turns else text_turn("")

        async def _gen():
            for chunk in chunks:
                yield chunk

        return _gen()


class FakeOpenAI:
    def __init__(self, turns, fold_reply: str = FOLD_REPLY) -> None:
        self.completions = _Completions(turns, fold_reply)
        self.chat = NS(completions=self.completions)


def text_turn(text: str = "好的"):
    return [
        _Chunk([_Choice(_Delta(content=text))]),
        _Chunk(usage=_Usage(9, 5)),
        _Chunk([_Choice(_Delta(), finish_reason="stop")]),
    ]


class FakeProvider:
    """Provider whose answer can change between turns (fact updated / deleted)."""

    def __init__(self, records=()):
        self.records = [dict(record) for record in records]
        self.queries: list[str] = []

    async def __call__(self, query: str) -> list[dict]:
        self.queries.append(query)
        return [dict(record) for record in self.records]


def make_agent(provider, replies, *, fold_reply: str = FOLD_REPLY) -> Agent:
    agent = Agent(model="test-model", api_base=API_BASE, api_key="test-key", fact_provider=provider)
    agent._openai_client = FakeOpenAI([text_turn(reply) for reply in replies], fold_reply)
    agent.session_id = SESSION_ID
    # The learning loop is not what this file is about; keep the scripts deterministic.
    agent._online_evolution_enabled = lambda: False
    return agent


async def _chat(agent: Agent, message: str) -> str:
    with events.use_sink(lambda event: None):
        await agent.chat(message)
    await agent.drain_background_skill_tasks()
    calls = agent._openai_client.completions.calls
    return _render(calls[-1]["messages"])


def _render(messages) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    parts.append(str(block.get("text") or block.get("content") or ""))
    return "\n".join(parts)


def _sections(text: str) -> tuple[str, str]:
    """(current values, superseded values) of the injected reminder."""
    assert FACT_REMINDER_MARKER in text, f"no fact reminder was injected:\n{text}"
    body = text.split(FACT_REMINDER_MARKER, 1)[1]
    if SUPERSEDED_FACTS_MARKER not in body:
        return body, ""
    current, superseded = body.split(SUPERSEDED_FACTS_MARKER, 1)
    return current, superseded


# --- the chain: recall -> change -> same session -> fold -> restore ----------


@pytest.mark.anyio
async def test_updated_fact_is_marked_superseded_while_the_history_keeps_the_old_reply():
    provider = FakeProvider([FACT])
    agent = make_agent(provider, ["你每天 18:00 下班。", "你每天 20:00 下班。"])

    await _chat(agent, "我几点下班")

    # 管理页（或任何直接写 Store 的入口）把事实改成 20:00
    provider.records = [{"id": "fact-1", "title": "下班时间", "detail": "用户每天 20:00 下班",
                         "status": "active", "meta": {"memory_kind": "preference"}}]
    sent = await _chat(agent, "我几点下班")

    current, superseded = _sections(sent)
    assert "20:00" in current
    assert "18:00" not in current, "旧值不得继续作为当前事实提供"
    assert "18:00" in superseded, "历史里的旧值必须带明确的失效说明"
    assert "20:00" in superseded, "失效说明要给出被替换成什么"
    assert "replaced by" in superseded
    assert SUPERSEDED_FACTS_RULE in sent
    # 历史保留真实发生过的内容：上一轮助手的回答没有被改写
    replies = [m["content"] for m in agent._openai_messages if m.get("role") == "assistant"]
    assert replies == ["你每天 18:00 下班。", "你每天 20:00 下班。"]


@pytest.mark.anyio
async def test_deleted_fact_is_reported_as_no_longer_stored():
    provider = FakeProvider([FACT])
    agent = make_agent(provider, ["你每天 18:00 下班。", "这条事实已经没有了。"])

    await _chat(agent, "我几点下班")
    provider.records = []              # forget_memory / 管理页删除
    sent = await _chat(agent, "我几点下班")

    current, superseded = _sections(sent)
    assert "18:00" not in current
    assert "18:00" in superseded
    assert "no longer in the memory store" in superseded


@pytest.mark.anyio
async def test_the_marked_old_value_survives_a_fold_of_the_conversation():
    provider = FakeProvider([FACT])
    agent = make_agent(provider, ["你每天 18:00 下班。", "你每天 20:00 下班。", "还是 20:00。"])

    await _chat(agent, "我几点下班")
    provider.records = [{"id": "fact-1", "title": "下班时间", "detail": "用户每天 20:00 下班",
                         "status": "active"}]
    await _chat(agent, "我几点下班")

    await agent.compact()
    # 折叠摘要本身可能带着旧值（它描述的正是当时说过的话）：历史保留，但必须被标注
    folded = json.dumps(agent._openai_messages, ensure_ascii=False)
    assert "<session-folded-memory>" in folded
    assert "18:00" in folded, "折叠摘要是历史，不被改写"

    sent = await _chat(agent, "我到底几点下班")
    current, superseded = _sections(sent)
    assert "20:00" in current
    assert "18:00" not in current
    assert "18:00" in superseded, "折叠之后旧值仍然被标注为失效"
    assert "20:00" in superseded


@pytest.mark.anyio
async def test_a_restarted_session_still_knows_which_value_is_stale():
    provider = FakeProvider([FACT])
    agent = make_agent(provider, ["你每天 18:00 下班。"])
    await _chat(agent, "我几点下班")
    agent._auto_save()

    saved = session_store.load_session(SESSION_ID)
    assert saved["factState"]["observed"], "已提供的事实随会话文件保存"
    assert saved["factState"]["superseded"] == []

    # 进程重启后事实已经被改过
    provider.records = [{"id": "fact-1", "title": "下班时间", "detail": "用户每天 20:00 下班",
                         "status": "active"}]
    restored = make_agent(provider, ["你每天 20:00 下班。"])
    restored.restore_session(saved)

    sent = await _chat(restored, "我几点下班")
    current, superseded = _sections(sent)
    assert "20:00" in current
    assert "18:00" not in current
    assert "18:00" in superseded
    # 恢复后的失效清单继续随会话保存
    restored._auto_save()
    assert session_store.load_session(SESSION_ID)["factState"]["superseded"]


@pytest.mark.anyio
async def test_a_value_that_comes_back_is_not_reported_as_superseded():
    provider = FakeProvider([FACT])
    agent = make_agent(provider, ["18:00。", "19:00。", "又回到 18:00。"])

    await _chat(agent, "我几点下班")
    provider.records = [{"id": "fact-1", "title": "下班时间", "detail": "用户每天 19:00 下班",
                         "status": "active"}]
    await _chat(agent, "我几点下班")
    provider.records = [dict(FACT)]
    sent = await _chat(agent, "我几点下班")

    current, superseded = _sections(sent)
    assert "18:00" in current, "值已经是当前值"
    # 失效条目形如：「- 下班时间 [preference]: "旧值" — replaced by "新值"」
    assert '"用户每天 18:00 下班" —' not in superseded, "当前值不得被标成失效"
    assert '"用户每天 19:00 下班" —' in superseded, "上一个值才是失效的那一个"


@pytest.mark.anyio
async def test_the_user_explicit_request_wins_over_a_stored_preference():
    preference = {
        "id": "fact-2",
        "title": "晚上习惯",
        "detail": "用户偏好：晚上不要提醒工作相关的事",
        "status": "active",
        "meta": {"memory_kind": "preference"},
    }
    provider = FakeProvider([preference])
    agent = make_agent(provider, ["好，这次照你说的办。"])

    sent = await _chat(agent, "今晚例外，帮我把复盘加到待办")

    assert FACT_PRECEDENCE_RULE in sent
    assert "本次明确要求" not in sent  # 规则只用一种语言，避免模型读到两种措辞
    assert "今晚例外，帮我把复盘加到待办" in sent
    assert "always wins over a remembered habit" in sent, "system prompt 同一条规则"


@pytest.mark.anyio
async def test_only_active_facts_can_be_recalled_or_injected():
    store = Store()
    created = json.loads(await execute_tool(store, "remember_fact", {
        "content": "用户住在北京", "label": "住址", "kind": "fact",
    }))
    active_id = created["id"]
    expired = json.loads(await execute_tool(store, "remember_fact", {
        "content": "用户住在上海", "label": "旧住址", "kind": "fact",
    }))
    deleted = json.loads(await execute_tool(store, "remember_fact", {
        "content": "用户喜欢咖啡", "label": "旧偏好", "kind": "preference",
    }))
    assert json.loads(await execute_tool(store, "update_memory", {
        "id": expired["id"], "status": "expired",
    }))["ok"] is True
    assert json.loads(await execute_tool(store, "forget_memory", {"id": deleted["id"]}))["ok"] is True

    recalled = json.loads(await execute_tool(store, "recall_memories", {"query": ""}))
    assert [record["id"] for record in recalled["memories"]] == [active_id]

    provider = build_fact_provider(store)
    assert [record["id"] for record in await provider("")] == [active_id]
    assert [record["id"] for record in await provider("我以前住哪")] == [active_id]

    agent = make_agent(provider, ["好的。"])
    sent = await _chat(agent, "我之前住在哪里，喜欢喝什么")
    assert "北京" in sent
    assert "上海" not in sent and "咖啡" not in sent


@pytest.mark.anyio
async def test_a_fact_read_through_the_tool_is_tracked_too():
    """模型用 recall_memories 工具读到的事实同样属于「已提供」，改掉后要标注失效。"""
    store = Store()
    created = json.loads(await execute_tool(store, "remember_fact", {
        "content": "用户每天 18:00 下班", "label": "下班时间", "kind": "preference",
    }))
    memory_id = created["id"]

    async def executor(name, arguments):
        return await execute_tool(store, name, arguments)

    agent = make_agent(build_fact_provider(store), ["好的。"])
    agent.tool_executor = executor
    agent._custom_tool_names = {"recall_memories", "update_memory"}

    recall = await agent._execute_tool_call("recall_memories", {"query": "下班"})
    assert json.loads(recall)["count"] == 1
    assert agent._observed_facts, "工具读到的事实进入失效跟踪"

    await execute_tool(store, "update_memory", {"id": memory_id, "content": "用户每天 20:00 下班"})

    sent = await _chat(agent, "我几点下班")
    current, superseded = _sections(sent)
    assert "20:00" in current and "18:00" not in current
    assert "18:00" in superseded


def test_stripping_the_reminder_removes_both_sections():
    injection = (
        "<system-reminder>\n"
        + FACT_REMINDER_MARKER
        + "\n- 下班时间 [preference]: 用户每天 20:00 下班\n\n"
        + SUPERSEDED_FACTS_MARKER
        + '\n- 下班时间 [preference]: "用户每天 18:00 下班" — replaced by "用户每天 20:00 下班"\n'
        + SUPERSEDED_FACTS_RULE
        + "\n</system-reminder>"
    )
    text = "我几点下班\n\n" + injection
    assert strip_fact_reminders(text) == "我几点下班"
