"""Deterministic permission decisions for Tool-backed actions."""

from dataclasses import dataclass
from typing import Literal

from .extensions import ToolMetadata


IntentClarity = Literal["clear", "ambiguous"]
PermissionDecision = Literal["allow", "clarify", "confirm", "deny"]


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    user_id: str
    conversation_id: str
    granted_permissions: tuple[str, ...] = ("*",)
    intent_clarity: IntentClarity = "clear"


class PermissionEngine:
    """Evaluate Tool metadata without consulting Persona or chat copy."""

    def decide(
        self, metadata: ToolMetadata, context: ExecutionContext
    ) -> PermissionDecision:
        granted = frozenset(context.granted_permissions)
        if "*" not in granted and not set(metadata.permission_requirements) <= granted:
            return "deny"
        if context.intent_clarity == "ambiguous":
            return "clarify"
        if metadata.side_effect == "irreversible" or metadata.risk == "high":
            return "confirm"
        return "allow"


__all__ = [
    "ExecutionContext",
    "IntentClarity",
    "PermissionDecision",
    "PermissionEngine",
]
