"""Tool adapters for Memory operations."""

from dataclasses import asdict
from typing import Literal, cast

from mellowday.agent_core import Tool

from .memories import MemoryKind, MemoryNotFoundError, SQLiteMemoryService
from .memory_policy import MemoryLearningPolicy


def build_memory_tools(service: SQLiteMemoryService) -> tuple[Tool, ...]:
    policy = MemoryLearningPolicy(service)

    async def remember(
        arguments: dict[str, object], conversation_id: str
    ) -> object:
        memory = policy.remember_explicit(
            content=cast(str, arguments["content"]),
            kind=cast(MemoryKind, arguments["kind"]),
            evidence=cast(str, arguments["evidence"]),
            source_conversation_id=conversation_id,
        )
        if memory is None:
            return {"memory": None, "rejected": "not_explicit_durable_evidence"}
        return {"memory": asdict(memory)}

    async def learn(arguments: dict[str, object], conversation_id: str) -> object:
        memory = policy.remember_automatic(
            content=cast(str, arguments["content"]),
            kind=cast(Literal["preference", "fact"], arguments["kind"]),
            evidence=cast(str, arguments["evidence"]),
            source_conversation_id=conversation_id,
        )
        if memory is None:
            return {"memory": None, "rejected": "not_durable_or_supported"}
        return {"memory": asdict(memory)}

    async def search(
        arguments: dict[str, object], _conversation_id: str
    ) -> object:
        memories = service.list(cast(str, arguments["query"]))
        return {"memories": [asdict(memory) for memory in memories]}

    async def forget(arguments: dict[str, object], conversation_id: str) -> object:
        memory_id = cast(str, arguments["memory_id"])
        memory = service.delete(memory_id, conversation_id=conversation_id)
        if memory is None:
            raise MemoryNotFoundError(f"Memory not found: {memory_id}")
        return {"deleted_memory": asdict(memory)}

    return (
        Tool(
            name="memory_remember",
            description=(
                "Save durable User information only when the User explicitly asks "
                "the Assistant to remember it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "minLength": 1},
                    "kind": {
                        "type": "string",
                        "enum": ["preference", "fact", "important"],
                    },
                    "evidence": {"type": "string", "minLength": 1},
                },
                "required": ["content", "kind", "evidence"],
                "additionalProperties": False,
            },
            executor=remember,
            permission_requirements=("memory:write",),
            side_effect="reversible",
            user_evidence_argument="evidence",
        ),
        Tool(
            name="memory_learn",
            description=(
                "Conservatively save a stable User preference or fact only when "
                "content is directly supported by a quoted User message. Never save "
                "temporary emotion, jokes, or inference."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "minLength": 1},
                    "kind": {
                        "type": "string",
                        "enum": ["preference", "fact"],
                    },
                    "evidence": {"type": "string", "minLength": 1},
                },
                "required": ["content", "kind", "evidence"],
                "additionalProperties": False,
            },
            executor=learn,
            permission_requirements=("memory:write",),
            side_effect="reversible",
            user_evidence_argument="evidence",
        ),
        Tool(
            name="memory_search",
            description=(
                "Search the User's Memory to inspect or identify a specific record."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            executor=search,
            permission_requirements=("memory:read",),
        ),
        Tool(
            name="memory_forget",
            description=(
                "Permanently forget one Memory after the User clearly requests it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "memory_id": {"type": "string", "minLength": 1},
                },
                "required": ["memory_id"],
                "additionalProperties": False,
            },
            executor=forget,
            permission_requirements=("memory:delete",),
            side_effect="irreversible",
            risk="medium",
        ),
    )


__all__ = ["build_memory_tools"]
