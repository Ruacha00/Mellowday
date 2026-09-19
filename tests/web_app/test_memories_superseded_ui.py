"""记忆管理：被技能取代的事实要显示来源（技能名 + 时间）与可读状态。

背景（CONTRACTS 6quater.2，t9 落地）：与已落库技能实质重叠的事实被标成
status=superseded，记录不删除，meta 带 superseded_by_skill / superseded_at /
superseded_reason。API 已经能看到这些字段，但管理页不渲染 meta，用户看不到
「这条事实被哪条习惯取代了、什么时候」，也不知道它已经不再参与召回。

两层断言：
* 静态：页面确实读取 meta 的三个字段、只在记忆视图里渲染、用的是本地时间；
* 行为：把 app.js 里的纯函数抽出来在 node 里真跑一遍（缺 node 时跳过），
  避免「字符串在源码里出现过」这种会被死代码骗过的断言。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from mellowday import paths

APP_JS_PATH = paths.static_dir() / "app.js"
STYLES_CSS_PATH = paths.static_dir() / "styles.css"


@pytest.fixture(scope="module")
def app_js() -> str:
    return APP_JS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def styles_css() -> str:
    return STYLES_CSS_PATH.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    match = re.search(rf"^(?:async )?function {re.escape(name)}\(.*?^\}}", source, re.S | re.M)
    assert match, f"app.js must define {name}()"
    return match.group(0)


# ------------------------------------------------------------------ 静态断言


def test_the_page_reads_the_three_supersede_fields(app_js):
    helper = _function_body(app_js, "supersedeSourceText")
    for field in ("meta.superseded_by_skill", "meta.superseded_at", "meta.superseded_reason"):
        assert field in helper, f"必须读取 {field}"
    assert 'normalizeStatus(record.status) !== "superseded"' in helper, "只对被取代的事实显示来源"
    # 时间是给用户看的：必须走本地渲染，不能直接印 UTC 原值。
    assert "formatLocalMoment(meta.superseded_at)" in helper
    assert "不再参与召回" in helper


def test_meta_is_read_defensively(app_js):
    helper = _function_body(app_js, "recordMeta")
    assert "JSON.parse" in helper, "meta 可能是 JSON 字符串"
    assert 'typeof raw === "object"' in helper
    assert "return {};" in helper


def test_the_source_note_is_rendered_only_on_the_memories_page(app_js):
    cells = _function_body(app_js, "viewCells")
    assert 'if (state.kind === "memories")' in cells
    assert "supersedeSourceText(record)" in cells
    assert '"record-source warn"' in cells
    assert "detail.appendChild(note)" in cells


def test_a_superseded_record_without_meta_still_explains_itself(app_js):
    helper = _function_body(app_js, "supersedeSourceText")
    assert "没有来源信息" in helper
    # 空盒子不算「说明」：两条渲染分支都必须返回非空文案，并且都说清它不再参与召回。
    returns = [line.strip() for line in helper.splitlines() if line.strip().startswith("return ")]
    assert len(returns) == 2, returns
    for line in returns:
        assert "不再参与召回" in line, line
    # 唯一的空返回值是「这不是被取代的记录」这条早退分支。
    assert 'if (!record || normalizeStatus(record.status) !== "superseded") return "";' in helper


def test_the_badge_uses_the_shared_status_language(app_js):
    assert 'superseded: "已被替代"' in app_js
    rules = _function_body(app_js, "isDoneStatus")
    assert "statusRule(kind).doneValues.includes(normalizeStatus(status))" in rules
    memories = re.search(r"memories: \{\s*doneValues: \[([^\]]*)\]", app_js, re.S)
    assert memories, "记忆的状态规则必须存在"
    assert '"superseded"' in memories.group(1), "已被替代与已失效/已删除走同一套视觉语言"
    for label in ('expired: "已失效"', 'deleted: "已删除"'):
        assert label in app_js


def test_failure_and_empty_prompts_are_untouched(app_js):
    load = _function_body(app_js, "loadRecords")
    assert "读取记录失败" in load
    assert "暂无记录" in load
    assert "showRecordsNotice" in load


def test_styles_cover_the_source_note(styles_css):
    assert ".record-source {" in styles_css
    assert ".record-source.warn {" in styles_css


# --------------------------------------------------------- 行为断言（node 跑真函数）


def _run_node(program: str) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available; the behavioural check needs it")
    return subprocess.run(
        [node, "-e", program], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def test_supersede_source_text_behaviour(app_js):
    """把纯函数抽出来真跑一遍：每种输入都断言一次输出。"""
    parts = [
        _function_body(app_js, "normalizeStatus"),
        _function_body(app_js, "pad2"),
        _function_body(app_js, "parseMoment"),
        _function_body(app_js, "formatLocalMoment"),
        _function_body(app_js, "recordMeta"),
        _function_body(app_js, "supersedeSourceText"),
    ]
    cases = [
        {
            "name": "被取代且带完整来源",
            "record": {
                "status": "superseded",
                "meta": {
                    "superseded_by_skill": "每周回顾",
                    "superseded_at": "2026-09-18T12:00:00+00:00",
                    "superseded_reason": "与习惯规则重叠",
                },
            },
            "expect": ["被习惯「每周回顾」取代", "时间 ", "原因：与习惯规则重叠", "不再参与召回"],
        },
        {
            "name": "被取代但没有来源信息",
            "record": {"status": "superseded", "meta": {}},
            "expect": ["没有来源信息", "不再参与召回"],
        },
        {
            "name": "meta 是 JSON 字符串",
            "record": {
                "status": "superseded",
                "meta": json.dumps(
                    {"superseded_by_skill": "会议纪要整理", "superseded_at": "2026-09-18T01:30:00Z"},
                    ensure_ascii=False,
                ),
            },
            "expect": ["会议纪要整理", "时间 "],
        },
        {"name": "仍然生效的事实不显示来源", "record": {"status": "active", "meta": {"superseded_by_skill": "X"}}, "expect": [""]},
        {"name": "已删除的事实也不显示取代来源", "record": {"status": "deleted", "meta": {"superseded_by_skill": "X"}}, "expect": [""]},
        {"name": "没有 meta 字段也不崩", "record": {"status": "superseded"}, "expect": ["没有来源信息"]},
    ]
    program = (
        "\n".join(parts)
        + "\nconst cases = " + json.dumps(cases, ensure_ascii=False) + ";\n"
        + "let failed = 0;\n"
        + "for (const item of cases) {\n"
        + "  const actual = supersedeSourceText(item.record);\n"
        + "  for (const expected of item.expect) {\n"
        + "    const ok = expected === \"\" ? actual === \"\" : actual.indexOf(expected) >= 0;\n"
        + "    if (!ok) { failed += 1; console.log(\"FAIL \" + item.name + \" expected(\" + expected + \") got(\" + actual + \")\"); }\n"
        + "  }\n"
        + "}\n"
        + "console.log(failed === 0 ? \"all cases ok\" : failed + \" case(s) failed\");\n"
        + "process.exit(failed === 0 ? 0 : 1);\n"
    )
    result = _run_node(program)
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
    assert "all cases ok" in (result.stdout or "")


def test_the_time_in_the_source_note_is_local_not_utc(app_js):
    """同一时刻按本地时区渲染：不能用字符串截取 UTC 原值。"""
    parts = [
        _function_body(app_js, "normalizeStatus"),
        _function_body(app_js, "pad2"),
        _function_body(app_js, "parseMoment"),
        _function_body(app_js, "formatLocalMoment"),
        _function_body(app_js, "recordMeta"),
        _function_body(app_js, "supersedeSourceText"),
    ]
    program = (
        "\n".join(parts)
        + "\nconst record = { status: \"superseded\", meta: { superseded_by_skill: \"S\", superseded_at: \"2026-09-18T12:00:00Z\" } };\n"
        + "const text = supersedeSourceText(record);\n"
        + "const expected = formatLocalMoment(\"2026-09-18T12:00:00Z\");\n"
        + "console.log(text);\n"
        + "process.exit(text.indexOf(expected) >= 0 && text.indexOf(\"2026-09-18T12:00:00Z\") < 0 ? 0 : 1);\n"
    )
    result = _run_node(program)
    assert result.returncode == 0, (result.stdout or "") + (result.stderr or "")
