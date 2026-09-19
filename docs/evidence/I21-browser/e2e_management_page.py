"""Browser end-to-end check for the MellowDay management page (I21).

Drives the real server with a real Chromium: create, edit, complete/re-open,
undo and delete/undo on the records page, plus the local-time column.  The
assistant business tool reads the same data dir afterwards to prove that a
record edited in the page is what the assistant sees.
"""
import asyncio
import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(r"C:\Users\RuaCha\AppData\Local\Temp\i21-check\e2e-data")
os.environ["MELLOWDAY_DATA_DIR"] = str(DATA_DIR)
os.environ["MELLOWDAY_ENV_FILE"] = ""

from mellowday.personal_assistant.tools import execute_tool  # noqa: E402
from mellowday.storage.store import Store  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8791"
OUT = Path(r"C:\Users\RuaCha\AppData\Local\Temp\i21-check\e2e-evidence.md")
SHOT = Path(r"C:\Users\RuaCha\AppData\Local\Temp\i21-check\records-page.png")
EDIT_SHOT = Path(r"C:\Users\RuaCha\AppData\Local\Temp\i21-check\records-edit-mode.png")

lines: list[str] = []
failures: list[str] = []


def log(text: str) -> None:
    lines.append(text)
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def check(name: str, ok: bool, detail: str = "") -> None:
    log(("[PASS] " if ok else "[FAIL] ") + name + (" -- " + detail if detail else ""))
    if not ok:
        failures.append(name)


def rows(page):
    return page.eval_on_selector_all(
        "#records-table tbody tr",
        "rs => rs.map(r => Array.from(r.children).map(c => c.textContent.trim()))",
    )


def wait_rows(page, js: str, timeout: int = 8000) -> None:
    page.wait_for_function(js, timeout=timeout)


def wait_notice(page, fragment: str, timeout: int = 8000) -> str:
    page.wait_for_function(
        "f => { const n = document.getElementById('records-notice'); return n && n.textContent.includes(f); }",
        arg=fragment,
        timeout=timeout,
    )
    return page.eval_on_selector("#records-notice", "n => n.textContent")


def assistant_list_todos():
    """Call the assistant business tool from a fresh thread with its own loop.

    The Playwright sync API already owns an event loop, so asyncio.run cannot
    be used inline.
    """
    box = {}

    def worker():
        try:
            store = Store(data_dir=DATA_DIR)
            box["data"] = json.loads(asyncio.run(execute_tool(store, "list_todos", {})))
        except BaseException as exc:  # pragma: no cover - diagnostic only
            box["error"] = repr(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    if "error" in box:
        raise RuntimeError(box["error"])
    return box["data"]


edit_link = "#records-table tbody tr:not(.editing) td.row-actions .link.edit"
save_link = "tr.editing td.row-actions .link.edit"

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1360, "height": 940})
    console: list[str] = []
    page.on("console", lambda m: console.append(m.type + ": " + m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console.append("pageerror: " + str(e)))
    page.goto(BASE + "/", wait_until="load")

    # clean leftovers from an earlier run so the list starts empty
    for leftover in page.request.get(BASE + "/api/records/todos").json()["records"]:
        page.request.delete(BASE + "/api/records/todos/" + leftover["id"])
    page.reload(wait_until="load")

    # --- management page chrome (undo bar is created by app.js) -------------
    page.click('button.nav-item[data-view="todos"]')
    page.wait_for_selector("#records-toolbar", state="visible")
    check("records toolbar with undo button is rendered", page.locator("#records-undo").count() == 1)
    header = page.eval_on_selector_all("#records-table thead th", "hs => hs.map(h => h.textContent.trim())")
    check("table header has the local-time and action columns", header == ["标题", "备注", "时间（本地）", "状态", "操作"], " | ".join(header))
    check("empty state is readable before any record exists", "暂无记录" in rows(page)[0][0], rows(page)[0][0])

    # --- create through the page form (local wall clock 19:00 -> UTC 11:00) -
    page.fill("#record-title", "买牛奶")
    page.fill("#record-detail", "低脂")
    page.fill("#record-due", "2026-09-19T19:00")
    page.click("#record-form button[type=submit]")
    check("create shows a success notice", "已新建" in wait_notice(page, "已新建"))
    wait_rows(page, "() => { const r = document.querySelector('#records-table tbody tr'); return r && r.children.length === 5 && r.children[0].textContent.includes('买牛奶'); }")
    row = rows(page)[0]
    check("new row is listed", row[0] == "买牛奶" and row[1] == "低脂", " / ".join(row))
    check("time column shows LOCAL time, not the stored UTC value", row[2] == "2026-09-19 19:00", row[2])
    time_title = page.eval_on_selector("#records-table tbody tr td.cell-time", "c => c.title")
    check("tooltip still exposes the stored UTC instant", "2026-09-19T11:00:00+00:00" in time_title, time_title.replace(chr(10), " | "))
    check("status badge starts as 未完成", row[3] == "未完成", row[3])

    # --- complete / re-open ------------------------------------------------
    page.click("#records-table tbody tr td.row-actions .link.toggle")
    check("completing a todo reports it", "已完成" in wait_notice(page, "已完成"))
    wait_rows(page, "() => document.querySelector('#records-table tbody tr .status-badge').textContent.trim() === '已完成'")
    toggle_text = page.locator("#records-table tbody tr td.row-actions .link.toggle").inner_text().strip()
    check("row offers 重新打开 once finished", toggle_text == "重新打开", toggle_text)
    page.click("#records-undo")
    check("undo restores the previous status", "已撤销上一步" in wait_notice(page, "已撤销上一步"))
    wait_rows(page, "() => document.querySelector('#records-table tbody tr .status-badge').textContent.trim() === '未完成'")

    # --- edit title / detail / time ----------------------------------------
    page.click(edit_link)
    page.wait_for_selector("tr.editing")
    page.screenshot(path=str(EDIT_SHOT), full_page=True)
    due_input = page.eval_on_selector("tr.editing input[type=datetime-local]", "i => i.value")
    check("edit form prefills the local wall clock", due_input == "2026-09-19T19:00", due_input)
    check("edit form prefills title and detail",
          page.eval_on_selector_all("tr.editing input:not([type=datetime-local])", "is => is.map(i => i.value)") == ["买牛奶", "低脂"])
    page.fill("tr.editing input:not([type=datetime-local]) >> nth=0", "买燕麦奶")
    page.click(save_link)
    check("saving reports success", "已保存" in wait_notice(page, "已保存"))
    wait_rows(page, "() => document.querySelector('#records-table tbody tr td').textContent.trim() === '买燕麦奶'")
    check("edited title is shown in the table", rows(page)[0][0] == "买燕麦奶", rows(page)[0][0])

    # --- the assistant reads the same store (no model involved) -------------
    listed = assistant_list_todos()
    titles = [r.get("title") for r in listed.get("records", [])]
    check("assistant list_todos sees the value edited in the page", titles == ["买燕麦奶"], str(titles))
    assistant_record = listed["records"][0]
    local_ok = str(assistant_record.get("due_at_local", "")).startswith("2026-09-19T19:00:00")
    check("assistant view keeps UTC and adds the local rendering",
          assistant_record.get("due_at") == "2026-09-19T11:00:00+00:00" and local_ok,
          str(assistant_record.get("due_at")) + " / " + str(assistant_record.get("due_at_local")))

    api = page.request.get(BASE + "/api/records/todos").json()["records"][0]
    record_id = api["id"]
    check("web records API stores the ISO instant in UTC", api["due_at"] == "2026-09-19T11:00:00+00:00", str(api["due_at"]))
    check("web records API agrees with the assistant local time", api.get("due_at_local") == assistant_record.get("due_at_local"), str(api.get("due_at_local")))
    page.screenshot(path=str(SHOT), full_page=True)

    # --- undo the edit ------------------------------------------------------
    page.click("#records-undo")
    check("undo reports the edit it reverted", "已撤销上一步" in wait_notice(page, "已撤销上一步"))
    wait_rows(page, "() => document.querySelector('#records-table tbody tr td').textContent.trim() === '买牛奶'")
    check("undo restored the previous title", rows(page)[0][0] == "买牛奶", rows(page)[0][0])
    page.click("#records-undo")
    repeated = wait_notice(page, "已经撤销过了")
    check("a second undo is a notice, not an error", "已经撤销过了" in repeated and "失败" not in repeated, repeated)

    # --- delete and undo the delete ----------------------------------------
    page.click("#records-table tbody tr td.row-actions .link.danger")
    check("delete reports that it can be undone", "已删除" in wait_notice(page, "已删除"))
    wait_rows(page, "() => document.querySelector('#records-table tbody tr td.empty') !== null")
    check("deleted record disappears from the table", "暂无记录" in rows(page)[0][0])
    page.click("#records-undo")
    check("undo of the delete reports success", "已撤销上一步" in wait_notice(page, "已撤销上一步"))
    wait_rows(page, "() => { const r = document.querySelector('#records-table tbody tr'); return r && r.children.length === 5; }")
    check("deleted record is restored", rows(page)[0][0] == "买牛奶", rows(page)[0][0])

    # --- backend errors are visible, not silent ----------------------------
    page.click(edit_link)
    page.wait_for_selector("tr.editing")
    page.request.delete(BASE + "/api/records/todos/" + record_id)
    page.click(save_link)
    error_notice = wait_notice(page, "保存失败")
    check("a 404 from the backend is displayed to the user", "保存失败" in error_notice and "404" in error_notice, error_notice)
    check("the failed row stays in edit mode so typing is not lost", page.locator("tr.editing").count() == 1)

    # --- empty state on another kind ---------------------------------------
    page.click('button.nav-item[data-view="notes"]')
    wait_rows(page, "() => document.querySelector('#records-table tbody tr td.empty') !== null")
    check("switching kind shows its own empty state", "暂无记录" in rows(page)[0][0], rows(page)[0][0])
    page.click('button.nav-item[data-view="todos"]')
    page.wait_for_function("() => document.querySelector('#records-table tbody tr td.empty') !== null")

    # The single expected console entry is the browser logging the 404 that the
    # page just displayed to the user; anything else would be a real defect.
    unexpected = [entry for entry in console if "status of 404" not in entry]
    log("console entries seen: " + repr(console))
    check("no unexpected browser console errors", not unexpected, "; ".join(unexpected))
    browser.close()

summary = "FAILURES: " + str(len(failures)) + (" -> " + ", ".join(failures) if failures else " (all checks passed)")
log("")
log(summary)
OUT.write_text("# I21 browser end-to-end evidence\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
print("evidence written to", OUT)
raise SystemExit(1 if failures else 0)
