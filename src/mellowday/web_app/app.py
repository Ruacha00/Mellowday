"""Browser-facing Web App boundary."""

from dataclasses import asdict
from collections.abc import Iterable
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    FakeProvider,
    ModelProvider,
    Skill,
    Tool,
    TurnRequest,
)


_STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
_DEFAULT_SKILL_STATE_PATH = Path(".mellowday") / "skill-enablement.json"


class ChatRequestBody(BaseModel):
    conversation_id: str
    content: str


class SkillEnablementBody(BaseModel):
    enabled: bool


def create_app(
    *,
    provider: ModelProvider | None = None,
    tools: Iterable[Tool] = (),
    skills: Iterable[Skill] = (),
    skill_state_path: str | Path | None = _DEFAULT_SKILL_STATE_PATH,
) -> FastAPI:
    """Create the complete Web App boundary with an injectable Provider."""

    selected_provider = provider if provider is not None else FakeProvider()
    agent_core = AgentCore(
        provider=selected_provider,
        tools=tools,
        skills=skills,
        skill_state_path=skill_state_path,
    )
    app = FastAPI(title="Mellowday", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_STATIC_DIRECTORY), name="static")

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

    @app.post("/api/chat")
    async def chat(body: ChatRequestBody) -> dict[str, object]:
        result = await agent_core.run_turn(
            TurnRequest(
                conversation_id=body.conversation_id,
                messages=(ChatContent(role="user", content=body.content),),
            )
        )
        return asdict(result)

    return app
