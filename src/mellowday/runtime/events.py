"""Structured event bridge between the runtime and its callers.

The runtime was written against a terminal UI layer. Every user-visible message
that used to be printed now flows through this module as a structured event, so
a web request, a test or a CLI can all consume the same stream.

Callers install a sink with :func:`use_sink` (or `set_sink`/`reset_sink`) before
invoking the agent. Sinks are held in a :class:`contextvars.ContextVar`, so an
`asyncio` task created inside `Agent.chat` inherits the sink of the caller and
two concurrent sessions never see each other's events.

Event payloads always contain a `type` key. No event carries credentials.

Besides the conversation events listed in docs/specs/CONTRACTS.md section 3, this
module defines the learning-loop events (I24, contract 6quinquies):

    skill_candidate_proposed, skill_candidate_applied, skill_write_denied,
    skill_candidate_failed, skill_candidate_skipped

They are emitted through :func:`emit_skill_event` and describe exactly what
happened to one online skill candidate, so a denied, skipped or failed write can
never disappear silently. See :data:`LEARNING_EVENT_TYPES` for each payload.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Callable, Iterator

Event = dict[str, Any]
EventSink = Callable[[Event], None]

_sink: contextvars.ContextVar[EventSink | None] = contextvars.ContextVar(
    "mellowday_event_sink", default=None
)


def set_sink(sink: EventSink | None):
    """Install a sink for the current context; returns a token for `reset_sink`."""
    return _sink.set(sink)


def reset_sink(token) -> None:
    _sink.reset(token)


def current_sink() -> EventSink | None:
    return _sink.get()


@contextmanager
def use_sink(sink: EventSink | None) -> Iterator[None]:
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


def emit(event: Event) -> None:
    """Deliver one event to the active sink. Never raises into the runtime."""
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # a broken consumer must not break a conversation
        pass


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


# --------------------------------------------------------------------------
# Learning-loop events (I24)
# --------------------------------------------------------------------------
# The online skill learning loop must never drop a candidate silently. Every
# step of one write attempt is reported with a structured event whose payload
# carries a skill name and a short human-readable reason - never a credential.
#
#   skill_candidate_proposed  {skill, action, summary}
#       A candidate reached the write step. When a confirmer is available this
#       is followed by the caller's own `confirmation` event (the web layer adds
#       the one-shot token); the runtime deliberately does not emit a second,
#       token-less confirmation, because the web client can only answer the one
#       that carries a token.
#   skill_candidate_applied   {skill, action}
#       The write really happened: action "add" created a skill, "merge" evolved
#       an existing one (repeated feedback therefore does not append a new skill
#       on every turn).
#   skill_write_denied        {skill, action, reason, summary}
#       Nothing was written: the user refused (`reason="user_denied"`), there was
#       nobody to ask (`reason="no_confirmer"`), the confirmation itself failed
#       (`reason="confirm_error:..."`), or the permission mode forbids the write
#       (`reason="permission_mode:..."`).
#   skill_candidate_failed    {skill, action, reason}
#       Extracting or writing the candidate raised, or the skills package
#       reported a failure; the conversation itself is unaffected.
#   skill_candidate_skipped   {skill, stage, reason}
#       The pipeline stopped before a write: evolution disabled, plan mode, no
#       conversation window, no model client, skills package unavailable, or the
#       candidate was discarded as having no durable value.

LEARNING_EVENT_TYPES = (
    "skill_candidate_proposed",
    "skill_candidate_applied",
    "skill_write_denied",
    "skill_candidate_failed",
    "skill_candidate_skipped",
)
"""The event types added for the learning loop (docs/specs/CONTRACTS.md 6quinquies)."""


def skill_event(
    kind: str,
    *,
    skill: object = "",
    action: object = "",
    reason: object = "",
    summary: object = "",
    stage: object = "",
) -> Event:
    """Build one learning-loop event.

    Empty fields are omitted so a consumer can tell "not applicable" from an
    empty value; every text value is bounded and coerced to safe UTF-8.
    """
    event: Event = {"type": kind}
    for key, value in (
        ("skill", skill),
        ("action", action),
        ("reason", reason),
        ("summary", summary),
        ("stage", stage),
    ):
        text = _safe_text(value).strip()
        if text:
            event[key] = text[:400]
    return event


def emit_skill_event(
    kind: str,
    *,
    skill: object = "",
    action: object = "",
    reason: object = "",
    summary: object = "",
    stage: object = "",
) -> None:
    """Emit one learning-loop event; never raises into the runtime."""
    emit(
        skill_event(
            kind, skill=skill, action=action, reason=reason, summary=summary, stage=stage
        )
    )


# --------------------------------------------------------------------------
# Tool presentation helpers (kept from the original UI layer)
# --------------------------------------------------------------------------

_ICONS = {
    "skill": "S",
    "skill_create": "+",
    "skill_evolve": "~",
    "compact_context": "C",
}


def tool_icon(name: str) -> str:
    return _ICONS.get(name, "*")


def tool_summary(name: str, inp: dict) -> str:
    if not isinstance(inp, dict):
        return ""
    for key in ("summary", "title", "name", "query", "text", "kind"):
        value = inp.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:120]
    for key, value in inp.items():
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            return f"{key}={str(value)[:100]}"
    return ""


# --------------------------------------------------------------------------
# Terminal-compatible surface, now backed by events
# --------------------------------------------------------------------------


def print_assistant_text(text: str) -> None:
    emit({"type": "text_delta", "text": _safe_text(text)})


def print_tool_call(name: str, inp: dict) -> None:
    emit({"type": "tool_start", "name": name, "arguments": inp if isinstance(inp, dict) else {}})


def print_tool_result(name: str, result: str) -> None:
    emit({"type": "tool_result", "name": name, "result": _safe_text(result)})


def print_file_change_result(name: str, result: str) -> None:
    emit({"type": "tool_result", "name": name, "result": _safe_text(result)})


def print_error(msg: object) -> None:
    emit({"type": "error", "message": _safe_text(msg)})


def print_warning(msg: object) -> None:
    emit({"type": "warning", "message": _safe_text(msg)})


def print_info(msg: object) -> None:
    emit({"type": "notice", "message": _safe_text(msg)})


def print_confirmation(command: str) -> None:
    emit({"type": "confirmation", "summary": _safe_text(command)})


def print_divider() -> None:
    emit({"type": "turn_end"})


def print_retry(attempt: int, max_retries: int, reason: str) -> None:
    emit({"type": "retry", "attempt": attempt, "max_retries": max_retries, "reason": _safe_text(reason)})


def print_cost(input_tokens: int, output_tokens: int) -> None:
    emit({"type": "token_usage", "input": int(input_tokens), "output": int(output_tokens)})


def print_sub_agent_start(agent_type: str, description: str) -> None:
    emit({"type": "subagent_start", "agent_type": _safe_text(agent_type), "description": _safe_text(description)})


def print_sub_agent_end(agent_type: str, description: str) -> None:
    emit({"type": "subagent_end", "agent_type": _safe_text(agent_type), "description": _safe_text(description)})


def print_welcome() -> None:
    emit({"type": "notice", "message": "MellowDay ready"})


def print_user_prompt() -> None:
    emit({"type": "prompt"})


def print_goodbye() -> None:
    emit({"type": "notice", "message": "Session closed"})


def print_interrupted() -> None:
    emit({"type": "notice", "message": "Interrupted"})


def print_plan_for_approval(plan_content: str) -> None:
    emit({"type": "plan", "content": _safe_text(plan_content)})


def print_plan_approval_options() -> None:
    emit({"type": "plan_options"})


def print_memory_entries(memories: list) -> None:
    emit({"type": "memory_list", "entries": [_safe_text(m) for m in memories]})


def print_skill_entries(skills: list) -> None:
    emit({"type": "skill_list", "entries": [getattr(s, "name", _safe_text(s)) for s in skills]})


def start_spinner(label: str = "Thinking") -> None:
    emit({"type": "busy_start", "label": _safe_text(label)})


def stop_spinner() -> None:
    emit({"type": "busy_end"})


# Backwards-compatible private aliases used by the ported UI helpers.
def _print_file_change_result(name: str, result: str) -> None:
    print_file_change_result(name, result)


def _get_tool_icon(name: str) -> str:
    return tool_icon(name)


def _get_tool_summary(name: str, inp: dict) -> str:
    return tool_summary(name, inp)
