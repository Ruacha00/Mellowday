"""Registered Tool adapters for Note operations."""

from dataclasses import asdict
from typing import cast

from mellowday.agent_core import Tool

from .notes import Note, NoteNotFoundError, NoteUpdates, SQLiteNoteService


def build_note_tools(service: SQLiteNoteService) -> tuple[Tool, ...]:
    async def create(arguments: dict[str, object], conversation_id: str) -> object:
        note = service.create(
            title=cast(str | None, arguments.get("title")),
            content=cast(str, arguments["content"]),
            conversation_id=conversation_id,
        )
        return {"note": asdict(note)}

    async def get(arguments: dict[str, object], _conversation_id: str) -> object:
        note_id = cast(str, arguments["note_id"])
        return {"note": asdict(_require_note(service.get(note_id), note_id))}

    async def search(arguments: dict[str, object], _conversation_id: str) -> object:
        notes = service.search(cast(str, arguments.get("query", "")))
        return {"notes": [asdict(note) for note in notes]}

    async def update(arguments: dict[str, object], conversation_id: str) -> object:
        updates: NoteUpdates = {}
        if "title" in arguments:
            updates["title"] = cast(str | None, arguments["title"])
        if "content" in arguments:
            updates["content"] = cast(str, arguments["content"])
        note = service.update(
            cast(str, arguments["note_id"]),
            **updates,
            conversation_id=conversation_id,
        )
        return {"note": asdict(_require_note(note, cast(str, arguments["note_id"])))}

    async def delete(arguments: dict[str, object], conversation_id: str) -> object:
        note = service.delete(
            cast(str, arguments["note_id"]), conversation_id=conversation_id
        )
        return {
            "deleted_note": asdict(
                _require_note(note, cast(str, arguments["note_id"]))
            )
        }

    note_id_schema = {
        "type": "object",
        "properties": {"note_id": {"type": "string", "minLength": 1}},
        "required": ["note_id"],
        "additionalProperties": False,
    }
    return (
        Tool(
            name="note_create",
            description=(
                "Create a Note only after the User clearly asks to preserve "
                "free-form content."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": ["string", "null"]},
                    "content": {"type": "string", "minLength": 1},
                },
                "required": ["content"],
                "additionalProperties": False,
            },
            executor=create,
            permission_requirements=("notes:write",),
            side_effect="reversible",
        ),
        Tool(
            name="note_get",
            description="Retrieve one Note by its stable identifier.",
            input_schema=note_id_schema,
            executor=get,
            permission_requirements=("notes:read",),
        ),
        Tool(
            name="note_search",
            description="List or search the User's Notes by title and content.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "additionalProperties": False,
            },
            executor=search,
            permission_requirements=("notes:read",),
        ),
        Tool(
            name="note_update",
            description="Update the optional title or content of a Note.",
            input_schema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "minLength": 1},
                    "title": {"type": ["string", "null"]},
                    "content": {"type": "string", "minLength": 1},
                },
                "required": ["note_id"],
                "additionalProperties": False,
            },
            executor=update,
            permission_requirements=("notes:write",),
            side_effect="reversible",
        ),
        Tool(
            name="note_delete",
            description="Permanently delete a Note.",
            input_schema=note_id_schema,
            executor=delete,
            permission_requirements=("notes:delete",),
            side_effect="irreversible",
            risk="medium",
        ),
    )


def _require_note(note: Note | None, note_id: str) -> Note:
    if note is None:
        raise NoteNotFoundError(note_id)
    return note


__all__ = ["build_note_tools"]
