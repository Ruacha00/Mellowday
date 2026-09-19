"""T8 证据脚本：真实进程 + 真实 Chromium，重开会话后能看到工具调用、结果与错误。

不是 pytest 模块（文件名不以 test_ 开头）。直接运行：

    python tests/web_app/manual_t8_history_panel.py

启动三样真实东西（无外网）：
* 127.0.0.1 上的假 OpenAI 兼容模型：第一轮要求调用 list_notes（limit=200），之后回答文本；
* 真实 MellowDay 服务进程（uvicorn，隔离数据目录，MELLOWDAY_ENV_FILE 关闭）；
* 真实 Chromium（Playwright）打开真实页面。

检查：
  A. 200 条长笔记 → list_notes 结果 > 30KB → 走大结果路径（产物 + 占位提示）；
  B. 关掉模型后发一条消息 → 真实错误进入执行记录；
  C. 浏览器重开会话：工具调用行、工具结果行（含预览）、错误行都在，且用户/助手消息还在；
  D. 结果行可折叠展开；点「查看原文」要么读到原文，要么给出带 HTTP 状态的可见失败（不得静默）；
     后端是否已透传结构化 ref 会被记录下来（t10 前后各跑一次即可对比）。
退出码：全部通过 0，否则 1。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(tempfile.mkdtemp(prefix="mellowday-history-"))
SESSION = "t8-history"
USER_MESSAGE = "把笔记列出来看看"
NOTE_COUNT = 200
CHECK: dict[str, bool] = {}
DETAIL: dict[str, object] = {}


def check(name: str, ok: bool, info: object = "") -> None:
    CHECK[name] = bool(ok)
    DETAIL[name] = info
    print(("PASS  " if ok else "FAIL  ") + name + ((" :: " + str(info)[:400]) if info != "" else ""))


state = {"calls": 0, "lock": threading.Lock()}


class ModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _chunk(self, payload: dict) -> None:
        self.wfile.write(("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        with state["lock"]:
            state["calls"] += 1
            n = state["calls"]
        model = body.get("model")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if n == 1:
            arguments = json.dumps({"limit": 200, "include_done": False}, ensure_ascii=False)
            self._chunk({
                "id": "c1", "object": "chat.completion.chunk", "created": 0, "model": model,
                "choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": 0, "id": "call_t8_1", "type": "function",
                    "function": {"name": "list_notes", "arguments": arguments},
                }]}, "finish_reason": None}],
            })
            self._chunk({
                "id": "c1", "object": "chat.completion.chunk", "created": 0, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            })
        else:
            for char in "一共" + str(NOTE_COUNT) + "条笔记，都列在上面了。":
                self._chunk({
                    "id": "c2", "object": "chat.completion.chunk", "created": 0, "model": model,
                    "choices": [{"index": 0, "delta": {"content": char}, "finish_reason": None}],
                })
            self._chunk({
                "id": "c2", "object": "chat.completion.chunk", "created": 0, "model": model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            })
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()


def free_ports(count: int) -> list[int]:
    """Reserve distinct ports: bind them all at once, then release them together."""
    sockets = []
    ports = []
    for _ in range(count):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        sockets.append(probe)
        ports.append(probe.getsockname()[1])
    for probe in sockets:
        probe.close()
    return ports


def stream_turn(client: httpx.Client, message: str) -> list[dict]:
    events: list[dict] = []
    with client.stream("POST", "/api/chat", json={"session_id": SESSION, "message": message}) as response:
        for line in response.iter_lines():
            if not line.startswith("data: "):
                continue
            try:
                events.append(json.loads(line[6:]))
            except ValueError:
                continue
    return events


def main() -> int:
    model_port, app_port = free_ports(2)
    print("ports: model=", model_port, "app=", app_port)
    model_server = ThreadingHTTPServer(("127.0.0.1", model_port), ModelHandler)
    model_thread = threading.Thread(target=model_server.serve_forever, daemon=True)
    model_thread.start()

    (DATA / "config.json").write_text(
        json.dumps({"model": {
            "api_key": "t8-key",
            "api_base": f"http://127.0.0.1:{model_port}/v1",
            "model": "t8-fake-model",
            "thinking": False,
            "max_turns": None,
        }}, ensure_ascii=False),
        encoding="utf-8",
    )

    child_env = {k: v for k, v in os.environ.items() if not k.startswith("MELLOWDAY_")}
    child_env["MELLOWDAY_ENV_FILE"] = ""
    server = subprocess.Popen(
        [sys.executable, "-m", "mellowday.web_app", "--data-dir", str(DATA), "--port", str(app_port)],
        cwd=str(ROOT), env=child_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    server_log: list[str] = []

    def drain() -> None:
        # A full pipe would freeze the child; keep reading it until it exits.
        for line in server.stdout or []:
            server_log.append(line.rstrip())

    threading.Thread(target=drain, daemon=True).start()
    browser = None
    playwright = None
    try:
        client = httpx.Client(base_url=f"http://127.0.0.1:{app_port}", timeout=60)
        deadline = time.time() + 40
        health = None
        while time.time() < deadline:
            try:
                health = client.get("/api/health").json()
                break
            except Exception:
                time.sleep(0.3)
        check("server_up", bool(health and health.get("ok")), health)

        for index in range(NOTE_COUNT):
            created = client.post("/api/records/notes", json={
                "title": "笔记 " + str(index + 1),
                "detail": "第" + str(index + 1) + "条笔记的正文：" + ("内容" * 80),
            })
            if created.status_code != 200:
                check("notes_created", False, created.status_code)
                break
            if (index + 1) % 50 == 0:
                print("created", index + 1, "notes", flush=True)
        listed = client.get("/api/records/notes").json().get("records", [])
        check("notes_created", len(listed) == NOTE_COUNT, len(listed))

        events = stream_turn(client, USER_MESSAGE)
        types = [event.get("type") for event in events]
        results = [event for event in events if event.get("type") == "tool_result"]
        check("turn_emitted_tool_result", bool(results), types[-6:])
        structured = [event for event in results if event.get("ref")]
        check("event_carries_structured_ref", bool(structured),
              {"ref": structured[0].get("ref"), "truncated": structured[0].get("truncated"),
               "chars": structured[0].get("chars")} if structured else "no structured ref in event")

        payload = client.get("/api/sessions/" + SESSION).json()
        trace = payload.get("trace", [])
        entry_types = [entry.get("type") for entry in trace]
        trace_results = [entry for entry in trace if entry.get("type") == "tool_result"]
        DETAIL["trace_types"] = entry_types
        DETAIL["trace_has_trace_display"] = "trace_display" in payload
        DETAIL["trace_tool_result_keys"] = sorted(trace_results[0].keys()) if trace_results else []
        check("trace_has_tool_call", "tool_call" in entry_types, entry_types)
        check("trace_has_tool_result", "tool_result" in entry_types, entry_types)
        check("trace_has_trace_display", isinstance(payload.get("trace_display"), list)
              and len(payload.get("trace_display") or []) == len(trace),
              len(payload.get("trace_display") or []))
        first_result = trace_results[0] if trace_results else {}
        stored = str(first_result.get("result") or "")
        # CONTRACTS 6ter.2：进入上下文（以及 trace）的是占位提示，原文只在产物文件里。
        check("trace_result_is_the_placeholder_not_the_original",
              0 < len(stored) < 4000 and "saved as ref" in stored, len(stored))
        check("trace_tool_result_declares_the_original_size",
              int(first_result.get("chars") or 0) > 30000, first_result.get("chars"))
        check("trace_tool_result_carries_ref",
              bool(first_result.get("ref")),
              {k: first_result.get(k) for k in ("ref", "chars", "truncated")} if first_result else "")
        artifact = DATA / "tool_results" / SESSION / (str(first_result.get("ref")) + ".txt")
        artifact_text = artifact.read_text(encoding="utf-8") if artifact.is_file() else ""
        check("original_is_in_the_artifact_file",
              len(artifact_text) > 30000 and "笔记 1" in artifact_text, len(artifact_text))
        DETAIL["artifact_path"] = str(artifact)

        # t10 之前受限引用读取还没有 HTTP 入口：这里探测一次，用来决定浏览器断言走哪条分支。
        probe = client.get("/api/sessions/" + SESSION + "/tool-results/" + str(first_result.get("ref")) +
                           "?offset=0&limit=200")
        route_ready = probe.status_code == 200 and bool(probe.json().get("ok"))
        DETAIL["reference_route_status"] = probe.status_code
        DETAIL["reference_route_ready"] = route_ready
        if route_ready:
            body = probe.json()
            base = "/api/sessions/" + SESSION + "/tool-results/" + str(first_result.get("ref"))
            paged = client.get(base + "?offset=1000&limit=200")
            checks_page = paged.status_code == 200 and paged.json().get("offset") == 1000
            located = client.get(base + "?query=" + "笔记 200")
            checks_query = located.status_code == 200 and located.json().get("match_offset") is not None
            check("reference_route_pages_by_offset", checks_page, paged.json().get("offset"))
            check("reference_route_locates_a_passage", checks_query,
                  located.json().get("match_offset") if located.status_code == 200 else located.status_code)
            check("reference_route_reports_the_total", body.get("total_chars") == len(artifact_text),
                  body.get("total_chars"))
            bad_ref = client.get("/api/sessions/" + SESSION + "/tool-results/bad.ref")
            check("illegal_ref_is_refused_not_500", bad_ref.status_code == 400, bad_ref.status_code)
            unknown_ref = client.get("/api/sessions/" + SESSION + "/tool-results/nope-nope-nope")
            check("unknown_ref_is_404", unknown_ref.status_code == 404, unknown_ref.status_code)

        model_server.shutdown()
        model_server.server_close()
        error_events = stream_turn(client, "模型已经关掉了，这条应该报错")
        error_types = [event.get("type") for event in error_events]
        after = client.get("/api/sessions/" + SESSION).json().get("trace", [])
        errors = [entry for entry in after if entry.get("type") == "error"]
        DETAIL["error_event_seen"] = "error" in error_types
        check("error_recorded_in_trace", bool(errors), [entry.get("message") for entry in errors][:1])

        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1360, "height": 900})
        page.goto(f"http://127.0.0.1:{app_port}/", wait_until="networkidle")
        page.wait_for_selector(f'#session-list li[title="{SESSION}"]', timeout=15000)
        page.click(f'#session-list li[title="{SESSION}"]')
        page.wait_for_selector(".trace-row", timeout=15000)

        call_rows = page.locator(".trace-tool-call")
        result_rows = page.locator(".trace-tool-result")
        error_rows = page.locator(".trace-error")
        check("browser_tool_call_row", call_rows.count() >= 1,
              call_rows.first.inner_text() if call_rows.count() else "none")
        check("browser_tool_result_row", result_rows.count() >= 1,
              result_rows.first.inner_text()[:200] if result_rows.count() else "none")
        check("browser_error_row", error_rows.count() >= 1,
              error_rows.first.inner_text()[:200] if error_rows.count() else "none")
        check("browser_user_message_kept",
              USER_MESSAGE in page.inner_text("#messages"), None)
        reply_visible = page.locator("#messages .msg.assistant").count() >= 1 and bool(
            page.locator("#messages .msg.assistant").last.inner_text().strip()
        )
        check("browser_assistant_reply_kept", reply_visible, None)

        call_rows.first.locator(".trace-head").click()
        call_body_visible = call_rows.first.locator(".trace-body").is_visible()
        call_text = call_rows.first.locator(".trace-pre").inner_text()
        check("tool_call_expands_with_arguments", call_body_visible and "limit" in call_text, call_text[:120])

        result_rows.first.locator(".trace-head").click()
        result_body_visible = result_rows.first.locator(".trace-body").is_visible()
        preview = result_rows.first.locator(".trace-pre").first.inner_text()
        check("tool_result_expands_with_preview", result_body_visible and len(preview) > 100, len(preview))

        original_button = result_rows.first.locator(".trace-original")
        check("large_result_offers_the_original_by_reference", original_button.count() > 0, None)
        original_button.first.click()
        page.wait_for_timeout(2000)
        box_text = result_rows.first.locator(".trace-original-box").inner_text()
        check("reference_read_is_never_silent", bool(box_text.strip()), box_text[:200])
        if route_ready:
            head = artifact_text[:200]
            check("reference_read_returns_the_original", head in box_text or len(box_text) > 500,
                  box_text[:160])
        else:
            check("missing_route_is_reported_with_a_status",
                  "原文读取失败" in box_text and "HTTP" in box_text, box_text[:200])
            DETAIL["blocked"] = ("超长结果经 ref 展开：前端入口与可见失败已验证，"
                                 "受限引用 HTTP 路由待 t10 落地后重跑本脚本")

        if route_ready:
            original_text = result_rows.first.locator(".trace-original-text")
            first_page = original_text.inner_text()
            result_rows.first.locator(".trace-more").click()
            page.wait_for_function(
                "n => (document.querySelector('.trace-original-text')?.textContent.length || 0) > n",
                arg=len(first_page),
            )
            second_page = original_text.inner_text()
            check("browser_next_page_appends_original",
                  len(second_page) == 16000 and second_page.startswith(first_page))
            original_button.first.click()
            check("browser_collapse_hides_original", original_text.count() == 0)
            original_button.first.click()
            check("browser_reopen_preserves_pages", original_text.inner_text() == second_page)
            while result_rows.first.locator(".trace-more").count():
                before = len(original_text.inner_text())
                result_rows.first.locator(".trace-more").click()
                page.wait_for_function(
                    "n => (document.querySelector('.trace-original-text')?.textContent.length || 0) > n",
                    arg=before,
                )
            check("browser_all_pages_equal_saved_original", original_text.inner_text() == artifact_text)
            check("browser_end_of_original_is_visible", "已到结尾" in result_rows.first.inner_text())

        screenshot = DATA / "t8-history-panel.png"
        page.screenshot(path=str(screenshot), full_page=False)
        DETAIL["screenshot"] = str(screenshot)

        # ---- 记忆管理：被技能取代的事实要显示来源（CONTRACTS 6quater.2 的字段形状） ----
        superseded = client.post("/api/records/memories", json={
            "title": "下班时间",
            "detail": "用户 18:30 下班",
            "status": "superseded",
            "meta": {
                "superseded_by_skill": "每周回顾",
                "superseded_at": "2026-09-18T12:00:00+00:00",
                "superseded_reason": "与习惯规则实质重叠",
            },
        })
        check("superseded_fact_created", superseded.status_code == 200,
              superseded.status_code)
        active = client.post("/api/records/memories", json={
            "title": "常喝美式", "detail": "口味偏好，不再改", "status": "active",
        })
        check("active_fact_created", active.status_code == 200, active.status_code)

        page.click('[data-view="memories"]')
        page.wait_for_selector("#records-table tbody tr", timeout=10000)
        rows = page.locator("#records-table tbody tr")
        row_texts = [rows.nth(index).inner_text() for index in range(rows.count())]
        joined = "\n".join(row_texts)
        DETAIL["memories_rows"] = row_texts
        check("memories_row_shows_the_supersede_source", "被习惯「每周回顾」取代" in joined,
              joined[:400])
        check("memories_row_explains_recall_stop", "不再参与召回" in joined, None)
        check("memories_row_shows_a_readable_badge", "已被替代" in joined, None)
        check("memories_row_shows_a_local_time", "时间 " in joined, None)
        active_row = next((item for item in row_texts if "常喝美式" in item), "")
        check("active_fact_has_no_supersede_source", bool(active_row) and "取代" not in active_row,
              active_row[:160])
        memories_shot = DATA / "t8-memories-superseded.png"
        page.screenshot(path=str(memories_shot), full_page=False)
        DETAIL["memories_screenshot"] = str(memories_shot)
        page.close()
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()
        try:
            model_server.shutdown()
        except Exception:
            pass
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
        if server_log:
            print("server log tail:")
            for line in server_log[-15:]:
                print("   ", line)

    (DATA / "browser-report.json").write_text(
        json.dumps({"checks": CHECK, "details": DETAIL}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failures = [name for name, ok in CHECK.items() if not ok]
    print()
    print("detail:", json.dumps(DETAIL, ensure_ascii=False)[:2000])
    print("checks:", len(CHECK), "failures:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
