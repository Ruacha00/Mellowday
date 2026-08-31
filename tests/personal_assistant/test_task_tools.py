import asyncio
from pathlib import Path

from mellowday.personal_assistant import SQLiteTaskService, build_task_tools


def test_registered_task_tools_cover_the_complete_task_lifecycle(
    tmp_path: Path,
) -> None:
    service = SQLiteTaskService(
        tmp_path / "mellowday.sqlite3", id_factory=lambda: "task-1"
    )
    tools = {tool.name: tool for tool in build_task_tools(service)}

    async def exercise() -> None:
        created = await tools["task_create"].executor(
            {
                "title": "Submit report",
                "details": "Attach charts",
                "deadline": "2026-09-04",
            },
            "chat-1",
        )
        assert created["task"]["id"] == "task-1"

        retrieved = await tools["task_get"].executor(
            {"task_id": "task-1"}, "chat-1"
        )
        assert retrieved["task"]["title"] == "Submit report"

        updated = await tools["task_update"].executor(
            {"task_id": "task-1", "title": "Send report", "details": ""},
            "chat-1",
        )
        assert updated["task"]["title"] == "Send report"
        assert updated["task"]["details"] is None

        completed = await tools["task_complete"].executor(
            {"task_id": "task-1"}, "chat-1"
        )
        assert completed["task"]["completed"] is True

        reopened = await tools["task_reopen"].executor(
            {"task_id": "task-1"}, "chat-1"
        )
        assert reopened["task"]["completed"] is False

        listed = await tools["task_list"].executor({}, "chat-1")
        assert [task["id"] for task in listed["tasks"]] == ["task-1"]

        deleted = await tools["task_delete"].executor(
            {"task_id": "task-1"}, "chat-1"
        )
        assert deleted["deleted_task"]["id"] == "task-1"

    asyncio.run(exercise())

    assert set(tools) == {
        "task_create",
        "task_get",
        "task_list",
        "task_update",
        "task_complete",
        "task_reopen",
        "task_delete",
    }
    assert tools["task_delete"].side_effect == "irreversible"
    assert service.list() == ()
