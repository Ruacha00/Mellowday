"""F 项：规则正文可见、可编辑、可回看历史正文，且改动影响后续新会话。

对应第三轮任务 t3 的 F 项验收：

* 管理页能读到技能**当前的规则正文**（不只是名称/描述/版本）；
* 编辑保存走既有版本机制（历史快照 + 补丁位 +1），不新建存储；
* 编辑后的正文对新会话生效（发现缓存被刷新，加载路径拿到新规则）；
* 没有实质变化时不写文件、不升版本；空正文被拒绝；
* 历史版本的正文可单独查看，并且仍能回退。

全部离线：技能建在隔离的 MELLOWDAY_DATA_DIR 下，不发网络请求。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mellowday import paths
from mellowday.runtime.skills import (
    build_skill_descriptions,
    create_skill_file,
    discover_skills,
    evolve_skill_file,
    get_skill_by_name,
    get_skill_detail,
    get_skill_version_content,
    list_skill_versions,
    reset_skill_cache,
    restore_skill_version,
    retrieve_relevant_skills,
    split_evolution_notes,
    update_skill,
)

NAME = "每周回顾"
DESC = "梳理本周完成与未完成的待办，生成本周总结与下周计划"
WHEN = "当用户要求做每周回顾、周总结或复盘本周安排时使用"
RULE_A = "先列已完成"
RULE_B = "再列未完成"
BODY = f"# 步骤\n\n1. {RULE_A}\n2. {RULE_B}"
QUERY = "帮我做每周回顾和周总结"


@pytest.fixture(autouse=True)
def _isolated_skill_cache():
    reset_skill_cache()
    yield
    reset_skill_cache()


@pytest.fixture
def skill_file(isolated_data_dir: Path) -> Path:
    result = create_skill_file(
        name=NAME, description=DESC, instructions=BODY, when_to_use=WHEN, tags=["回顾"]
    )
    assert result["ok"] is True, result
    reset_skill_cache()
    return Path(result["file"])


def _hit_names(query: str) -> list[str]:
    return [str(hit.get("name")) for hit in retrieve_relevant_skills(query, limit=5)]


# ------------------------------------------------------------------ 查看当前正文


def test_detail_exposes_the_current_rules(skill_file: Path, isolated_data_dir: Path) -> None:
    detail = get_skill_detail(NAME)

    assert detail["ok"] is True
    assert detail["name"] == NAME
    assert detail["description"] == DESC
    assert detail["when_to_use"] == WHEN
    assert detail["version"] == "0.1.0"
    assert detail["enabled"] is True
    assert detail["tags"] == "回顾"
    assert RULE_A in detail["body"] and RULE_B in detail["body"]
    assert detail["notes"] == ""
    assert Path(detail["path"]) == skill_file


def test_detail_of_an_unknown_skill_is_a_domain_failure(isolated_data_dir: Path) -> None:
    result = get_skill_detail("不存在的技能")
    assert result["ok"] is False
    assert result["error_code"] == "skill_not_found"
    assert get_skill_detail("   ")["error_code"] == "invalid_name"


def test_detail_is_readable_while_the_skill_is_disabled(skill_file: Path, isolated_data_dir: Path) -> None:
    from mellowday.runtime.skills import disable_skill, enable_skill

    assert disable_skill(NAME)["ok"] is True
    detail = get_skill_detail(NAME)
    assert detail["ok"] is True and detail["enabled"] is False
    assert RULE_A in detail["body"]
    assert enable_skill(NAME)["ok"] is True


# ------------------------------------------------------------------ 编辑保存


def test_update_replaces_the_rules_and_keeps_a_restorable_snapshot(
    skill_file: Path, isolated_data_dir: Path
) -> None:
    older = get_skill_detail(NAME)["body"]

    result = update_skill(NAME, instructions=f"# 步骤\n\n1. {RULE_A}\n2. 标注负责人\n3. {RULE_B}")

    assert result["ok"] is True, result
    assert result["changed"] is True
    assert result["previous_version"] == "0.1.0"
    assert result["version"] == "0.1.1"

    detail = get_skill_detail(NAME)
    assert "标注负责人" in detail["body"]
    assert detail["version"] == "0.1.1"
    # 历史版本仍然可读，并且内容就是编辑前那一份。
    history = get_skill_version_content(NAME, "0.1.0")
    assert history["ok"] is True and history["current"] is False
    assert history["body"] == older
    assert [item["version"] for item in list_skill_versions(NAME)][:2] == ["0.1.1", "0.1.0"]

    # 回退仍然可用：编辑没有绕开既有版本机制。
    assert restore_skill_version(NAME, "0.1.0")["ok"] is True
    assert get_skill_detail(NAME)["body"] == older


def test_update_without_a_real_change_does_not_write_or_bump_the_version(
    skill_file: Path, isolated_data_dir: Path
) -> None:
    before = skill_file.read_text(encoding="utf-8")
    before_mtime = skill_file.stat().st_mtime_ns

    result = update_skill(NAME, instructions=BODY, description=DESC)

    assert result["ok"] is True
    assert result["changed"] is False
    assert result["version"] == "0.1.0"
    assert skill_file.read_text(encoding="utf-8") == before
    assert skill_file.stat().st_mtime_ns == before_mtime


def test_update_rejects_an_empty_rule_body(skill_file: Path, isolated_data_dir: Path) -> None:
    before = skill_file.read_text(encoding="utf-8")

    result = update_skill(NAME, instructions="   \n  ")

    assert result["ok"] is False
    assert result["error_code"] == "empty_instructions"
    assert skill_file.read_text(encoding="utf-8") == before
    assert get_skill_detail(NAME)["version"] == "0.1.0"


def test_update_keeps_the_evolution_notes_and_appends_an_edit_note(
    skill_file: Path, isolated_data_dir: Path
) -> None:
    evolve_skill_file(skill_name=NAME, lesson="先给出结论再列细节", rationale="用户两次纠正")
    reset_skill_cache()
    notes = get_skill_detail(NAME)["notes"]
    assert "先给出结论再列细节" in notes

    result = update_skill(NAME, instructions=f"# 步骤\n\n1. {RULE_A}\n2. 标注负责人", note="手工编辑")

    assert result["ok"] is True, result
    detail = get_skill_detail(NAME)
    assert "先给出结论再列细节" in detail["notes"], "溯源小节不能被编辑掉"
    assert "手工编辑" in detail["notes"]
    assert notes.count("## Evolution Notes") == 1
    assert detail["notes"].count("## Evolution Notes") == 1, "不能出现两个同名溯源小节"


def test_update_is_refused_while_the_skill_is_disabled(
    skill_file: Path, isolated_data_dir: Path
) -> None:
    from mellowday.runtime.skills import disable_skill, enable_skill

    assert disable_skill(NAME)["ok"] is True
    refused = update_skill(NAME, instructions="# 新规则")
    assert refused["ok"] is False
    assert refused["error_code"] == "skill_disabled"

    assert enable_skill(NAME)["ok"] is True
    allowed = update_skill(NAME, instructions="# 新规则")
    assert allowed["ok"] is True and allowed["version"] == "0.1.1"


def test_update_of_an_unknown_skill_is_a_domain_failure(isolated_data_dir: Path) -> None:
    result = update_skill("不存在的技能", instructions="# 新规则")
    assert result["ok"] is False
    assert result["error_code"] == "skill_not_found"


def test_update_can_change_description_and_when_to_use(skill_file: Path, isolated_data_dir: Path) -> None:
    result = update_skill(NAME, description="每周复盘并生成下周计划", when_to_use="用户要求复盘时")
    assert result["ok"] is True and result["changed"] is True

    detail = get_skill_detail(NAME)
    assert detail["description"] == "每周复盘并生成下周计划"
    assert detail["when_to_use"] == "用户要求复盘时"
    # 正文没有提交时不动。
    assert RULE_A in detail["body"] and RULE_B in detail["body"]

# ------------------------------------------------------- 改动影响后续新会话


def test_edit_takes_effect_for_subsequent_sessions(skill_file: Path, isolated_data_dir: Path) -> None:
    """编辑保存后，新会话看到的技能正文必须是新规则（发现缓存被刷新）。"""
    assert NAME in _hit_names(QUERY)
    assert "标注负责人" not in (get_skill_by_name(NAME).prompt_template or "")

    update_skill(NAME, instructions=f"# 步骤\n\n1. {RULE_A}\n2. 标注负责人")

    # 新会话的加载路径：发现结果（进程内缓存）与技能提示词。
    loaded = get_skill_by_name(NAME)
    assert loaded is not None
    assert "标注负责人" in loaded.prompt_template
    assert NAME in _hit_names(QUERY)
    assert NAME in build_skill_descriptions()


def _rule_body_loaded_in_a_new_session() -> str:
    """新会话拿到的规则正文（不含演化溯源小节）。"""
    loaded = get_skill_by_name(NAME)
    assert loaded is not None
    return split_evolution_notes(loaded.prompt_template or "")[0]


def test_removing_a_rule_through_edit_makes_it_disappear_from_the_loaded_skill(
    skill_file: Path, isolated_data_dir: Path
) -> None:
    """误学成规则的一次性要求被删掉后，新会话加载到的规则正文里不再有它。

    溯源小节只记录当次的判断理由（供人回看），规则是否生效只看规则正文，
    所以断言落在规则正文上。
    """
    detail = get_skill_detail(NAME)
    mislearned = detail["body"] + "\n3. 这一次只列三条"
    assert update_skill(NAME, instructions=mislearned, note="记录一次误学")["ok"] is True
    assert "这一次只列三条" in _rule_body_loaded_in_a_new_session()

    result = update_skill(NAME, instructions=BODY, note="删除一次性要求")

    assert result["ok"] is True, result
    detail = get_skill_detail(NAME)
    assert "这一次只列三条" not in detail["body"]
    assert RULE_A in detail["body"] and RULE_B in detail["body"]
    assert "这一次只列三条" not in _rule_body_loaded_in_a_new_session()
    # 溯源仍然保留历史（它记录的是理由，不是规则）。
    assert "删除一次性要求" in detail["notes"]


def test_history_body_of_the_current_version_matches_the_file(
    skill_file: Path, isolated_data_dir: Path
) -> None:
    current = get_skill_version_content(NAME, "0.1.0")
    assert current["ok"] is True and current["current"] is True
    assert RULE_A in current["body"]
    assert Path(current["path"]) == skill_file


def test_history_body_of_an_unknown_version_or_skill_is_a_domain_failure(
    skill_file: Path, isolated_data_dir: Path
) -> None:
    assert get_skill_version_content(NAME, "9.9.9")["error_code"] == "version_not_found"
    assert get_skill_version_content("不存在的技能", "0.1.0")["error_code"] == "skill_not_found"
    assert get_skill_version_content(NAME, " ")["error_code"] == "version_required"
    assert get_skill_version_content(" ", "0.1.0")["error_code"] == "invalid_name"


def test_every_edit_lands_in_the_evolution_log(skill_file: Path, isolated_data_dir: Path) -> None:
    update_skill(NAME, instructions=f"# 步骤\n\n1. {RULE_A}\n2. 标注负责人")

    usage = paths.evolution_dir() / "usage.jsonl"
    rows = [json.loads(line) for line in usage.read_text(encoding="utf-8").splitlines() if line.strip()]
    edits = [row for row in rows if row.get("event") == "evolve" and row.get("skill") == NAME]
    assert edits and edits[-1]["actor"] == "user"
    history = paths.evolution_dir() / "history"
    snapshots = [json.loads(line) for path in history.glob("*.jsonl") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [row["version"] for row in snapshots] == ["0.1.0"]
    assert snapshots[0]["content"].startswith("---")


def test_skills_without_notes_have_an_empty_notes_field(skill_file: Path, isolated_data_dir: Path) -> None:
    detail = get_skill_detail(NAME)
    assert detail["notes"] == ""
    assert "## Evolution Notes" not in detail["body"]
