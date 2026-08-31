"""Product-neutral values exchanged through the Agent Core facade."""

from dataclasses import dataclass, field
from typing import Literal


ChatRole = Literal["user", "assistant"]
StopReason = Literal["final"]


@dataclass(frozen=True, slots=True)
class ChatContent:
    role: ChatRole
    content: str


@dataclass(frozen=True, slots=True)
class TurnRequest:
    conversation_id: str
    messages: tuple[ChatContent, ...]


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    sequence: int
    type: str
    occurred_at: float
    conversation_id: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnResult:
    chat_content: ChatContent
    stop_reason: StopReason
    events: tuple[RuntimeEvent, ...]

