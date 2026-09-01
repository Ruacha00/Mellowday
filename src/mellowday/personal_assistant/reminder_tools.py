"""Registered Tool adapters for Reminder operations."""

from dataclasses import asdict
from typing import cast

from mellowday.agent_core import Tool

from .reminders import Reminder, ReminderUpdates, SQLiteReminderService


def build_reminder_tools(service: SQLiteReminderService) -> tuple[Tool, ...]:
    async def create(arguments: dict[str, object], conversation_id: str) -> object:
        reminder = service.create(
            message=cast(str, arguments["message"]),
            due_at=cast(str, arguments["due_at"]),
            task_id=cast(str | None, arguments.get("task_id")),
            conversation_id=conversation_id,
        )
        return {"reminder": asdict(reminder)}

    async def get(arguments: dict[str, object], _conversation_id: str) -> object:
        return _reminder_result(
            service.get(cast(str, arguments["reminder_id"]))
        )

    async def list_reminders(
        _arguments: dict[str, object], _conversation_id: str
    ) -> object:
        return {"reminders": [asdict(reminder) for reminder in service.list()]}

    async def update(arguments: dict[str, object], _conversation_id: str) -> object:
        updates: ReminderUpdates = {}
        if "message" in arguments:
            updates["message"] = cast(str, arguments["message"])
        if "due_at" in arguments:
            updates["due_at"] = cast(str, arguments["due_at"])
        if "task_id" in arguments:
            updates["task_id"] = cast(str | None, arguments["task_id"])
        return _reminder_result(
            service.update(cast(str, arguments["reminder_id"]), **updates)
        )

    async def dismiss(arguments: dict[str, object], _conversation_id: str) -> object:
        return _reminder_result(
            service.dismiss(cast(str, arguments["reminder_id"]))
        )

    async def cancel(arguments: dict[str, object], _conversation_id: str) -> object:
        return _reminder_result(
            service.cancel(cast(str, arguments["reminder_id"]))
        )

    async def delete(arguments: dict[str, object], _conversation_id: str) -> object:
        reminder = service.delete(cast(str, arguments["reminder_id"]))
        if reminder is None:
            return {"error": "reminder_not_found"}
        return {"deleted_reminder": asdict(reminder)}

    reminder_id_schema = {
        "type": "object",
        "properties": {"reminder_id": {"type": "string", "minLength": 1}},
        "required": ["reminder_id"],
        "additionalProperties": False,
    }
    return (
        Tool(
            name="reminder_create",
            description=(
                "Create a Reminder only when the User clearly provides a specific "
                "due time; ambiguous due times require clarification."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "minLength": 1},
                    "due_at": {
                        "type": "string",
                        "description": "ISO 8601 date-time with a UTC offset.",
                    },
                    "task_id": {"type": ["string", "null"]},
                },
                "required": ["message", "due_at"],
                "additionalProperties": False,
            },
            executor=create,
            permission_requirements=("reminders:write",),
            side_effect="reversible",
        ),
        Tool(
            name="reminder_get",
            description="Retrieve one Reminder by its stable identifier.",
            input_schema=reminder_id_schema,
            executor=get,
            permission_requirements=("reminders:read",),
        ),
        Tool(
            name="reminder_list",
            description="List the User's Reminders and delivery states.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            executor=list_reminders,
            permission_requirements=("reminders:read",),
        ),
        Tool(
            name="reminder_update",
            description="Update and reschedule a Reminder.",
            input_schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "minLength": 1},
                    "message": {"type": "string", "minLength": 1},
                    "due_at": {"type": "string"},
                    "task_id": {"type": ["string", "null"]},
                },
                "required": ["reminder_id"],
                "additionalProperties": False,
            },
            executor=update,
            permission_requirements=("reminders:write",),
            side_effect="reversible",
        ),
        Tool(
            name="reminder_dismiss",
            description="Dismiss a Reminder without completing its linked Task.",
            input_schema=reminder_id_schema,
            executor=dismiss,
            permission_requirements=("reminders:write",),
            side_effect="reversible",
        ),
        Tool(
            name="reminder_cancel",
            description="Cancel a Reminder without completing its linked Task.",
            input_schema=reminder_id_schema,
            executor=cancel,
            permission_requirements=("reminders:write",),
            side_effect="reversible",
        ),
        Tool(
            name="reminder_delete",
            description="Permanently delete a Reminder.",
            input_schema=reminder_id_schema,
            executor=delete,
            permission_requirements=("reminders:delete",),
            side_effect="irreversible",
            risk="medium",
        ),
    )


def _reminder_result(reminder: Reminder | None) -> dict[str, object]:
    if reminder is None:
        return {"error": "reminder_not_found"}
    return {"reminder": asdict(reminder)}


__all__ = ["build_reminder_tools"]
