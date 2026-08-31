from pathlib import Path

import pytest

from mellowday.personal_assistant import (
    NoteChange,
    NoteChangeNotificationError,
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
    summarized_changes = [
        (change.operation, change.note_id, change.conversation_id)
        for change in changes
    ]
    assert summarized_changes == [
        ("created", "note-1", "chat-1"),
        ("updated", "note-1", "chat-1"),
        ("deleted", "note-1", "chat-1"),
    ]


def test_note_content_is_required_at_the_service_boundary(tmp_path: Path) -> None:
    service = SQLiteNoteService(tmp_path / "mellowday.sqlite3")

    with pytest.raises(NoteValidationError, match="content"):
        service.create(content="   ")


def test_no_op_note_updates_do_not_change_timestamps_or_emit_events(
    tmp_path: Path,
) -> None:
    changes: list[NoteChange] = []
    service = SQLiteNoteService(
        tmp_path / "mellowday.sqlite3",
        clock=iter((100.0, 200.0)).__next__,
        change_listener=changes.append,
    )
    created = service.create(title="Trip", content="Visit Kyoto")

    unchanged = service.update(created.id, title="Trip", content="Visit Kyoto")

    assert unchanged == created
    assert [change.operation for change in changes] == ["created"]
    with pytest.raises(NoteValidationError, match="at least one"):
        service.update(created.id)


def test_committed_note_change_reports_listener_failure_truthfully(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"

    def unavailable_listener(_change: NoteChange) -> None:
        raise OSError("audit disk unavailable")

    service = SQLiteNoteService(
        database_path,
        id_factory=lambda: "note-1",
        change_listener=unavailable_listener,
    )

    with pytest.raises(NoteChangeNotificationError) as failure:
        service.create(content="Persist this")

    assert failure.value.operation == "created"
    assert failure.value.note_id == "note-1"
    assert failure.value.committed is True
    assert SQLiteNoteService(database_path).get("note-1") is not None
