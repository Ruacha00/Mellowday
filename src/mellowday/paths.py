"""Filesystem layout for MellowDay runtime state.

All persistent state lives under :func:`data_dir`, which defaults to `./data`
relative to the current working directory and can be overridden with the
`MELLOWDAY_DATA_DIR` environment variable.
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "mellowday"


def data_dir() -> Path:
    """Root directory for all MellowDay state (created on demand)."""
    raw = os.environ.get("MELLOWDAY_DATA_DIR")
    base = Path(raw).expanduser() if raw else Path.cwd() / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def ensure(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def skills_dir() -> Path:
    return ensure(data_dir() / "skills")


def skills_archive_dir() -> Path:
    return ensure(data_dir() / "skills" / ".archive")


def sessions_dir() -> Path:
    return ensure(data_dir() / "sessions")


def memory_dir() -> Path:
    return ensure(data_dir() / "memory")


def evolution_dir() -> Path:
    return ensure(data_dir() / "skill_evolution")


def eval_dir() -> Path:
    return ensure(data_dir() / "skill_evolution" / "evals")


def store_path() -> Path:
    return data_dir() / "mellowday.sqlite3"


def config_path() -> Path:
    return data_dir() / "config.json"


def log_path() -> Path:
    return data_dir() / "mellowday.log"


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def static_dir() -> Path:
    return package_dir() / "web_app" / "static"
