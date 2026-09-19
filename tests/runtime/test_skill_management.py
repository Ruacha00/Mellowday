"""I24a 运行时测试：技能查看、停用/恢复、版本历史与版本回退。

核心验收（对应 docs/issues/BOARD.md 的 I24 与 CONTRACTS.md 6quinquies）：

* list_skills 能列出技能的版本、启用状态、来源与路径；
* **停用必须真的影响检索**：停用后 discover_skills / build_skill_descriptions /
  retrieve_relevant_skills 都不再返回该技能，恢复后必须重新出现；
* 版本列表能看到历史版本，回退必须把内容真的换回旧版本，且回退动作本身在版本列表可见。

全部离线：不读 .env、不发网络请求；技能创建在隔离的 MELLOWDAY_DATA_DIR 下。
技能名与描述都是中文，用来锁住 cp936 环境下必须显式 utf-8 的文件 IO。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mellowday import paths
from mellowday.runtime.skills import (
    SkillManagementError,
    UnknownSkillError,
    build_skill_descriptions,
    create_skill_file,
    disable_skill,
    discover_skills,
    enable_skill,
    evolve_skill_file,
    get_skill_by_name,
    list_skill_versions,
    list_skills,
    parse_frontmatter,
    record_usage_judgments,
    reset_skill_cache,
    restore_skill_version,
    retrieve_relevant_skills,
)

REQUIRED_KEYS = {"name", "description", "version", "enabled", "source", "path"}

NAME_A = "每周回顾"
NAME_B = "会议纪要整理"
NAME_C = "旅行行程规划"

DESC_A = "梳理本周完成与未完成的待办，生成本周总结与下周计划"
DESC_B = "把会议记录整理成决议摘要与待办清单"
WHEN_A = "当用户要求做每周回顾、周总结或复盘本周安排时使用"
WHEN_B = "当用户提供会议记录并要求整理时使用"

BODY_A = "# 步骤\n\n1. 先列已完成\n2. 再列未完成"
BODY_B = "# 步骤\n\n1. 提取决议\n2. 输出待办"

QUERY_A = "帮我做每周回顾和周总结"
QUERY_B = "整理一下会议纪要"


@pytest.fixture(autouse=True)
def _isolated_skill_cache():
    """技能发现是进程级缓存，每个用例前后都必须清空。"""
    reset_skill_cache()
    yield
    reset_skill_cache()


@pytest.fixture
def zh_skills(isolated_data_dir: Path) -> dict[str, Path]:
    """在隔离数据目录里建三个中文技能，返回 名字 -> SKILL.md 路径。"""
    created: dict[str, Path] = {}
    for name, description, when_to_use, body in (
        (NAME_A, DESC_A, WHEN_A, BODY_A),
        (NAME_B, DESC_B, WHEN_B, BODY_B),
        (NAME_C, "把出行需求整理成按天的行程安排", "当用户说要安排旅行或出差行程时使用", "# 步骤\n\n1. 收集日期\n2. 输出行程"),
    ):
        result = create_skill_file(
            name=name, description=description, instructions=body, when_to_use=when_to_use
        )
        assert result["ok"] is True, result
        created[name] = Path(result["file"])
    reset_skill_cache()
    return created


def _names(skills) -> set[str]:
    return {skill.name for skill in skills}


def _hit_names(query: str) -> list[str]:
    return [str(hit.get("name")) for hit in retrieve_relevant_skills(query, limit=5)]


# ------------------------------------------------------------------ 查看


def test_list_skills_reports_version_status_source_and_path(zh_skills, isolated_data_dir: Path) -> None:
    entries = list_skills()
    assert [entry["name"] for entry in entries] == sorted([NAME_A, NAME_B, NAME_C])
    for entry in entries:
        assert REQUIRED_KEYS <= set(entry), entry
        assert entry["version"] == "0.1.0"
        assert entry["enabled"] is True
        assert entry["source"] == "project"
        assert entry["archived_to"] == ""
        assert entry["updated_at"]
        skill_file = Path(entry["path"])
        assert skill_file.is_file() and skill_file.name == "SKILL.md"
        assert skill_file.parent.parent == paths.skills_dir()

    by_name = {entry["name"]: entry for entry in entries}
    assert by_name[NAME_A]["description"] == DESC_A
    assert by_name[NAME_B]["description"] == DESC_B


def test_list_skills_is_empty_without_any_skill(isolated_data_dir: Path) -> None:
    assert list_skills() == []
    assert discover_skills() == []


# -------------------------------------------------- 停用 / 恢复影响检索


def test_disable_removes_skill_from_discovery_retrieval_and_descriptions(
    zh_skills, isolated_data_dir: Path
) -> None:
    skill_file = zh_skills[NAME_A]

    # 先热一次缓存：如果停用后没有刷新缓存，下面的断言就会失败。
    assert NAME_A in _names(discover_skills())
    assert NAME_A in _hit_names(QUERY_A)
    assert NAME_A in build_skill_descriptions()

    disabled = disable_skill(NAME_A)
    assert disabled["ok"] is True, disabled
    assert disabled["name"] == NAME_A
    assert disabled["changed"] is True

    archived_dir = Path(disabled["archived_to"])
    assert archived_dir.parent == paths.skills_archive_dir()
    assert (archived_dir / "SKILL.md").is_file()
    assert disabled["path"] == str(archived_dir / "SKILL.md")
    assert not skill_file.exists()
    assert not skill_file.parent.exists()

    # 核心：停用后三个入口都不得再返回该技能。
    assert NAME_A not in _names(discover_skills())
    assert get_skill_by_name(NAME_A) is None
    assert NAME_A not in _hit_names(QUERY_A)
    assert _hit_names(QUERY_A) == []
    assert NAME_A not in build_skill_descriptions()
    assert NAME_B in _hit_names(QUERY_B)

    listed = {entry["name"]: entry for entry in list_skills()}
    assert listed[NAME_A]["enabled"] is False
    assert listed[NAME_A]["archived_to"] == str(archived_dir)
    assert listed[NAME_A]["version"] == "0.1.0"
    assert listed[NAME_B]["enabled"] is True

    enabled = enable_skill(NAME_A)
    assert enabled["ok"] is True, enabled
    assert enabled["changed"] is True
    assert Path(enabled["path"]).is_file()
    assert not archived_dir.exists()

    # 恢复后必须重新出现在发现、检索与描述里。
    assert NAME_A in _names(discover_skills())
    assert NAME_A in _hit_names(QUERY_A)
    assert NAME_A in build_skill_descriptions()
    assert get_skill_by_name(NAME_A) is not None
    assert {entry["name"]: entry["enabled"] for entry in list_skills()}[NAME_A] is True


def test_disabled_skill_disappears_from_the_system_prompt(zh_skills, isolated_data_dir: Path) -> None:
    """停用必须影响后续会话：新会话组装的系统提示里不能再出现被停用的技能。"""
    from mellowday.runtime.prompt import build_system_prompt

    assert NAME_A in build_system_prompt()

    assert disable_skill(NAME_A)["ok"] is True
    after_disable = build_system_prompt()
    assert NAME_A not in after_disable
    assert NAME_B in after_disable  # 只影响被停用的那一个

    assert enable_skill(NAME_A)["ok"] is True
    assert NAME_A in build_system_prompt()


def test_disable_and_enable_are_idempotent(zh_skills, isolated_data_dir: Path) -> None:
    first = disable_skill(NAME_C)
    second = disable_skill(NAME_C)
    assert first["ok"] is True and second["ok"] is True
    assert second["changed"] is False
    assert second["archived_to"] == first["archived_to"]

    back = enable_skill(NAME_C)
    again = enable_skill(NAME_C)
    assert back["ok"] is True and back["changed"] is True
    assert again["ok"] is True and again["changed"] is False
    assert again["path"] == back["path"]
    assert NAME_C in _names(discover_skills())


def test_disable_archives_the_whole_skill_directory(zh_skills, isolated_data_dir: Path) -> None:
    skill_dir = zh_skills[NAME_A].parent
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "notes.md").write_text("# 参考：每周回顾模板\n", encoding="utf-8")

    disabled = disable_skill(NAME_A)
    assert disabled["ok"] is True
    archived = Path(disabled["archived_to"])
    assert (archived / "references" / "notes.md").read_text(encoding="utf-8") == "# 参考：每周回顾模板\n"

    enabled = enable_skill(NAME_A)
    restored_dir = Path(enabled["path"]).parent
    assert (restored_dir / "references" / "notes.md").is_file()


def test_chinese_content_survives_archive_and_enable(zh_skills, isolated_data_dir: Path) -> None:
    skill_file = zh_skills[NAME_B]
    original = skill_file.read_text(encoding="utf-8")
    assert NAME_B in original and DESC_B in original

    disabled = disable_skill(NAME_B)
    archived_file = Path(disabled["archived_to"]) / "SKILL.md"
    assert archived_file.read_text(encoding="utf-8") == original

    enabled = enable_skill(NAME_B)
    assert Path(enabled["path"]).read_text(encoding="utf-8") == original


def test_enable_recovers_a_skill_archived_by_usage_pruning(zh_skills, isolated_data_dir: Path, monkeypatch) -> None:
    """归档目录与既有自动剪枝共用一套约定，恢复入口同样能把剪枝掉的技能拿回来。"""
    skill_dir = zh_skills[NAME_C].parent
    monkeypatch.setenv("MELLOWDAY_SKILL_PRUNE_PROJECT", "1")
    judgments = [
        {"name": NAME_C, "skill_dir": str(skill_dir), "source": "project", "relevant": False, "used": False}
        for _ in range(40)
    ]
    assert record_usage_judgments(judgments)["pruned"] == [NAME_C]
    reset_skill_cache()
    assert NAME_C not in _names(discover_skills())
    assert NAME_C not in _hit_names("安排旅行行程")

    listed = {entry["name"]: entry for entry in list_skills()}
    assert listed[NAME_C]["enabled"] is False
    assert listed[NAME_A]["enabled"] is True

    restored = enable_skill(NAME_C)
    assert restored["ok"] is True and restored["changed"] is True
    assert NAME_C in _names(discover_skills())
    assert {entry["name"]: entry["enabled"] for entry in list_skills()}[NAME_C] is True


# ------------------------------------------------------- 版本与版本回退


def test_list_skill_versions_history_newest_first(zh_skills, isolated_data_dir: Path) -> None:
    skill_file = zh_skills[NAME_A]
    assert [item["version"] for item in list_skill_versions(NAME_A)] == ["0.1.0"]

    first = evolve_skill_file(skill_name=NAME_A, lesson="先给出结论再列细节")
    second = evolve_skill_file(skill_name=NAME_A, lesson="每周一早上发出提醒")
    assert (first["version"], second["version"]) == ("0.1.1", "0.1.2")

    versions = list_skill_versions(NAME_A)
    assert [item["version"] for item in versions] == ["0.1.2", "0.1.1", "0.1.0"]
    assert versions[0]["current"] is True
    assert versions[0]["path"] == str(skill_file)
    assert versions[0]["source"] == "active"
    for item in versions:
        assert item["updated_at"]
        assert item["path"]
    assert {item["version"]: item["current"] for item in versions} == {
        "0.1.2": True,
        "0.1.1": False,
        "0.1.0": False,
    }
    # 历史版本指向记录内容的 history 文件，当前版本指向 SKILL.md。
    assert Path(versions[1]["path"]).name.endswith(".jsonl")
    assert versions[1]["path"] != versions[0]["path"]


def test_restore_skill_version_swaps_content_back_and_is_visible(zh_skills, isolated_data_dir: Path) -> None:
    skill_file = zh_skills[NAME_A]
    evolve_skill_file(skill_name=NAME_A, lesson="先给出结论再列细节")
    evolve_skill_file(skill_name=NAME_A, lesson="每周一早上发出提醒")
    before = skill_file.read_text(encoding="utf-8")
    assert "先给出结论再列细节" in before
    assert "每周一早上发出提醒" in before

    result = restore_skill_version(NAME_A, "0.1.0")
    assert result["ok"] is True, result
    assert result["name"] == NAME_A
    assert result["restored_from"] == "0.1.0"
    assert result["version"] == "0.1.3"  # 回退记为新版本（补丁位 +1）
    assert result["path"] == str(skill_file)
    assert result["changed"] is True

    after_raw = skill_file.read_text(encoding="utf-8")
    parsed = parse_frontmatter(after_raw)
    assert parsed.meta["name"] == NAME_A
    assert parsed.meta["version"] == "0.1.3"
    assert parsed.meta["restored-from"] == "0.1.0"
    assert parsed.meta["restored-at"]
    assert parsed.meta["description"] == DESC_A
    # 内容真的换回了旧版本：后续演化写进去的东西不在了。
    assert parsed.body == BODY_A
    assert "先给出结论再列细节" not in after_raw
    assert "每周一早上发出提醒" not in after_raw

    # 回退动作本身在版本列表里可见。
    versions = list_skill_versions(NAME_A)
    assert [item["version"] for item in versions] == ["0.1.3", "0.1.2", "0.1.1", "0.1.0"]
    assert versions[0]["current"] is True

    # 检索/加载拿到的是回退后的内容。
    skill = get_skill_by_name(NAME_A)
    assert skill is not None and skill.prompt_template == BODY_A
    assert NAME_A in _hit_names(QUERY_A)


def test_restore_is_itself_reversible(zh_skills, isolated_data_dir: Path) -> None:
    skill_file = zh_skills[NAME_A]
    evolve_skill_file(skill_name=NAME_A, lesson="先给出结论再列细节")
    evolve_skill_file(skill_name=NAME_A, lesson="每周一早上发出提醒")

    assert restore_skill_version(NAME_A, "0.1.0")["ok"] is True
    again = restore_skill_version(NAME_A, "0.1.2")
    assert again["ok"] is True and again["changed"] is True
    assert again["restored_from"] == "0.1.2"
    assert again["version"] == "0.1.4"

    parsed = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    assert "先给出结论再列细节" in parsed.body
    assert "每周一早上发出提醒" in parsed.body
    assert parsed.meta["restored-from"] == "0.1.2"
    assert [item["version"] for item in list_skill_versions(NAME_A)] == [
        "0.1.4",
        "0.1.3",
        "0.1.2",
        "0.1.1",
        "0.1.0",
    ]


def test_restore_current_version_changes_nothing(zh_skills, isolated_data_dir: Path) -> None:
    skill_file = zh_skills[NAME_A]
    before = skill_file.read_text(encoding="utf-8")

    result = restore_skill_version(NAME_A, "0.1.0")
    assert result["ok"] is True
    assert result["changed"] is False
    assert result["version"] == "0.1.0"
    assert skill_file.read_text(encoding="utf-8") == before
    assert [item["version"] for item in list_skill_versions(NAME_A)] == ["0.1.0"]


# ------------------------------------------------------------ 非法输入


def test_unknown_skill_and_version_return_structured_failures(zh_skills, isolated_data_dir: Path) -> None:
    for result in (disable_skill("不存在的技能"), enable_skill("不存在的技能")):
        assert result["ok"] is False
        assert result["error_code"] == "skill_not_found"
        assert result["error"]

    missing_version = restore_skill_version(NAME_A, "9.9.9")
    assert missing_version["ok"] is False
    assert missing_version["error_code"] == "version_not_found"
    assert "9.9.9" in missing_version["error"]

    missing_skill = restore_skill_version("不存在的技能", "0.1.0")
    assert missing_skill["ok"] is False and missing_skill["error_code"] == "skill_not_found"


def test_invalid_names_and_versions_are_rejected(zh_skills, isolated_data_dir: Path) -> None:
    for result in (disable_skill(""), enable_skill("   "), restore_skill_version("", "0.1.0")):
        assert result["ok"] is False
        assert result["error_code"] == "invalid_name"

    blank_version = restore_skill_version(NAME_A, "  ")
    assert blank_version["ok"] is False
    assert blank_version["error_code"] == "version_required"

    with pytest.raises(UnknownSkillError):
        list_skill_versions("不存在的技能")
    with pytest.raises(SkillManagementError):
        list_skill_versions("   ")
    # 两个异常都必须是明确的 ValueError，网页层据此映射 404 / 400。
    assert issubclass(UnknownSkillError, ValueError)
    assert issubclass(SkillManagementError, ValueError)


def test_failed_restore_leaves_the_skill_untouched(zh_skills, isolated_data_dir: Path) -> None:
    skill_file = zh_skills[NAME_A]
    evolve_skill_file(skill_name=NAME_A, lesson="先给出结论再列细节")
    before = skill_file.read_text(encoding="utf-8")
    history = paths.evolution_dir() / "history" / f"{NAME_A}.jsonl"
    history_lines = len([line for line in history.read_text(encoding="utf-8").splitlines() if line.strip()])

    result = restore_skill_version(NAME_A, "9.9.9")
    assert result["ok"] is False
    assert skill_file.read_text(encoding="utf-8") == before
    assert len([line for line in history.read_text(encoding="utf-8").splitlines() if line.strip()]) == history_lines


def test_restore_is_refused_while_the_skill_is_disabled(zh_skills, isolated_data_dir: Path) -> None:
    assert disable_skill(NAME_A)["ok"] is True

    result = restore_skill_version(NAME_A, "0.1.0")
    assert result["ok"] is False
    assert result["error_code"] == "skill_disabled"
    assert result["error"]

    # 停用期间版本历史仍然可查，只是来源是归档目录。
    versions = list_skill_versions(NAME_A)
    assert versions[0]["current"] is True
    assert versions[0]["source"] == "archived"
    assert Path(versions[0]["path"]).parent.parent == paths.skills_archive_dir()


def test_management_events_are_recorded_in_the_evolution_log(zh_skills, isolated_data_dir: Path) -> None:
    disable_skill(NAME_A)
    enable_skill(NAME_A)
    evolve_skill_file(skill_name=NAME_A, lesson="先给出结论再列细节")
    restore_skill_version(NAME_A, "0.1.0")

    usage_log = paths.evolution_dir() / "usage.jsonl"
    rows = [json.loads(line) for line in usage_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [row["event"] for row in rows if row.get("skill") == NAME_A]
    assert "disable" in events
    assert "enable" in events
    assert "restore" in events
