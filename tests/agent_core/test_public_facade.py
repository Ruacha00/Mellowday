import asyncio

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    ConfirmationDecision,
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
