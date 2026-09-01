"""Bounded, read-only Proactive Chat evaluation and persistence."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mellowday.agent_core import (
    ChatContent,
    ModelProvider,
    ProviderFailure,
    ProviderRequest,
)

from .calendar_events import CalendarEvent, SQLiteCalendarEventService
from .memory_context import MemoryRetriever
from .persona import Persona
from .reminders import Reminder, SQLiteReminderService
from .tasks import SQLiteTaskService, Task


ProactiveOutcome = Literal["sent", "suppressed"]


class ProactiveChatValidationError(ValueError):
    """Raised when Proactive Chat settings are invalid."""


@dataclass(frozen=True, slots=True)
class ProactiveChatSettings:
    enabled: bool
    quiet_hours_start: str
    quiet_hours_end: str
    cooldown_seconds: int
    daily_limit: int


@dataclass(frozen=True, slots=True)
class ProactiveChatDelivery:
    evaluation_id: str
    conversation_id: str
    content: str
    occurred_at: float


@dataclass(frozen=True, slots=True)
class ProactiveChatResult:
    evaluation_id: str
    conversation_id: str
    outcome: ProactiveOutcome
    reason: str
    occurred_at: float
    content: str | None = None


@dataclass(frozen=True, slots=True)
class ProactiveChatAudit:
    evaluation_id: str
    conversation_id: str
    outcome: ProactiveOutcome
    reason: str
    occurred_at: float
    memory_count: int = 0
    life_record_count: int = 0


@dataclass(frozen=True, slots=True)
class _EvaluationContext:
    recent_messages: tuple[ChatContent, ...]
    memories: tuple[str, ...]
    tasks: tuple[Task, ...]
    reminders: tuple[Reminder, ...]
    calendar_events: tuple[CalendarEvent, ...]

    @property
    def life_record_count(self) -> int:
        return len(self.tasks) + len(self.reminders) + len(self.calendar_events)


class SQLiteProactiveChatStore:
    """Persist scheduler settings, interaction state, limits, and deduplication."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._database_path = Path(database_path)
        self._clock = clock
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def settings(self) -> ProactiveChatSettings:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT enabled, quiet_hours_start, quiet_hours_end,
                       cooldown_seconds, daily_limit
                FROM proactive_chat_settings WHERE installation_id = 1
                """
            ).fetchone()
        if row is None:
            raise RuntimeError("Proactive Chat settings are not initialized")
        return ProactiveChatSettings(
            enabled=bool(row[0]),
            quiet_hours_start=str(row[1]),
            quiet_hours_end=str(row[2]),
            cooldown_seconds=int(row[3]),
            daily_limit=int(row[4]),
        )

    def update_settings(
        self,
        *,
        enabled: bool,
        quiet_hours_start: str,
        quiet_hours_end: str,
        cooldown_seconds: int,
        daily_limit: int,
    ) -> ProactiveChatSettings:
        start = _quiet_time(quiet_hours_start, "quiet_hours_start")
        end = _quiet_time(quiet_hours_end, "quiet_hours_end")
        if cooldown_seconds < 0:
            raise ProactiveChatValidationError("cooldown_seconds must be non-negative")
        if daily_limit < 0:
            raise ProactiveChatValidationError("daily_limit must be non-negative")
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE proactive_chat_settings
                SET enabled = ?, quiet_hours_start = ?, quiet_hours_end = ?,
                    cooldown_seconds = ?, daily_limit = ?, updated_at = ?
                WHERE installation_id = 1
                """,
                (
                    int(enabled), start, end, cooldown_seconds, daily_limit,
                    self._clock(),
                ),
            )
        return self.settings()

    def record_user_interaction(self, conversation_id: str, occurred_at: float) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO proactive_chat_interactions(conversation_id, occurred_at)
                VALUES (?, ?)
                ON CONFLICT(conversation_id) DO UPDATE
                SET occurred_at = MAX(occurred_at, excluded.occurred_at)
                """,
                (conversation_id, occurred_at),
            )

    def last_user_interaction(self, conversation_id: str) -> float | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT occurred_at FROM proactive_chat_interactions "
                "WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return None if row is None else float(row[0])

    def sent_count(self, local_date: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) FROM proactive_chat_evaluations
                WHERE local_date = ? AND outcome = 'sent'
                """,
                (local_date,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def last_sent_at(self, conversation_id: str) -> float | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT MAX(evaluated_at) FROM proactive_chat_evaluations
                WHERE conversation_id = ? AND outcome = 'sent'
                """,
                (conversation_id,),
            ).fetchone()
        return None if row is None or row[0] is None else float(row[0])

    def reserve(
        self,
        *,
        evaluation_id: str,
        evaluation_key: str,
        conversation_id: str,
        evaluated_at: float,
        local_date: str,
    ) -> bool:
        with self._connect() as connection:
            inserted = connection.execute(
                """
                INSERT OR IGNORE INTO proactive_chat_evaluations(
                    evaluation_id, evaluation_key, conversation_id, evaluated_at,
                    local_date, outcome, reason
                ) VALUES (?, ?, ?, ?, ?, 'evaluating', 'pending')
                """,
                (
                    evaluation_id, evaluation_key, conversation_id, evaluated_at,
                    local_date,
                ),
            )
        return inserted.rowcount == 1

    def finish(
        self,
        evaluation_id: str,
        *,
        outcome: ProactiveOutcome,
        reason: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE proactive_chat_evaluations SET outcome = ?, reason = ?
                WHERE evaluation_id = ?
                """,
                (outcome, reason, evaluation_id),
            )

    def _initialize(self) -> None:
        now = self._clock()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS proactive_chat_settings (
                    installation_id INTEGER PRIMARY KEY CHECK (installation_id = 1),
                    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
                    quiet_hours_start TEXT NOT NULL,
                    quiet_hours_end TEXT NOT NULL,
                    cooldown_seconds INTEGER NOT NULL CHECK (cooldown_seconds >= 0),
                    daily_limit INTEGER NOT NULL CHECK (daily_limit >= 0),
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proactive_chat_interactions (
                    conversation_id TEXT PRIMARY KEY,
                    occurred_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proactive_chat_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    evaluation_key TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL,
                    evaluated_at REAL NOT NULL,
                    local_date TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK (
                        outcome IN ('evaluating', 'sent', 'suppressed')
                    ),
                    reason TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS proactive_chat_evaluations_by_day
                    ON proactive_chat_evaluations(local_date, outcome);
                CREATE INDEX IF NOT EXISTS proactive_chat_evaluations_by_conversation
                    ON proactive_chat_evaluations(conversation_id, evaluated_at);
                """
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO proactive_chat_settings(
                    installation_id, enabled, quiet_hours_start, quiet_hours_end,
                    cooldown_seconds, daily_limit, updated_at
                ) VALUES (1, 0, '22:00', '08:00', 21600, 2, ?)
                """,
                (now,),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path, timeout=5.0)


class ProactiveChatCoordinator:
    """Decide and deliver one bounded Proactive Chat evaluation."""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        store: SQLiteProactiveChatStore,
        persona_provider: Callable[[], Persona],
        memory_retriever: MemoryRetriever,
        tasks: SQLiteTaskService,
        reminders: SQLiteReminderService,
        calendar_events: SQLiteCalendarEventService,
        recent_messages: Callable[[str], tuple[ChatContent, ...]],
        deliver: Callable[[ProactiveChatDelivery], Awaitable[None]],
        audit: Callable[[ProactiveChatAudit], None],
        installation_timezone: str,
        clock: Callable[[], float] = time.time,
        minimum_idle_seconds: int = 300,
        upcoming_horizon_seconds: int = 86400,
        evaluation_interval_seconds: int = 1800,
        message_character_limit: int = 500,
        id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        try:
            self._timezone = ZoneInfo(installation_timezone)
        except ZoneInfoNotFoundError as error:
            raise ProactiveChatValidationError(
                f"unknown installation timezone: {installation_timezone}"
            ) from error
        if minimum_idle_seconds < 0 or upcoming_horizon_seconds <= 0:
            raise ProactiveChatValidationError("scheduler bounds are invalid")
        if evaluation_interval_seconds <= 0 or message_character_limit <= 0:
            raise ProactiveChatValidationError("evaluation bounds are invalid")
        self._provider = provider
        self._store = store
        self._persona_provider = persona_provider
        self._memory_retriever = memory_retriever
        self._tasks = tasks
        self._reminders = reminders
        self._calendar_events = calendar_events
        self._recent_messages = recent_messages
        self._deliver = deliver
        self._audit = audit
        self._clock = clock
        self._minimum_idle_seconds = minimum_idle_seconds
        self._upcoming_horizon_seconds = upcoming_horizon_seconds
        self._evaluation_interval_seconds = evaluation_interval_seconds
        self._message_character_limit = message_character_limit
        self._id_factory = id_factory

    async def evaluate(self, conversation_id: str = "main") -> ProactiveChatResult:
        now = self._clock()
        local_now = datetime.fromtimestamp(now, self._timezone)
        settings = self._store.settings()
        evaluation_id = self._id_factory()
        if not settings.enabled:
            return self._suppressed(
                evaluation_id, conversation_id, now, "disabled", audit=True
            )
        evaluation_key = (
            f"{conversation_id}:{int(now // self._evaluation_interval_seconds)}"
        )
        if not self._store.reserve(
            evaluation_id=evaluation_id,
            evaluation_key=evaluation_key,
            conversation_id=conversation_id,
            evaluated_at=now,
            local_date=local_now.date().isoformat(),
        ):
            return ProactiveChatResult(
                evaluation_id=evaluation_id,
                conversation_id=conversation_id,
                outcome="suppressed",
                reason="already_evaluated",
                occurred_at=now,
            )
        if _is_quiet(local_now, settings):
            return self._suppressed(
                evaluation_id, conversation_id, now, "quiet_hours"
            )
        last_interaction = self._store.last_user_interaction(conversation_id)
        if (
            last_interaction is not None
            and now - last_interaction < self._minimum_idle_seconds
        ):
            return self._suppressed(
                evaluation_id, conversation_id, now, "recent_interaction"
            )
        if self._store.sent_count(local_now.date().isoformat()) >= settings.daily_limit:
            return self._suppressed(
                evaluation_id, conversation_id, now, "daily_limit"
            )
        last_sent = self._store.last_sent_at(conversation_id)
        if last_sent is not None and now - last_sent < settings.cooldown_seconds:
            return self._suppressed(evaluation_id, conversation_id, now, "cooldown")

        context = self._context(conversation_id, now)
        try:
            reply = await self._provider.complete(
                ProviderRequest(
                    messages=(
                        ChatContent(role="user", content=_render_context(context)),
                    ),
                    tools=(),
                    skills=(),
                    system_instructions=_proactive_instructions(
                        self._persona_provider(), self._message_character_limit
                    ),
                )
            )
        except ProviderFailure:
            return self._suppressed(
                evaluation_id,
                conversation_id,
                now,
                "provider_failed",
                context=context,
            )
        decision = _parse_decision(reply.content, self._message_character_limit)
        if decision is None:
            return self._suppressed(
                evaluation_id,
                conversation_id,
                now,
                "invalid_decision",
                context=context,
            )
        send, content = decision
        if not send:
            return self._suppressed(
                evaluation_id,
                conversation_id,
                now,
                "model_suppressed",
                context=context,
            )
        assert content is not None
        # Persist the sent outcome before external delivery. A restart can lose this
        # message, but cannot duplicate it or evade the cooldown/daily limit.
        self._store.finish(evaluation_id, outcome="sent", reason="model_sent")
        await self._deliver(
            ProactiveChatDelivery(
                evaluation_id=evaluation_id,
                conversation_id=conversation_id,
                content=content,
                occurred_at=now,
            )
        )
        result = ProactiveChatResult(
            evaluation_id=evaluation_id,
            conversation_id=conversation_id,
            outcome="sent",
            reason="model_sent",
            occurred_at=now,
            content=content,
        )
        self._audit_result(result, context)
        return result

    def _context(self, conversation_id: str, now: float) -> _EvaluationContext:
        horizon = now + self._upcoming_horizon_seconds
        recent = self._recent_messages(conversation_id)[-6:]
        tasks = tuple(
            task
            for task in self._tasks.list()
            if not task.completed
            and task.deadline is not None
            and _in_window(task.deadline, now, horizon, self._timezone)
        )[:5]
        reminders = tuple(
            reminder
            for reminder in self._reminders.list()
            if reminder.delivery_state == "scheduled"
            and _in_window(reminder.due_at, now, horizon, self._timezone)
        )[:5]
        calendar_events = tuple(
            event
            for event in self._calendar_events.list()
            if _in_window(event.start_at, now, horizon, self._timezone)
        )[:5]
        query_parts = [message.content for message in recent if message.role == "user"]
        query_parts.extend(task.title for task in tasks)
        query_parts.extend(reminder.message for reminder in reminders)
        query_parts.extend(event.title for event in calendar_events)
        memories = tuple(
            memory.content
            for memory in self._memory_retriever.relevant(" ".join(query_parts))
        )
        return _EvaluationContext(
            recent_messages=recent,
            memories=memories,
            tasks=tasks,
            reminders=reminders,
            calendar_events=calendar_events,
        )

    def _suppressed(
        self,
        evaluation_id: str,
        conversation_id: str,
        occurred_at: float,
        reason: str,
        *,
        audit: bool = False,
        context: _EvaluationContext | None = None,
    ) -> ProactiveChatResult:
        if reason != "disabled":
            self._store.finish(
                evaluation_id, outcome="suppressed", reason=reason
            )
        result = ProactiveChatResult(
            evaluation_id=evaluation_id,
            conversation_id=conversation_id,
            outcome="suppressed",
            reason=reason,
            occurred_at=occurred_at,
        )
        if audit or reason != "already_evaluated":
            self._audit_result(result, context)
        return result

    def _audit_result(
        self,
        result: ProactiveChatResult,
        context: _EvaluationContext | None,
    ) -> None:
        self._audit(
            ProactiveChatAudit(
                evaluation_id=result.evaluation_id,
                conversation_id=result.conversation_id,
                outcome=result.outcome,
                reason=result.reason,
                occurred_at=result.occurred_at,
                memory_count=0 if context is None else len(context.memories),
                life_record_count=0 if context is None else context.life_record_count,
            )
        )


def _quiet_time(value: str, field: str) -> str:
    try:
        parsed = datetime.strptime(value.strip(), "%H:%M")
    except ValueError as error:
        raise ProactiveChatValidationError(f"{field} must use HH:MM") from error
    return parsed.strftime("%H:%M")


def _is_quiet(now: datetime, settings: ProactiveChatSettings) -> bool:
    start = datetime.strptime(settings.quiet_hours_start, "%H:%M").time()
    end = datetime.strptime(settings.quiet_hours_end, "%H:%M").time()
    current = now.time().replace(second=0, microsecond=0)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def _in_window(value: str, start: float, end: float, timezone: ZoneInfo) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    timestamp = parsed.timestamp()
    return start <= timestamp <= end


def _proactive_instructions(persona: Persona, character_limit: int) -> str:
    return (
        f"{persona.chat_instructions()}\n\n"
        "You are performing one read-only Proactive Chat evaluation. Decide only "
        "whether to send one short message and what that Chat Content says. You have "
        "no tools and must not request, create, update, or delete any stored record. "
        "Use only relevant supplied context and do not expose storage metadata. "
        "Return JSON only: {\"send\": false} or "
        "{\"send\": true, \"content\": \"message\"}. "
        f"Sent content must be at most {character_limit} characters."
    )


def _render_context(context: _EvaluationContext) -> str:
    sections = ["Recent Conversation:"]
    sections.extend(
        f"- {message.role}: {message.content}" for message in context.recent_messages
    )
    sections.append("Relevant Memory:")
    sections.extend(f"- {value}" for value in context.memories)
    sections.append("Upcoming Tasks:")
    sections.extend(f"- {task.title} | {task.deadline}" for task in context.tasks)
    sections.append("Upcoming Reminders:")
    sections.extend(
        f"- {reminder.message} | {reminder.due_at}"
        for reminder in context.reminders
    )
    sections.append("Upcoming Calendar Events:")
    sections.extend(
        f"- {event.title} | {event.start_at}" for event in context.calendar_events
    )
    return "\n".join(sections)


def _parse_decision(
    value: str, character_limit: int
) -> tuple[bool, str | None] | None:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("send"), bool):
        return None
    if payload["send"] is False:
        return False, None
    content = payload.get("content")
    if not isinstance(content, str):
        return None
    normalized = content.strip()
    if not normalized or len(normalized) > character_limit:
        return None
    return True, normalized


__all__ = [
    "ProactiveChatAudit",
    "ProactiveChatCoordinator",
    "ProactiveChatDelivery",
    "ProactiveChatResult",
    "ProactiveChatSettings",
    "ProactiveChatValidationError",
    "SQLiteProactiveChatStore",
]
