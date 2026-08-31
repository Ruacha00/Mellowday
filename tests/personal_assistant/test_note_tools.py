import asyncio
from pathlib import Path

from mellowday.personal_assistant import SQLiteNoteService, build_note_tools


def test_registered_note_tools_cover_the_complete_note_lifecycle(
    tmp_path: Path,
) -> None:
    service = SQLiteNoteService(
        tmp_path / "mellowday.sqlite3", id_factory=lambda: "note-1"
    )
    tools = {tool.name: tool for tool in build_note_tools(service)}

    async def exercise_tools() -> None:
        created = await tools["note_create"].executor(
            {"title": "Trip", "content": "Visit Kyoto"}, "chat-1"
        )
        retrieved = await tools["note_get"].executor(
            {"note_id": "note-1"}, "chat-1"
        )
        searched = await tools["note_search"].executor(
            {"query": "kyoto"}, "chat-1"
        )
        updated = await tools["note_update"].executor(
            {"note_id": "note-1", "content": "Visit Nara"}, "chat-1"
        )
        deleted = await tools["note_delete"].executor(
            {"note_id": "note-1"}, "chat-1"
        )

        assert created["note"]["id"] == "note-1"
        assert retrieved["note"]["title"] == "Trip"
        assert searched["notes"] == [created["note"]]
        assert updated["note"]["content"] == "Visit Nara"
        assert deleted["deleted_note"]["id"] == "note-1"

    asyncio.run(exercise_tools())

    assert set(tools) == {
        "note_create",
        "note_get",
        "note_search",
        "note_update",
        "note_delete",
    }
    assert tools["note_create"].side_effect == "reversible"
    assert tools["note_update"].side_effect == "reversible"
    assert tools["note_delete"].side_effect == "irreversible"
