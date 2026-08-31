"""Reminder behavior at the browser-facing API boundary."""

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import ProviderReply, ProviderRequest, ToolCall
from mellowday.web_app import create_app


class FakeProvider:
    name = "fake"

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        return ProviderReply(content=request.messages[-1].content)


def test_settings_manages_reminders_through_the_application_service(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            task = await client.post(
                "/api/settings/tasks", json={"title": "Submit report"}
            )
            task_id = task.json()["task"]["id"]
            created = await client.post(
                "/api/settings/reminders",
                json={
                    "message": "Submit the report",
                    "due_at": "2026-09-04T17:00:00+08:00",
                    "task_id": task_id,
                    "conversation_id": "main",
                },
            )
            reminder_id = created.json()["reminder"]["id"]
            retrieved = await client.get(
                f"/api/settings/reminders/{reminder_id}"
            )
            updated = await client.patch(
                f"/api/settings/reminders/{reminder_id}",
                json={"message": "Send the report"},
            )
            dismissed = await client.post(
                f"/api/settings/reminders/{reminder_id}/dismiss"
            )
            cancelled = await client.post(
                f"/api/settings/reminders/{reminder_id}/cancel"
            )
            listed = await client.get("/api/settings/reminders")
            confirmation_response = await client.post(
                f"/api/settings/reminders/{reminder_id}/delete-confirmation"
            )
            confirmation = confirmation_response.json()["confirmation"]
            deleted = await client.request(
                "DELETE",
                f"/api/settings/reminders/{reminder_id}",
                json={
                    "confirmation_id": confirmation["id"],
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )
            linked_task = await client.get(f"/api/settings/tasks/{task_id}")
            capabilities = await client.get("/api/settings/capabilities")

        assert created.status_code == 201
        assert retrieved.json() == created.json()
        assert updated.json()["reminder"]["message"] == "Send the report"
        assert dismissed.json()["reminder"]["delivery_state"] == "dismissed"
        assert cancelled.json()["reminder"]["delivery_state"] == "cancelled"
        assert listed.json()["reminders"] == [cancelled.json()["reminder"]]
        assert deleted.json()["deleted_reminder"]["id"] == reminder_id
        assert linked_task.json()["task"]["completed"] is False
        assert {item["name"] for item in capabilities.json()["tools"]} >= {
            "reminder_create", "reminder_get", "reminder_list",
            "reminder_update", "reminder_dismiss", "reminder_cancel",
            "reminder_delete",
        }

    asyncio.run(exercise())


def test_chat_creates_clear_reminders_and_clarifies_ambiguous_due_times(
    tmp_path: Path,
) -> None:
    class ReminderProvider:
        name = "reminder-script"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                if request.tool_results[-1].error == "ambiguous_intent":
                    return ProviderReply(content="What time should I remind you?")
                return ProviderReply(content="I’ll remind you at five.")
            command = request.messages[-1].content
            call = ToolCall(
                command,
                "reminder_create",
                {
                    "message": "Join the call",
                    "due_at": "2026-09-04T17:00:00+08:00",
                },
                intent_clarity="ambiguous" if command == "later" else "clear",
            )
            return ProviderReply(tool_calls=(call,))

    async def exercise() -> None:
        app = create_app(
            provider=ReminderProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            ambiguous = await client.post(
                "/api/chat", json={"conversation_id": "main", "content": "later"}
            )
            before = await client.get("/api/settings/reminders")
            clear = await client.post(
                "/api/chat", json={"conversation_id": "main", "content": "five"}
            )
            after = await client.get("/api/settings/reminders")

        assert ambiguous.json()["stop_reason"] == "clarification"
        assert ambiguous.json()["chat_content"]["content"] == (
            "What time should I remind you?"
        )
        assert before.json() == {"reminders": []}
        assert clear.json()["stop_reason"] == "final"
        assert len(after.json()["reminders"]) == 1
        assert after.json()["reminders"][0]["conversation_id"] == "main"

    asyncio.run(exercise())
