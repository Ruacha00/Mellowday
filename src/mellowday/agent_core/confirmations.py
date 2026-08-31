"""Bound, expiring, one-time Explicit Confirmation records."""

import secrets
from copy import deepcopy
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from .types import ChatContent


ConfirmationStatus = Literal["pending", "accepted", "rejected", "expired"]
ConfirmationDecisionValue = Literal["accept", "reject"]


class ConfirmationError(Exception):
    def __init__(self, code: str) -> None:
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


@dataclass(frozen=True, slots=True)
class ConfirmationResolution:
    pending: PendingConfirmation
    call_id: str
    granted_permissions: tuple[str, ...]
    decision: ConfirmationDecisionValue


@dataclass(slots=True)
class _StoredConfirmation:
    pending: PendingConfirmation
    call_id: str
    granted_permissions: tuple[str, ...]
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
        now: float,
    ) -> PendingConfirmation:
        safe_binding = ConfirmationBinding(
            user_id=binding.user_id,
            conversation_id=binding.conversation_id,
            tool=binding.tool,
            arguments=deepcopy(binding.arguments),
            initiating_context=binding.initiating_context,
        )
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
                decision=decision.decision,
            )

    @staticmethod
    def _copy_pending(pending: PendingConfirmation) -> PendingConfirmation:
        return PendingConfirmation(
            id=pending.id,
            binding=ConfirmationBinding(
                user_id=pending.binding.user_id,
                conversation_id=pending.binding.conversation_id,
                tool=pending.binding.tool,
                arguments=deepcopy(pending.binding.arguments),
                initiating_context=pending.binding.initiating_context,
            ),
            created_at=pending.created_at,
            expires_at=pending.expires_at,
        )


__all__ = [
    "ConfirmationBinding",
    "ConfirmationDecision",
    "ConfirmationDecisionValue",
    "ConfirmationError",
    "PendingConfirmation",
]
