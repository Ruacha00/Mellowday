"""Daily Review behavior at the browser-facing API boundary."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from httpx import ASGITransport, AsyncClient

from mellowday.agent_core import ProviderReply, ProviderRequest, ToolCall
from mellowday.web_app import create_app


class FakeProvider:
    name = "fake"

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        return ProviderReply(content=request.messages[-1].content)


def test_settings_returns_an_empty_derived_daily_review_without_persisting_it(
    tmp_path: Path,
) -> None:
    generated_at = datetime(2026, 9, 1, 1, tzinfo=timezone.utc).timestamp()
    database_path = tmp_path / "mellowday.sqlite3"

    async def exercise_boundary() -> dict[str, object]:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=database_path,
            installation_timezone="Asia/Shanghai",
            daily_review_clock=lambda: generated_at,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/settings/daily-review")
        assert response.status_code == 200
        return response.json()

    assert asyncio.run(exercise_boundary()) == {
        "daily_review": {
            "date": "2026-09-01",
            "timezone": "Asia/Shanghai",
            "generated_at": generated_at,
            "tasks": [],
            "reminders": [],
            "calendar_events": [],
            "notes": [],
        }
    }

    with sqlite3.connect(database_path) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert not any("review" in table for table in tables)


def test_settings_derives_each_daily_review_section_from_current_life_records(
    tmp_path: Path,
) -> None:
    generated_at = datetime(2026, 9, 1, 1, tzinfo=timezone.utc).timestamp()

    async def exercise_boundary() -> None:
        app = create_app(
            provider=FakeProvider(),
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            installation_timezone="Asia/Shanghai",
            daily_review_clock=lambda: generated_at,
            life_record_clock=lambda: generated_at,
            reminder_clock=lambda: generated_at,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            overdue_task = await client.post(
                "/api/settings/tasks",
                json={"title": "Submit report", "deadline": "2026-08-31"},
            )
            await client.post(
                "/api/settings/tasks",
                json={
                    "title": "Call the clinic",
                    "deadline": "2026-09-01T17:00:00+08:00",
                },
            )
            await client.post(
                "/api/settings/tasks",
                json={"title": "Plan the weekend", "deadline": "2026-09-05"},
            )
            await client.post(
                "/api/settings/tasks", json={"title": "Buy tea"}
            )
            completed_task = await client.post(
                "/api/settings/tasks",
                json={"title": "Already sent", "deadline": "2026-09-01"},
            )
            await client.post(
                f"/api/settings/tasks/{completed_task.json()['task']['id']}/complete"
            )

            overdue_reminder = await client.post(
                "/api/settings/reminders",
                json={
                    "message": "Take medicine",
                    "due_at": "2026-09-01T08:00:00+08:00",
                },
            )
            await client.post(
                "/api/settings/reminders",
                json={
                    "message": "Join stand-up",
                    "due_at": "2026-09-01T10:00:00+08:00",
                },
            )
            dismissed_reminder = await client.post(
                "/api/settings/reminders",
                json={
                    "message": "Old alert",
                    "due_at": "2026-08-31T08:00:00+08:00",
                },
            )
            await client.post(
                "/api/settings/reminders/"
                f"{dismissed_reminder.json()['reminder']['id']}/dismiss"
            )

            await client.post(
                "/api/settings/calendar-events",
                json={
                    "title": "Overnight maintenance",
                    "start_at": "2026-08-31T23:00",
                    "end_at": "2026-09-01T10:00",
                },
            )
            await client.post(
                "/api/settings/calendar-events",
                json={
                    "title": "Previous day only",
                    "start_at": "2026-08-31T23:00",
                    "end_at": "2026-09-01T00:00",
                },
            )
            await client.post(
                "/api/settings/calendar-events",
                json={"title": "Lunch", "start_at": "2026-09-01T12:00"},
            )
            await client.post(
                "/api/settings/calendar-events",
                json={"title": "Tomorrow", "start_at": "2026-09-02T09:00"},
            )

            note = await client.post(
                "/api/settings/notes",
                json={"title": "Meeting prep", "content": "Bring the figures"},
            )

            first = (await client.get("/api/settings/daily-review")).json()[
                "daily_review"
            ]

            overdue_task_id = overdue_task.json()["task"]["id"]
            overdue_reminder_id = overdue_reminder.json()["reminder"]["id"]
            await client.post(f"/api/settings/tasks/{overdue_task_id}/complete")
            await client.post(
                f"/api/settings/reminders/{overdue_reminder_id}/dismiss"
            )
            await client.patch(
                f"/api/settings/notes/{note.json()['note']['id']}",
                json={"content": "Bring the final figures"},
            )
            refreshed = (await client.get("/api/settings/daily-review")).json()[
                "daily_review"
            ]

        assert [(item["title"], item["timing"]) for item in first["tasks"]] == [
            ("Submit report", "overdue"),
            ("Call the clinic", "due_today"),
            ("Plan the weekend", "upcoming"),
            ("Buy tea", "unscheduled"),
        ]
        assert [
            (item["message"], item["timing"]) for item in first["reminders"]
        ] == [
            ("Take medicine", "overdue"),
            ("Join stand-up", "upcoming"),
        ]
        assert [
            (item["title"], item["timing"])
            for item in first["calendar_events"]
        ] == [
            ("Overnight maintenance", "ongoing"),
            ("Lunch", "upcoming"),
        ]
        assert [(item["title"], item["content"]) for item in first["notes"]] == [
            ("Meeting prep", "Bring the figures")
        ]
        assert {item["title"] for item in refreshed["tasks"]} == {
            "Buy tea",
            "Plan the weekend",
            "Call the clinic",
        }
        assert [item["message"] for item in refreshed["reminders"]] == [
            "Join stand-up"
        ]
        assert refreshed["notes"][0]["content"] == "Bring the final figures"

    asyncio.run(exercise_boundary())


def test_chat_and_settings_share_the_review_while_persona_stays_chat_only(
    tmp_path: Path,
) -> None:
    generated_at = datetime(2026, 9, 1, 1, tzinfo=timezone.utc).timestamp()

    class DailyReviewProvider:
        name = "daily-review-script"

        def __init__(self) -> None:
            self.review: object = None

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            if request.tool_results:
                self.review = request.tool_results[-1].result["daily_review"]
                assert "Assistant name: Luma" in request.system_instructions
                return ProviderReply(
                    content="Luma's gentle take: the report is waiting for you."
                )
            return ProviderReply(
                tool_calls=(
                    ToolCall("today-review", "daily_review_get", {}),
                )
            )

    provider = DailyReviewProvider()

    async def exercise_boundary() -> None:
        app = create_app(
            provider=provider,
            conversation_database_path=tmp_path / "mellowday.sqlite3",
            installation_timezone="Asia/Shanghai",
            daily_review_clock=lambda: generated_at,
            life_record_clock=lambda: generated_at,
            audit_path=None,
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.put(
                "/api/settings/persona",
                json={
                    "name": "Luma",
                    "identity": "a steady companion",
                    "character": "warm and candid",
                    "speaking_style": "gentle",
                    "relationship_framing": "a trusted companion",
                    "conversational_boundaries": "stay truthful",
                    "proactive_chat_style": "brief",
                },
            )
            await client.post(
                "/api/settings/tasks",
                json={"title": "Submit report", "deadline": "2026-09-01"},
            )
            chat = await client.post(
                "/api/chat",
                json={
                    "conversation_id": "main",
                    "content": "How does my day look?",
                },
            )
            settings = await client.get("/api/settings/daily-review")
            capabilities = await client.get("/api/settings/capabilities")

        assert chat.json()["chat_content"]["content"].startswith(
            "Luma's gentle take:"
        )
        assert provider.review == settings.json()["daily_review"]
        assert "Luma" not in str(settings.json())
        review_tool = next(
            tool
            for tool in capabilities.json()["tools"]
            if tool["name"] == "daily_review_get"
        )
        assert review_tool["permission_requirements"] == ["daily_review:read"]
        assert review_tool["side_effect"] == "none"

    asyncio.run(exercise_boundary())
