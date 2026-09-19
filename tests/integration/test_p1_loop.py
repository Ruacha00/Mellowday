"""P1 integration: natural language -> real Agent -> business tool -> Store -> HTTP API.

The runtime agent is the genuine ported one; only the model transport is a
scripted fake. This proves the wiring between runtime, business tools, storage
and the HTTP layer without any network access.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from mellowday.storage.store import Store
from mellowday.web_app.app import create_app
from mellowday.web_app.service import SessionRegistry


def _text_chunks(text: str):
    return [
        NS(usage=None, choices=[NS(delta=NS(content=char, tool_calls=None), finish_reason=None)])
        for char in text
    ]


def _tool_chunk(call_id: str, name: str, arguments: dict):
    call = NS(
        index=0,
        id=call_id,
        function=NS(name=name, arguments=json.dumps(arguments, ensure_ascii=False)),
    )
    return NS(usage=None, choices=[NS(delta=NS(content=None, tool_calls=[call]), finish_reason=None)])


def _final(finish: str):
    return NS(
        usage=NS(prompt_tokens=11, completion_tokens=7),
        choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason=finish)],
    )


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for chunk in self._chunks:
                yield chunk
        return gen()


class _FakeCompletions:
    def __init__(self, script):
        self.script = script
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.script) - 1)
        return _FakeStream(self.script[index])


class _FakeClient:
    def __init__(self, script, **_kwargs):
        self.chat = NS(completions=_FakeCompletions(script))


@pytest.fixture
def scripted_model(monkeypatch):
    """Install a scripted OpenAI-compatible transport and return its recorder."""

    def install(script):
        created: list = []

        def factory(**kwargs):
            client = _FakeClient(script, **kwargs)
            created.append(client)
            return client

        monkeypatch.setattr(openai, "AsyncOpenAI", factory)
        monkeypatch.setenv("MELLOWDAY_API_KEY", "test-key")
        monkeypatch.setenv("MELLOWDAY_API_BASE", "https://example.invalid/v1")
        monkeypatch.setenv("MELLOWDAY_MODEL", "fake-model")
        return created

    return install


def _sse_events(body: str) -> list[dict]:
    """Parse an SSE body into its JSON payloads."""
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except ValueError:
                continue
    return events


def _api(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test")


@pytest.mark.anyio
async def test_natural_language_creates_a_todo_through_the_real_stack(tmp_path, scripted_model):
    script = [
        [_tool_chunk("call_1", "create_todo", {"title": "明晚七点复习"}), _final("tool_calls")],
        _text_chunks("已经加入待办。") + [_final("stop")],
    ]
    scripted_model(script)

    store = Store(data_dir=tmp_path / "data")
    registry = SessionRegistry(store=store)
    events = [event async for event in registry.run_turn("s1", "帮我把明晚七点复习加入待办")]

    kinds = [e["type"] for e in events]
    assert "tool_start" in kinds and "tool_result" in kinds
    assert any(e["type"] == "tool_start" and e["name"] == "create_todo" for e in events)
    reply = "".join(e["text"] for e in events if e["type"] == "text_delta")
    assert "已经加入待办" in reply

    todos = store.list_records("todos")
    assert len(todos) == 1
    assert todos[0]["title"] == "明晚七点复习"


@pytest.mark.anyio
async def test_tool_result_is_fed_back_to_the_model(tmp_path, scripted_model):
    script = [
        [_tool_chunk("call_9", "create_note", {"title": "会议纪要", "detail": "三条"}), _final("tool_calls")],
        _text_chunks("笔记已保存。") + [_final("stop")],
    ]
    created = scripted_model(script)

    store = Store(data_dir=tmp_path / "data")
    registry = SessionRegistry(store=store)
    [event async for event in registry.run_turn("s2", "把会议纪要记成笔记")]

    assert len(created) == 1
    completions = created[0].chat.completions
    main_calls = [call for call in completions.calls if call.get("stream")]
    assert len(main_calls) == 2, "one streamed round trip to call the tool, one to answer"
    second_messages = main_calls[1]["messages"]
    tool_messages = [m for m in second_messages if m.get("role") == "tool"]
    assert tool_messages, "the tool result must be sent back to the model"
    payload = json.loads(tool_messages[0]["content"])
    assert payload["ok"] is True
    assert store.list_records("notes")[0]["title"] == "会议纪要"


@pytest.mark.anyio
async def test_streaming_deltas_arrive_incrementally(tmp_path, scripted_model):
    script = [_text_chunks("第一句。第二句。") + [_final("stop")]]
    scripted_model(script)
    registry = SessionRegistry(store=Store(data_dir=tmp_path / "data"))
    deltas = [e["text"] async for e in registry.run_turn("s3", "你好") if e["type"] == "text_delta"]
    assert len(deltas) > 1, "text must stream, not arrive as one block"
    assert "".join(deltas).endswith("第一句。第二句。")


@pytest.mark.anyio
async def test_records_created_by_chat_are_visible_over_http(tmp_path, scripted_model):
    script = [
        [_tool_chunk("c1", "create_reminder", {"title": "带伞", "due_at": "2026-09-20T08:00:00Z"}), _final("tool_calls")],
        _text_chunks("提醒已设置。") + [_final("stop")],
    ]
    scripted_model(script)

    store = Store(data_dir=tmp_path / "data")
    app = create_app(store=store, registry=SessionRegistry(store=store))

    async with _api(app) as client:
        async with client.stream("POST", "/api/chat", json={"session_id": "http1", "message": "提醒我带伞"}) as response:
            assert response.status_code == 200
            body = "".join([part async for part in response.aiter_text()])
        streamed = _sse_events(body)
        assert any(e["type"] == "tool_start" and e["name"] == "create_reminder" for e in streamed)
        reply = "".join(e["text"] for e in streamed if e["type"] == "text_delta")
        assert "提醒已设置" in reply
        assert streamed[-1]["type"] == "done"

        listed = (await client.get("/api/records/reminders")).json()
        assert [r["title"] for r in listed["records"]] == ["带伞"]
        assert (await client.get("/api/health")).json()["model_configured"] is True
        sessions = (await client.get("/api/sessions")).json()["sessions"]
        assert any(s["session_id"] == "http1" for s in sessions)


@pytest.mark.anyio
async def test_invalid_record_payload_returns_400_not_500(tmp_path):
    store = Store(data_dir=tmp_path / "data")
    app = create_app(store=store)
    async with _api(app) as client:
        response = await client.post("/api/records/todos", json={"due_at": "not-a-date"})
        assert response.status_code == 400
        assert (await client.get("/api/records/nope")).status_code == 404
        config_view = (await client.get("/api/config")).json()
        assert config_view["api_key_hint"] == ""
