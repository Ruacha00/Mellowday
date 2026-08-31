"""Registered Tool adapters for Calendar Event operations."""

from dataclasses import asdict
from typing import cast

from mellowday.agent_core import Tool

from .calendar_events import (
    CalendarEvent,
    CalendarEventNotFoundError,
    CalendarEventUpdates,
    SQLiteCalendarEventService,
)


def build_calendar_event_tools(
    service: SQLiteCalendarEventService,
) -> tuple[Tool, ...]:
    async def create(arguments: dict[str, object], conversation_id: str) -> object:
        event = service.create(
            title=cast(str, arguments["title"]),
            start_at=cast(str, arguments["start_at"]),
            end_at=cast(str | None, arguments.get("end_at")),
            details=cast(str | None, arguments.get("details")),
            conversation_id=conversation_id,
        )
        return _event_payload(service, event)

    async def get(arguments: dict[str, object], _conversation_id: str) -> object:
        event_id = cast(str, arguments["event_id"])
        return _event_payload(service, _require_event(service.get(event_id), event_id))

    async def list_events(
        _arguments: dict[str, object], _conversation_id: str
    ) -> object:
        return {
            "calendar_events": [asdict(event) for event in service.list()]
        }

    async def update(arguments: dict[str, object], conversation_id: str) -> object:
        updates: CalendarEventUpdates = {}
        if "title" in arguments:
            updates["title"] = cast(str, arguments["title"])
        if "start_at" in arguments:
            updates["start_at"] = cast(str, arguments["start_at"])
        if "end_at" in arguments:
            updates["end_at"] = cast(str | None, arguments["end_at"])
        if "details" in arguments:
            updates["details"] = cast(str | None, arguments["details"])
        event_id = cast(str, arguments["event_id"])
        event = service.update(
            event_id,
            **updates,
            conversation_id=conversation_id,
        )
        return _event_payload(service, _require_event(event, event_id))

    async def delete(arguments: dict[str, object], conversation_id: str) -> object:
        event_id = cast(str, arguments["event_id"])
        event = service.delete(event_id, conversation_id=conversation_id)
        return {"deleted_calendar_event": asdict(_require_event(event, event_id))}

    event_id_schema = {
        "type": "object",
        "properties": {"event_id": {"type": "string", "minLength": 1}},
        "required": ["event_id"],
        "additionalProperties": False,
    }
    time_properties = {
        "start_at": {
            "type": "string",
            "description": (
                "ISO 8601 date-time. A missing UTC offset uses the installation "
                "timezone."
            ),
        },
        "end_at": {"type": ["string", "null"]},
    }
    return (
        Tool(
            name="calendar_event_create",
            description=(
                "Create a Calendar Event after the User clearly supplies its title, "
                "date, and time. Clarify ambiguous required date or time information "
                "before calling this Tool. This does not create a Task or Reminder."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    **time_properties,
                    "details": {"type": ["string", "null"]},
                },
                "required": ["title", "start_at"],
                "additionalProperties": False,
            },
            executor=create,
            permission_requirements=("calendar_events:write",),
            side_effect="reversible",
        ),
        Tool(
            name="calendar_event_get",
            description=(
                "Retrieve one Calendar Event and any conflicting Calendar Events by "
                "its stable identifier."
            ),
            input_schema=event_id_schema,
            executor=get,
            permission_requirements=("calendar_events:read",),
        ),
        Tool(
            name="calendar_event_list",
            description="List the User's Calendar Events in start-time order.",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            executor=list_events,
            permission_requirements=("calendar_events:read",),
        ),
        Tool(
            name="calendar_event_update",
            description=(
                "Update a Calendar Event. Clarify ambiguous required date or time "
                "information before calling this Tool."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "event_id": {"type": "string", "minLength": 1},
                    "title": {"type": "string", "minLength": 1},
                    **time_properties,
                    "details": {"type": ["string", "null"]},
                },
                "required": ["event_id"],
                "additionalProperties": False,
            },
            executor=update,
            permission_requirements=("calendar_events:write",),
            side_effect="reversible",
        ),
        Tool(
            name="calendar_event_delete",
            description="Permanently delete a Calendar Event.",
            input_schema=event_id_schema,
            executor=delete,
            permission_requirements=("calendar_events:delete",),
            side_effect="irreversible",
            risk="medium",
        ),
    )


def _event_payload(
    service: SQLiteCalendarEventService, event: CalendarEvent
) -> dict[str, object]:
    return {
        "calendar_event": asdict(event),
        "conflicts": [
            asdict(conflict) for conflict in service.conflicts_for(event.id)
        ],
    }


def _require_event(
    event: CalendarEvent | None, event_id: str
) -> CalendarEvent:
    if event is None:
        raise CalendarEventNotFoundError(event_id)
    return event


__all__ = ["build_calendar_event_tools"]
