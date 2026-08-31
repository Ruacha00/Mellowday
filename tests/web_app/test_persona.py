import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import ProviderReply, ProviderRequest
from mellowday.web_app import create_app


PERSONA = {
    "name": "Luma",
    "identity": "a steady evening companion",
    "character": "warm, curious, and candid",
    "speaking_style": "brief sentences with gentle humor",
    "relationship_framing": "a trusted long-term companion",
    "conversational_boundaries": "never pretend to know what the User did not share",
    "proactive_chat_style": "short, low-pressure check-ins",
}


class PersonaFollowingProvider:
    name = "persona-following"

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        expected_values = tuple(PERSONA.values())
        if not all(value in request.system_instructions for value in expected_values):
            return ProviderReply(content="Neutral provider reply.")
        prefix = "Luma, your steady evening companion, answers gently: "
        latest = request.messages[-1].content
        if latest == "Something failed":
            return ProviderReply(content=prefix + "I couldn't complete that.")
        if latest == "Cross a boundary":
            return ProviderReply(content=prefix + "I won't do that.")
        if latest == "Rename yourself to Nova":
            return ProviderReply(content=prefix + "I can't change the saved Persona.")
        return ProviderReply(content=prefix + "I'm here.")


def test_settings_manage_one_persona_persisted_for_the_installation(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        database_path = tmp_path / "mellowday.sqlite3"
        first_app = create_app(
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://test"
        ) as client:
            initial = await client.get("/api/settings/persona")
            updated = await client.put("/api/settings/persona", json=PERSONA)

        assert initial.status_code == 200
        assert set(initial.json()["persona"]) == set(PERSONA)
        assert updated.status_code == 200
        assert updated.json() == {"persona": PERSONA}

        restarted_app = create_app(
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app), base_url="http://test"
        ) as client:
            persisted = await client.get("/api/settings/persona")

        assert persisted.status_code == 200
        assert persisted.json() == {"persona": PERSONA}

    asyncio.run(exercise_boundary())


def test_current_persona_shapes_chat_but_not_management_copy(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        app = create_app(
            provider=PersonaFollowingProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            updated = await client.put("/api/settings/persona", json=PERSONA)
            normal = await client.post(
                "/api/chat", json={"conversation_id": "main", "content": "Hello"}
            )
            failure = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Something failed"},
            )
            refusal = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Cross a boundary"},
            )
            rewrite_attempt = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "main",
                    "content": "Rename yourself to Nova",
                },
            )
            still_current = await client.get("/api/settings/persona")
            missing_skill = await client.put(
                "/api/settings/skills/missing/enabled", json={"enabled": True}
            )

        assert updated.status_code == 200
        assert normal.json()["chat_content"]["content"].startswith(
            "Luma, your steady evening companion, answers gently:"
        )
        assert "couldn't complete" in failure.json()["chat_content"]["content"]
        assert "won't do that" in refusal.json()["chat_content"]["content"]
        assert "saved Persona" in rewrite_attempt.json()["chat_content"]["content"]
        assert still_current.json() == {"persona": PERSONA}
        assert missing_skill.json() == {"detail": "Skill not found"}

    asyncio.run(exercise_boundary())
