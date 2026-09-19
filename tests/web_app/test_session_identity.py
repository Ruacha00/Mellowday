"""I19: session-id validation and complete session deletion.

Regression tests for the session-identity part of CONTRACTS.md 6bis:

* a session id is validated at the SessionRegistry boundary - allowed charset
  [A-Za-z0-9_-], length 1-64 - and an invalid id never creates a file;
* None / "" mean "new session" and the server generates the id;
* deleting a session removes the display history, the runtime session file, the
  folded-memory files, the in-memory state, the pending confirmations and the
  running turn; querying it afterwards restores nothing;
* the HTTP layer answers 400 for an unusable id and 404 for an unknown session.

No model, no network: the agent factory is a fake.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from urllib.parse import quote

import httpx
import pytest

from mellowday import paths
from mellowday.runtime import events
from mellowday.runtime.sessions import save_folded_session_memory, save_session
from mellowday.storage.store import Store
from mellowday.web_app import service
from mellowday.web_app.app import create_app

VALID_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")

INVALID_IDS = [
    "../evil",
    "..",
    "../../etc/passwd",
    "a/../b",
    "a/b",
    "..\\evil",
    "C:\\Users\\someone",
    "C:/Users/someone",
    "/etc/passwd",
    "a b",
    " lead",
    "trail ",
    "a.b",
    "会话一",
    "id\u0000null",
    "x" * 65,
    "-" * 64 + "x",
]


class FakeAgent:
    """Streams one delta immediately, then optionally keeps running."""

    def __init__(self, *, hold: float = 0.0) -> None:
        self.hold = hold
        self.session_id = ""
        self.confirm_fn = None
        self.active = 0
        self.finished: list[str] = []
        self.abort_calls = 0

    def set_confirm_fn(self, fn) -> None:
        self.confirm_fn = fn

    def abort(self) -> None:
        self.abort_calls += 1

    async def chat(self, message: str) -> None:
        self.active += 1
        try:
            events.emit({"type": "text_delta", "text": f"[{message}]"})
            if self.hold:
                await asyncio.sleep(self.hold)
        finally:
            self.active -= 1
            self.finished.append(message)


def make_registry(agent: FakeAgent, data_dir) -> service.SessionRegistry:
    def factory(*, session_id, store, tool_executor):
        agent.session_id = session_id
        return agent

    return service.SessionRegistry(store=Store(data_dir=data_dir), agent_factory=factory)


def tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


async def collect(registry, session_id, message) -> list[dict]:
    async def drain() -> list[dict]:
        return [event async for event in registry.run_turn(session_id, message)]

    return await asyncio.wait_for(drain(), 10)


# --------------------------------------------------------------- validation


@pytest.mark.anyio
@pytest.mark.parametrize("bad_id", INVALID_IDS)
async def test_invalid_session_ids_are_rejected_without_creating_anything(tmp_path, bad_id):
    registry = make_registry(FakeAgent(), tmp_path / "data")
    sessions_dir = paths.sessions_dir()
    before = tree(sessions_dir)

    with pytest.raises(service.InvalidSessionId):
        registry.get(bad_id)
    with pytest.raises(service.InvalidSessionId):
        registry.history(bad_id)
    with pytest.raises(service.InvalidSessionId):
        registry.drop(bad_id)
    with pytest.raises(service.InvalidSessionId):
        registry.exists(bad_id)
    with pytest.raises(service.InvalidSessionId):
        await registry.adrop(bad_id)
    assert tree(sessions_dir) == before, "an invalid id must not create any file"
    assert not (tmp_path / "evil").exists()


@pytest.mark.anyio
async def test_validate_session_id_only_accepts_the_documented_charset(tmp_path):
    assert service.validate_session_id("ok_ID-123") == "ok_ID-123"
    assert service.validate_session_id("x" * 64) == "x" * 64
    for bad in (None, "", 12, b"bytes", ["list"], {"dict": 1}, True):
        with pytest.raises(service.InvalidSessionId):
            service.validate_session_id(bad)
    with pytest.raises(service.InvalidSessionId):
        service.validate_session_id("x" * 65)


@pytest.mark.anyio
async def test_missing_id_creates_a_fresh_valid_session(tmp_path):
    registry = make_registry(FakeAgent(), tmp_path / "data")
    first = registry.get(None).session_id
    second = registry.get("").session_id
    third = registry.get(None).session_id
    assert len({first, second, third}) == 3
    for sid in (first, second, third):
        assert VALID_ID.fullmatch(sid), sid


@pytest.mark.anyio
async def test_run_turn_rejects_an_invalid_id_before_streaming(tmp_path):
    registry = make_registry(FakeAgent(), tmp_path / "data")
    with pytest.raises(service.InvalidSessionId):
        await collect(registry, "../evil", "hi")
    assert tree(paths.sessions_dir()) == set()


# ----------------------------------------------------------------- deletion


@pytest.mark.anyio
async def test_drop_removes_history_runtime_files_and_memory_state(tmp_path):
    agent = FakeAgent()
    registry = make_registry(agent, tmp_path / "data")
    await collect(registry, "gone", "你好")

    # The runtime writes these next to the display history.
    save_session("gone", {"metadata": {"id": "gone"}, "openaiMessages": []})
    save_folded_session_memory("gone", {"summary": "旧摘要"})
    sessions_dir = paths.sessions_dir()
    assert {p.name for p in sessions_dir.iterdir()} >= {
        "gone.history.json",
        "gone.json",
        "gone.folded-memory.jsonl",
        "gone.folded-memory.latest.json",
    }

    state = registry.get("gone")
    token, _future = state.confirmations.open("要删除吗")
    assert state.confirmations.pending() == [token]

    assert registry.drop("gone") is True

    assert registry.history("gone") == []
    assert registry.exists("gone") is False
    assert registry.peek("gone") is None
    assert state.confirmations.pending() == []
    assert not [p for p in sessions_dir.iterdir() if p.name.startswith("gone")]
    assert (await collect(registry, "gone", "还在吗"))[-1]["type"] == "done"


@pytest.mark.anyio
async def test_delete_stops_the_running_turn_and_leaves_no_history(tmp_path):
    agent = FakeAgent(hold=0.5)
    registry = make_registry(agent, tmp_path / "data")

    stream = registry.run_turn("busy", "第一轮")
    assert (await stream.__anext__())["type"] == "session"
    while (await stream.__anext__())["type"] != "text_delta":
        pass
    assert agent.active == 1

    assert await asyncio.wait_for(registry.adrop("busy"), 10) is True

    assert agent.active == 0, "deleting a session must stop its running turn"
    assert agent.abort_calls >= 1
    assert registry.history("busy") == []
    assert path_missing("busy")
    # A late write from the abandoned turn must not resurrect the session.
    await asyncio.sleep(0.1)
    assert registry.history("busy") == []
    assert path_missing("busy")
    assert registry.exists("busy") is False


def path_missing(session_id: str) -> bool:
    return not list(paths.sessions_dir().glob(f"{session_id}*"))


@pytest.mark.anyio
async def test_dropping_an_unknown_session_reports_nothing_removed(tmp_path):
    registry = make_registry(FakeAgent(), tmp_path / "data")
    assert registry.drop("never-existed") is False
    assert await registry.adrop("never-existed") is False


# ---------------------------------------------------------------------- HTTP


def api(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test"
    )


@pytest.fixture
def configured_app(tmp_path, monkeypatch):
    monkeypatch.setenv("MELLOWDAY_API_KEY", "test-key")
    monkeypatch.setenv("MELLOWDAY_API_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("MELLOWDAY_MODEL", "fake-model")
    agent = FakeAgent()
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(
        store=store,
        agent_factory=lambda *, session_id, store, tool_executor: agent,
    )
    return create_app(store=store, registry=registry), registry


@pytest.mark.anyio
async def test_api_rejects_unusable_session_ids_with_400(tmp_path, configured_app):
    app, registry = configured_app
    before = tree(paths.sessions_dir())
    async with api(app) as client:
        chat = await client.post("/api/chat", json={"session_id": "../evil", "message": "hi"})
        assert chat.status_code == 400
        assert chat.headers["content-type"].startswith("application/json")
        assert (await client.post("/api/chat", json={"session_id": 7, "message": "hi"})).status_code == 400

        # Ids that cannot survive URL handling (dot segments are resolved before
        # the request is sent, a slash is a path separator) never reach the
        # handler at all: the router or the /api fallback answers instead. What
        # matters is that nothing is ever served as a session.
        for raw in ("../evil", "..", "a/b", "C:/Users/someone"):
            encoded = quote(raw, safe="")
            statuses = (400, 404, 405)
            assert (await client.get(f"/api/sessions/{encoded}")).status_code in statuses, raw
            assert (await client.delete(f"/api/sessions/{encoded}")).status_code in statuses, raw

        # Ids that do route all the way to the handler are rejected with 400.
        for raw in ("a b", "x" * 65, "C:\\Users\\someone", "会话", "-.%20"):
            encoded = quote(raw, safe="")
            assert (await client.get(f"/api/sessions/{encoded}")).status_code == 400, raw
            assert (await client.delete(f"/api/sessions/{encoded}")).status_code == 400, raw
            assert (await client.post(f"/api/chat/{encoded}/abort")).status_code == 400, raw
    assert tree(paths.sessions_dir()) == before
    assert not registry.list()


@pytest.mark.anyio
async def test_unknown_session_is_404_for_get_and_delete(tmp_path, configured_app):
    app, _registry = configured_app
    async with api(app) as client:
        assert (await client.get("/api/sessions/absent")).status_code == 404
        assert (await client.delete("/api/sessions/absent")).status_code == 404


@pytest.mark.anyio
async def test_delete_over_http_removes_everything_and_does_not_restore(tmp_path, configured_app):
    app, _registry = configured_app
    async with api(app) as client:
        async with client.stream(
            "POST", "/api/chat", json={"session_id": "http-del", "message": "记一下"}
        ) as response:
            assert response.status_code == 200
            await response.aread()

        detail = await client.get("/api/sessions/http-del")
        assert detail.status_code == 200
        assert [m["role"] for m in detail.json()["messages"]] == ["user", "assistant"]
        assert detail.json()["active"] is True

        save_session("http-del", {"metadata": {"id": "http-del"}, "openaiMessages": []})
        save_folded_session_memory("http-del", {"summary": "摘要"})

        deleted = await client.delete("/api/sessions/http-del")
        assert deleted.status_code == 200
        assert deleted.json() == {"ok": True, "session_id": "http-del"}

        assert (await client.get("/api/sessions/http-del")).status_code == 404
        assert (await client.delete("/api/sessions/http-del")).status_code == 404
        sessions = (await client.get("/api/sessions")).json()["sessions"]
        assert all(item["session_id"] != "http-del" for item in sessions)
        assert not (paths.sessions_dir() / "http-del.json").exists()
        await asyncio.sleep(0.1)
        assert (await client.get("/api/sessions/http-del")).status_code == 404
