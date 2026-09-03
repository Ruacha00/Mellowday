"""Proactive Chat settings, scheduling, delivery, and audit at the Web boundary."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import ProviderReply, ProviderRequest
from mellowday.web_app import create_app


class ProactiveProvider:
    name = "proactive-script"

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        return ProviderReply(
            content='{"send": true, "content": "A gentle local check-in."}'
        )


def test_settings_persist_style_and_reject_invalid_quiet_hours(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        path = tmp_path / "mellowday.sqlite3"
        app = create_app(
            provider=ProactiveProvider(),
            conversation_database_path=path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            initial = await client.get("/api/settings/proactive-chat")
            updated = await client.put(
                "/api/settings/proactive-chat",
                json={
                    "enabled": True,
                    "quiet_hours_start": "23:00",
                    "quiet_hours_end": "07:00",
                    "cooldown_seconds": 1200,
                    "daily_limit": 3,
                    "proactive_chat_style": "warm, brief, and optional",
                },
            )
            invalid = await client.put(
                "/api/settings/proactive-chat",
                json={
                    "enabled": True,
                    "quiet_hours_start": "25:00",
                    "quiet_hours_end": "07:00",
                    "cooldown_seconds": 1200,
                    "daily_limit": 3,
                    "proactive_chat_style": "brief",
                },
            )

        restarted = create_app(
            provider=ProactiveProvider(),
            conversation_database_path=path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://test"
        ) as client:
            persisted = await client.get("/api/settings/proactive-chat")
            persona = await client.get("/api/settings/persona")

        assert initial.json()["settings"]["enabled"] is False
        assert updated.json()["settings"] == {
            "enabled": True,
            "quiet_hours_start": "23:00",
            "quiet_hours_end": "07:00",
            "cooldown_seconds": 1200,
            "daily_limit": 3,
            "proactive_chat_style": "warm, brief, and optional",
        }
        assert invalid.status_code == 422
        assert persisted.json() == updated.json()
        assert persona.json()["persona"]["proactive_chat_style"] == (
            "warm, brief, and optional"
        )

    asyncio.run(exercise())


def test_scheduler_delivers_to_conversation_and_audits_without_prompt(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc).timestamp()
        provider = ProactiveProvider()
        app = create_app(
            provider=provider,
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
            proactive_clock=lambda: now,
            proactive_poll_interval=0.01,
            proactive_minimum_idle_seconds=0,
            proactive_evaluation_interval_seconds=60,
        )
        async with app.router.lifespan_context(app):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                saved = await client.put(
                    "/api/settings/proactive-chat",
                    json={
                        "enabled": True,
                        "quiet_hours_start": "00:00",
                        "quiet_hours_end": "00:00",
                        "cooldown_seconds": 0,
                        "daily_limit": 1,
                        "proactive_chat_style": "gentle and brief",
                    },
                )
                assert saved.status_code == 200
                for _ in range(50):
                    conversation = await client.get("/api/conversations/main")
                    if conversation.status_code == 200:
                        break
                    await asyncio.sleep(0.01)
                audit = await client.get("/api/settings/audit")

        assert conversation.status_code == 200
        assert conversation.json()["messages"] == [
            {
                "role": "assistant",
                "content": "A gentle local check-in.",
                "source": "proactive_chat",
            }
        ]
        assert len(provider.requests) == 1
        assert provider.requests[0].tools == ()
        assert provider.requests[0].skills == ()
        proactive_events = [
            event
            for event in audit.json()["events"]
            if event["details"].get("resource_type")
            == "proactive_chat_evaluation"
        ]
        assert len(proactive_events) == 1
        assert proactive_events[0]["details"] == {
            "action": "proactive_chat_sent",
            "resource_type": "proactive_chat_evaluation",
            "resource_id": proactive_events[0]["details"]["resource_id"],
            "reason": "model_sent",
            "memory_count": 0,
            "life_record_count": 0,
        }
        assert "content" not in proactive_events[0]["details"]

    asyncio.run(exercise())
