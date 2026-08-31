"""Browser-facing Web App boundary."""

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mellowday.agent_core import (
    AgentCore,
    ChatContent,
    FakeProvider,
    ModelProvider,
    TurnRequest,
)


_STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"


class ChatRequestBody(BaseModel):
    conversation_id: str
    content: str


def create_app(*, provider: ModelProvider | None = None) -> FastAPI:
    """Create the complete Web App boundary with an injectable Provider."""

    selected_provider = provider if provider is not None else FakeProvider()
    agent_core = AgentCore(provider=selected_provider)
    app = FastAPI(title="Mellowday", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=_STATIC_DIRECTORY), name="static")

    @app.get("/", response_class=FileResponse)
    async def conversation_surface() -> FileResponse:
        return FileResponse(_STATIC_DIRECTORY / "index.html")

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

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
