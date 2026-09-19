"""FastAPI application exposing the MellowDay runtime over HTTP.

The API is intentionally small: one streaming chat endpoint, session and
configuration endpoints, and a records API over the same store the assistant
uses. The bundled static page is a thin client for exactly those endpoints.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mellowday import config, paths
from mellowday.storage.store import Store
from mellowday.timefmt import localize_record
from mellowday.web_app import service, stream

RECORD_KINDS = ("todos", "calendar", "reminders", "notes", "memories")


def create_app(*, store: Store | None = None, registry: service.SessionRegistry | None = None) -> FastAPI:
    app = FastAPI(title="MellowDay", version="0.1.0")
    app.state.store = store if store is not None else Store()
    app.state.registry = registry if registry is not None else service.SessionRegistry(store=app.state.store)

    # ------------------------------------------------------------- meta

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        cfg = config.load_model_config()
        return {"ok": True, "app": "mellowday", "version": "0.1.0", "model_configured": cfg.configured}

    # ----------------------------------------------------------- config

    @app.get("/api/config")
    async def read_config() -> dict[str, Any]:
        return config.load_model_config().public()

    @app.put("/api/config")
    async def write_config(payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        allowed = {k: v for k, v in payload.items() if k in {"api_key", "api_base", "model", "thinking", "max_turns"}}
        cfg = config.update_model_config(**allowed)
        return cfg.public()

    # ----------------------------------------------------------- chat

    @app.get("/api/persona")
    async def read_persona() -> dict[str, str]:
        from mellowday.personal_assistant.persona import load_persona, PersonaError
        try:
            return load_persona()
        except PersonaError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.put("/api/persona")
    async def write_persona(payload: dict[str, Any] = Body(...)) -> dict[str, str]:
        from mellowday.personal_assistant.persona import save_persona, validate_persona, PersonaError
        try:
            validate_persona(payload)
        except PersonaError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            return save_persona(payload)
        except PersonaError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail="人格配置保存失败，请重试；未报告保存成功") from exc

    @app.post("/api/chat")
    async def chat(request: Request, payload: dict[str, Any] = Body(default_factory=dict)):
        message = str(payload.get("message") or "")
        session_id = payload.get("session_id")
        # None / "" mean "new session" (the server generates the id). Anything
        # else must be a valid id: an unusable one is answered with 400 instead
        # of opening a stream, so it can never reach the filesystem.
        if session_id not in (None, ""):
            try:
                service.validate_session_id(session_id)
            except service.InvalidSessionId as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        accept = request.headers.get("accept", "")
        cfg = config.load_model_config()
        if not cfg.configured:
            async def failure() -> AsyncIterator[str]:
                yield stream.to_sse({"type": "error", "message": "model not configured: set MELLOWDAY_API_KEY"})
                yield stream.to_sse({"type": "done"})

            return StreamingResponse(failure(), media_type="text/event-stream")

        async def generator() -> AsyncIterator[str]:
            try:
                async for event in app.state.registry.run_turn(session_id, message):
                    yield stream.to_sse(event)
            except service.InvalidSessionId as exc:
                yield stream.to_sse({"type": "error", "message": str(exc)})
                yield stream.to_sse({"type": "done"})
            except Exception as exc:  # pragma: no cover - defensive
                yield stream.to_sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
                yield stream.to_sse({"type": "done"})

        media = "application/x-ndjson" if "ndjson" in accept else "text/event-stream"
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        return StreamingResponse(generator(), media_type=media, headers=headers)

    @app.post("/api/chat/{session_id}/abort")
    async def abort(session_id: str) -> dict[str, Any]:
        try:
            state = app.state.registry.peek(session_id)
        except service.InvalidSessionId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if state is None:
            raise HTTPException(status_code=404, detail="unknown session")
        state.confirmations.cancel_all()
        try:
            state.agent.abort()
        except Exception:
            pass
        return {"ok": True}

    # -------------------------------------------------------- sessions

    @app.get("/api/sessions")
    async def list_sessions() -> dict[str, Any]:
        return {"sessions": app.state.registry.list()}

    # Chosen behaviour for an id that exists nowhere (see docs/specs/CONTRACTS.md
    # 6bis): reading or deleting an unknown session is a 404, never an empty 200.
    # An id that could not be a session at all is a 400.
    @app.get("/api/sessions/{session_id}")
    async def session_detail(session_id: str) -> dict[str, Any]:
        registry = app.state.registry
        try:
            service.validate_session_id(session_id)
            known = registry.exists(session_id)
        except service.InvalidSessionId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not known:
            raise HTTPException(status_code=404, detail="session not found")
        # session_detail() owns the payload shape: display history plus the raw
        # execution record (tool calls, results and errors) that folding never
        # touches. The 400/404 handling above is deliberately kept here.
        return registry.session_detail(session_id)

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> dict[str, Any]:
        try:
            removed = await app.state.registry.adrop(session_id)
        except service.InvalidSessionId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if not removed:
            raise HTTPException(status_code=404, detail="session not found")
        return {"ok": True, "session_id": session_id}

    # ------------------------------------------------------ tool results

    # The web side of the restricted reference read (CONTRACTS.md 6ter.1/
    # 6ter.2). A shortened tool result keeps its whole original in the session
    # artifact directory, and a trace entry carries the bare `ref` of that
    # artifact - so the browser needs an entry point to follow the ref.

    # This must never become a general file read: `ref` is a name, not a path,
    # the lookup stays inside that one session's directory, and one response
    # is bounded. Every failure mode is reported as data - a bad ref is a 400,
    # an unknown one a 404 - so this endpoint cannot answer 500.
    @app.get("/api/sessions/{session_id}/tool-results/{ref}", response_model=None)
    async def read_tool_result(
        session_id: str,
        ref: str,
        offset: int = 0,
        limit: int | None = None,
        query: str | None = None,
    ) -> JSONResponse | dict[str, Any]:
        from mellowday.runtime import sessions as session_store

        try:
            sid = service.validate_session_id(session_id)
        except service.InvalidSessionId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # The paging window follows the runtime's own default and is clamped
        # by read_tool_artifact(), so one request can never pull in a whole
        # huge result.
        window = session_store.ARTIFACT_DEFAULT_CHARS if limit is None else int(limit)

        # A deleted or unknown session has no artifacts, and answering must not
        # create the directory tree either: the artifact layer creates it on
        # demand, so the lookup is only entered while it already exists. An
        # existing tree with no directory for this session answers 404 as well.
        if not (paths.data_dir() / session_store.ARTIFACT_DIR_NAME).is_dir():
            return JSONResponse(
                status_code=404,
                content={
                    "ok": False,
                    "error": "unknown_ref",
                    "ref": ref,
                    "detail": "本会话没有这个工具产物的 ref（会话已删除或从未产生过长结果）",
                },
            )
        try:
            result = session_store.read_tool_artifact(
                sid, ref, offset=offset, limit=window, query=query
            )
        except Exception as exc:  # pragma: no cover - unreadable data directory
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "error": "unavailable",
                    "ref": ref,
                    "detail": f"tool result unavailable: {type(exc).__name__}: {exc}",
                },
            )
        if result.get("ok"):
            return result
        error = str(result.get("error") or "")
        if error in {"invalid_ref", "invalid_arguments"}:
            status_code = 400
        elif error in {"unknown_ref", "not_found"}:
            status_code = 404
        else:
            # unreadable and anything unexpected: a report, never a crash.
            status_code = 503
        return JSONResponse(
            status_code=status_code,
            content={**result, "detail": result.get("message") or error or "tool result failed"},
        )

    # --------------------------------------------------------- records

    def _guard(kind: str) -> None:
        if kind not in RECORD_KINDS:
            raise HTTPException(status_code=404, detail=f"unknown record kind: {kind}")

    def _localize(payload: dict[str, Any]) -> dict[str, Any]:
        """Add the local-time rendering to every record this API hands out.

        The chat surface and the management page must agree on how a time is
        shown; both now go through mellowday.timefmt.
        """
        result = localize_record(payload) if "due_at" in payload else dict(payload)
        nested = result.get("record")
        if isinstance(nested, dict) and "due_at" in nested:
            result["record"] = localize_record(nested)
        return result

    @app.get("/api/records/{kind}")
    async def list_records(kind: str, q: str | None = None) -> dict[str, Any]:
        _guard(kind)
        records = app.state.store.search_records(kind, q) if q else app.state.store.list_records(kind)
        return {"kind": kind, "records": [localize_record(record) for record in records]}

    @app.post("/api/records/{kind}")
    async def create_record(kind: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        _guard(kind)
        try:
            return _localize(app.state.store.create_record(kind, payload))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.patch("/api/records/{kind}/{record_id}")
    async def update_record(
        kind: str, record_id: str, payload: dict[str, Any] = Body(default_factory=dict)
    ) -> dict[str, Any]:
        _guard(kind)
        try:
            return _localize(app.state.store.update_record(kind, record_id, payload))
        except KeyError:
            raise HTTPException(status_code=404, detail="record not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    @app.delete("/api/records/{kind}/{record_id}")
    async def delete_record(kind: str, record_id: str) -> dict[str, Any]:
        _guard(kind)
        try:
            return _localize(app.state.store.delete_record(kind, record_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="record not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    # response_model=None: this route answers either the plain result dict or a
    # 409 JSONResponse, so FastAPI must not infer a response model from the
    # union return annotation.
    @app.post("/api/records/undo/{operation_id}", response_model=None)
    async def undo(operation_id: str) -> JSONResponse | dict[str, Any]:
        result = app.state.store.undo(operation_id)
        if result.get("error") == "conflict":
            # The store refused to replay a snapshot that is no longer the
            # current state of the record. 409 carries the reason: the page
            # prints `detail`, and `message`/`changed_fields`/`current_record`
            # stay available for a richer display. Nothing was written.
            return JSONResponse(
                status_code=409,
                content={
                    **result,
                    "detail": result.get("message") or "撤销被拒绝：记录已被后续修改。",
                },
            )
        return result

    # ---------------------------------------------------- confirmations

    @app.post("/api/confirmations/{token}")
    async def confirm(token: str, payload: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or "")
        approved = bool(payload.get("approved", False))
        try:
            state = app.state.registry.peek(session_id) if session_id else None
        except service.InvalidSessionId as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if state is None:
            raise HTTPException(status_code=404, detail="unknown session")
        accepted = state.confirmations.resolve(token, approved)
        return {"ok": True, "accepted": accepted, "approved": approved}

    # -------------------------------------------------------------- skills

    # Mounted before the /api fallback below: a catch-all registered first would
    # swallow every /api/skills request and answer 404.
    from mellowday.web_app.skills_api import router as skills_router

    app.include_router(skills_router)

    # ------------------------------------------------------------ fallback

    # Anything under /api that no route matched is an API 404: it must never
    # fall through to the static file mount, which would try to serve it from
    # disk (and, on Windows, fails on a path carrying a drive letter).
    @app.api_route(
        "/api/{unmatched:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def unmatched_api(unmatched: str) -> JSONResponse:
        return JSONResponse({"detail": f"unknown endpoint: /api/{unmatched}"}, status_code=404)

    # ------------------------------------------------------------- static

    static = paths.static_dir()
    if static.exists():
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    else:  # pragma: no cover - static assets are optional at runtime
        @app.get("/")
        async def index() -> JSONResponse:
            return JSONResponse({"app": "mellowday", "message": "static assets not installed"})

    return app


app = create_app()
