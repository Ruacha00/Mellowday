"""Real-process smoke check for the web session lifecycle (I18/I19/I20).

This file is NOT a pytest module (its name does not start with "test_"), so the
offline suite ignores it. Run it directly when you need process-level evidence
instead of in-process evidence:

    python tests/web_app/smoke_real_process.py

It starts two local processes/threads and uses no external network:

* a fake OpenAI-compatible model on 127.0.0.1 (streams slowly, records every
  request and when its consumer closed the connection);
* the real MellowDay server (uvicorn, "python -m mellowday.web_app") with
  MELLOWDAY_ENV_FILE disabled and an isolated data directory.

It then drives the server over real HTTP and checks:

  A. chat, drop the connection mid-stream, immediately start a second turn on
     the same session: the first turn stops (its model call is aborted), the
     second completes, the display history stays ordered with exactly one reply
     per turn;
  B. an invalid session id answers 400 and creates no file;
  C. DELETE removes the display history and the runtime session file, a later
     GET is 404 and re-deleting is 404 as well;
  D. saving settings makes the NEXT turn use the new model while the session
     history keeps growing.

Exit status: 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import json
import os
import select
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
DATA = Path(tempfile.mkdtemp(prefix="mellowday-smoke-"))
TEXT = "内容" * 8
FULL_REPLY_CHUNKS = len("回复1号：" + TEXT)

state = {"active": 0, "calls": [], "lock": threading.Lock()}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *args):  # keep the output to the JSON report
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
            slot = {
                "n": index,
                "model": body.get("model"),
                "messages": len(messages),
                "last_user": last_user,
                "user_messages": [
                    message.get("content") for message in messages
                    if message.get("role") == "user"
                ],
                "start": time.time(),
                "last_write": None,
                "peer_closed": None,
                "chunks": 0,
                "end": None,
                "overlap_at_start": state["active"] - 1,
            }
            state["calls"].append(slot)

        def watch(conn, slot=slot):
            """Notice the consumer closing the socket without waiting for a write."""
            while slot["peer_closed"] is None:
                try:
                    readable, _, _ = select.select([conn], [], [], 0.005)
                    if readable and conn.recv(1, socket.MSG_PEEK) == b"":
                        with state["lock"]:
                            slot["peer_closed"] = time.time()
                        return
                except OSError:
                    with state["lock"]:
                        slot["peer_closed"] = time.time()
                    return
                time.sleep(0.002)

        threading.Thread(target=watch, args=(self.connection,), daemon=True).start()

        text = f"回复{index}号：" + TEXT
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for char in text:
                chunk = {
                    "id": f"c{index}",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": body.get("model"),
                    "choices": [{"index": 0, "delta": {"content": char}, "finish_reason": None}],
                }
                self.wfile.write(
                    ("data: " + json.dumps(chunk, ensure_ascii=False) + "\n\n").encode("utf-8")
                )
                self.wfile.flush()
                with state["lock"]:
                    slot["chunks"] += 1
                    slot["last_write"] = time.time()
                time.sleep(0.1)
            final = {
                "id": f"c{index}",
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
                slot["end"] = time.time()
                state["active"] -= 1


def free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def snapshot() -> list[dict]:
    with state["lock"]:
        return [dict(item) for item in state["calls"]]


def main() -> int:
    model_port = free_port()
    app_port = free_port()
    model_server = ThreadingHTTPServer(("127.0.0.1", model_port), Handler)
    threading.Thread(target=model_server.serve_forever, daemon=True).start()

    (DATA / "config.json").write_text(
        json.dumps(
            {
                "model": {
                    "api_key": "smoke-key",
                    "api_base": f"http://127.0.0.1:{model_port}/v1",
                    "model": "smoke-model-1",
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

    results: dict = {}
    checks: dict[str, bool] = {}
    try:
        client = httpx.Client(base_url=f"http://127.0.0.1:{app_port}", timeout=30)
        deadline = time.time() + 30
        health = None
        while time.time() < deadline:
            try:
                health = client.get("/api/health").json()
                break
            except Exception:
                time.sleep(0.3)
        results["health"] = health
        checks["server_is_up"] = bool(health and health.get("ok"))
        checks["model_configured"] = bool(health and health.get("model_configured"))

        session_id = "smoke1"
        frames = 0
        started = time.time()
        with client.stream(
            "POST", "/api/chat", json={"session_id": session_id, "message": "第一轮"}
        ) as response:
            for line in response.iter_lines():
                if line.startswith("data: "):
                    frames += 1
                    if frames >= 3:
                        break
        disconnected_at = time.time()
        results["disconnect"] = {
            "frames_before_disconnect": frames,
            "seconds_before_disconnect": round(disconnected_at - started, 2),
        }
        second = client.post("/api/chat", json={"session_id": session_id, "message": "第二轮"})
        results["disconnect"]["second_turn_status"] = second.status_code
        time.sleep(0.5)

        messages = client.get(f"/api/sessions/{session_id}").json()["messages"]
        roles = [item["role"] for item in messages]
        results["history"] = [
            {"role": item["role"], "content": item["content"][:12]} for item in messages
        ]
        checks["history_is_ordered"] = roles == ["user", "assistant", "user", "assistant"]
        checks["one_reply_per_turn"] = len([r for r in roles if r == "assistant"]) == 2
        checks["first_reply_is_the_partial_one"] = bool(
            len(messages) > 1 and str(messages[1]["content"]).startswith("回")
        )
        checks["second_reply_is_complete"] = bool(
            len(messages) > 3 and str(messages[3]["content"]).startswith("回复2号")
        )

        calls = snapshot()
        turn1 = next((c for c in calls if "第一轮" in c["last_user"]), None)
        turn2 = next((c for c in calls if "第二轮" in c["last_user"]), None)
        results["model_calls"] = [
            {
                "n": c["n"],
                "model": c["model"],
                "messages": c["messages"],
                "last_user": c["last_user"],
                "chunks_written": c["chunks"],
                "overlap_at_start": c["overlap_at_start"],
            }
            for c in calls
        ]
        checks["turn1_model_stopped_early"] = bool(turn1 and turn1["chunks"] < FULL_REPLY_CHUNKS)
        checks["turn2_model_completed"] = bool(turn2 and turn2["chunks"] >= FULL_REPLY_CHUNKS)
        checks["second_turn_saw_the_first_message"] = bool(
            turn1 and turn2 and turn2["messages"] > turn1["messages"]
        )

        saved = client.put("/api/config", json={"model": "smoke-model-2"})
        results["config_saved"] = saved.json()
        checks["saved_config_has_no_key"] = (
            "api_key" not in saved.json() and "smoke-key" not in json.dumps(saved.json())
        )
        client.post("/api/chat", json={"session_id": session_id, "message": "第三轮"})
        calls = snapshot()
        results["models_used"] = [c["model"] for c in calls]
        results["messages_per_call"] = [c["messages"] for c in calls]
        results["history_after_config"] = len(
            client.get(f"/api/sessions/{session_id}").json()["messages"]
        )
        # Background evaluations can follow the conversation request with a
        # shorter, independent prompt. Identify the actual third user turn;
        # the last SDK request is not necessarily the conversation.
        turn3 = next((c for c in calls if c["last_user"] == "第三轮"), None)
        results["conversation_after_config"] = turn3
        checks["next_turn_uses_the_saved_model"] = bool(
            turn3 and turn3["model"] == "smoke-model-2"
        )
        checks["history_survives_the_config_change"] = (
            bool(turn3 and turn3["user_messages"] == ["第一轮", "第二轮", "第三轮"])
            and results["history_after_config"] == 6
        )

        bad = client.post("/api/chat", json={"session_id": "../evil", "message": "hi"})
        results["invalid_id"] = {"status": bad.status_code, "body": bad.json()}
        checks["invalid_id_is_400"] = bad.status_code == 400

        sessions_dir = DATA / "sessions"
        before_delete = sorted(p.name for p in sessions_dir.iterdir())
        deleted = client.delete(f"/api/sessions/{session_id}")
        after_delete = sorted(p.name for p in sessions_dir.iterdir())
        results["delete"] = {
            "status": deleted.status_code,
            "files_before": before_delete,
            "files_after": after_delete,
            "get_after_delete": client.get(f"/api/sessions/{session_id}").status_code,
            "delete_again": client.delete(f"/api/sessions/{session_id}").status_code,
            "listed_after": [s["session_id"] for s in client.get("/api/sessions").json()["sessions"]],
        }
        checks["delete_removed_every_file"] = bool(before_delete) and not after_delete
        checks["deleted_session_is_gone"] = results["delete"]["get_after_delete"] == 404
        checks["delete_is_idempotent"] = results["delete"]["delete_again"] == 404
        checks["deleted_session_is_unlisted"] = results["delete"]["listed_after"] == []
        client.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        model_server.shutdown()

    results["checks"] = checks
    print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        print("SMOKE FAILED: " + ", ".join(failed))
        return 1
    print("SMOKE OK: %d checks passed" % len(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
