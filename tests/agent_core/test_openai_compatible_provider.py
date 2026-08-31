import asyncio

from mellowday.agent_core import ChatContent, ProviderRequest
from mellowday.agent_core.openai_compatible import (
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    ProviderFailure,
    ProviderTransportError,
    ProviderTransportResponse,
)


class RecordedTransport:
    def __init__(
        self,
        responses: tuple[ProviderTransportResponse | Exception, ...],
    ) -> None:
        self.responses = iter(responses)
        self.requests: list[dict[str, object]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object] | None,
        timeout: float,
    ) -> ProviderTransportResponse:
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_openai_compatible_reply_is_normalized_at_the_adapter_boundary() -> None:
    transport = RecordedTransport(
        (
            ProviderTransportResponse(
                status_code=200,
                payload={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "content": "",
                                "tool_calls": [
                                    {
                                        "id": "call-1",
                                        "function": {
                                            "name": "save_note",
                                            "arguments": '{"content":"Buy tea"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 4,
                        "total_tokens": 16,
                    },
                },
            ),
        )
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            name="Local model",
            base_url="http://localhost:9000/v1",
            model="chat-model",
            api_key="local-secret",
            timeout_seconds=7,
            max_retries=0,
        ),
        transport=transport,
    )

    reply = asyncio.run(
        provider.complete(
            ProviderRequest(
                messages=(ChatContent(role="user", content="Save a tea note"),)
            )
        )
    )

    assert reply.stop_reason == "tool_calls"
    assert reply.usage is not None
    assert reply.usage.input_tokens == 12
    assert reply.usage.output_tokens == 4
    assert reply.usage.total_tokens == 16
    assert reply.retries == 0
    assert reply.tool_calls[0].name == "save_note"
    assert reply.tool_calls[0].arguments == {"content": "Buy tea"}
    assert transport.requests == [
        {
            "method": "POST",
            "url": "http://localhost:9000/v1/chat/completions",
            "headers": {
                "Authorization": "Bearer local-secret",
                "Content-Type": "application/json",
            },
            "json": {
                "model": "chat-model",
                "messages": [{"role": "user", "content": "Save a tea note"}],
            },
            "timeout": 7,
        }
    ]


def test_retryable_responses_are_retried_and_counted() -> None:
    transport = RecordedTransport(
        (
            ProviderTransportResponse(status_code=503, payload={}),
            ProviderTransportResponse(
                status_code=200,
                payload={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": "Recovered"},
                        }
                    ]
                },
            ),
        )
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            name="Local model",
            base_url="http://localhost:9000/v1",
            model="chat-model",
            api_key="local-secret",
            max_retries=1,
        ),
        transport=transport,
        retry_delay=lambda _seconds: asyncio.sleep(0),
    )

    reply = asyncio.run(
        provider.complete(
            ProviderRequest(
                messages=(ChatContent(role="user", content="Hello"),)
            )
        )
    )

    assert reply.content == "Recovered"
    assert reply.retries == 1
    assert len(transport.requests) == 2


def test_transport_timeout_is_normalized_without_leaking_transport_details() -> None:
    secret = "never-return-this-secret"
    transport = RecordedTransport(
        (
            ProviderTransportError(timeout=True, detail=f"request used {secret}"),
            ProviderTransportError(timeout=True, detail=f"request used {secret}"),
        )
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            name="Local model",
            base_url="http://localhost:9000/v1",
            model="chat-model",
            api_key=secret,
            max_retries=1,
        ),
        transport=transport,
        retry_delay=lambda _seconds: asyncio.sleep(0),
    )

    try:
        asyncio.run(
            provider.complete(
                ProviderRequest(
                    messages=(ChatContent(role="user", content="Hello"),)
                )
            )
        )
    except ProviderFailure as error:
        assert error.code == "timeout"
        assert error.retryable is True
        assert error.attempts == 2
        assert secret not in str(error)
    else:
        raise AssertionError("ProviderFailure was not raised")


def test_malformed_success_payload_is_normalized_as_invalid_response() -> None:
    transport = RecordedTransport(
        (ProviderTransportResponse(status_code=200, payload={"choices": []}),)
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            name="Local model",
            base_url="http://localhost:9000/v1",
            model="chat-model",
            api_key="local-secret",
            max_retries=0,
        ),
        transport=transport,
    )

    try:
        asyncio.run(
            provider.complete(
                ProviderRequest(
                    messages=(ChatContent(role="user", content="Hello"),)
                )
            )
        )
    except ProviderFailure as error:
        assert error.code == "invalid_response"
        assert error.retryable is False
        assert error.attempts == 1
    else:
        raise AssertionError("ProviderFailure was not raised")
