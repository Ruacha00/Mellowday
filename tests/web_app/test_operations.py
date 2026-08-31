import asyncio
import logging
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import FakeProvider
from mellowday.web_app import create_app


def test_settings_status_is_role_free_and_never_exposes_provider_credentials(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> tuple[int, dict[str, object], str]:
        app = create_app(
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/settings/providers",
                json={
                    "name": "Local model",
                    "base_url": "http://localhost:9000/v1",
                    "model": "small-model",
                    "api_key": "top-secret-provider-key",
                    "timeout_seconds": 30,
                    "max_retries": 1,
                },
            )
            provider_id = created.json()["provider"]["id"]
            await client.post(f"/api/settings/providers/{provider_id}/select")
            await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "hello"},
            )
            response = await client.get("/api/settings/status")
        return response.status_code, response.json(), response.text

    status_code, payload, response_text = asyncio.run(exercise_boundary())
    provider_id = str(payload.get("provider", {}).get("id", ""))
    assert status_code == 200
    assert payload["backend"] == {"ok": True, "service": "mellowday"}
    assert payload["provider"] == {
        "configured": True,
        "enabled": True,
        "id": provider_id,
        "model": "small-model",
        "name": "Local model",
    }
    assert payload["sessions"] == 1
    assert payload["single_user"] is True
    assert "top-secret-provider-key" not in response_text
    assert "api_key" not in response_text
    assert "role" not in payload


def test_runtime_events_and_logs_have_filters_and_stable_cursors(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> tuple[dict[str, object], ...]:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/chat", json={"conversation_id": "first", "content": "one"}
            )
            first = await client.get(
                "/api/events/recent",
                params={"since": 0, "type": "turn_completed", "limit": 10},
            )
            first_cursor = first.json().get("cursor", 0)
            await client.post(
                "/api/chat", json={"conversation_id": "second", "content": "two"}
            )
            incremental = await client.get(
                "/api/events/recent",
                params={
                    "since": first_cursor,
                    "type": "turn_completed",
                    "conversation_id": "second",
                },
            )

            logging.getLogger("mellowday.test").warning("diagnostic marker")
            logs = await client.get(
                "/api/logs/recent",
                params={"since": 0, "level": "WARNING", "q": "marker"},
            )
            no_more_logs = await client.get(
                "/api/logs/recent", params={"since": logs.json().get("cursor", 0)}
            )
        return first.json(), incremental.json(), logs.json(), no_more_logs.json()

    first, incremental, logs, no_more_logs = asyncio.run(exercise_boundary())
    assert [event["type"] for event in first["events"]] == [
        "turn_completed"
    ]
    assert [event["conversation_id"] for event in incremental["events"]] == [
        "second"
    ]
    assert incremental["cursor"] > first["cursor"]
    assert logs["logs"][-1]["message"] == "diagnostic marker"
    assert logs["logs"][-1]["level"] == "WARNING"
    assert no_more_logs["logs"] == []


def test_diagnostic_probe_uses_agent_core_without_ordinary_history(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> tuple[dict[str, object], dict[str, object]]:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "remember me"},
            )
            probe = await client.post(
                "/api/settings/diagnostics/probe",
                json={"content": "check the core"},
            )
            conversations = await client.get("/api/conversations")
        return probe.json(), conversations.json()

    probe, conversations = asyncio.run(exercise_boundary())
    assert probe["turn"]["chat_content"] == {
        "role": "assistant",
        "content": "I heard: check the core",
    }
    assert probe["duration_ms"] >= 0
    assert probe["events"][-1]["type"] == "turn_completed"
    assert [item["conversation_id"] for item in conversations["conversations"]] == [
        "main"
    ]
