"""E: a long tool result is saved complete, and the model can get it back.

The runtime used to cut a tool result off at 30 KB and hand the model a path it
had no tool to read; the raw record cut every field at 4000 characters, so a
long tool result was not even parseable JSON any more. Now:

* the complete text is written to data_dir()/tool_results/<session>/<ref>.txt;
* the conversation carries a bounded placeholder with that ref;
* the runtime offers a read_tool_result tool that pages through the original or
  jumps to a passage - scoped to the artifacts of this one session, with no
  parameter that could name a path, so arbitrary file reads stay removed;
* folding, auto-saving and restarting never overwrite the artifact.

The transport is a scripted in-process fake: no network, no credential.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace as NS

import pytest

from mellowday import paths
from mellowday.runtime import events
from mellowday.runtime import sessions as session_store
from mellowday.runtime.agent import Agent

API_BASE = "http://127.0.0.1:9/v1"
SESSION_ID = "art-session"
MARKER = "中部目标-9F3A"

NOTE_DEF = {"name": "list_notes", "description": "x", "input_schema": {"type": "object"}}


def huge_payload() -> str:
    """A JSON tool result big enough to be persisted (>30 KB) with a marker inside."""
    rows = [f"row-{index:04d}" for index in range(4000)]
    return json.dumps({"records": rows[:2000] + [MARKER] + rows[2000:]}, ensure_ascii=False)


# --- scripted OpenAI-compatible transport ------------------------------------


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
    """Turns are consumed in order; an entry may be a callable of the request."""

    def __init__(self, turns) -> None:
        self._turns = list(turns)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs.get("stream"):
            return NS(choices=[NS(message=NS(content=""), finish_reason="stop")])
        item = self._turns.pop(0) if self._turns else text_turn("")
        if callable(item):
            item = item(kwargs)

        async def _gen():
            for chunk in item:
                yield chunk

        return _gen()


class FakeOpenAI:
    def __init__(self, turns) -> None:
        self.completions = _Completions(turns)
        self.chat = NS(completions=self.completions)


def text_turn(text: str = "好的"):
    return [
        _Chunk([_Choice(_Delta(content=text))]),
        _Chunk(usage=_Usage(9, 5)),
        _Chunk([_Choice(_Delta(), finish_reason="stop")]),
    ]


def tool_turn(name: str, arguments, call_id: str = "call_1"):
    payload = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
    return [
        _Chunk([_Choice(_Delta(tool_calls=[_ToolCall(0, call_id, name, payload)]))]),
        _Chunk([_Choice(_Delta(), finish_reason="tool_calls")]),
        _Chunk(usage=_Usage(20, 6)),
    ]


def make_agent(turns, *, session_id=SESSION_ID, custom_tools=None, tool_executor=None) -> Agent:
    agent = Agent(
        model="test-model",
        api_base=API_BASE,
        api_key="test-key",
        custom_tools=custom_tools,
        tool_executor=tool_executor,
    )
    agent._openai_client = FakeOpenAI(turns)
    agent.session_id = session_id
    # The learning loop runs in the background of a turn and is not what this
    # file is about; disabling it keeps the scripts deterministic.
    agent._online_evolution_enabled = lambda: False
    return agent


async def _run(agent: Agent, message: str) -> list[dict]:
    seen: list[dict] = []
    with events.use_sink(seen.append):
        await agent.chat(message)
    await agent.drain_background_skill_tasks()
    return seen


def _artifact_files():
    return sorted((paths.data_dir() / "tool_results").glob("*/*.txt"))


def _ref_from_messages(messages) -> str:
    """The only way a test model learns a ref: it reads the placeholder."""
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            match = re.search(r'ref "([A-Za-z0-9_-]+)"', content)
            if match:
                return match.group(1)
    raise AssertionError("the placeholder never offered a ref to the model")


# --- the placeholder and the artifact ----------------------------------------


@pytest.mark.anyio
async def test_a_huge_tool_result_is_saved_complete_and_shown_as_a_reference():
    big = huge_payload()
    calls: list[str] = []

    async def executor(name, arguments):
        calls.append(name)
        return big

    agent = make_agent(
        [tool_turn("list_notes", {}), text_turn("读完了。")],
        custom_tools=[NOTE_DEF],
        tool_executor=executor,
    )
    seen = await _run(agent, "把笔记都列出来")

    result = next(event for event in seen if event["type"] == "tool_result")
    assert "Result too large" in result["result"]
    files = _artifact_files()
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == big, "原文完整保存"
    assert paths.data_dir() in files[0].parents

    ref = files[0].stem
    assert f'ref "{ref}"' in result["result"]
    assert "read_tool_result" in result["result"]

    # The conversation only carries the bounded placeholder, not the 40 KB result.
    tool_message = [m for m in agent._openai_messages if m.get("role") == "tool"][-1]
    assert len(tool_message["content"]) < len(big) / 2
    assert calls == ["list_notes"]


@pytest.mark.anyio
async def test_the_model_can_retrieve_and_use_a_target_from_the_middle():
    big = huge_payload()
    calls: list[str] = []

    async def executor(name, arguments):
        calls.append(name)
        return big

    def retrieval_turn(request):
        # A real model does exactly this: it reads the ref out of the placeholder.
        ref = _ref_from_messages(request["messages"])
        return tool_turn("read_tool_result", {"ref": ref, "query": MARKER}, call_id="call_2")

    agent = make_agent(
        [tool_turn("list_notes", {}), retrieval_turn, text_turn("找到了：中部目标。")],
        custom_tools=[NOTE_DEF],
        tool_executor=executor,
    )
    seen = await _run(agent, "把笔记都列出来，找到中部目标那一条")

    results = [event for event in seen if event["type"] == "tool_result"]
    assert [event["name"] for event in results] == ["list_notes", "read_tool_result"]
    read_back = json.loads(results[1]["result"])
    assert read_back["ok"] is True
    assert MARKER in read_back["text"]
    assert read_back["match_offset"] > len(big) // 3, "目标在长结果中部，不是开头"
    assert len(read_back["text"]) < len(big) // 2, "只返回目标附近的一段窗口"

    # 「并使用」：取回的内容进入下一轮请求，模型据此作答
    sent = json.dumps(agent._openai_client.completions.calls[-1]["messages"], ensure_ascii=False)
    assert MARKER in sent
    reply = "".join(event.get("text", "") for event in seen if event["type"] == "text_delta")
    assert reply.strip() == "找到了：中部目标。"

    # 取回工具由运行时执行（会话作用域），不会被当成业务工具转发出去
    assert calls == ["list_notes"]


@pytest.mark.anyio
async def test_the_large_result_event_carries_the_reference_structurally():
    """下游（原始记录 / 历史界面）不得靠正则从占位文案里抠 ref。"""
    big = huge_payload()

    async def executor(name, arguments):
        return big

    agent = make_agent(
        [tool_turn("list_notes", {}), text_turn("读完了。")],
        custom_tools=[NOTE_DEF],
        tool_executor=executor,
    )
    seen = await _run(agent, "把笔记都列出来")
    result = next(event for event in seen if event["type"] == "tool_result")

    assert result["truncated"] is True
    assert result["chars"] == len(big)
    assert result["preview"] == big[:400]
    assert result["ref"] and result["ref"] not in ("", None)
    # 结构化 ref 直接可用，不需要解析 result 文本
    outcome = json.loads(agent._read_tool_result({"ref": result["ref"], "limit": 500}))
    assert outcome["ok"] is True and outcome["text"] == big[:500]
    assert f'ref "{result["ref"]}"' in result["result"], "占位文案里仍然给模型 ref"


@pytest.mark.anyio
async def test_a_small_result_event_carries_no_structured_fields():
    async def executor(name, arguments):
        return '{"ok": true, "count": 0, "records": []}'

    agent = make_agent(
        [tool_turn("list_notes", {}), text_turn("读完了。")],
        custom_tools=[NOTE_DEF],
        tool_executor=executor,
    )
    seen = await _run(agent, "把笔记都列出来")
    result = next(event for event in seen if event["type"] == "tool_result")

    assert result["result"] == '{"ok": true, "count": 0, "records": []}'
    assert not {"ref", "chars", "preview", "truncated"} & set(result)


@pytest.mark.anyio
async def test_paging_walks_the_whole_result_and_is_reachable_through_the_tool():
    big = huge_payload()
    ref = session_store.save_tool_artifact(SESSION_ID, "list_notes", big)["ref"]

    chunks: list[str] = []
    offset = 0
    while True:
        outcome = session_store.read_tool_artifact(SESSION_ID, ref, offset=offset, limit=4096)
        assert outcome["ok"] is True
        assert outcome["total_chars"] == len(big)
        chunks.append(outcome["text"])
        if not outcome["has_more"]:
            assert outcome["next_offset"] is None
            break
        assert outcome["next_offset"] > offset
        offset = outcome["next_offset"]
    assert "".join(chunks) == big, "分页可以取回完整原文"

    agent = make_agent([text_turn("好的。")])
    first = json.loads(agent._read_tool_result({"ref": ref, "offset": 0, "limit": 1000}))
    assert first["ok"] is True and first["returned"] == 1000
    assert first["text"] == big[:1000]
    beyond = json.loads(agent._read_tool_result({"ref": ref, "offset": len(big) + 10}))
    assert beyond["ok"] is True and beyond["text"] == "" and beyond["has_more"] is False
    missing = json.loads(agent._read_tool_result({"ref": ref, "query": "不存在的内容"}))
    assert missing["ok"] is False and missing["error"] == "not_found"


@pytest.mark.anyio
async def test_a_ref_can_only_reach_this_sessions_own_artifacts():
    mine = session_store.save_tool_artifact(SESSION_ID, "list_notes", "自己的产物")["ref"]
    other = session_store.save_tool_artifact("other-session", "list_notes", "别人的产物")["ref"]

    assert session_store.read_tool_artifact(SESSION_ID, mine)["text"] == "自己的产物"
    foreign = session_store.read_tool_artifact(SESSION_ID, other)
    assert foreign["ok"] is False and foreign["error"] == "unknown_ref"

    agent = make_agent([text_turn("好的。")])
    for bad_ref in (
        "../../../mellowday.sqlite3",
        "..",
        "C:\\Windows\\win.ini",
        "/etc/passwd",
        "mellowday.sqlite3",
        "art/../secret",
        "",
        "a" * 300,
        other,
    ):
        outcome = json.loads(agent._read_tool_result({"ref": bad_ref}))
        assert outcome["ok"] is False, bad_ref
    # 合法但不存在 / 别的会话的 ref，都不会读到任何内容
    assert json.loads(agent._read_tool_result({"ref": mine, "limit": "1000"}))["text"] == "自己的产物"


@pytest.mark.anyio
async def test_fold_autosave_and_restart_leave_the_artifact_untouched():
    big = huge_payload()

    async def executor(name, arguments):
        return big

    agent = make_agent(
        [tool_turn("list_notes", {}), text_turn("读完了。")],
        custom_tools=[NOTE_DEF],
        tool_executor=executor,
    )
    await _run(agent, "把笔记都列出来")
    files = _artifact_files()
    assert len(files) == 1
    ref = files[0].stem
    before = files[0].read_bytes()

    await agent.compact()
    agent._auto_save()

    assert files[0].read_bytes() == before, "折叠与自动保存都不改写工具产物"
    saved = session_store.load_session(SESSION_ID)
    assert saved["metadata"]["id"] == SESSION_ID

    # A new process: a fresh Agent restored from the session file, same id.
    restored = make_agent([text_turn("继续。")])
    restored.restore_session(saved)
    outcome = json.loads(restored._read_tool_result({"ref": ref, "limit": 5000}))
    assert outcome["ok"] is True
    assert outcome["text"] == big[:5000]
    assert files[0].read_bytes() == before


@pytest.mark.anyio
async def test_the_read_tool_is_offered_to_the_model_without_a_path_parameter():
    agent = make_agent([text_turn("好的。")])
    await _run(agent, "你好")

    sent_tools = agent._openai_client.completions.calls[-1]["tools"]
    definition = next(
        tool for tool in sent_tools if tool["function"]["name"] == "read_tool_result"
    )["function"]
    assert set(definition["parameters"]["properties"]) == {"ref", "offset", "limit", "query"}
    assert definition["parameters"]["required"] == ["ref"]
    assert not [key for key in definition["parameters"]["properties"] if "path" in key or "file" in key]
    assert "read_tool_result" in [tool["name"] for tool in agent.tools]
