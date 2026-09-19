"""Environment file loading.

Kept dependency-free and separate from :mod:`mellowday.paths` and
:mod:`mellowday.config` so it can run before either of them is imported.
"""
from __future__ import annotations

import os
from pathlib import Path

_loaded = False


def load_env() -> None:
    """Load MellowDay settings from a local .env file, exactly once.

    Real process environment variables always win over the file, so a
    deployment can override anything without editing the file.
    """
    global _loaded
    if _loaded:
        return
    _loaded = True

    explicit = os.environ.get("MELLOWDAY_ENV_FILE")
    if explicit == "":
        return  # explicitly disabled (the test suite runs hermetic)

    candidates = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    else:
        repo_root = Path(__file__).resolve().parents[2]
        candidates.append(Path.cwd() / ".env")
        candidates.append(repo_root / ".env")

    try:
        from dotenv import load_dotenv
    except Exception:  # python-dotenv is optional at import time
        return

    for candidate in candidates:
        try:
            if candidate.is_file():
                load_dotenv(candidate, override=False)
                return
        except OSError:
            continue
