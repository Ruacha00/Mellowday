"""Calendar Event behavior at the browser-facing API boundary."""

import asyncio
from pathlib import Path

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import ProviderReply, ProviderRequest, ToolCall
from mellowday.web_app import create_app


class FakeProvider:
    name = "fake"

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        return ProviderReply(content=request.messages[-1].content)


def test_settings_manages_persistent_calendar_events_with_conflict_information(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        database_path = tmp_path / "mellowday.sqlite3"
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            installation_timezone="Asia/Shanghai",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            invalid = await client.post(
                "/api/settings/calendar-events",
                json={
                    "title": "Invalid",
                    "start_at": "2026-09-04T18:00",
                    "end_at": "2026-09-04T17:00",
                },
            )
            first = await client.post(
                "/api/settings/calendar-events",
                json={
                    "title": "Project review",
                    "start_at": "2026-09-04T17:00",
                    "end_at": "2026-09-04T18:00",
                    "details": "Discuss launch",
                },
            )
            first_id = first.json()["calendar_event"]["id"]
            second = await client.post(
                "/api/settings/calendar-events",
                json={
                    "title": "Call",
                    "start_at": "2026-09-04T17:30",
                    "end_at": "2026-09-04T18:30",
                },
            )
            second_id = second.json()["calendar_event"]["id"]
            retrieved = await client.get(
                f"/api/settings/calendar-events/{second_id}"
            )
            listed = await client.get("/api/settings/calendar-events")
            updated = await client.patch(
                f"/api/settings/calendar-events/{second_id}",
                json={"start_at": "2026-09-04T19:00", "end_at": None},
            )
            tasks = await client.get("/api/settings/tasks")
            reminders = await client.get("/api/settings/reminders")
            audit = await client.get("/api/settings/audit")
            capabilities = await client.get("/api/settings/capabilities")

        restarted = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            installation_timezone="Asia/Shanghai",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=restarted), base_url="http://test"
        ) as client:
            persisted = await client.get(
                f"/api/settings/calendar-events/{second_id}"
            )
            confirmation_response = await client.post(
                f"/api/settings/calendar-events/{second_id}/delete-confirmation"
            )
            confirmation = confirmation_response.json()["confirmation"]
            deleted = await client.request(
                "DELETE",
                f"/api/settings/calendar-events/{second_id}",
                json={
                    "confirmation_id": confirmation["id"],
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )

        assert invalid.status_code == 422
        assert invalid.json()["detail"] == {
            "code": "invalid_calendar_event",
            "message": "end_at must be after start_at",
        }
        assert first.status_code == 201
        assert first.json()["calendar_event"]["start_at"] == (
            "2026-09-04T17:00:00+08:00"
        )
        assert first.json()["conflicts"] == []
        assert second.json()["conflicts"][0]["id"] == first_id
        assert retrieved.json() == second.json()
        assert [event["id"] for event in listed.json()["calendar_events"]] == [
            first_id,
            second_id,
        ]
        assert listed.json()["conflicts"][second_id][0]["id"] == first_id
        assert updated.json()["conflicts"] == []
        assert persisted.json() == updated.json()
        assert tasks.json() == {"tasks": []}
        assert reminders.json() == {"reminders": []}
        changes = [
            event
            for event in audit.json()["events"]
            if event["type"] == "application_action_completed"
            and event["details"]["resource_type"] == "calendar_event"
        ]
        assert [event["details"]["action"] for event in changes] == [
            "created",
            "created",
            "updated",
        ]
        assert {tool["name"] for tool in capabilities.json()["tools"]} >= {
            "calendar_event_create",
            "calendar_event_get",
            "calendar_event_list",
            "calendar_event_update",
            "calendar_event_delete",
        }
        assert confirmation["binding"]["tool"] == "calendar_event_delete"
        assert deleted.json()["deleted_calendar_event"]["id"] == second_id

    asyncio.run(exercise())


def test_chat_runs_calendar_event_lifecycle_and_clarifies_ambiguous_time(
    tmp_path: Path,
) -> None:
    class CalendarProvider:
        name = "calendar-script"

        def __init__(self) -> None:
            self.event_id = ""
            self.results: list[str] = []

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                result = request.tool_results[-1]
                if result.error == "ambiguous_intent":
                    return ProviderReply(
                        content="What date and time should I put on your calendar?"
                    )
                self.results.append(result.name)
                if result.name == "calendar_event_create":
                    self.event_id = result.result["calendar_event"]["id"]
                return ProviderReply(content=f"Finished {result.name}.")
            command = request.messages[-1].content
            calls = {
                "ambiguous": ToolCall(
                    "ambiguous",
                    "calendar_event_create",
                    {"title": "Dinner", "start_at": "2026-09-04T19:00"},
                    intent_clarity="ambiguous",
                ),
                "create": ToolCall(
                    "create",
                    "calendar_event_create",
                    {
                        "title": "Dinner",
                        "start_at": "2026-09-04T19:00",
                        "end_at": "2026-09-04T20:00",
                    },
                ),
                "list": ToolCall("list", "calendar_event_list", {}),
                "retrieve": ToolCall(
                    "retrieve", "calendar_event_get", {"event_id": self.event_id}
                ),
                "update": ToolCall(
                    "update",
                    "calendar_event_update",
                    {"event_id": self.event_id, "title": "Dinner with Mei"},
                ),
                "delete": ToolCall(
                    "delete",
                    "calendar_event_delete",
                    {"event_id": self.event_id},
                ),
            }
            return ProviderReply(
                content="Please confirm deletion." if command == "delete" else "",
                tool_calls=(calls[command],),
            )

    provider = CalendarProvider()

    async def exercise() -> None:
        app = create_app(
            provider=provider,
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            installation_timezone="Asia/Shanghai",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            ambiguous = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "ambiguous"},
            )
            before = await client.get("/api/settings/calendar-events")
            for command in ("create", "list", "retrieve", "update"):
                response = await client.post(
                    "/api/chat",
                    json={"conversation_id": "main", "content": command},
                )
                assert response.json()["stop_reason"] == "final"
            updated = await client.get(
                f"/api/settings/calendar-events/{provider.event_id}"
            )
            pending = await client.post(
                "/api/chat",
                json={"conversation_id": "main", "content": "delete"},
            )
            confirmation = pending.json()["confirmation"]
            deleted = await client.post(
                f"/api/settings/confirmations/{confirmation['id']}/decision",
                json={
                    "decision": "accept",
                    "binding": confirmation["binding"],
                },
            )
            after = await client.get("/api/settings/calendar-events")
            tasks = await client.get("/api/settings/tasks")
            reminders = await client.get("/api/settings/reminders")
            audit = await client.get("/api/settings/audit")

        assert ambiguous.json()["stop_reason"] == "clarification"
        assert ambiguous.json()["chat_content"]["content"] == (
            "What date and time should I put on your calendar?"
        )
        assert before.json()["calendar_events"] == []
        assert updated.json()["calendar_event"]["title"] == "Dinner with Mei"
        assert pending.json()["stop_reason"] == "confirmation_pending"
        assert deleted.json()["turn"]["stop_reason"] == "confirmation_accepted"
        assert after.json()["calendar_events"] == []
        assert tasks.json() == {"tasks": []}
        assert reminders.json() == {"reminders": []}
        calendar_events = [
            event
            for event in audit.json()["events"]
            if event["type"] == "application_action_completed"
            and event["details"]["resource_type"] == "calendar_event"
        ]
        assert [event["details"]["action"] for event in calendar_events] == [
            "created",
            "updated",
            "deleted",
        ]
        assert all(event["conversation_id"] == "main" for event in calendar_events)

    asyncio.run(exercise())

    assert provider.results == [
        "calendar_event_create",
        "calendar_event_list",
        "calendar_event_get",
        "calendar_event_update",
        "calendar_event_delete",
    ]


def test_chat_naturally_clarifies_an_ambiguous_installation_time(
    tmp_path: Path,
) -> None:
    class AmbiguousTimeProvider:
        name = "ambiguous-calendar-time"

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                result = request.tool_results[-1]
                assert result.error == "ambiguous_intent"
                assert "UTC offset" in (result.detail or "")
                return ProviderReply(
                    content=(
                        "That time occurs twice. Which UTC offset should I use?"
                    )
                )
            return ProviderReply(
                tool_calls=(
                    ToolCall(
                        "ambiguous-dst-time",
                        "calendar_event_create",
                        {
                            "title": "Night shift",
                            "start_at": "2026-11-01T01:30",
                        },
                    ),
                )
            )

    async def exercise() -> None:
        app = create_app(
            provider=AmbiguousTimeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            installation_timezone="America/New_York",
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "main",
                    "content": "Put the night shift at 1:30 on November 1.",
                },
            )
            events = await client.get("/api/settings/calendar-events")

        assert response.json()["stop_reason"] == "clarification"
        assert response.json()["chat_content"]["content"] == (
            "That time occurs twice. Which UTC offset should I use?"
        )
        assert events.json()["calendar_events"] == []

    asyncio.run(exercise())
