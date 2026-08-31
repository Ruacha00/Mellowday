import asyncio
from pathlib import Path

import pytest

from mellowday.personal_assistant import (
    CalendarEventNotFoundError,
    SQLiteCalendarEventService,
    build_calendar_event_tools,
)


def test_registered_calendar_event_tools_cover_the_complete_lifecycle(
    tmp_path: Path,
) -> None:
    ids = iter(("event-1", "event-2"))
    service = SQLiteCalendarEventService(
        tmp_path / "mellowday.sqlite3",
        installation_timezone="Asia/Shanghai",
        id_factory=lambda: next(ids),
    )
    service.create(
        title="Existing call",
        start_at="2026-09-04T17:30",
        end_at="2026-09-04T18:30",
    )
    tools = {tool.name: tool for tool in build_calendar_event_tools(service)}

    async def exercise_tools() -> None:
        created = await tools["calendar_event_create"].executor(
            {
                "title": "Project review",
                "start_at": "2026-09-04T17:00",
                "end_at": "2026-09-04T18:00",
                "details": "Discuss launch",
            },
            "chat-1",
        )
        retrieved = await tools["calendar_event_get"].executor(
            {"event_id": "event-2"}, "chat-1"
        )
        listed = await tools["calendar_event_list"].executor({}, "chat-1")
        updated = await tools["calendar_event_update"].executor(
            {
                "event_id": "event-2",
                "title": "Launch review",
                "start_at": "2026-09-04T19:00",
                "end_at": None,
            },
            "chat-1",
        )
        deleted = await tools["calendar_event_delete"].executor(
            {"event_id": "event-2"}, "chat-1"
        )

        assert created["calendar_event"]["id"] == "event-2"
        assert created["conflicts"][0]["id"] == "event-1"
        assert retrieved == created
        assert len(listed["calendar_events"]) == 2
        assert updated["calendar_event"]["title"] == "Launch review"
        assert updated["conflicts"] == []
        assert deleted["deleted_calendar_event"]["id"] == "event-2"

    asyncio.run(exercise_tools())

    assert set(tools) == {
        "calendar_event_create",
        "calendar_event_get",
        "calendar_event_list",
        "calendar_event_update",
        "calendar_event_delete",
    }
    assert "clarif" in tools["calendar_event_create"].description.lower()
    assert tools["calendar_event_create"].side_effect == "reversible"
    assert tools["calendar_event_update"].side_effect == "reversible"
    assert tools["calendar_event_delete"].side_effect == "irreversible"


def test_missing_calendar_event_is_a_tool_failure(tmp_path: Path) -> None:
    tools = {
        tool.name: tool
        for tool in build_calendar_event_tools(
            SQLiteCalendarEventService(
                tmp_path / "mellowday.sqlite3",
                installation_timezone="Asia/Shanghai",
            )
        )
    }

    with pytest.raises(CalendarEventNotFoundError, match="Calendar Event not found"):
        asyncio.run(
            tools["calendar_event_get"].executor(
                {"event_id": "missing"}, "chat-1"
            )
        )
