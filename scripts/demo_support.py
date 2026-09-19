"""Helpers for the round-3 demonstration scripts.

The demonstration has to show the product working, not just the runtime: the
rule that a correction produces must be *visible, reviewable and manageable*
through the same HTTP surface the web page uses. So the demo runs a real
uvicorn process against the run's own data directory and talks to it with the
standard library - no test client, no in-process shortcut.

Everything here is deliberately dependency-free (urllib + subprocess) and
never touches the machine's real data directory: the caller passes the run
directory that gate_common pinned.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]


def free_port() -> int:
    """A port the OS just handed out; released immediately for the child."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _child_env(data_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    # The child must inherit the pinned run directory and must not load .env,
    # which would point it back at the machine's real data directory.
    env["MELLOWDAY_DATA_DIR"] = str(data_dir)
    env["MELLOWDAY_ENV_FILE"] = ""
    env["PYTHONIOENCODING"] = "utf-8"
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def http_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """One JSON request; HTTP errors come back as data, never as an exception."""
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            status = int(getattr(response, "status", 200))
        parsed = json.loads(raw) if raw.strip() else {}
        return {"ok": 200 <= status < 300, "status": status, "payload": parsed}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except ValueError:
            parsed = {"raw": raw}
        return {"ok": False, "status": int(exc.code), "payload": parsed}
    except Exception as exc:
        return {"ok": False, "status": 0, "payload": {},
                "error": "%s: %s" % (type(exc).__name__, exc)}


class RealServer:
    """A real web-app process (python -m mellowday.web_app) on a private port."""

    def __init__(self, data_dir: Path, *, log_path: Path | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.port = free_port()
        self.base = "http://127.0.0.1:%d" % self.port
        self.log_path = Path(log_path) if log_path else self.data_dir.parent / "webapp.log"
        self.process: subprocess.Popen | None = None
        self.started_utc = ""
        self.startup: dict[str, Any] = {}

    def start(self, *, timeout: float = 45.0) -> "RealServer":
        self.started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log = self.log_path.open("a", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "mellowday.web_app", "--port", str(self.port),
             "--data-dir", str(self.data_dir)],
            cwd=str(REPO),
            env=_child_env(self.data_dir),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.startup = {"ok": False, "reason": "the server process exited during startup",
                                "exit_code": self.process.returncode}
                return self
            health = self.get("/api/health")
            if health.get("ok"):
                self.startup = {"ok": True, "health": health.get("payload"),
                                "seconds": round(timeout - (deadline - time.monotonic()), 2)}
                return self
            time.sleep(0.4)
        self.startup = {"ok": False, "reason": "health endpoint did not answer within %.0fs" % timeout}
        return self

    # ------------------------------------------------------------- requests

    def get(self, path: str) -> dict[str, Any]:
        return http_json("GET", self.base + path, timeout=30.0)

    def post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return http_json("POST", self.base + path, payload if payload is not None else {})

    def put(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return http_json("PUT", self.base + path, payload)

    def stop(self) -> dict[str, Any]:
        if self.process is None:
            return {"stopped": False, "reason": "never started"}
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=15)
        return {"stopped": True, "exit_code": self.process.returncode}


def run_child(
    script: Path,
    args: Iterable[str],
    data_dir: Path,
    *,
    log_path: Path | None = None,
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Run one of our scripts in a genuinely separate process.

    Used for the restart-continuation step: the session must survive the death
    of the process that created it, so the proof has to come from a new one.
    """
    argv = [sys.executable, str(script), *[str(arg) for arg in args]]
    log_target = Path(log_path) if log_path else Path(data_dir).parent / "child.log"
    log_target.parent.mkdir(parents=True, exist_ok=True)
    with log_target.open("a", encoding="utf-8") as log:
        completed = subprocess.run(
            argv,
            cwd=str(REPO),
            env=_child_env(Path(data_dir)),
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    return {
        "argv": argv,
        "exit_code": completed.returncode,
        "log": str(log_target),
    }


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
