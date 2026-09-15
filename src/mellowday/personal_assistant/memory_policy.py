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
            or _is_transient_or_joke(evidence, content)
            or _is_optout_or_other_speaker(evidence)
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
            or _is_transient_or_joke(evidence, content)
            or _is_optout_or_other_speaker(evidence)
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
    return re.search(
        r"我(?:一直|平时|通常|一向|长期)?(?:喜欢|偏好|习惯|常用|使用|用|不喜欢)",
        evidence,
    ) is not None or any(
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


def _is_transient_or_joke(evidence: str, content: str) -> bool:
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
    if any(marker in evidence for marker in ("开玩笑", "说笑", "哈哈")):
        return True
    claim = _normalized_claim(content)
    clauses = re.split(r"[，,。！？!?;；\n]", evidence)
    matching = [clause for clause in clauses if claim.rstrip() in _normalized_claim(clause)]
    temporal_scope = " ".join(matching) if matching else evidence
    if any(marker in temporal_scope for marker in ("今天", "今晚", "明天", "昨天", "目前", "暂时", "这周")):
        return True
    return re.search(
        r"\b(?:i am|i m|i feel|feeling)\s+"
        r"(?:sad|happy|angry|tired|upset|stressed|anxious|excited|lonely|bored)\b",
        normalized,
    ) is not None


def _is_optout_or_other_speaker(evidence: str) -> bool:
    """Do not interpret refusal or somebody else's first-person quote as consent."""
    normalized = _normalized_claim(evidence)
    return (
        re.search(r"\b(?:do not|don t|never)\s+(?:remember|save|store)\b", normalized) is not None
        or re.search(r"(?:不要|别|不必|不用|无需)(?:帮我)?(?:记|保存|存储)", evidence) is not None
        or re.search(r"(?:我(?:的)?(?:朋友|同事|家人)|他|她)(?:说|表示)[：:，,]", evidence) is not None
        or re.search(r"\b(?:said|says|told me)\s*[:：]", evidence.casefold()) is not None
    )


__all__ = ["MemoryLearningPolicy"]
