"""Web session service tests using a fake agent (no model, no network)."""
from __future__ import annotations

import asyncio
import json

import pytest

from mellowday.runtime import events
from mellowday.storage.store import Store
from mellowday.web_app import service


class FakeAgent:
    """Minimal stand-in for the runtime agent: emits text, optionally confirms."""

    def __init__(self, *, reply: str = "好的", confirm: bool = False, explode: bool = False) -> None:
        self.reply = reply
        self.want_confirm = confirm
        self.explode = explode
        self.confirm_fn = None
        self.aborted = False
        self.messages: list[str] = []

    def set_confirm_fn(self, fn) -> None:
        self.confirm_fn = fn

    def abort(self) -> None:
        self.aborted = True

    async def chat(self, message: str) -> None:
        self.messages.append(message)
        if self.explode:
            raise RuntimeError("model exploded")
        if self.want_confirm and self.confirm_fn is not None:
            approved = await self.confirm_fn("删除待办 1")
            events.emit({"type": "notice", "message": f"approved={approved}"})
        events.emit({"type": "text_delta", "text": self.reply})


def make_registry(fake: FakeAgent, data_dir) -> service.SessionRegistry:
    store = Store(data_dir=data_dir)
    def factory(*, session_id, store, tool_executor):
        fake.session_id = session_id
        return fake
    return service.SessionRegistry(store=store, agent_factory=factory)


@pytest.mark.anyio
async def test_turn_streams_events_and_persists_history(tmp_path):
    fake = FakeAgent(reply="明天有 2 个安排")
    registry = make_registry(fake, tmp_path / "data")

    seen = [event async for event in registry.run_turn("s1", "明天有什么安排")]
    kinds = [e["type"] for e in seen]
    assert kinds[0] == "session"
    assert "text_delta" in kinds
    assert kinds[-1] == "done"
    assert fake.messages == ["明天有什么安排"]

    history = registry.history("s1")
    assert [h["role"] for h in history] == ["user", "assistant"]
    assert history[1]["content"] == "明天有 2 个安排"


@pytest.mark.anyio
async def test_empty_message_is_rejected_without_touching_agent(tmp_path):
    fake = FakeAgent()
    registry = make_registry(fake, tmp_path / "data")
    seen = [event async for event in registry.run_turn("s1", "   ")]
    assert [e["type"] for e in seen] == ["session", "error", "done"]
    assert fake.messages == []


@pytest.mark.anyio
async def test_agent_failure_surfaces_as_error_event(tmp_path):
    fake = FakeAgent(explode=True)
    registry = make_registry(fake, tmp_path / "data")
    seen = [event async for event in registry.run_turn("s1", "hi")]
    types = [e["type"] for e in seen]
    assert "error" in types
    assert types[-1] == "done"


@pytest.mark.anyio
async def test_agent_construction_failure_is_reported(tmp_path):
    def factory(**_):
        raise RuntimeError("no api key")
    registry = service.SessionRegistry(store=Store(data_dir=tmp_path / "data"), agent_factory=factory)
    seen = [event async for event in registry.run_turn("s1", "hi")]
    assert seen[0]["type"] == "error"
    assert seen[-1]["type"] == "done"


@pytest.mark.anyio
async def test_confirmation_token_is_single_use(tmp_path):
    fake = FakeAgent(confirm=True)
    registry = make_registry(fake, tmp_path / "data")

    tokens: list[str] = []
    approved_notice = None
    async for event in registry.run_turn("s1", "删除它"):
        if event["type"] == "confirmation":
            tokens.append(event["id"])
            registry.get("s1").confirmations.resolve(event["id"], True)
        if event["type"] == "notice" and "approved" in str(event.get("message")):
            approved_notice = event["message"]

    assert tokens and len(tokens) == 1
    assert approved_notice == "approved=True"
    assert registry.get("s1").confirmations.resolve(tokens[0], True) is False


@pytest.mark.anyio
async def test_sessions_are_isolated_and_serial(tmp_path):
    agents: dict[str, FakeAgent] = {}

    def factory(*, session_id, store, tool_executor):
        agent = FakeAgent(reply=f"reply-{session_id}")
        agents[session_id] = agent
        return agent

    registry = service.SessionRegistry(store=Store(data_dir=tmp_path / "data"), agent_factory=factory)

    async def collect(sid: str) -> list[dict]:
        return [event async for event in registry.run_turn(sid, f"msg-{sid}")]

    results = await asyncio.gather(collect("a"), collect("b"))
    texts = {r[0]["session_id"]: [e.get("text") for e in r if e["type"] == "text_delta"] for r in results}
    assert texts["a"] == ["reply-a"]
    assert texts["b"] == ["reply-b"]
    assert agents["a"].messages == ["msg-a"]
    assert agents["b"].messages == ["msg-b"]


@pytest.mark.anyio
async def test_list_and_drop_sessions(tmp_path):
    registry = make_registry(FakeAgent(), tmp_path / "data")
    [event async for event in registry.run_turn("s1", "hello")]
    listing = registry.list()
    assert any(item["session_id"] == "s1" for item in listing)
    assert registry.drop("s1") is True
    assert registry.history("s1") == []
