"""Real-process evidence for the two T1 fixes (delete + queue, undo conflict).

This file is NOT a pytest module (its name does not start with "test_"), so the
offline suite ignores it.  Run it directly when process-level evidence is
wanted instead of in-process evidence:

    python tests/web_app/manual_t1_regression.py

It starts no external network: a fake OpenAI-compatible model on 127.0.0.1 and
the real MellowDay server (uvicorn, "python -m mellowday.web_app") with an
isolated data directory, then checks two things through real HTTP and a real
browser (Chromium via Playwright):

  A. while one turn of a session is executing, a second turn of the same
     session is queued and the session is deleted: the model is called exactly
     once, the queued turn is answered with the deletion, and no session file
     comes back;
  B. the management page is told why an undo was refused: edit the title,
     edit the detail from another client, click "undo the last step" - the
     notice names the field that would have been lost, and the detail is
     still there.

Exit status: 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("TEMP", ".")) / "md_t1_evidence_data"
OUT = Path(os.environ.get("TEMP", ".")) / "md_t1_evidence.md"

FULL_REPLY = "回复1号：" + "内容" * 6
"""What the fake model streams for the first call (used to see a partial answer)."""

state = {"active": 0, "calls": [], "lock": threading.Lock()}
lines: list[str] = []
failures: list[str] = []
T0 = time.time()


def stamp(label: str) -> None:
    """Timeline entry: the ordering is part of the evidence."""
    log("    +%6.2fs  %s" % (time.time() - T0, label))


def log(text: str) -> None:
    lines.append(text)
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def check(name: str, ok: bool, detail: str = "") -> None:
    log(("[PASS] " if ok else "[FAIL] ") + name + (" -- " + detail if detail else ""))
    if not ok:
        failures.append(name)


class Handler(BaseHTTPRequestHandler):
    """A slow OpenAI-compatible stream: one call is visible for a while."""

    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        messages = body.get("messages") or []
        last_user = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                last_user = str(message.get("content") or "")[:16]
                break
        with state["lock"]:
            state["active"] += 1
            index = len(state["calls"]) + 1
            slot = {"n": index, "last_user": last_user, "chunks": 0, "start": time.time()}
            state["calls"].append(slot)
        text = "回复" + str(index) + "号：" + "内容" * 6
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for char in text:
                chunk = {
                    "id": "c" + str(index),
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": body.get("model"),
                    "choices": [
                        {"index": 0, "delta": {"content": char}, "finish_reason": None}
                    ],
                }
                self.wfile.write(("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8"))
                self.wfile.flush()
                with state["lock"]:
                    slot["chunks"] += 1
                time.sleep(0.4)
            final = {
                "id": "c" + str(index),
                "object": "chat.completion.chunk",
                "created": 0,
                "model": body.get("model"),
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
            self.wfile.write(("data: " + json.dumps(final) + "\n\n").encode("utf-8"))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            pass
        finally:
            with state["lock"]:
                state["active"] -= 1


def calls() -> list[dict]:
    with state["lock"]:
        return [dict(item) for item in state["calls"]]


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def wait_until(predicate, timeout: float = 20.0, what: str = "condition") -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def frames_of(body: str) -> list[dict]:
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def warm_client(base: str, *, timeout: float = 60) -> httpx.Client:
    """A client whose connection is already open: the first request of a brand
    new client costs seconds on this loopback, and phase A depends on the
    deletion landing inside the running model call."""
    client = httpx.Client(base_url=base, timeout=timeout)
    client.get("/api/health")
    return client


def chat_in_background(client: httpx.Client, tag: str, session_id: str, message: str, started: threading.Event, box: dict) -> None:
    """Stream one chat request; signal on its first frame, keep the body."""
    frames: list[dict] = []
    try:
        with client.stream(
            "POST", "/api/chat", json={"session_id": session_id, "message": message}
        ) as response:
            box["status"] = response.status_code
            stamp(tag + " response headers " + str(response.status_code))
            for line in response.iter_lines():
                if line.startswith("data: "):
                    frame = json.loads(line[len("data: "):])
                    frames.append(frame)
                    if not started.is_set():
                        stamp(tag + " first frame: " + str(frame.get("type")))
                    started.set()
    except Exception as exc:  # pragma: no cover - diagnostic
        box["error"] = repr(exc)
        stamp(tag + " stream error " + repr(exc))
        started.set()
    box["frames"] = frames
    stamp(tag + " stream ended with " + str(frames[-1].get("type") if frames else None))


def session_files() -> list[str]:
    sessions = DATA / "sessions"
    if not sessions.exists():
        return []
    return sorted(p.name for p in sessions.iterdir())


def phase_a(base: str) -> None:
    log("")
    log("== A: executing turn + queued turn + delete ==")
    first_started = threading.Event()
    second_started = threading.Event()
    first_box: dict = {}
    second_box: dict = {}
    control = warm_client(base, timeout=30)
    first_client = warm_client(base)
    second_client = warm_client(base)
    try:
        first = threading.Thread(
            target=chat_in_background,
            args=(first_client, "T1", "t1queue", "第一轮", first_started, first_box),
            daemon=True,
        )
        first.start()
        check("the first turn answers with a stream", first_started.wait(20))
        check(
            "the model is streaming for the first turn",
            wait_until(lambda: len(calls()) == 1 and state["active"] == 1),
        )
        stamp("the first turn is executing its model call")

        second = threading.Thread(
            target=chat_in_background,
            args=(second_client, "T2", "t1queue", "第二轮", second_started, second_box),
            daemon=True,
        )
        second.start()
        check("the queued turn resolved its session before the deletion", second_started.wait(20))
        check(
            "the first turn is still executing while the second waits",
            state["active"] == 1 and len(calls()) == 1,
            "active=" + str(state["active"]) + " calls=" + str(len(calls())),
        )
        stamp("the queued turn is waiting, the deletion goes out now")

        deleted = control.delete("/api/sessions/t1queue")
        stamp("DELETE answered " + str(deleted.status_code))
        check("DELETE answers 200", deleted.status_code == 200, str(deleted.status_code))
        first.join(30)
        second.join(30)
        check("the executing turn finished", not first.is_alive())
        check("the queued turn finished", not second.is_alive())
    finally:
        control.close()
        first_client.close()
        second_client.close()

    with httpx.Client(base_url=base, timeout=30) as client:
        seen = calls()
        check(
            "the model is called exactly once",
            len(seen) == 1,
            "calls=" + str([c["last_user"] for c in seen]),
        )
        check(
            "the second user message never reached the model",
            all("第二轮" not in str(c["last_user"]) for c in seen),
            str([c["last_user"] for c in seen]),
        )
        second_frames = second_box.get("frames") or []
        check(
            "the queued turn is told the session was deleted",
            any(
                frame.get("type") == "error" and "删除" in str(frame.get("message", ""))
                for frame in second_frames
            ),
            str([f.get("type") for f in second_frames]),
        )
        check(
            "the queued turn still ends with done",
            bool(second_frames) and second_frames[-1].get("type") == "done",
            str(second_frames[-1] if second_frames else None),
        )
        check(
            "the executing turn still ends with done",
            bool(first_box.get("frames")) and first_box["frames"][-1].get("type") == "done",
        )
        first_text = "".join(
            str(frame.get("text") or "")
            for frame in (first_box.get("frames") or [])
            if frame.get("type") == "text_delta"
        )
        check(
            "the deletion stopped the executing turn mid-answer",
            0 < len(first_text) < len(FULL_REPLY),
            "chars=" + str(len(first_text)) + " of " + str(len(FULL_REPLY)),
        )
        log("model calls seen: " + str([(c["n"], c["last_user"], c["chunks"]) for c in seen]))
        check(
            "the session stays deleted over HTTP",
            client.get("/api/sessions/t1queue").status_code == 404,
        )
        time.sleep(0.5)
        check("no session file came back", session_files() == [], str(session_files()))


def phase_b(base: str) -> None:
    log("")
    log("== B: the page is shown why an undo was refused ==")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1360, "height": 940})
        page.goto(base + "/", wait_until="load")
        page.click('button.nav-item[data-view="notes"]')
        page.wait_for_selector("#records-toolbar", state="visible")

        page.fill("#record-title", "原标题")
        page.fill("#record-detail", "D0")
        page.click("#record-form button[type=submit]")
        page.wait_for_function(
            "() => document.querySelector('#records-notice').textContent.includes('已新建')"
        )

        # op1: the page edits the title and remembers the operation.
        page.click("#records-table tbody tr td.row-actions .link.edit")
        page.wait_for_selector("tr.editing")
        page.fill("tr.editing input:not([type=datetime-local]) >> nth=0", "新标题")
        page.click("tr.editing td.row-actions .link.edit")
        page.wait_for_function(
            "() => document.querySelector('#records-notice').textContent.includes('已保存')"
        )

        records = page.request.get(base + "/api/records/notes").json()["records"]
        record = records[0]
        check("the page edit landed", record["title"] == "新标题", record["title"])

        # Another client edits the detail: this is the change an undo of op1
        # used to roll back silently.
        patched = page.request.patch(
            base + "/api/records/notes/" + record["id"], data={"detail": "D1"}
        )
        check("the second client change landed", patched.status == 200, str(patched.status))

        page.click("#records-undo")
        page.wait_for_function(
            "() => document.querySelector('#records-notice').textContent.includes('撤销失败')"
        )
        notice = page.eval_on_selector("#records-notice", "n => n.textContent")
        log("notice shown to the user: " + notice)
        check("the refusal is visible on the page", "撤销失败" in notice, notice)
        check("the notice explains the conflict", "撤销被拒绝" in notice, notice)
        check("the notice names the field that would be lost", "备注" in notice, notice)
        check(
            "the notice points at the later change",
            "请先撤销那次修改" in notice,
            notice,
        )

        stored = page.request.get(base + "/api/records/notes").json()["records"][0]
        check("the later change is still there", stored["detail"] == "D1", str(stored["detail"]))
        check("the title edit was not applied", stored["title"] == "新标题", str(stored["title"]))

        # The order that works: undo the later change first, then the page
        # undo of the title edit is no longer in conflict.
        detail_op = patched.json()["operation_id"]
        with httpx.Client(base_url=base, timeout=30) as client:
            recovered = client.post("/api/records/undo/" + detail_op)
        check(
            "undoing the later change first still works",
            recovered.status_code == 200,
            str(recovered.status_code),
        )
        after_first = page.request.get(base + "/api/records/notes").json()["records"][0]
        check("the detail is back to D0", after_first["detail"] == "D0", str(after_first["detail"]))

        page.click("#records-undo")
        page.wait_for_function(
            "() => document.querySelector('#records-notice').textContent.includes('已撤销上一步')"
        )
        final_title = page.request.get(base + "/api/records/notes").json()["records"][0]["title"]
        check(
            "the title edit is undoable once the later change is undone",
            final_title == "原标题",
            str(final_title),
        )

        shot = Path(os.environ.get("TEMP", ".")) / "md_t1_undo_conflict.png"
        page.screenshot(path=str(shot), full_page=True)
        log("screenshot: " + str(shot))
        browser.close()


def main() -> int:
    if DATA.exists():
        shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)

    model_port = free_port()
    app_port = free_port()
    model_server = ThreadingHTTPServer(("127.0.0.1", model_port), Handler)
    threading.Thread(target=model_server.serve_forever, daemon=True).start()
    (DATA / "config.json").write_text(
        json.dumps(
            {
                "model": {
                    "api_key": "evidence-key",
                    "api_base": "http://127.0.0.1:" + str(model_port) + "/v1",
                    "model": "evidence-model",
                    "thinking": False,
                    "max_turns": None,
                }
            }
        ),
        encoding="utf-8",
    )

    child_env = {k: v for k, v in os.environ.items() if not k.startswith("MELLOWDAY_")}
    child_env["MELLOWDAY_ENV_FILE"] = ""
    server = subprocess.Popen(
        [sys.executable, "-m", "mellowday.web_app", "--data-dir", str(DATA), "--port", str(app_port)],
        cwd=str(ROOT),
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    base = "http://127.0.0.1:" + str(app_port)
    try:
        with httpx.Client(base_url=base, timeout=30) as client:
            up = wait_until(lambda: _healthy(client), timeout=40)
        check("the real server is up", up, base)
        if not up:
            return 1
        phase_a(base)
        phase_b(base)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
        model_server.shutdown()

    log("")
    summary = "FAILURES: " + str(len(failures)) + (
        " -> " + ", ".join(failures) if failures else " (all checks passed)"
    )
    log(summary)
    OUT.write_text("# T1 real-process evidence\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("evidence written to", OUT)
    return 1 if failures else 0


def _healthy(client: httpx.Client) -> bool:
    try:
        return bool(client.get("/api/health").json().get("ok"))
    except Exception:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
