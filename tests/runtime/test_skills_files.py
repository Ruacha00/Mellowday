"""I03 文件层测试：技能创建 / 演化 / 版本号 / frontmatter 往返，以及在线演化的写入路径。

覆盖：
(c) `create_skill_file` / `evolve_skill_file` 版本号递增，写出的 SKILL.md 可再次解析且往返一致；
    版本快照、使用日志、归档目录都落在 `MELLOWDAY_DATA_DIR` 下。
    在线演化（`online_ingest` 等）在离线桩模型下完成实时写入 —— 不经过也不依赖评测阻断。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mellowday import paths
from mellowday.runtime.skills import (
    OnlineSkillCandidate,
    create_skill,
    create_skill_file,
    discover_skills,
    evaluate_online_skill_evolution_async,
    evolve_skill,
    evolve_skill_file,
    extract_online_skill_candidate,
    format_frontmatter,
    format_skill_stats,
    get_skill_by_name,
    judge_retrieved_skill_usage,
    load_skill_stats,
    online_ingest,
    parse_frontmatter,
    record_feedback,
    record_skill_feedback,
    record_skill_invocation,
    record_usage_judgments,
    reset_skill_cache,
    resolve_skill_file,
    skill_stats,
)

SKILL_NAME = "每周回顾"
SKILL_DESCRIPTION = "梳理本周完成与未完成的待办，生成本周总结与下周计划"
SKILL_WHEN = "当用户要求做每周回顾、周总结或复盘本周安排时使用"
SKILL_BODY = "# 步骤\n\n1. 列出本周完成的待办\n2. 列出未完成的待办\n3. 给出下周计划"


@pytest.fixture(autouse=True)
def _isolated_skill_cache():
    reset_skill_cache()
    yield
    reset_skill_cache()


def _read(skill_file: Path):
    raw = skill_file.read_text(encoding="utf-8")
    parsed = parse_frontmatter(raw)
    return raw, parsed


def test_create_skill_file_version_and_frontmatter_roundtrip(isolated_data_dir: Path) -> None:
    result = create_skill_file(
        name=SKILL_NAME,
        description=SKILL_DESCRIPTION,
        instructions=SKILL_BODY,
        when_to_use=SKILL_WHEN,
        target="project",
        context="inline",
        user_invocable=True,
        tags=["回顾", "待办"],
    )
    assert result["ok"] is True, result
    skill_file = Path(result["file"])
    assert skill_file.name == "SKILL.md"
    assert skill_file.parent.parent == paths.skills_dir()
    assert skill_file.is_file()

    raw, parsed = _read(skill_file)
    assert parsed.meta["name"] == SKILL_NAME
    assert parsed.meta["version"] == "0.1.0"
    assert parsed.meta["description"] == SKILL_DESCRIPTION
    assert parsed.meta["when-to-use"] == SKILL_WHEN
    assert parsed.meta["user-invocable"] == "true"
    assert parsed.meta["context"] == "inline"
    assert parsed.meta["tags"] == "回顾,待办"
    assert parsed.body.startswith("# 步骤")
    assert "给出下周计划" in parsed.body

    # frontmatter 往返一致：重新格式化后再次解析得到同样的 meta / body。
    reformatted = format_frontmatter(parsed.meta, parsed.body)
    assert reformatted == raw.rstrip("\n")
    again = parse_frontmatter(reformatted)
    assert again.meta == parsed.meta
    assert again.body == parsed.body

    # 重复创建同名技能：拒绝而不是覆盖。
    duplicate = create_skill_file(name=SKILL_NAME, description="重复", instructions="# 重复")
    assert duplicate["ok"] is False
    assert "already exists" in duplicate["error"]

    # 创建事件写入演化目录。
    evolution_dir = paths.evolution_dir()
    usage_log = evolution_dir / "usage.jsonl"
    assert usage_log.is_file()
    events = [json.loads(line) for line in usage_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert events[0]["event"] == "create"
    assert events[0]["skill"] == SKILL_NAME
    assert not str(usage_log).startswith(str(paths.skills_dir()))


def test_evolve_skill_file_bumps_version_and_keeps_content_parseable(isolated_data_dir: Path) -> None:
    created = create_skill_file(
        name=SKILL_NAME,
        description=SKILL_DESCRIPTION,
        instructions=SKILL_BODY,
        when_to_use=SKILL_WHEN,
        tags=["回顾", "待办"],
    )
    skill_file = Path(created["file"])
    _, before = _read(skill_file)
    body_before = before.body

    first = evolve_skill_file(skill_name=SKILL_NAME, lesson="先给出结论再列细节", rationale="用户两次纠正")
    assert first["ok"] is True, first
    assert first["version"] == "0.1.1"
    assert Path(first["file"]) == skill_file

    _, after_first = _read(skill_file)
    assert after_first.meta["version"] == "0.1.1"
    assert after_first.meta["evolution-count"] == "1"
    assert after_first.meta["last-evolved"]
    assert "## Evolution Notes" in after_first.body
    assert "先给出结论再列细节" in after_first.body
    assert body_before.strip() in after_first.body
    # 演化后仍可往返解析。
    assert parse_frontmatter(format_frontmatter(after_first.meta, after_first.body)).meta == after_first.meta

    second = evolve_skill_file(
        skill_name=SKILL_NAME,
        lesson="每周一早上发出提醒",
        description="梳理本周待办并生成总结（含提醒）",
        when_to_use=SKILL_WHEN,
        tags=["提醒"],
    )
    assert second["ok"] is True, second
    assert second["version"] == "0.1.2"

    _, after_second = _read(skill_file)
    assert after_second.meta["version"] == "0.1.2"
    assert after_second.meta["evolution-count"] == "2"
    assert after_second.meta["description"] == "梳理本周待办并生成总结（含提醒）"
    assert after_second.meta["tags"] == "回顾,待办,提醒"
    assert "每周一早上发出提醒" in after_second.body
    assert "先给出结论再列细节" in after_second.body
    assert body_before.strip() in after_second.body

    # 版本快照落在演化目录，按技能 slug 归档。
    history_files = list((paths.evolution_dir() / "history").glob("*.jsonl"))
    assert len(history_files) == 1
    snapshots = [json.loads(line) for line in history_files[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [item["version"] for item in snapshots] == ["0.1.0", "0.1.1"]
    assert snapshots[0]["content"].startswith("---")

    assert resolve_skill_file(SKILL_NAME, target="project") == skill_file
    assert resolve_skill_file(SKILL_NAME, target="user") == skill_file
    assert resolve_skill_file("不存在的技能") is None


def test_create_and_evolve_wrappers_discover_and_record_stats(isolated_data_dir: Path) -> None:
    created = create_skill(
        name="会议纪要整理",
        description="把会议记录整理成决议摘要与待办清单",
        instructions="# 步骤\n1. 提取决议\n2. 输出待办",
        when_to_use="当用户提供会议记录时使用",
    )
    assert created["ok"] is True
    assert get_skill_by_name("会议纪要整理") is not None

    evolved = evolve_skill(skill_name="会议纪要整理", lesson="先列决议再列待办")
    assert evolved["ok"] is True
    assert evolved["version"] == "0.1.1"

    record_skill_invocation(skill_name="会议纪要整理", source="project", context="inline", args="今天的会议")
    record_feedback("会议纪要整理", "up", "很好用")
    record_skill_feedback(skill_name="会议纪要整理", rating="up", note="补充反馈")

    stats = load_skill_stats()
    assert stats["会议纪要整理"]["created"] == 1
    assert stats["会议纪要整理"]["invocations"] == 1
    assert stats["会议纪要整理"]["feedback"] == 2
    assert stats["会议纪要整理"]["evolutions"] == 1
    assert stats["会议纪要整理"]["version"] == "0.1.1"

    rendered = format_skill_stats()
    assert "会议纪要整理" in rendered
    assert skill_stats() == rendered


def test_usage_judgments_archive_stale_skill_into_archive_dir(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_skill(
        name="临时技能",
        description="一个从未被采用的技能",
        instructions="# 步骤\n1. 试试看",
    )
    skill_file = Path(created["file"])
    skill_dir = skill_file.parent
    assert skill_dir.parent == paths.skills_dir()

    monkeypatch.setenv("MELLOWDAY_SKILL_PRUNE_PROJECT", "1")
    judgments = [
        {"name": "临时技能", "skill_dir": str(skill_dir), "source": "project", "relevant": False, "used": False}
        for _ in range(40)
    ]
    result = record_usage_judgments(judgments)
    assert result["ok"] is True
    assert result["pruned"] == ["临时技能"]

    archived = list(paths.skills_archive_dir().glob("临时技能-*"))
    assert len(archived) == 1
    assert (archived[0] / "SKILL.md").is_file()
    assert not skill_dir.exists()

    reset_skill_cache()
    # 归档目录不再参与发现（.archive 下没有直接的 SKILL.md）。
    assert [skill.name for skill in discover_skills()] == []
    stats = load_skill_stats()
    assert stats["临时技能"]["retrieved"] == 40
    assert stats["临时技能"]["pruned"] is True


@pytest.mark.anyio
async def test_extract_online_skill_candidate_parses_and_rejects_weak_evidence() -> None:
    async def side_query(system: str, payload: str) -> str:
        assert "Extractor" in system
        assert json.loads(payload)["messages"]
        return (
            '说明文字 {"skills": [{"name": "会议待办提取", '
            '"description": "把会议记录整理成待办清单", '
            '"when_to_use": "当用户给出会议记录时", '
            '"instructions": "# 步骤\\n1. 提取决议", '
            '"evidence": "用户要求以后都这样", "tags": "会议，待办"}]} 结尾'
        )

    candidate = await extract_online_skill_candidate(
        messages=[{"role": "user", "content": "以后会议记录都帮我整理成待办"}],
        side_query=side_query,
    )
    assert isinstance(candidate, OnlineSkillCandidate)
    assert candidate is not None
    assert candidate.name == "会议待办提取"
    assert candidate.tags == ["会议", "待办"]

    async def empty_side_query(system: str, payload: str) -> str:
        return '{"skills": []}'

    assert (
        await extract_online_skill_candidate(messages=[{"role": "user", "content": "随口一说"}], side_query=empty_side_query)
        is None
    )


@pytest.mark.anyio
async def test_online_ingest_writes_skill_live_without_eval_gate(isolated_data_dir: Path) -> None:
    async def side_query(system: str, payload: str) -> str:
        if "Extractor" in system:
            return json.dumps(
                {
                    "skills": [
                        {
                            "name": "会议待办提取",
                            "description": "把会议记录整理成待办清单",
                            "when_to_use": "当用户给出会议记录并要求整理待办时",
                            "instructions": "# 步骤\n1. 提取决议\n2. 输出待办",
                            "evidence": "用户明确要求长期这样做",
                            "tags": ["会议", "待办"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps({"action": "add", "reason": "没有同类技能"}, ensure_ascii=False)

    result = await online_ingest(
        messages=[
            {"role": "user", "content": "以后会议记录都帮我整理成待办"},
            {"role": "assistant", "content": "好的"},
        ],
        side_query=side_query,
    )
    assert result["ok"] is True, result
    assert result["action"] == "add"

    reset_skill_cache()
    skill = get_skill_by_name("会议待办提取")
    assert skill is not None
    assert skill.source == "project"
    assert Path(skill.skill_dir).parent == paths.skills_dir()

    # 实时写入不经过评测：没有生成任何评测报告。
    assert not (paths.evolution_dir() / "online_eval_report.json").exists()
    # 溯源记录写入演化目录。
    assert (paths.evolution_dir() / "online_provenance.jsonl").is_file()
    provenance = json.loads((paths.evolution_dir() / "online_skill_provenance.json").read_text(encoding="utf-8"))
    assert provenance["会议待办提取"]["last_action"] == "add"


@pytest.mark.anyio
async def test_online_ingest_respects_write_denial(isolated_data_dir: Path) -> None:
    async def side_query(system: str, payload: str) -> str:
        if "Extractor" in system:
            return json.dumps(
                {
                    "skills": [
                        {
                            "name": "被拒绝的技能",
                            "description": "用户拒绝写入的技能",
                            "instructions": "# 步骤\n1. 不应落盘",
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps({"action": "add"}, ensure_ascii=False)

    async def deny(summary: str) -> bool:
        assert "online skill evolution" in summary
        return False

    result = await online_ingest(
        messages=[{"role": "user", "content": "以后都这样"}, {"role": "assistant", "content": "好的"}],
        side_query=side_query,
        confirm_write=deny,
    )
    assert result["ok"] is False
    assert result["action"] == "add_denied"
    reset_skill_cache()
    assert get_skill_by_name("被拒绝的技能") is None


@pytest.mark.anyio
async def test_judge_retrieved_skill_usage_heuristic_and_judge_paths() -> None:
    hits = [
        {
            "name": "会议纪要整理",
            "source": "project",
            "skill_dir": "/tmp/会议纪要整理",
            "score": 0.72,
        }
    ]
    heuristic = await judge_retrieved_skill_usage(
        hits=hits,
        user_message="把会议记录整理一下",
        assistant_text="我会按 会议纪要整理 的流程输出决议和待办。",
    )
    assert len(heuristic) == 1
    assert heuristic[0]["retrieved"] is True
    assert heuristic[0]["relevant"] is False
    assert heuristic[0]["used"] is True
    assert heuristic[0]["score"] == 0.72

    async def side_query(system: str, payload: str) -> str:
        return json.dumps(
            {"judgments": [{"name": "会议纪要整理", "relevant": True, "used": True, "reason": "按技能流程输出"}]},
            ensure_ascii=False,
        )

    judged = await judge_retrieved_skill_usage(
        hits=hits,
        user_message="把会议记录整理一下",
        assistant_text="决议：……待办：……",
        side_query=side_query,
    )
    assert judged[0]["relevant"] is True
    assert judged[0]["used"] is True
    assert judged[0]["reason"] == "按技能流程输出"
    assert await judge_retrieved_skill_usage(hits=[], user_message="x", assistant_text="y") == []


@pytest.mark.anyio
async def test_online_eval_runs_offline_in_isolated_data_dir(isolated_data_dir: Path) -> None:
    report = await evaluate_online_skill_evolution_async()
    assert isinstance(report, dict)
    assert "aggregate" in report
    assert report["aggregate"]["online_ingests"] == 0
    assert report["llm_judge"]["enabled"] is False
    assert (paths.evolution_dir() / "online_eval_report.json").is_file()
