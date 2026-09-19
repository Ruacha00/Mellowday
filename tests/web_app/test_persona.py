"""Identity persistence and real runtime prompt refresh; no model calls."""
import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from mellowday.personal_assistant import persona
from mellowday.runtime.agent import Agent
from mellowday.web_app.app import create_app


@pytest.mark.anyio
async def test_api_roundtrip_and_invalid_write_preserves_identity():
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        original = (await client.get("/api/persona")).json()
        updated = {**original, "name": "小悠", "speaking_style": "先听我说，再问是否需要建议。"}
        assert (await client.put("/api/persona", json=updated)).json() == updated
        assert (await client.put("/api/persona", json={**updated, "name": 3})).status_code == 422
        assert (await client.put("/api/persona", json={**updated, "name": "x" * 81})).status_code == 422
        assert (await client.put("/api/persona", json={**updated, "permission": "all"})).status_code == 422
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        assert (await client.get("/api/persona")).json() == updated


@pytest.mark.anyio
async def test_corrupt_document_is_not_silently_replaced():
    persona.persona_path().write_text("{broken", encoding="utf-8")
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        assert (await client.get("/api/persona")).status_code == 409
        assert (await client.put("/api/persona", json=persona.DEFAULT_PERSONA)).status_code == 409
    assert persona.persona_path().read_text(encoding="utf-8") == "{broken"


@pytest.mark.anyio
async def test_atomic_replace_failure_preserves_saved_identity(monkeypatch):
    persona.save_persona(persona.DEFAULT_PERSONA)
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(persona.os, "replace", fail)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as client:
        assert (await client.put("/api/persona", json={**persona.DEFAULT_PERSONA, "name": "lost"})).status_code == 500
    assert persona.load_persona() == persona.DEFAULT_PERSONA
    assert not list(persona.persona_path().parent.glob(".persona-*.tmp"))


@pytest.mark.anyio
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
async def test_existing_agent_adopts_persona_without_rewriting_history(monkeypatch, protocol):
    agent = Agent(
        api_base="http://127.0.0.1:9/v1" if protocol == "openai" else None,
        anthropic_base_url="http://127.0.0.1:9",
        api_key="test",
    )
    # Keep the public turn path while isolating external integrations and learning.
    agent._mcp_initialized = True
    monkeypatch.setattr(agent, "_run_skill_usage_tracking", AsyncMock())
    monkeypatch.setattr(agent, "_run_online_skill_evolution", AsyncMock())
    monkeypatch.setattr(agent, "_augment_user_message_with_skill_context", lambda message: (message, None))
    captured_prompts = []

    async def model_reply(**kwargs):
        captured_prompts.append(
            agent._openai_messages[0]["content"] if protocol == "openai" else agent._system_prompt
        )
        if protocol == "openai":
            return {"choices": [{"message": {"role": "assistant", "content": "我在听。"}}]}
        return SimpleNamespace(
            usage=SimpleNamespace(input_tokens=0, output_tokens=0),
            content=[SimpleNamespace(type="text", text="我在听。")],
        )

    monkeypatch.setattr(agent, f"_call_{protocol}_stream", model_reply)
    await agent.chat("我今天只想聊聊")
    await agent.drain_background_skill_tasks()
    messages = agent._openai_messages[1:] if protocol == "openai" else agent._anthropic_messages
    history = deepcopy(messages)
    assert history == [
        {"role": "user", "content": "我今天只想聊聊"},
        {"role": "assistant", "content": "我在听。" if protocol == "openai" else [{"type": "text", "text": "我在听。"}]},
    ]
    persona.save_persona({**persona.DEFAULT_PERSONA, "name": "小悠新称呼"})
    await agent.chat("继续陪我聊聊")
    await agent.drain_background_skill_tasks()
    assert len(captured_prompts) == 2
    assert "小悠新称呼" not in captured_prompts[0]
    assert "小悠新称呼" in captured_prompts[1]
    messages = agent._openai_messages[1:] if protocol == "openai" else agent._anthropic_messages
    assert messages[:len(history)] == history
    assert "permission" in agent._system_prompt
    assert not any(t["name"] in {"save_persona", "update_persona"} for t in agent.tools)


def test_blank_fields_default_and_json_boundary():
    updated = persona.save_persona({**persona.DEFAULT_PERSONA, "name": "  ", "character": '文字\n"fake": "override"'})
    assert updated["name"] == "MellowDay"
    assert json.loads(persona.persona_prompt().split("Persona JSON:\n", 1)[1]) == updated
