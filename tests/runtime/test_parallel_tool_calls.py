"""Regression: one round with several tool calls must run each exactly once.

A real-model session died with HTTP 400 (duplicate tool_call_id) and the tool
results arrived cumulatively: one, then two, then three. Cause: the
batch/execute block sat *inside* the per-tool-call loop, so every iteration
reprocessed all tool calls seen so far. With N calls in a round the tools ran
1+2+...+N times - duplicate writes to the user's data - and the same
tool_call_id was appended repeatedly, which the API rejects permanently.

The same structure exists in the reference implementation, so this is an
inherited defect rather than a port regression.
"""
from __future__ import annotations

import json

import pytest

from test_agent_runtime import (  # pytest puts this directory on sys.path
    _Choice,
    _Chunk,
    _Delta,
    _ToolCall,
    _Usage,
    make_agent,
    _run,
)


def multi_tool_turn(calls, prompt_tokens=20, completion_tokens=6):
    """One assistant round that requests several tools at once."""
    tool_calls = [
        _ToolCall(index, call_id, name, args)
        for index, (call_id, name, args) in enumerate(calls)
    ]
    return [
        _Chunk([_Choice(_Delta(tool_calls=tool_calls))]),
        _Chunk([_Choice(_Delta(), finish_reason="tool_calls")]),
        _Chunk(usage=_Usage(prompt_tokens, completion_tokens)),
    ]


def text_turn(text):
    return [
        _Chunk([_Choice(_Delta(content=text))]),
        _Chunk([_Choice(_Delta(), finish_reason="stop")]),
    ]


TOOL_DEF = {"name": "create_todo", "description": "x", "input_schema": {"type": "object"}}
NOTE_DEF = {"name": "create_note", "description": "y", "input_schema": {"type": "object"}}

THREE_CALLS = [
    ("call_a", "create_todo", '{"title": "A"}'),
    ("call_b", "create_todo", '{"title": "B"}'),
    ("call_c", "create_todo", '{"title": "C"}'),
]


@pytest.mark.anyio
async def test_each_tool_in_a_parallel_round_runs_exactly_once():
    executed: list[str] = []

    async def executor(name, arguments):
        executed.append(name)
        return json.dumps({"ok": True, "name": name})

    agent = make_agent(
        turns=[multi_tool_turn(THREE_CALLS), text_turn("done")],
        custom_tools=[TOOL_DEF],
        tool_executor=executor,
    )
    await _run(agent, "add three todos")

    assert sorted(executed) == ["create_todo"] * 3, f"tools ran {len(executed)} times: {executed}"


@pytest.mark.anyio
async def test_tool_messages_have_unique_ids_and_match_the_calls():
    async def executor(name, arguments):
        return json.dumps({"ok": True})

    agent = make_agent(
        turns=[multi_tool_turn(THREE_CALLS), text_turn("done")],
        custom_tools=[TOOL_DEF],
        tool_executor=executor,
    )
    await _run(agent, "add three todos")

    tool_messages = [m for m in agent._openai_messages if m.get("role") == "tool"]
    ids = [m["tool_call_id"] for m in tool_messages]
    assert len(ids) == 3, f"expected one tool message per call, got {len(ids)}: {ids}"
    assert len(set(ids)) == len(ids), f"duplicate tool_call_id sent to the API: {ids}"
    assert set(ids) == {"call_a", "call_b", "call_c"}


@pytest.mark.anyio
async def test_two_calls_produce_exactly_two_tool_events():
    async def executor(name, arguments):
        return json.dumps({"ok": True})

    calls = [
        ("call_a", "create_todo", '{"title": "A"}'),
        ("call_b", "create_note", '{"title": "B"}'),
    ]
    agent = make_agent(
        turns=[multi_tool_turn(calls), text_turn("done")],
        custom_tools=[TOOL_DEF, NOTE_DEF],
        tool_executor=executor,
    )
    seen = await _run(agent, "add a todo and a note")
    results = [e for e in seen if e["type"] == "tool_result"]
    assert len(results) == 2, f"tool results re-emitted cumulatively: {len(results)}"
