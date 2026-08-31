import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import FakeProvider, Skill, Tool
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
