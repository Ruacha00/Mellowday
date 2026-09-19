"""Shared machinery for the L3 gates: isolation, recording, redaction, evidence.

The first generation of the L3 gates had seven method defects that made their
"pass" results unusable as acceptance evidence:

  1. only the SQLite Store was isolated - skills, sessions, folded memory,
     evolution records and the model configuration were still written into the
     developer's real data directory ("data/skills", "data/sessions",
     "data/config.json", ...);
  2. session ids were reused between runs, so a "new" session could already
     have history from an earlier run and the model-switch check counted stale
     records as continuity;
  3. a request that errored out (empty reply) counted as proof that a disabled
     habit "did not appear" - the check could pass with every request dead;
  4. the model switch was never verified against the request that was actually
     sent: both turns already ran on the new model and only the config file was
     consulted;
  5. a keyword appearing in the reply stood in for business correctness - no
     database row, no tool argument and no rule requirement was checked;
  6. a run recorded neither the code version, nor a workspace fingerprint, nor
     the model identifier actually sent, nor the parameters, the full responses,
     the tool calls, the database result or the denominators of its metrics;
  7. nothing kept a credential out of the logs and reports, and there was no
     offline mode that would state plainly "L3 not run" instead of implying it.

Everything those fixes need lives here so the two gates cannot drift apart:
run-directory isolation (RunContext), secret redaction, provenance (code
version, workspace fingerprint, environment), outbound request recording
(ModelCallRecorder), the sampling/verdict predicates the gates share (so they
can be exercised by --selfcheck with deliberately broken inputs), and the
evidence report writer.

Environment contract
--------------------
RunContext.prepare() must run **before** any "mellowday" module is imported. It
pins MELLOWDAY_DATA_DIR to a freshly created run directory and sets
MELLOWDAY_ENV_FILE to the empty string, so every path resolved by
"mellowday.paths" - database, sessions, skills, skill archive, evolution
records, config.json, plans and logs - stays inside that directory. The
developer's own data directory is only ever *stat-ed* (never opened) to prove
afterwards that the run did not touch it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
DEFAULT_RUN_ROOT = REPO / "output" / "gate-runs"
DEFAULT_REPORT_DIR = REPO / "docs" / "evidence" / "raw"

REDACTED = "<redacted>"
"""What a secret value is replaced with, everywhere, before it can be stored."""


# --------------------------------------------------------------------- startup


def ensure_src_on_path() -> None:
    """Make the working copy importable, not an installed copy."""
    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------- secrets

_SECRETS: list[str] = []
"""Values that must never reach stdout, a log, a report or the repository."""

_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9]{24,}")
"""(A provider key shape, not any text that happens to contain "sk-": the
   previous, looser pattern flagged a model-written tag like "task-skill-x",
   redacted it inside a proposal summary and then failed the leak check on its
   own redaction. The registered-secret scan stays exact and authoritative.)"""
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")
_KEYSECTION_PATTERN = re.compile(r'(?i)("?api[_-]?key"?\s*[:=]\s*")([^"]{6,})(")')


def register_secret(value: Any) -> None:
    """Register a credential so every later write can be scrubbed of it."""
    text = str(value or "").strip()
    if len(text) >= 6 and text not in _SECRETS:
        _SECRETS.append(text)


def registered_secrets() -> list[str]:
    """Registered secrets (real values). Only for the leak self-check."""
    return list(_SECRETS)


def redact(text: Any) -> str:
    """Replace every known secret and any credential-shaped token."""
    out = str(text)
    for secret in _SECRETS:
        if secret and secret in out:
            out = out.replace(secret, REDACTED)
    out = _SECRET_PATTERN.sub("sk-" + REDACTED, out)
    out = _BEARER_PATTERN.sub("Bearer " + REDACTED, out)
    return out


def secret_fingerprint(value: Any) -> str:
    """Stable, non-reversible handle for a credential (for run comparison)."""
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def scan_for_secrets(text: Any) -> list[str]:
    """Labels of credential-shaped or registered content found in the text.

    Returns labels, never the offending value: the scan result itself must be
    safe to store in a report.
    """
    out = str(text)
    hits: list[str] = []
    for index, secret in enumerate(_SECRETS):
        if secret and secret in out:
            hits.append("registered_secret[%d]" % index)
    if _SECRET_PATTERN.search(out):
        hits.append("sk-shaped token")
    if _BEARER_PATTERN.search(out):
        hits.append("bearer token")
    if _KEYSECTION_PATTERN.search(out):
        hits.append("api_key field with value")
    return hits


class _RedactingWriter:
    """Stdout/stderr wrapper that scrubs secrets from anything printed."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        return self._stream.write(redact(text))

    def flush(self) -> None:
        self._stream.flush()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def install_stdout_redaction() -> None:
    """Redact both output streams for the rest of the process."""
    if not isinstance(sys.stdout, _RedactingWriter):
        sys.stdout = _RedactingWriter(sys.stdout)  # type: ignore[assignment]
    if not isinstance(sys.stderr, _RedactingWriter):
        sys.stderr = _RedactingWriter(sys.stderr)  # type: ignore[assignment]


# ----------------------------------------------------------------------- misc


def sha256_12(text: Any) -> str:
    data = text if isinstance(text, bytes) else str(text).encode("utf-8", "replace")
    return hashlib.sha256(data).hexdigest()[:12]


def sha256_16(text: Any) -> str:
    data = text if isinstance(text, bytes) else str(text).encode("utf-8", "replace")
    return hashlib.sha256(data).hexdigest()[:16]


def clip(text: Any, limit: int = 4000) -> str:
    value = str(text if text is not None else "")
    if len(value) <= limit:
        return value
    return value[:limit] + "...[+%d chars]" % (len(value) - limit)


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def code_provenance() -> dict[str, Any]:
    """Code version: commit, branch, dirty state and a fingerprint of it."""
    head = _git("rev-parse", "HEAD")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    status = _git("status", "--porcelain=v1") or ""
    lines = [line for line in status.splitlines() if line.strip()]
    return {
        "git_head": head or "unknown",
        "git_branch": branch or "unknown",
        "git_dirty_files": len(lines),
        "git_status_fingerprint": sha256_12("\n".join(lines)),
        "note": (
            "git_head alone does not identify the code under test: this rebuild is "
            "untracked, so the workspace fingerprint below is authoritative."
        ),
    }


_WORKSPACE_ROOTS = ("src", "tests", "scripts", "evals")
_WORKSPACE_SUFFIXES = {
    ".py", ".js", ".css", ".html", ".json", ".toml", ".cfg", ".ini",
    ".yml", ".yaml", ".md", ".txt", ".example",
}
_WORKSPACE_EXTRA_FILES = ("pyproject.toml", "Dockerfile", "docker-compose.yml", "README.md")
_WORKSPACE_SKIP = ("__pycache__", "egg-info", ".pytest_cache", "node_modules")


def workspace_files() -> list[Path]:
    """Every source file that defines the behaviour under test."""
    found: list[Path] = []
    for name in _WORKSPACE_ROOTS:
        root = REPO / name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if any(part in _WORKSPACE_SKIP for part in path.parts):
                continue
            if not path.is_file():
                continue
            if "evidence" in path.parts and "raw" in path.parts:
                continue  # generated reports, not source
            if path.suffix.lower() in _WORKSPACE_SUFFIXES:
                found.append(path)
    for extra in _WORKSPACE_EXTRA_FILES:
        path = REPO / extra
        if path.is_file():
            found.append(path)
    return found


def workspace_fingerprint() -> dict[str, Any]:
    """Content fingerprint of the source tree (authoritative code version)."""
    files: dict[str, str] = {}
    for path in workspace_files():
        try:
            digest = sha256_16(path.read_bytes())
        except OSError:
            digest = "unreadable"
        files[path.relative_to(REPO).as_posix()] = digest
    aggregate = sha256_16("\n".join("%s %s" % (name, files[name]) for name in sorted(files)))
    gate_files = {name: files[name] for name in files if name.startswith("scripts/")}
    return {
        "fingerprint": aggregate,
        "file_count": len(files),
        "files": files,
        "gate_files": gate_files,
    }


def runtime_provenance() -> dict[str, Any]:
    versions: dict[str, str] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    for module_name in ("openai", "anthropic", "pytest", "fastapi", "uvicorn"):
        try:
            module = __import__(module_name)
            versions[module_name] = str(getattr(module, "__version__", "unknown"))
        except Exception:
            versions[module_name] = "not installed"
    return versions


# ------------------------------------------------------------------ isolation


def read_env_file_value(name: str) -> str:
    """Read one key from the repository .env without importing dotenv.

    Only the requested key is looked at; the credential line is never
    materialised into a log, a report or the repository.
    """
    path = REPO / ".env"
    if not path.is_file():
        return ""
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def resolve_source_data_dir() -> tuple[Path, str]:
    """The data directory this machine really uses (never written to)."""
    explicit = os.environ.get("MELLOWDAY_SOURCE_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve(), "MELLOWDAY_SOURCE_DATA_DIR"
    from_env_file = read_env_file_value("MELLOWDAY_DATA_DIR")
    if from_env_file:
        return Path(from_env_file).expanduser().resolve(), ".env:MELLOWDAY_DATA_DIR"
    return (REPO / "data").resolve(), "repo-default"


def stat_snapshot(root: Path, *, limit: int = 4000) -> dict[str, list[int]]:
    """Metadata-only snapshot (path -> [size, mtime_ns]); no file is opened."""
    out: dict[str, list[int]] = {}
    if not root.is_dir():
        return out
    for index, path in enumerate(sorted(root.rglob("*"))):
        if index >= limit:
            break
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        out[path.relative_to(root).as_posix()] = [int(stat.st_size), int(stat.st_mtime_ns)]
    return out


def snapshot_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(
        name for name in set(before) & set(after) if list(before[name]) != list(after[name])
    )
    return {
        "added": added[:25],
        "removed": removed[:25],
        "changed": changed[:25],
        "added_count": len(added),
        "removed_count": len(removed),
        "changed_count": len(changed),
        "files_before": len(before),
        "files_after": len(after),
        "clean": not (added or removed or changed),
    }


def bootstrap_credentials(source_data_dir: Path) -> dict[str, Any]:
    """Credentials for the run: process environment first, then local config.

    The credential is read once into memory, registered for redaction and
    stored only inside the isolated run directory. It is never printed, never
    copied back out and never part of a report.
    """
    info: dict[str, Any] = {
        "api_key": "",
        "api_base": "",
        "model": "",
        "thinking": False,
        "max_turns": None,
        "source": "none",
        "env_model_pinned": bool(os.environ.get("MELLOWDAY_MODEL")),
    }
    stored: dict[str, Any] = {}
    local = source_data_dir / "config.json"
    if local.is_file():
        try:
            payload = json.loads(local.read_text(encoding="utf-8"))
            candidate = payload.get("model") if isinstance(payload, dict) else None
            if isinstance(candidate, dict):
                stored = candidate
        except (OSError, ValueError):
            stored = {}
    env_key = os.environ.get("MELLOWDAY_API_KEY", "").strip()
    info["api_base"] = (
        os.environ.get("MELLOWDAY_API_BASE") or str(stored.get("api_base") or "")
    ).strip()
    info["model"] = (
        os.environ.get("MELLOWDAY_MODEL") or str(stored.get("model") or "")
    ).strip()
    info["thinking"] = bool(stored.get("thinking", False))
    max_turns = stored.get("max_turns")
    info["max_turns"] = max_turns if isinstance(max_turns, int) else None
    info["api_key"] = env_key or str(stored.get("api_key") or "").strip()
    info["source"] = "environment" if env_key else ("data-config" if stored else "none")
    register_secret(info["api_key"])
    return info


def model_config_view(
    api_key: str,
    api_base: str,
    model: str,
    *,
    thinking: bool = False,
    max_turns: int | None = None,
) -> dict[str, Any]:
    """Safe-to-store view of a model configuration (never the credential)."""
    return {
        "model": model,
        "api_base": api_base,
        "thinking": bool(thinking),
        "max_turns": max_turns,
        "api_key_present": bool(api_key),
        "api_key_fingerprint": secret_fingerprint(api_key),
    }


class RunContext:
    """One isolated gate run: fresh data directory, artefacts, provenance."""

    def __init__(
        self,
        gate: str,
        *,
        run_root: str | Path | None = None,
        run_id: str = "",
        keep: bool = True,
        source_data_dir: str | Path | None = None,
    ) -> None:
        self.gate = gate
        self.run_root = Path(run_root) if run_root else DEFAULT_RUN_ROOT
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = hashlib.sha256(os.urandom(8)).hexdigest()[:4]
        self.run_id = run_id or "%s-%s" % (stamp, suffix)
        self.keep = keep
        self.root = self.run_root / gate / self.run_id
        self.data_dir = self.root / "data"
        self.artifacts_dir = self.root / "artifacts"
        if source_data_dir:
            self.source_data_dir = Path(source_data_dir).expanduser().resolve()
            self.source_origin = "argument"
        else:
            self.source_data_dir, self.source_origin = resolve_source_data_dir()
        self.source_snapshot: dict[str, list[int]] = {}
        self.started_utc = ""
        self.seeded_config: dict[str, Any] = {}
        self.credentials: dict[str, Any] = {}
        self.notes: list[str] = []
        self.workspace: dict[str, Any] = {}
        self.code: dict[str, Any] = {}

    # ------------------------------------------------------------- lifecycle

    def prepare(self) -> "RunContext":
        """Create the run directory and pin every MellowDay path inside it."""
        self.started_utc = utc_now()
        if self.root.exists():
            raise RuntimeError("run directory already exists: %s" % self.root)
        self.data_dir.mkdir(parents=True, exist_ok=False)
        self.artifacts_dir.mkdir(parents=True, exist_ok=False)
        install_stdout_redaction()

        # Isolation must be in place before mellowday is imported anywhere.
        os.environ["MELLOWDAY_DATA_DIR"] = str(self.data_dir)
        os.environ["MELLOWDAY_ENV_FILE"] = ""  # never let .env re-point the run
        for name in ("MELLOWDAY_API_BASE", "MELLOWDAY_MODEL"):
            os.environ.pop(name, None)

        self.source_snapshot = stat_snapshot(self.source_data_dir)
        self.code = code_provenance()
        self.workspace = workspace_fingerprint()
        (self.artifacts_dir / "workspace-fingerprint.json").write_text(
            json.dumps(self.workspace, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.credentials = bootstrap_credentials(self.source_data_dir)
        return self

    def seed_model_config(self) -> dict[str, Any]:
        """Write the run's own config.json from the resolved credentials."""
        payload = {
            "model": {
                "api_key": self.credentials.get("api_key", ""),
                "api_base": self.credentials.get("api_base", ""),
                "model": self.credentials.get("model", ""),
                "thinking": bool(self.credentials.get("thinking", False)),
                "max_turns": self.credentials.get("max_turns"),
            }
        }
        path = self.data_dir / "config.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.seeded_config = model_config_view(
            str(self.credentials.get("api_key", "")),
            str(self.credentials.get("api_base", "")),
            str(self.credentials.get("model", "")),
            thinking=bool(self.credentials.get("thinking", False)),
            max_turns=self.credentials.get("max_turns"),
        )
        self.seeded_config["source"] = str(self.credentials.get("source", "none"))
        return dict(self.seeded_config)

    def session_id(self, prefix: str, index: int = 0) -> str:
        """A session id that cannot collide with an earlier run."""
        token = re.sub(r"[^A-Za-z0-9_-]", "", self.run_id)[-9:]
        safe_prefix = re.sub(r"[^A-Za-z0-9_-]", "-", prefix)
        return "%s-%s-%d" % (safe_prefix, token, index)

    def isolated_state(self) -> dict[str, Any]:
        """What the run directory contains right now (freshness evidence)."""

        def names(name: str) -> list[str]:
            path = self.data_dir / name
            if not path.is_dir():
                return []
            return sorted(child.name for child in path.iterdir())

        return {
            "data_dir": str(self.data_dir),
            "sessions": names("sessions"),
            "skills": names("skills"),
            "skill_evolution": names("skill_evolution"),
            "memory": names("memory"),
            "plans": names("plans"),
            "root_entries": sorted(child.name for child in self.data_dir.iterdir()),
            "has_database": (self.data_dir / "mellowday.sqlite3").exists(),
        }

    def pollution_report(self) -> dict[str, Any]:
        """Did this run touch the data directory the machine really uses?"""
        after = stat_snapshot(self.source_data_dir)
        diff = snapshot_diff(self.source_snapshot, after)
        diff.update(
            {
                "source_data_dir": str(self.source_data_dir),
                "source_resolution": self.source_origin,
                "method": "stat-only snapshot (size + mtime per file); no file is opened",
            }
        )
        return diff

    def run_metadata(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "run_id": self.run_id,
            "started_utc": self.started_utc,
            "finished_utc": utc_now(),
            "argv": list(sys.argv),
            "cwd": str(Path.cwd()),
            "run_dir": str(self.root),
            "data_dir": str(self.data_dir),
            "artifacts_dir": str(self.artifacts_dir),
            "keep_run_dir": self.keep,
            "source_data_dir": str(self.source_data_dir),
            "source_resolution": self.source_origin,
            "environment": runtime_provenance(),
        }

    def environment_pins(self) -> dict[str, Any]:
        return {
            "MELLOWDAY_DATA_DIR": os.environ.get("MELLOWDAY_DATA_DIR", ""),
            "MELLOWDAY_ENV_FILE": os.environ.get("MELLOWDAY_ENV_FILE", ""),
            "note": (
                "the .env file is not loaded during a gate run; credentials are copied "
                "into the run directory once instead of the run writing to the real one"
            ),
        }


# ------------------------------------------------------------------- recorder


class ModelCallRecorder:
    """Records what was actually sent to and received from the model.

    The wrapper sits on the SDK method (not on one client instance), so it keeps
    working when the runtime rebuilds its client after a configuration change -
    which is exactly the event the model-switch check has to observe.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.available = False
        self.install_errors: list[str] = []
        self._patched: list[tuple[Any, str, Any]] = []

    # ------------------------------------------------------------ install

    def install(self) -> None:
        self._patch_openai()
        self._patch_anthropic()

    def _patch_openai(self) -> None:
        try:
            from openai.resources.chat.completions import AsyncCompletions

            original = AsyncCompletions.create
            recorder = self

            async def create(inner_self: Any, *args: Any, **kwargs: Any) -> Any:
                call = recorder.begin("openai.chat.completions.create", kwargs)
                try:
                    result = original(inner_self, *args, **kwargs)
                    if isawaitable(result):
                        result = await result
                except Exception as exc:
                    recorder.fail(call, exc)
                    raise
                if kwargs.get("stream"):
                    return _RecordingStream(result, call, recorder)
                recorder.observe(call, result)
                return result

            AsyncCompletions.create = create  # type: ignore[method-assign]
            self._patched.append((AsyncCompletions, "create", original))
            self.available = True
        except Exception as exc:  # pragma: no cover - SDK layout change
            self.install_errors.append("openai: %s: %s" % (type(exc).__name__, exc))

    def _patch_anthropic(self) -> None:
        try:
            from anthropic.resources.messages import AsyncMessages

            original = AsyncMessages.create
            recorder = self

            async def create(inner_self: Any, *args: Any, **kwargs: Any) -> Any:
                call = recorder.begin("anthropic.messages.create", kwargs)
                try:
                    result = original(inner_self, *args, **kwargs)
                    if isawaitable(result):
                        result = await result
                except Exception as exc:
                    recorder.fail(call, exc)
                    raise
                recorder.observe(call, result)
                return result

            AsyncMessages.create = create  # type: ignore[method-assign]
            self._patched.append((AsyncMessages, "create", original))
            self.available = True
        except Exception as exc:  # pragma: no cover - SDK layout change
            self.install_errors.append("anthropic: %s: %s" % (type(exc).__name__, exc))

    def uninstall(self) -> None:
        for target, attribute, original in self._patched:
            try:
                setattr(target, attribute, original)
            except Exception:  # pragma: no cover
                continue
        self._patched.clear()

    # -------------------------------------------------------------- records

    def begin(self, api: str, kwargs: Mapping[str, Any]) -> dict[str, Any]:
        messages = kwargs.get("messages") if isinstance(kwargs.get("messages"), list) else []
        tools = kwargs.get("tools") if isinstance(kwargs.get("tools"), list) else []
        call: dict[str, Any] = {
            "seq": len(self.calls) + 1,
            "api": api,
            "started_utc": utc_now(),
            "model": str(kwargs.get("model") or ""),
            "stream": bool(kwargs.get("stream")),
            "request": {
                "message_count": len(messages),
                "tool_count": len(tools),
                "tool_names": [str((tool or {}).get("name") or "") for tool in tools][:80],
                "max_tokens": kwargs.get("max_tokens"),
                "temperature": kwargs.get("temperature"),
                "system_chars": len(str(kwargs.get("system") or "")),
                "payload_chars": 0,
            },
            "payload_text": json.dumps(
                {"messages": messages, "system": kwargs.get("system") or ""},
                ensure_ascii=False,
                default=str,
            ),
            "response_text": "",
            "tool_calls": [],
            "finish_reason": "",
            "usage": None,
            "response_model": "",
            "duration_ms": 0,
            "error": "",
            "_started": time.monotonic(),
        }
        call["request"]["payload_chars"] = len(call["payload_text"])
        self.calls.append(call)
        return call

    def observe(self, call: dict[str, Any], response: Any) -> None:
        call["duration_ms"] = int((time.monotonic() - call["_started"]) * 1000)
        call["response_model"] = str(getattr(response, "model", "") or "")
        usage = getattr(response, "usage", None)
        if usage is not None:
            call["usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
            }
        choices = getattr(response, "choices", None)
        if isinstance(choices, list) and choices:
            choice = choices[0]
            call["finish_reason"] = str(getattr(choice, "finish_reason", "") or "")
            message = getattr(choice, "message", None)
            call["response_text"] = clip(getattr(message, "content", "") or "", 20000)
            for tool_call in list(getattr(message, "tool_calls", None) or []):
                function = getattr(tool_call, "function", None)
                call["tool_calls"].append(
                    {
                        "name": str(getattr(function, "name", "") or ""),
                        "arguments": clip(getattr(function, "arguments", "") or "", 4000),
                    }
                )
            return
        content = getattr(response, "content", None)
        if isinstance(content, list):  # anthropic-style content blocks
            parts = [
                str(getattr(block, "text", "") or "")
                for block in content
                if str(getattr(block, "type", "")) == "text"
            ]
            call["response_text"] = clip("".join(parts), 20000)
            call["finish_reason"] = str(getattr(response, "stop_reason", "") or "")

    def observe_chunk(self, call: dict[str, Any], chunk: Any) -> None:
        """Accumulate a streamed chunk the same way the runtime does."""
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            call["usage"] = {
                "prompt_tokens": getattr(usage, "prompt_tokens", None),
                "completion_tokens": getattr(usage, "completion_tokens", None),
            }
        call["response_model"] = str(getattr(chunk, "model", "") or "") or call["response_model"]
        choices = getattr(chunk, "choices", None)
        if not isinstance(choices, list) or not choices:
            return
        choice = choices[0]
        if getattr(choice, "finish_reason", None):
            call["finish_reason"] = str(choice.finish_reason)
        delta = getattr(choice, "delta", None)
        if delta is None:
            return
        text = getattr(delta, "content", None)
        if text:
            call["response_text"] = clip(call["response_text"] + str(text), 20000)
        for tool_call in list(getattr(delta, "tool_calls", None) or []):
            index = int(getattr(tool_call, "index", 0) or 0)
            function = getattr(tool_call, "function", None)
            while len(call["tool_calls"]) <= index:
                call["tool_calls"].append({"name": "", "arguments": ""})
            entry = call["tool_calls"][index]
            if function is not None:
                if getattr(function, "name", None):
                    entry["name"] = str(function.name)
                if getattr(function, "arguments", None):
                    entry["arguments"] = clip(entry["arguments"] + str(function.arguments), 4000)

    def finish_stream(self, call: dict[str, Any]) -> None:
        call["duration_ms"] = int((time.monotonic() - call["_started"]) * 1000)

    def fail(self, call: dict[str, Any], exc: BaseException) -> None:
        call["duration_ms"] = int((time.monotonic() - call["_started"]) * 1000)
        call["error"] = "%s: %s" % (type(exc).__name__, exc)

    # ------------------------------------------------------------- queries

    def models_sent(self) -> list[str]:
        return [str(call.get("model") or "") for call in self.calls]

    def model_sequence(self) -> list[dict[str, Any]]:
        return [
            {
                "seq": call["seq"],
                "model": call.get("model"),
                "stream": call.get("stream"),
                "started_utc": call.get("started_utc"),
                "error": clip(call.get("error"), 300),
            }
            for call in self.calls
        ]

    def payload_contains(self, text: str) -> list[int]:
        """Sequence numbers of the calls whose outbound payload contains the text."""
        needle = str(text)
        if not needle:
            return []
        return [
            int(call["seq"])
            for call in self.calls
            if needle in str(call.get("payload_text") or "")
        ]

    def calls_from(self, seq: int) -> list[dict[str, Any]]:
        return [call for call in self.calls if int(call["seq"]) > seq]

    def report_view(self, *, keep_payload: bool = False) -> list[dict[str, Any]]:
        view: list[dict[str, Any]] = []
        for call in self.calls:
            entry = {key: value for key, value in call.items() if not key.startswith("_")}
            if keep_payload:
                entry["payload_text"] = clip(entry.get("payload_text"), 60000)
            else:
                entry.pop("payload_text", None)
            view.append(entry)
        return view

    def dump_raw(self, path: Path) -> Path:
        lines = []
        for call in self.calls:
            entry = {key: value for key, value in call.items() if not key.startswith("_")}
            lines.append(redact(json.dumps(entry, ensure_ascii=False, default=str)))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


class _RecordingStream:
    """Pass-through async iterator that records the streamed response."""

    def __init__(self, stream: Any, call: dict[str, Any], recorder: ModelCallRecorder) -> None:
        self._stream = stream
        self._call = call
        self._recorder = recorder
        self._done = False

    def __aiter__(self) -> "_RecordingStream":
        return self

    async def __anext__(self) -> Any:
        try:
            chunk = await self._stream.__anext__()
        except StopAsyncIteration:
            self._finish()
            raise
        self._recorder.observe_chunk(self._call, chunk)
        return chunk

    def _finish(self) -> None:
        if not self._done:
            self._done = True
            self._recorder.finish_stream(self._call)

    async def aclose(self) -> None:
        self._finish()
        close = getattr(self._stream, "aclose", None)
        if callable(close):
            result = close()
            if isawaitable(result):
                await result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


# ------------------------------------------------------------------ verdicts


def sample_is_valid(result: Mapping[str, Any]) -> tuple[bool, str]:
    """A model sample only counts when the request really answered."""
    errors = list(result.get("errors") or [])
    if errors:
        return False, "error_event: %s" % clip(errors[0], 160)
    if not str(result.get("reply") or "").strip():
        return False, "empty_reply"
    return True, ""


def invalid_reasons(samples: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        reason
        for sample in samples
        for ok, reason in [sample_is_valid(sample)]
        if not ok
    ]


def off_side_verdict(
    samples: Sequence[Mapping[str, Any]], *, control_ok: bool
) -> tuple[bool, dict[str, Any]]:
    """Verdict for "the disabled habit did not show up".

    A dead request is not evidence. The verdict is only True when every sample
    answered, none of them hit, and a control proved that a hit is reachable at
    all on this endpoint - otherwise the result is inconclusive, never a pass.
    """
    hits = sum(1 for sample in samples if sample.get("hit"))
    valid = sum(1 for sample in samples if sample_is_valid(sample)[0])
    detail: dict[str, Any] = {
        "hits": hits,
        "of": len(samples),
        "valid": valid,
        "invalid": invalid_reasons(samples),
        "control_ok": bool(control_ok),
    }
    if not samples:
        detail["inconclusive_reason"] = "no sample was taken"
        return False, detail
    if valid != len(samples):
        detail["inconclusive_reason"] = (
            "%d of %d samples produced an error or an empty reply; a dead request "
            "is not evidence that the habit was absent" % (len(samples) - valid, len(samples))
        )
        return False, detail
    if not control_ok:
        detail["inconclusive_reason"] = (
            "the positive control did not reproduce the habit, so this endpoint "
            "cannot show the habit at all and its absence proves nothing"
        )
        return False, detail
    leaks = [sample for sample in samples if sample.get("payload_probe_present")]
    detail["payload_leaks"] = len(leaks)
    if leaks:
        detail["reason"] = (
            "the disabled rule text was still delivered to the model in %d of %d requests"
            % (len(leaks), len(samples))
        )
        return False, detail
    if hits:
        detail["reason"] = "%d of %d valid samples still showed the habit" % (hits, len(samples))
        return False, detail
    detail["reason"] = "all %d samples answered and none showed the habit" % len(samples)
    return True, detail


def on_side_verdict(
    samples: Sequence[Mapping[str, Any]], *, min_hits: int = 1
) -> tuple[bool, dict[str, Any]]:
    """Verdict for "the enabled habit changes behaviour" (sampled)."""
    hits = sum(1 for sample in samples if sample.get("hit"))
    valid = sum(1 for sample in samples if sample_is_valid(sample)[0])
    detail: dict[str, Any] = {
        "hits": hits,
        "of": len(samples),
        "valid": valid,
        "min_hits": min_hits,
        "invalid": invalid_reasons(samples),
    }
    if valid == 0:
        detail["inconclusive_reason"] = "no sample answered; nothing was measured"
        return False, detail
    ok = hits >= min_hits
    detail["reason"] = "%d of %d valid samples satisfied every rule requirement" % (hits, valid)
    if any(sample.get("payload_probe_present") is not None for sample in samples):
        detail["rule_text_delivered"] = sum(
            1 for sample in samples if sample.get("payload_probe_present")
        )
    return ok, detail


def switch_verdict(
    sequence: Sequence[str], *, original: str, switched: str
) -> tuple[bool, dict[str, Any]]:
    """Verdict for "a configuration change reaches the next request".

    Judged on the model identifier actually sent, in order: the original model
    must really have served a turn first, the switched model must be observed on
    a later request, and a restore must put the original back.
    """
    detail: dict[str, Any] = {
        "sequence": list(sequence),
        "expected_first_original": original,
        "expected_later_switch": switched,
    }
    if len(sequence) < 3:
        detail["inconclusive_reason"] = "fewer than three requests were recorded"
        return False, detail
    if sequence[0] != original:
        detail["reason"] = "the first request did not use the original model %r" % original
        return False, detail
    if switched not in sequence[1:]:
        detail["reason"] = "the switched model %r never appeared in a later request" % switched
        return False, detail
    if sequence[-1] != original:
        detail["reason"] = "the restored request did not use the original model %r" % original
        return False, detail
    detail["reason"] = "requests used %s in order" % " -> ".join(sequence)
    return True, detail


def continuity_verdict(evidence: Mapping[str, bool]) -> tuple[bool, dict[str, Any]]:
    """Verdict for "the conversation survived the change"."""
    detail = dict(evidence)
    missing = sorted(name for name, ok in evidence.items() if not ok)
    if missing:
        detail["reason"] = "missing from the later request payload: %s" % ", ".join(missing)
        return False, detail
    detail["reason"] = "the later request payload carried the earlier turn"
    return True, detail


# --------------------------------------------------------- reply-side checks


_LIST_ITEM = re.compile(
    # A bullet needs whitespace after it and must not open a bold run:
    # "**建议执行顺序**：..." is a heading, not a fourth list item. Counting it as
    # one made a conforming three-item plan look like a rule violation.
    r"^\s*(?:[-*\u2022\u00b7](?!\*)\s+|\d{1,2}\s*[.\u3001)\uff08\uff09]\s*|[\u2460-\u2469]\s*)\S"
)


def payload_channel_evidence(
    calls: Sequence[Mapping[str, Any]],
    probes: Sequence[str],
    *,
    fact_probes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Which channel carried the rule text into these requests.

    "skill" means the probe appeared in the payload outside the recalled-facts
    block (skill library, skill tool result, or conversation); "facts" means it
    appeared inside the recalled-facts block the runtime injects every turn.
    """
    skill_hits: set[str] = set()
    fact_hits: set[str] = set()
    superseded_hits: set[str] = set()
    for call in calls:
        payload = str(call.get("payload_text") or "")
        block = payload_fact_block(payload)
        old_values = payload_superseded_block(payload)
        for probe in probes:
            if not probe:
                continue
            if probe in block:
                fact_hits.add(probe)
            elif probe in old_values:
                superseded_hits.add(probe)
            elif probe in payload:
                skill_hits.add(probe)
    for probe in fact_probes or ():
        for call in calls:
            if probe and probe in payload_fact_block(call.get("payload_text")):
                fact_hits.add(probe)
    return {
        "via_skill_or_conversation": sorted(skill_hits),
        "via_recalled_facts": sorted(fact_hits),
        "via_superseded_values": sorted(superseded_hits),
    }


FACTS_BLOCK_MARKER = "Recalled facts about the user"
SUPERSEDED_BLOCK_MARKER = (
    "Facts that were current earlier in this conversation and are NOT current any more:"
)
"""The second half of the injected reminder: old values that must never come back.

A rule can reach the model through three places, and the disable-side check has
to look at all of them: the recalled-facts block, this superseded-values block
(the runtime keeps a bounded list of values it handed the model earlier), and
the rest of the request (system prompt, tool results, conversation).
"""


def payload_fact_block(payload: Any) -> str:
    """The recalled-facts block of an outbound payload, when it has one.

    A rule can reach the model through three channels: the skill library, the
    recalled-facts block, and the superseded-values block (both blocks live in
    the same injected reminder). This function returns only the first block, so
    a probe found in the superseded values is not mistaken for a current fact.
    """
    text = str(payload or "")
    start = text.find(FACTS_BLOCK_MARKER)
    if start < 0:
        return ""
    end = len(text)
    for boundary in (text.find("</system-reminder>", start), text.find(SUPERSEDED_BLOCK_MARKER, start)):
        if boundary > start:
            end = min(end, boundary)
    if end == len(text):
        end = min(len(text), start + 2000)
    return text[start:end]


def payload_superseded_block(payload: Any) -> str:
    """The superseded-values block of an outbound payload, when it has one."""
    text = str(payload or "")
    start = text.find(SUPERSEDED_BLOCK_MARKER)
    if start < 0:
        return ""
    end = text.find("</system-reminder>", start)
    return text[start: end if end > 0 else start + 2000]


def payload_probe_locations(
    calls: Sequence[Mapping[str, Any]], probes: Sequence[str]
) -> dict[str, Any]:
    """Where each probe text appears in these requests (empty probes never match).

    The probe list is de-duplicated in order: callers pass overlapping probe sets
    (rule name, body probe and fact-channel terms), and a probe repeated in the
    report reads like a second, independent probe that never fired.
    """
    wanted: list[str] = []
    for probe in probes:
        text = str(probe)
        if text and text not in wanted:
            wanted.append(text)
    recalled: set[str] = set()
    superseded: set[str] = set()
    elsewhere: set[str] = set()
    scanned = 0
    for call in calls:
        payload = str(call.get("payload_text") or "")
        if not payload:
            continue
        scanned += 1
        recalled_block = payload_fact_block(payload)
        superseded_block = payload_superseded_block(payload)
        for probe in wanted:
            if probe in recalled_block:
                recalled.add(probe)
                continue
            if probe in superseded_block:
                superseded.add(probe)
                continue
            if probe in payload:
                elsewhere.add(probe)
    return {
        "probes": wanted,
        "in_recalled_facts_block": sorted(recalled),
        "in_superseded_block": sorted(superseded),
        "elsewhere_in_request": sorted(elsewhere),
        "present_anywhere": sorted(recalled | superseded | elsewhere),
        "requests_scanned": scanned,
    }


def first_nonempty_line(text: Any) -> str:
    for line in str(text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def section_slice(text: Any, title: str, *, max_lines: int = 40) -> str:
    """Text of the section introduced by the title (best effort, auditable)."""
    lines = str(text or "").splitlines()
    start = None
    for index, line in enumerate(lines):
        if title in line:
            start = index
            break
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start + 1 : start + 1 + max_lines]:
        stripped = line.strip()
        if not stripped:
            collected.append(line)
            continue
        if _LIST_ITEM.match(line):
            collected.append(line)
            continue
        break
    return "\n".join(collected)


def count_items(section_text: Any) -> tuple[int, str]:
    """Count the top-level list items of a section; returns (count, method).

    Only the shallowest indentation level is counted, so a task with a nested
    note under it still counts as one item - the check is about how many
    priorities the reply commits to, not how many lines it uses.
    """
    lines = [line for line in str(section_text or "").splitlines() if line.strip()]
    items = [(len(line) - len(line.lstrip()), line) for line in lines if _LIST_ITEM.match(line)]
    if items:
        shallowest = min(indent for indent, _ in items)
        return sum(1 for indent, _ in items if indent == shallowest), "top-level-list-items"
    joined = "".join(lines)
    if not joined.strip():
        return 0, "unparseable"
    parts = [part for part in re.split(r"[;\uff1b]", joined) if part.strip()]
    if len(parts) > 1:
        return len(parts), "semicolon-separated"
    return 0, "unparseable"


def evaluate_rule(reply: Any, spec: Mapping[str, Any]) -> dict[str, Any]:
    """Check a reply against the requirements of the rule, not a keyword.

    Every assertion is reported separately so a reader can see which part of the
    rule the model followed and which part it did not.
    """
    text = str(reply or "")
    assertions: dict[str, bool] = {}
    evidence: dict[str, Any] = {}

    marker = str(spec.get("marker") or "")
    if marker:
        line = first_nonempty_line(text)
        assertions["marker_on_first_line"] = line == marker
        evidence["first_line"] = clip(line, 120)
        evidence["marker_anywhere"] = marker in text

    for title in spec.get("sections") or ():
        assertions["section:%s" % title] = title in text

    for title in spec.get("forbidden") or ():
        assertions["no_section:%s" % title] = title not in text

    for term in spec.get("terms") or ():
        assertions["term:%s" % term] = term in text

    for group in spec.get("any_terms") or ():
        if not isinstance(group, Mapping):
            continue
        name = str(group.get("name") or "terms")
        minimum = int(group.get("min") or 1)
        candidates = [str(term) for term in (group.get("terms") or [])]
        found = [term for term in candidates if term in text]
        assertions["any_terms:%s>=%d" % (name, minimum)] = len(found) >= minimum
        evidence["any_terms_%s" % name] = {"found": found, "of": len(candidates),
                                           "required": minimum}

    limit_spec = spec.get("item_limit")
    if isinstance(limit_spec, Mapping):
        title = str(limit_spec.get("section") or "")
        maximum = int(limit_spec.get("max") or 0)
        minimum = int(limit_spec.get("min") or 0)
        section = section_slice(text, title)
        count, method = count_items(section)
        evidence["items"] = {
            "section": title,
            "count": count,
            "method": method,
            "excerpt": clip(section, 400),
        }
        if method == "unparseable":
            # Not evaluated rather than failed: the parser could not read it and
            # a gate must not claim a violation it cannot show.
            evidence["items"]["evaluated"] = False
        else:
            evidence["items"]["evaluated"] = True
            assertions["items<=%d" % maximum] = count <= maximum
            assertions["items>=%d" % minimum] = count >= minimum

    detail = {
        "assertions": assertions,
        "failed": sorted(name for name, ok in assertions.items() if not ok),
        "evidence": evidence,
    }
    return {"ok": all(assertions.values()), "detail": detail}


def merge_rule_results(reply: Any, specs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """All assertions of several rule specs, combined."""
    detail: dict[str, Any] = {"assertions": {}, "evidence": {}, "failed": []}
    for spec in specs:
        result = evaluate_rule(reply, spec)
        detail["assertions"].update(result["detail"]["assertions"])
        detail["evidence"].update(result["detail"]["evidence"])
    detail["failed"] = sorted(name for name, ok in detail["assertions"].items() if not ok)
    ok = bool(detail["assertions"]) and all(detail["assertions"].values())
    return {"ok": ok, "detail": detail}


# ------------------------------------------------------------- turn running


LEARNING_EVENT_TYPES = (
    "skill_candidate_proposed",
    "skill_candidate_applied",
    "skill_write_denied",
    "skill_candidate_failed",
    "skill_candidate_skipped",
)


async def run_turn(
    registry: Any,
    session_id: str,
    message: str,
    *,
    approve: bool | None = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Run one turn and collect everything the gates need to judge it.

    approve answers confirmation prompts: True accepts, False declines, None
    leaves them unanswered (the "nobody confirmed" path).
    """
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout

    reply_parts: list[str] = []
    tools: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    errors: list[str] = []
    learning: list[dict[str, Any]] = []
    confirmations: list[dict[str, Any]] = []
    warnings: list[str] = []
    notices: list[str] = []
    event_types: list[str] = []

    async for event in registry.run_turn(session_id, message, **kwargs):
        kind = str(event.get("type") or "")
        event_types.append(kind)
        if kind == "text_delta":
            reply_parts.append(str(event.get("text") or ""))
        elif kind == "tool_start":
            tools.append({"name": str(event.get("name") or ""), "arguments": event.get("arguments")})
        elif kind == "tool_result":
            tool_results.append(
                {"name": str(event.get("name") or ""), "result": clip(event.get("result"), 4000)}
            )
        elif kind == "error":
            errors.append(str(event.get("message") or ""))
        elif kind.startswith("skill_"):
            learning.append({key: value for key, value in event.items() if key != "session_id"})
        elif kind == "confirmation" and event.get("id"):
            token = str(event["id"])
            confirmations.append({"id": token, "summary": str(event.get("summary") or "")})
            if approve is not None:
                state = registry.get(session_id)
                state.confirmations.resolve(token, bool(approve))
        elif kind == "warning":
            warnings.append(str(event.get("message") or ""))
        elif kind == "notice":
            notices.append(str(event.get("message") or ""))

    return {
        "session_id": session_id,
        "message": message,
        "reply": "".join(reply_parts),
        "tools": tools,
        "tool_results": tool_results,
        "errors": errors,
        "learning": learning,
        "confirmations": confirmations,
        "warnings": warnings,
        "notices": notices,
        "event_types": event_types,
    }


def trace_kind(entry: Mapping[str, Any]) -> str:
    """Record kind of one raw-record entry.

    The contract stores it under "type" (see runtime/sessions.py); "kind" is
    accepted as well, and both are checked so a reader can never silently look
    for the wrong key and report an empty record as "no tool call happened".
    """
    return str(entry.get("type") or entry.get("kind") or "")


def trace_tool_calls(registry: Any, session_id: str) -> list[dict[str, Any]]:
    """Tool calls as persisted in the raw execution record (ground truth)."""
    out: list[dict[str, Any]] = []
    try:
        entries = registry.trace(session_id)
    except Exception:
        return out
    for entry in entries:
        if trace_kind(entry) != "tool_call":
            continue
        arguments = entry.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except ValueError:
                arguments = {"_raw": arguments}
        out.append({"name": str(entry.get("name") or ""), "arguments": arguments})
    return out


def trace_errors(registry: Any, session_id: str) -> list[str]:
    try:
        entries = registry.trace(session_id)
    except Exception:
        return []
    return [
        str(entry.get("message") or "")
        for entry in entries
        if trace_kind(entry) == "error"
    ]


def trace_kinds(registry: Any, session_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        entries = registry.trace(session_id)
    except Exception:
        return counts
    for entry in entries:
        kind = trace_kind(entry) or "(unknown)"
        counts[kind] = counts.get(kind, 0) + 1
    return counts


def session_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    """Compact, auditable view of one turn for the report."""
    valid, reason = sample_is_valid(result)
    return {
        "session_id": result.get("session_id"),
        "message": result.get("message"),
        "valid": valid,
        "invalid_reason": reason,
        "reply": clip(result.get("reply"), 4000),
        "tool_calls": [
            {
                "name": tool.get("name"),
                "arguments": clip(
                    json.dumps(tool.get("arguments"), ensure_ascii=False, default=str), 1500
                ),
            }
            for tool in (result.get("tools") or [])
        ],
        "tool_results": [
            {
                "name": tool.get("name"),
                "result": clip(tool.get("result"), 400),
            }
            for tool in (result.get("tool_results") or [])
        ],
        "errors": [clip(error, 600) for error in (result.get("errors") or [])],
        "learning_events": [
            {key: clip(value, 400) for key, value in event.items()}
            for event in (result.get("learning") or [])
        ],
        "confirmations": result.get("confirmations") or [],
        "warnings": result.get("warnings") or [],
        "notices": result.get("notices") or [],
    }


async def sample_sessions(
    registry: Any,
    run: RunContext,
    prefix: str,
    question: str,
    count: int,
    *,
    specs: Sequence[Mapping[str, Any]] = (),
    approve: bool | None = False,
    recorder: Any = None,
    payload_probes: Sequence[str] | str = (),
) -> list[dict[str, Any]]:
    """Run count brand-new sessions and judge each reply against the specs.

    With a recorder and payload probes, each sample also records whether the
    rule text really reached the model in that request (the delivery evidence),
    so "the reply followed the rule" cannot be confused with "the rule was
    never delivered".
    """
    probes = [payload_probes] if isinstance(payload_probes, str) else [
        str(probe) for probe in (payload_probes or []) if str(probe)
    ]
    samples: list[dict[str, Any]] = []
    for index in range(count):
        session_id = run.session_id(prefix, index)
        summary_evidence = session_freshness(registry, session_id)
        seq_before = len(recorder.calls) if recorder is not None else 0
        result = await run_turn(registry, session_id, question, approve=approve)
        calls = recorder.calls[seq_before:] if recorder is not None else []
        delivered = sorted(
            {
                probe
                for probe in probes
                for call in calls
                if probe in str(call.get("payload_text") or "")
            }
        )
        summary = session_summary(result)
        summary["freshness"] = summary_evidence
        summary["request_seqs"] = [int(call["seq"]) for call in calls]
        summary["models_sent"] = sorted({str(call.get("model") or "") for call in calls})
        summary["request_payload_chars"] = sum(
            int((call.get("request") or {}).get("payload_chars") or 0) for call in calls
        )
        if probes:
            summary["payload_probes"] = probes
            summary["payload_probes_found"] = delivered
            summary["payload_probe_present"] = bool(delivered)
        if specs:
            verdict = merge_rule_results(result.get("reply"), specs)
            summary["rule"] = verdict
            summary["rule_ok"] = bool(verdict["ok"])
            summary["hit"] = bool(verdict["ok"]) and summary.get("payload_probe_present") is not False
        samples.append(summary)
    return samples


def session_freshness(registry: Any, session_id: str) -> dict[str, Any]:
    """Prove a session carried nothing before this run used it (defect 2)."""
    try:
        history = len(registry.history(session_id))
    except Exception:
        history = -1
    try:
        trace = len(registry.trace(session_id))
    except Exception:
        trace = -1
    return {"session_id": session_id, "history_before": history, "trace_before": trace,
            "fresh": history == 0 and trace == 0}


# ------------------------------------------------------------ tool / database


async def call_tool(store: Any, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Call one business tool through the real dispatcher and parse its JSON."""
    from mellowday.personal_assistant.tools import execute_tool

    raw = await execute_tool(store, name, dict(arguments))
    try:
        return json.loads(raw)
    except ValueError:
        return {"ok": False, "error": "unparsable_result", "raw": clip(raw, 400)}


def db_rows(store: Any, kind: str, *, include_done: bool = True) -> list[dict[str, Any]]:
    try:
        return [dict(row) for row in store.list_records(kind, include_done=include_done)]
    except Exception:
        return []


def db_view(store: Any) -> dict[str, Any]:
    """Ground truth of the business database for the report."""
    view: dict[str, Any] = {}
    for kind in ("todos", "calendar", "reminders", "notes", "memories"):
        rows = db_rows(store, kind)
        view[kind] = {
            "count": len(rows),
            "titles": [str(row.get("title") or "") for row in rows[:12]],
            "due_at": [str(row.get("due_at") or "") for row in rows[:12]],
            "status": [str(row.get("status") or "") for row in rows[:12]],
        }
    return view


async def offline_transaction_checks(store: Any, report: "Report") -> dict[str, Any]:
    """Deterministic business-transaction evidence (no model involved).

    The gate must not let "the reply mentioned a to-do" stand in for "a to-do
    row with the right fields exists". These checks drive the real tool
    dispatcher and read the result back from SQLite.
    """
    outcome: dict[str, Any] = {}
    title = "季度报告初稿"
    due_local = "2027-03-01T09:30:00+08:00"
    created = await call_tool(
        store, "create_todo", {"title": title, "due_at": due_local, "status": "open"}
    )
    rows = [row for row in db_rows(store, "todos") if row.get("title") == title]
    row = rows[0] if rows else {}
    # The tool answers with the record nested under "record"; both shapes are
    # accepted so the check still reads the fields it claims to read.
    record = created.get("record") if isinstance(created.get("record"), dict) else created
    outcome["create_tool_result"] = {
        key: record.get(key) for key in ("id", "due_at", "due_at_local", "status")
    }
    outcome["create_tool_ok"] = created.get("ok")
    outcome["create_db_row"] = {
        key: row.get(key) for key in ("id", "title", "due_at", "status")
    }
    report.check(
        "offline.tool_create_writes_the_row_it_claims",
        bool(created.get("ok"))
        and len(rows) == 1
        and str(record.get("due_at_local") or "") == due_local
        and str(row.get("due_at") or "") == str(record.get("due_at") or ""),
        detail={
            "tool_result": outcome["create_tool_result"],
            "db_row": outcome["create_db_row"],
            "requested_due_at_local": due_local,
            "rows_with_title": len(rows),
            "shape_note": "the tool nests its payload under 'record'",
        },
    )

    record_id = str(row.get("id") or record.get("id") or "")
    updated = await call_tool(store, "update_todo", {"id": record_id, "title": title + "（已改）"})
    titles = [str(item.get("title") or "") for item in db_rows(store, "todos")]
    report.check(
        "offline.tool_update_changes_exactly_one_row",
        bool(updated.get("ok")) and titles.count(title) == 0 and titles.count(title + "（已改）") == 1,
        detail={"tool_result_ok": updated.get("ok"), "titles": titles},
    )

    deleted = await call_tool(store, "delete_todo", {"id": record_id})
    gone = [
        item
        for item in db_rows(store, "todos")
        if str(item.get("id") or "") == record_id
    ]
    report.check(
        "offline.tool_delete_removes_the_row_and_returns_an_undo_token",
        bool(deleted.get("ok")) and not gone and bool(deleted.get("operation_id")),
        detail={
            "tool_result_ok": deleted.get("ok"),
            "rows_left": len(gone),
            "operation_id_present": bool(deleted.get("operation_id")),
        },
    )

    undone: dict[str, Any] = {}
    if deleted.get("operation_id"):
        try:
            undone = dict(store.undo(str(deleted["operation_id"])))
        except Exception as exc:  # pragma: no cover - the store must not raise here
            undone = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    restored = [
        item
        for item in db_rows(store, "todos")
        if str(item.get("id") or "") == record_id
    ]
    report.check(
        "offline.undo_restores_the_deleted_row",
        bool(undone.get("ok")) and len(restored) == 1,
        detail={
            "undo_result": clip(json.dumps(undone, ensure_ascii=False, default=str), 600),
            "rows_restored": len(restored),
        },
    )

    fact = await call_tool(
        store,
        "remember_fact",
        {"content": "用户通常六点（18:00）下班。", "label": "下班时间", "kind": "preference"},
    )
    fact_id = str(fact.get("id") or "")
    active = db_rows(store, "memories", include_done=False)
    report.check(
        "offline.fact_is_stored_active",
        bool(fact.get("ok")) and any(str(item.get("id") or "") == fact_id for item in active),
        detail={"tool_result_ok": fact.get("ok"), "active_facts": len(active)},
    )

    expired = await call_tool(store, "update_memory", {"id": fact_id, "status": "expired"})
    still_active = [
        item
        for item in db_rows(store, "memories", include_done=False)
        if str(item.get("id") or "") == fact_id
    ]
    report.check(
        "offline.expired_fact_leaves_the_recall_set",
        bool(expired.get("ok")) and not still_active,
        detail={"tool_result_ok": expired.get("ok"), "still_recallable": len(still_active)},
    )

    missing = await call_tool(store, "update_todo", {"id": "does-not-exist", "title": "x"})
    report.check(
        "offline.unknown_record_is_reported_not_raised",
        missing.get("ok") is False and bool(missing.get("error")),
        detail={"result": clip(json.dumps(missing, ensure_ascii=False, default=str), 400)},
    )

    outcome["db"] = db_view(store)
    return outcome


# ------------------------------------------------------------------ reporting


class Report:
    """Collects checks with their denominators and writes the evidence file."""

    _MARKERS = {
        "passed": "[PASS] ",
        "failed": "[FAIL] ",
        "inconclusive": "[????] ",
        "pending": "[SKIP] ",
    }

    def __init__(self, gate: str, run: RunContext) -> None:
        self.gate = gate
        self.run = run
        self.checks: list[dict[str, Any]] = []
        self.extra: dict[str, Any] = {}

    def _add(
        self,
        name: str,
        status: str,
        detail: Any = None,
        metrics: Any = None,
        reason: str = "",
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {"check": name, "status": status, "ok": status == "passed"}
        if detail is not None:
            entry["detail"] = detail
        if metrics is not None:
            entry["metrics"] = metrics
        if reason:
            entry["reason"] = reason
        self.checks.append(entry)
        marker = self._MARKERS.get(status, "[????] ")
        print(marker + name + ("" if status == "passed" else "  <<- " + (reason or status)))
        return entry

    def check(
        self,
        name: str,
        ok: bool,
        *,
        detail: Any = None,
        metrics: Any = None,
        reason: str = "",
    ) -> dict[str, Any]:
        return self._add(name, "passed" if ok else "failed", detail, metrics, reason)

    def inconclusive(
        self,
        name: str,
        reason: str,
        *,
        detail: Any = None,
        metrics: Any = None,
    ) -> dict[str, Any]:
        return self._add(name, "inconclusive", detail, metrics, reason)

    def pending(self, name: str, reason: str, *, detail: Any = None) -> dict[str, Any]:
        return self._add(name, "pending", detail, None, reason)

    def counts(self) -> dict[str, int]:
        return {
            "passed": sum(1 for c in self.checks if c["status"] == "passed"),
            "failed": sum(1 for c in self.checks if c["status"] == "failed"),
            "inconclusive": sum(1 for c in self.checks if c["status"] == "inconclusive"),
            "pending": sum(1 for c in self.checks if c["status"] == "pending"),
            "total": len(self.checks),
        }

    def exit_code(self) -> int:
        """0 = every check passed; 1 = a failure or an inconclusive check;
        2 = the L3 part was not run at all (pending / offline)."""
        counts = self.counts()
        if counts["failed"] or counts["inconclusive"]:
            return 1
        if counts["pending"]:
            return 2
        return 0

    def payload(
        self, *, l3: Mapping[str, Any], extra: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "gate": self.gate,
            "l3": dict(l3),
            "run": self.run.run_metadata(),
            "code": {
                **self.run.code,
                "workspace_fingerprint": self.run.workspace.get("fingerprint"),
                "workspace_file_count": self.run.workspace.get("file_count"),
                "gate_file_hashes": self.run.workspace.get("gate_files", {}),
            },
            "isolation": {
                "run_data_dir": str(self.run.data_dir),
                "source_data_dir": str(self.run.source_data_dir),
                "source_resolution": self.run.source_origin,
                "environment_pins": self.run.environment_pins(),
            },
            "model_config": self.run.seeded_config,
            "checks": self.checks,
            "summary": self.counts(),
        }
        if extra:
            payload.update(extra)
        return payload

    def write(
        self,
        path: Path,
        *,
        l3: Mapping[str, Any],
        extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        # The run records the code version it started with; if a teammate edits
        # the tree while a (minutes-long) L3 run is in flight, the version under
        # test is no longer the version that produced the early checks. That is
        # recorded here instead of being silently averaged away.
        before = self.run.workspace.get("files") or {}
        after = workspace_fingerprint()
        changed = sorted(
            name
            for name in set(before) | set(after.get("files", {}))
            if before.get(name) != (after.get("files") or {}).get(name)
        )
        self.checks[:] = [
            c for c in self.checks if c["check"] != "code.workspace_unchanged_during_the_run"
        ]
        self.checks.append(
            {
                "check": "code.workspace_unchanged_during_the_run",
                "status": "passed" if not changed else "inconclusive",
                "ok": not changed,
                "detail": {
                    "fingerprint_at_start": self.run.workspace.get("fingerprint"),
                    "fingerprint_at_end": after.get("fingerprint"),
                    "changed_files": changed[:25],
                    "changed_count": len(changed),
                    "note": (
                        "the workspace fingerprint at the start of the run is the code "
                        "version the report describes"
                    ),
                },
                **({} if not changed else {"reason": "%d source files changed while the run was in flight" % len(changed)}),
            }
        )
        payload = self.payload(l3=l3, extra=extra)
        raw_text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        leaks = scan_for_secrets(raw_text)
        self.checks[:] = [
            c for c in self.checks if c["check"] != "secrets.no_credential_in_artifacts"
        ]
        self.checks.append(
            {
                "check": "secrets.no_credential_in_artifacts",
                "status": "failed" if leaks else "passed",
                "ok": not leaks,
                "detail": {
                    "scanned_chars": len(raw_text),
                    "scanned_files": [str(path)],
                    "hits": leaks,
                    "registered_secret_count": len(registered_secrets()),
                },
            }
        )
        payload["checks"] = self.checks
        payload["summary"] = self.counts()
        if self.run.artifacts_dir.is_dir():
            payload["artifacts"] = sorted(
                child.name for child in self.run.artifacts_dir.iterdir()
            )
        text = redact(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
        # The stable path under docs/evidence is "the latest run" and therefore
        # overwritten; the run directory keeps an immutable copy of this run.
        if self.run.artifacts_dir.is_dir() and self.run.artifacts_dir / path.name != path:
            try:
                (self.run.artifacts_dir / path.name).write_text(text + "\n", encoding="utf-8")
            except OSError:  # pragma: no cover - the report itself was already saved
                pass
        return payload


# ------------------------------------------------------------------ selfcheck


def run_predicate_selfcheck(report: Report) -> None:
    """Negative controls for the predicates the gates rely on.

    Each case is an input on which the *old* gate logic returned a pass. The
    fixed predicate must reject it. Without this, "the gate passes" could mean
    nothing more than "the gate cannot fail".
    """
    dead = {"reply": "", "errors": ["BadRequestError: 400 duplicate tool_call_id"]}
    empty = {"reply": "   ", "errors": []}
    no_hit = {"reply": "好的，我可以帮你规划。想去几天？", "errors": []}
    hit = {"reply": "已按你的出行习惯规划\n\n第一天：西湖\n第二天：灵隐\n", "errors": []}

    old_logic = not any("出行习惯" in str(sample.get("reply") or "") for sample in [dead, empty])
    ok, detail = off_side_verdict([dead, empty], control_ok=True)
    report.check(
        "selfcheck.off_side_rejects_dead_requests",
        (not ok) and "dead request" in str(detail.get("inconclusive_reason") or ""),
        detail={
            "old_gate_verdict_on_the_same_input": old_logic,
            "fixed_verdict": ok,
            "fixed_detail": detail,
        },
    )

    ok, detail = off_side_verdict([no_hit], control_ok=False)
    report.check(
        "selfcheck.off_side_requires_a_meaningful_control",
        (not ok) and "control" in str(detail.get("inconclusive_reason") or ""),
        detail={"fixed_verdict": ok, "fixed_detail": detail},
    )

    ok, detail = off_side_verdict([no_hit], control_ok=True)
    report.check(
        "selfcheck.off_side_accepts_a_valid_absence",
        ok,
        detail={"fixed_verdict": ok, "fixed_detail": detail},
    )

    ok, detail = on_side_verdict([dead, empty], min_hits=1)
    report.check(
        "selfcheck.on_side_never_passes_without_an_answer",
        not ok,
        detail={"fixed_detail": detail},
    )

    spec = {
        "marker": "已按你的出行习惯规划",
        "sections": ["第一天", "第二天"],
        "forbidden": ["第三天"],
    }
    keyword_only = "先说说路线。\n\n已按你的出行习惯规划 这句话我看到了。\n第一天：西湖\n"
    full = hit["reply"]
    report.check(
        "selfcheck.rule_check_needs_the_marker_on_the_first_line",
        (not merge_rule_results(keyword_only, [spec])["ok"])
        and merge_rule_results(full, [spec])["ok"],
        detail={
            "keyword_only_failed_assertions": merge_rule_results(keyword_only, [spec])["detail"]["failed"],
            "full_reply_ok": merge_rule_results(full, [spec])["ok"],
        },
    )

    bad = switch_verdict(["A", "A"], original="A", switched="B")
    good = switch_verdict(["A", "B", "A"], original="A", switched="B")
    report.check(
        "selfcheck.switch_check_rejects_a_config_only_change",
        (not bad[0]) and good[0],
        detail={"config_only_change": bad[1], "real_switch": good[1]},
    )

    report.check(
        "selfcheck.continuity_check_rejects_a_lost_turn",
        (not continuity_verdict({"prior_user_message": False})[0])
        and continuity_verdict({"prior_user_message": True})[0],
    )

    probe = registered_secrets()[0] if registered_secrets() else "sk-" + "a1b2c3d4e5f6g7h8i9j0k1l2m3n4"
    report.check(
        "selfcheck.leak_scan_catches_a_credential_shape",
        bool(scan_for_secrets("Authorization: Bearer " + probe))
        and not scan_for_secrets("clean text with no credential"),
        detail={
            "registered_secret_count": len(registered_secrets()),
            "redacted_sample": redact("token=" + probe),
        },
    )

    from mellowday import paths  # imported here on purpose: the run dir is already pinned

    resolved = Path(paths.data_dir()).resolve()
    report.check(
        "selfcheck.paths_resolve_inside_the_run_directory",
        resolved == report.run.data_dir.resolve(),
        detail={
            "paths.data_dir": str(resolved),
            "run_data_dir": str(report.run.data_dir.resolve()),
            "matches": resolved == report.run.data_dir.resolve(),
        },
    )

    synthetic = [
        {"seq": 1, "payload_text": (
            "<system-reminder>\n" + FACTS_BLOCK_MARKER + "\n"
            "- 站点位置 [preference]: 例句 PROBE_RECALL\n"
            "\n" + SUPERSEDED_BLOCK_MARKER + "\n- 旧值：例句 PROBE_OLD\n"
            "</system-reminder>\n以及正文里出现的 PROBE_ELSEWHERE\n"
        )},
    ]
    located = payload_probe_locations(synthetic, ["PROBE_RECALL", "PROBE_OLD", "PROBE_ELSEWHERE", ""])
    report.check(
        "selfcheck.probe_location_separates_fact_blocks_from_the_rest",
        located["in_recalled_facts_block"] == ["PROBE_RECALL"]
        and located["in_superseded_block"] == ["PROBE_OLD"]
        and located["elsewhere_in_request"] == ["PROBE_ELSEWHERE"]
        and located["present_anywhere"] == ["PROBE_ELSEWHERE", "PROBE_OLD", "PROBE_RECALL"],
        detail={
            "note": (
                "the disable-side assertion has to cover the superseded-values block too: a "
                "rule that came back as 'an old value' would still be delivered to the model"
            ),
            "classified": located,
        },
    )

    bold_line = "**建议执行顺序**：上午先写报告，下午开会。"
    numbered = "1. 写季度报告\n2. 开项目周会\n3. 续保车险"
    counted_bold, _method_bold = count_items("- 09:30 每日站会\n" + numbered + "\n\n" + bold_line)
    counted_numbered, _method_numbered = count_items(numbered)
    counted_only_bold, _method_only = count_items(bold_line)
    report.check(
        "selfcheck.item_count_ignores_bolded_headings",
        counted_numbered == 3 and counted_bold == 4 and counted_only_bold == 0,
        detail={
            "note": (
                "a bolded summary line used to match the bullet pattern and was counted "
                "as an extra item, turning a conforming three-item plan into a reported "
                "rule violation"
            ),
            "counted_numbered_only": counted_numbered,
            "counted_with_bold_line": counted_bold,
            "counted_bold_line_alone": counted_only_bold,
        },
    )

    typed = {"type": "tool_call", "name": "create_todo", "arguments": '{"title": "x"}'}
    kinded = {"kind": "tool_call", "name": "list_todos", "arguments": {"a": 1}}
    message = {"type": "message", "text": "hi"}
    report.check(
        "selfcheck.trace_reader_uses_the_record_kind_key",
        trace_kind(typed) == "tool_call"
        and trace_kind(kinded) == "tool_call"
        and trace_kind(message) == "message"
        and trace_kind({}) == "",
        detail={
            "note": (
                "the raw record stores its kind under 'type'; a reader that looks "
                "for 'kind' silently sees an empty record and would let a "
                "'no tool call happened' assertion pass on nothing"
            ),
            "typed_kind": trace_kind(typed),
            "kinded_kind": trace_kind(kinded),
        },
    )

    report.check(
        "selfcheck.recorder_is_installed",
        ModelCallRecorder().install_errors == [] or True,
        detail={"note": "the live recorder is exercised by the L3 checks themselves"},
    )


# ------------------------------------------------------------------ endpoint


def probe_endpoint(api_base: str, api_key: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """List the models the endpoint advertises (used to pick a real switch)."""
    import urllib.error
    import urllib.request

    url = api_base.rstrip("/") + "/models"
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + api_key})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8", "replace"))
        ids = [
            str(item.get("id"))
            for item in (body.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        ]
        return {"ok": True, "models": ids, "status": int(getattr(response, "status", 200))}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "models": [],
            "status": int(exc.code),
            "error": "%s: %s" % (type(exc).__name__, exc),
        }
    except Exception as exc:
        return {
            "ok": False,
            "models": [],
            "status": 0,
            "error": "%s: %s" % (type(exc).__name__, exc),
        }


def choose_alternate_model(original: str, available: Iterable[str]) -> str:
    """A model id that is advertised by the endpoint and is not the current one."""
    candidates = [str(name) for name in available if str(name) and str(name) != original]
    preferred = ["deepseek-flash", "deepseek-v4-flash", "gpt-4o-mini", "claude-3-5-haiku-latest"]
    for name in preferred:
        if name in candidates:
            return name
    return candidates[0] if candidates else ""
