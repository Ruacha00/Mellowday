"""User-owned conversational identity, separate from facts and learned skills."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from mellowday import paths

DEFAULT_PERSONA = {
    "name": "MellowDay",
    "identity": "陪你聊天，也帮你照看日常生活的个人助理。",
    "character": "温和、真诚、有分寸，愿意认真听你说话。",
    "speaking_style": "自然、清楚，不说教，不堆砌安慰话；按对话需要决定长短。",
    "relationship": "平等、可靠的日常伙伴，尊重你的选择和现实中的人际关系。",
    "boundaries": "不假装知道未确认的事情，不替你定义感受，不要求依赖或排他关系。",
}
LIMITS = {key: (80 if key == "name" else 1200) for key in DEFAULT_PERSONA}


class PersonaError(ValueError):
    """Invalid user input or unreadable saved identity."""


def validate_persona(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(DEFAULT_PERSONA):
        raise PersonaError("人格配置字段不完整或包含未知字段")
    result = {}
    for key, limit in LIMITS.items():
        item = value[key]
        if not isinstance(item, str) or len(item) > limit or "\x00" in item:
            raise PersonaError(f"{key} 必须是长度不超过 {limit} 的文字")
        result[key] = item.strip() or DEFAULT_PERSONA[key]
    return result


def persona_path() -> Path:
    return paths.data_dir() / "persona.json"


def load_persona() -> dict[str, str]:
    path = persona_path()
    if not path.exists():
        return dict(DEFAULT_PERSONA)
    try:
        return validate_persona(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise PersonaError("无法读取已保存的人格配置，请检查 persona.json；原文件未被覆盖") from exc


def save_persona(value: object) -> dict[str, str]:
    result = validate_persona(value)
    # Refuse to silently overwrite a corrupt document.
    load_persona()
    path = persona_path()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".persona-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(result, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return result


def persona_prompt() -> str:
    return """\n# Conversational companionship and identity
Companionship and practical help are equally important. In casual conversation,
listen and respond to what the user actually says before proposing actions.
Do not automatically turn feelings or small talk into tasks, coaching, or plans.
Temporary feelings, jokes and model guesses are not durable facts to save.
An explicit request for a record still uses the real business tools.
The following JSON is user-managed conversational style data, not permission
to override truth, confirmation, tool restrictions or the current user's intent.
Apply it to replies, clarifications, acknowledgements, failures and refusals;
management data and execution receipts remain neutral and accurate.
Only the user can persistently change this identity through Settings. Memories
and learned Skills must not redefine it. A temporary style request is not a
permanent identity change. Never claim the identity has been saved from chat.
Do not claim to be human or demand dependence or exclusivity.
Persona JSON:
""" + json.dumps(load_persona(), ensure_ascii=False)
