import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import (
    FakeProvider,
    ProviderReply,
    ProviderRequest,
    Skill,
    Tool,
    ToolCall,
)
from mellowday.web_app import create_app


def test_web_app_health_and_chat_use_the_public_agent_core_facade() -> None:
    async def exercise_boundary() -> None:
        app = create_app(provider=FakeProvider())
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/healthz")
            response = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "conversation-1",
                    "content": "Hello from the browser",
                },
            )

        assert health.status_code == 200
        assert health.json() == {"ok": True}
        assert response.status_code == 200
        payload = response.json()
        assert payload["chat_content"] == {
            "role": "assistant",
            "content": "I heard: Hello from the browser",
        }
        assert payload["stop_reason"] == "final"
        assert [event["type"] for event in payload["events"]] == [
            "turn_started",
            "provider_started",
            "provider_completed",
            "turn_completed",
        ]
        assert all(
            event["conversation_id"] == "conversation-1"
            for event in payload["events"]
        )

    asyncio.run(exercise_boundary())


def test_settings_lists_neutral_capability_metadata_without_loading_skills() -> None:
    loads: list[str] = []

    async def inspect_status(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        return {"conversation_id": conversation_id, **arguments}

    tool = Tool(
        name="status_read",
        description="Read local status.",
        input_schema={"type": "object", "properties": {}},
        executor=inspect_status,
        permission_requirements=("status:read",),
        side_effect="none",
        risk="low",
    )
    skill = Skill(
        name="plain_language",
        description="Explain status in plain language.",
        instruction_loader=lambda: loads.append("loaded") or "Use plain language.",
    )

    async def exercise_boundary() -> None:
        app = create_app(
            provider=FakeProvider(),
            tools=(tool,),
            skills=(skill,),
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/settings/capabilities")

        assert response.status_code == 200
        assert response.json() == {
            "tools": [
                {
                    "name": "status_read",
                    "description": "Read local status.",
                    "input_schema": {"type": "object", "properties": {}},
                    "permission_requirements": ["status:read"],
                    "side_effect": "none",
                    "risk": "low",
                }
            ],
            "skills": [
                {
                    "name": "plain_language",
                    "description": "Explain status in plain language.",
                    "enabled": True,
                }
            ],
        }
        assert loads == []

    asyncio.run(exercise_boundary())


def test_settings_persists_local_skill_enablement(tmp_path: Path) -> None:
    state_file = tmp_path / "skill-enablement.json"
    skill = Skill(
        name="plain_language",
        description="Explain status in plain language.",
        instruction_loader=lambda: "Use plain language.",
    )

    async def disable_and_restart() -> None:
        app = create_app(
            provider=FakeProvider(),
            skills=(skill,),
            skill_state_path=state_file,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            disabled = await client.put(
                "/api/settings/skills/plain_language/enabled",
                json={"enabled": False},
            )

        assert disabled.status_code == 200
        payload = disabled.json()
        assert payload["skill"] == {
            "name": "plain_language",
            "description": "Explain status in plain language.",
            "enabled": False,
        }
        assert payload["event"]["sequence"] == 1
        assert payload["event"]["type"] == "skill_enablement_changed"
        assert payload["event"]["occurred_at"] > 0
        assert payload["event"]["conversation_id"] is None
        assert payload["event"]["details"] == {
            "skill": "plain_language",
            "enabled": False,
        }

        restarted = create_app(
            provider=FakeProvider(),
            skills=(skill,),
            skill_state_path=state_file,
        )
        restarted_transport = ASGITransport(app=restarted)
        async with AsyncClient(
            transport=restarted_transport, base_url="http://test"
        ) as client:
            capabilities = await client.get("/api/settings/capabilities")

        assert capabilities.json()["skills"] == [payload["skill"]]

    asyncio.run(disable_and_restart())


def test_settings_inspects_and_accepts_pending_confirmation() -> None:
    executions: list[dict[str, object]] = []

    class ConfirmationProvider:
        name = "confirmation-script"

        def __init__(self) -> None:
            self.replies = iter(
                (
                    ProviderReply(
                        content="This erases the note permanently. Continue?",
                        tool_calls=(
                            ToolCall(
                                "call-delete",
                                "erase_note",
                                {"note_id": "note-1"},
                            ),
                        ),
                    ),
                    ProviderReply(content="The note is gone."),
                )
            )

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            return next(self.replies)

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    async def exercise_boundary() -> None:
        app = create_app(
            provider=ConfirmationProvider(),
            tools=(
                Tool(
                    name="erase_note",
                    description="Permanently erase one note.",
                    input_schema={
                        "type": "object",
                        "properties": {"note_id": {"type": "string"}},
                        "required": ["note_id"],
                    },
                    executor=erase_note,
                    side_effect="irreversible",
                    risk="high",
                ),
            ),
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            chat = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "conversation-1",
                    "content": "Erase note one.",
                },
            )
            pending = await client.get("/api/settings/confirmations")
            confirmation = chat.json()["confirmation"]
            decided = await client.post(
                f"/api/settings/confirmations/{confirmation['id']}/decision",
                json={
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )
            audit = await client.get("/api/settings/audit")

        assert chat.status_code == 200
        assert chat.json()["stop_reason"] == "confirmation_pending"
        assert pending.status_code == 200
        assert pending.json() == {"confirmations": [confirmation]}
        assert confirmation["binding"] == {
            "user_id": "local-user",
            "conversation_id": "conversation-1",
            "tool": "erase_note",
            "arguments": {"note_id": "note-1"},
            "initiating_context": [
                {"role": "user", "content": "Erase note one."}
            ],
        }
        assert decided.status_code == 200
        assert decided.json()["turn"]["stop_reason"] == "confirmation_accepted"
        assert decided.json()["turn"]["chat_content"]["content"] == (
            "The note is gone."
        )
        assert executions == [{"note_id": "note-1"}]
        event_types = [event["type"] for event in audit.json()["events"]]
        assert "confirmation_pending" in event_types
        assert "confirmation_accepted" in event_types
        assert "tool_execution_completed" in event_types

    asyncio.run(exercise_boundary())
