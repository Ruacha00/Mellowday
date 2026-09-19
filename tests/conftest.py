"""Shared pytest configuration.

The suite is hermetic: it never reads a developer .env and never uses a real
model credential. Async tests use the anyio plugin (@pytest.mark.anyio)
because pytest-asyncio is not installed here; the backend is pinned to asyncio.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Must happen before any test module imports mellowday: disable .env loading and
# drop ambient credentials so assertions about an unconfigured model stay true.
os.environ["MELLOWDAY_ENV_FILE"] = ""
for _name in ("MELLOWDAY_API_KEY", "MELLOWDAY_API_BASE", "MELLOWDAY_MODEL"):
    os.environ.pop(_name, None)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Keep every test away from the developer's real data directory."""
    target = tmp_path / "mellowday-data"
    target.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MELLOWDAY_DATA_DIR", str(target))
    yield target
