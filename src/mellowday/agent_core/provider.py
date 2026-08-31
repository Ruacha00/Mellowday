"""Vendor-neutral model Provider contract and deterministic local fake."""

from dataclasses import dataclass
from typing import Protocol

from .types import ChatContent


@dataclass(frozen=True, slots=True)
class ProviderReply:
    content: str


class ModelProvider(Protocol):
    name: str

    async def complete(self, messages: tuple[ChatContent, ...]) -> ProviderReply:
        """Return one normalized Provider reply for the supplied Chat Content."""


class FakeProvider:
    """Deterministic Provider used by local development and automated tests."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[ChatContent, ...]] = []

    async def complete(self, messages: tuple[ChatContent, ...]) -> ProviderReply:
        self.calls.append(messages)
        latest_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        return ProviderReply(content=f"I heard: {latest_user}")
