"""Second browser pass: layout sanity, created_at fallback, per-kind status."""
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8791"
OUT = Path(r"C:\Users\RuaCha\AppData\Local\Temp\i21-check\e2e-evidence-2.md")
lines = []
failures = []


def log(text):
    lines.append(text)
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def check(name, ok, detail=""):
    log(("[PASS] " if ok else "[FAIL] ") + name + (" -- " + detail if detail else ""))
    if not ok:
        failures.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1360, "height": 940})
    page.goto(BASE + "/", wait_until="load")

    # a note is a kind that is not a todo: exercises the generic table path
    page.request.post(BASE + "/api/records/notes", data={"title": "会议纪要", "detail": "三行"})
    page.click('button.nav-item[data-view="notes"]')
    page.wait_for_selector("#records-table tbody tr td.row-actions")

    # --- layout sanity: toolbar above the table, edit inputs usable ---------
    toolbar = page.locator("#records-toolbar").bounding_box()
    table = page.locator(".table-wrap").bounding_box()
    check("undo toolbar is laid out above the table", toolbar and table and toolbar["y"] + toolbar["height"] <= table["y"] + 1,
          f"toolbar y={toolbar['y']:.0f} h={toolbar['height']:.0f}, table y={table['y']:.0f}")
    check("undo button is visible and labelled",
          page.locator("#records-undo").is_visible() and page.locator("#records-undo").inner_text().strip() == "撤销上一步")
    check("notice line is present", page.locator("#records-notice").count() == 1)

    # --- created_at fallback for a record without a due date ---------------
    time_cell = page.locator("#records-table tbody tr td.cell-time").first
    cell_text = time_cell.inner_text().strip()
    created = page.request.get(BASE + "/api/records/notes").json()["records"][0]["created_at"]
    expected = datetime.fromisoformat(created).astimezone().strftime("%Y-%m-%d %H:%M")
    check("record without a due date falls back to a local created_at", cell_text.startswith(expected) and "（创建）" in cell_text,
          cell_text + " vs expected " + expected + " from " + created)

    # --- per-kind status mapping (notes: 归档 / 恢复) ------------------------
    toggle = page.locator("#records-table tbody tr td.row-actions .link.toggle").first
    check("notes offer 归档 rather than 完成", toggle.inner_text().strip() == "归档", toggle.inner_text().strip())
    toggle.click()
    page.wait_for_function("() => document.querySelector('#records-notice').textContent.includes('已归档')")
    stored = page.request.get(BASE + "/api/records/notes").json()["records"][0]["status"]
    check("归档 writes the status the store expects for notes", stored == "archived", str(stored))
    check("finished note is still listed with its badge",
          page.locator("#records-table tbody tr .status-badge").first.inner_text().strip() == "已归档",
          page.locator("#records-table tbody tr .status-badge").first.inner_text().strip())
    page.click("#records-undo")
    page.wait_for_function("() => document.querySelector('#records-notice').textContent.includes('已撤销上一步')")
    page.wait_for_function("() => document.querySelector('#records-table tbody tr .status-badge').textContent.trim() === '有效'")
    check("undo returns the note to active",
          page.request.get(BASE + "/api/records/notes").json()["records"][0]["status"] == "active")

    # --- edit state geometry ----------------------------------------------
    page.click("#records-table tbody tr:not(.editing) td.row-actions .link.edit")
    page.wait_for_selector("tr.editing")
    boxes = page.eval_on_selector_all(
        "tr.editing input",
        "is => is.map(i => ({w: i.getBoundingClientRect().width, h: i.getBoundingClientRect().height, v: i.value}))",
    )
    check("every edit input is rendered with a usable size", len(boxes) == 3 and all(b["w"] > 60 and b["h"] > 18 for b in boxes), str(boxes))
    check("edit inputs are prefilled with the record", [b["v"] for b in boxes][:2] == ["会议纪要", "三行"], str([b["v"] for b in boxes]))
    save_visible = page.locator("tr.editing td.row-actions .link.edit").is_visible()
    cancel_visible = page.locator("tr.editing td.row-actions .link.cancel").is_visible()
    check("save and cancel are both visible in edit state", save_visible and cancel_visible)
    page.locator("tr.editing td.row-actions .link.cancel").click()
    page.wait_for_function("() => document.querySelectorAll('tr.editing').length === 0")
    check("cancel returns the row to browse state", page.locator("tr.editing").count() == 0)

    # clean up the notes used by this pass
    for record in page.request.get(BASE + "/api/records/notes").json()["records"]:
        page.request.delete(BASE + "/api/records/notes/" + record["id"])
    for record in page.request.get(BASE + "/api/records/todos").json()["records"]:
        page.request.delete(BASE + "/api/records/todos/" + record["id"])
    browser.close()

log("")
log("FAILURES: " + str(len(failures)) + (" -> " + ", ".join(failures) if failures else " (all checks passed)"))
OUT.write_text("# I21 second browser pass\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
raise SystemExit(1 if failures else 0)
