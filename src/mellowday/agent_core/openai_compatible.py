"""OpenAI-compatible transport adapter for the vendor-neutral Provider contract."""

from __future__ import annotations

import json
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Protocol

from .extensions import ToolCall
from .provider import (
    ProviderFailure,
    ProviderFailureCode,
    ProviderReply,
    ProviderRequest,
    ProviderStopReason,
    ProviderUsage,
)


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    name: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float = 60
    max_retries: int = 2


@dataclass(frozen=True, slots=True)
class ProviderTransportResponse:
    status_code: int
    payload: dict[str, object]


class ProviderTransport(Protocol):
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object] | None,
        timeout: float,
    ) -> ProviderTransportResponse: ...


class HttpxProviderTransport:
    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object] | None,
        timeout: float,
    ) -> ProviderTransportResponse:
        import httpx

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, url, headers=headers, json=json)
        except httpx.TimeoutException as error:
            raise ProviderTransportError(timeout=True) from error
        except httpx.HTTPError as error:
            raise ProviderTransportError(timeout=False) from error
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return ProviderTransportResponse(
            status_code=response.status_code,
            payload=payload if isinstance(payload, dict) else {},
        )


class ProviderTransportError(Exception):
    def __init__(self, *, timeout: bool, detail: str = "") -> None:
        super().__init__(detail)
        self.timeout = timeout


class OpenAICompatibleProvider:
    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: ProviderTransport,
        retry_delay: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.name = config.name
        self._config = config
        self._transport = transport
        self._retry_delay = retry_delay

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        payload: dict[str, object] = {
            "model": self._config.model,
            "messages": self._messages(request),
        }
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await self._transport.request(
                    "POST",
                    f"{self._config.base_url.rstrip('/')}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._config.timeout_seconds,
                )
            except ProviderTransportError as error:
                failure = ProviderFailure(
                    "timeout" if error.timeout else "unavailable",
                    retryable=True,
                    attempts=attempt + 1,
                )
            else:
                response_failure = self._response_failure(
                    response, attempts=attempt + 1
                )
                if response_failure is None:
                    try:
                        return replace(self._normalize(response.payload), retries=attempt)
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                        raise ProviderFailure(
                            "invalid_response",
                            retryable=False,
                            attempts=attempt + 1,
                        ) from None
                failure = response_failure
            if not failure.retryable or attempt >= self._config.max_retries:
                raise failure
            await self._retry_delay(0.5 * (attempt + 1))
        raise AssertionError("Provider retry loop did not return or raise")

    async def validate(self) -> None:
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await self._transport.request(
                    "GET",
                    f"{self._config.base_url.rstrip('/')}/models",
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=None,
                    timeout=self._config.timeout_seconds,
                )
            except ProviderTransportError as error:
                failure = ProviderFailure(
                    "timeout" if error.timeout else "unavailable",
                    retryable=True,
                    attempts=attempt + 1,
                )
            else:
                response_failure = self._response_failure(
                    response, attempts=attempt + 1
                )
                if response_failure is None:
                    return
                failure = response_failure
            if not failure.retryable or attempt >= self._config.max_retries:
                raise failure
            await self._retry_delay(0.5 * (attempt + 1))

    @staticmethod
    def _response_failure(
        response: ProviderTransportResponse, *, attempts: int
    ) -> ProviderFailure | None:
        status = response.status_code
        if 200 <= status < 300:
            return None
        if status in {401, 403}:
            code: ProviderFailureCode = "authentication"
            retryable = False
        elif status == 429:
            code = "rate_limited"
            retryable = True
        elif status in {408, 504}:
            code = "timeout"
            retryable = True
        elif status >= 500:
            code = "unavailable"
            retryable = True
        else:
            code = "request_rejected"
            retryable = False
        return ProviderFailure(code, retryable=retryable, attempts=attempts)

    @staticmethod
    def _messages(request: ProviderRequest) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        if request.system_instructions:
            messages.append(
                {"role": "system", "content": request.system_instructions}
            )
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in request.messages
        )
        return messages

    @staticmethod
    def _normalize(payload: dict[str, object]) -> ProviderReply:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Provider response has no choices")
        choice = choices[0]
        if not isinstance(choice, dict):
            raise ValueError("Provider response choice is invalid")
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ValueError("Provider response message is invalid")
        message_data = message
        raw_calls = message_data.get("tool_calls")
        tool_calls: list[ToolCall] = []
        if isinstance(raw_calls, list):
            for raw_call in raw_calls:
                if not isinstance(raw_call, dict):
                    continue
                function = raw_call.get("function")
                if not isinstance(function, dict):
                    continue
                arguments = function.get("arguments", "{}")
                try:
                    parsed = json.loads(arguments) if isinstance(arguments, str) else None
                except json.JSONDecodeError:
                    parsed = None
                tool_calls.append(
                    ToolCall(
                        id=str(raw_call.get("id", "")),
                        name=str(function.get("name", "")),
                        arguments=parsed if isinstance(parsed, dict) else None,
                    )
                )
        usage_data = payload.get("usage")
        usage = None
        if isinstance(usage_data, dict):
            input_tokens = int(usage_data.get("prompt_tokens", 0))
            output_tokens = int(usage_data.get("completion_tokens", 0))
            usage = ProviderUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=int(
                    usage_data.get("total_tokens", input_tokens + output_tokens)
                ),
            )
        stop_reasons: dict[str, ProviderStopReason] = {
            "stop": "completed",
            "tool_calls": "tool_calls",
            "length": "length",
            "content_filter": "content_filter",
        }
        return ProviderReply(
            content=str(message_data.get("content") or ""),
            tool_calls=tuple(tool_calls),
            usage=usage,
            stop_reason=stop_reasons.get(
                str(choice.get("finish_reason", "")), "unknown"
            ),
        )


__all__ = [
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "HttpxProviderTransport",
    "ProviderFailure",
    "ProviderTransport",
    "ProviderTransportError",
    "ProviderTransportResponse",
]
