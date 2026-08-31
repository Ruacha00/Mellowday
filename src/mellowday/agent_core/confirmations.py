"""Bound, expiring, one-time Explicit Confirmation records."""

import secrets
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from .extensions import LoadedSkill, ToolExecutionResult
from .types import ChatContent


ConfirmationStatus = Literal["pending", "accepted", "rejected", "expired"]
ConfirmationDecisionValue = Literal["accept", "reject"]
ConfirmationErrorCode = Literal[
    "not_found", "already_decided", "binding_mismatch", "expired"
]


class ConfirmationError(Exception):
    def __init__(self, code: ConfirmationErrorCode) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class ConfirmationBinding:
    user_id: str
    conversation_id: str
    tool: str
    arguments: dict[str, object]
    initiating_context: tuple[ChatContent, ...]


@dataclass(frozen=True, slots=True)
class PendingConfirmation:
    id: str
    binding: ConfirmationBinding
    created_at: float
    expires_at: float


@dataclass(frozen=True, slots=True)
class ConfirmationDecision:
    confirmation_id: str
    binding: ConfirmationBinding
    decision: ConfirmationDecisionValue

    def __post_init__(self) -> None:
        if self.decision not in {"accept", "reject"}:
            raise ValueError(f"invalid confirmation decision: {self.decision!r}")


@dataclass(frozen=True, slots=True)
class ConfirmationResolution:
    pending: PendingConfirmation
    call_id: str
    granted_permissions: tuple[str, ...]
    prior_tool_results: tuple[ToolExecutionResult, ...]
    loaded_skills: tuple[LoadedSkill, ...]
    decision: ConfirmationDecisionValue


@dataclass(slots=True)
class _StoredConfirmation:
    pending: PendingConfirmation
    call_id: str
    granted_permissions: tuple[str, ...]
    prior_tool_results: tuple[ToolExecutionResult, ...]
    loaded_skills: tuple[LoadedSkill, ...]
    status: ConfirmationStatus = "pending"


class ConfirmationStore:
    def __init__(self, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            raise ValueError("confirmation_ttl_seconds must be positive")
        self._ttl_seconds = float(ttl_seconds)
        self._records: dict[str, _StoredConfirmation] = {}
        self._lock = Lock()

    def create(
        self,
        *,
        binding: ConfirmationBinding,
        call_id: str,
        granted_permissions: tuple[str, ...],
        prior_tool_results: tuple[ToolExecutionResult, ...],
        loaded_skills: tuple[LoadedSkill, ...],
        now: float,
    ) -> PendingConfirmation:
        safe_binding = self._copy_binding(binding)
        pending = PendingConfirmation(
            id=secrets.token_urlsafe(24),
            binding=safe_binding,
            created_at=now,
            expires_at=now + self._ttl_seconds,
        )
        with self._lock:
            self._records[pending.id] = _StoredConfirmation(
                pending=pending,
                call_id=call_id,
                granted_permissions=granted_permissions,
                prior_tool_results=deepcopy(prior_tool_results),
                loaded_skills=loaded_skills,
            )
        return self._copy_pending(pending)

    def pending(self, *, now: float) -> tuple[PendingConfirmation, ...]:
        with self._lock:
            for record in self._records.values():
                if record.status == "pending" and now >= record.pending.expires_at:
                    record.status = "expired"
            return tuple(
                self._copy_pending(record.pending)
                for record in self._records.values()
                if record.status == "pending"
            )

    def decide(
        self, decision: ConfirmationDecision, *, now: float
    ) -> ConfirmationResolution:
        with self._lock:
            record = self._records.get(decision.confirmation_id)
            if record is None:
                raise ConfirmationError("not_found")
            if record.status != "pending":
                raise ConfirmationError("already_decided")
            if decision.binding != record.pending.binding:
                raise ConfirmationError("binding_mismatch")
            if now >= record.pending.expires_at:
                record.status = "expired"
                raise ConfirmationError("expired")
            record.status = "accepted" if decision.decision == "accept" else "rejected"
            return ConfirmationResolution(
                pending=self._copy_pending(record.pending),
                call_id=record.call_id,
                granted_permissions=record.granted_permissions,
                prior_tool_results=deepcopy(record.prior_tool_results),
                loaded_skills=record.loaded_skills,
                decision=decision.decision,
            )

    @staticmethod
    def _copy_pending(pending: PendingConfirmation) -> PendingConfirmation:
        return PendingConfirmation(
            id=pending.id,
            binding=ConfirmationStore._copy_binding(pending.binding),
            created_at=pending.created_at,
            expires_at=pending.expires_at,
        )

    @staticmethod
    def _copy_binding(binding: ConfirmationBinding) -> ConfirmationBinding:
        return ConfirmationBinding(
            user_id=binding.user_id,
            conversation_id=binding.conversation_id,
            tool=binding.tool,
            arguments=deepcopy(binding.arguments),
            initiating_context=binding.initiating_context,
        )


__all__ = [
    "ConfirmationBinding",
    "ConfirmationDecision",
    "ConfirmationDecisionValue",
    "ConfirmationError",
    "ConfirmationErrorCode",
    "PendingConfirmation",
]
