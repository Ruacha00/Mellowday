"""学习写入的确认接线与可见性（I24b，契约 6quinquies）。

测试驱动的是**真实的运行时学习回路**：假模型客户端 + 假 side_query + 隔离数据目录，
技能文件的落盘与「合并而非追加」由 skills 包负责。断言焦点是运行时的接线：

* 有 confirm_fn 且同意 -> 写入生效，并发出 skill_candidate_applied；
* 有 confirm_fn 且拒绝 -> 不写入，并发出 skill_write_denied（带原因）；
* 没有 confirm_fn     -> 不写入、不抛异常，拒绝同样可见；
* 同一候选连续出现     -> 合并/演化（技能数量不增长）；
* 写入抛错            -> 发出 skill_candidate_failed，回合本身不受影响；
* drain 之后没有后台任务残留。

离线：不读真实 .env、不发网络请求。
"""
from __future__ import annotations

import asyncio
import json

import pytest

from mellowday.runtime import events
from mellowday.runtime.agent import Agent
from mellowday.runtime.skills import discover_skills, get_skill_by_name, reset_skill_cache

API_BASE = "http://127.0.0.1:9/v1"

CANDIDATE = {
    "name": "brief-answers",
    "description": "Prefer short direct answers",
    "when_to_use": "answering a question",
    "instructions": "Keep the answer short and skip preamble.",
    "evidence": "user asked for shorter answers",
    "tags": ["style"],
}

DECISION_ADD = {"action": "add", "target_skill": "", "reason": "brand new capability"}
DECISION_DISCARD = {"action": "discard", "target_skill": "", "reason": "already covered"}


# --- fake OpenAI-compatible streaming client --------------------------------

class _Usage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


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


def text_turn(text="好的，我记住了"):
    return [
        _Chunk([_Choice(_Delta(content=text))]),
        _Chunk(usage=_Usage(10, 4)),
        _Chunk([_Choice(_Delta(), finish_reason="stop")]),
    ]


# --- fake side query: the only "model" the learning loop talks to -----------

def make_side_query(*, candidate=None, decision=None):
    """Return an async side_query that answers each learning prompt offline."""
    candidate = CANDIDATE if candidate is None else candidate
    decision = DECISION_ADD if decision is None else decision
    prompts: list[str] = []

    async def side_query(system: str, user_message: str) -> str:
        prompts.append(system)
        if "Extractor" in system:
            return json.dumps({"skills": [] if candidate is None else [candidate]})
        if "Manager" in system:
            return json.dumps(decision)
        if "Judge" in system:
            payload = json.loads(user_message)
            hits = payload.get("retrieved_skills") or []
            return json.dumps(
                {
                    "judgments": [
                        {"name": hit.get("name"), "relevant": True, "used": True, "reason": "stub"}
                        for hit in hits
                    ]
                }
            )
        return "{}"

    side_query.prompts = prompts  # type: ignore[attr-defined]
    return side_query


# --- harness ----------------------------------------------------------------

def make_agent(*, turns=2, confirm=None, side_query=None, **agent_kwargs) -> Agent:
    agent = Agent(model="test-model", api_base=API_BASE, api_key="test-key", **agent_kwargs)
    agent._openai_client = FakeOpenAI([text_turn() for _ in range(turns)])
    query = side_query or make_side_query()
    agent._build_side_query = lambda *, max_tokens=256: query
    if confirm is not None:
        agent.set_confirm_fn(confirm)
    return agent


async def run_turn(agent: Agent, message: str) -> list[dict]:
    """Run one turn and wait for the background learning tasks it started.

    This mirrors the call site the web layer must use: drain before the event
    stream (sink) is closed, otherwise the learning events never reach the user.
    """
    seen: list[dict] = []
    with events.use_sink(seen.append):
        await agent.chat(message)
        await agent.drain_background_skill_tasks()
    return seen


def types(seen: list[dict]) -> list[str]:
    return [event["type"] for event in seen]


def events_of(seen: list[dict], kind: str) -> list[dict]:
    return [event for event in seen if event["type"] == kind]


def summary_line(summary: str) -> str:
    """写入确认文本里机器可读的那一行（runtime 用它解析 action 与技能名）。

    确认文本现在是多行的：前面是候选规则与变更说明，最后一行才是
    "online skill evolution: <action> <name>"。
    """
    return [line for line in str(summary).splitlines() if line.strip()][-1]


def skill_names() -> list[str]:
    reset_skill_cache()
    return [skill.name for skill in discover_skills()]


FEEDBACK = "以后回答简短点，别啰嗦"
# These cases test confirmation wiring for a standing rule, not whether a
# current-output adjustment inherits permanence from an earlier user turn.
REPEAT = "以后每次都简短直接地回答，不加开场白"


@pytest.fixture(autouse=True)
def fresh_skill_cache():
    """skills 包的发现结果是进程内全局缓存（不区分数据目录），会让上一个用例的
    技能泄漏到下一个用例的隔离目录里。每个用例前后各重置一次，断言才只看本用例。
    """
    reset_skill_cache()
    yield
    reset_skill_cache()


# --- confirmed write --------------------------------------------------------

@pytest.mark.anyio
async def test_confirmed_candidate_is_written_and_visible():
    asked: list[str] = []

    async def confirm(summary: str) -> bool:
        asked.append(summary)
        return True

    agent = make_agent(turns=2, confirm=confirm)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    # 确认请求带着技能名与动作到达调用方（网页层据此发出带 token 的 confirmation），
    # 并且把真正要写入的规则摊开给用户看，而不是只给一句摘要。
    assert [summary_line(item) for item in asked] == ["online skill evolution: add brief-answers"]
    assert "Keep the answer short and skip preamble." in asked[0]

    proposed = events_of(seen, "skill_candidate_proposed")
    assert proposed and proposed[0]["skill"] == "brief-answers"
    assert proposed[0]["action"] == "add"

    applied = events_of(seen, "skill_candidate_applied")
    assert [event["action"] for event in applied] == ["add"]
    assert applied[0]["skill"] == "brief-answers"

    # 写入真的落到了技能目录（隔离数据目录）
    assert skill_names() == ["brief-answers"]


# --- denied write -----------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("latest", ["还是太长了，再短一点", "这次临时回答一句话，不用记住"])
async def test_latest_current_output_request_does_not_inherit_durable_permission(latest):
    async def confirm(summary: str) -> bool:
        raise AssertionError("A current-output request must not reach confirmation")

    query = make_side_query()
    agent = make_agent(turns=2, confirm=confirm, side_query=query)
    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, latest)

    assert skill_names() == []
    assert events_of(seen, "skill_candidate_proposed") == []
    assert events_of(seen, "skill_candidate_applied") == []
    assert any("一次性" in str(event.get("reason")) for event in events_of(seen, "skill_candidate_skipped"))
    assert not any("Extractor" in prompt for prompt in query.prompts)

@pytest.mark.anyio
async def test_denied_candidate_is_not_written_and_the_denial_is_visible():
    asked: list[str] = []

    async def confirm(summary: str) -> bool:
        asked.append(summary)
        return False

    agent = make_agent(turns=2, confirm=confirm)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    assert [summary_line(item) for item in asked] == ["online skill evolution: add brief-answers"]

    denied = events_of(seen, "skill_write_denied")
    assert denied, "拒绝必须可见，不能静默丢弃"
    assert denied[0]["reason"] == "user_denied"
    assert denied[0]["skill"] == "brief-answers"
    assert denied[0]["action"] == "add"
    assert "summary" in denied[0]

    assert events_of(seen, "skill_candidate_applied") == []
    assert skill_names() == []


@pytest.mark.anyio
async def test_failing_confirm_fn_is_reported_as_a_denied_write():
    async def confirm(summary: str) -> bool:
        raise RuntimeError("confirmation channel closed")

    agent = make_agent(turns=2, confirm=confirm)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    denied = events_of(seen, "skill_write_denied")
    assert denied and denied[0]["reason"] == "confirm_error:RuntimeError"
    assert skill_names() == []
    # 回合本身没有受影响
    assert "text_delta" in types(seen)


# --- nobody to ask ----------------------------------------------------------

@pytest.mark.anyio
async def test_without_confirm_fn_the_write_is_refused_and_still_visible():
    agent = make_agent(turns=2)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    denied = events_of(seen, "skill_write_denied")
    assert denied, "没有 confirm_fn 时拒绝必须可见"
    assert denied[0]["reason"] == "no_confirmer"
    assert skill_names() == []
    # 不抛异常：这一轮照常结束
    assert "turn_end" in types(seen)


@pytest.mark.anyio
async def test_plan_mode_skips_the_learning_write_visibly():
    seen: list[dict] = []
    agent = make_agent(turns=2, permission_mode="plan")

    with events.use_sink(seen.append):
        await agent.chat(FEEDBACK)
        await agent.chat(REPEAT)
        await agent.drain_background_skill_tasks()

    skipped = events_of(seen, "skill_candidate_skipped")
    assert skipped and skipped[0]["reason"] == "plan_mode"
    assert skill_names() == []


@pytest.mark.anyio
async def test_early_return_before_the_model_call_is_reported():
    """没有模型客户端时学习提前结束，但必须说明原因（不做静默 return）。"""
    agent = make_agent(turns=2)
    agent._build_side_query = lambda *, max_tokens=256: None

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    skipped = events_of(seen, "skill_candidate_skipped")
    assert skipped and skipped[0]["reason"] == "no_model_client"
    assert skill_names() == []


# --- repeated feedback merges instead of appending --------------------------

@pytest.mark.anyio
async def test_repeated_candidate_does_not_create_a_second_skill_or_a_new_version():
    """同一份反馈再来一次：既不多一份技能，也不产生无意义的新版本。"""
    asked: list[str] = []

    async def confirm(summary: str) -> bool:
        asked.append(summary)
        return True

    agent = make_agent(turns=3, confirm=confirm)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)      # 第一次学习：add
    seen += await run_turn(agent, REPEAT)      # 同一候选再来一次：判定重复

    applied = events_of(seen, "skill_candidate_applied")
    assert [event["action"] for event in applied] == ["add"]
    # 只有一份技能：重复反馈不会追加新技能
    assert skill_names() == ["brief-answers"]
    # 没有实质变化时不再打扰用户确认，也不升版本
    assert [summary_line(item) for item in asked] == ["online skill evolution: add brief-answers"]
    reset_skill_cache()
    skill = get_skill_by_name("brief-answers")
    assert skill is not None
    # 重复的那一轮必须是可见的「跳过」，而不是静默丢弃
    skipped = events_of(seen, "skill_candidate_skipped")
    assert any("重复" in str(event.get("reason") or "") for event in skipped), skipped


@pytest.mark.anyio
async def test_discarded_candidate_is_visible_as_skipped():
    async def confirm(summary: str) -> bool:  # pragma: no cover - must not be reached
        raise AssertionError("a discarded candidate must never reach the write step")

    query = make_side_query(decision=DECISION_DISCARD)
    agent = make_agent(turns=2, confirm=confirm, side_query=query)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    skipped = events_of(seen, "skill_candidate_skipped")
    assert skipped and skipped[-1]["reason"] == "already covered"
    assert skill_names() == []


# --- write failures ---------------------------------------------------------

@pytest.mark.anyio
async def test_skill_write_failure_is_reported_and_the_turn_survives(monkeypatch):
    from mellowday.runtime.skills import skills as skills_module

    def exploding_create_skill(*args, **kwargs):
        raise RuntimeError("skill directory is read-only")

    monkeypatch.setattr(skills_module, "create_skill", exploding_create_skill)

    async def confirm(summary: str) -> bool:
        return True

    agent = make_agent(turns=2, confirm=confirm)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    failed = events_of(seen, "skill_candidate_failed")
    assert failed, "写入抛错必须发出失败事件"
    assert "read-only" in failed[0]["reason"]
    assert events_of(seen, "skill_candidate_applied") == []
    assert skill_names() == []
    # 回合本身不受影响
    assert "text_delta" in types(seen)
    assert "turn_end" in types(seen)


@pytest.mark.anyio
async def test_unexpected_ingest_failure_is_reported_and_contained(monkeypatch):
    import mellowday.runtime.skills as skills_package

    async def exploding_ingest(**kwargs):
        raise RuntimeError("skills package exploded")

    monkeypatch.setattr(skills_package, "online_ingest", exploding_ingest)
    agent = make_agent(turns=2)

    seen = await run_turn(agent, FEEDBACK)
    seen += await run_turn(agent, REPEAT)

    failed = events_of(seen, "skill_candidate_failed")
    assert failed and "skills package exploded" in failed[0]["reason"]
    assert "turn_end" in types(seen)
    assert agent.has_pending_background_skill_tasks is False


# --- background task recycling ---------------------------------------------

@pytest.mark.anyio
async def test_drain_finishes_every_background_task():
    async def confirm(summary: str) -> bool:
        return True

    agent = make_agent(turns=2, confirm=confirm)

    seen: list[dict] = []
    with events.use_sink(seen.append):
        await agent.chat(FEEDBACK)
        assert agent.has_pending_background_skill_tasks is True

        await agent.drain_background_skill_tasks()
        assert agent.has_pending_background_skill_tasks is False

        await agent.chat(REPEAT)
        assert agent.has_pending_background_skill_tasks is True
        await agent.drain_background_skill_tasks()

    assert agent.has_pending_background_skill_tasks is False
    assert all(task.done() for task in agent._background_skill_tasks)
    # drain 之后学习结果已经产生（事件在关闭 sink 之前到达）
    assert events_of(seen, "skill_candidate_applied")


@pytest.mark.anyio
async def test_cancelled_background_tasks_are_collected():
    agent = make_agent(turns=2)

    seen: list[dict] = []
    with events.use_sink(seen.append):
        await agent.chat(FEEDBACK)
        agent.cancel_background_skill_tasks()
        # drain 必须容忍被取消的任务，并且不抛异常
        await agent.drain_background_skill_tasks()

    assert agent.has_pending_background_skill_tasks is False
    assert agent._background_skill_tasks == set()

# --- interactive extraction entry (extract_now) -----------------------------

@pytest.mark.anyio
async def test_extract_now_reports_a_confirmed_write():
    asked: list[str] = []

    async def confirm(summary: str) -> bool:
        asked.append(summary)
        return True

    agent = make_agent(turns=1, confirm=confirm)
    await run_turn(agent, FEEDBACK)          # 留下待提取的对话窗口

    seen: list[dict] = []
    with events.use_sink(seen.append):
        outcome = await agent.extract_now(hint="short answers")

    assert [summary_line(item) for item in asked] == ["online skill evolution: add brief-answers"]
    assert outcome["ok"] is True
    assert outcome["action"] == "add"
    assert outcome["skill"] == "brief-answers"
    assert outcome["written"] is True
    assert events_of(seen, "skill_candidate_proposed")
    assert events_of(seen, "skill_candidate_applied")
    assert skill_names() == ["brief-answers"]


@pytest.mark.anyio
async def test_extract_now_reports_a_denied_write_instead_of_claiming_success():
    async def confirm(summary: str) -> bool:
        return False

    agent = make_agent(turns=1, confirm=confirm)
    await run_turn(agent, FEEDBACK)

    seen: list[dict] = []
    with events.use_sink(seen.append):
        outcome = await agent.extract_now()

    assert outcome["written"] is False
    assert outcome["action"] == "add_denied"
    assert events_of(seen, "skill_write_denied")[0]["reason"] == "user_denied"
    assert skill_names() == []

@pytest.mark.anyio
async def test_bounded_drain_does_not_cancel_the_learning_task():
    """网页层可以只等一小段时间：超时只是不再阻塞，任务本身不被取消。"""
    agent = make_agent(turns=1)
    release = asyncio.Event()
    started = asyncio.Event()

    async def slow_learning() -> None:
        started.set()
        await release.wait()

    with events.use_sink(lambda event: None):
        agent._schedule_background_skill_task(slow_learning(), stage="online_skill_evolution")
        await started.wait()

        await agent.drain_background_skill_tasks(timeout=0.05)
        assert agent.has_pending_background_skill_tasks is True

        release.set()
        await agent.drain_background_skill_tasks()

    assert agent.has_pending_background_skill_tasks is False
    assert agent._background_skill_tasks == set()
