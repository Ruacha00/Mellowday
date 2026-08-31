"""Product-neutral values exchanged through the Agent Core facade."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .confirmations import PendingConfirmation


ChatRole = Literal["user", "assistant"]
StopReason = Literal[
    "final",
    "clarification",
    "confirmation_pending",
    "confirmation_accepted",
    "confirmation_rejected",
    "step_limit",
    "tool_call_limit",
    "provider_error",
]
EventType = Literal[
    "turn_started",
    "provider_started",
    "provider_completed",
    "provider_failed",
    "action_decided",
    "confirmation_pending",
    "confirmation_accepted",
    "confirmation_rejected",
    "tool_execution_started",
    "tool_execution_completed",
    "tool_execution_failed",
    "skill_load_started",
    "skill_loaded",
    "skill_load_failed",
    "skill_enablement_changed",
    "turn_limit_reached",
    "turn_completed",
    "conversation_history_initialized",
    "conversation_history_loaded",
    "conversation_history_appended",
    "conversation_history_listed",
    "conversation_history_read",
    "conversation_history_reset",
    "conversation_history_failed",
    "application_action_completed",
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
    user_id: str = "local-user"
    granted_permissions: tuple[str, ...] = ("*",)


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    sequence: int
    type: EventType
    occurred_at: float
    conversation_id: str | None
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnResult:
    chat_content: ChatContent
    stop_reason: StopReason
    events: tuple[RuntimeEvent, ...]
    confirmation: PendingConfirmation | None = None
