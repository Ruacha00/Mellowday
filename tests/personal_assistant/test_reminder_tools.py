import asyncio
from pathlib import Path

from mellowday.personal_assistant import SQLiteReminderService, build_reminder_tools


def test_registered_reminder_tools_cover_the_complete_lifecycle(
    tmp_path: Path,
) -> None:
    service = SQLiteReminderService(
        tmp_path / "mellowday.sqlite3", id_factory=lambda: "reminder-1"
    )
    tools = {tool.name: tool for tool in build_reminder_tools(service)}

    async def exercise() -> None:
        created = await tools["reminder_create"].executor(
            {
                "message": "Join the call",
                "due_at": "2026-09-04T17:00:00+08:00",
            },
            "main",
        )
        assert created["reminder"]["id"] == "reminder-1"
        retrieved = await tools["reminder_get"].executor(
            {"reminder_id": "reminder-1"}, "main"
        )
        assert retrieved["reminder"]["message"] == "Join the call"
        updated = await tools["reminder_update"].executor(
            {"reminder_id": "reminder-1", "message": "Join stand-up"}, "main"
        )
        assert updated["reminder"]["message"] == "Join stand-up"
        assert (await tools["reminder_list"].executor({}, "main"))["reminders"]
        dismissed = await tools["reminder_dismiss"].executor(
            {"reminder_id": "reminder-1"}, "main"
        )
        assert dismissed["reminder"]["delivery_state"] == "dismissed"
        cancelled = await tools["reminder_cancel"].executor(
            {"reminder_id": "reminder-1"}, "main"
        )
        assert cancelled["reminder"]["delivery_state"] == "cancelled"
        deleted = await tools["reminder_delete"].executor(
            {"reminder_id": "reminder-1"}, "main"
        )
        assert deleted["deleted_reminder"]["id"] == "reminder-1"

    asyncio.run(exercise())

    assert set(tools) == {
        "reminder_create", "reminder_get", "reminder_list", "reminder_update",
        "reminder_dismiss", "reminder_cancel", "reminder_delete",
    }
    assert tools["reminder_create"].side_effect == "reversible"
    assert tools["reminder_delete"].side_effect == "irreversible"
