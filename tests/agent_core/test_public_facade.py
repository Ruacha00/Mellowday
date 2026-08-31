import asyncio

from mellowday.agent_core import AgentCore, ChatContent, FakeProvider, TurnRequest
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


def test_provider_failure_returns_truthful_chat_and_safe_diagnostics() -> None:
    class FailingProvider:
        name = "configured-provider"

        async def complete(self, _request: object) -> object:
            raise ProviderFailure(
                "authentication", retryable=False, attempts=1
            )

    core = AgentCore(provider=FailingProvider())

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
        content=(
            "I couldn't reach the configured model Provider, so I can't "
            "answer that reliably right now. Please check Settings and try again."
        ),
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
