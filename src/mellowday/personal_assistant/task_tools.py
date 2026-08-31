"""Registered Tool adapters for Task operations."""

from dataclasses import asdict
from typing import cast

from mellowday.agent_core import Tool

from .tasks import SQLiteTaskService, Task


def build_task_tools(service: SQLiteTaskService) -> tuple[Tool, ...]:
    async def create(arguments: dict[str, object], conversation_id: str) -> object:
        task = service.create(
            title=cast(str, arguments["title"]),
            details=cast(str | None, arguments.get("details")),
            deadline=cast(str | None, arguments.get("deadline")),
            conversation_id=conversation_id,
        )
        return {"task": asdict(task)}

    async def get(arguments: dict[str, object], _conversation_id: str) -> object:
        return _task_result(service.get(cast(str, arguments["task_id"])))

    async def list_tasks(
        _arguments: dict[str, object], _conversation_id: str
    ) -> object:
        return {"tasks": [asdict(task) for task in service.list()]}

    async def update(arguments: dict[str, object], conversation_id: str) -> object:
        task_id = cast(str, arguments["task_id"])
        current = service.get(task_id)
        if current is None:
            return _task_result(None)
        task = service.update(
            task_id,
            title=cast(str, arguments.get("title", current.title)),
            details=cast(str | None, arguments.get("details", current.details)),
            deadline=cast(str | None, arguments.get("deadline", current.deadline)),
            conversation_id=conversation_id,
        )
        return _task_result(task)

    async def complete(arguments: dict[str, object], conversation_id: str) -> object:
        task = service.complete(
            cast(str, arguments["task_id"]), conversation_id=conversation_id
        )
        return _task_result(task)

    async def reopen(arguments: dict[str, object], conversation_id: str) -> object:
        task = service.reopen(
            cast(str, arguments["task_id"]), conversation_id=conversation_id
        )
        return _task_result(task)

    async def delete(arguments: dict[str, object], conversation_id: str) -> object:
        task = service.delete(
            cast(str, arguments["task_id"]), conversation_id=conversation_id
        )
        if task is None:
            return {"error": "task_not_found"}
        return {"deleted_task": asdict(task)}

    task_id_schema = {
        "type": "object",
        "properties": {"task_id": {"type": "string", "minLength": 1}},
        "required": ["task_id"],
        "additionalProperties": False,
    }
    return (
        Tool(
            name="task_create",
            description="Create a Task after the User clearly asks to create one.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "details": {"type": "string"},
                    "deadline": {"type": "string"},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            executor=create,
            permission_requirements=("tasks:write",),
            side_effect="reversible",
        ),
        Tool(
            name="task_get",
            description="Retrieve one Task by its stable identifier.",
            input_schema=task_id_schema,
            executor=get,
            permission_requirements=("tasks:read",),
        ),
        Tool(
            name="task_list",
            description="List the User's Tasks.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            executor=list_tasks,
            permission_requirements=("tasks:read",),
        ),
        Tool(
            name="task_update",
            description="Update the title, details, or deadline of a Task.",
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "minLength": 1},
                    "title": {"type": "string", "minLength": 1},
                    "details": {"type": "string"},
                    "deadline": {"type": "string"},
                },
                "required": ["task_id"],
                "additionalProperties": False,
            },
            executor=update,
            permission_requirements=("tasks:write",),
            side_effect="reversible",
        ),
        Tool(
            name="task_complete",
            description="Mark a Task complete.",
            input_schema=task_id_schema,
            executor=complete,
            permission_requirements=("tasks:write",),
            side_effect="reversible",
        ),
        Tool(
            name="task_reopen",
            description="Reopen a completed Task.",
            input_schema=task_id_schema,
            executor=reopen,
            permission_requirements=("tasks:write",),
            side_effect="reversible",
        ),
        Tool(
            name="task_delete",
            description="Permanently delete a Task.",
            input_schema=task_id_schema,
            executor=delete,
            permission_requirements=("tasks:delete",),
            side_effect="irreversible",
            risk="medium",
        ),
    )


def _task_result(task: Task | None) -> dict[str, object]:
    if task is None:
        return {"error": "task_not_found"}
    return {"task": asdict(task)}


__all__ = ["build_task_tools"]
