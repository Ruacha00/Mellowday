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
        self._pending_skill_calls: list[tuple[str, str]] = []

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        payload: dict[str, object] = {
            "model": self._config.model,
            "messages": self._messages(request),
        }
        tools = self._tools(request)
        if tools:
            payload["tools"] = tools
        response, retries = await self._request_with_retries(
            "POST", "chat/completions", payload=payload
        )
        try:
            return replace(self._normalize(response.payload), retries=retries)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise ProviderFailure(
                "invalid_response",
                retryable=False,
                attempts=retries + 1,
            ) from None

    async def validate(self) -> None:
        response, retries = await self._request_with_retries(
            "GET", "models", payload=None
        )
        models = response.payload.get("data")
        if isinstance(models, list) and any(
            isinstance(model, dict) and model.get("id") == self._config.model
            for model in models
        ):
            return
        raise ProviderFailure(
            "invalid_response",
            retryable=False,
            attempts=retries + 1,
        )

    async def _request_with_retries(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None,
    ) -> tuple[ProviderTransportResponse, int]:
        for attempt in range(self._config.max_retries + 1):
            try:
                response = await self._transport.request(
                    method,
                    f"{self._config.base_url.rstrip('/')}/{path}",
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
                    return response, attempt
                failure = response_failure
            if not failure.retryable or attempt >= self._config.max_retries:
                raise failure
            await self._retry_delay(0.5 * (attempt + 1))
        raise AssertionError("Provider retry loop did not return or raise")

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

    def _messages(self, request: ProviderRequest) -> list[dict[str, object]]:
        messages: list[dict[str, object]] = []
        system_sections = [request.system_instructions]
        system_sections.extend(
            f"Loaded Skill {skill.name}:\n{skill.instructions}"
            for skill in request.loaded_skills
        )
        system_content = "\n\n".join(
            section for section in system_sections if section.strip()
        )
        if system_content:
            messages.append({"role": "system", "content": system_content})
        messages.extend(
            {"role": message.role, "content": message.content}
            for message in request.messages
        )
        if self._pending_skill_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "mellowday_load_skill",
                                "arguments": json.dumps(
                                    {"name": name}, ensure_ascii=False
                                ),
                            },
                        }
                        for call_id, name in self._pending_skill_calls
                    ],
                }
            )
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(
                        {"ok": True, "loaded_skill": name}, ensure_ascii=False
                    ),
                }
                for call_id, name in self._pending_skill_calls
            )
            self._pending_skill_calls.clear()
        if request.assistant_tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    dict(call.arguments or {}), ensure_ascii=False
                                ),
                            },
                        }
                        for call in request.assistant_tool_calls
                    ],
                }
            )
        messages.extend(
            {
                "role": "tool",
                "tool_call_id": result.call_id,
                "content": json.dumps(
                    {
                        "ok": result.ok,
                        "result": result.result,
                        "error": result.error,
                        "detail": result.detail,
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            }
            for result in request.tool_results
        )
        return messages

    @staticmethod
    def _tools(request: ProviderRequest) -> list[dict[str, object]]:
        definitions: list[dict[str, object]] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in request.tools
        ]
        if request.skills:
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": "mellowday_load_skill",
                        "description": "Load one available Skill before answering.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "name": {
                                    "type": "string",
                                    "enum": [skill.name for skill in request.skills],
                                    "description": "; ".join(
                                        f"{skill.name}: {skill.description}"
                                        for skill in request.skills
                                    ),
                                }
                            },
                            "required": ["name"],
                        },
                    },
                }
            )
        return definitions

    def _normalize(self, payload: dict[str, object]) -> ProviderReply:
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
        selected_skills: list[str] = []
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
                name = str(function.get("name", ""))
                if name == "mellowday_load_skill" and isinstance(parsed, dict):
                    selected = parsed.get("name")
                    if isinstance(selected, str):
                        selected_skills.append(selected)
                        self._pending_skill_calls.append(
                            (str(raw_call.get("id", "")), selected)
                        )
                    continue
                tool_calls.append(
                    ToolCall(
                        id=str(raw_call.get("id", "")),
                        name=name,
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
            selected_skills=tuple(selected_skills),
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
