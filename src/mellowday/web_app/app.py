"""Browser-facing Web App boundary."""

from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Literal, assert_never

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    ConfirmationBinding,
    ConfirmationDecision,
    ConfirmationError,
    ConfirmationErrorCode,
    ConversationHistoryError,
    FakeProvider,
    ModelProvider,
    RuntimeEventLog,
    Skill,
    SQLiteConversationHistory,
    Tool,
    TurnRequest,
)


_STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
_DEFAULT_SKILL_STATE_PATH = Path(".mellowday") / "skill-enablement.json"
_DEFAULT_AUDIT_PATH = Path(".mellowday") / "audit-events.jsonl"


class ChatRequestBody(BaseModel):
    conversation_id: str
    content: str


class SkillEnablementBody(BaseModel):
    enabled: bool


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
    history_context_limit: int = 12_000,
) -> FastAPI:
    """Create the complete Web App boundary with an injectable Provider."""

    selected_provider = provider if provider is not None else FakeProvider()
    database_path = (
        Path(conversation_database_path)
        if conversation_database_path is not None
        else Path.cwd() / "data" / "mellowday.sqlite3"
    )
    runtime_events = RuntimeEventLog()
    conversation_history = SQLiteConversationHistory(
        database_path, events=runtime_events
    )
    agent_core = AgentCore(
        provider=selected_provider,
        tools=tools,
        skills=skills,
        skill_state_path=skill_state_path,
        audit_path=audit_path,
        conversation_history=conversation_history,
        history_message_limit=history_message_limit,
        history_context_limit=history_context_limit,
    )
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

    @app.get("/", response_class=FileResponse)
    async def conversation_surface() -> FileResponse:
        return FileResponse(_STATIC_DIRECTORY / "index.html")

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

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
        binding = ConfirmationBinding(
            user_id=body.binding.user_id,
            conversation_id=body.binding.conversation_id,
            tool=body.binding.tool,
            arguments=body.binding.arguments,
            initiating_context=tuple(
                ChatContent(role=item.role, content=item.content)
                for item in body.binding.initiating_context
            ),
        )
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
    async def reset_conversation(conversation_id: str) -> dict[str, object]:
        removed_messages = conversation_history.reset(conversation_id)
        return {"ok": True, "removed_messages": removed_messages}

    @app.get("/api/events/recent")
    async def recent_events(limit: int = 100) -> dict[str, object]:
        return {
            "events": [
                asdict(event) for event in runtime_events.recent(limit=limit)
            ]
        }

    return app
