from pathlib import Path

import pytest

from mellowday.personal_assistant import (
    SQLiteTaskService,
    TaskChange,
    TaskValidationError,
)


def test_task_creation_survives_restart_with_stable_fields(tmp_path: Path) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    service = SQLiteTaskService(database_path, clock=lambda: 1_725_000_000.0)

    created = service.create(
        title="Submit the report",
        details="Attach the final charts",
        deadline="2026-09-04T17:00:00+08:00",
    )

    restarted = SQLiteTaskService(database_path, clock=lambda: 1_725_000_100.0)
    stored = restarted.get(created.id)

    assert stored == created
    assert stored.id
    assert stored.title == "Submit the report"
    assert stored.details == "Attach the final charts"
    assert stored.completed is False
    assert stored.deadline == "2026-09-04T17:00:00+08:00"
    assert stored.created_at == 1_725_000_000.0
    assert stored.updated_at == 1_725_000_000.0
    assert stored.completed_at is None


def test_task_lifecycle_uses_one_service_and_emits_operation_changes(
    tmp_path: Path,
) -> None:
    changes: list[TaskChange] = []
    times = iter((10.0, 20.0, 30.0, 40.0, 50.0))
    service = SQLiteTaskService(
        tmp_path / "mellowday.sqlite3",
        clock=lambda: next(times),
        id_factory=lambda: "task-1",
        change_listener=changes.append,
    )

    created = service.create(title="Draft report", conversation_id="chat-1")
    updated = service.update(
        created.id,
        title="Submit report",
        details="Use final figures",
        deadline="2026-09-04",
    )
    completed = service.complete(created.id)
    reopened = service.reopen(created.id)
    listed = service.list()
    deleted = service.delete(created.id)

    assert updated is not None and updated.updated_at == 20.0
    assert completed is not None and completed.completed_at == 30.0
    assert reopened is not None and reopened.completed_at is None
    assert listed == (reopened,)
    assert deleted == reopened
    assert service.get(created.id) is None
    assert [change.operation for change in changes] == [
        "created",
        "updated",
        "completed",
        "reopened",
        "deleted",
    ]
    assert changes[0].conversation_id == "chat-1"
    assert all(change.task_id == "task-1" for change in changes)


def test_task_input_is_validated_at_the_service_boundary(tmp_path: Path) -> None:
    service = SQLiteTaskService(tmp_path / "mellowday.sqlite3")

    with pytest.raises(TaskValidationError, match="title"):
        service.create(title="   ")
    with pytest.raises(TaskValidationError, match="UTC offset"):
        service.create(title="Report", deadline="2026-09-04T17:00:00")
