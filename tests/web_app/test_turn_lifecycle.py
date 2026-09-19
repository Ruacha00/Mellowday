"""I18: a disconnected client must not leave a turn running.

Regression tests for the turn lifecycle contract (CONTRACTS.md 6bis):

* the execution task must be finished *before* the session lock is released;
* a session never runs two turns at the same time;
* a cancelled turn still lands exactly one assistant reply in the display history;
* a turn performs its business writes exactly once.

Most tests use a fake agent; the last one drives the genuine ported runtime
against a scripted in-process model transport. No network either way.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from mellowday import paths
from mellowday.runtime import events
from mellowday.storage.store import Store
from mellowday.web_app import service
from mellowday.web_app.app import create_app

HOLD_SECONDS = 0.30


class SlowAgent:
    """A runtime agent that streams one delta, then keeps thinking for a while."""

    def __init__(self, *, hold: float = HOLD_SECONDS) -> None:
        self.hold = hold
        self.session_id = ""
        self.confirm_fn = None
        self.started: list[str] = []
        self.finished: list[str] = []
        self.active = 0
        self.max_active = 0
        self.abort_calls = 0
        # One business write per turn, performed before the slow part.
        self.writes: list[str] = []

    def set_confirm_fn(self, fn) -> None:
        self.confirm_fn = fn

    def abort(self) -> None:
        self.abort_calls += 1

    async def chat(self, message: str) -> None:
        self.started.append(message)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            events.emit({"type": "text_delta", "text": f"[{message}]"})
            self.writes.append(message)
            await asyncio.sleep(self.hold)
            events.emit({"type": "text_delta", "text": "…结束"})
        finally:
            self.active -= 1
            self.finished.append(message)


def make_registry(fake: SlowAgent, data_dir) -> service.SessionRegistry:
    def factory(*, session_id, store, tool_executor):
        fake.session_id = session_id
        return fake

    return service.SessionRegistry(store=Store(data_dir=data_dir), agent_factory=factory)


async def advance_to_first_delta(stream) -> dict:
    """Consume the session event and the first text_delta event."""
    first = await asyncio.wait_for(stream.__anext__(), 5)
    assert first["type"] == "session"
    while True:
        event = await asyncio.wait_for(stream.__anext__(), 5)
        if event["type"] == "text_delta":
            return event


async def collect(registry, session_id: str, message: str) -> list[dict]:
    async def drain() -> list[dict]:
        return [event async for event in registry.run_turn(session_id, message)]

    return await asyncio.wait_for(drain(), 10)


@pytest.mark.anyio
async def test_client_disconnect_stops_the_running_turn(tmp_path):
    """Closing the response generator must reap the runtime task, not orphan it."""
    fake = SlowAgent()
    registry = make_registry(fake, tmp_path / "data")

    stream = registry.run_turn("s1", "第一轮")
    await advance_to_first_delta(stream)
    assert fake.active == 1, "the turn must be running while it streams"

    await asyncio.wait_for(stream.aclose(), 5)  # the browser hung up

    assert fake.active == 0, "the running turn must be stopped before the lock is released"
    assert fake.finished == ["第一轮"]
    assert fake.abort_calls >= 1, "the agent must be told to stop as well"


@pytest.mark.anyio
async def test_turn_cancellation_is_reaped_and_reported_as_cancelled(tmp_path):
    """A cancelled response task (server-side disconnect) behaves like aclose()."""
    fake = SlowAgent()
    registry = make_registry(fake, tmp_path / "data")
    reached = asyncio.Event()

    async def consume() -> None:
        async for event in registry.run_turn("s1", "第一轮"):
            if event["type"] == "text_delta":
                reached.set()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(reached.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)

    assert fake.active == 0, "cancelling the stream must stop the runtime turn"
    assert fake.finished == ["第一轮"]


@pytest.mark.anyio
async def test_second_turn_after_disconnect_is_serial_and_ordered(tmp_path):
    """After a disconnect the next turn must not overlap the abandoned one."""
    fake = SlowAgent()
    registry = make_registry(fake, tmp_path / "data")

    stream = registry.run_turn("s1", "第一轮")
    await advance_to_first_delta(stream)
    await asyncio.wait_for(stream.aclose(), 5)

    seen = await collect(registry, "s1", "第二轮")
    assert seen[0]["type"] == "session"
    assert seen[-1]["type"] == "done"
    assert fake.max_active == 1, "at most one turn may execute at a time"
    assert fake.writes == ["第一轮", "第二轮"], "each turn writes to the business layer once"

    history = registry.history("s1")
    assert [item["role"] for item in history] == ["user", "assistant", "user", "assistant"]
    assert history[0]["content"] == "第一轮"
    assert history[1]["content"].startswith("[第一轮"), "a cancelled turn keeps the text it produced"
    assert history[2]["content"] == "第二轮"
    assert history[3]["content"].startswith("[第二轮")


@pytest.mark.anyio
async def test_many_disconnects_leave_one_reply_per_turn(tmp_path):
    """Repeated abandons must neither duplicate nor drop assistant history."""
    fake = SlowAgent()
    registry = make_registry(fake, tmp_path / "data")

    for index in range(3):
        stream = registry.run_turn("s1", f"第{index}轮")
        await advance_to_first_delta(stream)
        await asyncio.wait_for(stream.aclose(), 5)

    await collect(registry, "s1", "收尾")
    history = registry.history("s1")
    assert [item["role"] for item in history] == ["user", "assistant"] * 4
    assert [item["content"] for item in history if item["role"] == "user"] == [
        "第0轮", "第1轮", "第2轮", "收尾",
    ]
    assert fake.max_active == 1
    assert fake.writes == ["第0轮", "第1轮", "第2轮", "收尾"]


@pytest.mark.anyio
async def test_disconnect_before_the_first_delta_still_releases_the_lock(tmp_path):
    """Disconnecting during startup must not deadlock the next turn."""
    fake = SlowAgent()
    registry = make_registry(fake, tmp_path / "data")

    stream = registry.run_turn("s1", "第一轮")
    assert (await asyncio.wait_for(stream.__anext__(), 5))["type"] == "session"
    await asyncio.wait_for(stream.aclose(), 5)

    seen = await collect(registry, "s1", "第二轮")
    assert seen[-1]["type"] == "done"
    assert fake.max_active == 1
    # The first turn never entered the locked section, so it left no trace at
    # all: the displayed history starts with the second turn.
    history = registry.history("s1")
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[0]["content"] == "第二轮"


@pytest.mark.anyio
async def test_disconnect_while_queued_leaves_the_running_turn_untouched(tmp_path):
    """A turn cancelled while waiting for the lock must not disturb the holder."""
    fake = SlowAgent()
    registry = make_registry(fake, tmp_path / "data")

    first = registry.run_turn("s1", "第一轮")
    await advance_to_first_delta(first)

    async def queued() -> None:
        async for _event in registry.run_turn("s1", "第二轮"):
            pass

    waiting = asyncio.create_task(queued())
    await asyncio.sleep(0.05)  # it is now parked on the session lock
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiting, 5)

    rest = [event async for event in first]
    assert rest[-1]["type"] == "done", "the running turn must still finish"

    assert fake.max_active == 1
    assert fake.writes == ["第一轮"], "the abandoned turn must never reach the agent"
    history = registry.history("s1")
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[1]["content"].startswith("[第一轮")


# ------------------------------------------------- real runtime (no network)


class _SlowStream:
    """A model stream that keeps producing deltas slowly."""

    def __init__(self, chunks, pace: float) -> None:
        self._chunks = chunks
        self._pace = pace

    def __aiter__(self):
        async def gen():
            for chunk in self._chunks:
                await asyncio.sleep(self._pace)
                yield chunk

        return gen()


class _SlowCompletions:
    def __init__(self, chunks, pace: float) -> None:
        self.chunks = chunks
        self.pace = pace
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return _SlowStream(self.chunks, self.pace)


def _text_chunks(text: str):
    stream = [
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=char, tool_calls=None), finish_reason=None
                )
            ],
        )
        for char in text
    ]
    stream.append(
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=3),
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, tool_calls=None), finish_reason="stop"
                )
            ],
        )
    )
    return stream


@pytest.mark.anyio
async def test_real_runtime_agent_stops_when_the_client_disconnects(tmp_path, monkeypatch):
    """The ported runtime itself must stop: no model call may outlive the turn."""
    import openai

    completions = _SlowCompletions(_text_chunks("一二三四五六七八九十" * 4), 0.05)

    def factory(**_kwargs):
        client = SimpleNamespace()
        client.chat = SimpleNamespace(completions=completions)
        return client

    monkeypatch.setattr(openai, "AsyncOpenAI", factory)
    monkeypatch.setenv("MELLOWDAY_API_KEY", "test-key")
    monkeypatch.setenv("MELLOWDAY_API_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("MELLOWDAY_MODEL", "fake-model")

    registry = service.SessionRegistry(store=Store(data_dir=tmp_path / "data"))
    stream = registry.run_turn("rt1", "你好")
    await advance_to_first_delta(stream)
    agent = registry.peek("rt1").agent
    assert agent._current_task is not None, "the runtime task must be running"

    await asyncio.wait_for(stream.aclose(), 10)

    assert agent._current_task is None, "the runtime task must be finished"
    assert agent._aborted is True, "the runtime must be told to abort"
    calls_at_disconnect = len(completions.calls)
    await asyncio.sleep(0.2)
    assert len(completions.calls) == calls_at_disconnect, "no model call may outlive the turn"

    history = registry.history("rt1")
    assert [item["role"] for item in history] == ["user", "assistant"]
    assert history[1]["content"], "the partial answer must still be shown"


# ------------------------------- deleting a session that has a queued turn


async def wait_until(predicate, timeout: float = 5.0) -> None:
    """Wait for a synchronous condition without guessing a fixed delay."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("condition was not reached in time")
        await asyncio.sleep(0.01)


def sse_events(body: str) -> list[dict]:
    """Decode the SSE body the page consumes back into event dicts."""
    events_seen: list[dict] = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events_seen.append(json.loads(line[len("data: "):]))
    return events_seen


@pytest.mark.anyio
async def test_a_queued_turn_never_runs_after_the_session_is_deleted(tmp_path):
    """T1-A: a turn that is *executing* plus a queued turn of the same session
    plus a deletion.  The queued turn used to acquire the lock after the
    deletion and run anyway - model call, business write, and a history file
    rebuilt behind the deletion's back.
    """
    fake = SlowAgent(hold=1.0)
    registry = make_registry(fake, tmp_path / "data")

    running = registry.run_turn("s1", "第一轮")
    await advance_to_first_delta(running)

    queued = registry.run_turn("s1", "第二轮")
    assert (await asyncio.wait_for(queued.__anext__(), 5))["type"] == "session"

    async def drain() -> list[dict]:
        return [event async for event in queued]

    parked = asyncio.create_task(drain())
    await asyncio.sleep(0.05)  # the queued turn is now parked on the session lock
    state = registry.peek("s1")
    assert state is not None and state.lock.locked(), "turn 1 still holds the lock"
    assert not parked.done(), "the second turn is waiting, not running"

    assert await asyncio.wait_for(registry.adrop("s1"), 10) is True

    tail = [event async for event in running]
    assert tail[-1]["type"] == "done", "the deleted session's turn still ends cleanly"
    answered = await asyncio.wait_for(parked, 10)

    assert answered[-1]["type"] == "done"
    assert any(
        event["type"] == "error" and "删除" in str(event.get("message", ""))
        for event in answered
    ), "the queued turn must be told why it did not run"
    assert fake.started == ["第一轮"], "the queued turn must never reach the model"
    assert fake.writes == ["第一轮"], "and never reach a business tool"
    assert registry.history("s1") == [], "its history write must not resurrect the session"
    assert registry.trace("s1") == []
    assert not list(paths.sessions_dir().glob("s1*")), "no session file may be rebuilt"


@pytest.mark.anyio
async def test_delete_over_http_answers_a_queued_chat_instead_of_running_it(tmp_path, monkeypatch):
    """The same scenario at the HTTP boundary the page actually uses."""
    monkeypatch.setenv("MELLOWDAY_API_KEY", "test-key")
    monkeypatch.setenv("MELLOWDAY_API_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("MELLOWDAY_MODEL", "fake-model")
    fake = SlowAgent(hold=3.0)
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(
        store=store,
        agent_factory=lambda *, session_id, store, tool_executor: fake,
    )
    # httpx buffers a streamed ASGI response, so the two requests are simply
    # started without waiting: the moment SessionRegistry.get() has answered a
    # second time, the queued request holds the state object the deletion is
    # about to drop, and from there on it can only end in the refusal branch.
    resolved: list[str] = []
    original_get = registry.get

    def tracked_get(session_id):
        state = original_get(session_id)
        resolved.append(state.session_id)
        return state

    monkeypatch.setattr(registry, "get", tracked_get)
    app = create_app(store=store, registry=registry)

    async def chat(client, message: str) -> str:
        response = await client.post(
            "/api/chat", json={"session_id": "queue-1", "message": message}
        )
        assert response.status_code == 200
        return response.text

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://mellowday.test") as client:
        running = asyncio.create_task(chat(client, "第一轮"))
        await wait_until(lambda: fake.active == 1)

        waiting = asyncio.create_task(chat(client, "第二轮"))
        await wait_until(lambda: len(resolved) == 2)

        deleted = await client.delete("/api/sessions/queue-1")
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True, "session_id": "queue-1"}

        first_body = await asyncio.wait_for(running, 15)
        second_body = await asyncio.wait_for(waiting, 15)

        first_seen = sse_events(first_body)
        second_seen = sse_events(second_body)
        assert first_seen[-1]["type"] == "done"
        assert second_seen[-1]["type"] == "done"
        assert any(
            event["type"] == "error" and "删除" in str(event.get("message", ""))
            for event in second_seen
        ), "the page must be shown the reason, not an empty answer"
        assert "第二轮" not in [event.get("text") for event in second_seen]
        assert fake.started == ["第一轮"], "the model is called once, not twice"
        assert not list(paths.sessions_dir().glob("queue-1*"))
        assert (await client.get("/api/sessions/queue-1")).status_code == 404
        await asyncio.sleep(0.1)
        assert not list(paths.sessions_dir().glob("queue-1*")), "no late write resurrects it"
