"""Real-process evidence for the restricted tool-result read (t10).

Not a pytest module (its name does not start with "test_"), so the offline
suite ignores it. Run it directly:

    python tests/web_app/manual_t10_tool_results_api.py

It starts no external network: a fake OpenAI-compatible model on 127.0.0.1 that
asks for one "list_notes" call (the notes make the result larger than the 30KB
inline threshold), and the real MellowDay server over an isolated data
directory. Then it checks with real HTTP requests that

  * the model-visible result is the placeholder while the trace entry carries
    the structured ref / chars / preview / truncated of the artifact,
  * GET /api/sessions/{id} serves the complete record and the bounded
    trace_display, and
  * GET /api/sessions/{id}/tool-results/{ref} serves the stored original by
    paging and by query, and answers 400/404 - never 500 - for bad refs,
    unknown refs, foreign sessions and traversal attempts.

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
DATA = Path(os.environ.get("TEMP", ".")) / "md_t10_evidence_data"
OUT = Path(os.environ.get("TEMP", ".")) / "md_t10_evidence.md"
SESSION = "t10evidence"
OTHER = "t10other"
NEEDLE = "第七篇笔记的特殊段落"

os.environ["MELLOWDAY_DATA_DIR"] = str(DATA)
os.environ["MELLOWDAY_ENV_FILE"] = ""
sys.path.insert(0, str(ROOT / "src"))

from mellowday.storage.store import Store  # noqa: E402

state = {"calls": 0, "lock": threading.Lock()}
lines: list[str] = []
failures: list[str] = []


def log(text: str) -> None:
    lines.append(text)
    print(text.encode("ascii", "backslashreplace").decode("ascii"))


def check(name: str, ok: bool, detail: str = "") -> None:
    log(("[PASS] " if ok else "[FAIL] ") + name + (" -- " + detail if detail else ""))
    if not ok:
        failures.append(name)


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class ModelHandler(BaseHTTPRequestHandler):
    """First call: one list_notes tool call. Every later call: plain text."""

    protocol_version = "HTTP/1.0"

    def log_message(self, *args):
        pass

    def _send(self, payload: dict) -> None:
        self.wfile.write(("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def _chunk(self, delta: dict, finish=None, usage=None) -> dict:
        payload = {
            "id": "chunk-1",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "evidence-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        if usage is not None:
            payload["usage"] = usage
        return payload

    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        json.loads(self.rfile.read(length) or b"{}")
        with state["lock"]:
            state["calls"] += 1
            call = state["calls"]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            if call == 1:
                self._send(self._chunk({"tool_calls": [{
                    "index": 0,
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "list_notes", "arguments": json.dumps({"limit": 500})},
                }]}))
                self._send(self._chunk({}, finish="tool_calls", usage={
                    "prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28,
                }))
            else:
                for char in "都读完了，原文已经保存。":
                    self._send(self._chunk({"content": char}))
                self._send(self._chunk({}, finish="stop", usage={
                    "prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52,
                }))
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            pass


def seed_notes() -> str:
    """Notes whose listing is bigger than the runtime inline threshold."""
    store = Store(data_dir=DATA)
    for index in range(30):
        detail = "z" * 1200
        if index == 6:
            detail = NEEDLE + detail
        store.create_record("notes", {"title": "note%d" % index, "detail": detail})
    return "seeded"


def main() -> int:
    if DATA.exists():
        shutil.rmtree(DATA, ignore_errors=True)
    DATA.mkdir(parents=True, exist_ok=True)
    seed_notes()

    model_port = free_port()
    app_port = free_port()
    model = ThreadingHTTPServer(("127.0.0.1", model_port), ModelHandler)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    (DATA / "config.json").write_text(
        json.dumps({
            "model": {
                "api_key": "evidence-key",
                "api_base": "http://127.0.0.1:%d/v1" % model_port,
                "model": "evidence-model",
                "thinking": False,
                "max_turns": None,
            }
        }),
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
    base = "http://127.0.0.1:%d" % app_port
    try:
        client = httpx.Client(base_url=base, timeout=60)
        deadline = time.time() + 40
        health = None
        while time.time() < deadline:
            try:
                health = client.get("/api/health").json()
                break
            except Exception:
                time.sleep(0.3)
        check("the real server is up", bool(health and health.get("ok")), base)
        if not health:
            return 1

        with client.stream("POST", "/api/chat", json={"session_id": SESSION, "message": "把笔记都列出来"}) as response:
            frames = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]
        kinds = [frame.get("type") for frame in frames]
        check("the turn finished", kinds and kinds[-1] == "done", str(kinds[-4:]))
        check("the model asked for the tool", "tool_start" in kinds)

        detail = client.get("/api/sessions/" + SESSION).json()
        raw = [e for e in detail["trace"] if e["type"] == "tool_result"]
        check("the record has the tool result", len(raw) == 1, str(len(raw)))
        entry = raw[0]
        check("the record carries the structured reference",
              bool(entry.get("ref")) and entry.get("truncated") is True and entry.get("chars", 0) > 30 * 1024,
              "ref=%s chars=%s" % (entry.get("ref"), entry.get("chars")))
        check("the model-visible result is the placeholder, not the original",
              str(entry["result"]).startswith("[Result too large"), str(entry["result"])[:60])
        display = [e for e in detail["trace_display"] if e["type"] == "tool_result"][0]
        # The runtime already shortened the model-visible text itself, so this
        # entry needs no further folding; what matters is that the display view
        # is bounded and still carries the reference to the original.
        check("GET /api/sessions/{id} serves a bounded display view that keeps the ref",
              display["ref"] == entry["ref"] and len(display["result"]) <= 4000 + 80,
              "chars=%d display_shortened=%s" % (len(display["result"]), display.get("display_shortened")))
        check("the display view and the record are separate fields",
              "trace" in detail and "trace_display" in detail and detail["trace"] is not detail["trace_display"])

        ref = entry["ref"]
        endpoint = base + "/api/sessions/" + SESSION + "/tool-results/" + ref
        page = client.get(endpoint, params={"limit": 300})
        check("the first page is served over real HTTP", page.status_code == 200, str(page.status_code))
        body = page.json()
        check("the page carries the whole-original length", body.get("total_chars") == entry.get("chars"), str(body.get("total_chars")))
        check("the page is the original text", body.get("text") == str(entry.get("preview"))[:300])
        check("the page says how to continue", body.get("has_more") is True and body.get("next_offset") == 300)

        second = client.get(endpoint, params={"offset": 300, "limit": 300}).json()
        check("paging continues at the right offset", second.get("offset") == 300 and len(second.get("text", "")) == 300)
        check("the placeholder is not what the endpoint serves", body.get("text") != entry.get("result"))

        found = client.get(endpoint, params={"query": NEEDLE, "limit": 400})
        check("a query read locates the passage", found.status_code == 200 and NEEDLE in found.json().get("text", ""), str(found.status_code))
        check("the query reports where the match is", found.json().get("match_offset") is not None)

        missing = client.get(endpoint, params={"query": "no such text"})
        check("a query miss is a 404, not a 500", missing.status_code == 404, str(missing.status_code))
        unknown = client.get(base + "/api/sessions/" + SESSION + "/tool-results/1700000000000-list_notes-deadbeef")
        check("an unknown ref is a 404", unknown.status_code == 404, str(unknown.status_code))
        dotted = client.get(base + "/api/sessions/" + SESSION + "/tool-results/mellowday.sqlite3")
        check("a ref that looks like a path is a 400", dotted.status_code == 400, str(dotted.status_code))

        foreign = client.get(base + "/api/sessions/" + OTHER + "/tool-results/" + ref)
        check("another session cannot follow this ref", foreign.status_code == 404, str(foreign.status_code))
        for raw_ref in ("..%2F..%2Fmellowday.sqlite3", "..%5C..%5Cmellowday.sqlite3"):
            attempted = client.get(base + "/api/sessions/" + SESSION + "/tool-results/" + raw_ref)
            check("traversal attempt %s is refused without a 500" % raw_ref,
                  attempted.status_code != 500 and "SQLite format" not in attempted.text,
                  str(attempted.status_code))

        # A deleted session keeps nothing: the ref answers 404 and no read
        # recreates a directory or a file.
        session_dir = DATA / "tool_results" / SESSION
        check("the artifact directory exists while the session lives", session_dir.is_dir(), str(session_dir))
        deleted = client.delete("/api/sessions/" + SESSION)
        check("the session is deleted over real HTTP", deleted.status_code == 200, str(deleted.status_code))
        check("the deletion removed the artifact directory", not session_dir.exists())
        stale = client.get(endpoint)
        check("a stale ref answers 404 after the deletion", stale.status_code == 404, str(stale.status_code))
        leftovers = list((DATA / "tool_results").glob("**/*.txt")) if (DATA / "tool_results").exists() else []
        check("no read recreated an artifact or a session directory",
              not session_dir.exists() and not leftovers, str(leftovers))
        client.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except Exception:
            server.kill()
        model.shutdown()

    log("")
    summary = "FAILURES: " + str(len(failures)) + (" -> " + ", ".join(failures) if failures else " (all checks passed)")
    log(summary)
    OUT.write_text("# t10 real-process evidence\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    print("evidence written to", OUT)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
