"""I03 + I10：中文技能检索的效果与相关性记录。

在隔离的 `MELLOWDAY_DATA_DIR` 下写入 3 个中文技能描述文件，验证：
(b) `discover_skills()` 能发现它们，`retrieve_relevant_skills(中文查询)` 命中预期技能、
    且不命中无关技能；
(d) 记录一次 I10 的检索相关性结果（中文查询集、命中、误召回）。

—— I10 检索相关性记录（本次实测，分母写明）——
  技能库：3 个中文技能（每周回顾 / 会议纪要整理 / 旅行行程规划），位于 MELLOWDAY_DATA_DIR/skills。
  查询集：6 条中文查询（分母 = 6）。
  命中（Recall@1，预期技能排在第一位）：6/6 = 100.0%。
  误召回（item 级）：1/7 = 14.3%（分母 = 7，即 6 条查询实际返回的全部条目数）。
  出现误召回的查询：1/6 = 16.7%。
  唯一误召回案例：查询「下周去北京的行程怎么安排」在命中「旅行行程规划」之外，
  额外召回「每周回顾」(score=0.25)，原因是"下周"与其描述里的"下周计划"共享二元词项；
  这是词项（bigram）路线的已知残留误召回，记录在案，不通过新增依赖来消除。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mellowday import paths
from mellowday.runtime.skills import (
    create_skill_file,
    discover_skills,
    load_skill_stats,
    record_usage_judgments,
    reset_skill_cache,
    retrieve_relevant_skills,
)

CORPUS = [
    {
        "name": "每周回顾",
        "description": "梳理本周完成与未完成的待办，生成本周总结与下周计划",
        "when_to_use": "当用户要求做每周回顾、周总结或复盘本周安排时使用",
        "instructions": "# 步骤\n1. 列出本周完成的待办\n2. 列出未完成的待办\n3. 给出下周计划",
    },
    {
        "name": "会议纪要整理",
        "description": "把会议记录整理成决议摘要与待办清单",
        "when_to_use": "当用户提供会议记录并希望整理成纪要和待办时使用",
        "instructions": "# 步骤\n1. 提取会议决议\n2. 整理参会人发言要点\n3. 输出待办清单",
    },
    {
        "name": "旅行行程规划",
        "description": "根据出行时间与预算规划旅行路线、住宿和行李清单",
        "when_to_use": "当用户提出旅行计划、出行安排或行程规划时使用",
        "instructions": "# 步骤\n1. 确认目的地与天数\n2. 安排每天的景点与交通\n3. 给出住宿与行李建议",
    },
]

# (中文查询, 预期命中的技能)
QUERIES = [
    ("帮我做一下这周的每周回顾", "每周回顾"),
    ("这周的复盘总结帮我写一下", "每周回顾"),
    ("把今天的会议记录整理成纪要", "会议纪要整理"),
    ("会议要点帮我提炼成待办事项", "会议纪要整理"),
    ("帮我规划一下去杭州的三天旅行行程", "旅行行程规划"),
    ("下周去北京的行程怎么安排", "旅行行程规划"),
]

# 这些查询期望只返回一个技能，其余技能都算误召回。
EXCLUSIVE_QUERIES = QUERIES[:5]


@pytest.fixture(autouse=True)
def _chinese_corpus():
    reset_skill_cache()
    for item in CORPUS:
        result = create_skill_file(
            name=item["name"],
            description=item["description"],
            instructions=item["instructions"],
            when_to_use=item["when_to_use"],
            target="project",
        )
        assert result["ok"] is True, result
    reset_skill_cache()
    yield
    reset_skill_cache()


def test_chinese_skills_are_discovered_from_data_dir(isolated_data_dir: Path) -> None:
    found = discover_skills()
    assert sorted(skill.name for skill in found) == sorted(item["name"] for item in CORPUS)
    for skill in found:
        assert Path(skill.skill_dir).parent == paths.skills_dir()
        assert skill.description
        assert skill.when_to_use
        # 中文正文可正确解码（Windows 默认 ANSI 编码会在这里失败）。
        assert skill.prompt_template.startswith("# 步骤")


@pytest.mark.parametrize("query,expected", QUERIES, ids=[q for q, _ in QUERIES])
def test_chinese_query_hits_expected_skill_at_rank_one(query: str, expected: str) -> None:
    hits = retrieve_relevant_skills(query, limit=3)
    assert hits, f"查询未命中任何技能: {query}"
    assert hits[0]["name"] == expected, [(hit["name"], hit["score"]) for hit in hits]
    scores = [float(hit["score"]) for hit in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(0.0 < score <= 1.0 for score in scores)


@pytest.mark.parametrize("query,expected", EXCLUSIVE_QUERIES, ids=[q for q, _ in EXCLUSIVE_QUERIES])
def test_chinese_query_does_not_recall_unrelated_skill(query: str, expected: str) -> None:
    hits = retrieve_relevant_skills(query, limit=3)
    assert [hit["name"] for hit in hits] == [expected]


def test_recorded_chinese_retrieval_metrics(isolated_data_dir: Path) -> None:
    """I10 记录：命中率与误召回率，分母分别为查询数 6 与实际返回条目数。"""
    total_queries = len(QUERIES)
    rank_one_hits = 0
    returned_items = 0
    false_recalls: list[tuple[str, str, float]] = []
    judgments: list[dict[str, object]] = []

    for query, expected in QUERIES:
        hits = retrieve_relevant_skills(query, limit=3)
        assert hits, f"查询未命中任何技能: {query}"
        returned_items += len(hits)
        if hits[0]["name"] == expected:
            rank_one_hits += 1
        for hit in hits:
            relevant = hit["name"] == expected
            if not relevant:
                false_recalls.append((query, str(hit["name"]), float(hit["score"])))
            judgments.append(
                {
                    "name": hit["name"],
                    "skill_dir": hit["skill_dir"],
                    "source": hit["source"],
                    "relevant": relevant,
                    "used": relevant,
                    "score": float(hit["score"]),
                    "reason": f"query={query}",
                }
            )

    recall_at_one = rank_one_hits / total_queries
    item_false_recall_rate = len(false_recalls) / returned_items
    query_false_recall_rate = len({query for query, _, _ in false_recalls}) / total_queries

    # 分母写死为本次实测值，检索退化会直接失败。
    assert total_queries == 6
    assert returned_items == 7
    assert recall_at_one == 1.0
    assert len(false_recalls) == 1
    assert item_false_recall_rate == pytest.approx(1 / 7)
    assert query_false_recall_rate == pytest.approx(1 / 6)
    # 门槛断言：命中率必须满分，误召回不得超过 25%。
    assert recall_at_one >= 1.0
    assert item_false_recall_rate <= 0.25
    assert false_recalls[0][0] == "下周去北京的行程怎么安排"

    # 把这次相关性判定持久化，供后续复盘（I10/I11）读取。
    result = record_usage_judgments(judgments)
    assert result["ok"] is True
    assert result["pruned"] == []
    stats = load_skill_stats()
    assert sum(int(item.get("retrieved", 0)) for item in stats.values()) == returned_items
    assert sum(int(item.get("relevant", 0)) for item in stats.values()) == total_queries
    assert stats["每周回顾"]["retrieved"] == 3
    assert stats["每周回顾"]["relevant"] == 2
