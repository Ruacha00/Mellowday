"""The public orchestration facade for one conversation turn."""

import json
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from .extensions import (
    LoadedSkill,
    Skill,
    SkillMetadata,
    Tool,
    ToolArgumentsError,
    ToolCall,
    ToolExecutionResult,
    ToolMetadata,
    validate_tool_arguments,
)
from .provider import ModelProvider, ProviderRequest
from .types import ChatContent, EventType, RuntimeEvent, TurnRequest, TurnResult


class AgentCore:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        tools: Iterable[Tool] = (),
        skills: Iterable[Skill] = (),
        skill_state_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._provider = provider
        self._clock = clock
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"Tool already registered: {tool.name}")
            self._tools[tool.name] = tool
        self._skills: dict[str, Skill] = {}
        self._skill_enabled: dict[str, bool] = {}
        self._skill_state_path = (
            Path(skill_state_path) if skill_state_path is not None else None
        )
        saved_skill_state = self._read_skill_state()
        for skill in skills:
            if skill.name in self._skills:
                raise ValueError(f"Skill already registered: {skill.name}")
            self._skills[skill.name] = skill
            self._skill_enabled[skill.name] = saved_skill_state.get(
                skill.name, skill.enabled_by_default
            )

    def list_tools(self) -> tuple[ToolMetadata, ...]:
        """Return neutral Tool metadata without exposing executors."""

        return tuple(tool.metadata() for tool in self._tools.values())

    def list_skills(self) -> tuple[SkillMetadata, ...]:
        """Return discoverable metadata without loading Skill instructions."""

        return tuple(
            skill.metadata(enabled=self._skill_enabled[name])
            for name, skill in self._skills.items()
        )

    def set_skill_enabled(self, name: str, enabled: bool) -> SkillMetadata | None:
        """Update and locally persist one registered Skill's enablement."""

        skill = self._skills.get(name)
        if skill is None:
            return None
        self._skill_enabled[name] = enabled
        self._write_skill_state()
        return skill.metadata(enabled=enabled)

    async def run_turn(self, request: TurnRequest) -> TurnResult:
        conversation_id = request.conversation_id.strip()
        messages = tuple(
            ChatContent(role=message.role, content=message.content.strip())
            for message in request.messages
        )
        events: list[RuntimeEvent] = []

        def emit(event_type: EventType, **details: object) -> None:
            events.append(
                RuntimeEvent(
                    sequence=len(events) + 1,
                    type=event_type,
                    occurred_at=self._clock(),
                    conversation_id=conversation_id,
                    details=details,
                )
            )

        emit("turn_started", message_count=len(messages))
        tool_results: list[ToolExecutionResult] = []
        loaded_skills: dict[str, LoadedSkill] = {}
        for skill_name in request.requested_skills:
            self._load_skill(skill_name, loaded_skills, emit)
        while True:
            emit("provider_started", provider=self._provider.name)
            reply = await self._provider.complete(
                ProviderRequest(
                    messages=messages,
                    tools=self.list_tools(),
                    tool_results=tuple(tool_results),
                    skills=tuple(
                        metadata
                        for metadata in self.list_skills()
                        if metadata.enabled
                    ),
                    loaded_skills=tuple(loaded_skills.values()),
                )
            )
            emit("provider_completed", provider=self._provider.name)
            if not reply.tool_calls and not reply.selected_skills:
                break
            for skill_name in reply.selected_skills:
                self._load_skill(skill_name, loaded_skills, emit)
            for call in reply.tool_calls:
                tool_results.append(
                    await self._execute_tool(call, conversation_id, emit)
                )

        chat_content = ChatContent(role="assistant", content=reply.content.strip())
        emit("turn_completed", stop_reason="final")
        return TurnResult(
            chat_content=chat_content,
            stop_reason="final",
            events=tuple(events),
        )

    async def _execute_tool(
        self,
        call: ToolCall,
        conversation_id: str,
        emit: Callable[..., None],
    ) -> ToolExecutionResult:
        emit("tool_execution_started", tool=call.name, call_id=call.id)
        tool = self._tools.get(call.name)
        if tool is None:
            result = ToolExecutionResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="unknown_tool",
            )
            emit(
                "tool_execution_failed",
                tool=call.name,
                call_id=call.id,
                error=result.error,
            )
            return result
        try:
            arguments = validate_tool_arguments(tool.input_schema, call.arguments)
            value = await tool.executor(arguments, conversation_id)
        except ToolArgumentsError as error:
            result = ToolExecutionResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="invalid_arguments",
                detail=str(error),
            )
            emit(
                "tool_execution_failed",
                tool=call.name,
                call_id=call.id,
                error=result.error,
            )
            return result
        except Exception as error:  # noqa: BLE001 - extension failures are normalized
            result = ToolExecutionResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="executor_error",
                detail=str(error),
            )
            emit(
                "tool_execution_failed",
                tool=call.name,
                call_id=call.id,
                error=result.error,
            )
            return result
        result = ToolExecutionResult(
            call_id=call.id,
            name=call.name,
            ok=True,
            result=value,
        )
        emit("tool_execution_completed", tool=call.name, call_id=call.id)
        return result

    def _load_skill(
        self,
        name: str,
        loaded_skills: dict[str, LoadedSkill],
        emit: Callable[..., None],
    ) -> None:
        if name in loaded_skills:
            return
        emit("skill_load_started", skill=name)
        skill = self._skills.get(name)
        if skill is None:
            emit("skill_load_failed", skill=name, error="unknown_skill")
            return
        if not self._skill_enabled[name]:
            emit("skill_load_failed", skill=name, error="skill_disabled")
            return
        try:
            instructions = skill.instruction_loader().strip()
        except Exception as error:  # noqa: BLE001 - extension failures are normalized
            emit(
                "skill_load_failed",
                skill=name,
                error="loader_error",
                detail=str(error),
            )
            return
        if not instructions:
            emit("skill_load_failed", skill=name, error="empty_instructions")
            return
        loaded_skills[name] = LoadedSkill(name=name, instructions=instructions)
        emit("skill_loaded", skill=name)

    def _read_skill_state(self) -> dict[str, bool]:
        if self._skill_state_path is None:
            return {}
        try:
            payload = json.loads(self._skill_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(name): enabled
            for name, enabled in payload.items()
            if isinstance(enabled, bool)
        }

    def _write_skill_state(self) -> None:
        if self._skill_state_path is None:
            return
        self._skill_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._skill_state_path.write_text(
            json.dumps(self._skill_enabled, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
