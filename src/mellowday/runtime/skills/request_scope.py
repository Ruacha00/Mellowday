"""Guard automatic learning using the latest user request only.

A previous refusal to remember does not veto a new durable instruction; an old
durable preference does not authorize learning a temporary exception. The
extractor still receives the conversation for context and decides what is a
reusable rule. This guard only rejects explicit local scope or current-output
adjustments in the latest turn; it does not infer a standing policy from history.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

__all__ = [
    "classify_request_scope",
    "one_off_skip_reason",
    "user_turn_texts",
]

# 明确的「不要记住」表达。否定「不要一次列十几条」这类内容要求不算命中。
_HARD_PATTERNS: tuple[str, ...] = (
    r"不用记(住|下|了|这条|这个|它|着)?(?![流水账笔日])",
    r"不要记(住|下|这条|这个|它)?(?![流水账笔日])",
    r"不需要记(住|下|这条|这个)?(?![流水账笔日])",
    r"无需记(住|下|这条|这个)?(?![流水账笔日])",
    r"不必记(住|下|这条|这个)?(?![流水账笔日])",
    r"别记(住|下|这|那|它|此|了|吧)?(?![流水账笔日])",
    r"不用保存|不用记录|不用存下来|不用存档|不要保存|别保存|不用留(下来|下)?",
    r"不用学(这个|这条|它)?|别学(这个|这条|它)|不需要学",
    r"(这|此|本条|这条)[^，。；！？\n]{0,8}(不用记|别记|不用保存|不用学)",
    r"忘(掉|记)(这|此|它)|忽略(这|此)条|忽略(刚才|上面)那句",
    r"don'?t (remember|record|save|store|learn)",
    r"do not (remember|record|save|store)",
    r"no need to (remember|record|save|store)",
    r"forget (this|that|it)",
)

# 只针对当前这一轮的限定词。
_ROUND_LIMIT_PATTERNS: tuple[str, ...] = (
    r"这次",
    r"这一次",
    r"这轮",
    r"本轮",
    r"本次",
    r"这一回",
    r"就这一回",
    r"仅此一次",
    r"只这一次",
    r"暂时",
    r"临时",
    r"先这样",
    r"先这么",
    r"先按这个",
    r"this time",
    r"this once",
    r"just this once",
    r"for now",
    r"temporarily",
)

# 针对「当前这段输出」的改动：形状很具体，避免把「任何抱怨」都算成一次性。
_OUTPUT_ADJUST_PATTERNS: tuple[str, ...] = (
    r"再[^，。；！？\n]{0,6}(一些|一点|些|点)",
    r"(第[一二三四五六七八九十百\d]+(条|点|段|个|项|部分)|这(条|段|句|点|部分|块)|"
    r"那一?(条|段|句)|上面那?(条|段|句)|刚才那?(条|段|句)|这里|此处)"
    r"[^，。；！？\n]{0,24}(加|改|换|删|去|补|展开|压缩|缩短|拆分|合并|扩写|润色)",
    r"(加上|再加|补上|多给|少给|删掉|去掉|换成|改成)[^，。；！？\n]{0,12}"
    r"(字段|数据|口径|内容|文字|例子|示例|表格|图表|标题|段落|句子|要点|结论|理由|说明|描述)",
)

# 仅本条用户消息里的长期信号可覆盖本条消息的软信号。
_DURABLE_PATTERNS: tuple[str, ...] = (
    r"以后",
    r"今后",
    r"每次",
    r"每一次",
    r"每回",
    r"一律",
    r"始终",
    r"一直",
    r"长期",
    r"下次",
    r"后续",
    r"成为(习惯|规矩|默认)",
    r"固定(地)?(这样|这么)",
    r"from now on",
    r"every time",
    r"always",
    r"going forward",
    r"in the future",
)

_HARD_RE = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _HARD_PATTERNS)
_ROUND_LIMIT_RE = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _ROUND_LIMIT_PATTERNS)
_OUTPUT_ADJUST_RE = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _OUTPUT_ADJUST_PATTERNS)
_DURABLE_RE = tuple(re.compile(pattern, re.IGNORECASE) for pattern in _DURABLE_PATTERNS)

REASON_HARD_TEMPLATE = (
    "一次性要求不写入：「{hit}」是用户明确表示不用记住这条；自动学习已跳过（管理页仍可手动新建/编辑技能）。"
)
REASON_SOFT_TEMPLATE = (
    "一次性要求不写入：这条反馈只针对当前这次输出（命中「{hit}」），没有长期规则信号；自动学习已跳过。"
)


def _normalize(text: object) -> str:
    raw = str(text or "").replace("\u3000", " ")
    return re.sub(r"\s+", " ", raw).strip()


def user_turn_texts(messages: Iterable[Mapping[str, Any]] | None) -> list[str]:
    """按顺序取出窗口里的用户消息原文（助手消息不是用户证据）。"""
    turns: list[str] = []
    for message in list(messages or []):
        if not isinstance(message, Mapping):
            continue
        if str(message.get("role") or "").strip().lower() != "user":
            continue
        text = _normalize(message.get("content"))
        if text:
            turns.append(text)
    return turns


def _first_hit(patterns: tuple[re.Pattern[str], ...], text: str) -> str:
    for pattern in patterns:
        found = pattern.search(text)
        if found:
            return found.group(0).strip()
    return ""


def classify_request_scope(messages: Iterable[Mapping[str, Any]] | None) -> dict[str, Any]:
    """判定这次反馈能不能进入自动学习。

    返回 dict：scope（one_off/learnable）、learnable、hard、soft、durable、reason、
    last_user；hard/soft/durable 是命中的原文片段（没有命中时为空串），便于把判定理由
    写进可见事件与溯源记录。
    """
    turns = user_turn_texts(messages)
    if not turns:
        return {
            "scope": "learnable",
            "learnable": True,
            "hard": "",
            "soft": "",
            "durable": "",
            "reason": "",
            "last_user": "",
        }

    last_user = turns[-1]
    hard = _first_hit(_HARD_RE, last_user)
    soft = _first_hit(_ROUND_LIMIT_RE, last_user) or _first_hit(_OUTPUT_ADJUST_RE, last_user)
    durable = _first_hit(_DURABLE_RE, last_user)

    if hard:
        return {
            "scope": "one_off",
            "learnable": False,
            "hard": hard,
            "soft": soft,
            "durable": durable,
            "reason": REASON_HARD_TEMPLATE.format(hit=hard),
            "last_user": last_user,
        }
    if soft and not durable:
        return {
            "scope": "one_off",
            "learnable": False,
            "hard": "",
            "soft": soft,
            "durable": "",
            "reason": REASON_SOFT_TEMPLATE.format(hit=soft),
            "last_user": last_user,
        }
    return {
        "scope": "learnable",
        "learnable": True,
        "hard": "",
        "soft": soft,
        "durable": durable,
        "reason": "",
        "last_user": last_user,
    }


def one_off_skip_reason(messages: Iterable[Mapping[str, Any]] | None) -> str:
    """一次性要求时返回可展示的理由；可以学习时返回空串。"""
    verdict = classify_request_scope(messages)
    return "" if verdict["learnable"] else str(verdict["reason"])
