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
        }
    ),
    "air_travel_seat": frozenset(
        {"aisle", "flight", "flying", "plane", "seat", "seats", "window"}
    ),
    "food": frozenset(
        {"allergy", "cilantro", "dinner", "eat", "food", "meal", "restaurant"}
    ),
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
    return frozenset(
        term
        for term in re.findall(r"[\w]+", value.casefold())
        if len(term) > 1 and term not in _GENERIC_TERMS
    )


def _concepts(terms: frozenset[str]) -> frozenset[str]:
    return frozenset(
        concept for concept, vocabulary in _CONCEPTS.items() if terms & vocabulary
    )


__all__ = ["AssistantContextAssembler", "MemoryRetriever"]
