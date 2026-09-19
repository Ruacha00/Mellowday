"""Runtime fact recall tests (I22).

Facts have exactly one source - the SQLite "memories" records - and the runtime
gets its candidates from an injected `fact_provider`. These tests drive the Agent
with a fake OpenAI-compatible client and a fake provider, so nothing here touches
the network, a real credential or a real model.
"""
from __future__ import annotations

import json

import pytest

from mellowday.personal_assistant.tools import build_fact_provider, execute_tool
from mellowday.runtime import events
from mellowday.runtime.agent import Agent
from mellowday.runtime.memory import (
    FACT_PRECEDENCE_RULE,
    FACT_REMINDER_MARKER,
    SUPERSEDED_FACTS_MARKER,
    SUPERSEDED_FACTS_RULE,
    RelevantMemory,
    format_memories_for_injection,
    query_terms,
    recall_facts,
    score_fact,
    strip_fact_reminders,
)
from mellowday.storage.store import Store

API_BASE = "http://127.0.0.1:9/v1"

FACT = {
    "id": "fact-1",
    "title": "下班时间",
    "detail": "用户每天 18:00 下班",
    "status": "active",
    "meta": {"memory_kind": "preference"},
}


# --- fake OpenAI-compatible client -----------------------------------------

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
    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self._turns.pop(0) if self._turns else text_turn("")
        async def _gen():
            for chunk in chunks:
                yield chunk
        return _gen()


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class FakeOpenAI:
    def __init__(self, turns):
        self.completions = _Completions(turns)
        self.chat = _Chat(self.completions)


def text_turn(text="好的"):
    return [
        _Chunk([_Choice(_Delta(content=text))]),
        _Chunk(usage=_Usage(10, 4)),
        _Chunk([_Choice(_Delta(), finish_reason="stop")]),
    ]


def make_agent(fact_provider=None, *, turns=1):
    agent = Agent(
        model="test-model",
        api_base=API_BASE,
        api_key="test-key",
        fact_provider=fact_provider,
    )
    agent._openai_client = FakeOpenAI([text_turn() for _ in range(turns)])
    # 关闭后台技能学习：它会再发一次（假）模型调用，干扰「本轮只调用一次模型」的断言。
    agent._online_evolution_enabled = lambda: False
    return agent


class FakeProvider:
    """Provider whose answer can change between turns (fact updated / deleted)."""

    def __init__(self, records=()):
        self.records = [dict(record) for record in records]
        self.queries = []

    async def __call__(self, query: str) -> list[dict]:
        self.queries.append(query)
        return [dict(record) for record in self.records]


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


def _sent(agent) -> str:
    """Everything the model was given in the most recent request."""
    return _render(agent._openai_client.chat.completions.calls[-1]["messages"])


async def _chat(agent, message):
    seen = []
    with events.use_sink(seen.append):
        await agent.chat(message)
    await agent.drain_background_skill_tasks()
    return seen


def _injection_sections(text: str) -> tuple[str, str]:
    """把送进模型的上下文拆成「当前值段」与「已失效旧值段」。

    Returns (current, superseded); both are "" when nothing was injected.
    """
    if FACT_REMINDER_MARKER not in text:
        return "", ""
    body = text.split(FACT_REMINDER_MARKER, 1)[1]
    if SUPERSEDED_FACTS_MARKER in body:
        current, superseded = body.split(SUPERSEDED_FACTS_MARKER, 1)
        return current, superseded
    return body, ""


# --- term splitting ---------------------------------------------------------

def test_chinese_input_yields_terms_without_whitespace():
    terms = query_terms("我几点下班")
    assert "下班" in terms          # 相邻双字词项
    assert "我几" in terms
    assert query_terms("咖啡") == {"咖啡"}
    assert query_terms(" ") == set()


def test_score_fact_prefers_hits_and_ignores_unrelated_input():
    fact = {"id": "fact-1", "title": "下班时间", "detail": "用户每天 18:00 下班"}
    assert score_fact("我几点下班", fact) > 0.0
    assert score_fact("我的咖啡偏好", fact) == 0.0


def test_strip_fact_reminders_keeps_the_user_text():
    injection = format_memories_for_injection(
        [RelevantMemory("fact-1", "用户每天 18:00 下班", 0, "下班时间 [preference]")]
    )
    assert FACT_REMINDER_MARKER in injection
    text = "我几点下班\n\n" + injection
    assert strip_fact_reminders(text) == "我几点下班"
    # A message without a reminder is returned untouched.
    assert strip_fact_reminders("普通问题") == "普通问题"


@pytest.mark.anyio
async def test_recall_facts_without_provider_returns_nothing():
    assert await recall_facts("我几点下班", None) == []


# --- every turn recalls automatically --------------------------------------

@pytest.mark.anyio
async def test_chinese_message_recalls_and_injects_the_fact():
    provider = FakeProvider([FACT])
    agent = make_agent(provider)

    await _chat(agent, "我几点下班")

    # 1) the provider was asked with the user's own wording (no whitespace needed)
    assert provider.queries == ["我几点下班"]
    # 2) the fact is visible in the messages that were sent to the model
    sent = _sent(agent)
    assert FACT_REMINDER_MARKER in sent
    assert "18:00" in sent
    assert "下班时间" in sent
    # 3) exactly one model call: recall needs no LLM side query
    assert len(agent._openai_client.chat.completions.calls) == 1


@pytest.mark.anyio
async def test_empty_provider_result_keeps_the_conversation_normal():
    provider = FakeProvider([])
    agent = make_agent(provider)

    seen = await _chat(agent, "我几点下班")

    assert provider.queries == ["我几点下班"]
    assert "text_delta" in [event["type"] for event in seen]
    assert "turn_end" in [event["type"] for event in seen]
    assert FACT_REMINDER_MARKER not in _sent(agent)


@pytest.mark.anyio
async def test_missing_fact_provider_does_not_raise_or_inject():
    agent = make_agent(None)

    seen = await _chat(agent, "我几点下班")

    assert agent.fact_provider is None
    assert "text_delta" in [event["type"] for event in seen]
    assert FACT_REMINDER_MARKER not in _sent(agent)


@pytest.mark.anyio
async def test_failing_provider_does_not_break_the_turn():
    async def broken(query: str) -> list[dict]:
        raise RuntimeError("store unavailable")

    agent = make_agent(broken)

    seen = await _chat(agent, "我几点下班")

    assert "text_delta" in [event["type"] for event in seen]
    assert FACT_REMINDER_MARKER not in _sent(agent)


@pytest.mark.anyio
async def test_updated_fact_replaces_the_old_value_in_context():
    provider = FakeProvider([FACT])
    agent = make_agent(provider, turns=2)

    await _chat(agent, "我几点下班")
    assert "18:00" in _sent(agent)

    provider.records = [
        {"id": "fact-1", "title": "下班时间", "detail": "用户每天 19:00 下班", "status": "active"}
    ]
    await _chat(agent, "我几点下班")

    sent = _sent(agent)
    current, superseded = _injection_sections(sent)
    # 当前值：唯一可以被当成「现在」使用的内容
    assert "19:00" in current
    assert "18:00" not in current
    # 旧值即使还留在历史里，也必须带着「已失效」的说明出现
    assert SUPERSEDED_FACTS_MARKER in sent
    assert "18:00" in superseded and "19:00" in superseded
    assert "replaced by" in superseded
    assert SUPERSEDED_FACTS_RULE in sent
    # 当前明确要求优先于默认偏好
    assert FACT_PRECEDENCE_RULE in sent
    # 召回用用户原话；"" 的那次是「上轮提供过的值是否还有效」的校验读取
    assert [query for query in provider.queries if query] == ["我几点下班", "我几点下班"]


@pytest.mark.anyio
async def test_deleted_fact_is_no_longer_visible():
    provider = FakeProvider([FACT])
    agent = make_agent(provider, turns=2)

    await _chat(agent, "我几点下班")
    assert "18:00" in _sent(agent)

    provider.records = []          # status 已不是 active
    await _chat(agent, "我几点下班")

    sent = _sent(agent)
    current, superseded = _injection_sections(sent)
    # 当前值段里不再有任何内容，旧值被明确标记为已从记忆库消失
    assert "18:00" not in current
    assert "下班时间" not in current
    assert "18:00" in superseded
    assert "no longer in the memory store" in superseded
    # 没有当前事实时不再重复「明确要求优先」这条（它只约束已存偏好）
    assert FACT_PRECEDENCE_RULE not in sent


@pytest.mark.anyio
async def test_non_active_records_from_the_provider_are_never_injected():
    provider = FakeProvider([
        {"id": "old", "title": "旧住址", "detail": "用户住在北京", "status": "deleted"},
        {"id": "gone", "title": "旧偏好", "detail": "用户喜欢咖啡", "status": "expired"},
    ])
    agent = make_agent(provider)

    await _chat(agent, "我住在哪里")

    sent = _sent(agent)
    assert FACT_REMINDER_MARKER not in sent
    assert "北京" not in sent


@pytest.mark.anyio
async def test_large_irrelevant_candidate_pool_is_not_injected():
    provider = FakeProvider([
        {"id": f"f{index}", "title": f"杂项{index}", "detail": f"第 {index} 条无关记录", "status": "active"}
        for index in range(8)
    ])
    agent = make_agent(provider)

    await _chat(agent, "帮我建一个待办")

    assert FACT_REMINDER_MARKER not in _sent(agent)


@pytest.mark.anyio
async def test_small_store_keeps_facts_visible_when_wording_differs():
    """事实库很小时，措辞不同也不应该让「记住过的事实」完全用不上。"""
    provider = FakeProvider([FACT])
    agent = make_agent(provider)

    await _chat(agent, "今天下午的安排是什么")

    assert "18:00" in _sent(agent)


# --- anthropic-shaped history ----------------------------------------------

@pytest.mark.anyio
async def test_anthropic_message_blocks_gain_and_lose_the_reminder():
    provider = FakeProvider([FACT])
    agent = make_agent(provider)
    agent._anthropic_messages = [
        {"role": "user", "content": [{"type": "text", "text": "我几点下班"}]}
    ]

    await agent._inject_recalled_facts(agent._anthropic_messages, "我几点下班")
    blocks = agent._anthropic_messages[-1]["content"]
    assert any("18:00" in str(block.get("text")) for block in blocks if isinstance(block, dict))

    provider.records = [
        {"id": "fact-1", "title": "下班时间", "detail": "用户每天 19:00 下班", "status": "active"}
    ]
    await agent._inject_recalled_facts(agent._anthropic_messages, "我几点下班")

    rendered = _render(agent._anthropic_messages)
    current, superseded = _injection_sections(rendered)
    assert "19:00" in current
    assert "18:00" not in current
    assert "18:00" in superseded
    # 用户原本的文本块保留
    assert "我几点下班" in rendered


@pytest.mark.anyio
async def test_fold_transcript_drops_previous_fact_values():
    provider = FakeProvider([FACT])
    agent = make_agent(provider)

    await _chat(agent, "我几点下班")
    assert "18:00" in _render(agent._openai_messages)

    # 折叠摘要的输入先移除注入段落，摘要不会把旧事实带回来
    transcript_messages = [
        agent._message_without_fact_reminder(message) for message in agent._openai_messages
    ]
    assert "18:00" not in _render(transcript_messages)
    assert "我几点下班" in _render(transcript_messages)


# --- single source: SQLite -> provider -> context ---------------------------

@pytest.mark.anyio
async def test_real_store_facts_reach_the_context_and_follow_updates():
    store = Store()
    created = json.loads(await execute_tool(store, "remember_fact", {
        "content": "用户每天 18:00 下班",
        "label": "下班时间",
        "kind": "preference",
    }))
    assert created["ok"] is True
    memory_id = created["id"]

    agent = make_agent(build_fact_provider(store), turns=3)

    await _chat(agent, "我几点下班")
    sent = _sent(agent)
    assert FACT_REMINDER_MARKER in sent
    assert "18:00" in sent

    updated = json.loads(await execute_tool(store, "update_memory", {
        "id": memory_id,
        "content": "用户每天 19:00 下班",
    }))
    assert updated["ok"] is True

    await _chat(agent, "我几点下班")
    sent = _sent(agent)
    current, superseded = _injection_sections(sent)
    assert "19:00" in current
    assert "18:00" not in current
    assert "18:00" in superseded

    forgotten = json.loads(await execute_tool(store, "forget_memory", {"id": memory_id}))
    assert forgotten["ok"] is True

    await _chat(agent, "我几点下班")
    sent = _sent(agent)
    current, superseded = _injection_sections(sent)
    assert "19:00" not in current
    assert "19:00" in superseded
    assert "no longer in the memory store" in superseded
