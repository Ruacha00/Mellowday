"""F 项静态测试：习惯页面能看规则正文、能编辑保存、能看历史正文。

页面是原生 JS + CSS，没有构建步骤，离线测试套件里也没有浏览器，因此这里仍然只做
静态断言：接口路径与 HTTP 方法、规则正文与编辑器的渲染、失败与「没有变化」的提示、
历史正文入口、以及多行确认文本的样式。接口行为本身由
tests/web_app/test_skills_edit_api.py 与 tests/runtime/test_skill_editing.py 覆盖。
"""
from __future__ import annotations

import re

import pytest

from mellowday import paths
from mellowday.web_app import skills_api

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


# ------------------------------------------------------------------ 接口接线


def test_detail_and_update_paths_match_the_backend_router(app_js):
    registered = {
        (route.path, method)
        for route in skills_api.router.routes
        for method in getattr(route, "methods", set()) or set()
    }
    for path, method in (
        ("/api/skills/{name}", "GET"),
        ("/api/skills/{name}", "PUT"),
        ("/api/skills/{name}/versions/{version}", "GET"),
    ):
        assert (path, method) in registered, f"后端缺少 {method} {path}"
    # 视图路径表必须逐字对齐后端。
    assert 'detail: "/api/skills/{name}"' in app_js
    assert 'update: "/api/skills/{name}"' in app_js
    assert 'versionBody: "/api/skills/{name}/versions/{version}"' in app_js


def test_read_and_save_use_the_right_http_methods(app_js):
    # 读规则与历史正文是 GET（不传 method，走 fetch 默认值）。
    assert 'requestJson(skillEndpoint("detail", { name: skill.name }))' in app_js
    assert 'requestJson(skillEndpoint("versionBody", { name: skill.name, version: version }))' in app_js
    # 保存是 PUT，并且带上 JSON Content-Type。
    assert re.search(
        r'skillEndpoint\(\s*"update",\s*\{\s*name:\s*skill\.name\s*\}\s*\),\s*\{\s*'
        r'method:\s*"PUT",\s*headers:\s*\{\s*"Content-Type":\s*"application/json"\s*\},',
        app_js,
    ), "保存必须 PUT 到 /api/skills/{name} 并发送 JSON"
    # 编辑不新建任何本地存储：没有第二种持久化。
    assert "localStorage" not in app_js
    assert "sessionStorage" not in app_js


# ------------------------------------------------------------------ 规则正文


def test_card_offers_viewing_and_editing_the_rules(app_js):
    assert "查看规则" in app_js and "收起规则" in app_js
    assert "编辑规则" in app_js and "取消编辑" in app_js
    card = _function_body(app_js, "buildSkillCard")
    assert "buildSkillDetail(skill, detail, editing)" in card
    assert "toggleSkillDetail(skill)" in card
    assert "startSkillEdit(skill)" in card


def test_rule_panel_renders_the_current_body(app_js):
    panel = _function_body(app_js, "buildSkillDetail")
    assert "detail.body" in panel
    assert '"skill-body"' in panel
    assert '"pre"' in panel
    assert "当前规则（版本 " in panel
    # 溯源单独展示，并且明说它不是规则本身。
    assert "detail.notes" in panel
    assert "演化溯源" in panel
    assert "规则读取失败" in app_js


def test_editor_exposes_description_when_and_rules(app_js):
    editor = _function_body(app_js, "buildSkillEditor")
    for field in ("skill-input-desc", "skill-input-when", "skill-input-rules"):
        assert field in editor, f"编辑器缺少字段 {field}"
    assert '"textarea"' in editor
    assert "规则正文（必填，保存时整体替换）" in editor
    assert "保存并生成新版本" in editor
    assert "saveSkillEdit(skill, {{" in editor or "saveSkillEdit(skill, {" in editor
    # 保存提示必须说明复用版本机制、且影响后续新会话。
    assert "版本号 +1" in editor
    assert "随时可以回退" in editor


def test_saving_validates_and_reports_the_new_version(app_js):
    save = _function_body(app_js, "saveSkillEdit")
    assert "用途描述不能为空" in save
    assert "规则正文不能为空" in save
    assert "previous_version" in save and "data.version" in save
    assert "之后的新对话按新规则执行" in save
    assert "没有变化，未生成新版本" in save
    assert "loadSkills();" in save


def test_editing_a_disabled_habit_points_at_the_fix(app_js):
    start = _function_body(app_js, "startSkillEdit")
    assert "if (!skillEnabled(skill))" in start
    assert "SKILL_DISABLED_HINT" in start
    assert re.search(r"SKILL_DISABLED_HINT[\s\S]*?return;", start), "提示后必须直接返回，不能进入编辑态"
    assert start.index("SKILL_DISABLED_HINT") < start.index("state.skillEdit")


# ------------------------------------------------------------------ 历史正文


def test_every_version_body_can_be_inspected(app_js):
    assert "查看正文" in app_js and "收起正文" in app_js
    row = _function_body(app_js, "buildSkillVersionRow")
    assert "toggleSkillVersionBody(skill, version.version)" in row
    body = _function_body(app_js, "buildSkillVersionBody")
    assert "entry.body" in body
    assert '"skill-body"' in body
    toggle = _function_body(app_js, "toggleSkillVersionBody")
    assert '"versionBody"' in toggle
    assert "describeSkillFailure" in toggle
    assert "版本正文读取失败" in app_js


def test_rollback_still_works_after_the_edit_view_was_added(app_js):
    assert "回退到此版本" in app_js
    assert "确认回退" in app_js
    confirm = _function_body(app_js, "confirmSkillRestore")
    assert 'skillEndpoint("restore"' in confirm
    # 回退之后缓存里的正文必须失效，否则面板会显示回退前的内容。
    assert "detail.body = \"\";" in confirm


# ------------------------------------------------------------------ 确认框与样式


def test_multi_line_confirmation_is_rendered_line_by_line(app_js, styles_css):
    # 学习写入的确认文本现在带候选规则与旧→新对照，必须按行显示。
    assert re.search(r'class=\\"confirm-text\\"', app_js), "确认框必须用 confirm-text 承载多行文本"
    assert ".confirm-text { white-space: pre-line; }" in styles_css


def test_styles_cover_the_rule_view_and_editor(styles_css):
    for selector in (
        ".skill-detail",
        ".skill-body",
        ".skill-notes",
        ".skill-editor",
        ".skill-field",
        ".skill-input",
        ".skill-textarea",
        ".skill-editor-actions",
        ".skill-save",
        ".skill-version-body",
        ".version-body-link",
    ):
        assert selector in styles_css, f"{selector} 必须有样式"


def test_no_new_dom_ids_are_required(app_js):
    """规则面板与编辑器都挂在既有容器里，不需要新增 id。"""
    referenced = set(re.findall(r'\bel\(\s*"(skills-[^"]+|view-skills)"\s*\)', app_js))
    assert referenced == {"skills-notice", "skills-list", "view-skills", "skills-reload"}, referenced
