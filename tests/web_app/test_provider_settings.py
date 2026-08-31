import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.web_app import create_app
from mellowday.agent_core.openai_compatible import ProviderTransportResponse


class RecordedTransport:
    def __init__(
        self, replies: tuple[str | ProviderTransportResponse, ...]
    ) -> None:
        self._replies = iter(replies)
        self.requests: list[dict[str, object]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object] | None,
        timeout: float,
    ) -> ProviderTransportResponse:
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "json": json}
        )
        reply = next(self._replies)
        if isinstance(reply, ProviderTransportResponse):
            return reply
        return ProviderTransportResponse(
            status_code=200,
            payload={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": reply},
                    }
                ]
            },
        )


def test_settings_create_and_list_provider_with_masked_local_credentials(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        database_path = tmp_path / "mellowday.sqlite3"
        app = create_app(
            conversation_database_path=database_path,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/settings/providers",
                json={
                    "name": "Local model",
                    "base_url": "http://localhost:9000/v1",
                    "model": "chat-model",
                    "api_key": "super-secret-key",
                    "timeout_seconds": 12,
                    "max_retries": 1,
                },
            )
            listed = await client.get("/api/settings/providers")

        assert created.status_code == 201
        provider = created.json()["provider"]
        assert provider["api_key"] == "••••-key"
        assert "super-secret-key" not in created.text
        assert listed.status_code == 200
        assert listed.json() == {"providers": [provider]}
        assert "super-secret-key" not in listed.text
        assert b"super-secret-key" in database_path.read_bytes()

    asyncio.run(exercise_boundary())


def test_settings_validate_and_disable_a_provider(tmp_path: Path) -> None:
    async def exercise_boundary() -> None:
        transport = RecordedTransport(
            (
                ProviderTransportResponse(
                    status_code=200, payload={"data": [{"id": "chat-model"}]}
                ),
            )
        )
        app = create_app(
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
            provider_transport=transport,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/settings/providers",
                json={
                    "name": "Local model",
                    "base_url": "http://localhost:9000/v1",
                    "model": "chat-model",
                    "api_key": "local-secret",
                    "timeout_seconds": 12,
                    "max_retries": 0,
                },
            )
            provider_id = created.json()["provider"]["id"]
            await client.post(f"/api/settings/providers/{provider_id}/select")
            validated = await client.post(
                f"/api/settings/providers/{provider_id}/validate"
            )
            status = await client.get("/api/settings/status")
            disabled = await client.put(
                f"/api/settings/providers/{provider_id}/enabled",
                json={"enabled": False},
            )
            reselection = await client.post(
                f"/api/settings/providers/{provider_id}/select"
            )
            fallback_turn = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Hello"},
            )

        assert validated.status_code == 200
        assert validated.json() == {"valid": True}
        assert status.json()["provider"]["health"]["state"] == "available"
        assert status.json()["provider"]["health"]["checked_at"] > 0
        assert transport.requests[0]["method"] == "GET"
        assert transport.requests[0]["url"] == "http://localhost:9000/v1/models"
        assert disabled.status_code == 200
        assert disabled.json()["provider"]["enabled"] is False
        assert disabled.json()["provider"]["selected"] is False
        assert reselection.status_code == 409
        assert fallback_turn.json()["stop_reason"] == "provider_error"
        assert "no model Provider is selected" in fallback_turn.json()[
            "chat_content"
        ]["content"]

    asyncio.run(exercise_boundary())


def test_provider_credentials_never_appear_in_chat_events_or_diagnostics(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        secret = "credential-that-must-stay-local"
        transport = RecordedTransport(
            (
                ProviderTransportResponse(
                    status_code=401,
                    payload={"error": {"message": f"invalid key {secret}"}},
                ),
            )
        )
        app = create_app(
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
            provider_transport=transport,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/settings/providers",
                json={
                    "name": "Remote model",
                    "base_url": "https://example.invalid/v1",
                    "model": "chat-model",
                    "api_key": secret,
                    "timeout_seconds": 12,
                    "max_retries": 0,
                },
            )
            provider_id = created.json()["provider"]["id"]
            await client.post(f"/api/settings/providers/{provider_id}/select")
            chat = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Hello"},
            )
            audit = await client.get("/api/settings/audit")
            events = await client.get("/api/events/recent")
            diagnostics = await client.get("/healthz")
            settings = await client.get("/api/settings/providers")
            operation_status = await client.get("/api/settings/status")
            logs = await client.get("/api/logs/recent")

        outputs = (
            chat,
            audit,
            events,
            diagnostics,
            settings,
            operation_status,
            logs,
        )
        assert all(secret not in response.text for response in outputs)
        assert chat.json()["stop_reason"] == "provider_error"
        assert "rejected its credentials" in chat.json()["chat_content"]["content"]
        assert chat.json()["events"][2]["details"] == {
            "provider": "Remote model",
            "code": "authentication",
            "retryable": False,
            "attempts": 1,
        }
        assert diagnostics.json() == {"ok": True}

    asyncio.run(exercise_boundary())


def test_failed_validation_returns_safe_neutral_diagnostics(tmp_path: Path) -> None:
    async def exercise_boundary() -> None:
        secret = "validation-secret"
        transport = RecordedTransport(
            (
                ProviderTransportResponse(
                    status_code=401,
                    payload={"error": {"message": f"invalid {secret}"}},
                ),
            )
        )
        app = create_app(
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
            provider_transport=transport,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/settings/providers",
                json={
                    "name": "Remote model",
                    "base_url": "https://example.invalid/v1",
                    "model": "chat-model",
                    "api_key": secret,
                    "timeout_seconds": 12,
                    "max_retries": 0,
                },
            )
            provider_id = created.json()["provider"]["id"]
            validation = await client.post(
                f"/api/settings/providers/{provider_id}/validate"
            )

        assert validation.status_code == 200
        assert validation.json() == {
            "valid": False,
            "failure": {
                "code": "authentication",
                "retryable": False,
                "attempts": 1,
            },
        }
        assert secret not in validation.text

    asyncio.run(exercise_boundary())


def test_selected_provider_and_edits_apply_to_subsequent_turns(
    tmp_path: Path,
) -> None:
    async def exercise_boundary() -> None:
        transport = RecordedTransport(("First provider reply", "Edited model reply"))
        app = create_app(
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
            provider_transport=transport,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/api/settings/providers",
                json={
                    "name": "Local model",
                    "base_url": "http://localhost:9000/v1",
                    "model": "first-model",
                    "api_key": "local-secret",
                    "timeout_seconds": 12,
                    "max_retries": 0,
                },
            )
            provider_id = created.json()["provider"]["id"]
            selected = await client.post(
                f"/api/settings/providers/{provider_id}/select"
            )
            first_turn = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Hello"},
            )
            edited = await client.put(
                f"/api/settings/providers/{provider_id}",
                json={
                    "name": "Local model",
                    "base_url": "http://localhost:9000/v1",
                    "model": "edited-model",
                    "api_key": "",
                    "timeout_seconds": 12,
                    "max_retries": 0,
                },
            )
            second_turn = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "Again"},
            )

        assert selected.status_code == 200
        assert selected.json()["provider"]["selected"] is True
        assert first_turn.json()["chat_content"]["content"] == "First provider reply"
        assert edited.status_code == 200
        assert edited.json()["provider"]["api_key"] == "••••cret"
        assert second_turn.json()["chat_content"]["content"] == "Edited model reply"
        assert [request["json"]["model"] for request in transport.requests] == [
            "first-model",
            "edited-model",
        ]
        assert all(
            request["headers"]["Authorization"] == "Bearer local-secret"
            for request in transport.requests
        )

    asyncio.run(exercise_boundary())
