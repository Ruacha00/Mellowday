"""T8 静态测试：历史面板消费原始执行记录（工具调用、结果、错误）。

页面是原生 JS + CSS，离线套件里没有浏览器，因此这里钉住「页面上必须存在什么」：
消费 trace / trace_display、按顺序渲染 tool_call / tool_result / error、超长结果只走
结构化 ref（禁止从占位文案里抠引用）、分页读取、三处空态与失败提示、以及折叠状态。

接口行为由 tests/web_app/test_execution_trace.py 与 tests/runtime 覆盖；真实进程 +
真实浏览器的证据见本轮交付说明（scripts 侧脚本，不入库）。
"""
from __future__ import annotations

import re

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


# ------------------------------------------------------------------ 消费哪些字段


def test_history_panel_consumes_trace_and_trace_display(app_js):
    render = _function_body(app_js, "renderHistory")
    assert "payload.trace" in render, "必须消费原始执行记录 trace"
    assert "payload.trace_display" in render, "必须消费有界展示视图 trace_display"
    assert "payload.messages" in render, "对话历史仍然要显示（不能取代，也不能被取代）"


def test_session_open_goes_through_the_structured_endpoint_table(app_js):
    assert 'detail: "/api/sessions/{session}"' in app_js
    assert 'toolResult: "/api/sessions/{session}/tool-results/{ref}"' in app_js
    open_session = _function_body(app_js, "openSession")
    assert 'sessionEndpoint("detail", { session: id })' in open_session
    # 读到会话之后必须走 renderHistory（真正消费执行记录的入口），
    # 退回到「只渲染 res.messages」会让整个面板白做。
    assert "renderHistory(result.data || {})" in open_session
    assert "res.messages" not in open_session
    # 读取失败必须可见，不能留一个空白的消息区。
    assert "读取会话失败" in open_session
    assert "renderHistoryNotice" in open_session


def test_every_trace_type_has_a_renderer(app_js):
    node = _function_body(app_js, "buildTraceNode")
    for entry_type in ("user", "assistant", "message", "tool_call", "tool_result", "error"):
        assert f'"{entry_type}"' in node, f"{entry_type} 必须有渲染分支"
    assert "buildToolCallRow" in node and "buildToolResultRow" in node and "buildErrorRow" in node


def test_messages_and_tools_are_rendered_in_record_order(app_js):
    render = _function_body(app_js, "renderHistory")
    # 单次顺序遍历，靠 appendChild 保持时间顺序：不能分组、不能倒序。
    assert "trace.forEach((entry, index) =>" in render
    assert "container.appendChild(node)" in render
    assert "reverse()" not in render


def test_a_turn_with_a_committed_reply_does_not_render_the_stream_chunks_twice(app_js):
    body = _function_body(app_js, "buildTraceNode")
    assert "committed.has(String(entry && entry.turn))" in body
    committed = _function_body(app_js, "committedAssistantTurns")
    assert '"assistant"' in committed


# ------------------------------------------------- 超长结果：只认结构化 ref


def test_oversized_result_uses_the_structured_ref_only(app_js):
    row = _function_body(app_js, "buildToolResultRow")
    assert "entry && entry.ref != null" in row, "ref 只能来自结构化字段"
    assert "entry.truncated" in row
    assert "entry.chars" in row
    # 禁止从占位文案里抠引用：占位文案一变就静默失效（CONTRACTS 6ter.2）。
    assert 'ref="' not in app_js
    assert "ref='" not in app_js
    assert not re.search(r"/[^/\n]*\bref\b[^/\n]*/[gimsuy]*", app_js), "不允许用正则处理引用"
    assert not re.search(r"(\.match|\.exec)\s*\([^)]*\bref\b", app_js), "不允许从文本里抠引用"
    assert "complete output saved as ref" not in app_js.lower(), "不得依赖占位文案的措辞"


def test_a_truncated_result_without_a_ref_says_so(app_js):
    row = _function_body(app_js, "buildToolResultRow")
    assert "没有结构化 ref" in row
    assert "trace-note" in row  # 失败/缺信息必须是可见文案，不是空块


def test_expanding_a_result_reads_it_through_the_reference_endpoint(app_js):
    loader = _function_body(app_js, "loadToolResult")
    assert 'sessionEndpoint("toolResult", { session: state.sessionId, ref: ref })' in loader
    assert "?offset=" in loader and "&limit=" in loader
    assert "TRACE_RESULT_PAGE" in loader
    toggle = _function_body(app_js, "toggleToolResult")
    assert "查看原文" in app_js and "收起原文" in app_js
    assert "loadToolResult" in toggle


def test_paging_uses_the_server_offsets_and_offers_more(app_js):
    loader = _function_body(app_js, "loadToolResult")
    assert "data.next_offset" in loader
    assert "data.total_chars" in loader
    assert "data.has_more" in loader
    box = _function_body(app_js, "renderToolResultBox")
    assert "继续加载" in box
    assert "已显示" in box and "已到结尾" in box


def test_a_failed_reference_read_is_visible_with_a_reason(app_js):
    describe = _function_body(app_js, "describeTraceFailure")
    assert "HTTP 404" in describe and "HTTP 400" in describe
    assert "受限引用读取接口" in describe
    loader = _function_body(app_js, "loadToolResult")
    assert 'data.ok === false' in loader
    # 两条失败分支（HTTP 层失败 / 域内失败）都必须把提示挂进盒子：
    # 只留字符串、不 append，等于静默失败。
    assert loader.count('box.appendChild(toolResultNote("原文读取失败') == 2, loader


# ------------------------------------------------------------------ 错误与空态


def test_errors_from_the_record_are_rendered_with_their_phase(app_js):
    row = _function_body(app_js, "buildErrorRow")
    assert "entry && entry.message" in row
    assert "entry && entry.phase" in row
    assert "错误" in row


def test_empty_states_are_explicit(app_js):
    render = _function_body(app_js, "renderHistory")
    assert "没有执行记录" in render, "早期会话没有 trace 时必须说明"
    assert "没有工具调用" in render, "有记录但没有工具调用时必须说明"
    assert "renderHistoryNotice" in render
    open_session = _function_body(app_js, "openSession")
    assert "读取会话失败" in open_session


def test_display_messages_missing_from_the_record_are_still_shown(app_js):
    fn = _function_body(app_js, "appendUnmirroredMessages")
    assert "missing" in fn and "bubble(" in fn
    assert "在原始记录里没有对应条目" in fn
    render = _function_body(app_js, "renderHistory")
    assert "appendUnmirroredMessages(historyMessages, seenTexts)" in render


def test_tool_rows_collapse_and_keep_their_state(app_js):
    for name in ("buildToolCallRow", "buildToolResultRow"):
        row = _function_body(app_js, name)
        assert "state.traceOpen[String(index)]" in row, f"{name} 必须可折叠并复用展开状态"
        assert "body.hidden" in row
        assert '"trace-head"' in row
    open_session = _function_body(app_js, "openSession")
    assert "state.traceOpen = {};" in open_session
    assert "state.traceResults = {};" in open_session


def test_tool_call_row_shows_name_and_arguments(app_js):
    row = _function_body(app_js, "buildToolCallRow")
    assert "调用工具" in row
    assert "traceTextValue(shown, entry" in row and '"arguments"' in row
    formatter = _function_body(app_js, "formatToolArguments")
    assert "JSON.parse" in formatter and "JSON.stringify" in formatter
    # 参数过长时截断，而不是把整段塞进 DOM。
    assert "boundTraceText" in row


def test_raw_trace_without_a_display_view_is_still_bounded_on_the_page(app_js):
    bound = _function_body(app_js, "boundTraceText")
    assert "if (raw.length <= limit) return raw;" in bound
    assert "省略" in bound
    # 不能出现无条件的 return raw：那会让下面的截断分支永远到不了（死代码也会骗过字符串断言）。
    stray = [line.strip() for line in bound.splitlines() if line.strip() == "return raw;"]
    assert not stray, "boundTraceText 必须先判断长度再返回"
    row = _function_body(app_js, "buildToolResultRow")
    assert "boundTraceText(previewText, TRACE_RESULT_PREVIEW_CHARS)" in row


# --------------------------------------------------------- 实时事件里的结构化引用


def test_live_tool_result_announces_the_saved_reference(app_js):
    handler = _function_body(app_js, "handleEvent")
    # 锚定整句赋值：前面加任何短路（例如 false &&）都必须被判失败。
    assert re.search(r"const saved = event\.truncated && event\.ref\b", handler), handler
    assert "完整原文按引用保存" in handler
    assert 'ref="' not in handler, "实时路径同样不得从文本里抠 ref"


# ------------------------------------------------------------------ 样式与接线


def test_styles_cover_the_history_rows(styles_css):
    for selector in (
        ".trace-notice",
        ".trace-notice.warn",
        ".trace-notice.error",
        ".trace-row",
        ".trace-tool",
        ".trace-head",
        ".trace-body",
        ".trace-pre",
        ".trace-actions",
        ".trace-meta",
        ".trace-note",
        ".trace-note.warn",
        ".trace-note.error",
        ".trace-original-box",
        ".trace-original-text",
        ".trace-error",
    ):
        assert selector in styles_css, f"{selector} 必须有样式"


def test_the_panel_needs_no_new_element_ids(app_js):
    """历史面板全部挂在既有 #messages 容器里，不需要新增 id。"""
    referenced = set(re.findall(r'\bel\(\s*"([^"]+)"\s*\)', app_js))
    assert "messages" in referenced
    assert not [name for name in referenced if name.startswith("trace-")], "不要新增 trace-* 控件 id"
