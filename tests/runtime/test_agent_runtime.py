"""Agent loop tests driven by a fake OpenAI-compatible client.

Nothing here touches the network: agent._openai_client is replaced with an
object whose chat.completions.create returns a scripted async chunk stream.
"""
from __future__ import annotations

import pytest

from mellowday.runtime import events
from mellowday.runtime.agent import Agent

API_BASE = "http://127.0.0.1:9/v1"

CUSTOM_TOOLS = [
    {
        "name": "add_todo",
        "description": "Create a to-do item.",
        "input_schema": {
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
        },
    }
]


# --- fake OpenAI-compatible streaming client --------------------------------

class _Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Function:
    def __init__(self, name=None, arguments=None):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, index, id, name=None, arguments=""):
        self.index = index
        self.id = id
        self.function = _Function(name, arguments)


class _Delta:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _Choice:
    def __init__(self, delta, finish_reason=None):
        self.delta = delta
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choices=None, usage=None):
        self.choices = choices or []
        self.usage = usage


class _Completions:
    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self._turns.pop(0) if self._turns else text_turn("")
        async def _gen():
            for chunk in chunks:
                yield chunk
        return _gen()


class _Chat:
    def __init__(self, completions):
        self.completions = completions


class FakeOpenAI:
    def __init__(self, turns):
        self.completions = _Completions(turns)
        self.chat = _Chat(self.completions)


def text_turn(text, prompt_tokens=10, completion_tokens=4):
    return [
        _Chunk([_Choice(_Delta(content=text))]),
        _Chunk(usage=_Usage(prompt_tokens, completion_tokens)),
        _Chunk([_Choice(_Delta(), finish_reason="stop")]),
    ]


def tool_turn(name, arguments, call_id="call_1", prompt_tokens=20, completion_tokens=6):
    return [
        _Chunk([_Choice(_Delta(tool_calls=[_ToolCall(0, call_id, name, arguments)]))]),
        _Chunk([_Choice(_Delta(), finish_reason="tool_calls")]),
        _Chunk(usage=_Usage(prompt_tokens, completion_tokens)),
    ]


def make_agent(*, turns, custom_tools=None, tool_executor=None, max_turns=None):
    agent = Agent(
        model="test-model",
        api_base=API_BASE,
        api_key="test-key",
        custom_tools=custom_tools,
        tool_executor=tool_executor,
        max_turns=max_turns,
    )
    agent._openai_client = FakeOpenAI(turns)
    return agent


async def _run(agent, message):
    seen = []
    with events.use_sink(seen.append):
        await agent.chat(message)
    await agent.drain_background_skill_tasks()
    return seen


def _types(seen):
    return [event["type"] for event in seen]


# --- tests ------------------------------------------------------------------

def test_agent_imports_and_constructs():
    agent = Agent(model="test-model", api_base=API_BASE, api_key="test-key")
    assert agent.model == "test-model"
    assert agent.use_openai is True
    assert agent.get_token_usage() == {"input": 0, "output": 0}
    assert agent.tool_executor is None
    assert agent._custom_tool_names == set()


def test_agent_constructs_without_api_key():
    agent = Agent(model="test-model", api_base=API_BASE)
    assert agent._openai_client is not None


@pytest.mark.anyio
async def test_chat_emits_text_delta():
    agent = make_agent(turns=[text_turn("Hello there")])

    seen = await _run(agent, "hi")

    assert "text_delta" in _types(seen)
    text = "".join(e["text"] for e in seen if e["type"] == "text_delta")
    assert "Hello there" in text
    assert "turn_end" in _types(seen)
    assert "token_usage" in _types(seen)
    assert agent.get_token_usage() == {"input": 10, "output": 4}


@pytest.mark.anyio
async def test_custom_tool_is_routed_to_the_executor():
    calls = []

    async def executor(name, arguments):
        calls.append((name, arguments))
        return '{"ok": true, "id": "abc123"}'

    agent = make_agent(
        turns=[tool_turn("add_todo", '{"title": "buy milk"}'), text_turn("Done")],
        custom_tools=CUSTOM_TOOLS,
        tool_executor=executor,
    )

    seen = await _run(agent, "add a todo to buy milk")

    assert calls == [("add_todo", {"title": "buy milk"})]
    starts = [e for e in seen if e["type"] == "tool_start"]
    results = [e for e in seen if e["type"] == "tool_result"]
    assert starts and starts[0]["name"] == "add_todo"
    assert starts[0]["arguments"] == {"title": "buy milk"}
    assert results and results[0]["name"] == "add_todo"
    assert "abc123" in results[0]["result"]
    # The tool result is fed back to the model as a tool message.
    assert agent._openai_messages[-1]["role"] == "assistant"
    assert any(m.get("role") == "tool" for m in agent._openai_messages)


@pytest.mark.anyio
async def test_custom_tool_without_executor_falls_back_to_builtin_unknown():
    agent = make_agent(
        turns=[tool_turn("add_todo", '{"title": "x"}'), text_turn("ok")],
        custom_tools=CUSTOM_TOOLS,
    )

    seen = await _run(agent, "add a todo")

    results = [e for e in seen if e["type"] == "tool_result"]
    assert results and "Unknown tool: add_todo" in results[0]["result"]


@pytest.mark.anyio
async def test_unknown_tool_does_not_crash_the_turn():
    async def executor(name, arguments):  # never called: not a custom tool
        raise AssertionError("executor must not be called for a non-custom tool")

    agent = make_agent(
        turns=[tool_turn("mystery_tool", "{}"), text_turn("recovered")],
        custom_tools=CUSTOM_TOOLS,
        tool_executor=executor,
    )

    seen = await _run(agent, "do something odd")

    results = [e for e in seen if e["type"] == "tool_result"]
    assert results and "Unknown tool: mystery_tool" in results[0]["result"]
    assert "text_delta" in _types(seen)


@pytest.mark.anyio
async def test_max_turns_stops_the_tool_loop():
    calls = []

    async def executor(name, arguments):
        calls.append(name)
        return "ok"

    agent = make_agent(
        turns=[tool_turn("add_todo", "{}", "c1"), tool_turn("add_todo", "{}", "c2")],
        custom_tools=CUSTOM_TOOLS,
        tool_executor=executor,
        max_turns=1,
    )

    await _run(agent, "loop forever")

    assert agent.current_turns == 1
    assert calls == []
    assert len(agent._openai_client.chat.completions.calls) == 1


@pytest.mark.anyio
async def test_abort_ends_the_request_without_raising():
    calls = []
    agent = make_agent(
        turns=[tool_turn("add_todo", '{"title": "stop me"}'), text_turn("never reached")],
        custom_tools=CUSTOM_TOOLS,
    )

    async def executor(name, arguments):
        calls.append(name)
        agent.abort()
        return "ok"

    agent.tool_executor = executor

    seen = await _run(agent, "add a todo")

    assert calls == ["add_todo"]
    assert agent._aborted is True
    assert len(agent._openai_client.chat.completions.calls) == 1
    # chat() returned normally; only the first turn produced events.
    assert "text_delta" not in _types(seen)


def test_abort_without_active_request_is_safe():
    agent = Agent(model="test-model", api_base=API_BASE, api_key="test-key")
    agent.abort()
    assert agent._aborted is True
