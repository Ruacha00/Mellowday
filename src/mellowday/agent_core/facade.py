"""The public orchestration facade for one conversation turn."""

import json
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Literal

from .actions import ExecutionContext, PermissionDecision, PermissionEngine
from .audit import AuditLog
from .confirmations import (
    ConfirmationBinding,
    ConfirmationDecision,
    ConfirmationResolution,
    ConfirmationStore,
    PendingConfirmation,
)
from .extensions import (
    LoadedSkill,
    Skill,
    SkillMetadata,
    Tool,
    ToolArgumentsError,
    ToolCall,
    ToolExecutionResult,
    ToolMetadata,
    ToolOutcome,
    UndoMetadata,
    validate_tool_arguments,
)
from .provider import ModelProvider, ProviderRequest
from .types import (
    ChatContent,
    EventType,
    RuntimeEvent,
    StopReason,
    TurnRequest,
    TurnResult,
)


class AgentCore:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        tools: Iterable[Tool] = (),
        skills: Iterable[Skill] = (),
        skill_state_path: str | Path | None = None,
        max_provider_steps: int = 8,
        max_tool_calls: int = 16,
        confirmation_ttl_seconds: float = 600,
        audit_path: str | Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if max_provider_steps < 1:
            raise ValueError("max_provider_steps must be at least 1")
        if max_tool_calls < 0:
            raise ValueError("max_tool_calls must not be negative")
        self._provider = provider
        self._permission_engine = PermissionEngine()
        self._confirmations = ConfirmationStore(confirmation_ttl_seconds)
        self._clock = clock
        self._max_provider_steps = max_provider_steps
        self._max_tool_calls = max_tool_calls
        self._audit = AuditLog(audit_path)
        self._event_sequence = self._audit.last_sequence
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

    def list_pending_confirmations(self) -> tuple[PendingConfirmation, ...]:
        """Return pending confirmations without exposing executable state."""

        return self._confirmations.pending(now=self._clock())

    def list_audit_events(self) -> tuple[RuntimeEvent, ...]:
        """Return neutral action and runtime history in sequence order."""

        return self._audit.events()

    async def decide_confirmation(
        self, decision: ConfirmationDecision
    ) -> TurnResult:
        """Accept or reject one bound confirmation exactly once."""

        resolution = self._confirmations.decide(decision, now=self._clock())
        binding = resolution.pending.binding
        events: list[RuntimeEvent] = []

        def emit(event_type: EventType, **details: object) -> None:
            events.append(
                self._runtime_event(
                    event_type,
                    conversation_id=binding.conversation_id,
                    **details,
                )
            )

        if resolution.decision == "accept":
            emit(
                "confirmation_accepted",
                confirmation_id=resolution.pending.id,
                tool=binding.tool,
            )
            tool_result = await self._execute_confirmed_tool(resolution, emit)
            stop_reason: StopReason = "confirmation_accepted"
        else:
            emit(
                "confirmation_rejected",
                confirmation_id=resolution.pending.id,
                tool=binding.tool,
            )
            tool_result = ToolExecutionResult(
                call_id=resolution.call_id,
                name=binding.tool,
                ok=False,
                error="user_rejected",
            )
            stop_reason = "confirmation_rejected"

        emit("provider_started", provider=self._provider.name)
        reply = await self._provider.complete(
            ProviderRequest(
                messages=binding.initiating_context,
                tools=self.list_tools(),
                tool_results=resolution.prior_tool_results + (tool_result,),
                skills=tuple(
                    metadata
                    for metadata in self.list_skills()
                    if metadata.enabled
                ),
                loaded_skills=resolution.loaded_skills,
            )
        )
        emit("provider_completed", provider=self._provider.name)
        emit("turn_completed", stop_reason=stop_reason)
        return TurnResult(
            chat_content=ChatContent(role="assistant", content=reply.content.strip()),
            stop_reason=stop_reason,
            events=tuple(events),
        )

    def set_skill_enabled(
        self, name: str, enabled: bool
    ) -> tuple[SkillMetadata, RuntimeEvent] | None:
        """Update and locally persist one registered Skill's enablement."""

        skill = self._skills.get(name)
        if skill is None:
            return None
        self._skill_enabled[name] = enabled
        self._write_skill_state()
        metadata = skill.metadata(enabled=enabled)
        event = self._runtime_event(
            "skill_enablement_changed",
            conversation_id=None,
            skill=name,
            enabled=enabled,
        )
        return metadata, event

    async def run_turn(self, request: TurnRequest) -> TurnResult:
        conversation_id = request.conversation_id.strip()
        execution_context = ExecutionContext(
            user_id=request.user_id.strip(),
            conversation_id=conversation_id,
            granted_permissions=request.granted_permissions,
        )
        messages = tuple(
            ChatContent(role=message.role, content=message.content.strip())
            for message in request.messages
        )
        events: list[RuntimeEvent] = []

        def emit(event_type: EventType, **details: object) -> None:
            events.append(
                self._runtime_event(
                    event_type,
                    conversation_id=conversation_id,
                    **details,
                )
            )

        emit("turn_started", message_count=len(messages))
        tool_results: list[ToolExecutionResult] = []
        loaded_skills: dict[str, LoadedSkill] = {}
        handled_call_ids: set[str] = set()
        provider_steps = 0
        tool_calls = 0
        last_reply_content = ""
        final_stop_reason: StopReason = "final"
        clarification_requested = False
        for skill_name in request.requested_skills:
            self._load_skill(skill_name, loaded_skills, emit)
        while True:
            if provider_steps >= self._max_provider_steps:
                return self._limit_result(
                    events=events,
                    emit=emit,
                    stop_reason="step_limit",
                    limit="provider_steps",
                    reply_content=last_reply_content,
                )
            provider_steps += 1
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
            last_reply_content = reply.content.strip()
            if not reply.tool_calls and not reply.selected_skills:
                if clarification_requested:
                    final_stop_reason = "clarification"
                break
            if tool_calls + len(reply.tool_calls) > self._max_tool_calls:
                return self._limit_result(
                    events=events,
                    emit=emit,
                    stop_reason="tool_call_limit",
                    limit="tool_calls",
                    reply_content=last_reply_content,
                )
            tool_calls += len(reply.tool_calls)
            for skill_name in reply.selected_skills:
                self._load_skill(skill_name, loaded_skills, emit)
            clarifying_call = next(
                (
                    call
                    for call in reply.tool_calls
                    if call.id not in handled_call_ids
                    and (tool := self._tools.get(call.name)) is not None
                    and self._permission_decision(tool, call, execution_context)
                    == "clarify"
                ),
                None,
            )
            if clarifying_call is not None:
                handled_call_ids.add(clarifying_call.id)
                emit(
                    "action_decided",
                    tool=clarifying_call.name,
                    call_id=clarifying_call.id,
                    decision="clarify",
                )
                tool_results.append(
                    ToolExecutionResult(
                        call_id=clarifying_call.id,
                        name=clarifying_call.name,
                        ok=False,
                        error="ambiguous_intent",
                    )
                )
                clarification_requested = True
                continue
            for call in reply.tool_calls:
                if call.id in handled_call_ids:
                    emit(
                        "tool_execution_failed",
                        tool=call.name,
                        call_id=call.id,
                        error="duplicate_call",
                    )
                    continue
                handled_call_ids.add(call.id)
                outcome = await self._execute_tool(
                    call,
                    execution_context,
                    messages,
                    tuple(tool_results),
                    tuple(loaded_skills.values()),
                    emit,
                )
                if outcome == "clarify":
                    tool_results.append(
                        ToolExecutionResult(
                            call_id=call.id,
                            name=call.name,
                            ok=False,
                            error="ambiguous_intent",
                        )
                    )
                    clarification_requested = True
                    break
                if isinstance(outcome, PendingConfirmation):
                    emit(
                        "confirmation_pending",
                        confirmation_id=outcome.id,
                        tool=outcome.binding.tool,
                        expires_at=outcome.expires_at,
                    )
                    return TurnResult(
                        chat_content=ChatContent(
                            role="assistant", content=reply.content.strip()
                        ),
                        stop_reason="confirmation_pending",
                        events=tuple(events),
                        confirmation=outcome,
                    )
                tool_results.append(outcome)

        chat_content = ChatContent(role="assistant", content=reply.content.strip())
        emit("turn_completed", stop_reason=final_stop_reason)
        return TurnResult(
            chat_content=chat_content,
            stop_reason=final_stop_reason,
            events=tuple(events),
        )

    def _runtime_event(
        self,
        event_type: EventType,
        *,
        conversation_id: str | None,
        **details: object,
    ) -> RuntimeEvent:
        self._event_sequence += 1
        event = RuntimeEvent(
            sequence=self._event_sequence,
            type=event_type,
            occurred_at=self._clock(),
            conversation_id=conversation_id,
            details=details,
        )
        self._audit.append(event)
        return event

    @staticmethod
    def _limit_result(
        *,
        events: list[RuntimeEvent],
        emit: Callable[..., None],
        stop_reason: StopReason,
        limit: str,
        reply_content: str,
    ) -> TurnResult:
        emit("turn_limit_reached", limit=limit)
        return TurnResult(
            chat_content=ChatContent(role="assistant", content=reply_content),
            stop_reason=stop_reason,
            events=tuple(events),
        )

    async def _execute_tool(
        self,
        call: ToolCall,
        context: ExecutionContext,
        initiating_context: tuple[ChatContent, ...],
        prior_tool_results: tuple[ToolExecutionResult, ...],
        loaded_skills: tuple[LoadedSkill, ...],
        emit: Callable[..., None],
    ) -> ToolExecutionResult | PendingConfirmation | Literal["clarify"]:
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
        decision = self._permission_decision(tool, call, context)
        emit("action_decided", tool=call.name, call_id=call.id, decision=decision)
        if decision == "clarify":
            return "clarify"
        if decision == "deny":
            result = ToolExecutionResult(
                call_id=call.id,
                name=call.name,
                ok=False,
                error="permission_denied",
            )
            emit(
                "tool_execution_failed",
                tool=call.name,
                call_id=call.id,
                error=result.error,
            )
            return result
        arguments = self._validate_tool_call(
            tool=tool,
            call_id=call.id,
            arguments=call.arguments,
            emit=emit,
        )
        if isinstance(arguments, ToolExecutionResult):
            return arguments
        if decision == "confirm":
            return self._confirmations.create(
                binding=ConfirmationBinding(
                    user_id=context.user_id,
                    conversation_id=context.conversation_id,
                    tool=tool.name,
                    arguments=arguments,
                    initiating_context=initiating_context,
                ),
                call_id=call.id,
                granted_permissions=context.granted_permissions,
                prior_tool_results=prior_tool_results,
                loaded_skills=loaded_skills,
                now=self._clock(),
            )
        return await self._invoke_validated_tool(
            tool=tool,
            call_id=call.id,
            arguments=arguments,
            conversation_id=context.conversation_id,
            emit=emit,
        )

    def _permission_decision(
        self, tool: Tool, call: ToolCall, context: ExecutionContext
    ) -> PermissionDecision:
        return self._permission_engine.decide(
            tool.metadata(),
            ExecutionContext(
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                granted_permissions=context.granted_permissions,
                intent_clarity=call.intent_clarity,
            ),
        )

    async def _execute_confirmed_tool(
        self,
        resolution: ConfirmationResolution,
        emit: Callable[..., None],
    ) -> ToolExecutionResult:
        binding = resolution.pending.binding
        tool = self._tools.get(binding.tool)
        if tool is None:
            result = ToolExecutionResult(
                call_id=resolution.call_id,
                name=binding.tool,
                ok=False,
                error="unknown_tool",
            )
            emit(
                "tool_execution_failed",
                tool=binding.tool,
                call_id=resolution.call_id,
                error=result.error,
            )
            return result
        context = ExecutionContext(
            user_id=binding.user_id,
            conversation_id=binding.conversation_id,
            granted_permissions=resolution.granted_permissions,
        )
        permission = self._permission_engine.decide(tool.metadata(), context)
        if permission == "deny":
            result = ToolExecutionResult(
                call_id=resolution.call_id,
                name=binding.tool,
                ok=False,
                error="permission_denied",
            )
            emit(
                "tool_execution_failed",
                tool=binding.tool,
                call_id=resolution.call_id,
                error=result.error,
            )
            return result
        arguments = self._validate_tool_call(
            tool=tool,
            call_id=resolution.call_id,
            arguments=binding.arguments,
            emit=emit,
        )
        if isinstance(arguments, ToolExecutionResult):
            return arguments
        return await self._invoke_validated_tool(
            tool=tool,
            call_id=resolution.call_id,
            arguments=arguments,
            conversation_id=binding.conversation_id,
            emit=emit,
        )

    @staticmethod
    def _validate_tool_call(
        *,
        tool: Tool,
        call_id: str,
        arguments: Mapping[str, object] | None,
        emit: Callable[..., None],
    ) -> dict[str, object] | ToolExecutionResult:
        try:
            return validate_tool_arguments(tool.input_schema, arguments)
        except ToolArgumentsError as error:
            result = ToolExecutionResult(
                call_id=call_id,
                name=tool.name,
                ok=False,
                error="invalid_arguments",
                detail=str(error),
            )
            emit(
                "tool_execution_failed",
                tool=tool.name,
                call_id=call_id,
                error=result.error,
            )
            return result

    async def _invoke_validated_tool(
        self,
        *,
        tool: Tool,
        call_id: str,
        arguments: dict[str, object],
        conversation_id: str,
        emit: Callable[..., None],
    ) -> ToolExecutionResult:
        emit("tool_execution_started", tool=tool.name, call_id=call_id)
        try:
            value = await tool.executor(arguments, conversation_id)
        except Exception as error:  # noqa: BLE001 - extension failures are normalized
            result = ToolExecutionResult(
                call_id=call_id,
                name=tool.name,
                ok=False,
                error="executor_error",
                detail=str(error),
            )
            emit(
                "tool_execution_failed",
                tool=tool.name,
                call_id=call_id,
                error=result.error,
            )
            return result
        result_value, undo = self._normalize_tool_outcome(value)
        result = ToolExecutionResult(
            call_id=call_id,
            name=tool.name,
            ok=True,
            result=result_value,
            undo=undo,
        )
        completion_details: dict[str, object] = {
            "tool": tool.name,
            "call_id": call_id,
        }
        if undo is not None:
            completion_details["undo"] = asdict(undo)
        emit("tool_execution_completed", **completion_details)
        return result

    @staticmethod
    def _normalize_tool_outcome(
        value: object,
    ) -> tuple[object, UndoMetadata | None]:
        if isinstance(value, ToolOutcome):
            return value.value, value.undo
        return value, None

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
