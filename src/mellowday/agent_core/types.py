"""Product-neutral values exchanged through the Agent Core facade."""

from dataclasses import dataclass, field
from typing import Literal


ChatRole = Literal["user", "assistant"]
StopReason = Literal["final"]
EventType = Literal[
    "turn_started",
    "provider_started",
    "provider_completed",
    "tool_execution_started",
    "tool_execution_completed",
    "tool_execution_failed",
    "skill_load_started",
    "skill_loaded",
    "skill_load_failed",
    "turn_completed",
]


@dataclass(frozen=True, slots=True)
class ChatContent:
    role: ChatRole
    content: str


@dataclass(frozen=True, slots=True)
class TurnRequest:
    conversation_id: str
    messages: tuple[ChatContent, ...]
    requested_skills: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    sequence: int
    type: EventType
    occurred_at: float
    conversation_id: str
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnResult:
    chat_content: ChatContent
    stop_reason: StopReason
    events: tuple[RuntimeEvent, ...]
