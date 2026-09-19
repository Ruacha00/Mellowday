"""C 缺陷修复的行为级测试：合并不丢旧规则、discard 不写入、重复候选不升版。

对应第三轮任务 t3 的 C 项验收：

* 模型判 discard 时不得产生任何写入（即使候选与既有技能身份命中）；
* 合并必须保留仍有效的旧规则，覆盖「旧规则 A+B + 候选 C」；
* 缺少有效合并正文时不得用单条候选覆盖原文；
* 相同反馈重复出现不得无限新增技能，也不得无意义升版；
* 「只修改部分旧规则」只替换被改的那一条。

测试走真实写入路径：真实技能文件（隔离 MELLOWDAY_DATA_DIR）+ 假 side_query
（离线，不发网络请求），断言的是磁盘上的技能正文、版本号与历史快照，而不是内部
函数的返回值。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mellowday import paths
from mellowday.runtime.agent import Agent
from mellowday.runtime.skills import (
    OnlineSkillCandidate,
    create_skill_file,
    discover_skills,
    extract_online_skill_candidate,
    maintain_online_skill_candidate,
    online_ingest,
    parse_frontmatter,
    reset_skill_cache,
)
NAME = "输出格式"
DESC = "回答输出格式的固定要求"
WHEN = "生成回答时"
RULE_A = "先给结论，再给理由"
RULE_B = "超过三行时用小标题分段"
RULE_B2 = "超过三行时用小标题分段，并在结尾给出下一步"
RULE_C = "回答里不要出现英文缩写"
BODY = f"# 步骤\n\n- {RULE_A}\n- {RULE_B}"

CANDIDATE = {
    "name": NAME,
    "description": DESC,
    "when_to_use": WHEN,
    "instructions": f"- {RULE_C}",
    "evidence": "用户明确要求不要用英文缩写",
    "tags": ["style"],
}

DECISION_DISCARD = {"action": "discard", "target_skill": "", "reason": "已有技能已覆盖这一点"}


@pytest.fixture(autouse=True)
def _fresh_skill_cache():
    """技能发现是进程级缓存；每个用例前后都清空，断言才只看本用例。"""
    reset_skill_cache()
    yield
    reset_skill_cache()

def make_side_query(decision: dict, *, candidate: dict | None = None):
    """Manager 返回给定决策；Extractor 默认没有候选。"""
    prompts: dict[str, list[str]] = {"manager": [], "extractor": []}

    async def side_query(system: str, payload: str) -> str:
        if "Extractor" in system:
            prompts["extractor"].append(system)
            skills = [] if candidate is None else [candidate]
            return json.dumps({"skills": skills}, ensure_ascii=False)
        prompts["manager"].append(system)
        return json.dumps(decision, ensure_ascii=False)

    side_query.prompts = prompts  # type: ignore[attr-defined]
    return side_query


def create_skill(name: str = NAME, description: str = DESC, body: str = BODY) -> Path:
    result = create_skill_file(
        name=name, description=description, instructions=body, when_to_use=WHEN
    )
    assert result["ok"] is True, result
    reset_skill_cache()
    return Path(result["file"])


def read_skill(skill_file: Path) -> tuple[dict[str, str], str]:
    parsed = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    return dict(parsed.meta), parsed.body


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


def always_yes(asked: list[str]):
    async def confirm(summary: str) -> bool:
        asked.append(summary)
        return True

    return confirm


async def maintain(decision: dict, *, confirm, candidate: dict | None = None) -> dict:
    return await maintain_online_skill_candidate(
        candidate=OnlineSkillCandidate(**(candidate or CANDIDATE)),
        side_query=make_side_query(decision, candidate=candidate),
        confirm_write=confirm,
    )

# --------------------------------------------------------------- 旧规则 A+B + 候选 C


@pytest.mark.anyio
async def test_merge_keeps_old_rules_and_adds_the_candidate(isolated_data_dir: Path) -> None:
    skill_file = create_skill()
    asked: list[str] = []
    decision = {
        "action": "merge",
        "target_skill": NAME,
        "reason": "补一条输出要求",
        "merged_instructions": f"# 步骤\n\n- {RULE_A}\n- {RULE_B}\n- {RULE_C}",
    }

    result = await maintain(decision, confirm=always_yes(asked))

    assert result["ok"] is True and result["action"] == "merge", result
    meta, body = read_skill(skill_file)
    assert RULE_A in body and RULE_B in body and RULE_C in body
    assert meta["version"] == "0.1.1"
    assert len(history_rows()) == 1
    assert len(asked) == 1


@pytest.mark.anyio
async def test_merge_without_a_merged_body_never_overwrites_the_original(
    isolated_data_dir: Path,
) -> None:
    """回归缺陷：没有 merged_instructions 时用单条候选正文覆盖原文，旧规则全部丢失。"""
    skill_file = create_skill()
    asked: list[str] = []
    decision = {"action": "merge", "target_skill": NAME, "reason": "补一条输出要求"}

    result = await maintain(decision, confirm=always_yes(asked))

    assert result["ok"] is True and result["action"] == "merge", result
    _meta, body = read_skill(skill_file)
    assert RULE_A in body, "旧规则 A 必须保留"
    assert RULE_B in body, "旧规则 B 必须保留"
    assert RULE_C in body, "候选 C 必须写进去"
    assert body.strip() != f"- {RULE_C}"


@pytest.mark.anyio
async def test_merge_does_not_lose_an_old_rule_the_model_forgot(isolated_data_dir: Path) -> None:
    """模型给的合并正文漏掉旧规则 B：运行时必须把 B 补回来，不能静默丢规则。"""
    skill_file = create_skill()
    asked: list[str] = []
    decision = {
        "action": "merge",
        "target_skill": NAME,
        "reason": "补一条输出要求",
        "merged_instructions": f"# 步骤\n\n- {RULE_A}\n- {RULE_C}",
    }

    result = await maintain(decision, confirm=always_yes(asked))

    assert result["ok"] is True, result
    _meta, body = read_skill(skill_file)
    assert RULE_A in body and RULE_B in body and RULE_C in body


@pytest.mark.anyio
async def test_only_an_explicit_supersede_removes_an_old_rule(isolated_data_dir: Path) -> None:
    """旧规则只在模型逐字声明 superseded_rules 时才消失。"""
    skill_file = create_skill()
    asked: list[str] = []
    decision = {
        "action": "merge",
        "target_skill": NAME,
        "reason": "用新规则替换旧的分段要求",
        "merged_instructions": f"# 步骤\n\n- {RULE_A}\n- {RULE_C}",
        "superseded_rules": [f"- {RULE_B}"],
    }

    result = await maintain(decision, confirm=always_yes(asked))

    assert result["ok"] is True, result
    _meta, body = read_skill(skill_file)
    assert RULE_A in body and RULE_C in body
    assert RULE_B not in body, "显式淘汰的旧规则必须真的不再出现"


@pytest.mark.anyio
async def test_partial_revision_replaces_only_the_rule_that_changed(isolated_data_dir: Path) -> None:
    """显式指认旧规则后，替换该项；相似措辞本身不授权删除。"""
    skill_file = create_skill()
    asked: list[str] = []
    decision = {
        "action": "merge",
        "target_skill": NAME,
        "reason": "补充分段后的收尾要求",
        "merged_instructions": f"# 步骤\n\n- {RULE_A}\n- {RULE_B2}\n- {RULE_C}",
        "superseded_rules": [f"- {RULE_B}"],
    }

    result = await maintain(decision, confirm=always_yes(asked))

    assert result["ok"] is True, result
    merge = result["merge"]
    assert merge["removed"] == [f"- {RULE_B}"], merge
    assert f"- {RULE_B2}" in merge["added"]
    _meta, body = read_skill(skill_file)
    assert RULE_A in body
    assert RULE_B2 in body
    assert body.count(RULE_B) == 1, body

# ------------------------------------------------------------------ 重复候选


@pytest.mark.anyio
async def test_duplicate_candidate_writes_nothing_and_does_not_bump_the_version(
    isolated_data_dir: Path,
) -> None:
    """同一份反馈重复出现：不重复写入、不升版本，也不该再问一次确认。"""
    skill_file = create_skill()
    decision = {
        "action": "merge",
        "target_skill": NAME,
        "reason": "补一条输出要求",
        "merged_instructions": f"# 步骤\n\n- {RULE_A}\n- {RULE_B}\n- {RULE_C}",
    }
    first_asked: list[str] = []
    first = await maintain(decision, confirm=always_yes(first_asked))
    assert first["ok"] is True and first["written"] is True

    before_raw = skill_file.read_text(encoding="utf-8")
    before_meta, _ = read_skill(skill_file)
    before_history = len(history_rows())
    before_mtime = skill_file.stat().st_mtime_ns

    second_asked: list[str] = []
    second = await maintain(decision, confirm=always_yes(second_asked))

    assert second["ok"] is True, second
    assert second["written"] is False
    assert second.get("no_change") is True
    assert second["action"] == "discard", "没有写入时不能对外报告成一次更新"
    assert "重复" in str(second.get("decision", {}).get("reason") or "")
    assert second_asked == [], "没有任何变更就不该再打扰用户确认"
    assert skill_file.read_text(encoding="utf-8") == before_raw
    meta, _ = read_skill(skill_file)
    assert meta["version"] == before_meta["version"] == "0.1.1"
    assert len(history_rows()) == before_history
    assert skill_file.stat().st_mtime_ns == before_mtime


@pytest.mark.anyio
async def test_repeated_candidate_does_not_create_a_second_skill(isolated_data_dir: Path) -> None:
    """重复候选走合并；技能数量不增长。"""
    create_skill()
    decision = {"action": "add", "target_skill": "", "reason": "看起来是新的"}
    asked: list[str] = []
    result = await maintain(decision, confirm=always_yes(asked))

    # 身份命中把 add 改判成 merge；候选规则如果已在正文里，就不产生实质变化。
    assert result["ok"] is True, result
    assert result["action"] in {"merge", "discard"}, result
    if result["action"] == "discard":
        assert result["written"] is False
    reset_skill_cache()
    assert [skill.name for skill in discover_skills()] == [NAME]

# ------------------------------------------------------------------ discard 终态


@pytest.mark.anyio
async def test_discard_never_writes_even_when_identity_matches(isolated_data_dir: Path) -> None:
    """回归缺陷：身份命中把 discard 无条件改成 merge，产生没人要求的写入与版本 +1。"""
    skill_file = create_skill()
    before_raw = skill_file.read_text(encoding="utf-8")
    before_mtime = skill_file.stat().st_mtime_ns
    asked: list[str] = []

    async def confirm(summary: str) -> bool:  # pragma: no cover - 不应被调用
        asked.append(summary)
        raise AssertionError("discard 不该走到确认写入")

    result = await maintain(DECISION_DISCARD, confirm=confirm)

    assert result["ok"] is True
    assert result["action"] == "discard"
    assert result["written"] is False
    assert result["skill"] == ""
    assert asked == []
    assert skill_file.read_text(encoding="utf-8") == before_raw
    assert skill_file.stat().st_mtime_ns == before_mtime
    assert history_rows() == []
    meta, _ = read_skill(skill_file)
    assert meta["version"] == "0.1.0"


@pytest.mark.anyio
async def test_add_is_upgraded_to_merge_for_an_existing_name(isolated_data_dir: Path) -> None:
    """同名候选不能新建第二份技能，也不能因为 create 失败而报写入失败。"""
    create_skill()
    decision = {"action": "add", "target_skill": "", "reason": "看起来是新的"}
    asked: list[str] = []
    result = await maintain(
        decision, confirm=always_yes(asked), candidate={**CANDIDATE, "description": "完全不同的描述"}
    )

    assert result["action"] == "merge", result
    assert result["ok"] is True, result
    reset_skill_cache()
    assert [skill.name for skill in discover_skills()] == [NAME]

# ------------------------------------------------------- 确认文本要能看懂改了什么


@pytest.mark.anyio
async def test_write_confirmation_shows_the_real_candidate_rules(isolated_data_dir: Path) -> None:
    create_skill()
    asked: list[str] = []
    decision = {
        "action": "merge",
        "target_skill": NAME,
        "reason": "补充分段后的收尾要求",
        "merged_instructions": f"# 步骤\n\n- {RULE_A}\n- {RULE_B2}\n- {RULE_C}",
    }

    await maintain(decision, confirm=always_yes(asked))

    assert len(asked) == 1
    summary = asked[0]
    assert RULE_C in summary, "确认文本必须写出实际候选规则"
    assert RULE_B in summary and RULE_B2 in summary, "合并确认要给旧→新的对照"
    assert RULE_A in summary
    lines = [line for line in summary.splitlines() if line.strip()]
    assert lines[-1] == f"online skill evolution: merge {NAME}"
    # runtime 侧解析出的 action/技能名必须仍然正确（多行文本不能污染事件字段）。
    assert Agent._skill_write_summary_parts(summary) == ("merge", NAME)


@pytest.mark.anyio
async def test_new_skill_confirmation_shows_the_rules_to_be_written(isolated_data_dir: Path) -> None:
    asked: list[str] = []
    decision = {"action": "add", "target_skill": "", "reason": "新的可复用规则"}

    result = await maintain(decision, confirm=always_yes(asked))

    assert result["action"] == "add" and result["written"] is True
    assert len(asked) == 1
    assert RULE_C in asked[0]
    assert asked[0].splitlines()[-1] == f"online skill evolution: add {NAME}"
    assert Agent._skill_write_summary_parts(asked[0]) == ("add", NAME)

# --------------------------------------------------------- 一次性要求不成为永久规则


@pytest.mark.anyio
async def test_one_off_request_is_not_learned_and_writes_nothing(isolated_data_dir: Path) -> None:
    """一次性要求：提取阶段就不该产出候选，运行时也不得写入任何技能。

    「一次性 vs 长期」的判定由提取模型给出（提示词里明确排除了 one-off / temporary
    内容）；这里锁住运行时的另一半契约：没有候选就没有写入，而且提示词确实带着这条
    约束，改坏了会立刻失败。
    """
    query = make_side_query({"action": "add"}, candidate=None)
    asked: list[str] = []

    result = await online_ingest(
        messages=[
            {"role": "user", "content": "这次先只列三条，以后不用"},
            {"role": "assistant", "content": "好的，这次只列三条。"},
        ],
        side_query=query,
        confirm_write=always_yes(asked),
    )

    assert result["ok"] is True and result["action"] == "none", result
    assert asked == []
    reset_skill_cache()
    assert discover_skills() == []

    extractor_prompts = query.prompts["extractor"]
    assert extractor_prompts, "提取阶段必须调用 Extractor"
    prompt = extractor_prompts[0]
    assert "one-off" in prompt and "temporary" in prompt
    assert "durable" in prompt


@pytest.mark.anyio
async def test_extractor_still_extracts_a_durable_request(isolated_data_dir: Path) -> None:
    """对照组：明确的长期要求会被提取成候选，说明上一条不是因为提取永远为空。"""
    query = make_side_query({"action": "add"}, candidate=CANDIDATE)

    candidate = await extract_online_skill_candidate(
        messages=[{"role": "user", "content": "以后回答都别用英文缩写"}],
        side_query=query,
    )

    assert candidate is not None
    assert candidate.name == NAME
    assert RULE_C in candidate.instructions


@pytest.mark.anyio
async def test_manager_prompt_demands_a_complete_merged_body(isolated_data_dir: Path) -> None:
    """提示词侧的另一半保障：要求完整合并正文，并要求显式声明被淘汰的规则。"""
    create_skill()
    query = make_side_query(DECISION_DISCARD)
    await maintain_online_skill_candidate(
        candidate=OnlineSkillCandidate(**CANDIDATE),
        side_query=query,
        confirm_write=always_yes([]),
    )

    prompt = query.prompts["manager"][0]
    assert "COMPLETE merged body" in prompt
    assert "superseded_rules" in prompt
    assert "Discard is final" in prompt
