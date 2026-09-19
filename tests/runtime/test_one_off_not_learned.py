"""I11：一次性要求不得被学习（t12）。

真实模型演示（t5）里两条一次性要求仍然被学成了规则：显式说「也不用记住这条要求」的
请求把技能从 0.1.0 升到 0.1.1；折叠场景里的「第二条再展开一点，加上要对比的两个数据
口径」被学成了新技能。本文件锁住修复后的行为：

* 三类一次性输入（显式不用记住 / 只针对当前输出 / 轮次限定）都不写文件、不升版本，
  并返回可见的跳过（action=discard + 非空 reason，运行时映射成 skill_candidate_skipped）；
* 同类输入重复三次仍不产生技能；
* 对照组：明确的、可复用的纠正仍然会被学习（防止「一刀切关掉学习」也能过测）；
* 门槛在模型调用之前生效：一次性输入根本不会去问模型，模型不可用也不改变语义；
* 判定本身有单元级断言（真实短语逐条判定），避免只靠端到端用例。

旧实现下会失败的断言：本文件里全部 one_off 用例——旧实现没有门槛，候选会被合并/新建
并升版本；还有「一次性输入不调用模型」这条（旧实现会调用模型）。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mellowday import paths
from mellowday.runtime import events
from mellowday.runtime.agent import Agent
from mellowday.runtime.skills import (
    create_skill_file,
    discover_skills,
    online_ingest,
    parse_frontmatter,
    reset_skill_cache,
)
from mellowday.runtime.skills.request_scope import classify_request_scope, user_turn_texts

NAME = "季度报告大纲"
DESC = "生成季度报告时使用的固定大纲"
WHEN = "用户要求写季度报告时"
BODY = "# 步骤\n\n1. 先说结论\n2. 再列数据"

# t5 实测的两条失败输入
EXPLICIT_ONE_OFF = "这次先只要一句话概括就行，也不用记住这条要求"
OUTPUT_ADJUST_ONE_OFF = "第二条再展开一点，加上要对比的两个数据口径"
ROUND_LIMITED_ONE_OFF = "暂时先这样吧，这轮就按这个来"

# 明确、可复用的纠正（核心演示里的同款句式）
DURABLE_CORRECTION = "不对。以后帮我规划的时候，必须先列出当天已有的固定日程，然后只排三个重点任务，不要一次列十几条。"

CANDIDATE = {
    "name": NAME,
    "description": DESC,
    "when_to_use": WHEN,
    "instructions": f"- {OUTPUT_ADJUST_ONE_OFF}",
    "evidence": "用户要求补一个数据口径",
    "tags": ["report"],
}


class ModelMustNotBeAsked:
    """一次性输入不该调用模型：真被调用就报错，顺便计数。"""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, system: str, payload: str) -> str:  # pragma: no cover - 不应命中
        self.calls += 1
        raise AssertionError("一次性要求不应调用模型")


class RaisingConfirm:
    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, summary: str) -> bool:  # pragma: no cover - 不应命中
        self.calls += 1
        raise AssertionError("一次性要求不应请求写入确认")


def make_side_query(*, candidate=None, decision=None):
    """正常路径用的假模型：Extractor 返回候选，Manager 返回决策。"""
    candidate = CANDIDATE if candidate is None else candidate
    decision = {"action": "add", "target_skill": ""} if decision is None else decision
    prompts: list[str] = []

    async def side_query(system: str, payload: str) -> str:
        prompts.append(system)
        if "Extractor" in system:
            return json.dumps({"skills": [] if candidate is None else [candidate]}, ensure_ascii=False)
        if "Manager" in system:
            return json.dumps(decision, ensure_ascii=False)
        return "{}"

    side_query.prompts = prompts  # type: ignore[attr-defined]
    return side_query


@pytest.fixture(autouse=True)
def _fresh_skill_cache():
    reset_skill_cache()
    yield
    reset_skill_cache()


def skill_names() -> list[str]:
    reset_skill_cache()
    return [skill.name for skill in discover_skills()]


def history_rows() -> list[dict]:
    root = paths.evolution_dir() / "history"
    if not root.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(root.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def provenance_rows() -> list[dict]:
    log = paths.evolution_dir() / "online_provenance.jsonl"
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def create_existing_skill() -> Path:
    result = create_skill_file(name=NAME, description=DESC, instructions=BODY, when_to_use=WHEN)
    assert result["ok"] is True, result
    reset_skill_cache()
    return Path(result["file"])


def read_version(skill_file: Path) -> str:
    parsed = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    return str(parsed.meta.get("version") or "")


# ------------------------------------------------------- 三类一次性要求：不写不升版


@pytest.mark.anyio
async def test_explicit_do_not_remember_is_never_written(isolated_data_dir: Path) -> None:
    query = ModelMustNotBeAsked()
    confirm = RaisingConfirm()

    result = await online_ingest(
        messages=[{"role": "user", "content": EXPLICIT_ONE_OFF}, {"role": "assistant", "content": "好的"}],
        side_query=query,
        confirm_write=confirm,
    )

    assert result["ok"] is True
    assert result["action"] == "discard", result
    assert result["one_off"] is True
    assert result["written"] is False and result["changed"] is False
    assert "一次性要求不写入" in result["reason"] and "不用记住" in result["reason"]
    # 门槛在模型之前：既没问模型，也没问用户，更没写盘。
    assert query.calls == 0
    assert confirm.calls == 0
    assert skill_names() == []
    assert history_rows() == []
    record = provenance_rows()[-1]
    assert record["action"] == "discard"
    assert record["decision"]["source"] == "request_scope"


@pytest.mark.anyio
async def test_current_output_adjustment_cannot_bump_an_existing_version(
    isolated_data_dir: Path,
) -> None:
    """回归 t5 场景 2：折叠场景里的一次性调整曾把新技能写成 v0.1.0。"""
    skill_file = create_existing_skill()
    before = skill_file.read_text(encoding="utf-8")
    version_before = read_version(skill_file)
    history_before = len(history_rows())
    query = ModelMustNotBeAsked()

    result = await online_ingest(
        messages=[
            {"role": "user", "content": "帮我写个季度报告大纲"},
            {"role": "assistant", "content": "1. 核心成果 2. 风险 3. 下季度计划"},
            {"role": "user", "content": OUTPUT_ADJUST_ONE_OFF},
        ],
        side_query=query,
        confirm_write=RaisingConfirm(),
    )

    assert result["action"] == "discard" and result["one_off"] is True, result
    assert "再展开一点" in result["reason"]
    assert query.calls == 0
    assert skill_names() == [NAME]
    assert read_version(skill_file) == version_before == "0.1.0"
    assert skill_file.read_text(encoding="utf-8") == before
    assert len(history_rows()) == history_before


@pytest.mark.anyio
async def test_round_limited_request_is_never_written(isolated_data_dir: Path) -> None:
    query = ModelMustNotBeAsked()

    result = await online_ingest(
        messages=[{"role": "user", "content": ROUND_LIMITED_ONE_OFF}, {"role": "assistant", "content": "好"}],
        side_query=query,
        confirm_write=RaisingConfirm(),
    )

    assert result["action"] == "discard" and result["one_off"] is True, result
    assert "暂时" in result["reason"] or "这轮" in result["reason"]
    assert query.calls == 0
    assert skill_names() == []
    assert history_rows() == []


@pytest.mark.anyio
async def test_repeated_one_off_requests_still_produce_nothing(isolated_data_dir: Path) -> None:
    """同类输入重复三次：既不新增技能，也不升版本，每次都有可见理由。"""
    create_existing_skill()
    skill_file = paths.skills_dir() / NAME / "SKILL.md"
    version_before = read_version(skill_file)

    for round_index in range(3):
        query = ModelMustNotBeAsked()
        result = await online_ingest(
            messages=[
                {"role": "user", "content": OUTPUT_ADJUST_ONE_OFF + "（第 " + str(round_index + 1) + " 次）"},
                {"role": "assistant", "content": "好"},
            ],
            side_query=query,
            confirm_write=RaisingConfirm(),
        )
        assert result["action"] == "discard" and result["one_off"] is True, result
        assert result["reason"], "每一轮都必须给出可展示的理由"
        assert query.calls == 0

    assert skill_names() == [NAME]
    assert read_version(skill_file) == version_before == "0.1.0"
    assert history_rows() == []


# ------------------------------------------------------------------ 对照组：真规则照学


@pytest.mark.anyio
async def test_a_durable_correction_is_still_learned(isolated_data_dir: Path) -> None:
    """防止「一刀切关掉学习」也能过测：明确的长期纠正必须照旧落盘。"""
    query = make_side_query()

    async def confirm(summary: str) -> bool:
        return True

    result = await online_ingest(
        messages=[{"role": "user", "content": DURABLE_CORRECTION}, {"role": "assistant", "content": "好的"}],
        side_query=query,
        confirm_write=confirm,
    )

    assert result["action"] == "add" and result["written"] is True, result
    assert result["one_off"] is False if "one_off" in result else True
    assert skill_names() == [NAME]
    assert query.prompts, "对照组必须真的走完模型流程，不能被门槛短路"


@pytest.mark.anyio
async def test_current_output_adjustment_does_not_inherit_old_durable_scope(
    isolated_data_dir: Path,
) -> None:
    """历史长期要求不把当前输出调整自动提升为永久规则。"""
    window = [
        {"role": "user", "content": "以后回答简短点，别啰嗦"},
        {"role": "assistant", "content": "好的，我记住了"},
        {"role": "user", "content": "还是太长了，再短一点"},
    ]
    verdict = classify_request_scope(window)
    assert verdict["learnable"] is False, verdict
    assert verdict["durable"] == ""

    result = await online_ingest(messages=window, side_query=ModelMustNotBeAsked(), confirm_write=RaisingConfirm())
    assert result["action"] == "discard" and result["written"] is False, result
    assert skill_names() == []


# ------------------------------------------------------------------ 判定本身的单元断言


ONE_OFF_PHRASES = (
    EXPLICIT_ONE_OFF,
    OUTPUT_ADJUST_ONE_OFF,
    ROUND_LIMITED_ONE_OFF,
    "这次先只列三条",
    "先这样吧",
    "再详细一点，把风险那一节拆开",
    "这轮先不用写总结",
)

DURABLE_PHRASES = (
    DURABLE_CORRECTION,
    "以后回答简短点，别啰嗦",
    "以后每个报告都加上数据对比口径",
    "以后回答都别用英文缩写",
    "每次都要先给结论",
    "from now on keep the answers short",
)


def test_the_classifier_separates_one_off_from_durable() -> None:
    for text in ONE_OFF_PHRASES:
        verdict = classify_request_scope([{"role": "user", "content": text}])
        assert verdict["scope"] == "one_off", (text, verdict)
    for text in DURABLE_PHRASES:
        verdict = classify_request_scope([{"role": "user", "content": text}])
        assert verdict["learnable"] is True, (text, verdict)


def test_ordinary_rules_without_durability_words_are_not_blocked() -> None:
    """没有任何一次性信号的普通纠正默认放行，学习行为与以前一致。"""
    for text in ("不要用英文缩写", "先给结论，再给理由", "别记流水账，只写结论", "回答里别用 emoji"):
        verdict = classify_request_scope([{"role": "user", "content": text}])
        assert verdict["learnable"] is True, (text, verdict)


def test_only_user_turns_are_evidence() -> None:
    messages = [
        {"role": "assistant", "content": "好的，这次我先只列三条"},
        {"role": "user", "content": "以后都要列三条"},
    ]
    assert user_turn_texts(messages) == ["以后都要列三条"]
    assert classify_request_scope(messages)["learnable"] is True


@pytest.mark.anyio
async def test_the_extractor_prompt_carries_the_one_off_guard(isolated_data_dir: Path) -> None:
    """提示词是第一道防线：三类一次性要求都要写进去，而且中文不能是转义串。"""
    query = make_side_query(candidate=None)
    await online_ingest(messages=[{"role": "user", "content": DURABLE_CORRECTION}], side_query=query)

    prompt = query.prompts[0]
    assert "not-to-remember" in prompt
    assert "round-limited" in prompt
    assert "durability words" in prompt
    for word in ("以后", "每次", "一律", "这次", "暂时", "临时", "先这样"):
        assert word in prompt, word


# ------------------------------------------------- 可见性：运行时把跳过报成事件


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

    async def create(self, **kwargs):
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


def make_agent(*, turns=2, side_query=None) -> Agent:
    agent = Agent(model="test-model", api_base="http://127.0.0.1:9/v1", api_key="test-key")
    agent._openai_client = FakeOpenAI([text_turn() for _ in range(turns)])
    query = side_query or make_side_query()
    agent._build_side_query = lambda *, max_tokens=256: query
    return agent


async def run_turn(agent: Agent, message: str) -> list[dict]:
    seen: list[dict] = []
    with events.use_sink(seen.append):
        await agent.chat(message)
        await agent.drain_background_skill_tasks()
    return seen


@pytest.mark.anyio
async def test_one_off_feedback_is_visible_as_a_skipped_event(isolated_data_dir: Path) -> None:
    """可见性：被跳过的一次性要求必须变成 skill_candidate_skipped，而不是静默。"""
    query = ModelMustNotBeAsked()
    agent = make_agent(turns=2, side_query=query)

    seen = await run_turn(agent, EXPLICIT_ONE_OFF)
    seen += await run_turn(agent, EXPLICIT_ONE_OFF)

    skipped = [event for event in seen if event["type"] == "skill_candidate_skipped"]
    assert skipped, "一次性要求必须留下可见的跳过事件"
    assert "一次性要求不写入" in str(skipped[-1].get("reason"))
    assert not [event for event in seen if event["type"] == "skill_candidate_applied"]
    assert not [event for event in seen if event["type"] == "skill_write_denied"]
    assert query.calls == 0, "门槛在模型之前，连模型都不该问"
    assert skill_names() == []
