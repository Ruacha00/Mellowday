import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import (
    ChatContent,
    FakeProvider,
    ProviderReply,
    ProviderRequest,
    Skill,
    Tool,
    ToolCall,
)
from mellowday.web_app import create_app


class ContextEchoProvider:
    name = "context-echo"

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        rendered = " | ".join(
            f"{message.role}:{message.content}" for message in request.messages
        )
        return ProviderReply(content=rendered)


def test_conversation_history_survives_backend_restart_and_is_isolated(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        database_path = tmp_path / "data" / "mellowday.sqlite3"

        first_app = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
        first_transport = ASGITransport(app=first_app)
        async with AsyncClient(
            transport=first_transport, base_url="http://test"
        ) as client:
            alpha = await client.post(
                "/api/chat",
                json={"conversation_id": "alpha", "content": "First message"},
            )
            beta = await client.post(
                "/api/chat",
                json={"conversation_id": "beta", "content": "Separate message"},
            )

        assert alpha.status_code == 200
        assert beta.status_code == 200

        restarted_app = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
        restarted_transport = ASGITransport(app=restarted_app)
        async with AsyncClient(
            transport=restarted_transport, base_url="http://test"
        ) as client:
            conversations = await client.get("/api/conversations")
            alpha_history = await client.get("/api/conversations/alpha")
            beta_history = await client.get("/api/conversations/beta")

        assert conversations.status_code == 200
        rows = conversations.json()["conversations"]
        assert [row["conversation_id"] for row in rows] == ["beta", "alpha"]
        assert [row["message_count"] for row in rows] == [2, 2]
        assert [row["character_count"] for row in rows] == [41, 35]
        assert all(row["created_at"] > 0 for row in rows)
        assert all(row["updated_at"] >= row["created_at"] for row in rows)
        assert alpha_history.status_code == 200
        assert alpha_history.json()["messages"] == [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "I heard: First message"},
        ]
        assert beta_history.status_code == 200
        assert beta_history.json()["messages"] == [
            {"role": "user", "content": "Separate message"},
            {"role": "assistant", "content": "I heard: Separate message"},
        ]

    asyncio.run(exercise_boundary())


def test_agent_core_receives_bounded_recent_history_through_the_web_app(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        database_path = tmp_path / "mellowday.sqlite3"
        initial_app = create_app(
            provider=ContextEchoProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=initial_app), base_url="http://test"
        ) as client:
            first = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "one"},
            )
        assert first.json()["chat_content"]["content"] == "user:one"

        message_limited_app = create_app(
            provider=ContextEchoProvider(),
            conversation_database_path=database_path,
            history_message_limit=1,
            history_character_limit=100,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=message_limited_app),
            base_url="http://test",
        ) as client:
            second = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "two"},
            )
        assert second.json()["chat_content"]["content"] == (
            "assistant:user:one | user:two"
        )

        character_limited_app = create_app(
            provider=ContextEchoProvider(),
            conversation_database_path=database_path,
            history_message_limit=40,
            history_character_limit=8,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=character_limited_app),
            base_url="http://test",
        ) as client:
            third = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "three"},
            )
        assert third.json()["chat_content"]["content"] == "user:three"

    asyncio.run(exercise_boundary())


def test_settings_resets_only_selected_history_and_reports_structured_events(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                "/api/chat",
                json={"conversation_id": "keep", "content": "Keep this"},
            )
            await client.post(
                "/api/chat",
                json={"conversation_id": "reset", "content": "Remove this"},
            )
            before_reset = await client.get("/api/events/recent")
            unconfirmed = await client.post("/api/conversations/reset/reset")
            cancel_requested = await client.post(
                "/api/conversations/reset/reset-confirmation"
            )
            cancel_confirmation = cancel_requested.json()["confirmation"]
            cancelled = await client.post(
                "/api/conversations/reset/reset",
                json={
                    "decision": "reject",
                    "binding": cancel_confirmation["binding"],
                    "confirmation_id": cancel_confirmation["id"],
                },
            )
            after_cancel = await client.get("/api/conversations/reset")
            requested = await client.post(
                "/api/conversations/reset/reset-confirmation"
            )
            confirmation = requested.json()["confirmation"]
            reset = await client.post(
                "/api/conversations/reset/reset",
                json={
                    "decision": "accept",
                    "binding": confirmation["binding"],
                    "confirmation_id": confirmation["id"],
                },
            )
            replay = await client.post(
                "/api/conversations/reset/reset",
                json={
                    "decision": "accept",
                    "binding": confirmation["binding"],
                    "confirmation_id": confirmation["id"],
                },
            )
            reset_history = await client.get("/api/conversations/reset")
            kept_history = await client.get("/api/conversations/keep")
            after_reset = await client.get("/api/events/recent")

        assert before_reset.status_code == 200
        before_types = [event["type"] for event in before_reset.json()["events"]]
        assert before_types == [
            "conversation_history_initialized",
            "conversation_history_loaded",
            "conversation_history_appended",
            "conversation_history_loaded",
            "conversation_history_appended",
        ]
        assert before_reset.json()["events"][0]["details"] == {
            "from_version": 0,
            "schema_version": 1,
        }
        assert unconfirmed.status_code == 422
        assert cancel_requested.status_code == 200
        assert cancelled.status_code == 200
        assert cancelled.json()["ok"] is False
        assert cancelled.json()["decision"] == "reject"
        assert cancelled.json()["removed_messages"] == 0
        assert after_cancel.status_code == 200
        assert requested.status_code == 200
        assert confirmation["binding"] == {
            "user_id": "local-user",
            "conversation_id": "reset",
            "tool": "conversation_history.reset",
            "arguments": {},
            "initiating_context": [],
        }
        assert reset.status_code == 200
        assert reset.json()["ok"] is True
        assert reset.json()["removed_messages"] == 2
        assert replay.status_code == 409
        assert reset_history.status_code == 404
        assert kept_history.status_code == 200
        assert [message["content"] for message in kept_history.json()["messages"]] == [
            "Keep this",
            "I heard: Keep this",
        ]
        reset_events = [
            event
            for event in after_reset.json()["events"]
            if event["type"] == "conversation_history_reset"
        ]
        assert len(reset_events) == 1
        assert reset_events[0]["conversation_id"] == "reset"
        assert reset_events[0]["details"] == {"removed_messages": 2}

    asyncio.run(exercise_boundary())


def test_conversation_history_failures_are_diagnosable_through_the_web_app(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        database_path = tmp_path / "mellowday.sqlite3"
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            audit_path=None,
        )
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Before failure"},
            )
            database_path.write_text("not a sqlite database", encoding="utf-8")

            failed = await client.get("/api/conversations")
            events = await client.get("/api/events/recent")

        assert failed.status_code == 503
        assert failed.json() == {
            "detail": {
                "code": "conversation_history_unavailable",
                "operation": "list",
            }
        }
        failure_events = [
            event
            for event in events.json()["events"]
            if event["type"] == "conversation_history_failed"
        ]
        assert len(failure_events) == 1
        assert failure_events[0]["details"]["operation"] == "list"
        assert failure_events[0]["details"]["error_type"] == "DatabaseError"
        assert "database" in failure_events[0]["details"]["message"].lower()

    asyncio.run(exercise_boundary())


def test_web_app_health_and_chat_use_the_public_agent_core_facade(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
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


def test_settings_lists_neutral_capability_metadata_without_loading_skills(
    tmp_path: Path,
) -> None:
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
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
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
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
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
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        restarted_transport = ASGITransport(app=restarted)
        async with AsyncClient(
            transport=restarted_transport, base_url="http://test"
        ) as client:
            capabilities = await client.get("/api/settings/capabilities")

        assert capabilities.json()["skills"] == [payload["skill"]]

    asyncio.run(disable_and_restart())


def test_settings_inspects_and_accepts_pending_confirmation(tmp_path: Path) -> None:
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
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
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
