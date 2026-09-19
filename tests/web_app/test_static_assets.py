"""Static contract checks for the bundled management page assets.

The management page is plain JavaScript and CSS served straight out of
``mellowday/web_app/static``: there is no build step and the offline test suite
has no browser.  Everything a user can only reach through the page - editing a
record, finishing / re-opening it, undoing the last write and reading times in
the local timezone - is therefore pinned textually here, so that removing one of
those entry points breaks a test instead of only breaking the page.

Only static assertions live in this module; the HTTP behaviour behind them is
covered by ``tests/web_app/test_service.py`` and the storage tests.
"""
from __future__ import annotations

import re

import pytest

from mellowday import paths
from mellowday.storage.store import DEFAULT_STATUS, DONE_STATUSES, KINDS

STATIC = paths.static_dir()
APP_JS_PATH = STATIC / "app.js"
STYLES_CSS_PATH = STATIC / "styles.css"
INDEX_HTML_PATH = STATIC / "index.html"


@pytest.fixture(scope="module")
def app_js() -> str:
    return APP_JS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def styles_css() -> str:
    return STYLES_CSS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def index_html() -> str:
    return INDEX_HTML_PATH.read_text(encoding="utf-8")


def _status_rules(app_js: str) -> dict[str, str]:
    """Return the per-kind block of the STATUS_RULES map as raw text."""
    start = app_js.index("const STATUS_RULES")
    end = app_js.index("const STATUS_LABEL")
    block = app_js[start:end]
    rules: dict[str, str] = {}
    for kind in KINDS:
        match = re.search(rf"\b{kind}:\s*\{{(.*?)\}}", block, re.S)
        assert match, f"STATUS_RULES has no entry for {kind!r}"
        rules[kind] = match.group(1)
    return rules


def test_assets_are_utf8_text_with_readable_copy(app_js, styles_css, index_html):
    assert APP_JS_PATH.exists() and STYLES_CSS_PATH.exists() and INDEX_HTML_PATH.exists()
    # Decoding as UTF-8 must preserve the Chinese interface copy (a cp936
    # round-trip silently mangles it).
    assert "撤销上一步" in app_js
    assert "编辑" in app_js and "保存" in app_js and "取消" in app_js
    assert "table" in styles_css
    assert "MellowDay" in index_html


def test_app_js_uses_the_documented_record_endpoints(app_js):
    assert '"/api/records/"' in app_js
    assert '"/api/records/undo/"' in app_js
    assert re.search(r'method:\s*"PATCH"', app_js), "editing and status changes must PATCH"
    assert re.search(r'method:\s*"DELETE"', app_js)
    assert re.search(r'method:\s*"POST"', app_js)
    for kind in KINDS:
        assert f'"{kind}"' in app_js, f"the page must know the {kind!r} kind"
    assert "RECORD_KINDS" in app_js


def test_status_toggle_only_uses_statuses_the_store_accepts(app_js):
    rules = _status_rules(app_js)
    assert set(rules) == set(KINDS)
    for kind, body in rules.items():
        listed = re.search(r"doneValues:\s*\[(.*?)\]", body, re.S)
        assert listed, f"{kind!r} must declare which statuses count as finished"
        mapped = set(re.findall(r'"([^"]+)"', listed.group(1)))
        assert mapped == set(DONE_STATUSES[kind]), (
            f"{kind!r} finished statuses {sorted(mapped)} must match the store's "
            f"{sorted(DONE_STATUSES[kind])}"
        )
        done_value = re.search(r'doneValue:\s*"([^"]+)"', body)
        open_value = re.search(r'openValue:\s*"([^"]+)"', body)
        assert done_value and open_value, f"{kind!r} must map both directions"
        assert done_value.group(1) in DONE_STATUSES[kind]
        # Re-opening a record must land back on the status the store assigns to
        # new records, otherwise the record sits in a state the store never
        # produces on its own.
        assert open_value.group(1) == DEFAULT_STATUS[kind]

    # The management page always states both directions of the toggle.
    assert "重新打开" in app_js
    assert re.search(r"actionLink\(toggleTarget\(", app_js), "each row needs a status toggle"


def test_rows_can_be_edited_in_place_and_saved(app_js):
    assert "editingId" in app_js
    assert re.search(r'actionLink\("编辑"', app_js)
    assert re.search(r'actionLink\("保存"', app_js)
    assert re.search(r'actionLink\("取消"', app_js)
    assert re.search(r"function saveEdit\(", app_js)
    # The PATCH body carries exactly the editable fields.
    assert re.search(r"const payload = \{ title: title, detail:", app_js)
    assert "payload.due_at" in app_js
    # Clearing the time input must clear due_at rather than being dropped.
    assert re.search(r"payload\.due_at = draft\.due \?", app_js)
    assert "toISOString()" in app_js


def test_undo_remembers_one_operation_id_and_consumes_it_once(app_js):
    assert "operation_id" in app_js
    assert re.search(r"function rememberOperation\(", app_js)
    # Every write records its operation_id, including create and status changes.
    for action in ('"create"', '"update"', '"status"', '"delete"'):
        assert f"rememberOperation(result.data, {action}" in app_js, f"{action} must be undoable"
    assert re.search(r"function undoLastOperation\(", app_js)
    assert '"/api/records/undo/"' in app_js
    assert "consumed" in app_js
    # A second click is a notice, not an error and not a second undo request.
    assert "已经撤销过了" in app_js
    # The button lives in app.js because index.html is not ours to change.
    assert re.search(r'\.id = "records-undo"', app_js)
    assert re.search(r'\.id = "records-notice"', app_js)
    assert re.search(r"undo\.onclick = undoLastOperation", app_js)


def test_time_column_shows_local_time_not_the_stored_utc_value(app_js):
    assert "due_at_local" in app_js
    assert re.search(r"record\.due_at_local \|\| record\.due_at", app_js)
    assert re.search(r"function formatLocalMoment\(", app_js)
    # Local getters, not the UTC ones: the page runs in the user timezone.
    assert "getHours()" in app_js and "getMinutes()" in app_js
    assert "getUTCHours" not in app_js
    # Records without a due date fall back to a local rendering of created_at.
    assert re.search(r"formatLocalMoment\(record\.created_at\)", app_js)
    assert "（创建）" in app_js
    # The raw UTC field is never printed into the table any more.
    assert not re.search(r"escapeHtml\(r\.due_at", app_js)
    assert not re.search(r"escapeHtml\(record\.due_at[^_]", app_js)
    # The table header says so, and new records still submit an ISO instant.
    assert "时间（本地）" in app_js


def test_backend_errors_are_shown_instead_of_being_swallowed(app_js):
    assert re.search(r"function describeError\(", app_js)
    assert "404" in app_js and "400" in app_js
    assert re.search(r'showRecordsNotice\([^;]*"error"\)', app_js, re.S)
    assert "读取记录失败" in app_js
    assert "保存失败" in app_js
    assert "删除失败" in app_js
    assert "撤销失败" in app_js
    # A failed save keeps the row in edit mode so typing is not lost.
    assert "Stay in edit mode" in app_js
    assert re.search(r"state\.editingId = null;\n\s*showRecordsNotice", app_js)


def test_every_element_id_used_by_app_js_exists(app_js, index_html):
    referenced = set(re.findall(r'\bel\(\s*"([^"]+)"\s*\)', app_js))
    assert referenced, "the page reads its controls through el()"
    from_html = set(re.findall(r'id="([^"]+)"', index_html))
    dynamic = set(re.findall(r'\.id = "([^"]+)"', app_js))
    missing = sorted(referenced - from_html - dynamic)
    assert not missing, f"app.js looks up ids that nothing creates: {missing}"


def test_table_header_is_generated_by_app_js(app_js):
    assert re.search(
        r"<tr><th>标题</th><th>备注</th><th>时间（本地）</th><th>状态</th><th>操作</th></tr>", app_js
    )
    assert 'colspan="5"' in app_js
    assert "暂无记录" in app_js


def test_styles_cover_the_new_management_controls(styles_css):
    for selector in (
        ".records-toolbar",
        ".records-notice",
        ".records-notice.error",
        ".row-actions",
        ".cell-input",
        ".cell-time",
        "tr.editing",
        ".status-badge",
        ".status-badge.done",
        "td .link.cancel",
        "td .link.danger",
        "td .link.toggle",
    ):
        assert selector in styles_css, f"{selector} must be styled"
