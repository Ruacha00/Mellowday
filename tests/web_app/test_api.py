import asyncio

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import FakeProvider
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
