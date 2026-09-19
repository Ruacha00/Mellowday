"""I23: the raw execution record survives folding, restarts and deletion.

Contract 6ter (docs/specs/CONTRACTS.md) requires the raw record of every turn -
user message, assistant text, tool call, tool result, error - to be appended to
its own file, independently of the runtime message list. Folding the context
replaces that list, and the runtime auto-saves the folded list over
{session_id}.json; neither may change or truncate the record. The record is what
the history surface replays, and it has to survive a process restart together
with the session it belongs to.

6ter.1 keeps the two paths apart: `trace` is that complete record, `trace_display`
is its bounded rendering twin, and the tool artifacts of a session belong to the
session lifecycle like every other file. 6ter.2 keeps a shortened result's
reference structured: the trace entry carries the ref of the artifact holding
the original, so no reader has to scrape it out of the placeholder text.

Every model call here goes through a scripted in-process transport: no network,
no real credential, no real model.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import httpx
import openai
import pytest

from mellowday import paths
from mellowday.runtime import events
from mellowday.runtime import sessions as session_store
from mellowday.storage.store import Store
from mellowday.web_app import service
from mellowday.web_app.app import create_app

API_BASE = "https://example.invalid/v1"
SESSION = "trace-1"

FOLD_REPLY = json.dumps(
    {
        "episode_memory": {
            "task_description": "用户在整理当天的待办与笔记",
            "key_events": [{"step": "1", "description": "登记了一件待办", "outcome": "完成"}],
            "current_progress": "待办与笔记都已登记",
        },
        "working_memory": {
            "immediate_goal": "确认登记结果",
            "current_challenges": "",
            "next_actions": [{"type": "tool_call", "description": "查询待办"}],
        },
        "tool_memory": {"tools_used": [], "derived_rules": []},
    },
    ensure_ascii=False,
)


# --- scripted OpenAI-compatible transport -----------------------------------


def _text_chunks(text: str):
    return [
        NS(usage=None, choices=[NS(delta=NS(content=char, tool_calls=None), finish_reason=None)])
        for char in text
    ]


def _tool_chunk(call_id: str, name: str, arguments: dict):
    call = NS(
        index=0,
        id=call_id,
        function=NS(name=name, arguments=json.dumps(arguments, ensure_ascii=False)),
    )
    return NS(usage=None, choices=[NS(delta=NS(content=None, tool_calls=[call]), finish_reason=None)])


def _final(finish: str, prompt_tokens: int = 11):
    return NS(
        usage=NS(prompt_tokens=prompt_tokens, completion_tokens=7),
        choices=[NS(delta=NS(content=None, tool_calls=None), finish_reason=finish)],
    )


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for chunk in self._chunks:
                yield chunk

        return gen()


class _Script:
    """One shared script: streamed turns plus every request the test can inspect."""

    def __init__(self, turns=None, fold_reply: str | None = None) -> None:
        self.turns = list(turns or [])
        self.fold_reply = fold_reply
        self.calls: list[dict] = []
        self.clients: list = []

    def streamed(self) -> list:
        return self.turns.pop(0) if self.turns else _text_chunks("")

    @property
    def messages_sent(self) -> list[dict]:
        return next(call["messages"] for call in reversed(self.calls) if call.get("stream"))


class _FakeCompletions:
    def __init__(self, script: _Script) -> None:
        self.script = script

    async def create(self, **kwargs):
        self.script.calls.append(kwargs)
        if not kwargs.get("stream"):
            # Side queries (folding, learning) are answered separately and never
            # consume a scripted conversation turn.
            text = self.script.fold_reply if int(kwargs.get("max_tokens") or 0) >= 6000 else ""
            return NS(choices=[NS(message=NS(content=text or ""), finish_reason="stop")])
        return _FakeStream(self.script.streamed())


class _FakeClient:
    def __init__(self, script: _Script, **kwargs) -> None:
        self.script = script
        self.kwargs = kwargs
        self.chat = NS(completions=_FakeCompletions(script))


@pytest.fixture
def scripted_model(monkeypatch):
    """Install a scripted transport as openai.AsyncOpenAI and return the script."""

    def install(script: _Script) -> _Script:
        def factory(**kwargs):
            client = _FakeClient(script, **kwargs)
            script.clients.append(client)
            return client

        monkeypatch.setattr(openai, "AsyncOpenAI", factory)
        monkeypatch.setenv("MELLOWDAY_API_KEY", "test-key")
        monkeypatch.setenv("MELLOWDAY_API_BASE", API_BASE)
        monkeypatch.setenv("MELLOWDAY_MODEL", "fake-model")
        # Learning runs in the background of a turn; disabling it keeps these
        # tests about the record, not about the learning loop.
        monkeypatch.setenv("MELLOWDAY_AUTO_SKILL_EVOLUTION", "0")
        return script

    return install


def make_registry(data_dir) -> service.SessionRegistry:
    return service.SessionRegistry(store=Store(data_dir=data_dir))


async def run_turn(registry, session_id: str, message: str) -> list[dict]:
    return [event async for event in registry.run_turn(session_id, message)]


def kinds(seen: list[dict]) -> list[str]:
    return [event["type"] for event in seen]


def entries(trace: list[dict], kind: str) -> list[dict]:
    return [entry for entry in trace if entry["type"] == kind]


def _two_working_turns() -> _Script:
    """Two turns, each with one business tool call, then a text answer."""
    return _Script(
        turns=[
            [_tool_chunk("c1", "create_todo", {"title": "七点复习"}), _final("tool_calls")],
            _text_chunks("已经加入待办。") + [_final("stop")],
            [_tool_chunk("c2", "create_note", {"title": "会议纪要", "detail": "三条"}), _final("tool_calls")],
            _text_chunks("笔记已保存。") + [_final("stop")],
            _text_chunks("待办还在。") + [_final("stop")],
        ],
        fold_reply=FOLD_REPLY,
    )


# --- 1. folding must not lose the original history ----------------------------


@pytest.mark.anyio
async def test_folding_keeps_every_pre_fold_turn_and_tool_call(tmp_path, scripted_model):
    script = scripted_model(_two_working_turns())
    registry = make_registry(tmp_path / "data")

    await run_turn(registry, SESSION, "帮我把七点复习加入待办")
    await run_turn(registry, SESSION, "把会议纪要记成笔记")

    agent = registry.peek(SESSION).agent
    assert len(agent._openai_messages) >= 9, "the runtime really accumulated a conversation"
    before_fold = registry.trace(SESSION)
    assert [entry["type"] for entry in before_fold] == [
        "user", "tool_call", "tool_result", "message", "assistant",
        "user", "tool_call", "tool_result", "message", "assistant",
    ]

    # Fold the context: the runtime message list is replaced by the summary.
    await agent.compact()
    summary = agent._openai_messages[1]["content"]
    assert "<session-folded-memory>" in summary
    assert len(agent._openai_messages) == 2, "folding replaced the raw messages"

    await run_turn(registry, SESSION, "待办还在吗")
    after_fold = registry.trace(SESSION)

    # Nothing that was already written may move, change or disappear.
    assert after_fold[: len(before_fold)] == before_fold
    assert len(after_fold) == len(before_fold) + 3

    users = entries(after_fold, "user")
    assert [entry["text"] for entry in users] == [
        "帮我把七点复习加入待办", "把会议纪要记成笔记", "待办还在吗",
    ]
    assert [entry["turn"] for entry in users] == [1, 2, 3]

    calls = entries(after_fold, "tool_call")
    results = entries(after_fold, "tool_result")
    assert [entry["name"] for entry in calls] == ["create_todo", "create_note"]
    assert [entry["turn"] for entry in calls] == [1, 2]
    assert json.loads(calls[0]["arguments"]) == {"title": "七点复习"}
    assert [entry["name"] for entry in results] == ["create_todo", "create_note"]
    assert json.loads(results[0]["result"])["ok"] is True
    assert json.loads(results[1]["result"])["ok"] is True

    # The summary belongs to the runtime, not to the record of what ran.
    assert not any("<session-folded-memory>" in json.dumps(entry, ensure_ascii=False) for entry in after_fold)

    # The auto-save really did overwrite the runtime session with the folded
    # list: the raw pre-fold text is gone from it and only the record keeps it.
    saved = session_store.load_session(SESSION)
    saved_text = json.dumps(saved, ensure_ascii=False)
    assert "<session-folded-memory>" in saved_text
    assert "帮我把七点复习加入待办" not in saved_text
    assert "把会议纪要记成笔记" not in saved_text
    assert "帮我把七点复习加入待办" in json.dumps(after_fold, ensure_ascii=False)

    # The display history is complete too, and its semantics did not change.
    history = registry.history(SESSION)
    assert [record["role"] for record in history] == ["user", "assistant"] * 3
    assert [record["content"] for record in history if record["role"] == "user"] == [
        "帮我把七点复习加入待办", "把会议纪要记成笔记", "待办还在吗",
    ]


@pytest.mark.anyio
async def test_the_automatic_fold_inside_a_turn_does_not_touch_the_record(tmp_path, scripted_model):
    """The reported failure mode: the fold happens mid-turn, the auto-save then
    writes the folded list over the session file - and the raw record of what
    ran before the fold has to be untouched by both."""
    huge = int(180000 * 0.9)
    scripted_model(
        _Script(
            turns=[
                [_tool_chunk("c1", "create_todo", {"title": "七点复习"}), _final("tool_calls")],
                _text_chunks("已经加入待办。") + [_final("stop")],
                [
                    _tool_chunk("c2", "create_note", {"title": "会议纪要"}),
                    _final("tool_calls", prompt_tokens=huge),
                ],
                _text_chunks("笔记也记下了。") + [_final("stop")],
            ],
            fold_reply=FOLD_REPLY,
        )
    )
    registry = make_registry(tmp_path / "data")
    await run_turn(registry, SESSION, "把七点复习加入待办")
    before = registry.trace(SESSION)

    await run_turn(registry, SESSION, "再记一条笔记")

    agent = registry.peek(SESSION).agent
    assert agent._folded_session_memories, "the runtime folded the context during the turn"
    assert len(agent._openai_messages) == 3, "system + folded summary + the answer of the folded turn"

    after = registry.trace(SESSION)
    assert after[: len(before)] == before, "the fold did not change one recorded entry"
    assert [entry["text"] for entry in entries(after, "user")] == ["把七点复习加入待办", "再记一条笔记"]
    assert [entry["name"] for entry in entries(after, "tool_call")] == ["create_todo", "create_note"]
    assert [entry["name"] for entry in entries(after, "tool_result")] == ["create_todo", "create_note"]

    saved_text = json.dumps(session_store.load_session(SESSION), ensure_ascii=False)
    assert "把七点复习加入待办" not in saved_text, "the auto-save replaced the raw messages"
    assert "把七点复习加入待办" in json.dumps(after, ensure_ascii=False), "the record still has them"


# --- 2. tool calls are visible in the record ----------------------------------


@pytest.mark.anyio
async def test_tool_call_and_result_are_recorded_verbatim(tmp_path, scripted_model):
    scripted_model(
        _Script(
            turns=[
                [_tool_chunk("c1", "create_todo", {"title": "七点复习"}), _final("tool_calls")],
                _text_chunks("已经加入待办。") + [_final("stop")],
            ]
        )
    )
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(store=store)

    seen = await run_turn(registry, SESSION, "把七点复习加入待办")
    streamed = next(event for event in seen if event["type"] == "tool_result")
    trace = registry.trace(SESSION)

    call = entries(trace, "tool_call")[0]
    assert call["name"] == "create_todo"
    assert call["turn"] == 1
    assert json.loads(call["arguments"]) == {"title": "七点复习"}

    result = entries(trace, "tool_result")[0]
    assert result["name"] == "create_todo"
    assert result["result"] == streamed["result"], "the record keeps what the turn really produced"
    payload = json.loads(result["result"])
    assert payload["ok"] is True
    assert store.get_record("todos", payload["id"])["title"] == "七点复习"
    assert "truncated" not in result

    message = entries(trace, "message")[0]
    assistant = entries(trace, "assistant")[0]
    assert message["text"].strip() == assistant["text"] == "已经加入待办。"
    assert [entry["type"] for entry in trace] == ["user", "tool_call", "tool_result", "message", "assistant"]
    assert all(entry["turn"] == 1 for entry in trace)


# --- 3. restart continuity after a fold ---------------------------------------


@pytest.mark.anyio
async def test_restart_after_a_fold_continues_and_keeps_the_record(tmp_path, scripted_model):
    script = scripted_model(
        _Script(
            turns=[
                [_tool_chunk("c1", "create_todo", {"title": "七点复习"}), _final("tool_calls")],
                _text_chunks("已经加入待办。") + [_final("stop")],
                _text_chunks("待办只有一件。") + [_final("stop")],
                _text_chunks("好的。") + [_final("stop")],
                _text_chunks("第二条是会议纪要。") + [_final("stop")],
            ],
            fold_reply=FOLD_REPLY,
        )
    )
    data_dir = tmp_path / "data"
    registry = service.SessionRegistry(store=Store(data_dir=data_dir))

    await run_turn(registry, SESSION, "帮我把七点复习加入待办")
    await run_turn(registry, SESSION, "还有别的吗")
    agent_before = registry.peek(SESSION).agent
    await agent_before.compact()
    await run_turn(registry, SESSION, "继续")  # the turn that auto-saves the folded list
    before_restart = registry.trace(SESSION)

    saved = session_store.load_session(SESSION)
    assert "<session-folded-memory>" in json.dumps(saved["openaiMessages"], ensure_ascii=False)

    # A new process: nothing survives except what is on disk.
    restarted = service.SessionRegistry(store=Store(data_dir=data_dir))
    agent_after = restarted.get(SESSION).agent
    assert agent_after is not agent_before
    assert agent_after._folded_session_memories, "the folded memory was restored"
    assert "<session-folded-memory>" in json.dumps(agent_after._openai_messages, ensure_ascii=False)

    seen = await run_turn(restarted, SESSION, "第二条是什么")
    assert kinds(seen)[-1] == "done"
    reply = "".join(event.get("text", "") for event in seen if event["type"] == "text_delta")
    assert "第二条是会议纪要" in reply

    sent = script.messages_sent
    assert any("<session-folded-memory>" in json.dumps(item, ensure_ascii=False) for item in sent)
    assert any(item.get("role") == "user" and item.get("content") == "第二条是什么" for item in sent)

    after_restart = restarted.trace(SESSION)
    assert after_restart[: len(before_restart)] == before_restart, "the record survived the restart"
    new_users = entries(after_restart, "user")
    assert [entry["turn"] for entry in new_users] == [1, 2, 3, 4], "numbering continued, it did not restart"
    assert new_users[-1]["text"] == "第二条是什么"


# --- 4. deleting a session removes the record --------------------------------


@pytest.mark.anyio
async def test_delete_removes_the_record_and_does_not_restore_it(tmp_path, scripted_model):
    scripted_model(
        _Script(
            turns=[
                [_tool_chunk("c1", "create_todo", {"title": "七点复习"}), _final("tool_calls")],
                _text_chunks("已经加入待办。") + [_final("stop")],
                _text_chunks("从头开始。") + [_final("stop")],
            ]
        )
    )
    data_dir = tmp_path / "data"
    registry = service.SessionRegistry(store=Store(data_dir=data_dir))
    await run_turn(registry, SESSION, "把七点复习加入待办")

    trace_file = session_store.trace_path(SESSION)
    assert trace_file.exists()
    assert registry.trace(SESSION), "the record exists before the deletion"

    assert await registry.adrop(SESSION) is True

    assert not trace_file.exists()
    assert registry.trace(SESSION) == []
    assert registry.history(SESSION) == []
    assert registry.exists(SESSION) is False
    assert not list(paths.sessions_dir().glob(f"{SESSION}*"))

    # Asking again - with a brand new registry, as a restarted process would -
    # must not bring anything back.
    restarted = service.SessionRegistry(store=Store(data_dir=data_dir))
    assert restarted.trace(SESSION) == []
    assert restarted.exists(SESSION) is False

    # Reusing the id starts a new record at turn 1 instead of reviving the old one.
    await run_turn(registry, SESSION, "从头开始")
    fresh = registry.trace(SESSION)
    assert [entry["turn"] for entry in fresh] == [1, 1, 1]
    assert fresh[0]["text"] == "从头开始"


# --- 5. long values are stored complete and shown bounded --------------------


class _TraceAgent:
    """A stand-in runtime emitting exactly the events the record consumes."""

    def __init__(self, result: str, text: str = "读完了。") -> None:
        self.result = result
        self.text = text
        self.session_id = ""
        self.confirm_fn = None

    def set_confirm_fn(self, fn) -> None:
        self.confirm_fn = fn

    def abort(self) -> None:
        pass

    async def chat(self, message: str) -> None:
        events.emit({"type": "tool_start", "name": "list_notes", "arguments": {"limit": 500}})
        events.emit({"type": "tool_result", "name": "list_notes", "result": self.result})
        events.emit({"type": "text_delta", "text": self.text})


def make_agent_registry(agent, data_dir) -> service.SessionRegistry:
    def factory(*, session_id, store, tool_executor):
        agent.session_id = session_id
        return agent

    return service.SessionRegistry(store=Store(data_dir=data_dir), agent_factory=factory)


@pytest.mark.anyio
async def test_oversized_tool_result_is_stored_complete_with_a_display_view(tmp_path):
    """6ter.1: the record keeps the whole result, the display view is bounded.

    The old contract shortened the stored value and marked it with
    result["truncated"]; that marker is gone on purpose. What has to hold now is
    the separation: the stored entry is complete, the display view is bounded,
    and looking at the view changes nothing.
    """
    long_result = "笔记开头-" + "A" * 12000 + "-笔记结尾"
    registry = make_agent_registry(_TraceAgent(long_result), tmp_path / "data")
    await run_turn(registry, "trace-long", "把笔记都列出来")

    stored = entries(registry.trace("trace-long"), "tool_result")[0]
    assert stored["result"] == long_result, "the record stores the whole value"
    assert stored["result_length"] == len(long_result)
    assert stored["result_preview"] == long_result[:200]
    assert "truncated" not in stored, "the record does not shorten anything"

    view = session_store.trace_entry_for_display(stored)
    assert len(view["result"]) <= session_store.TRACE_TEXT_LIMIT + 40
    assert view["result"].startswith("笔记开头-")
    assert view["result"].endswith("-笔记结尾")
    assert view["display_shortened"] == ["result"]
    assert stored["result"] == long_result, "showing an entry never changes the record"

    # A small result travels as it came, with no extra display fields.
    short = make_agent_registry(_TraceAgent("短结果"), tmp_path / "data2")
    await run_turn(short, "trace-short", "列一下")
    plain = entries(short.trace("trace-short"), "tool_result")[0]
    assert plain["result"] == "短结果"
    assert "truncated" not in plain
    assert "result_length" not in plain and "ref" not in plain
    assert session_store.trace_entry_for_display(plain)["result"] == "短结果"
    assert "display_shortened" not in session_store.trace_entry_for_display(plain)


@pytest.mark.anyio
async def test_a_long_json_tool_result_stays_parseable_in_the_record(tmp_path):
    """The reason the record stores the original: a folded copy is not JSON.

    A 4000-character head+tail preview of a JSON document no longer parses,
    which made the record useless as the source of truth. The stored value must
    stay parseable; only the display view may be a reading copy.
    """
    payload = {
        "notes": [
            {"id": index, "title": f"笔记{index}", "detail": "正文" * 40} for index in range(200)
        ]
    }
    long_json = json.dumps(payload, ensure_ascii=False)
    assert len(long_json) > session_store.TRACE_TEXT_LIMIT

    registry = make_agent_registry(_TraceAgent(long_json), tmp_path / "data")
    await run_turn(registry, "trace-json", "把笔记导出成 JSON")

    stored = entries(registry.trace("trace-json"), "tool_result")[0]
    assert json.loads(stored["result"]) == payload
    assert stored["result_length"] == len(long_json)

    view = session_store.trace_entry_for_display(stored)
    assert len(view["result"]) <= session_store.TRACE_TEXT_LIMIT + 40
    assert view["result"] != stored["result"]
    assert view["display_shortened"] == ["result"]


@pytest.mark.anyio
async def test_a_large_tool_result_carries_its_reference_into_the_record(tmp_path, scripted_model):
    """6ter.2 end to end: ref/chars/preview/truncated reach the trace entry.

    A real >30KB tool result makes the runtime store the original as an artifact
    and put the structured reference on the tool_result event. The record hands
    those fields through, so a history surface never has to scrape the reference
    out of the placeholder text - it can follow the ref to the original instead.
    """
    scripted_model(
        _Script(
            turns=[
                [_tool_chunk("c1", "list_notes", {"limit": 500}), _final("tool_calls")],
                _text_chunks("都读完了。") + [_final("stop")],
            ]
        )
    )
    store = Store(data_dir=tmp_path / "data")
    # ASCII payload: character count and byte count agree, so the record's
    # "chars" can be compared with the runtime's byte threshold directly.
    for index in range(80):
        store.create_record("notes", {"title": f"note{index}", "detail": "x" * 400})
    registry = service.SessionRegistry(store=store)

    await run_turn(registry, SESSION, "把所有笔记都列出来")

    entry = entries(registry.trace(SESSION), "tool_result")[0]
    assert entry["name"] == "list_notes"
    assert entry["truncated"] is True, "a shortened result says so on the event"
    assert entry["chars"] > 30 * 1024, "the original is over the inline threshold"
    assert entry["preview"], "the event carries a ready-made preview"
    assert entry["ref"] and "/" not in entry["ref"] and "\\" not in entry["ref"]
    assert entry["result"].startswith("[Result too large"), "result keeps its old meaning"

    # The structured reference really points at the whole original.
    read = session_store.read_tool_artifact(SESSION, entry["ref"], limit=200)
    assert read["ok"] is True
    assert read["total_chars"] == entry["chars"]
    assert read["text"] == str(entry["preview"])[:200]


@pytest.mark.anyio
async def test_the_reference_of_a_large_result_is_readable_over_http(tmp_path, scripted_model):
    """6ter.1 + 6ter.2 together: the trace's ref leads to the original over HTTP.

    The web surface follows the structured ref of a shortened result instead of
    scraping the placeholder text, so the restricted reference read has to serve
    the stored original - paged and bounded - from the session's own artifacts.
    """
    scripted_model(
        _Script(
            turns=[
                [_tool_chunk("c1", "list_notes", {"limit": 500}), _final("tool_calls")],
                _text_chunks("都读完了。") + [_final("stop")],
            ]
        )
    )
    store = Store(data_dir=tmp_path / "data")
    for index in range(30):
        store.create_record("notes", {"title": f"note{index}", "detail": "z" * 1200})
    registry = service.SessionRegistry(store=store)
    app = create_app(store=store, registry=registry)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test"
    ) as client:
        await run_turn(registry, SESSION, "把所有笔记都列出来")
        detail = (await client.get(f"/api/sessions/{SESSION}")).json()
        entry = entries(detail["trace"], "tool_result")[0]
        assert entry["truncated"] is True and entry["ref"]

        page = (
            await client.get(
                f"/api/sessions/{SESSION}/tool-results/{entry['ref']}", params={"limit": 300}
            )
        ).json()
        assert page["ok"] is True
        assert page["total_chars"] == entry["chars"], "the ref serves the whole original"
        assert page["text"] == str(entry["preview"])[:300]
        assert page["has_more"] is True
        assert page["text"] != entry["result"], "the placeholder is not the original"

        # The bounded display view keeps the reference, so a page can offer the
        # original without carrying it.
        display = entries(detail["trace_display"], "tool_result")[0]
        assert display["ref"] == entry["ref"]
        assert len(display["result"]) <= session_store.TRACE_TEXT_LIMIT + 80


@pytest.mark.anyio
async def test_oversized_assistant_text_is_stored_complete_too(tmp_path):
    registry = make_agent_registry(_TraceAgent("短", text="说明" * 4000), tmp_path / "data")
    await run_turn(registry, SESSION, "展开讲讲")

    message = entries(registry.trace(SESSION), "message")[0]
    assert message["text"] == "说明" * 4000, "streamed text is stored complete"
    assert message["text_length"] == 8000
    assert "truncated" not in message

    displayed = session_store.trace_entry_for_display(message)
    assert len(displayed["text"]) <= session_store.TRACE_TEXT_LIMIT + 8
    assert displayed["display_shortened"] == ["text"]
    assert message["text"] == "说明" * 4000, "the view never touches the record"

    # The reply committed to the display history is complete as well.
    committed = entries(registry.trace(SESSION), "assistant")[0]
    assert committed["text"] == "说明" * 4000


# --- 6. tool artifacts belong to the session lifecycle -----------------------


@pytest.mark.anyio
async def test_deleting_a_session_removes_its_tool_artifacts_only(tmp_path):
    """6ter.1: the artifact directory of a session goes with the session.

    Artifacts live under data_dir()/tool_results/<session>/, outside
    sessions_dir(), so deleting a session used to leave the originals of its long
    tool results behind. Deleting a session must leave nothing, and must not
    touch another session's artifacts either.
    """
    registry = make_agent_registry(_TraceAgent("短"), tmp_path / "data")
    await run_turn(registry, "keep", "先跑一轮")
    kept = session_store.save_tool_artifact("keep", "list_notes", "另一个会话的原文" * 200)
    await run_turn(registry, "doomed", "先跑一轮")
    gone = session_store.save_tool_artifact("doomed", "list_notes", "要删掉的原文" * 300)

    assert Path(gone["path"]).is_file() and Path(kept["path"]).is_file()
    assert session_store.read_tool_artifact("doomed", gone["ref"])["ok"] is True

    assert registry.drop("doomed") is True  # the synchronous deletion path
    assert not Path(gone["path"]).exists(), "the original must not outlive the session"
    assert not Path(gone["path"]).parent.exists(), "its artifact directory goes too"
    assert Path(kept["path"]).is_file(), "another session's artifacts must survive"
    failed = session_store.read_tool_artifact("doomed", gone["ref"])
    assert failed["ok"] is False
    assert failed["error"] == "unknown_ref"

    # adrop() cleans up through the same function.
    assert await registry.adrop("keep") is True
    assert not Path(kept["path"]).exists()
    assert not list((paths.data_dir() / session_store.ARTIFACT_DIR_NAME).glob("*/*.txt"))


@pytest.mark.anyio
async def test_deleting_a_session_without_artifacts_creates_nothing(tmp_path):
    """A deletion must not create the artifact directory as a side effect."""
    registry = make_agent_registry(_TraceAgent("短"), tmp_path / "data")
    root = paths.data_dir() / session_store.ARTIFACT_DIR_NAME
    assert not root.exists()

    assert registry.drop("never-existed") is False
    assert await registry.adrop("never-existed") is False
    assert not root.exists(), "an unknown session must not create anything"

    await run_turn(registry, "plain", "普通一轮")
    assert registry.drop("plain") is True
    assert not root.exists(), "a session without artifacts leaves no empty directory"


# --- the record is what the history surface reads ----------------------------


@pytest.mark.anyio
async def test_session_detail_carries_the_messages_unchanged_and_the_record(tmp_path, scripted_model):
    scripted_model(
        _Script(
            turns=[
                [_tool_chunk("c1", "create_todo", {"title": "七点复习"}), _final("tool_calls")],
                _text_chunks("已经加入待办。") + [_final("stop")],
            ]
        )
    )
    store = Store(data_dir=tmp_path / "data")
    registry = service.SessionRegistry(store=store)
    app = create_app(store=store, registry=registry)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test"
    ) as client:
        await run_turn(registry, SESSION, "把七点复习加入待办")
        detail = (await client.get(f"/api/sessions/{SESSION}")).json()

    # Backwards compatible: messages keeps its exact old meaning.
    assert [record["role"] for record in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][1]["content"] == "已经加入待办。"
    assert detail["active"] is True

    # The additive field is the raw record the history surface replays.
    payload = registry.session_detail(SESSION)
    assert payload["messages"] == detail["messages"]
    assert [entry["type"] for entry in payload["trace"]] == [
        "user", "tool_call", "tool_result", "message", "assistant",
    ]
    assert payload["trace"][1]["name"] == "create_todo"


@pytest.mark.anyio
async def test_session_detail_serves_the_raw_record_and_a_bounded_display_view(tmp_path):
    """6ter.1: trace stays complete, trace_display is its bounded twin."""
    long_result = "笔记开头-" + "C" * 12000 + "-笔记结尾"
    registry = make_agent_registry(_TraceAgent(long_result), tmp_path / "data")
    app = create_app(store=registry.store, registry=registry)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mellowday.test"
    ) as client:
        await run_turn(registry, SESSION, "把笔记都列出来")
        detail = (await client.get(f"/api/sessions/{SESSION}")).json()

    raw = entries(detail["trace"], "tool_result")[0]
    assert raw["result"] == long_result, "the web surface still gets the whole original"
    display = entries(detail["trace_display"], "tool_result")[0]
    assert display["result"] != raw["result"]
    assert "display shortened" in display["result"]
    assert len(display["result"]) <= session_store.TRACE_TEXT_LIMIT + 40
    assert display["display_shortened"] == ["result"]
    assert [entry["type"] for entry in detail["trace_display"]] == [
        entry["type"] for entry in detail["trace"]
    ], "both paths describe the same entries"

    # Rendering the view never rewrites what was stored.
    assert entries(registry.trace(SESSION), "tool_result")[0]["result"] == long_result


# --- background learning is reaped before the event stream closes -------------


class _LearningAgent:
    """A runtime whose background learning write is still in flight at the end."""

    def __init__(self, *, finishes: bool) -> None:
        self.pending = True
        self.finishes = finishes
        self.session_id = ""
        self.confirm_fn = None
        self.drain_calls: list[float | None] = []

    def set_confirm_fn(self, fn) -> None:
        self.confirm_fn = fn

    def abort(self) -> None:
        pass

    @property
    def has_pending_background_skill_tasks(self) -> bool:
        return self.pending

    async def drain_background_skill_tasks(self, timeout: float | None = None) -> None:
        self.drain_calls.append(timeout)
        # The learner asks the user from inside the drain: this event only
        # reaches the browser while the stream of the turn is still open.
        events.emit({"type": "notice", "message": "要把这条反馈记成习惯吗"})
        if self.finishes:
            self.pending = False

    async def chat(self, message: str) -> None:
        events.emit({"type": "text_delta", "text": "好的"})


@pytest.mark.anyio
async def test_background_learning_is_drained_inside_the_open_stream(tmp_path):
    agent = _LearningAgent(finishes=True)
    registry = make_agent_registry(agent, tmp_path / "data")

    seen = await run_turn(registry, SESSION, "以后都先问我一句")

    assert agent.drain_calls == [service.SKILL_DRAIN_TIMEOUT_SECONDS]
    assert kinds(seen) == ["session", "text_delta", "notice", "done"], "the learner reached the client"
    assert seen[-2]["message"] == "要把这条反馈记成习惯吗"
    assert service.SKILL_DRAIN_NOTICE not in json.dumps(seen, ensure_ascii=False)


@pytest.mark.anyio
async def test_learning_that_outlives_the_window_is_reported_not_silent(tmp_path):
    agent = _LearningAgent(finishes=False)
    registry = make_agent_registry(agent, tmp_path / "data")

    seen = await run_turn(registry, SESSION, "以后都先问我一句")

    assert agent.drain_calls == [service.SKILL_DRAIN_TIMEOUT_SECONDS]
    assert kinds(seen)[-1] == "done"
    notices = [event for event in seen if event["type"] == "notice"]
    assert notices[-1]["message"] == service.SKILL_DRAIN_NOTICE
    assert kinds(seen).index("notice") < kinds(seen).index("done")


@pytest.mark.anyio
async def test_turns_without_a_pending_learning_write_are_unchanged(tmp_path):
    class PlainAgent:
        def __init__(self) -> None:
            self.session_id = ""
            self.confirm_fn = None

        def set_confirm_fn(self, fn) -> None:
            self.confirm_fn = fn

        def abort(self) -> None:
            pass

        async def chat(self, message: str) -> None:
            events.emit({"type": "text_delta", "text": "好的"})

    plain = make_agent_registry(PlainAgent(), tmp_path / "data")
    reference = make_agent_registry(PlainAgent(), tmp_path / "data2")

    seen = await run_turn(plain, "trace-plain", "你好")
    expected = await run_turn(reference, "trace-reference", "你好")

    assert [event["type"] for event in seen] == [event["type"] for event in expected]
    assert kinds(seen) == ["session", "text_delta", "done"]
    assert "notice" not in kinds(seen)


@pytest.mark.anyio
async def test_a_runtime_error_is_recorded_in_the_turn(tmp_path):
    class ExplodingAgent:
        def __init__(self) -> None:
            self.session_id = ""
            self.confirm_fn = None

        def set_confirm_fn(self, fn) -> None:
            self.confirm_fn = fn

        def abort(self) -> None:
            pass

        async def chat(self, message: str) -> None:
            raise RuntimeError("model exploded")

    registry = make_agent_registry(ExplodingAgent(), tmp_path / "data")
    seen = await run_turn(registry, SESSION, "你好")

    assert "error" in kinds(seen)
    errors = entries(registry.trace(SESSION), "error")
    assert [entry["message"] for entry in errors] == ["RuntimeError: model exploded"]
    assert errors[0]["turn"] == 1
