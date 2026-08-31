import asyncio
from collections.abc import Sequence

import pytest

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    ProviderReply,
    ProviderRequest,
    Skill,
    Tool,
    ToolCall,
    TurnRequest,
)


class ScriptedProvider:
    name = "scripted"

    def __init__(self, replies: Sequence[ProviderReply]) -> None:
        self._replies = iter(replies)
        self.requests: list[ProviderRequest] = []

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        self.requests.append(request)
        return next(self._replies)


def test_tool_runs_through_a_complete_public_facade_turn() -> None:
    executions: list[tuple[dict[str, object], str]] = []

    async def add(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append((arguments, conversation_id))
        return {"total": int(arguments["left"]) + int(arguments["right"])}

    tool = Tool(
        name="add_numbers",
        description="Add two whole numbers.",
        input_schema={
            "type": "object",
            "properties": {
                "left": {"type": "integer"},
                "right": {"type": "integer"},
            },
            "required": ["left", "right"],
            "additionalProperties": False,
        },
        executor=add,
        permission_requirements=("calculator:use",),
        side_effect="none",
        risk="low",
    )
    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall(
                        id="call-1",
                        name="add_numbers",
                        arguments={"left": 2, "right": 3},
                    ),
                )
            ),
            ProviderReply(content="The total is 5."),
        )
    )
    times = iter(float(value) for value in range(1, 11))
    core = AgentCore(provider=provider, tools=(tool,), clock=lambda: next(times))

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Add 2 and 3."),),
            )
        )
    )

    assert result.chat_content == ChatContent(
        role="assistant", content="The total is 5."
    )
    assert executions == [
        ({"left": 2, "right": 3}, "conversation-1")
    ]
    assert [metadata.name for metadata in provider.requests[0].tools] == [
        "add_numbers"
    ]
    assert provider.requests[0].tools[0].permission_requirements == (
        "calculator:use",
    )
    assert provider.requests[0].tools[0].side_effect == "none"
    assert provider.requests[0].tools[0].risk == "low"
    assert provider.requests[1].tool_results[0].ok is True
    assert provider.requests[1].tool_results[0].result == {"total": 5}
    assert [event.type for event in result.events] == [
        "turn_started",
        "provider_started",
        "provider_completed",
        "tool_execution_started",
        "tool_execution_completed",
        "provider_started",
        "provider_completed",
        "turn_completed",
    ]


def test_invalid_tool_arguments_return_a_normalized_failure() -> None:
    executions: list[dict[str, object]] = []

    async def record(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    tool = Tool(
        name="save_count",
        description="Save one whole-number count.",
        input_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        executor=record,
        permission_requirements=("count:write",),
        side_effect="reversible",
        risk="medium",
    )
    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall(
                        id="call-invalid",
                        name="save_count",
                        arguments={"count": "three"},
                    ),
                )
            ),
            ProviderReply(content="That count was invalid."),
        )
    )
    core = AgentCore(provider=provider, tools=(tool,))

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Save three."),),
            )
        )
    )

    failure = provider.requests[1].tool_results[0]
    assert executions == []
    assert failure.ok is False
    assert failure.error == "invalid_arguments"
    assert failure.detail == "arguments.count must be integer"
    assert "tool_execution_failed" in [event.type for event in result.events]


def test_tool_schema_length_and_range_constraints_are_enforced() -> None:
    executions: list[dict[str, object]] = []

    async def record(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(arguments)
        return {"conversation_id": conversation_id}

    tool = Tool(
        name="constrained",
        description="Validate length and range constraints.",
        input_schema={
            "type": "object",
            "properties": {
                "label": {"type": "string", "minLength": 3, "maxLength": 5},
                "count": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["label", "count"],
            "additionalProperties": False,
        },
        executor=record,
    )
    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall("short", "constrained", {"label": "a", "count": 2}),
                    ToolCall("long", "constrained", {"label": "abcdef", "count": 2}),
                    ToolCall("below", "constrained", {"label": "okay", "count": 0}),
                    ToolCall("above", "constrained", {"label": "okay", "count": 11}),
                )
            ),
            ProviderReply(content="The values were invalid."),
        )
    )
    core = AgentCore(provider=provider, tools=(tool,))

    asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Validate values."),),
            )
        )
    )

    assert executions == []
    assert [result.detail for result in provider.requests[1].tool_results] == [
        "arguments.label is shorter than minLength 3",
        "arguments.label is longer than maxLength 5",
        "arguments.count is below minimum 1",
        "arguments.count is above maximum 10",
    ]


def test_tool_rejects_unknown_side_effect_and_risk_classifications() -> None:
    async def execute(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        return {"conversation_id": conversation_id, **arguments}

    with pytest.raises(ValueError, match="side-effect classification"):
        Tool(
            name="bad_side_effect",
            description="Invalid metadata.",
            input_schema={},
            executor=execute,
            side_effect="unknown",  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="risk classification"):
        Tool(
            name="bad_risk",
            description="Invalid metadata.",
            input_schema={},
            executor=execute,
            risk="unknown",  # type: ignore[arg-type]
        )


def test_tool_executor_errors_return_a_normalized_failure() -> None:
    async def fail(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        raise RuntimeError(f"extension unavailable for {conversation_id}")

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall(id="call-error", name="unstable", arguments={}),
                )
            ),
            ProviderReply(content="The extension was unavailable."),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="unstable",
                description="Synthetic failing Tool.",
                input_schema={"type": "object", "properties": {}},
                executor=fail,
            ),
        ),
    )

    asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Run it."),),
            )
        )
    )

    failure = provider.requests[1].tool_results[0]
    assert failure.ok is False
    assert failure.error == "executor_error"
    assert failure.detail == "extension unavailable for conversation-1"


def test_skill_instructions_load_only_after_provider_selection() -> None:
    loads: list[str] = []

    def load_instructions() -> str:
        loads.append("loaded")
        return "Answer with one short worked example."

    skill = Skill(
        name="worked_example",
        description="Use a worked example when explaining a concept.",
        instruction_loader=load_instructions,
    )
    provider = ScriptedProvider(
        (
            ProviderReply(selected_skills=("worked_example",)),
            ProviderReply(content="For example: 2 + 3 = 5."),
        )
    )
    times = iter(float(value) for value in range(1, 11))
    core = AgentCore(provider=provider, skills=(skill,), clock=lambda: next(times))

    assert [metadata.name for metadata in core.list_skills()] == [
        "worked_example"
    ]
    assert loads == []

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Explain addition."),),
            )
        )
    )

    assert loads == ["loaded"]
    assert provider.requests[0].loaded_skills == ()
    assert provider.requests[1].loaded_skills[0].instructions == (
        "Answer with one short worked example."
    )
    assert result.chat_content.content == "For example: 2 + 3 = 5."
    assert [event.type for event in result.events] == [
        "turn_started",
        "provider_started",
        "provider_completed",
        "skill_load_started",
        "skill_loaded",
        "provider_started",
        "provider_completed",
        "turn_completed",
    ]


def test_explicitly_requested_skill_loads_before_the_provider_call() -> None:
    skill = Skill(
        name="concise",
        description="Keep the answer concise.",
        instruction_loader=lambda: "Use no more than two sentences.",
    )
    provider = ScriptedProvider((ProviderReply(content="Short answer."),))
    times = iter(float(value) for value in range(1, 9))
    core = AgentCore(provider=provider, skills=(skill,), clock=lambda: next(times))

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Be brief."),),
                requested_skills=("concise",),
            )
        )
    )

    assert provider.requests[0].loaded_skills[0].name == "concise"
    assert [event.type for event in result.events] == [
        "turn_started",
        "skill_load_started",
        "skill_loaded",
        "provider_started",
        "provider_completed",
        "turn_completed",
    ]


def test_repeated_extension_requests_stop_without_reexecuting_a_tool() -> None:
    executions: list[str] = []

    async def execute(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(conversation_id)
        return arguments

    class RepeatingProvider:
        name = "repeating"

        def __init__(self) -> None:
            self.requests: list[ProviderRequest] = []

        async def complete(self, request: ProviderRequest) -> ProviderReply:
            self.requests.append(request)
            return ProviderReply(
                tool_calls=(ToolCall("same-call", "repeatable", {}),),
                selected_skills=("missing",),
            )

    provider = RepeatingProvider()
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="repeatable",
                description="Synthetic repeated Tool.",
                input_schema={},
                executor=execute,
            ),
        ),
        max_provider_steps=2,
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Repeat."),),
            )
        )
    )

    assert result.stop_reason == "step_limit"
    assert result.chat_content.content == ""
    assert len(provider.requests) == 2
    assert executions == ["conversation-1"]
    assert result.events[-1].type == "turn_limit_reached"
    assert result.events[-1].details == {"limit": "provider_steps"}


def test_tool_call_limit_stops_before_executing_the_batch() -> None:
    executions: list[str] = []

    async def execute(
        arguments: dict[str, object], conversation_id: str
    ) -> dict[str, object]:
        executions.append(conversation_id)
        return arguments

    provider = ScriptedProvider(
        (
            ProviderReply(
                tool_calls=(
                    ToolCall("call-1", "limited", {}),
                    ToolCall("call-2", "limited", {}),
                )
            ),
        )
    )
    core = AgentCore(
        provider=provider,
        tools=(
            Tool(
                name="limited",
                description="Synthetic limited Tool.",
                input_schema={},
                executor=execute,
            ),
        ),
        max_tool_calls=1,
    )

    result = asyncio.run(
        core.run_turn(
            TurnRequest(
                conversation_id="conversation-1",
                messages=(ChatContent(role="user", content="Run twice."),),
            )
        )
    )

    assert result.stop_reason == "tool_call_limit"
    assert result.chat_content.content == ""
    assert executions == []
    assert result.events[-1].details == {"limit": "tool_calls"}
