from pathlib import Path

import pytest

from mellowday.personal_assistant import (
    NoteChange,
    NoteValidationError,
    SQLiteNoteService,
)


def test_notes_survive_restart_and_support_search_and_updates(tmp_path: Path) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    changes: list[NoteChange] = []
    timestamps = iter((100.0, 200.0, 300.0))
    service = SQLiteNoteService(
        database_path,
        clock=lambda: next(timestamps),
        id_factory=lambda: "note-1",
        change_listener=changes.append,
    )

    created = service.create(
        title="  Trip ideas  ",
        content="  Visit Kyoto in autumn.  ",
        conversation_id="chat-1",
    )
    restarted = SQLiteNoteService(database_path, clock=lambda: 200.0)
    retrieved = restarted.get(created.id)
    search_results = restarted.search("kYoTo")
    updated = service.update(
        created.id,
        title=None,
        content="Visit Kyoto and Nara in autumn.",
        conversation_id="chat-1",
    )
    deleted = service.delete(created.id, conversation_id="chat-1")

    assert created.id == "note-1"
    assert created.title == "Trip ideas"
    assert created.content == "Visit Kyoto in autumn."
    assert created.created_at == 100.0
    assert created.updated_at == 100.0
    assert retrieved == created
    assert search_results == (created,)
    assert updated is not None
    assert updated.title is None
    assert updated.content == "Visit Kyoto and Nara in autumn."
    assert updated.created_at == 100.0
    assert updated.updated_at == 200.0
    assert deleted == updated
    assert service.list() == ()
    assert [(change.operation, change.note_id, change.conversation_id) for change in changes] == [
        ("created", "note-1", "chat-1"),
        ("updated", "note-1", "chat-1"),
        ("deleted", "note-1", "chat-1"),
    ]


def test_note_content_is_required_at_the_service_boundary(tmp_path: Path) -> None:
    service = SQLiteNoteService(tmp_path / "mellowday.sqlite3")

    with pytest.raises(NoteValidationError, match="content"):
        service.create(content="   ")
