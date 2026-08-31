"""Vendor-neutral model Provider contract and deterministic local fake."""

from dataclasses import dataclass
from typing import Protocol

from .extensions import (
    LoadedSkill,
    SkillMetadata,
    ToolCall,
    ToolExecutionResult,
    ToolMetadata,
)
from .types import ChatContent


@dataclass(frozen=True, slots=True)
class ProviderReply:
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    selected_skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    messages: tuple[ChatContent, ...]
    tools: tuple[ToolMetadata, ...] = ()
    tool_results: tuple[ToolExecutionResult, ...] = ()
    skills: tuple[SkillMetadata, ...] = ()
    loaded_skills: tuple[LoadedSkill, ...] = ()
    system_instructions: str = ""


class ModelProvider(Protocol):
    name: str

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
