"""I24c 静态测试：习惯（技能）管理界面。

技能管理后端（I24a）已经可用，但用户在页面上看不到、也无法停用任何习惯。
本模块把「页面上必须存在什么」钉成文本断言：五个接口路径、导航项与视图区块、
启停按钮、版本展开、回退的二次确认，以及停用态下的回退提示。

页面是原生 JS + CSS，没有构建步骤，离线测试套件里也没有浏览器，因此这里只做静态
断言；接口本身的行为由 tests/web_app/test_skills_api.py 覆盖，真实点击流程在交付
说明里给出可复核的手工步骤。

断言用到的文本片段都是 app.js / index.html 里真实存在的写法；改错接口路径、删掉
提示文案或去掉二次确认都会让断言失败（提交说明里附了变异校验记录）。
"""
from __future__ import annotations

import re

import pytest

from mellowday import paths
from mellowday.web_app import skills_api

APP_JS_PATH = paths.static_dir() / "app.js"
INDEX_HTML_PATH = paths.static_dir() / "index.html"
STYLES_CSS_PATH = paths.static_dir() / "styles.css"

# CONTRACTS.md 4.5 冻结的五个接口路径，必须逐字出现在 app.js。
CONTRACT_PATHS = (
    "/api/skills",
    "/api/skills/{name}/disable",
    "/api/skills/{name}/enable",
    "/api/skills/{name}/versions",
    "/api/skills/{name}/versions/{version}/restore",
)

# 停用中的技能不能回退版本（后端 400 skill_disabled），界面必须给出这句指引。
DISABLED_HINT = "请先恢复该技能再回退版本"


@pytest.fixture(scope="module")
def app_js() -> str:
    return APP_JS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def styles_css() -> str:
    return STYLES_CSS_PATH.read_text(encoding="utf-8")


def _function_body(source: str, name: str) -> str:
    """取出一个顶层函数（含 async）的完整源码。"""
    match = re.search(rf"^(?:async )?function {re.escape(name)}\(.*?^\}}", source, re.S | re.M)
    assert match, f"app.js must define {name}()"
    return match.group(0)


# ------------------------------------------------------------------ 导航与视图


def test_index_html_adds_a_habits_nav_item_and_view(index_html):
    assert re.search(
        r'<button class="nav-item(?: active)?" data-view="skills">\s*习惯\s*</button>', index_html
    ), '侧栏必须有 data-view="skills" 的「习惯」入口'
    assert '<section class="view" id="view-skills">' in index_html, "习惯视图区块必须存在"
    # 列表与提示行是 app.js 唯一能挂载内容的地方。
    assert 'id="skills-list"' in index_html
    assert 'id="skills-notice"' in index_html


def test_existing_views_and_nav_items_are_untouched(index_html):
    for view in ("chat", "todos", "calendar", "reminders", "notes", "memories", "settings"):
        assert f'data-view="{view}"' in index_html, f"原有的 {view} 导航项不能被删掉"
    for view_id in ("view-chat", "view-records", "view-settings"):
        assert f'id="{view_id}"' in index_html
    assert 'id="messages"' in index_html and 'id="records-table"' in index_html


# ------------------------------------------------------------------ 接口路径


def test_app_js_knows_the_contracted_paths(app_js):
    for path in CONTRACT_PATHS:
        assert f'"{path}"' in app_js, f"app.js 必须逐字使用契约路径 {path}"
    # 第三轮新增：规则正文查看（GET detail）、编辑保存（PUT update）、历史正文。
    for path in ("/api/skills/{name}", "/api/skills/{name}/versions/{version}"):
        assert f'"{path}"' in app_js, f"app.js 必须逐字使用新增路径 {path}"
    keys = set(re.findall(r'^\s*(\w+): "/api/skills', app_js, re.M))
    assert keys == {
        "list", "detail", "update", "disable", "enable", "versions", "versionBody", "restore",
    }, keys


def test_the_five_paths_match_the_backend_router():
    """前端的路径表必须和后端真实注册的路由一致，不能各写一份。"""
    registered = {
        (route.path, method)
        for route in skills_api.router.routes
        for method in getattr(route, "methods", set()) or set()
    }
    for path, method in (
        ("/api/skills", "GET"),
        ("/api/skills/{name}/disable", "POST"),
        ("/api/skills/{name}/enable", "POST"),
        ("/api/skills/{name}/versions", "GET"),
        ("/api/skills/{name}/versions/{version}/restore", "POST"),
    ):
        assert (path, method) in registered, f"后端缺少 {method} {path}，前端路径表已失效"


def test_skill_names_and_versions_are_url_encoded(app_js):
    expand = _function_body(app_js, "skillEndpoint")
    # 中文技能名必须走编码，不能直接拼进 URL。
    assert 'url.replace("{" + key + "}", encodeURIComponent(String(values[key])))' in expand


def test_every_skill_endpoint_is_called_with_the_contract_method(app_js):
    # 列表与版本列表是 GET：不传 method，走 fetch 默认值。
    assert 'requestJson(skillEndpoint("list"))' in app_js
    assert 'requestJson(skillEndpoint("versions", { name: skill.name }))' in app_js

    # 停用 / 恢复：动作由当前状态决定，一律 POST。
    assert 'const action = enabled ? "disable" : "enable";' in app_js
    assert 'requestJson(skillEndpoint(action, { name: skill.name }), { method: "POST" })' in app_js

    # 回退：POST，路径里带被回退到的版本号。
    assert re.search(
        r'skillEndpoint\(\s*"restore",\s*\{\s*name:\s*pending\.name,\s*version:\s*pending\.version\s*\}\),\s*'
        r'\{\s*method:\s*"POST"\s*\}',
        app_js,
    ), "回退必须是 POST 到 /api/skills/{name}/versions/{version}/restore"


# ------------------------------------------------------------------ 列表渲染


def test_list_shows_name_description_version_and_state(app_js):
    assert "skill.name" in app_js
    assert "skill.description" in app_js
    assert "skill.version" in app_js
    assert "skill.enabled !== false" in app_js
    assert '"启用中"' in app_js and '"已停用"' in app_js
    assert "查看版本" in app_js and "收起版本" in app_js


def test_empty_list_has_a_readable_hint(app_js):
    assert "还没有学到任何习惯" in app_js
    # 读取失败时不能只留空白。
    assert "读取习惯列表失败" in app_js
    assert "读取失败：请确认后端服务是否正常" in app_js


def test_each_skill_can_be_disabled_and_enabled_again(app_js):
    assert 'const label = enabled ? "停用" : "恢复";' in app_js
    assert "后续新对话按新的状态执行" in app_js
    toggle = _function_body(app_js, "toggleSkill")
    assert "requestJson" in toggle and '"error"' in toggle
    # 成功后重新拉取列表，界面不会停在旧状态。
    assert "loadSkills();" in toggle


# ------------------------------------------------------------- 版本列表与回退


def test_version_panel_marks_the_current_version_and_offers_rollback(app_js):
    assert "当前版本" in app_js
    assert "回退到此版本" in app_js
    assert 'version.current ? " current" : ""' in app_js
    row = _function_body(app_js, "buildSkillVersionRow")
    # 当前版本不再提供回退入口，避免无意义的重复回退。
    assert "else if (!version.current)" in row


def test_rollback_asks_for_a_second_confirmation_before_sending(app_js):
    request = _function_body(app_js, "requestSkillRestore")
    assert "requestJson" not in request, "第一次点击只能进入确认态，不能直接改技能"
    assert "state.skillConfirm = { name: skill.name, version: version };" in request
    assert "确认回退" in app_js
    confirm = _function_body(app_js, "confirmSkillRestore")
    assert "requestJson" in confirm and '"error"' in confirm
    assert 'skillEndpoint("restore"' in confirm
    # 取消路径不得发请求，也不得留下待确认状态。
    cancel = _function_body(app_js, "cancelSkillRestore")
    assert "requestJson" not in cancel
    assert "state.skillConfirm = null;" in cancel
    assert "cancelSkillRestore" in _function_body(app_js, "buildSkillVersionRow")


def test_version_panel_reports_a_failed_version_read(app_js):
    fetch = _function_body(app_js, "fetchSkillVersions")
    assert "describeSkillFailure" in fetch
    assert '"error"' in fetch
    assert "版本读取失败" in app_js


# ------------------------------------------------- 停用态：回退要给出可执行指引


def test_rollback_of_a_disabled_skill_points_at_the_fix(app_js):
    # 文案本身是契约的一部分，不只是那个常量名。
    assert f'const SKILL_DISABLED_HINT = "{DISABLED_HINT}";' in app_js, "提示文案必须逐字使用约定措辞"
    request = _function_body(app_js, "requestSkillRestore")
    assert "SKILL_DISABLED_HINT" in request, "停用态必须先提示再决定是否发请求"
    assert "if (!skillEnabled(skill))" in request
    # 指引出现在「设置确认态」之前，并带 return 短路。
    assert request.index("SKILL_DISABLED_HINT") < request.index("state.skillConfirm")
    assert re.search(r"SKILL_DISABLED_HINT[\s\S]*?return;", request), "提示后必须直接返回，不能继续发请求"
    # 展开的版本面板里也要写明这句。
    assert "SKILL_DISABLED_HINT" in _function_body(app_js, "buildSkillVersions")
    assert "该习惯已停用" in app_js


def test_skill_disabled_400_is_explained_with_status_and_detail(app_js):
    describe = _function_body(app_js, "describeSkillFailure")
    assert 'detail.indexOf("disabled")' in describe
    assert "SKILL_DISABLED_HINT" in describe
    assert 'String(result.error || "")' in describe
    # 两条返回分支都必须同时带上 HTTP 状态与后端 detail；
    # 只留其中一条（或把状态丢掉）都会被下面的断言抓住。
    returns = [line.strip() for line in describe.splitlines() if line.strip().startswith("return ")]
    disabled_line = next((line for line in returns if "SKILL_DISABLED_HINT" in line), "")
    plain_line = next(
        (line for line in returns if "detail" in line and "SKILL_DISABLED_HINT" not in line), ""
    )
    assert disabled_line and "result.status" in disabled_line and "detail" in disabled_line, returns
    assert plain_line and "result.status" in plain_line and "detail" in plain_line, returns


def test_http_status_and_detail_reach_the_notice_line(app_js):
    notice = _function_body(app_js, "showSkillsNotice")
    assert 'el("skills-notice")' in notice
    assert '"skills-notice" + (message && tone ? " " + tone : "")' in notice
    for prefix in ("读取习惯列表失败：", "读取「", "」的版本失败：", "回退失败："):
        assert prefix in app_js, f"失败提示缺少 {prefix}"
    # 每个失败分支都把错误写进提示行，且带 error 语气。
    assert len(re.findall(r"describeSkillFailure\(result\)", app_js)) >= 4
    assert len(re.findall(r'"error"\)', app_js)) >= 4


# ------------------------------------------------------------------ 接线与样式


def test_skills_view_is_wired_into_the_router(app_js):
    assert 'el("view-skills").classList.toggle("active", view === "skills")' in app_js
    assert 'if (view === "skills") loadSkills();' in app_js
    assert 'el("skills-reload").onclick' in app_js


def test_every_skills_element_id_used_by_app_js_exists(app_js, index_html):
    referenced = set(re.findall(r'\bel\(\s*"(skills-[^"]+|view-skills)"\s*\)', app_js))
    assert referenced == {"skills-notice", "skills-list", "view-skills", "skills-reload"}, referenced
    from_html = set(re.findall(r'id="([^"]+)"', index_html))
    assert not (referenced - from_html), sorted(referenced - from_html)


def test_styles_cover_the_skills_view(styles_css):
    for selector in (
        ".skills-notice",
        ".skills-notice.ok",
        ".skills-notice.warn",
        ".skills-notice.error",
        ".skills-list",
        ".skill-card",
        ".skill-card.disabled",
        ".skill-title",
        ".skill-name",
        ".skill-meta",
        ".skill-desc",
        ".skill-actions",
        ".status-badge.enabled",
        ".status-badge.disabled",
        ".status-badge.current-badge",
        ".skill-versions",
        ".skill-version",
        ".skill-version.current",
        ".skill-version-actions",
        ".skill-confirm",
        ".skill-confirm-yes",
        ".skill-hint",
    ):
        assert selector in styles_css, f"{selector} 必须有样式"
