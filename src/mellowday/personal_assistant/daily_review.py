"""Derived Daily Review assembled from current Life Records."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from .calendar_events import SQLiteCalendarEventService
from .notes import SQLiteNoteService
from .reminders import ReminderState, SQLiteReminderService
from .tasks import SQLiteTaskService


@dataclass(frozen=True, slots=True)
class DailyReviewTask:
    id: str
    title: str
    details: str | None
    deadline: str | None
    timing: Literal["overdue", "due_today", "upcoming", "unscheduled"]


@dataclass(frozen=True, slots=True)
class DailyReviewReminder:
    id: str
    message: str
    due_at: str
    delivery_state: ReminderState
    task_id: str | None
    timing: Literal["overdue", "upcoming"]


@dataclass(frozen=True, slots=True)
class DailyReviewCalendarEvent:
    id: str
    title: str
    start_at: str
    end_at: str | None
    details: str | None
    timing: Literal["past", "ongoing", "upcoming"]


@dataclass(frozen=True, slots=True)
class DailyReviewNote:
    id: str
    title: str | None
    content: str
    updated_at: float
    relevance: Literal["updated_today"]


@dataclass(frozen=True, slots=True)
class DailyReview:
    date: str
    timezone: str
    generated_at: float
    tasks: tuple[DailyReviewTask, ...]
    reminders: tuple[DailyReviewReminder, ...]
    calendar_events: tuple[DailyReviewCalendarEvent, ...]
    notes: tuple[DailyReviewNote, ...]


class DailyReviewService:
    """Build a fresh Daily Review without persisting a copied daily record."""

    def __init__(
        self,
        *,
        tasks: SQLiteTaskService,
        reminders: SQLiteReminderService,
        calendar_events: SQLiteCalendarEventService,
        notes: SQLiteNoteService,
        installation_timezone: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._tasks = tasks
        self._reminders = reminders
        self._calendar_events = calendar_events
        self._notes = notes
        self._timezone_name = installation_timezone
        self._timezone = ZoneInfo(installation_timezone)
        self._clock = clock

    def get(self) -> DailyReview:
        generated_at = self._clock()
        local_now = datetime.fromtimestamp(
            generated_at, timezone.utc
        ).astimezone(self._timezone)
        review_date = local_now.date()
        day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        tasks = tuple(
            sorted(
                (
                    DailyReviewTask(
                        id=task.id,
                        title=task.title,
                        details=task.details,
                        deadline=task.deadline,
                        timing=_task_timing(
                            task.deadline, review_date, self._timezone
                        ),
                    )
                    for task in self._tasks.list()
                    if not task.completed
                ),
                key=_task_sort_key,
            )
        )
        reminders = tuple(
            DailyReviewReminder(
                id=reminder.id,
                message=reminder.message,
                due_at=reminder.due_at,
                delivery_state=reminder.delivery_state,
                task_id=reminder.task_id,
                timing=(
                    "overdue"
                    if datetime.fromisoformat(reminder.due_at).timestamp()
                    <= generated_at
                    else "upcoming"
                ),
            )
            for reminder in self._reminders.list()
            if reminder.delivery_state in {"scheduled", "delivering", "failed"}
        )
        calendar_events = tuple(
            DailyReviewCalendarEvent(
                id=event.id,
                title=event.title,
                start_at=event.start_at,
                end_at=event.end_at,
                details=event.details,
                timing=_calendar_event_timing(
                    event.start_at, event.end_at, local_now
                ),
            )
            for event in self._calendar_events.list()
            if _calendar_event_occurs_on(
                event.start_at, event.end_at, day_start, day_end
            )
        )
        notes = tuple(
            DailyReviewNote(
                id=note.id,
                title=note.title,
                content=note.content,
                updated_at=note.updated_at,
                relevance="updated_today",
            )
            for note in self._notes.list()
            if datetime.fromtimestamp(note.updated_at, timezone.utc)
            .astimezone(self._timezone)
            .date()
            == review_date
        )
        return DailyReview(
            date=local_now.date().isoformat(),
            timezone=self._timezone_name,
            generated_at=generated_at,
            tasks=tasks,
            reminders=reminders,
            calendar_events=calendar_events,
            notes=notes,
        )


def _task_timing(
    deadline: str | None, review_date: date, installation_timezone: ZoneInfo
) -> Literal["overdue", "due_today", "upcoming", "unscheduled"]:
    if deadline is None:
        return "unscheduled"
    parsed = datetime.fromisoformat(deadline)
    deadline_date = (
        parsed.date()
        if parsed.tzinfo is None
        else parsed.astimezone(installation_timezone).date()
    )
    if deadline_date < review_date:
        return "overdue"
    if deadline_date == review_date:
        return "due_today"
    return "upcoming"


def _task_sort_key(task: DailyReviewTask) -> tuple[int, str, str]:
    priority = {
        "overdue": 0,
        "due_today": 1,
        "upcoming": 2,
        "unscheduled": 3,
    }
    return priority[task.timing], task.deadline or "", task.id


def _calendar_event_occurs_on(
    start_at: str,
    end_at: str | None,
    day_start: datetime,
    day_end: datetime,
) -> bool:
    start = datetime.fromisoformat(start_at)
    if end_at is None:
        return day_start <= start < day_end
    end = datetime.fromisoformat(end_at)
    return start < day_end and end > day_start


def _calendar_event_timing(
    start_at: str, end_at: str | None, local_now: datetime
) -> Literal["past", "ongoing", "upcoming"]:
    start = datetime.fromisoformat(start_at)
    end = datetime.fromisoformat(end_at) if end_at is not None else start
    if end <= local_now:
        return "past"
    if start <= local_now:
        return "ongoing"
    return "upcoming"


def daily_review_payload(review: DailyReview) -> dict[str, object]:
    """Render one neutral JSON-compatible projection for every product surface."""

    return {
        "date": review.date,
        "timezone": review.timezone,
        "generated_at": review.generated_at,
        "tasks": [asdict(task) for task in review.tasks],
        "reminders": [asdict(reminder) for reminder in review.reminders],
        "calendar_events": [asdict(event) for event in review.calendar_events],
        "notes": [asdict(note) for note in review.notes],
    }


__all__ = [
    "DailyReview",
    "DailyReviewCalendarEvent",
    "DailyReviewNote",
    "DailyReviewReminder",
    "DailyReviewService",
    "DailyReviewTask",
    "daily_review_payload",
]
