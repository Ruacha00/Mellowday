"""Session lifecycle and turn execution for the web layer.

One SessionState owns exactly one runtime agent. A session runs one turn at a
time (a per-session lock), while different sessions run concurrently; that is
what keeps conversation state isolated and reproducible.

Three lifecycle rules are enforced here (see docs/specs/CONTRACTS.md 6bis):

* a turn is only started while the session lock is held, and the execution task
  is always finished before that lock is released - a client that disconnects
  must never leave a runtime running behind the next turn;
* the lock is also the point where the turn re-checks that its session still
  exists: a request that waited behind a running turn while the session was
  deleted is answered instead of executed, so nothing resurrects the session;
* session ids are validated at this boundary before they are ever joined into a
  path, and deleting a session removes every trace of it;
* the model configuration is re-read at the start of every turn and adopted by
  the existing agent without touching its history or tools.

Two more contracts live here.

The raw execution record (docs/specs/CONTRACTS.md 6ter) is written next to the
display history as an append-only JSONL file, one line per user message,
assistant text, tool call, tool result and error. Context folding rewrites the
runtime message list and the runtime auto-saves that folded list over
`{id}.json`; neither touches the record, so the original conversation stays
replayable after a fold - and the web history surface reads it through
:meth:`SessionRegistry.trace`.

Background learning writes are reaped before the event stream of a turn is
closed, because the learner asks the user for confirmation *after* the model has
finished. Draining earlier than that would make every confirmation and every
skill_candidate_* event invisible.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from mellowday import config, paths
from mellowday.runtime import events
from mellowday.runtime import sessions as session_store
from mellowday.storage.store import Store

CONFIRMATION_TIMEOUT_SECONDS = 300.0
"""How long a turn waits for the user to answer a confirmation prompt."""

MESSAGE_FLUSH_CHARS = 256
"""Assistant text produced in a turn is appended to the raw trace in chunks of
at least this size, so a long answer is durable while it streams instead of
only appearing once the turn ends."""

SKILL_DRAIN_TIMEOUT_SECONDS = 60.0
"""How long a finished turn keeps its event stream open for the background
learning writes. The write needs the user to click a confirmation that only
reaches the browser while the stream is alive, so the window has to survive a
human decision - but it is also the window in which the SSE response is still
open, so it must stay well under the usual client/proxy idle timeout."""

TURN_ABORTED_MESSAGE = "本轮已中断"
"""Client-facing message for a turn that was stopped instead of finishing."""

SESSION_DROPPED_MESSAGE = "会话已删除，本轮未执行"
"""Client-facing message for a turn that was queued while its session was deleted.

The deletion wins: the queued turn is answered instead of run, so it cannot call
the model, reach a business tool, or write a session file back into existence.
"""

SKILL_DRAIN_NOTICE = "习惯学习仍在等待确认，本轮先结束；未确认的写入不会生效。"
"""Shown when a background learning write outlived the drain window."""

logger = logging.getLogger(__name__)

TURN_REAP_TIMEOUT_SECONDS = 15.0
"""Upper bound for waiting on an execution task that is being stopped."""

SESSION_ID_MAX_LENGTH = 64
SESSION_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,%d}\Z" % SESSION_ID_MAX_LENGTH)

_TRACE_KIND_BY_ROLE = {"user": "user", "assistant": "assistant"}
"""Display-history roles that also describe a raw-record entry.

Keeping the mapping here means a history write and its trace entry are produced
by the same call: there is no second path that could drift.
"""


class InvalidSessionId(ValueError):
    """A client-supplied session id cannot be used as a path element."""


def new_session_id() -> str:
    """Generate an id that always satisfies SESSION_ID_PATTERN."""
    return uuid.uuid4().hex[:12]


def is_valid_session_id(session_id: object) -> bool:
    return isinstance(session_id, str) and SESSION_ID_PATTERN.fullmatch(session_id) is not None


def validate_session_id(session_id: object) -> str:
    """Return session_id if it is safe to join into a path, else raise.

    Allowed: [A-Za-z0-9_-], 1-64 characters. None and the empty string mean
    "start a new session" and are *not* valid path elements: callers must
    generate one with new_session_id() (or use resolve_session_id()).
    """
    if not is_valid_session_id(session_id):
        raise InvalidSessionId(
            "invalid session id: only [A-Za-z0-9_-]{1,%d} is allowed" % SESSION_ID_MAX_LENGTH
        )
    return str(session_id)


def resolve_session_id(session_id: object) -> str:
    """None/empty mean "new session"; anything else must already be valid."""
    if session_id is None or session_id == "":
        return new_session_id()
    return validate_session_id(session_id)


def model_config_fingerprint(cfg: config.ModelConfig) -> tuple[Any, ...]:
    """Everything about a model config that changes how a request is sent."""
    return (
        cfg.model,
        cfg.api_base or "",
        cfg.api_key or "",
        bool(cfg.thinking),
        cfg.max_turns,
    )


def _build_openai_client(cfg: config.ModelConfig) -> Any:
    import os

    import openai

    # OpenAI-compatible endpoints often run locally and need no key, but the
    # SDK insists on a non-empty value.
    return openai.AsyncOpenAI(
        base_url=cfg.api_base,
        api_key=cfg.api_key or os.environ.get("OPENAI_API_KEY") or "not-required",
    )


def _build_anthropic_client(cfg: config.ModelConfig) -> Any:
    import anthropic

    kwargs: dict[str, Any] = {}
    if cfg.api_key:
        kwargs["api_key"] = cfg.api_key
    return anthropic.AsyncAnthropic(**kwargs)


def _ensure_system_message(agent: Any, use_openai: bool) -> None:
    """Keep a protocol switch usable: the target message list needs its prompt."""
    if not use_openai:
        return
    messages = getattr(agent, "_openai_messages", None)
    if not isinstance(messages, list) or messages:
        return
    prompt = getattr(agent, "_system_prompt", "") or ""
    if prompt:
        messages.append({"role": "system", "content": prompt})


def apply_model_config(agent: Any, cfg: config.ModelConfig | None = None) -> bool:
    """Adopt the current model configuration on an already-built agent.

    Returns True when the agent actually changed. Only model/credential fields
    are touched: the conversation history, the tool list and every other runtime
    state stay exactly as they were. The transport client is rebuilt only when
    the endpoint or the credentials changed, so an unchanged config costs
    nothing (no reconnect, no new client).
    """
    if cfg is None:
        cfg = config.load_model_config()
    fingerprint = model_config_fingerprint(cfg)
    previous = getattr(agent, "_mellowday_model_config", None)
    if previous == fingerprint:
        return False

    use_openai = bool(cfg.api_base)
    rebuild_client = (
        previous is None
        or bool(getattr(agent, "use_openai", use_openai)) != use_openai
        or previous[1] != fingerprint[1]
        or previous[2] != fingerprint[2]
    )

    agent.model = cfg.model
    agent.thinking = bool(cfg.thinking)
    if hasattr(agent, "max_turns"):
        agent.max_turns = cfg.max_turns

    # Fields the runtime derives from the model at construction time.
    resolve_thinking = getattr(agent, "_resolve_thinking_mode", None)
    if callable(resolve_thinking):
        with contextlib.suppress(Exception):
            agent._thinking_mode = resolve_thinking()
    with contextlib.suppress(Exception):
        from mellowday.runtime.agent import _get_context_windows

        agent.effective_window = _get_context_windows(cfg.model) - 20000

    if rebuild_client:
        if use_openai:
            agent._openai_client = _build_openai_client(cfg)
            agent._anthropic_client = None
        else:
            agent._anthropic_client = _build_anthropic_client(cfg)
            agent._openai_client = None
        agent.use_openai = use_openai
        _ensure_system_message(agent, use_openai)

    agent._mellowday_model_config = fingerprint
    return True


def _caller_is_cancelled() -> bool:
    """True when *this* task is being cancelled (client gone), not the runner."""
    task = asyncio.current_task()
    counter = getattr(task, "cancelling", None)
    if not callable(counter):
        return True
    try:
        return bool(counter())
    except Exception:  # pragma: no cover - defensive
        return True


def _background_skill_tasks_pending(agent: Any) -> bool:
    """True while the runtime still has a background learning write in flight.

    The runtime exposes this as a property; a stand-in agent (tests, other
    front ends) may not have it at all, and a missing control must never turn
    into an exception on the turn path. Both spellings are accepted so a
    non-property attribute can never be mistaken for "still pending".
    """
    flag = getattr(agent, "has_pending_background_skill_tasks", False)
    if callable(flag):
        try:
            flag = flag()
        except Exception:  # pragma: no cover - a broken probe is not a turn error
            return False
    return bool(flag)


class ConfirmationBroker:
    """Holds pending confirmations until the web client answers them.

    A confirmation token can be consumed exactly once; a repeated answer is a
    no-op instead of re-running the guarded operation.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}

    def open(self, summary: str) -> tuple[str, asyncio.Future]:
        token = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[token] = future
        return token, future

    def resolve(self, token: str, approved: bool) -> bool:
        future = self._pending.pop(token, None)
        if future is None or future.done():
            return False
        future.set_result(bool(approved))
        return True

    def discard(self, token: str) -> None:
        future = self._pending.pop(token, None)
        if future is not None and not future.done():
            future.cancel()

    def cancel_all(self) -> None:
        for token in list(self._pending):
            self.discard(token)

    def pending(self) -> list[str]:
        return list(self._pending)


@dataclass
class SessionState:
    session_id: str
    agent: Any
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    confirmations: ConfirmationBroker = field(default_factory=ConfirmationBroker)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    title: str = ""
    #: The turn currently executing for this session (None when idle).
    current_task: asyncio.Task | None = None
    #: Set when the session was deleted; a late turn must not write history back.
    dropped: bool = False
    #: Highest turn number already written to the raw execution record. It is
    #: seeded from that file, so numbering keeps counting across a restart.
    turn_seq: int = 0
    memory_turn: Any = None


class SessionRegistry:
    """Creates, restores, serves and deletes conversation sessions."""

    def __init__(
        self,
        *,
        store: Store | None = None,
        agent_factory: Callable[..., Any] | None = None,
        sessions_dir: Path | None = None,
    ) -> None:
        self.store = store if store is not None else Store()
        self._agent_factory = agent_factory
        self._sessions: dict[str, SessionState] = {}
        self._dir = sessions_dir or paths.sessions_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        from mellowday.personal_assistant.schedule import ScheduleService
        self.schedule = ScheduleService(self.store, session_exists=self.exists)

    # ---------------------------------------------------------------- agents

    def _factory(self) -> Callable[..., Any]:
        if self._agent_factory is not None:
            return self._agent_factory
        return build_agent

    async def _tool_executor(self, name: str, arguments: dict) -> str:
        from mellowday.personal_assistant.tools import execute_tool

        return await execute_tool(self.store, name, arguments)

    async def _session_tool_executor(self, state: SessionState, name: str, arguments: dict) -> str:
        if state.dropped:
            return json.dumps({"ok": False, "error": "session_deleted"})
        if name == "remember_fact":
            if state.memory_turn is None:
                return json.dumps({"ok": False, "error": "no_active_memory_turn"})
            # Never trust the main model's proposed content: it has history.
            # The separate evaluator sees only this turn's original user text.
            return json.dumps(await state.memory_turn.process(), ensure_ascii=False)
        if name in {"update_memory", "forget_memory"}:
            return json.dumps({"ok": False, "error": "settings_only",
                               "message": "请在设置中的记忆管理修改或删除条目。"}, ensure_ascii=False)
        from mellowday.personal_assistant import schedule_tools
        if name in {t["name"] for t in schedule_tools.tool_definitions()}:
            return await schedule_tools.execute_tool(self.schedule, name, arguments,
                                                     session_id=state.session_id, emit=events.emit)
        return await self._tool_executor(name, arguments)

    def get(self, session_id: str | None) -> SessionState:
        """Return the session for session_id, creating it when needed.

        None/empty start a new server-generated session. An invalid id is
        rejected here - before any agent, file or directory is created.
        """
        sid = resolve_session_id(session_id)
        existing = self._sessions.get(sid)
        if existing is not None:
            return existing
        state = SessionState(session_id=sid, agent=None)  # type: ignore[arg-type]
        # Continue the numbering of an existing raw record instead of starting
        # over: after a restart the file is the only memory of earlier turns.
        state.turn_seq = max(0, session_store.next_trace_turn(sid) - 1)
        state.agent = self._factory()(
            session_id=sid,
            store=self.store,
            tool_executor=lambda name, arguments: self._session_tool_executor(state, name, arguments),
        )
        state.title = self._load_history_title(sid)
        self._sessions[sid] = state
        return state

    def peek(self, session_id: str) -> SessionState | None:
        """Live state for a valid id, without creating a session."""
        return self._sessions.get(validate_session_id(session_id))

    def exists(self, session_id: str) -> bool:
        """True when the session has live state or a display history."""
        sid = validate_session_id(session_id)
        if sid in self._sessions:
            return True
        return bool(self._read_history(sid))

    # ------------------------------------------------------------- deletion

    def drop(self, session_id: str) -> bool:
        """Delete a session: memory, pending confirmations, running turn, files.

        Returns True when anything was found and removed. The in-flight turn (if
        any) is cancelled and tombstoned so it cannot write history back after
        the deletion.
        """
        sid = validate_session_id(session_id)
        state = self._sessions.pop(sid, None)
        self.schedule.pause_session(sid)
        removed = state is not None
        if state is not None:
            self._stop_turn(state)
        if self._remove_files(sid):
            removed = True
        return removed

    async def adrop(self, session_id: str) -> bool:
        """Like drop(), but also waits until the running turn has stopped."""
        sid = validate_session_id(session_id)
        state = self._sessions.get(sid)
        task = state.current_task if state is not None else None
        removed = self.drop(sid)
        if task is not None and not task.done():
            await self._reap_runner(task, agent=state.agent if state is not None else None)
        # A turn that was mid-flight could still have written a file in between.
        if self._remove_files(sid):
            removed = True
        return removed

    def _stop_turn(self, state: SessionState) -> None:
        """Cancel the running turn and make sure it cannot come back."""
        state.dropped = True
        state.confirmations.cancel_all()
        with contextlib.suppress(Exception):
            state.agent.abort()
        task = state.current_task
        if task is not None and not task.done():
            task.cancel()

    def _session_files(self, session_id: str) -> list[Path]:
        """Every file that belongs to one session (display + runtime state)."""
        sid = validate_session_id(session_id)
        roots = [self._dir, paths.sessions_dir()]
        files: list[Path] = []
        for root in roots:
            for name in (
                f"{sid}.history.json",
                f"{sid}.json",
                f"{sid}.folded-memory.jsonl",
                f"{sid}.folded-memory.latest.json",
                f"{sid}{session_store.TRACE_SUFFIX}",
            ):
                files.append(root / name)
            for pattern in (f"{sid}.folded-memory*", f"{sid}.trace*"):
                with contextlib.suppress(OSError):
                    files.extend(sorted(root.glob(pattern)))
        unique: list[Path] = []
        for path in files:
            if path not in unique:
                unique.append(path)
        return unique

    def _remove_files(self, session_id: str) -> bool:
        """Delete every file of one session, tool artifacts included.

        The artifacts (CONTRACTS.md 6ter.1) live under
        data_dir()/tool_results/<session>/, outside the sessions directory, so
        the glob above can never see them: they are removed through the runtime
        helper that owns that layout - and whose name mapping is the only
        authoritative one - so a deleted session leaves no original behind.
        """
        removed = False
        for path in self._session_files(session_id):
            if not path.exists():
                continue
            try:
                path.unlink()
                removed = True
            except OSError:  # pragma: no cover - unreadable/occupied file
                continue
        if self._remove_tool_artifacts(session_id):
            removed = True
        return removed

    def _remove_tool_artifacts(self, session_id: str) -> bool:
        """Delete the tool artifacts of one session; True when one went away.

        The artifacts directory is checked before the runtime helper is called
        at all: deleting a session that never produced an artifact - or one that
        never existed - must not create an empty tool_results directory either.
        """
        if not (paths.data_dir() / session_store.ARTIFACT_DIR_NAME).is_dir():
            return False
        return bool(session_store.delete_tool_artifacts(session_id))

    async def _reap_runner(self, runner: asyncio.Task | None, *, agent: Any = None) -> None:
        """Make sure the execution task has really stopped before returning.

        This is the single place that guarantees the lifecycle rule: the session
        lock is never released while the runtime of the previous turn is still
        running. Our own cancellation is swallowed only to keep waiting - the
        task itself is left to settle.
        """
        if runner is None:
            return
        if not runner.done():
            if agent is not None:
                with contextlib.suppress(Exception):
                    agent.abort()
            runner.cancel()
        deadline = time.monotonic() + TURN_REAP_TIMEOUT_SECONDS
        while not runner.done() and time.monotonic() < deadline:
            try:
                await asyncio.wait({runner}, timeout=0.25)
            except asyncio.CancelledError:
                if runner.done():
                    break
                continue
            except Exception:  # pragma: no cover - defensive
                break
        if not runner.done():  # pragma: no cover - a runtime that refuses to stop
            logger.warning(
                "turn for session %s did not stop within %.1fs",
                getattr(agent, "session_id", "?"),
                TURN_REAP_TIMEOUT_SECONDS,
            )
        if runner.done() and not runner.cancelled():
            with contextlib.suppress(BaseException):
                runner.exception()

    # ------------------------------------------------------------- listing

    def list(self) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        try:
            found = sorted(
                self._dir.glob("*.history.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )
        except OSError:  # pragma: no cover - defensive
            found = []
        for path in found:
            sid = path.name[: -len(".history.json")]
            if not is_valid_session_id(sid):
                continue
            record = self._history_summary(sid)
            if record:
                seen[sid] = record
        for sid, state in self._sessions.items():
            record = seen.setdefault(sid, {"session_id": sid, "title": state.title, "messages": 0})
            record["active"] = True
        return list(seen.values())

    def history(self, session_id: str) -> list[dict[str, Any]]:
        """User/assistant display history, oldest first (unchanged semantics)."""
        return self._read_history(validate_session_id(session_id))

    def trace(self, session_id: str) -> list[dict[str, Any]]:
        """Raw execution record of a session, oldest first.

        This is the append-only side of the history (CONTRACTS.md 6ter): it also
        contains what the display history never had - tool calls, tool results
        and errors - and it survives context folding, because folding only ever
        rewrites the runtime message list. Deleting the session removes it.
        """
        return session_store.read_trace(validate_session_id(session_id))

    def session_detail(self, session_id: str) -> dict[str, Any]:
        """Payload of `GET /api/sessions/{id}`: history + raw record + view.

        `messages` keeps its old meaning exactly. The other two fields are the
        two paths CONTRACTS.md 6ter.1 keeps apart: `trace` is the *complete*
        record the history surface replays and is never shortened, while
        `trace_display` is its bounded twin for rendering - same entries, long
        values folded for reading, the stored record untouched. A reader that
        needs the original of a long tool result follows the structured `ref`
        its trace entry carries to the artifacts of the session.
        """
        sid = validate_session_id(session_id)
        trace = session_store.read_trace(sid)
        messages = self._read_history(sid)
        # Durable outbox is authoritative; project reports into the history view
        # instead of dual-writing files and risking duplicates after a restart.
        if self.exists(sid):
            for report in self.schedule.reports_for_session(sid):
                stamp = datetime.fromisoformat(report["created_at"]).timestamp()
                messages.append({"role": "assistant", "content": report["body"], "ts": stamp,
                                 "notification_id": report["id"]})
                trace.append(session_store.trace_record("assistant", text=report["body"],
                    ts=stamp, time=report["created_at"], notification_id=report["id"]))
            messages.sort(key=lambda item: item.get("ts", 0))
            trace.sort(key=lambda item: item.get("ts", 0))
        return {
            "session_id": sid,
            "messages": messages,
            "trace": trace,
            "trace_display": session_store.trace_for_display(trace),
            "active": sid in self._sessions,
        }

    # ------------------------------------------------------------------ turns

    async def run_turn(
        self, session_id: str | None, message: str, *, timeout: float = CONFIRMATION_TIMEOUT_SECONDS
    ) -> AsyncIterator[dict[str, Any]]:
        """Run one user turn, streaming runtime events as they happen.

        The session lock is held for the whole turn, so a session is strictly
        serial. The events travel through a queue, which means the HTTP
        generator yields each event the moment the runtime produces it instead
        of waiting for the model to finish.

        Whatever ends this generator early - the client disconnecting (the
        generator is closed), the response task being cancelled, or the session
        being deleted - the runtime task is cancelled and awaited before the
        lock is released, and the text produced so far still lands in the
        display history exactly once.

        The lock is also where a queued request learns that it lost its
        session: this turn may have been waiting behind another turn of the
        same session while that session was deleted, and it must not run
        afterwards - no model call, no business tool, no history or trace
        write, because any of those would rebuild a file the deletion just
        removed. Such a turn is answered with SESSION_DROPPED_MESSAGE.
        """
        from mellowday.web_app.stream import EventChannel

        try:
            state = self.get(session_id)
        except InvalidSessionId:
            raise
        except Exception as exc:  # construction failures must reach the client
            yield {"type": "error", "message": f"agent unavailable: {type(exc).__name__}: {exc}"}
            yield {"type": "done", "session_id": session_id or ""}
            return
        yield {"type": "session", "session_id": state.session_id}

        answer = message.strip()
        if not answer:
            yield {"type": "error", "message": "empty message"}
            yield {"type": "done", "session_id": state.session_id}
            return

        channel = EventChannel()
        text_parts: list[str] = []
        runner: asyncio.Task | None = None
        error_message: str | None = None
        errors_seen: list[str] = []
        turn = state.turn_seq

        async with state.lock:
            # Re-check the session under the lock, after any wait on it. This
            # section runs synchronously up to the point where the runner task
            # is created, so the check is authoritative: nothing can delete the
            # session between here and the first model/tool call.
            if state.dropped:
                yield {"type": "error", "message": SESSION_DROPPED_MESSAGE}
                yield {"type": "done", "session_id": state.session_id}
                return
            state.turn_seq += 1
            turn = state.turn_seq
            # Assistant text is buffered only to keep the trace readable: it is
            # flushed while it streams, never held back until the turn ends.
            text_buffer: list[str] = []
            buffered_chars = 0

            def flush_message(*, partial: bool) -> None:
                nonlocal buffered_chars
                if not text_buffer:
                    return
                chunk = "".join(text_buffer)
                text_buffer.clear()
                buffered_chars = 0
                self._append_trace(state, "message", turn=turn, text=chunk, partial=partial)

            def sink(event: dict[str, Any]) -> None:
                nonlocal buffered_chars
                kind = event.get("type")
                # Text is recorded while it is produced, not while the client
                # consumes it: a disconnect must not lose the part of the answer
                # that already exists.
                if kind == "text_delta":
                    chunk = str(event.get("text") or "")
                    text_parts.append(chunk)
                    text_buffer.append(chunk)
                    buffered_chars += len(chunk)
                    if buffered_chars >= MESSAGE_FLUSH_CHARS:
                        flush_message(partial=True)
                elif kind == "tool_start":
                    self._append_trace(
                        state,
                        "tool_call",
                        turn=turn,
                        name=event.get("name"),
                        arguments=event.get("arguments"),
                    )
                elif kind == "tool_result":
                    # CONTRACTS.md 6ter.2: a result the runtime shortened
                    # carries the reference of the artifact holding the
                    # original. The record hands those fields through, so no
                    # reader has to scrape the reference out of the
                    # placeholder text. A small result carries none of them,
                    # and trace_record drops absent values.
                    self._append_trace(
                        state,
                        "tool_result",
                        turn=turn,
                        name=event.get("name"),
                        result=event.get("result"),
                        ref=event.get("ref"),
                        chars=event.get("chars"),
                        preview=event.get("preview"),
                        truncated=event.get("truncated"),
                    )
                elif kind == "error":
                    error_text = str(event.get("message") or "")
                    errors_seen.append(error_text)
                    self._append_trace(
                        state, "error", turn=turn, message=error_text, phase="runtime"
                    )
                channel.sink(event)

            self._append_history(
                state, {"role": "user", "content": answer, "ts": time.time()}, turn=turn
            )

            async def confirm(summary: str) -> bool:
                token, future = state.confirmations.open(summary)
                sink(
                    {
                        "type": "confirmation",
                        "id": token,
                        "summary": summary,
                        "session_id": state.session_id,
                    }
                )
                try:
                    return await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError:
                    return False

            state.updated_at = time.time()
            with contextlib.suppress(Exception):
                state.agent.set_confirm_fn(confirm)

            warning = self._adopt_model_config(state)
            if warning:
                sink({"type": "warning", "message": warning})

            from mellowday.personal_assistant.turn_memory import TurnMemory
            query_builder = getattr(state.agent, "_build_side_query", None)
            side_query = query_builder(max_tokens=1200) if callable(query_builder) else None
            state.memory_turn = TurnMemory(self.store, state.session_id, turn, answer, side_query, confirm)
            reports = self.schedule.reports_for_session(state.session_id)[-3:]
            state.agent._scheduled_report_context = json.dumps(
                [{"sent_at": r["created_at"], "body": r["body"]} for r in reports], ensure_ascii=False) if reports else ""

            async def run() -> str | None:
                token = events.set_sink(sink)
                try:
                    result = await self._invoke(state, answer)
                    if result is None and not state.dropped and not getattr(state.agent, "_aborted", False):
                        memory = await state.memory_turn.process()
                        if memory.get("ok"):
                            sink({"type": "notice", "message": memory.get("message", "已更新记忆。"),
                                  "operation_id": memory.get("operation_id")})
                        if side_query is not None and not state.dropped and not getattr(state.agent, "_aborted", False):
                            from mellowday.personal_assistant.persona_adaptation import adapt_turn
                            try:
                                await adapt_turn(state.session_id, str(turn), answer, side_query)
                            except asyncio.CancelledError:
                                raise
                            except Exception:
                                logger.warning("Persona adaptation failed; previous version retained")
                    # The learning loop writes *after* the model is done, and it
                    # asks the user first. Reaping it here - while the sink, the
                    # channel and the confirmation broker are all still alive -
                    # is what makes a confirmation box reachable at all; doing
                    # it in the outer finally would be too late, because the
                    # channel is already closed by then.
                    await self._drain_background_learning(state, channel)
                    return result
                finally:
                    events.reset_sink(token)
                    channel.close()

            runner = asyncio.create_task(run())
            state.current_task = runner
            try:
                try:
                    async for event in channel:
                        yield event
                    error_message = await runner
                except GeneratorExit:
                    raise
                except asyncio.CancelledError:
                    if _caller_is_cancelled():
                        raise
                    error_message = TURN_ABORTED_MESSAGE
                except Exception as exc:  # pragma: no cover - defensive
                    error_message = f"{type(exc).__name__}: {exc}"
            finally:
                await self._reap_runner(runner, agent=state.agent)
                state.current_task = None
                state.memory_turn = None
                state.confirmations.cancel_all()
                # The committed reply is mirrored into the raw record from the
                # same call that writes the display history: one write point,
                # so the two can never disagree about what was shown.
                flush_message(partial=False)
                self._commit_turn(state, text_parts, turn=turn)
                state.updated_at = time.time()

            if error_message:
                if error_message not in errors_seen:
                    self._append_trace(
                        state, "error", turn=turn, message=error_message, phase="turn"
                    )
                yield {"type": "error", "message": error_message}
            yield {"type": "done", "session_id": state.session_id}

    def _adopt_model_config(self, state: SessionState) -> str | None:
        """Re-read the model settings at the start of a turn (I20).

        The agent keeps its history and tools; only the model and the credential
        fields are replaced. Returns a warning message when it could not be
        applied, so the client can see why the settings did not take effect.
        """
        try:
            apply_model_config(state.agent)
            return None
        except Exception as exc:
            return f"model config not applied: {type(exc).__name__}: {exc}"

    def _commit_turn(
        self, state: SessionState, text_parts: list[str], *, turn: int | None = None
    ) -> None:
        """Append the assistant reply of a finished (or cancelled) turn once."""
        if state.dropped:
            # The session was deleted while this turn was running.
            return
        reply = "".join(text_parts).strip()
        if not reply:
            return
        self._append_history(
            state, {"role": "assistant", "content": reply, "ts": time.time()}, turn=turn
        )
        if not state.title:
            state.title = reply[:40]

    async def _drain_background_learning(self, state: SessionState, channel: Any) -> None:
        """Let the learning loop finish inside the turn that produced it.

        The runtime schedules the online-skill write as a background task and
        only then asks the user to confirm it. If the turn ends first, the
        confirmation and every skill_candidate_* event are emitted into a closed
        stream and the user never sees the write happen.

        The drain never cancels the task (an unanswered confirmation simply
        keeps waiting for its own timeout) and never raises: a turn must not
        fail because learning could not finish. When the window closes with the
        task still pending, the client is told, so nothing disappears silently.
        """
        if state.dropped or _caller_is_cancelled():
            # The client is gone or the session was deleted: there is nobody to
            # confirm anything, and blocking here would only delay the reaper.
            return
        if not _background_skill_tasks_pending(state.agent):
            return
        drain = getattr(state.agent, "drain_background_skill_tasks", None)
        if not callable(drain):
            return
        try:
            # The runtime's drain returns None and never raises; whether it is
            # still pending afterwards is the only reliable signal, so it is
            # re-checked instead of trusting a return value.
            await drain(timeout=SKILL_DRAIN_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - learning must not break a turn
            logger.warning("background learning drain failed: %s: %s", type(exc).__name__, exc)
        if _background_skill_tasks_pending(state.agent):
            channel.sink({"type": "notice", "message": SKILL_DRAIN_NOTICE})

    async def _invoke(self, state: SessionState, message: str) -> str | None:
        try:
            await state.agent.chat(message)
            return None
        except asyncio.CancelledError:
            return TURN_ABORTED_MESSAGE
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    # ---------------------------------------------------------------- history

    def _history_path(self, session_id: str) -> Path:
        # Path building is only ever reached with a validated id.
        return self._dir / f"{validate_session_id(session_id)}.history.json"

    def _append_history(
        self, state: SessionState, record: dict[str, Any], *, turn: int | None = None
    ) -> None:
        """Append one display-history record and mirror it into the raw trace.

        The display history and the raw execution record are written from this
        single place, so the record can never claim a reply that was not shown
        (or the other way round). Both files are append-only.

        Like the trace, a deleted session accepts no further history: opening
        the file in "a" mode would recreate it, and the delete removed it on
        purpose.
        """
        if state.dropped:
            return
        session_id = state.session_id
        path = self._history_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        kind = _TRACE_KIND_BY_ROLE.get(str(record.get("role")))
        if kind:
            self._append_trace(state, kind, turn=turn, text=str(record.get("content") or ""))

    def _append_trace(
        self, state: SessionState, kind: str, *, turn: int | None = None, **fields: Any
    ) -> None:
        """Append one entry to the raw execution record (CONTRACTS.md 6ter).

        Nothing here ever rewrites, truncates or reorders what was already
        written, and a session that is being deleted accepts no further entries
        (otherwise a cancelled turn would resurrect the file the delete just
        removed).
        """
        if state.dropped:
            return
        session_store.append_trace(
            state.session_id, session_store.trace_record(kind, turn=turn, **fields)
        )

    def _read_history(self, session_id: str) -> list[dict[str, Any]]:
        path = self._history_path(session_id)
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return records

    def _load_history_title(self, session_id: str) -> str:
        for record in self._read_history(session_id):
            if record.get("role") == "assistant" and record.get("content"):
                return str(record["content"])[:40]
        return ""

    def _history_summary(self, session_id: str) -> dict[str, Any] | None:
        records = self._read_history(session_id)
        if not records:
            return None
        title = ""
        for record in records:
            if record.get("role") == "user" and record.get("content"):
                title = str(record["content"])[:40]
                break
        return {
            "session_id": session_id,
            "title": title,
            "messages": len(records),
            "updated_at": records[-1].get("ts"),
            "active": session_id in self._sessions,
        }


def build_agent(
    *,
    session_id: str,
    store: Store,
    tool_executor: Callable[[str, dict], Awaitable[str]],
) -> Any:
    """Construct a runtime agent for one web session."""
    from mellowday.personal_assistant.tools import build_fact_provider, tool_definitions
    from mellowday.personal_assistant.schedule_tools import tool_definitions as calendar_tools
    from mellowday.runtime.agent import Agent
    from mellowday.runtime.sessions import load_session

    validate_session_id(session_id)
    cfg = config.load_model_config()
    agent = Agent(
        model=cfg.model,
        api_base=cfg.api_base or None,
        api_key=cfg.api_key or None,
        thinking=cfg.thinking,
        max_turns=cfg.max_turns,
        custom_tools=[t for t in tool_definitions() if t["name"] not in {
            "update_memory", "forget_memory", "create_calendar_event", "update_calendar_event", "delete_calendar_event",
        }] + calendar_tools(),
        product_mode=True,
        tool_executor=tool_executor,
        # Facts come from the same SQLite store the business tools write to, so
        # "the assistant remembered it" and "the assistant used it" cannot drift
        # apart the way they did when recall scanned Markdown files.
        fact_provider=build_fact_provider(store),
    )
    agent.session_id = session_id
    agent._mellowday_model_config = model_config_fingerprint(cfg)
    saved = load_session(session_id)
    if isinstance(saved, dict):
        try:
            agent.restore_session(saved)
        except Exception:
            pass
    return agent
