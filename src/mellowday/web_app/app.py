"""Browser-facing Web App boundary."""

import asyncio
import logging
import time
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Literal, assert_never, cast

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    ConfirmationBinding,
    ConfirmationDecision,
    ConfirmationError,
    ConfirmationErrorCode,
    ConversationHistoryError,
    EventType,
    ModelProvider,
    ProviderFailure,
    RuntimeEventLog,
    Skill,
    SQLiteConversationHistory,
    Tool,
    TurnRequest,
)
from mellowday.agent_core.openai_compatible import (
    HttpxProviderTransport,
    ProviderTransport,
)
from mellowday.personal_assistant import (
    Persona,
    SQLitePersonaStore,
    SQLiteTaskService,
    TaskChange,
    TaskUpdates,
    TaskValidationError,
    build_task_tools,
)

from .provider_settings import (
    SelectedProvider,
    SQLiteProviderConfigurationStore,
    build_openai_compatible_provider,
)
from .operations import install_log_buffer


_STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
_DEFAULT_SKILL_STATE_PATH = Path(".mellowday") / "skill-enablement.json"
_DEFAULT_AUDIT_PATH = Path(".mellowday") / "audit-events.jsonl"


class ChatRequestBody(BaseModel):
    conversation_id: str
    content: str


class SkillEnablementBody(BaseModel):
    enabled: bool


class PersonaBody(BaseModel):
    name: str
    identity: str
    character: str
    speaking_style: str
    relationship_framing: str
    conversational_boundaries: str
    proactive_chat_style: str


class ProviderConfigurationBody(BaseModel):
    name: str = Field(min_length=1)
    base_url: str = Field(pattern=r"^https?://")
    model: str = Field(min_length=1)
    api_key: str
    timeout_seconds: float = Field(default=60, gt=0)
    max_retries: int = Field(default=2, ge=0, le=10)


class ConfirmationChatContentBody(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ConfirmationBindingBody(BaseModel):
    user_id: str
    conversation_id: str
    tool: str
    arguments: dict[str, object]
    initiating_context: list[ConfirmationChatContentBody]


class ConfirmationDecisionBody(BaseModel):
    decision: Literal["accept", "reject"]
    binding: ConfirmationBindingBody


class ConversationResetDecisionBody(ConfirmationDecisionBody):
    confirmation_id: str


class ApplicationConfirmationDecisionBody(ConfirmationDecisionBody):
    confirmation_id: str


class DiagnosticProbeBody(BaseModel):
    content: str = Field(min_length=1, max_length=4_000)


class TaskCreateBody(BaseModel):
    title: str = Field(min_length=1)
    details: str | None = None
    deadline: str | None = None


class TaskUpdateBody(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    details: str | None = None
    deadline: str | None = None


def _confirmation_binding(body: ConfirmationBindingBody) -> ConfirmationBinding:
    return ConfirmationBinding(
        user_id=body.user_id,
        conversation_id=body.conversation_id,
        tool=body.tool,
        arguments=body.arguments,
        initiating_context=tuple(
            ChatContent(role=item.role, content=item.content)
            for item in body.initiating_context
        ),
    )


def _confirmation_status_code(code: ConfirmationErrorCode) -> int:
    match code:
        case "not_found":
            return 404
        case "expired":
            return 410
        case "binding_mismatch" | "already_decided":
            return 409
    assert_never(code)


def create_app(
    *,
    provider: ModelProvider | None = None,
    tools: Iterable[Tool] = (),
    skills: Iterable[Skill] = (),
    skill_state_path: str | Path | None = _DEFAULT_SKILL_STATE_PATH,
    audit_path: str | Path | None = _DEFAULT_AUDIT_PATH,
    conversation_database_path: str | Path | None = None,
    history_message_limit: int = 40,
    history_character_limit: int = 12_000,
    provider_transport: ProviderTransport | None = None,
) -> FastAPI:
    """Create the complete Web App boundary with an injectable Provider."""

    registered_skills = tuple(skills)
    database_path = (
        Path(conversation_database_path)
        if conversation_database_path is not None
        else Path.cwd() / "data" / "mellowday.sqlite3"
    )
    runtime_events = RuntimeEventLog()
    log_buffer = install_log_buffer()
    conversation_history = SQLiteConversationHistory(
        database_path, events=runtime_events
    )
    persona_store = SQLitePersonaStore(database_path)
    provider_store = SQLiteProviderConfigurationStore(database_path)
    agent_core_reference: list[AgentCore] = []

    def record_task_change(change: TaskChange) -> None:
        agent_core_reference[0].record_application_action(
            action=change.operation,
            resource_type="task",
            resource_id=change.task_id,
            conversation_id=change.conversation_id,
        )

    task_service = SQLiteTaskService(
        database_path, change_listener=record_task_change
    )
    registered_tools = (*build_task_tools(task_service), *tuple(tools))
    provider_health: dict[str, dict[str, object]] = {}
    configured_provider_transport = provider_transport or HttpxProviderTransport()
    if provider is None:
        selected_provider: ModelProvider = SelectedProvider(
            provider_store,
            configured_provider_transport,
        )
    else:
        selected_provider = provider
    agent_core = AgentCore(
        provider=selected_provider,
        tools=registered_tools,
        skills=registered_skills,
        skill_state_path=skill_state_path,
        audit_path=audit_path,
        conversation_history=conversation_history,
        history_message_limit=history_message_limit,
        history_character_limit=history_character_limit,
        system_instructions_provider=lambda: persona_store.get().chat_instructions(),
        provider_failure_content_provider=(
            lambda error: persona_store.get().provider_failure_chat_content(error.code)
        ),
        runtime_events=runtime_events,
    )
    agent_core_reference.append(agent_core)
    diagnostic_core = AgentCore(
        provider=selected_provider,
        tools=(),
        skills=registered_skills,
        skill_state_path=None,
        audit_path=None,
        conversation_history=None,
        system_instructions_provider=None,
        provider_failure_content_provider=lambda _error: "Provider call failed.",
        runtime_events=runtime_events,
    )
    diagnostic_lock = asyncio.Lock()
    app = FastAPI(title="Mellowday", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_STATIC_DIRECTORY), name="static")

    @app.exception_handler(ConversationHistoryError)
    async def conversation_history_failure(
        _request: Request, error: ConversationHistoryError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": {
                    "code": "conversation_history_unavailable",
                    "operation": error.operation,
                }
            },
        )

    @app.exception_handler(TaskValidationError)
    async def task_validation_failure(
        _request: Request, error: TaskValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": {"code": "invalid_task", "message": str(error)}
            },
        )

    @app.get("/", response_class=FileResponse)
    async def conversation_surface() -> FileResponse:
        return FileResponse(_STATIC_DIRECTORY / "index.html")

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/settings/status")
    async def operation_status() -> dict[str, object]:
        selected_configuration = provider_store.selected()
        if selected_configuration is not None:
            provider_status: dict[str, object] = {
                "id": selected_configuration.id,
                "name": selected_configuration.name,
                "model": selected_configuration.model,
                "enabled": selected_configuration.enabled,
                "configured": True,
                "health": provider_health.get(
                    selected_configuration.id, {"state": "not_checked"}
                ),
            }
        else:
            provider_status = {
                "name": selected_provider.name,
                "configured": provider is not None,
                "enabled": provider is not None,
                "health": {"state": "not_checked"},
            }
        return {
            "backend": {"ok": True, "service": "mellowday"},
            "provider": provider_status,
            "sessions": conversation_history.count_conversations(),
            "pending_confirmations": len(
                agent_core.list_pending_confirmations()
            ),
            "tools": len(agent_core.list_tools()),
            "skills": len(agent_core.list_skills()),
            "event_cursor": runtime_events.cursor,
            "log_cursor": log_buffer.cursor,
            "single_user": True,
        }

    @app.get("/api/settings/capabilities")
    async def capability_settings() -> dict[str, object]:
        return {
            "tools": [asdict(metadata) for metadata in agent_core.list_tools()],
            "skills": [asdict(metadata) for metadata in agent_core.list_skills()],
        }

    @app.put("/api/settings/skills/{name}/enabled")
    async def set_skill_enabled(
        name: str, body: SkillEnablementBody
    ) -> dict[str, object]:
        change = agent_core.set_skill_enabled(name, body.enabled)
        if change is None:
            raise HTTPException(status_code=404, detail="Skill not found")
        metadata, event = change
        return {"skill": asdict(metadata), "event": asdict(event)}

    @app.get("/api/settings/confirmations")
    async def pending_confirmations() -> dict[str, object]:
        return {
            "confirmations": [
                asdict(confirmation)
                for confirmation in agent_core.list_pending_confirmations()
            ]
        }

    @app.post("/api/settings/confirmations/{confirmation_id}/decision")
    async def decide_confirmation(
        confirmation_id: str, body: ConfirmationDecisionBody
    ) -> dict[str, object]:
        binding = _confirmation_binding(body.binding)
        try:
            turn = await agent_core.decide_confirmation(
                ConfirmationDecision(
                    confirmation_id=confirmation_id,
                    binding=binding,
                    decision=body.decision,
                )
            )
        except ConfirmationError as error:
            raise HTTPException(
                status_code=_confirmation_status_code(error.code),
                detail="Confirmation is unavailable for this decision",
            ) from error
        return {"turn": asdict(turn)}

    @app.get("/api/settings/audit")
    async def audit_history() -> dict[str, object]:
        return {
            "events": [asdict(event) for event in agent_core.list_audit_events()]
        }

    @app.post("/api/chat")
    async def chat(body: ChatRequestBody) -> dict[str, object]:
        result = await agent_core.run_turn(
            TurnRequest(
                conversation_id=body.conversation_id,
                messages=(ChatContent(role="user", content=body.content),),
            )
        )
        return asdict(result)

    @app.post("/api/settings/diagnostics/probe")
    async def diagnostic_probe(body: DiagnosticProbeBody) -> dict[str, object]:
        started = time.monotonic()
        async with diagnostic_lock:
            cursor = runtime_events.cursor
            try:
                result = await diagnostic_core.run_turn(
                    TurnRequest(
                        conversation_id="diagnostic-probe",
                        messages=(
                            ChatContent(role="user", content=body.content.strip()),
                        ),
                    )
                )
            except Exception as error:
                logging.getLogger("mellowday.web_app").error(
                    "Diagnostic probe failed: %s", type(error).__name__
                )
                raise HTTPException(
                    status_code=503,
                    detail={"code": "diagnostic_probe_failed"},
                ) from error
            events = runtime_events.query(
                since=cursor,
                limit=200,
                conversation_id="diagnostic-probe",
            )
        return {
            "turn": asdict(result),
            "duration_ms": int((time.monotonic() - started) * 1_000),
            "events": [asdict(event) for event in events],
        }

    @app.get("/api/settings/confirmations/recent")
    async def recent_confirmation_decisions() -> dict[str, object]:
        decisions = []
        for event in agent_core.list_audit_events():
            if event.type not in {"confirmation_accepted", "confirmation_rejected"}:
                continue
            decisions.append(
                {
                    "confirmation_id": event.details.get("confirmation_id", ""),
                    "conversation_id": event.conversation_id,
                    "decided_at": event.occurred_at,
                    "status": (
                        "accepted"
                        if event.type == "confirmation_accepted"
                        else "rejected"
                    ),
                    "tool": event.details.get("tool", ""),
                }
            )
        return {"confirmations": decisions[-50:]}

    @app.get("/api/conversations")
    async def list_conversations() -> dict[str, object]:
        return {
            "conversations": [
                asdict(conversation)
                for conversation in conversation_history.list_conversations()
            ]
        }

    @app.get("/api/conversations/{conversation_id}")
    async def get_conversation(conversation_id: str) -> dict[str, object]:
        conversation = conversation_history.get_conversation(conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {
            "conversation": asdict(conversation.summary),
            "messages": [asdict(message) for message in conversation.messages],
        }

    @app.post("/api/conversations/{conversation_id}/reset")
    async def reset_conversation(
        conversation_id: str, body: ConversationResetDecisionBody
    ) -> dict[str, object]:
        if body.binding.conversation_id != conversation_id:
            raise HTTPException(
                status_code=409,
                detail="Confirmation is bound to a different conversation",
            )
        binding = _confirmation_binding(body.binding)
        try:
            decision, removed_messages, event = (
                agent_core.decide_conversation_history_reset(
                    ConfirmationDecision(
                        confirmation_id=body.confirmation_id,
                        binding=binding,
                        decision=body.decision,
                    )
                )
            )
        except ConfirmationError as error:
            raise HTTPException(
                status_code=_confirmation_status_code(error.code),
                detail="Confirmation is unavailable for this decision",
            ) from error
        return {
            "ok": decision == "accept",
            "decision": decision,
            "removed_messages": removed_messages,
            "event": asdict(event),
        }

    @app.get("/api/settings/providers")
    async def list_provider_configurations() -> dict[str, object]:
        return {
            "providers": [
                configuration.settings_payload()
                for configuration in provider_store.list()
            ]
        }

    @app.post("/api/settings/providers", status_code=201)
    async def create_provider_configuration(
        body: ProviderConfigurationBody,
    ) -> dict[str, object]:
        configuration = provider_store.create(**body.model_dump())
        return {"provider": configuration.settings_payload()}

    @app.put("/api/settings/providers/{provider_id}")
    async def update_provider_configuration(
        provider_id: str, body: ProviderConfigurationBody
    ) -> dict[str, object]:
        configuration = provider_store.update(provider_id, **body.model_dump())
        if configuration is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        provider_health.pop(provider_id, None)
        return {"provider": configuration.settings_payload()}

    @app.post("/api/settings/providers/{provider_id}/select")
    async def select_provider_configuration(provider_id: str) -> dict[str, object]:
        configuration = provider_store.select(provider_id)
        if configuration is None:
            raise HTTPException(
                status_code=409, detail="Provider is unavailable for selection"
            )
        return {"provider": configuration.settings_payload()}

    @app.post("/api/settings/providers/{provider_id}/validate")
    async def validate_provider_configuration(provider_id: str) -> dict[str, object]:
        configuration = provider_store.get(provider_id)
        if configuration is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        adapter = build_openai_compatible_provider(
            configuration, configured_provider_transport
        )

        try:
            await adapter.validate()
        except ProviderFailure as error:
            provider_health[provider_id] = {
                "state": "unavailable",
                "code": error.code,
                "checked_at": time.time(),
            }
            return {
                "valid": False,
                "failure": {
                    "code": error.code,
                    "retryable": error.retryable,
                    "attempts": error.attempts,
                },
            }
        provider_health[provider_id] = {
            "state": "available",
            "checked_at": time.time(),
        }
        return {"valid": True}

    @app.put("/api/settings/providers/{provider_id}/enabled")
    async def set_provider_enabled(
        provider_id: str, body: SkillEnablementBody
    ) -> dict[str, object]:
        configuration = provider_store.set_enabled(provider_id, body.enabled)
        if configuration is None:
            raise HTTPException(status_code=404, detail="Provider not found")
        return {"provider": configuration.settings_payload()}

    @app.get("/api/settings/persona")
    async def get_persona() -> dict[str, object]:
        return {"persona": asdict(persona_store.get())}

    @app.put("/api/settings/persona")
    async def update_persona(body: PersonaBody) -> dict[str, object]:
        persona = persona_store.update(Persona(**body.model_dump()))
        return {"persona": asdict(persona)}

    @app.get("/api/settings/tasks")
    async def list_tasks() -> dict[str, object]:
        return {"tasks": [asdict(task) for task in task_service.list()]}

    @app.post("/api/settings/tasks", status_code=201)
    async def create_task(body: TaskCreateBody) -> dict[str, object]:
        task = task_service.create(**body.model_dump())
        return {"task": asdict(task)}

    @app.get("/api/settings/tasks/{task_id}")
    async def get_task(task_id: str) -> dict[str, object]:
        task = task_service.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(task)}

    @app.patch("/api/settings/tasks/{task_id}")
    async def update_task(
        task_id: str, body: TaskUpdateBody
    ) -> dict[str, object]:
        updates = cast(TaskUpdates, body.model_dump(exclude_unset=True))
        if "title" in updates and updates["title"] is None:
            raise TaskValidationError("title must not be null")
        task = task_service.update(
            task_id,
            **updates,
        )
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(task)}

    @app.post("/api/settings/tasks/{task_id}/complete")
    async def complete_task(task_id: str) -> dict[str, object]:
        task = task_service.complete(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(task)}

    @app.post("/api/settings/tasks/{task_id}/reopen")
    async def reopen_task(task_id: str) -> dict[str, object]:
        task = task_service.reopen(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"task": asdict(task)}

    @app.post("/api/settings/tasks/{task_id}/delete-confirmation")
    async def request_task_delete_confirmation(
        task_id: str,
    ) -> dict[str, object]:
        if task_service.get(task_id) is None:
            raise HTTPException(status_code=404, detail="Task not found")
        confirmation, event = agent_core.request_application_confirmation(
            user_id="local-user",
            conversation_id="settings",
            action="task_delete",
            arguments={"task_id": task_id},
        )
        return {"confirmation": asdict(confirmation), "event": asdict(event)}

    @app.delete("/api/settings/tasks/{task_id}")
    async def delete_task(
        task_id: str, body: ApplicationConfirmationDecisionBody
    ) -> dict[str, object]:
        if (
            body.binding.tool != "task_delete"
            or body.binding.arguments != {"task_id": task_id}
        ):
            raise HTTPException(
                status_code=409,
                detail="Confirmation is bound to a different Task action",
            )
        try:
            decision, event = agent_core.decide_application_confirmation(
                ConfirmationDecision(
                    confirmation_id=body.confirmation_id,
                    binding=_confirmation_binding(body.binding),
                    decision=body.decision,
                )
            )
        except ConfirmationError as error:
            raise HTTPException(
                status_code=_confirmation_status_code(error.code),
                detail="Confirmation is unavailable for this decision",
            ) from error
        if decision == "reject":
            return {"ok": False, "decision": decision, "event": asdict(event)}
        task = task_service.delete(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "ok": True,
            "decision": decision,
            "deleted_task": asdict(task),
            "event": asdict(event),
        }

    @app.post("/api/conversations/{conversation_id}/reset-confirmation")
    async def request_reset_confirmation(
        conversation_id: str,
    ) -> dict[str, object]:
        if conversation_history.get_conversation(conversation_id) is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        confirmation, event = agent_core.request_conversation_history_reset(
            user_id="local-user", conversation_id=conversation_id
        )
        return {"confirmation": asdict(confirmation), "event": asdict(event)}

    @app.get("/api/events/recent")
    async def recent_events(
        since: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=200),
        event_type: EventType | None = Query(default=None, alias="type"),
        conversation_id: str = "",
    ) -> dict[str, object]:
        events = runtime_events.query(
            since=since,
            limit=limit,
            event_type=event_type,
            conversation_id=conversation_id,
        )
        return {
            "events": [asdict(event) for event in events],
            "cursor": events[-1].sequence if events else runtime_events.cursor,
        }

    @app.get("/api/logs/recent")
    async def recent_logs(
        since: int = Query(default=0, ge=0),
        limit: int = Query(default=200, ge=1, le=200),
        level: Literal["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "",
        q: str = "",
    ) -> dict[str, object]:
        logs = log_buffer.query(
            since=since,
            limit=limit,
            minimum_level=level,
            contains=q,
        )
        return {
            "logs": list(logs),
            "cursor": (
                cast(int, logs[-1]["sequence"])
                if logs
                else log_buffer.cursor
            ),
        }

    return app
