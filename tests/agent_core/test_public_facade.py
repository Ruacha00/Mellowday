import asyncio

import pytest

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    ConfirmationDecision,
    ConfirmationError,
    FakeProvider,
    ProviderReply,
    ProviderRequest,
    Tool,
    ToolCall,
    TurnRequest,
)
from mellowday.agent_core.openai_compatible import ProviderFailure


def test_public_facade_returns_normalized_chat_content_and_lifecycle_events() -> None:
    provider = FakeProvider()
    times = iter((10.0, 11.0, 12.0, 13.0))
    core = AgentCore(provider=provider, clock=lambda: next(times))

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="  Hello, Mellowday.  "),),
            )
        )
    )

    assert result.chat_content == ChatContent(
        role="assistant", content="I heard: Hello, Mellowday."
    )
    assert result.stop_reason == "final"
    assert provider.calls == [
        (ChatContent(role="user", content="Hello, Mellowday."),)
    ]
    assert [event.type for event in result.events] == [
        "turn_started",
        "provider_started",
        "provider_completed",
        "turn_completed",
    ]
    assert [event.sequence for event in result.events] == [1, 2, 3, 4]
    assert [event.occurred_at for event in result.events] == [10.0, 11.0, 12.0, 13.0]
    assert all(event.conversation_id == "conversation-1" for event in result.events)
    assert result.events[-1].details == {"stop_reason": "final"}


def test_public_facade_records_product_neutral_application_actions() -> None:
    core = AgentCore(provider=FakeProvider(), clock=lambda: 42.0)

    event = core.record_application_action(
        action="created",
        resource_type="task",
        resource_id="task-1",
        conversation_id="conversation-1",
    )

    assert event.type == "application_action_completed"
    assert event.occurred_at == 42.0
    assert event.conversation_id == "conversation-1"
    assert event.details == {
        "action": "created",
        "resource_type": "task",
        "resource_id": "task-1",
    }
    assert core.list_audit_events() == (event,)


def test_public_facade_binds_one_time_application_action_confirmation() -> None:
    core = AgentCore(provider=FakeProvider(), clock=lambda: 42.0)
    pending, requested = core.request_application_confirmation(
        user_id="local-user",
        conversation_id="settings",
        action="task_delete",
        arguments={"task_id": "task-1"},
    )

    decision, decided = core.decide_application_confirmation(
        ConfirmationDecision(
            confirmation_id=pending.id,
            binding=pending.binding,
            decision="accept",
        )
    )

    assert decision == "accept"
    assert pending.binding.tool == "task_delete"
    assert pending.binding.arguments == {"task_id": "task-1"}
    assert requested.type == "confirmation_pending"
    assert decided.type == "confirmation_accepted"
    with pytest.raises(ConfirmationError, match="already_decided"):
        core.decide_application_confirmation(
            ConfirmationDecision(
                confirmation_id=pending.id,
                binding=pending.binding,
                decision="accept",
            )
        )


def test_provider_failure_returns_truthful_chat_and_safe_diagnostics() -> None:
    class FailingProvider:
        name = "configured-provider"

        async def complete(self, _request: object) -> object:
            raise ProviderFailure(
                "authentication", retryable=False, attempts=1
            )

    core = AgentCore(
        provider=FailingProvider(),
        provider_failure_content_provider=(
            lambda _error: "The configured Provider credentials were rejected."
        ),
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Hello"),),
            )
        )
    )

    assert result.stop_reason == "provider_error"
    assert result.chat_content == ChatContent(
        role="assistant",
        content="The configured Provider credentials were rejected.",
    )
    assert [event.type for event in result.events] == [
        "turn_started",
        "provider_started",
        "provider_failed",
        "turn_completed",
    ]
    assert result.events[2].details == {
        "provider": "configured-provider",
        "code": "authentication",
        "retryable": False,
        "attempts": 1,
    }


def test_provider_failure_after_confirmation_is_normalized() -> None:
    class ConfirmationThenFailureProvider:
        name = "configured-provider"

        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, _request: ProviderRequest) -> ProviderReply:
            self.calls += 1
            if self.calls == 1:
                return ProviderReply(
                    content="Delete it?",
                    tool_calls=(ToolCall("call-1", "delete_note", {}),),
                )
            raise ProviderFailure("timeout", retryable=True, attempts=3)

    async def delete_note(
        _arguments: dict[str, object], _conversation_id: str
    ) -> dict[str, bool]:
        return {"deleted": True}

    provider = ConfirmationThenFailureProvider()
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="delete_note",
                description="Delete a note permanently.",
                input_schema={"type": "object", "properties": {}},
                executor=delete_note,
                side_effect="irreversible",
                risk="high",
            ),
        ),
        provider_failure_content_provider=lambda _error: "The Provider timed out.",
    )

    pending_turn = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Delete it"),),
            )
        )
    )
    assert pending_turn.confirmation is not None
    resumed = asyncio.run(
        core.decide_confirmation(
            ConfirmationDecision(
                confirmation_id=pending_turn.confirmation.id,
                binding=pending_turn.confirmation.binding,
                decision="accept",
            )
        )
    )

    assert resumed.stop_reason == "provider_error"
    assert resumed.chat_content.content == "The Provider timed out."
    assert resumed.events[-2].type == "provider_failed"
    assert resumed.events[-2].details["code"] == "timeout"


def test_agent_core_rejects_tool_evidence_not_grounded_in_user_messages() -> None:
    executions: list[dict[str, object]] = []

    async def learn(
        arguments: dict[str, object], _conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"saved": True}

    class EvidenceProvider:
        name = "evidence-script"

        def __init__(self) -> None:
            self.replies = iter(
                (
                    ProviderReply(
                        tool_calls=(
                            ToolCall(
                                "invented-evidence",
                                "learn_fact",
                                {
                                    "content": "I prefer tea.",
                                    "evidence": "I prefer tea.",
                                },
                            ),
                        )
                    ),
                    ProviderReply(
                        content="I did not save an unsupported fact."
                    ),
                )
            )

        async def complete(self, _request: ProviderRequest) -> ProviderReply:
            return next(self.replies)

    provider = EvidenceProvider()
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="learn_fact",
                description="Save a directly supported User fact.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["content", "evidence"],
                },
                executor=learn,
                user_evidence_argument="evidence",
            ),
        ),
        audit_path=None,
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="main",
                messages=(
                    ChatContent(role="user", content="The cafe closes at nine."),
                ),
            )
        )
    )

    assert result.chat_content.content == "I did not save an unsupported fact."
    assert executions == []
    failures = [
        event for event in result.events if event.type == "tool_execution_failed"
    ]
    assert failures[-1].details["error"] == "ungrounded_evidence"
