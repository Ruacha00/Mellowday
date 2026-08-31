import asyncio
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    ConfirmationBinding,
    ConfirmationDecision,
    ConfirmationError,
    FakeProvider,
    ProviderReply,
    ProviderRequest,
    Skill,
    Tool,
    ToolCall,
    ToolClarificationRequired,
    ToolOutcome,
    TurnRequest,
    UndoMetadata,
)


class ScriptedProvider:
    name = "scripted"

    def __init__(self, replies: Sequence[ProviderReply]) -> None:
        self._replies = iter(replies)
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        return next(self._replies)


def test_clear_reversible_action_runs_without_confirmation() -> None:
    executions: list[dict[str, object]] = []

    async def save_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"note_id": "note-1", "conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="save_note",
                        arguments={"content": "Buy tea"},
                    ),
                )
            ),
            ProviderReply(content="I saved your tea note."),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="save_note",
                description="Save a note for later.",
                input_schema={
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                    "additionalProperties": False,
                },
                executor=save_note,
                permission_requirements=("notes:write",),
                side_effect="reversible",
                risk="medium",
            ),
        ),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(
                    ChatContent(role="user", content="Save a note to buy tea."),
                ),
            )
        )
    )

    assert executions == [{"content": "Buy tea"}]
    assert result.stop_reason == "final"
    assert result.chat_content.content == "I saved your tea note."
    assert [
        event.details["decision"]
        for event in result.events
        if event.type == "action_decided"
    ] == ["allow"]
    assert core.list_pending_confirmations() == ()


def test_ambiguous_action_returns_natural_clarification_without_execution() -> None:
    executions: list[dict[str, object]] = []

    async def update_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall(
                        id="call-ambiguous",
                        name="update_note",
                        arguments={"content": "Buy coffee"},
                        intent_clarity="ambiguous",
                    ),
                ),
            ),
            ProviderReply(content="Which note would you like me to update?"),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="update_note",
                description="Update one saved note.",
                input_schema={
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
                executor=update_note,
                side_effect="reversible",
                risk="low",
            ),
        ),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Change that note."),),
            )
        )
    )

    assert executions == []
    assert result.stop_reason == "clarification"
    assert result.chat_content.content == "Which note would you like me to update?"
    assert provider.requests[1].tool_results[0].error == "ambiguous_intent"
    assert [event.type for event in result.events].count("action_decided") == 1
    assert "tool_execution_started" not in [event.type for event in result.events]
    assert core.list_pending_confirmations() == ()


def test_tool_can_request_clarification_after_validating_domain_arguments() -> None:
    async def schedule_event(
        _arguments: dict[str, object], _conversation_id: str
    ) -> object:
        raise ToolClarificationRequired(
            "start_at is ambiguous; include a UTC offset"
        )

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall(
                        "ambiguous-time",
                        "schedule_event",
                        {"start_at": "2026-11-01T01:30"},
                    ),
                )
            ),
            ProviderReply(content="Which UTC offset should I use?"),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="schedule_event",
                description="Schedule an event at an unambiguous time.",
                input_schema={
                    "type": "object",
                    "properties": {"start_at": {"type": "string"}},
                    "required": ["start_at"],
                },
                executor=schedule_event,
                side_effect="reversible",
            ),
        ),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Schedule it at 1:30."),),
            )
        )
    )

    clarification = provider.requests[1].tool_results[0]
    assert clarification.error == "ambiguous_intent"
    assert clarification.detail == "start_at is ambiguous; include a UTC offset"
    assert result.stop_reason == "clarification"
    assert result.chat_content.content == "Which UTC offset should I use?"


def test_ambiguous_action_prevents_partial_execution_of_same_tool_batch() -> None:
    executions: list[str] = []

    async def execute(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(str(arguments["value"]))
        return {"conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall("call-clear", "change_note", {"value": "first"}),
                    ToolCall(
                        "call-ambiguous",
                        "change_note",
                        {"value": "second"},
                        intent_clarity="ambiguous",
                    ),
                )
            ),
            ProviderReply(content="Which change did you want me to make?"),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="change_note",
                description="Change one note.",
                input_schema={"type": "object", "properties": {}},
                executor=execute,
                side_effect="reversible",
            ),
        ),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Change those."),),
            )
        )
    )

    assert executions == []
    assert result.stop_reason == "clarification"
    assert result.chat_content.content == "Which change did you want me to make?"


def test_high_risk_action_creates_bound_pending_confirmation() -> None:
    executions: list[dict[str, object]] = []

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                content="That will permanently erase the note. Would you like me to continue?",
                tool_calls=(
                    ToolCall(
                        id="call-delete",
                        name="erase_note",
                        arguments={"note_id": "note-1"},
                    ),
                ),
            ),
        )
    )
    now = [100.0]
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={
                    "type": "object",
                    "properties": {"note_id": {"type": "string"}},
                    "required": ["note_id"],
                    "additionalProperties": False,
                },
                executor=erase_note,
                permission_requirements=("notes:delete",),
                side_effect="irreversible",
                risk="high",
            ),
        ),
        confirmation_ttl_seconds=60,
        clock=lambda: now[0],
    )
    initiating_context = (
        ChatContent(role="user", content="Erase note one forever."),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                messages=initiating_context,
            )
        )
    )

    assert executions == []
    assert result.stop_reason == "confirmation_pending"
    assert result.chat_content.content.startswith("That will permanently erase")
    assert result.confirmation is not None
    assert result.confirmation.binding.user_id == "user-1"
    assert result.confirmation.binding.conversation_id == "conversation-1"
    assert result.confirmation.binding.tool == "erase_note"
    assert result.confirmation.binding.arguments == {"note_id": "note-1"}
    assert result.confirmation.binding.initiating_context == initiating_context
    assert result.confirmation.expires_at == 160.0
    assert core.list_pending_confirmations() == (result.confirmation,)
    assert [
        event.details["decision"]
        for event in result.events
        if event.type == "action_decided"
    ] == ["confirm"]


def test_missing_permission_denies_action_and_provider_reports_naturally() -> None:
    executions: list[dict[str, object]] = []

    async def change_provider(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall(
                        id="call-denied",
                        name="change_provider",
                        arguments={"provider": "local"},
                    ),
                )
            ),
            ProviderReply(content="I can’t change that setting from this context."),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="change_provider",
                description="Change the configured model Provider.",
                input_schema={
                    "type": "object",
                    "properties": {"provider": {"type": "string"}},
                    "required": ["provider"],
                },
                executor=change_provider,
                permission_requirements=("providers:write",),
                side_effect="reversible",
                risk="medium",
            ),
        ),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Switch providers."),),
                granted_permissions=("notes:write",),
            )
        )
    )

    assert executions == []
    assert result.stop_reason == "final"
    assert result.chat_content.content == (
        "I can’t change that setting from this context."
    )
    assert provider.requests[1].tool_results[0].error == "permission_denied"
    assert [
        event.details["decision"]
        for event in result.events
        if event.type == "action_decided"
    ] == ["deny"]


def test_accepting_confirmation_executes_once_and_reports_outcome_naturally() -> None:
    executions: list[dict[str, object]] = []

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"erased": arguments["note_id"], "conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                content="This permanently erases the note. Should I continue?",
                tool_calls=(
                    ToolCall("call-delete", "erase_note", {"note_id": "note-1"}),
                ),
            ),
            ProviderReply(content="The note is gone."),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={
                    "type": "object",
                    "properties": {"note_id": {"type": "string"}},
                    "required": ["note_id"],
                },
                executor=erase_note,
                side_effect="irreversible",
                risk="high",
            ),
        ),
    )
    request = TurnRequest(
        user_id="user-1",
        conversation_id="conversation-1",
        messages=(ChatContent(role="user", content="Erase note one."),),
    )
    pending_turn = asyncio.run(core.run_turn(request))
    pending = pending_turn.confirmation
    assert pending is not None

    decision = ConfirmationDecision(
        confirmation_id=pending.id,
        binding=pending.binding,
        decision="accept",
    )
    result = asyncio.run(core.decide_confirmation(decision))

    assert executions == [{"note_id": "note-1"}]
    assert result.stop_reason == "confirmation_accepted"
    assert result.chat_content.content == "The note is gone."
    assert provider.requests[1].tool_results[0].ok is True
    assert provider.requests[1].tool_results[0].result == {
        "erased": "note-1",
        "conversation_id": "conversation-1",
    }
    assert core.list_pending_confirmations() == ()
    with pytest.raises(ConfirmationError) as replayed:
        asyncio.run(core.decide_confirmation(decision))
    assert replayed.value.code == "already_decided"
    assert executions == [{"note_id": "note-1"}]


def test_confirmation_resume_preserves_prior_tool_and_skill_context() -> None:
    async def inspect_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        return {"found": arguments["note_id"], "conversation_id": conversation_id}

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        return {"erased": arguments["note_id"], "conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall("call-inspect", "inspect_note", {"note_id": "note-1"}),
                ),
                selected_skills=("careful_actions",),
            ),
            ProviderReply(
                content="This permanently erases the note. Continue?",
                tool_calls=(
                    ToolCall("call-delete", "erase_note", {"note_id": "note-1"}),
                ),
            ),
            ProviderReply(content="The note is gone."),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="inspect_note",
                description="Inspect one note.",
                input_schema={"type": "object", "properties": {}},
                executor=inspect_note,
            ),
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={"type": "object", "properties": {}},
                executor=erase_note,
                side_effect="irreversible",
            ),
        ),
        skills=(
            Skill(
                name="careful_actions",
                description="Keep consequential action explanations clear.",
                instruction_loader=lambda: "Explain consequential actions carefully.",
            ),
        ),
    )
    pending_turn = asyncio.run(
        core.run_turn(
            TurnRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Erase note one."),),
            )
        )
    )
    pending = pending_turn.confirmation
    assert pending is not None

    asyncio.run(
        core.decide_confirmation(
            ConfirmationDecision(
                confirmation_id=pending.id,
                binding=pending.binding,
                decision="accept",
            )
        )
    )

    resumed_request = provider.requests[2]
    assert [result.name for result in resumed_request.tool_results] == [
        "inspect_note",
        "erase_note",
    ]
    assert [skill.name for skill in resumed_request.loaded_skills] == [
        "careful_actions"
    ]
    assert resumed_request.messages == (
        ChatContent(role="user", content="Erase note one."),
    )


@pytest.mark.parametrize(
    ("field", "mismatched_value"),
    (
        ("user_id", "user-2"),
        ("conversation_id", "conversation-2"),
        ("tool", "other_tool"),
        ("arguments", {"note_id": "note-2"}),
        (
            "initiating_context",
            (ChatContent(role="user", content="Erase a different note."),),
        ),
    ),
)
def test_mismatched_confirmation_binding_fails_without_consuming_pending_action(
    field: str, mismatched_value: object
) -> None:
    executions: list[dict[str, object]] = []

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                content="Should I erase it permanently?",
                tool_calls=(ToolCall("call-1", "erase_note", {"note_id": "note-1"}),),
            ),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={
                    "type": "object",
                    "properties": {"note_id": {"type": "string"}},
                    "required": ["note_id"],
                },
                executor=erase_note,
                side_effect="irreversible",
            ),
        ),
    )
    pending_turn = asyncio.run(
        core.run_turn(
            TurnRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Erase note one."),),
            )
        )
    )
    pending = pending_turn.confirmation
    assert pending is not None
    mismatched_binding = replace(
        pending.binding, **{field: mismatched_value}
    )

    with pytest.raises(ConfirmationError) as raised:
        asyncio.run(
            core.decide_confirmation(
                ConfirmationDecision(
                    confirmation_id=pending.id,
                    binding=mismatched_binding,
                    decision="accept",
                )
            )
        )

    assert raised.value.code == "binding_mismatch"
    assert executions == []
    assert core.list_pending_confirmations() == (pending,)


def test_expired_confirmation_cannot_execute() -> None:
    executions: list[dict[str, object]] = []

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    now = [100.0]
    provider = ScriptedProvider(
        (
            ProviderReply(
                content="Should I erase it permanently?",
                tool_calls=(ToolCall("call-1", "erase_note", {"note_id": "note-1"}),),
            ),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={"type": "object", "properties": {}},
                executor=erase_note,
                side_effect="irreversible",
            ),
        ),
        confirmation_ttl_seconds=10,
        clock=lambda: now[0],
    )
    pending_turn = asyncio.run(
        core.run_turn(
            TurnRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Erase note one."),),
            )
        )
    )
    pending = pending_turn.confirmation
    assert pending is not None
    now[0] = pending.expires_at

    with pytest.raises(ConfirmationError) as raised:
        asyncio.run(
            core.decide_confirmation(
                ConfirmationDecision(
                    confirmation_id=pending.id,
                    binding=pending.binding,
                    decision="accept",
                )
            )
        )

    assert raised.value.code == "expired"
    assert executions == []
    assert core.list_pending_confirmations() == ()


def test_public_pending_confirmation_cannot_mutate_stored_binding() -> None:
    executions: list[dict[str, object]] = []

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                content="Should I erase it permanently?",
                tool_calls=(ToolCall("call-1", "erase_note", {"note_id": "note-1"}),),
            ),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={"type": "object", "properties": {}},
                executor=erase_note,
                side_effect="irreversible",
            ),
        ),
    )
    pending_turn = asyncio.run(
        core.run_turn(
            TurnRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Erase note one."),),
            )
        )
    )
    public_pending = pending_turn.confirmation
    assert public_pending is not None
    public_pending.binding.arguments["note_id"] = "note-2"

    stored_pending = core.list_pending_confirmations()[0]
    assert stored_pending.binding.arguments == {"note_id": "note-1"}
    with pytest.raises(ConfirmationError) as raised:
        asyncio.run(
            core.decide_confirmation(
                ConfirmationDecision(
                    confirmation_id=public_pending.id,
                    binding=public_pending.binding,
                    decision="accept",
                )
            )
        )
    assert raised.value.code == "binding_mismatch"
    assert executions == []


def test_invalid_confirmation_decision_cannot_consume_pending_action() -> None:
    binding = ConfirmationBinding(
        user_id="user-1",
        conversation_id="conversation-1",
        tool="erase_note",
        arguments={"note_id": "note-1"},
        initiating_context=(ChatContent(role="user", content="Erase note one."),),
    )

    with pytest.raises(ValueError, match="confirmation decision"):
        ConfirmationDecision(
            confirmation_id="confirmation-1",
            binding=binding,
            decision="later",  # type: ignore[arg-type]
        )


def test_rejecting_confirmation_never_executes_and_reports_naturally() -> None:
    executions: list[dict[str, object]] = []

    async def erase_note(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    provider = ScriptedProvider(
        (
            ProviderReply(
                content="Should I erase it permanently?",
                tool_calls=(ToolCall("call-1", "erase_note", {"note_id": "note-1"}),),
            ),
            ProviderReply(content="Okay, I left the note where it was."),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="erase_note",
                description="Permanently erase one note.",
                input_schema={"type": "object", "properties": {}},
                executor=erase_note,
                side_effect="irreversible",
            ),
        ),
    )
    pending_turn = asyncio.run(
        core.run_turn(
            TurnRequest(
                user_id="user-1",
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Erase note one."),),
            )
        )
    )
    pending = pending_turn.confirmation
    assert pending is not None

    decision = ConfirmationDecision(
        confirmation_id=pending.id,
        binding=pending.binding,
        decision="reject",
    )
    result = asyncio.run(core.decide_confirmation(decision))

    assert executions == []
    assert result.stop_reason == "confirmation_rejected"
    assert result.chat_content.content == "Okay, I left the note where it was."
    assert provider.requests[1].tool_results[0].error == "user_rejected"
    assert core.list_pending_confirmations() == ()
    with pytest.raises(ConfirmationError) as replayed:
        asyncio.run(core.decide_confirmation(decision))
    assert replayed.value.code == "already_decided"
    assert executions == []


def test_audit_history_exposes_available_undo_metadata() -> None:
    async def save_note(
        arguments: dict[str, object], conversation_id: str
    ) -> ToolOutcome:
        assert conversation_id == "conversation-1"
        return ToolOutcome(
            value={"note_id": "note-1"},
            undo=UndoMetadata(
                tool="delete_note",
                arguments={"note_id": "note-1"},
            ),
        )

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall("call-save", "save_note", {"content": "Buy tea"}),
                )
            ),
            ProviderReply(content="I saved the note."),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="save_note",
                description="Save one note.",
                input_schema={
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
                executor=save_note,
                side_effect="reversible",
            ),
        ),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Save a tea note."),),
            )
        )
    )

    tool_result = provider.requests[1].tool_results[0]
    assert tool_result.result == {"note_id": "note-1"}
    assert tool_result.undo == UndoMetadata(
        tool="delete_note", arguments={"note_id": "note-1"}
    )
    assert result.chat_content.content == "I saved the note."
    audit = core.list_audit_events()
    assert audit == result.events
    completed = next(
        event for event in audit if event.type == "tool_execution_completed"
    )
    assert completed.details["undo"] == {
        "tool": "delete_note",
        "arguments": {"note_id": "note-1"},
    }
    completed.details["undo"] = {"tool": "tampered", "arguments": {}}
    stored_completed = next(
        event
        for event in core.list_audit_events()
        if event.type == "tool_execution_completed"
    )
    assert stored_completed.details["undo"] == {
        "tool": "delete_note",
        "arguments": {"note_id": "note-1"},
    }


def test_audit_history_persists_locally_across_agent_core_restart(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "audit-events.jsonl"
    first = AgentCore(provider=FakeProvider(), audit_path=audit_path)
    asyncio.run(
        first.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Hello."),),
            )
        )
    )
    first_history = first.list_audit_events()

    restarted = AgentCore(provider=FakeProvider(), audit_path=audit_path)
    assert restarted.list_audit_events() == first_history
    result = asyncio.run(
        restarted.run_turn(
            TurnRequest(
                conversation_id="conversation-2",
                messages=(ChatContent(role="user", content="Hello again."),),
            )
        )
    )

    assert result.events[0].sequence == first_history[-1].sequence + 1
    assert restarted.list_audit_events() == first_history + result.events
