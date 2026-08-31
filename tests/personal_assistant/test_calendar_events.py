from pathlib import Path

import pytest

from mellowday.personal_assistant import (
    CalendarEventChange,
    CalendarEventTimeClarificationRequired,
    CalendarEventValidationError,
    SQLiteCalendarEventService,
    SQLiteReminderService,
    SQLiteTaskService,
)


def test_calendar_events_use_installation_timezone_and_survive_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    changes: list[CalendarEventChange] = []
    ids = iter(("event-1", "event-2"))
    timestamps = iter((100.0, 200.0, 300.0, 400.0))
    service = SQLiteCalendarEventService(
        database_path,
        installation_timezone="Asia/Shanghai",
        clock=lambda: next(timestamps),
        id_factory=lambda: next(ids),
        change_listener=changes.append,
    )

    created = service.create(
        title="  Project review  ",
        start_at="2026-09-04T17:00",
        end_at="2026-09-04T18:00",
        details="  Discuss the launch plan.  ",
        conversation_id="chat-1",
    )
    overlapping = service.create(
        title="Call",
        start_at="2026-09-04T17:30:00+08:00",
        conversation_id="chat-1",
    )
    restarted = SQLiteCalendarEventService(
        database_path, installation_timezone="Asia/Shanghai"
    )

    assert created.id == "event-1"
    assert created.title == "Project review"
    assert created.start_at == "2026-09-04T17:00:00+08:00"
    assert created.end_at == "2026-09-04T18:00:00+08:00"
    assert created.details == "Discuss the launch plan."
    assert created.created_at == created.updated_at == 100.0
    assert restarted.get(created.id) == created
    assert restarted.list() == (created, overlapping)
    assert restarted.conflicts_for(created.id) == (overlapping,)
    assert SQLiteTaskService(database_path).list() == ()
    assert SQLiteReminderService(database_path).list() == ()

    updated = service.update(
        created.id,
        title="Launch review",
        start_at="2026-09-04T19:00",
        end_at=None,
        conversation_id="chat-1",
    )
    deleted = service.delete(created.id, conversation_id="chat-1")

    assert updated is not None
    assert updated.title == "Launch review"
    assert updated.start_at == "2026-09-04T19:00:00+08:00"
    assert updated.end_at is None
    assert updated.created_at == 100.0
    assert updated.updated_at == 300.0
    assert deleted == updated
    assert service.get(created.id) is None
    assert [change.operation for change in changes] == [
        "created",
        "created",
        "updated",
        "deleted",
    ]
    assert all(change.conversation_id == "chat-1" for change in changes)


def test_calendar_event_time_range_is_validated_at_the_service_boundary(
    tmp_path: Path,
) -> None:
    service = SQLiteCalendarEventService(
        tmp_path / "mellowday.sqlite3", installation_timezone="Asia/Shanghai"
    )

    with pytest.raises(CalendarEventValidationError, match="date-time"):
        service.create(title="Review", start_at="2026-09-04")
    with pytest.raises(CalendarEventValidationError, match="after start_at"):
        service.create(
            title="Review",
            start_at="2026-09-04T18:00",
            end_at="2026-09-04T17:00",
        )


def test_ambiguous_or_nonexistent_local_time_requires_clarification(
    tmp_path: Path,
) -> None:
    service = SQLiteCalendarEventService(
        tmp_path / "mellowday.sqlite3",
        installation_timezone="America/New_York",
    )

    with pytest.raises(
        CalendarEventTimeClarificationRequired, match="UTC offset"
    ):
        service.create(title="Night shift", start_at="2026-11-01T01:30")
    with pytest.raises(
        CalendarEventTimeClarificationRequired, match="does not exist"
    ):
        service.create(title="Early call", start_at="2026-03-08T02:30")

    explicit = service.create(
        title="Night shift",
        start_at="2026-11-01T01:30:00-05:00",
    )

    assert explicit.start_at == "2026-11-01T01:30:00-05:00"
