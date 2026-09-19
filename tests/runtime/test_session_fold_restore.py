"""I23: folding and restarting a session must not destroy its raw record.

The runtime side of contract 6ter (docs/specs/CONTRACTS.md):

* the raw execution record is append-only and lives in its own file, so neither
  a folded context nor the runtime auto-save (which writes the folded message
  list over {session_id}.json) can change what was already recorded;
* after a fold, a *new* Agent restored from that session file still knows the
  folded state and can continue the task.

The model transport is a scripted in-process fake: no network, no credential.
"""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest

from mellowday import paths
from mellowday.personal_assistant.tools import execute_tool, tool_definitions
from mellowday.runtime import events
from mellowday.runtime import sessions as session_store
from mellowday.runtime.agent import Agent
from mellowday.storage.store import Store

API_BASE = "http://127.0.0.1:9/v1"
SESSION_ID = "fold-restore"

FOLD_REPLY = json.dumps(
    {
        "episode_memory": {
            "task_description": "用户要求整理当天的安排",
            "key_events": [{"step": "1", "description": "登记了一件待办", "outcome": "完成"}],
            "current_progress": "待办已登记，等待确认",
        },
        "working_memory": {
            "immediate_goal": "继续确认剩余安排",
            "current_challenges": "",
            "next_actions": [{"type": "planning", "description": "继续"}],
        },
        "tool_memory": {"tools_used": [], "derived_rules": []},
    },
    ensure_ascii=False,
)


# --- scripted transport ------------------------------------------------------


class _Chunk:
    def __init__(self, choices=None, usage=None) -> None:
        self.choices = choices or []
        self.usage = usage


class _Choice:
    def __init__(self, content=None, finish_reason=None, tool_calls=None) -> None:
        self.delta = NS(content=content, tool_calls=tool_calls)
        self.finish_reason = finish_reason


class _Function:
    def __init__(self, name=None, arguments="") -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, index, call_id, name, arguments) -> None:
        self.index = index
        self.id = call_id
        self.function = _Function(name, arguments)


class _Completions:
    """Streamed turns are consumed in order; non-streamed calls are side queries."""

    def __init__(self, turns, fold_reply: str) -> None:
        self._turns = list(turns)
        self.fold_reply = fold_reply
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs.get("stream"):
            text = self.fold_reply if int(kwargs.get("max_tokens") or 0) >= 6000 else ""
            return NS(choices=[NS(message=NS(content=text or ""), finish_reason="stop")])
        chunks = self._turns.pop(0) if self._turns else [_Chunk([_Choice("")])]

        async def gen():
            for chunk in chunks:
                yield chunk

        return gen()


class FakeOpenAI:
    def __init__(self, turns, fold_reply: str = FOLD_REPLY) -> None:
        self.completions = _Completions(turns, fold_reply)
        self.chat = NS(completions=self.completions)


def text_turn(text: str) -> list:
    return [
        _Chunk([_Choice(content=text)]),
        _Chunk(usage=NS(prompt_tokens=9, completion_tokens=5)),
        _Chunk([_Choice(finish_reason="stop")]),
    ]


def tool_turn(name: str, arguments: dict, *, call_id: str = "call_1") -> list:
    payload = json.dumps(arguments, ensure_ascii=False)
    return [
        _Chunk([_Choice(tool_calls=[_ToolCall(0, call_id, name, payload)])]),
        _Chunk(usage=NS(prompt_tokens=11, completion_tokens=5)),
        _Chunk([_Choice(finish_reason="tool_calls")]),
    ]


def make_agent(script: FakeOpenAI) -> Agent:
    agent = Agent(model="test-model", api_base=API_BASE, api_key="test-key")
    agent._openai_client = script
    agent.session_id = SESSION_ID
    # The learning loop runs in the background of a turn and is not what this
    # file is about; disabling it keeps the scripts deterministic.
    agent._online_evolution_enabled = lambda: False
    return agent


async def chat(agent: Agent, message: str) -> list[dict]:
    seen: list[dict] = []
    with events.use_sink(seen.append):
        await agent.chat(message)
    await agent.drain_background_skill_tasks()
    return seen


def text_of(seen: list[dict]) -> str:
    return "".join(event.get("text", "") for event in seen if event["type"] == "text_delta").strip()


# --- the record itself -------------------------------------------------------


def test_trace_appends_and_never_rewrites_earlier_entries():
    session_store.append_trace(SESSION_ID, session_store.trace_record("user", turn=1, text="第一轮"))
    first = session_store.trace_path(SESSION_ID).read_bytes()

    session_store.append_trace(
        SESSION_ID, session_store.trace_record("tool_result", turn=1, name="list_todos", result="ok")
    )
    second = session_store.trace_path(SESSION_ID).read_bytes()
    assert second.startswith(first), "appending must not rewrite what was there"

    # The runtime auto-save overwrites the whole session file: the record is not
    # part of it and must come through untouched.
    session_store.save_session(SESSION_ID, {"metadata": {"id": SESSION_ID}, "openaiMessages": []})
    assert session_store.trace_path(SESSION_ID).read_bytes() == second

    entries = session_store.read_trace(SESSION_ID)
    assert [entry["type"] for entry in entries] == ["user", "tool_result"]
    assert entries[0]["text"] == "第一轮", "Chinese text is written and read as UTF-8"
    assert entries[1]["name"] == "list_todos"
    assert all(entry["turn"] == 1 and entry["ts"] and entry["time"] for entry in entries)


def test_trace_lives_in_the_data_directory_and_numbering_keeps_counting():
    assert paths.data_dir() in session_store.trace_path(SESSION_ID).parents
    assert session_store.next_trace_turn(SESSION_ID) == 1

    session_store.append_trace(SESSION_ID, session_store.trace_record("user", turn=3, text="三"))
    session_store.append_trace(SESSION_ID, session_store.trace_record("message", turn=1, text="一"))
    assert session_store.next_trace_turn(SESSION_ID) == 4, "the highest turn wins"


def test_long_values_are_stored_complete_and_a_display_view_is_bounded():
    long_text = "开头" + "字" * 9000 + "结尾"
    record = session_store.trace_record("tool_result", turn=2, name="list_notes", result=long_text)

    # 原文完整保存：被截断过的工具结果 JSON 已经不是可解析的 JSON，记录必须留住原文。
    assert record["result"] == long_text
    assert record["result_length"] == len(long_text)
    assert record["result_preview"] == long_text[:200]
    assert "truncated" not in record

    # 展示用有界视图与原文分开：视图短，记录不动。
    view = session_store.trace_entry_for_display(record)
    assert len(view["result"]) <= session_store.TRACE_TEXT_LIMIT + 40
    assert view["result"].startswith("开头") and view["result"].endswith("结尾")
    assert view["result_length"] == len(long_text)
    assert view["display_shortened"] == ["result"]
    assert record["result"] == long_text, "展示视图不得改动记录本身"
    assert session_store.trace_for_display([record]) == [view]

    short = session_store.trace_record("tool_result", turn=2, name="list_notes", result="短")
    assert short["result"] == "短"
    assert "truncated" not in short
    assert "result_length" not in short


def test_long_tool_arguments_stay_parsable_json():
    arguments = {"title": "七点复习", "detail": "说" * 6000, "meta": {"kind": "note"}}
    record = session_store.trace_record("tool_call", turn=1, name="create_note", arguments=arguments)

    assert json.loads(record["arguments"]) == arguments
    assert record["arguments_length"] > 6000
    assert record["arguments_preview"] == record["arguments"][:200]


def test_tool_arguments_are_stored_as_json_text():
    record = session_store.trace_record(
        "tool_call", turn=1, name="create_todo", arguments={"title": "七点复习"}
    )
    assert json.loads(record["arguments"]) == {"title": "七点复习"}


def test_reading_tolerates_damaged_lines_and_deletion_removes_the_file():
    session_store.append_trace(SESSION_ID, session_store.trace_record("user", turn=1, text="一"))
    with session_store.trace_path(SESSION_ID).open("a", encoding="utf-8") as handle:
        handle.write("{ not json\n\n")
    session_store.append_trace(SESSION_ID, session_store.trace_record("user", turn=2, text="二"))

    assert [entry["text"] for entry in session_store.read_trace(SESSION_ID)] == ["一", "二"]

    assert session_store.delete_trace(SESSION_ID) is True
    assert not session_store.trace_path(SESSION_ID).exists()
    assert session_store.read_trace(SESSION_ID) == []
    assert session_store.delete_trace(SESSION_ID) is False


# --- folding + restart continuity -------------------------------------------


@pytest.mark.anyio
async def test_a_new_agent_restored_after_a_fold_can_continue():
    script = FakeOpenAI([text_turn("已经加入待办。"), text_turn("还有一件事。")])
    agent = make_agent(script)

    await chat(agent, "帮我把七点复习加入待办")
    await chat(agent, "还有别的吗")
    assert "帮我把七点复习加入待办" in json.dumps(agent._openai_messages, ensure_ascii=False)

    await agent.compact()
    assert len(agent._openai_messages) == 2, "folding replaced the raw message list"
    assert "<session-folded-memory>" in agent._openai_messages[1]["content"]
    assert agent._folded_session_memories

    agent._auto_save()
    saved = session_store.load_session(SESSION_ID)
    saved_text = json.dumps(saved, ensure_ascii=False)
    assert "<session-folded-memory>" in saved_text
    assert "帮我把七点复习加入待办" not in saved_text, "the folded list replaced the raw messages"

    # A new process: a fresh Agent restored from that session file.
    restored = make_agent(FakeOpenAI([text_turn("继续完成它。")]))
    assert restored is not agent
    restored.restore_session(saved)
    assert restored._folded_session_memories, "the folded memory was restored"
    assert "<session-folded-memory>" in json.dumps(restored._openai_messages, ensure_ascii=False)

    seen = await chat(restored, "接着做")
    assert text_of(seen) == "继续完成它。", "the restored session can still finish a turn"

    sent = restored._openai_client.completions.calls[-1]["messages"]
    assert any("<session-folded-memory>" in json.dumps(item, ensure_ascii=False) for item in sent)
    assert any(item.get("role") == "user" and item.get("content") == "接着做" for item in sent)


# --- a fold is only "verified" when the remaining task still completes ------


FOLD_WITH_A_REMAINING_GOAL = json.dumps(
    {
        "episode_memory": {
            "task_description": "用户要把几件安排放进待办",
            "key_events": [{"step": "1", "description": "已加入「交周报」", "outcome": "完成"}],
            "current_progress": "还有一项没有加：预约体检",
        },
        "working_memory": {
            "immediate_goal": "继续把「预约体检」加入待办",
            "current_challenges": "用户要求不要改动已经有的待办",
            "next_actions": [{"type": "planning", "description": "用 create_todo 加体检，别碰已有记录"}],
        },
        "tool_memory": {"tools_used": ["create_todo"], "derived_rules": []},
    },
    ensure_ascii=False,
)


def make_tool_agent(turns, executor):
    """A scripted agent whose tools really run against a Store."""
    agent = Agent(
        model="test-model",
        api_base=API_BASE,
        api_key="test-key",
        custom_tools=tool_definitions(),
        tool_executor=executor,
    )
    agent._openai_client = FakeOpenAI(turns, fold_reply=FOLD_WITH_A_REMAINING_GOAL)
    agent.session_id = SESSION_ID
    agent._online_evolution_enabled = lambda: False
    return agent


@pytest.mark.anyio
async def test_a_fold_then_restart_keeps_goal_constraint_parameters_and_the_write():
    """A fold is only proved by the rest of the task: the remaining goal, the
    constraint the user stated, the tool parameters and the final stored result.

    A scripted model that only returns a fixed answer cannot show any of that, so
    this test drives real business tools against a real Store, folds, restarts
    from the session file and then completes the remaining item.
    """
    store = Store()
    wrote: list[tuple[str, dict]] = []

    async def executor(name, arguments):
        wrote.append((name, dict(arguments)))
        return await execute_tool(store, name, arguments)

    agent = make_tool_agent(
        [
            tool_turn("create_todo", {"title": "交周报", "detail": "带上数据", "due_at": "2026-09-20T09:00:00+08:00"}),
            text_turn("已经加好了。"),
            text_turn("好，我只加这一条。"),
        ],
        executor,
    )
    await chat(agent, "把「交周报」加到待办，周三上午九点前")
    await chat(agent, "还有一件：预约体检。注意不要改动我已经有的待办。")

    before = store.list_records("todos")
    assert [(record["title"], record["detail"]) for record in before] == [("交周报", "带上数据")]

    await agent.compact()
    agent._auto_save()
    saved = session_store.load_session(SESSION_ID)

    restored = make_tool_agent(
        [
            tool_turn("create_todo", {"title": "预约体检", "due_at": "2026-09-21T10:00:00+08:00"}, call_id="call_2"),
            text_turn("体检也加好了。"),
        ],
        executor,
    )
    restored.restore_session(saved)
    seen = await chat(restored, "接着把剩下那件也加上")

    # 1) 折叠状态里带着剩余目标与用户约束，模型不是靠猜
    sent = json.dumps(restored._openai_client.completions.calls[0]["messages"], ensure_ascii=False)
    assert "预约体检" in sent and "不要改动已经有的待办" in sent
    # 2) 重启后的工具调用参数原样到达业务层
    assert wrote[-1] == ("create_todo", {"title": "预约体检", "due_at": "2026-09-21T10:00:00+08:00"})
    # 3) 业务结果：两条都在，且折叠前那条没有被改动
    after = store.list_records("todos")
    assert sorted(record["title"] for record in after) == ["交周报", "预约体检"]
    kept = next(record for record in after if record["title"] == "交周报")
    assert kept["detail"] == "带上数据" and kept["due_at"] == before[0]["due_at"]
    added = next(record for record in after if record["title"] == "预约体检")
    assert added["due_at"] == "2026-09-21T02:00:00+00:00", "本地 10:00 按 UTC 存储"
    # 4) 收尾回复来自这一轮，不是折叠前那句固定答案
    assert text_of(seen) == "体检也加好了。"
