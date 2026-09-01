"""Deterministic coverage for bounded Proactive Chat."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mellowday.agent_core import ChatContent, ProviderReply, ProviderRequest
from mellowday.personal_assistant import (
    MemoryRetriever,
    Persona,
    ProactiveChatAudit,
    ProactiveChatCoordinator,
    ProactiveChatDelivery,
    ProactiveChatValidationError,
    SQLiteCalendarEventService,
    SQLiteMemoryService,
    SQLiteProactiveChatStore,
    SQLiteReminderService,
    SQLiteTaskService,
)


class ScriptedProvider:
    name = "scripted"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        return ProviderReply(content=self.replies.pop(0))


def _timestamp(hour: int = 12) -> float:
    return datetime(2026, 9, 1, hour, tzinfo=timezone.utc).timestamp()


def _build(
    path: Path,
    *,
    now: list[float],
    provider: ScriptedProvider,
    deliveries: list[ProactiveChatDelivery],
    audits: list[ProactiveChatAudit],
    recent: tuple[ChatContent, ...] = (),
) -> tuple[
    ProactiveChatCoordinator,
    SQLiteProactiveChatStore,
    SQLiteMemoryService,
    SQLiteTaskService,
    SQLiteReminderService,
    SQLiteCalendarEventService,
]:
    clock = lambda: now[0]
    store = SQLiteProactiveChatStore(path, clock=clock)
    memories = SQLiteMemoryService(path, clock=clock)
    tasks = SQLiteTaskService(path, clock=clock)
    reminders = SQLiteReminderService(path, clock=clock)
    calendar_events = SQLiteCalendarEventService(
        path, installation_timezone="UTC", clock=clock
    )

    async def deliver(delivery: ProactiveChatDelivery) -> None:
        deliveries.append(delivery)

    coordinator = ProactiveChatCoordinator(
        provider=provider,
        store=store,
        persona_provider=lambda: Persona(
            name="Luma",
            identity="a steady companion",
            character="kind",
            speaking_style="plain",
            relationship_framing="trusted",
            conversational_boundaries="truthful",
            proactive_chat_style="gentle and brief",
        ),
        memory_retriever=MemoryRetriever(memories),
        tasks=tasks,
        reminders=reminders,
        calendar_events=calendar_events,
        recent_messages=lambda _conversation_id: recent,
        deliver=deliver,
        audit=audits.append,
        installation_timezone="UTC",
        clock=clock,
        minimum_idle_seconds=300,
        evaluation_interval_seconds=60,
        id_factory=lambda: f"evaluation-{int(now[0])}",
    )
    return coordinator, store, memories, tasks, reminders, calendar_events


def _enable(
    store: SQLiteProactiveChatStore,
    *,
    quiet_start: str = "22:00",
    quiet_end: str = "08:00",
    cooldown: int = 3600,
    daily_limit: int = 2,
) -> None:
    store.update_settings(
        enabled=True,
        quiet_hours_start=quiet_start,
        quiet_hours_end=quiet_end,
        cooldown_seconds=cooldown,
        daily_limit=daily_limit,
    )


def test_settings_persist_and_validate_quiet_hours(tmp_path: Path) -> None:
    path = tmp_path / "mellowday.sqlite3"
    store = SQLiteProactiveChatStore(path)
    saved = store.update_settings(
        enabled=True,
        quiet_hours_start="23:15",
        quiet_hours_end="07:45",
        cooldown_seconds=900,
        daily_limit=3,
    )

    assert SQLiteProactiveChatStore(path).settings() == saved
    with pytest.raises(ProactiveChatValidationError, match="HH:MM"):
        store.update_settings(
            enabled=True,
            quiet_hours_start="25:00",
            quiet_hours_end="07:45",
            cooldown_seconds=900,
            daily_limit=3,
        )


def test_quiet_hours_and_recent_interaction_suppress_before_provider(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        quiet_now = [_timestamp(23)]
        quiet_provider = ScriptedProvider('{"send": true, "content": "hello"}')
        quiet_audits: list[ProactiveChatAudit] = []
        quiet, store, *_ = _build(
            tmp_path / "quiet.sqlite3",
            now=quiet_now,
            provider=quiet_provider,
            deliveries=[],
            audits=quiet_audits,
        )
        _enable(store)
        assert (await quiet.evaluate()).reason == "quiet_hours"
        assert quiet_provider.requests == []
        assert quiet_audits[-1].reason == "quiet_hours"

        recent_now = [_timestamp()]
        recent_provider = ScriptedProvider('{"send": true, "content": "hello"}')
        recent_audits: list[ProactiveChatAudit] = []
        recent, recent_store, *_ = _build(
            tmp_path / "recent.sqlite3",
            now=recent_now,
            provider=recent_provider,
            deliveries=[],
            audits=recent_audits,
        )
        _enable(recent_store, quiet_start="00:00", quiet_end="00:00")
        recent_store.record_user_interaction("main", recent_now[0] - 30)
        assert (await recent.evaluate()).reason == "recent_interaction"
        assert recent_provider.requests == []

    asyncio.run(exercise())


def test_provider_gets_relevant_context_persona_and_no_write_capability(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        now = [_timestamp()]
        provider = ScriptedProvider(
            '{"send": true, "content": "Tea before your afternoon plans?"}'
        )
        deliveries: list[ProactiveChatDelivery] = []
        audits: list[ProactiveChatAudit] = []
        coordinator, store, memories, tasks, reminders, events = _build(
            tmp_path / "context.sqlite3",
            now=now,
            provider=provider,
            deliveries=deliveries,
            audits=audits,
            recent=(ChatContent(role="user", content="I could use some tea"),),
        )
        _enable(store, quiet_start="00:00", quiet_end="00:00")
        memories.remember(
            content="The User prefers green tea",
            kind="preference",
            provenance="explicit",
        )
        tasks.create(title="Buy tea", deadline="2026-09-01T13:00:00+00:00")
        reminders.create(
            message="Take a tea break", due_at="2026-09-01T13:30:00+00:00"
        )
        events.create(title="Afternoon walk", start_at="2026-09-01T14:00:00+00:00")

        result = await coordinator.evaluate()

        assert result.outcome == "sent"
        assert [delivery.content for delivery in deliveries] == [result.content]
        request = provider.requests[0]
        assert request.tools == ()
        assert request.skills == ()
        assert "Assistant name: Luma" in request.system_instructions
        assert "Proactive-chat style: gentle and brief" in request.system_instructions
        context = request.messages[0].content
        assert "The User prefers green tea" in context
        assert "Buy tea" in context
        assert "Take a tea break" in context
        assert "Afternoon walk" in context
        assert audits == [
            ProactiveChatAudit(
                evaluation_id=result.evaluation_id,
                conversation_id="main",
                outcome="sent",
                reason="model_sent",
                occurred_at=now[0],
                memory_count=1,
                life_record_count=3,
            )
        ]
        assert not hasattr(audits[0], "content")

    asyncio.run(exercise())


def test_model_suppression_delivers_nothing_and_is_reasoned(tmp_path: Path) -> None:
    async def exercise() -> None:
        now = [_timestamp()]
        provider = ScriptedProvider('{"send": false}')
        deliveries: list[ProactiveChatDelivery] = []
        audits: list[ProactiveChatAudit] = []
        coordinator, store, *_ = _build(
            tmp_path / "suppressed.sqlite3",
            now=now,
            provider=provider,
            deliveries=deliveries,
            audits=audits,
        )
        _enable(store, quiet_start="00:00", quiet_end="00:00")

        result = await coordinator.evaluate()

        assert result.reason == "model_suppressed"
        assert deliveries == []
        assert audits[-1].reason == "model_suppressed"

    asyncio.run(exercise())


def test_restart_preserves_daily_limit_and_evaluation_deduplication(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        path = tmp_path / "restart.sqlite3"
        now = [_timestamp()]
        deliveries: list[ProactiveChatDelivery] = []
        audits: list[ProactiveChatAudit] = []
        first_provider = ScriptedProvider('{"send": true, "content": "One check-in"}')
        first, store, *_ = _build(
            path,
            now=now,
            provider=first_provider,
            deliveries=deliveries,
            audits=audits,
        )
        _enable(
            store,
            quiet_start="00:00",
            quiet_end="00:00",
            cooldown=0,
            daily_limit=1,
        )
        sent = await first.evaluate()
        duplicate = await first.evaluate()
        assert sent.outcome == "sent"
        assert duplicate.reason == "already_evaluated"

        now[0] += 120
        restarted_provider = ScriptedProvider(
            '{"send": true, "content": "Duplicate check-in"}'
        )
        restarted, restarted_store, *_ = _build(
            path,
            now=now,
            provider=restarted_provider,
            deliveries=deliveries,
            audits=audits,
        )
        assert restarted_store.settings().daily_limit == 1
        assert (await restarted.evaluate()).reason == "daily_limit"
        assert restarted_provider.requests == []
        assert [delivery.content for delivery in deliveries] == ["One check-in"]

    asyncio.run(exercise())


def test_cooldown_survives_a_new_coordinator(tmp_path: Path) -> None:
    async def exercise() -> None:
        path = tmp_path / "cooldown.sqlite3"
        now = [_timestamp()]
        first, store, *_ = _build(
            path,
            now=now,
            provider=ScriptedProvider('{"send": true, "content": "First"}'),
            deliveries=[],
            audits=[],
        )
        _enable(
            store,
            quiet_start="00:00",
            quiet_end="00:00",
            cooldown=3600,
            daily_limit=5,
        )
        assert (await first.evaluate()).outcome == "sent"

        now[0] += 120
        provider = ScriptedProvider('{"send": true, "content": "Second"}')
        restarted, *_ = _build(
            path,
            now=now,
            provider=provider,
            deliveries=[],
            audits=[],
        )
        assert (await restarted.evaluate()).reason == "cooldown"
        assert provider.requests == []

    asyncio.run(exercise())
