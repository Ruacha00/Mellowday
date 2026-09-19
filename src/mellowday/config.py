"""Model and runtime configuration.

Environment variables win over the stored config file so that a deployment can
override credentials without rewriting local state.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any

from mellowday import paths

DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_API_BASE = "https://api.deepseek.com"


@dataclass
class ModelConfig:
    """Configuration for one OpenAI-compatible chat completion endpoint."""

    api_key: str = ""
    api_base: str = DEFAULT_API_BASE
    model: str = DEFAULT_MODEL
    thinking: bool = False
    max_turns: int | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def public(self) -> dict[str, Any]:
        """Serializable view that never leaks the API key."""
        return {
            "api_base": self.api_base,
            "model": self.model,
            "thinking": self.thinking,
            "max_turns": self.max_turns,
            "configured": self.configured,
            "api_key_hint": (self.api_key[:4] + "..." + self.api_key[-4:]) if len(self.api_key) > 12 else "",
        }


def _read_file() -> dict[str, Any]:
    path = paths.config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_file(payload: dict[str, Any]) -> None:
    path = paths.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_model_config() -> ModelConfig:
    stored = _read_file().get("model", {}) if isinstance(_read_file().get("model", {}), dict) else {}
    cfg = ModelConfig(
        api_key=str(stored.get("api_key") or ""),
        api_base=str(stored.get("api_base") or DEFAULT_API_BASE),
        model=str(stored.get("model") or DEFAULT_MODEL),
        thinking=bool(stored.get("thinking", False)),
        max_turns=stored.get("max_turns") if isinstance(stored.get("max_turns"), int) else None,
    )
    # Environment overrides.
    cfg.api_key = os.environ.get("MELLOWDAY_API_KEY") or cfg.api_key
    cfg.api_base = os.environ.get("MELLOWDAY_API_BASE") or cfg.api_base
    cfg.model = os.environ.get("MELLOWDAY_MODEL") or cfg.model
    return cfg


def save_model_config(cfg: ModelConfig) -> ModelConfig:
    payload = _read_file()
    payload["model"] = asdict(cfg)
    _write_file(payload)
    return load_model_config()


def update_model_config(**changes: Any) -> ModelConfig:
    cfg = load_model_config()
    for key, value in changes.items():
        if value is None or not hasattr(cfg, key):
            continue
        if key == "api_key" and value == "":
            continue  # empty key means "keep existing"
        setattr(cfg, key, value)
    return save_model_config(cfg)
