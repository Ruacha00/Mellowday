"""Relevant Memory retrieval and Personal Assistant context assembly."""

import re
from collections.abc import Callable

from mellowday.agent_core import ChatContent

from .memories import Memory, SQLiteMemoryService
from .persona import Persona


_GENERIC_TERMS = frozenset(
    {
        "about",
        "am",
        "and",
        "are",
        "can",
        "choose",
        "could",
        "did",
        "do",
        "does",
        "for",
        "how",
        "in",
        "is",
        "like",
        "my",
        "of",
        "on",
        "please",
        "prefer",
        "select",
        "should",
        "the",
        "to",
        "use",
        "want",
        "when",
        "where",
        "what",
        "which",
        "would",
        "work",
        "your",
        "喜欢", "偏好", "习惯", "我的", "我喜", "我不", "我平", "平时", "一直",
        "什么", "怎么", "如何", "应该", "帮我", "适合", "现在", "通常", "一个",
    }
)
_CONCEPTS = {
    "programming_language": frozenset(
        {
            "code",
            "coding",
            "go",
            "golang",
            "java",
            "javascript",
            "language",
            "programming",
            "python",
            "rust",
            "typescript",
            "代码", "编程", "语言", "开发",
        }
    ),
    "air_travel_seat": frozenset(
        {"aisle", "flight", "flying", "plane", "seat", "seats", "window",
         "飞机", "机舱", "座位", "选座", "靠窗", "过道"}
    ),
    "food": frozenset(
        {"allergy", "cilantro", "dinner", "eat", "food", "meal", "restaurant",
         "晚餐", "晚饭", "午餐", "早餐", "吃饭", "餐厅", "香菜", "花生", "饮食"}
    ),
    "coffee": frozenset({"coffee", "sugar", "咖啡", "无糖", "加糖", "甜度"}),
    "response_style": frozenset({"replies", "reply", "concise", "detailed", "回复", "回答", "篇幅", "简短", "详细"}),
}


class MemoryRetriever:
    """Return only confidently related Memory using local lexical concepts."""

    def __init__(self, service: SQLiteMemoryService) -> None:
        self._service = service

    def relevant(self, query: str, *, limit: int = 5) -> tuple[Memory, ...]:
        query_terms = _terms(query)
        if not query_terms:
            return ()
        query_concepts = _concepts(query_terms)
        scored: list[tuple[int, float, Memory]] = []
        for memory in self._service.list():
            memory_terms = _terms(memory.content)
            concept_matches = query_concepts & _concepts(memory_terms)
            specific_matches = query_terms & memory_terms
            score = len(concept_matches) * 3 + len(specific_matches)
            if score:
                scored.append((score, memory.updated_at, memory))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return tuple(item[2] for item in scored[:limit])


class AssistantContextAssembler:
    """Assemble Persona and relevant Memory for one conversation turn."""

    def __init__(
        self,
        persona_provider: Callable[[], Persona],
        memory_retriever: MemoryRetriever,
    ) -> None:
        self._persona_provider = persona_provider
        self._memory_retriever = memory_retriever

    def instructions(self, messages: tuple[ChatContent, ...]) -> str:
        sections = [self._persona_provider().chat_instructions()]
        latest_user_message = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        memories = self._memory_retriever.relevant(latest_user_message)
        if memories:
            rendered = "\n".join(f"- {memory.content}" for memory in memories)
            sections.append(
                "Relevant Memory about the User for this turn only:\n"
                f"{rendered}\n"
                "Use it only when it helps answer the current message. Do not expose "
                "Memory identifiers, provenance, or unrelated stored information."
            )
        return "\n\n".join(sections)


def _terms(value: str) -> frozenset[str]:
    # Han text has no spaces; whole-sentence tokens cannot match paraphrases.
    # Bigrams keep this a small local retriever; domain concepts remain explicit.
    candidates = re.findall(r"[a-z0-9_]+", value.casefold())
    # Break at whole generic expressions before n-gram generation, otherwise
    # e.g. “一直喜欢” leaves “直喜” to match unrelated interests.
    han_value = re.sub(r"我(?:一直|平时|通常|一向|长期)?(?:喜欢|偏好|习惯|不喜欢)|我的|帮我|适合我", " ", value)
    for segment in re.findall(r"[\u3400-\u9fff]+", han_value):
        candidates.extend(segment[i:i + 2] for i in range(len(segment) - 1))
    return frozenset(
        term
        for term in candidates
        if len(term) > 1 and term not in _GENERIC_TERMS
    )


def _concepts(terms: frozenset[str]) -> frozenset[str]:
    return frozenset(
        concept for concept, vocabulary in _CONCEPTS.items() if terms & vocabulary
    )


__all__ = ["AssistantContextAssembler", "MemoryRetriever"]
