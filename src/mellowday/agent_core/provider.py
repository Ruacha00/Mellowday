"""Vendor-neutral model Provider contract and deterministic local fake."""

from dataclasses import dataclass
from typing import Literal, Protocol

from .extensions import (
    LoadedSkill,
    SkillMetadata,
    ToolCall,
    ToolExecutionResult,
    ToolMetadata,
)
from .types import ChatContent


ProviderStopReason = Literal[
    "completed", "tool_calls", "length", "content_filter", "unknown"
]
ProviderFailureCode = Literal[
    "authentication",
    "rate_limited",
    "timeout",
    "unavailable",
    "request_rejected",
    "invalid_response",
    "not_configured",
]


class ProviderFailure(Exception):
    """Safe normalized Provider failure without adapter or transport details."""

    def __init__(
        self,
        code: ProviderFailureCode,
        *,
        retryable: bool,
        attempts: int,
    ) -> None:
        super().__init__(f"Provider call failed: {code}")
        self.code = code
        self.retryable = retryable
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class ProviderReply:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    selected_skills: tuple[str, ...] = ()
    usage: ProviderUsage | None = None
    stop_reason: ProviderStopReason = "completed"
    retries: int = 0


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    messages: tuple[ChatContent, ...]
    tools: tuple[ToolMetadata, ...] = ()
    tool_results: tuple[ToolExecutionResult, ...] = ()
    skills: tuple[SkillMetadata, ...] = ()
    loaded_skills: tuple[LoadedSkill, ...] = ()
    system_instructions: str = ""


class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        """Return one normalized reply for the supplied Agent Core request."""


class FakeProvider:
    """Deterministic Provider used by local development and automated tests."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[ChatContent, ...]] = []
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        messages = request.messages
        self.calls.append(messages)
        latest_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        return ProviderReply(content=f"I heard: {latest_user}")
