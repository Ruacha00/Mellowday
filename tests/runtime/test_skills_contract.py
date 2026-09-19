"""I03 契约测试：`mellowday.runtime.skills` 的公开导出与包内硬性约束。

对应 CONTRACTS.md 4.5 —— 下列契约符号必须能从 `mellowday.runtime.skills` 直接导入；
同时守住三条硬约束：技能根目录只来自 `mellowday.paths`、只用词项检索（无向量库/新依赖）、
公开代码中不出现来源项目名称。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

# (a) 直接导入全部契约符号：任何缺失都会让本模块在收集阶段就失败。
from mellowday.runtime.skills import (  # noqa: F401
    SkillDefinition,
    build_skill_descriptions,
    create_skill,
    create_skill_file,
    discover_skills,
    evolve_skill,
    evolve_skill_file,
    execute_skill,
    extract_online_skill_candidate,
    format_retrieved_skill_context,
    format_skill_stats,
    get_skill_by_name,
    judge_retrieved_skill_usage,
    load_skill_stats,
    maintain_online_skill_candidate,
    online_ingest,
    record_feedback,
    record_online_provenance,
    record_skill_feedback,
    record_skill_invocation,
    record_usage_judgments,
    reset_skill_cache,
    resolve_skill_file,
    resolve_skill_prompt,
    retrieve_relevant_skills,
    skill_stats,
)

import mellowday.runtime.skills as skills_pkg
from mellowday import paths
from mellowday.runtime.skills import format_frontmatter

CONTRACT_SYMBOLS = [
    # 发现 / 元信息 / 检索 / 加载
    "SkillDefinition",
    "discover_skills",
    "get_skill_by_name",
    "execute_skill",
    "resolve_skill_prompt",
    "build_skill_descriptions",
    "retrieve_relevant_skills",
    "format_retrieved_skill_context",
    "reset_skill_cache",
    "create_skill",
    "evolve_skill",
    "record_feedback",
    "skill_stats",
    "record_usage_judgments",
    # 演化与评测
    "create_skill_file",
    "evolve_skill_file",
    "resolve_skill_file",
    "load_skill_stats",
    "format_skill_stats",
    "record_skill_invocation",
    "record_skill_feedback",
    "record_online_provenance",
    "extract_online_skill_candidate",
    "maintain_online_skill_candidate",
    "online_ingest",
    "judge_retrieved_skill_usage",
]

PACKAGE_DIR = Path(skills_pkg.__file__).resolve().parent


@pytest.fixture(autouse=True)
def _isolated_skill_cache():
    """技能发现带进程级缓存，每个用例前后都必须清空。"""
    reset_skill_cache()
    yield
    reset_skill_cache()


def test_contract_symbols_are_all_exported() -> None:
    missing = [name for name in CONTRACT_SYMBOLS if not hasattr(skills_pkg, name)]
    assert missing == [], f"缺失契约符号: {missing}"
    not_declared = [name for name in CONTRACT_SYMBOLS if name not in skills_pkg.__all__]
    assert not_declared == [], f"未声明在 __all__: {not_declared}"


def test_skill_definition_keeps_source_fields() -> None:
    skill = SkillDefinition(name="demo", description="描述")
    assert skill.user_invocable is True
    assert skill.context == "inline"
    assert skill.source == "project"
    assert skill.prompt_template == ""
    assert skill.skill_dir == ""


# 来源项目名称在公开代码中不得出现；这里用片段拼接，避免测试自身引入该名称。
_FORBIDDEN_NAME_FRAGMENTS = ("be" + "ar", "be" + "arcode")


def _forbidden_source_name_re() -> "re.Pattern[str]":
    pattern = "|".join(rf"\b{fragment}\b" for fragment in _FORBIDDEN_NAME_FRAGMENTS)
    return re.compile(pattern, re.IGNORECASE)


def test_package_contains_no_source_project_names() -> None:
    banned = _forbidden_source_name_re()
    offenders = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if banned.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert offenders == [], "公开代码中不得出现来源项目名称: " + "; ".join(offenders)


def test_package_has_no_external_or_vector_dependencies() -> None:
    banned = (
        "numpy",
        "faiss",
        "sentence_transformers",
        "chromadb",
        "sklearn",
        "torch",
        "requests",
        "openai",
        "anthropic",
    )
    offenders = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            assert "agents" not in stripped, f"{path.name}:{lineno} 仍在导入 agents.*: {stripped}"
            for module in banned:
                if re.match(rf"(from|import)\s+{module}\b", stripped):
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert offenders == [], "检索必须保持词项路线，不得引入向量库/新依赖: " + "; ".join(offenders)


def test_skill_roots_follow_mellowday_data_dir(isolated_data_dir: Path) -> None:
    assert paths.skills_dir() == isolated_data_dir / "skills"
    assert paths.skills_archive_dir() == isolated_data_dir / "skills" / ".archive"
    assert paths.evolution_dir() == isolated_data_dir / "skill_evolution"


def test_discovery_reads_from_data_dir_skills_root(isolated_data_dir: Path) -> None:
    skill_dir = paths.skills_dir() / "weekly"
    skill_dir.mkdir(parents=True)
    body = "# 周报规则\n\n请输出 $ARGUMENTS 的摘要。"
    (skill_dir / "SKILL.md").write_text(
        format_frontmatter({"name": "weekly", "description": "每周总结", "when-to-use": "用户要周报时"}, body),
        encoding="utf-8",
    )
    reset_skill_cache()

    found = discover_skills()
    assert [skill.name for skill in found] == ["weekly"]
    assert found[0].skill_dir == str(skill_dir)
    assert found[0].source == "project"
    assert found[0].when_to_use == "用户要周报时"
    assert found[0].prompt_template == body
    assert get_skill_by_name("weekly") is found[0]
    assert get_skill_by_name("missing") is None

    # 缓存：再次发现命中同一批对象，reset 后可重新扫描磁盘。
    assert discover_skills() == found
    reset_skill_cache()
    assert discover_skills()[0].skill_dir == str(skill_dir)

    assert execute_skill("missing", "") is None
    execution = execute_skill("weekly", "本周数据")
    assert execution is not None
    assert execution["context"] == "inline"
    assert execution["source"] == "project"
    assert execution["prompt"] == "# 周报规则\n\n请输出 本周数据 的摘要。"
    assert resolve_skill_prompt(found[0], "X") == "# 周报规则\n\n请输出 X 的摘要。"

    descriptions = build_skill_descriptions()
    assert "# Available Skills" in descriptions
    assert "/weekly" in descriptions

    context, top = format_retrieved_skill_context("帮我写一份每周总结")
    assert top is not None and top["name"] == "weekly"
    assert "<retrieved_skills>" in context
    assert format_retrieved_skill_context("zzz completely unrelated qqq")[1] is None


def test_discovery_ignores_cwd_and_legacy_skill_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """只认 MELLOWDAY_DATA_DIR/skills；不扫描 <cwd>、源码仓库或任何示例技能目录。"""
    for relative in ("skills", "legacy-skills", ".legacy-skills", "examples/skills"):
        decoy = tmp_path / relative / "decoy-skill"
        decoy.mkdir(parents=True)
        (decoy / "SKILL.md").write_text(
            format_frontmatter({"name": "decoy-skill", "description": "中文示例技能"}, "# 不应被加载"),
            encoding="utf-8",
        )
    monkeypatch.chdir(tmp_path)
    reset_skill_cache()

    assert discover_skills() == []
    assert retrieve_relevant_skills("中文示例技能 检索") == []
