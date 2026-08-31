import asyncio
from pathlib import Path

from mellowday.personal_assistant import (
    ReminderDelivery,
    ReminderScheduler,
    SQLiteReminderService,
    SQLiteTaskService,
)


def test_reminder_lifecycle_survives_restart_and_keeps_linked_task_open(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    task_service = SQLiteTaskService(
        database_path, id_factory=lambda: "task-1"
    )
    task_service.create(title="Submit report")
    times = iter((10.0, 20.0, 30.0, 40.0))
    service = SQLiteReminderService(
        database_path,
        clock=lambda: next(times),
        id_factory=lambda: "reminder-1",
    )

    created = service.create(
        message="Submit the report",
        due_at="2026-09-04T17:00:00+08:00",
        task_id="task-1",
        conversation_id="main",
    )
    updated = service.update(
        created.id,
        message="Send the report",
        due_at="2026-09-04T18:00:00+08:00",
    )
    dismissed = service.dismiss(created.id)
    cancelled = service.cancel(created.id)

    restarted = SQLiteReminderService(database_path)

    assert updated is not None and updated.updated_at == 20.0
    assert dismissed is not None and dismissed.delivery_state == "dismissed"
    assert dismissed.dismissed_at == 30.0
    assert cancelled is not None and cancelled.delivery_state == "cancelled"
    assert cancelled.cancelled_at == 40.0
    assert restarted.get(created.id) == cancelled
    assert restarted.list() == (cancelled,)
    assert task_service.get("task-1").completed is False
    assert restarted.delete(created.id) == cancelled
    assert restarted.get(created.id) is None


def test_scheduler_delivers_each_due_reminder_once_across_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "mellowday.sqlite3"
    service = SQLiteReminderService(
        database_path,
        clock=lambda: 1_788_200_000.0,
        id_factory=lambda: "reminder-1",
    )
    service.create(
        message="Join the call",
        due_at="2026-08-31T10:00:00+00:00",
        conversation_id="main",
    )
    deliveries: list[ReminderDelivery] = []

    async def deliver(delivery: ReminderDelivery) -> None:
        deliveries.append(delivery)

    first = ReminderScheduler(service, deliver, clock=lambda: 1_788_200_100.0)
    asyncio.run(first.run_due())

    restarted_service = SQLiteReminderService(database_path)
    restarted = ReminderScheduler(
        restarted_service, deliver, clock=lambda: 1_788_200_200.0
    )
    asyncio.run(restarted.run_due())

    stored = restarted_service.get("reminder-1")
    assert [(item.reminder_id, item.message, item.conversation_id) for item in deliveries] == [
        ("reminder-1", "Join the call", "main")
    ]
    assert stored is not None and stored.delivery_state == "delivered"
    assert stored.delivery_attempted_at == 1_788_200_100.0
    assert stored.delivered_at == 1_788_200_100.0
    assert stored.delivery_error is None
