"""I20: model settings take effect on the next turn, without losing the session.

Regression tests for the configuration part of CONTRACTS.md 6bis:

* every turn re-reads the model config and applies it to the session agent;
* changing the model keeps the conversation history and the tool state;
* an unchanged config does not rebuild the transport client;
* the settings page offers the current default model and allows custom input,
  and still never echoes the key.

The model transport is a scripted fake; no network, no real credential.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from mellowday import config, paths
from mellowday.storage.store import Store
from mellowday.web_app import service
from mellowday.web_app.app import create_app

INDEX_HTML = paths.static_dir() / "index.html"


def _text_chunks(text: str):
    return [
        NS(usage=None, choices=[NS(delta=NS(content=char, tool_calls=None), finish_reason=None)])
        for char in text
    ]


def _final(finish: str):
    return NS(
        usage=NS(prompt_tokens=5, completion_tokens=3),
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
    def __init__(self, script, **kwargs):
        self.chat = NS(completions=_FakeCompletions(script))
        self.kwargs = kwargs


@pytest.fixture
def scripted_model(monkeypatch):
    """Install a scripted OpenAI-compatible transport and record its clients."""

    def install(script):
        created: list[_FakeClient] = []

        def factory(**kwargs):
            client = _FakeClient(script, **kwargs)
            created.append(client)
            return client

        monkeypatch.setattr(openai, "AsyncOpenAI", factory)
        monkeypatch.setenv("MELLOWDAY_API_KEY", "test-key")
        monkeypatch.setenv("MELLOWDAY_API_BASE", "https://example.invalid/v1")
        monkeypatch.setenv("MELLOWDAY_MODEL", "model-one")
        return created

    return install


def _api(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test")


async def _turn(registry, session_id: str, message: str) -> list[dict]:
    return [event async for event in registry.run_turn(session_id, message)]


@pytest.mark.anyio
async def test_unchanged_configuration_does_not_rebuild_the_client(tmp_path, scripted_model):
    created = scripted_model([_text_chunks("你好") + [_final("stop")]])
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(store=store)

    await _turn(registry, "cfg-same", "第一轮")
    agent = registry.peek("cfg-same").agent
    client_before = agent._openai_client
    assert len(created) == 1

    assert service.apply_model_config(agent) is False, "an identical config is a no-op"
    await _turn(registry, "cfg-same", "同配置的第二轮")

    assert len(created) == 1, "an unchanged configuration must not reconnect"
    assert agent._openai_client is client_before


@pytest.mark.anyio
async def test_next_turn_uses_a_new_model_and_keeps_the_history(tmp_path, scripted_model, monkeypatch):
    created = scripted_model([_text_chunks("好的") + [_final("stop")]])
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(store=store)

    await _turn(registry, "cfg-live", "第一轮")
    agent = registry.peek("cfg-live").agent
    tools_before = [tool["name"] for tool in agent.tools]
    transcript_before = json.dumps(agent._openai_messages, ensure_ascii=False)
    client_before = agent._openai_client
    requests_before_save = len(created[0].chat.completions.calls)

    # The user saves new settings in the settings page.
    monkeypatch.setenv("MELLOWDAY_MODEL", "model-two")
    await _turn(registry, "cfg-live", "第二轮")

    completions = created[0].chat.completions
    models = [call["model"] for call in completions.calls]
    assert models[0] == "model-one"
    assert models[-1] == "model-two", "the next turn must use the saved model"
    assert "model-one" not in models[requests_before_save:], "no request after saving may use the old model"
    assert agent.model == "model-two"
    # Same endpoint -> the connection is reused, not rebuilt.
    assert agent._openai_client is client_before
    # Nothing about the session itself was reset.
    assert [tool["name"] for tool in agent.tools] == tools_before
    transcript_after = json.dumps(agent._openai_messages, ensure_ascii=False)
    assert "第一轮" in transcript_after and "第一轮" in transcript_before
    assert len(agent._openai_messages) > len(json.loads(transcript_before))
    history = registry.history("cfg-live")
    assert [item["role"] for item in history] == ["user", "assistant"] * 2


@pytest.mark.anyio
async def test_new_endpoint_or_key_rebuilds_the_client_without_losing_context(tmp_path, scripted_model, monkeypatch):
    created = scripted_model([_text_chunks("好的") + [_final("stop")]])
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(store=store)

    await _turn(registry, "cfg-endpoint", "第一轮")
    agent = registry.peek("cfg-endpoint").agent
    client_before = agent._openai_client
    messages_before = list(agent._openai_messages)

    monkeypatch.setenv("MELLOWDAY_API_BASE", "https://other.invalid/v1")
    monkeypatch.setenv("MELLOWDAY_API_KEY", "another-key")
    await _turn(registry, "cfg-endpoint", "第二轮")

    assert len(created) == 2, "a new endpoint needs a new client"
    assert agent._openai_client is not client_before
    assert agent._openai_client.kwargs["base_url"] == "https://other.invalid/v1"
    assert agent._openai_client.kwargs["api_key"] == "another-key"
    assert agent._openai_messages[: len(messages_before)] == messages_before


@pytest.mark.anyio
async def test_thinking_setting_is_adopted_without_touching_the_client(tmp_path, scripted_model):
    created = scripted_model([_text_chunks("好的") + [_final("stop")]])
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(store=store)
    await _turn(registry, "cfg-think", "第一轮")
    agent = registry.peek("cfg-think").agent
    client_before = agent._openai_client
    assert agent.thinking is False

    cfg = config.load_model_config()
    cfg.thinking = True
    assert service.apply_model_config(agent, cfg) is True

    assert agent.thinking is True
    assert agent._thinking_mode == agent._resolve_thinking_mode()
    assert agent._openai_client is client_before
    assert len(created) == 1


@pytest.mark.anyio
async def test_applying_a_config_never_drops_the_built_agent_state(tmp_path, scripted_model):
    scripted_model([_text_chunks("好的") + [_final("stop")]])
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(store=store)
    await _turn(registry, "cfg-state", "第一轮")
    agent = registry.peek("cfg-state").agent

    before = {
        "messages": len(agent._openai_messages),
        "tools": [tool["name"] for tool in agent.tools],
        "session_id": agent.session_id,
        "prompt": agent._system_prompt,
        "executor": agent.tool_executor,
    }

    cfg = config.load_model_config()
    cfg.model = "model-three"
    cfg.max_turns = 7
    service.apply_model_config(agent, cfg)

    assert len(agent._openai_messages) == before["messages"]
    assert [tool["name"] for tool in agent.tools] == before["tools"]
    assert agent.session_id == before["session_id"]
    assert agent._system_prompt == before["prompt"]
    assert agent.tool_executor is before["executor"]
    assert agent.max_turns == 7


@pytest.mark.anyio
async def test_saved_settings_reach_the_next_turn_over_http(tmp_path, scripted_model, monkeypatch):
    created = scripted_model([_text_chunks("好的") + [_final("stop")]])
    store = Store(data_dir=tmp_path / "data")
    app = create_app(store=store, registry=service.SessionRegistry(store=store))

    async with _api(app) as client:
        async with client.stream(
            "POST", "/api/chat", json={"session_id": "http-cfg", "message": "第一轮"}
        ) as response:
            await response.aread()

        # A deployment-level override wins over the stored file (CONTRACTS.md
        # section 2), so drop it to exercise the ordinary "user saves settings"
        # path.
        requests_before_save = len(created[0].chat.completions.calls)
        monkeypatch.delenv("MELLOWDAY_MODEL")
        saved = await client.put("/api/config", json={"model": "model-two"})
        assert saved.status_code == 200
        body = saved.json()
        assert body["model"] == "model-two"
        assert "api_key" not in body and "test-key" not in json.dumps(body)
        assert body["configured"] is True

        async with client.stream(
            "POST", "/api/chat", json={"session_id": "http-cfg", "message": "第二轮"}
        ) as response:
            await response.aread()

        detail = await client.get("/api/sessions/http-cfg")
        assert [m["role"] for m in detail.json()["messages"]] == ["user", "assistant"] * 2

    models = [call["model"] for call in created[0].chat.completions.calls]
    assert models[0] == "model-one"
    assert models[-1] == "model-two"
    assert "model-one" not in models[requests_before_save:]
    assert len(created) == 1, "the same endpoint keeps the same connection"


def test_settings_page_offers_the_default_model_and_a_custom_value():
    html = INDEX_HTML.read_text(encoding="utf-8")
    datalist = re.search(r'<input[^>]*id="cfg-model"[^>]*list="([^"]+)"', html)
    assert datalist, "the model field must accept a custom value (datalist input)"
    options = re.search(
        r'<datalist id="%s">(.*?)</datalist>' % re.escape(datalist.group(1)), html, re.S
    )
    assert options, "the datalist backing cfg-model must exist"
    for model in (config.DEFAULT_MODEL, "deepseek-v4-pro", "deepseek-flash", "deepseek-chat", "deepseek-reasoner"):
        assert f'value="{model}"' in options.group(1), f"{model} must be selectable"
    # A select cannot hold the configured value when it is not one of the
    # options, which is exactly how the default model disappeared before.
    assert "<select id=\"cfg-model\"" not in html
    # The key is still write-only.
    assert re.search(r'<input[^>]*id="cfg-key"[^>]*type="password"', html)
    assert "回显" not in html or "不修改" in html
