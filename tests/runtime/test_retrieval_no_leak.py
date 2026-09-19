"""t19：无关请求不得把工作流程规则注入请求载荷。

真实演示里「记一条待办」把「每日规划输出规则」以 score=0.085 注入了出站载荷
（旧阈值 0.08 刚好放行）；t14 在同一指纹下独立复现。本文件把断言放在**载荷层**：

* format_retrieved_skill_context() 是运行时拼 <retrieved_skills> 那个段的唯一入口
  （agent.py 用它构建用户消息），所以它的返回值就是载荷事实；
* 无关请求：载荷段为空、top 引用为 None（多语言、多句式各来一条）；
* 对照：相关请求仍然检索到技能，且载荷里确实出现它（防止「一刀切关掉检索」也能过测）；
* 判据本身的真值表（分数下限 + 多字词项数），以及默认阈值不再散落魔数。

I10 基线（Recall@1 = 6/6、item 级误召回 1/7）由 tests/runtime/test_skills_retrieval_zh.py
继续逐项锁住；本文件只补充「无关请求」这一侧。

旧实现下会失败的断言：全部 IRRELEVANT 用例（旧阈值 0.08 会把噪声命中写进载荷），
以及 is_relevant_hit 的下限断言。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mellowday.runtime.skills import (
    RETRIEVAL_MIN_CONTENT_TERMS,
    RETRIEVAL_MIN_SCORE,
    create_skill_file,
    format_retrieved_skill_context,
    is_relevant_hit,
    reset_skill_cache,
    retrieve_relevant_skills,
)

# I10 的中文技能库（与 test_skills_retrieval_zh.py 同一批文本）
CORPUS = [
    ("每周回顾", "梳理本周完成与未完成的待办，生成本周总结与下周计划",
     "当用户要求做每周回顾、周总结或复盘本周安排时使用",
     "# 步骤\n1. 列出本周完成的待办\n2. 列出未完成的待办\n3. 给出下周计划"),
    ("会议纪要整理", "把会议记录整理成决议摘要与待办清单",
     "当用户提供会议记录并希望整理成纪要和待办时使用",
     "# 步骤\n1. 提取会议决议\n2. 整理参会人发言要点\n3. 输出待办清单"),
    ("旅行行程规划", "根据出行时间与预算规划旅行路线、住宿和行李清单",
     "当用户提出旅行计划、出行安排或行程规划时使用",
     "# 步骤\n1. 确认目的地与天数\n2. 安排每天的景点与交通\n3. 给出住宿与行李建议"),
    # 演示里被误注入的规划规则（每天规划任务时的输出格式）
    ("每日规划输出规则", "规划每天任务时的输出格式：先列固定日程，再排三个重点任务",
     "当用户要求规划今天或明天的任务时使用，输出要按固定格式",
     "# 输出格式\n1. 先列出当天已有的固定日程\n2. 只排三个重点任务\n3. 结尾给出一句风险提示"),
]

# 与任何一条技能的工作流程无关的请求（多语言、多句式）
IRRELEVANT = (
    "记一条待办",
    "现在几点",
    "帮我建个提醒",
    "帮我记一下明天买菜",
    "设置一个闹钟",
    "今天天气怎么样",
    "what time is it",
    "remind me to call mom",
    "帮我记一条笔记，别忘了",
)

# 相关请求：必须仍然命中并在载荷里出现
RELEVANT = (
    ("帮我做一下这周的每周回顾", "每周回顾"),
    ("把今天的会议记录整理成纪要", "会议纪要整理"),
    ("帮我规划一下去杭州的三天旅行行程", "旅行行程规划"),
    ("帮我规划一下明天的任务", "每日规划输出规则"),
)


@pytest.fixture(autouse=True)
def _corpus():
    reset_skill_cache()
    for name, description, when, instructions in CORPUS:
        result = create_skill_file(
            name=name, description=description, when_to_use=when, instructions=instructions
        )
        assert result["ok"] is True, result
    reset_skill_cache()
    yield
    reset_skill_cache()


# ------------------------------------------------------------------ 载荷层断言


@pytest.mark.parametrize("query", IRRELEVANT, ids=list(IRRELEVANT))
def test_irrelevant_request_gets_no_retrieved_skills_in_the_payload(query: str) -> None:
    context, top = format_retrieved_skill_context(query, limit=3)

    assert context == "", f"无关请求不该注入 <retrieved_skills> 段：{query} -> {context[:80]}"
    assert "<retrieved_skills>" not in context
    assert top is None
    assert retrieve_relevant_skills(query, limit=3) == []


@pytest.mark.parametrize("query,expected", RELEVANT, ids=[q for q, _ in RELEVANT])
def test_relevant_request_still_retrieves_and_injects(query: str, expected: str) -> None:
    context, top = format_retrieved_skill_context(query, limit=3)

    assert top is not None, f"相关请求必须仍然命中：{query}"
    assert top["name"] == expected, [hit["name"] for hit in retrieve_relevant_skills(query, limit=3)]
    assert "<retrieved_skills>" in context
    assert expected in context


def test_the_known_t19_leak_shape_cannot_reach_the_payload() -> None:
    """两条实测泄漏形状：极低分噪声 + 单字命中（分数甚至 0.53）。"""
    context, top = format_retrieved_skill_context("记一条待办", limit=3)
    assert top is None and context == ""

    # 旧实现下这条会以 0.53 分命中「每周回顾」（命中词是「办 / 待办」，其中一个是单字）。
    assert retrieve_relevant_skills("记一条待办", limit=3) == []
    # 「明天」这种时间词单独命中也不再算证据。
    assert retrieve_relevant_skills("帮我记一下明天买菜", limit=3) == []


# ------------------------------------------------------------ 判据本身的真值表


def test_default_min_score_comes_from_the_named_constant() -> None:
    import inspect

    from mellowday.runtime.skills import skills as skills_module

    signature = inspect.signature(skills_module.retrieve_relevant_skills)
    assert signature.parameters["min_score"].default == RETRIEVAL_MIN_SCORE
    assert RETRIEVAL_MIN_SCORE > 0.08, "至少要比旧阈值高：0.085 那类噪声不能再放行"
    assert RETRIEVAL_MIN_CONTENT_TERMS >= 2


def test_relevance_gate_truth_table() -> None:
    # 分数低于下限：拒绝（这就是 t14 报告的 0.085 命中）。
    assert is_relevant_hit(score=0.085, matched_terms={"每周", "总结"}) is False
    assert is_relevant_hit(score=RETRIEVAL_MIN_SCORE - 0.001, matched_terms={"a", "bb"}) is False
    # 分数够，但只有一个多字词项（另一个是单字，例如「办 + 待办」）：拒绝。
    assert is_relevant_hit(score=0.53, matched_terms={"办", "待办"}) is False
    assert is_relevant_hit(score=0.53, matched_terms={"明天"}) is False
    assert is_relevant_hit(score=0.53, matched_terms={"安排"}) is False
    # 两个及以上多字词项：放行（真命中的形状）。
    assert is_relevant_hit(score=0.53, matched_terms={"安排", "行程"}) is True
    assert is_relevant_hit(score=RETRIEVAL_MIN_SCORE, matched_terms={"每周", "周总", "总结"}) is True
    # 显式放宽下限时（内部相似度比较）仍然要求多字词项。
    assert is_relevant_hit(score=0.03, matched_terms={"待办"}, min_score=0.03) is False
    assert is_relevant_hit(score=0.03, matched_terms={"待办", "会议"}, min_score=0.03) is True


def test_internal_similarity_search_keeps_its_wide_floor() -> None:
    """合并相似度比较不是用户请求：它显式传 min_score=0.03，不受载荷下限影响。"""
    from mellowday.runtime.skills import online_skill_evolution as evolution_module

    source = Path(evolution_module.__file__).read_text(encoding="utf-8")
    assert "min_score=0.03" in source, "合并相似度比较需要更宽的网，不能被载荷下限一刀切"


def test_every_hit_in_the_payload_carries_its_evidence() -> None:
    """载荷里的每一条命中都必须有多字词项证据，不能只靠分数。"""
    hits = retrieve_relevant_skills("帮我做一下这周的每周回顾", limit=3)
    assert hits, "对照请求必须命中"
    top = hits[0]
    assert top["name"] == "每周回顾"
    assert float(top["score"]) >= RETRIEVAL_MIN_SCORE


# ------------------------------------------------- 真实出站载荷（经过 Agent 一轮）


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
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        chunks = self._turns.pop(0) if self._turns else _text_turn("")

        async def _gen():
            for chunk in chunks:
                yield chunk

        return _gen()


class _Chat:
    def __init__(self, completions):
        self.completions = completions


def _text_turn(text="好的。"):
    return [
        _Chunk([_Choice(_Delta(content=text))]),
        _Chunk(usage=_Usage(10, 4)),
        _Chunk([_Choice(_Delta(), finish_reason="stop")]),
    ]


def _outbound_texts(agent) -> list[str]:
    """把这一轮真正发给模型的 user 消息取出来（载荷事实）。"""
    texts: list[str] = []
    for call in agent._openai_client.completions.calls:  # type: ignore[attr-defined]
        for message in call.get("messages") or []:
            if str(message.get("role")) == "user":
                texts.append(str(message.get("content") or ""))
    return texts


async def _run_agent_turn(message: str):
    from mellowday.runtime.agent import Agent

    agent = Agent(model="test-model", api_base="http://127.0.0.1:9/v1", api_key="test-key")
    agent._openai_client = type(
        "Fake",
        (),
        {"completions": _Completions([_text_turn()]), "chat": _Chat(_Completions([_text_turn()]))},
    )()
    agent._openai_client.chat = _Chat(agent._openai_client.completions)
    await agent.chat(message)
    return _outbound_texts(agent)


@pytest.mark.anyio
async def test_outbound_payload_of_an_irrelevant_turn_has_no_rules() -> None:
    texts = await _run_agent_turn("记一条待办")

    assert texts, "必须抓到出站 user 消息"
    joined = "\n".join(texts)
    assert "<retrieved_skills>" not in joined, joined[:400]
    for name, *_ in CORPUS:
        assert name not in joined, f"无关请求的出站载荷里不该出现 {name}"


@pytest.mark.anyio
async def test_outbound_payload_of_a_relevant_turn_carries_the_skill() -> None:
    texts = await _run_agent_turn("帮我做一下这周的每周回顾")

    joined = "\n".join(texts)
    assert "<retrieved_skills>" in joined
    assert "每周回顾" in joined
