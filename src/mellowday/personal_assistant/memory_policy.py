"""Conservative policy for creating Memory from Chat Content."""

import re
from typing import Literal

from .memories import Memory, MemoryKind, SQLiteMemoryService


class MemoryLearningPolicy:
    """Ground explicit and automatic Memory writes in durable User evidence."""

    def __init__(self, service: SQLiteMemoryService) -> None:
        self._service = service

    def remember_explicit(
        self,
        *,
        content: str,
        kind: MemoryKind,
        evidence: str,
        source_conversation_id: str,
    ) -> Memory | None:
        if (
            not _claim_is_supported(content, evidence)
            or _is_transient_or_joke(evidence)
            or not _has_explicit_memory_intent(evidence)
        ):
            return None
        return self._service.remember(
            content=content,
            kind=kind,
            provenance="explicit",
            source_conversation_id=source_conversation_id,
        )

    def remember_automatic(
        self,
        *,
        content: str,
        kind: Literal["preference", "fact"],
        evidence: str,
        source_conversation_id: str,
    ) -> Memory | None:
        if (
            not _claim_is_supported(content, evidence)
            or _is_transient_or_joke(evidence)
            or not _has_stable_fact_or_preference_cue(evidence)
        ):
            return None
        return self._service.remember(
            content=content,
            kind=kind,
            provenance="automatic",
            source_conversation_id=source_conversation_id,
        )


def _normalized_claim(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


def _claim_is_supported(content: str, evidence: str) -> bool:
    normalized_content = _normalized_claim(content)
    normalized_evidence = _normalized_claim(evidence)
    return bool(normalized_content and normalized_content in normalized_evidence)


def _has_explicit_memory_intent(evidence: str) -> bool:
    normalized = _normalized_claim(evidence)
    return any(
        cue in normalized
        for cue in (
            "remember",
            "do not forget",
            "don t forget",
            "save this as memory",
            "记住",
            "记得",
            "记下来",
        )
    )


def _has_stable_fact_or_preference_cue(evidence: str) -> bool:
    padded = f" {_normalized_claim(evidence)} "
    return any(
        cue in padded
        for cue in (
            " i prefer ",
            " i like ",
            " i love ",
            " i dislike ",
            " i hate ",
            " i don t ",
            " i do not ",
            " i use ",
            " i work ",
            " i live ",
            " i speak ",
            " my name ",
            " my birthday ",
            " my timezone ",
            " my pronouns ",
            " my job ",
        )
    )


def _is_transient_or_joke(evidence: str) -> bool:
    normalized = _normalized_claim(evidence)
    padded = f" {normalized} "
    transient_or_joke_markers = (
        " just kidding ",
        " kidding ",
        " joking ",
        " not really ",
        " sarcasm ",
        " haha ",
        " lol ",
        " today ",
        " tonight ",
        " tomorrow ",
        " yesterday ",
        " right now ",
        " at the moment ",
        " currently ",
        " for now ",
        " temporarily ",
        " this morning ",
        " this evening ",
        " this week ",
        " lately ",
    )
    if any(marker in padded for marker in transient_or_joke_markers):
        return True
    return re.search(
        r"\b(?:i am|i m|i feel|feeling)\s+"
        r"(?:sad|happy|angry|tired|upset|stressed|anxious|excited|lonely|bored)\b",
        normalized,
    ) is not None


__all__ = ["MemoryLearningPolicy"]
