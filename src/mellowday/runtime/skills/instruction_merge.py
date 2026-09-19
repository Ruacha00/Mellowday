"""Preserve existing rule units unless explicitly superseded verbatim.

Only exact text duplicates are skipped. Similar wording is not evidence of
identical meaning or an instruction to replace another rule. Public similarity
helpers remain available for diagnostics, but do not decide writes or removals.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

__all__ = [
    "NOTES_MARKER",
    "split_evolution_notes",
    "split_rule_units",
    "rule_similarity",
    "rule_overlap",
    "merge_instructions",
]

NOTES_MARKER = "## Evolution Notes"

_LIST_MARKER = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_HEADING = re.compile(r"^\s*#{1,6}\s+")
_PUNCT = re.compile("[\\s\\u3000，。、；：！？,.;:!?\x60'\"“”‘’()（）\\[\\]【】<>《》\\-\\u2014_*+|~#]+")
_WORD_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def split_evolution_notes(body: str) -> tuple[str, str]:
    """把正文拆成 (规则正文, 演化溯源小节)；没有溯源小节时第二项为空串。"""
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.strip().startswith(NOTES_MARKER):
            rules = "\n".join(lines[:index]).strip("\n")
            notes = "\n".join(lines[index:]).strip("\n")
            return rules, notes
    return text.strip("\n"), ""


def _is_list_item(line: str) -> bool:
    return bool(_LIST_MARKER.match(line))


def _is_heading(line: str) -> bool:
    return bool(_HEADING.match(line))


def split_rule_units(text: str) -> list[str]:
    """把正文切成规则单位：标题、列表项、段落各自成一条。

    列表项的续行（缩进的下一行）并入上一条规则，避免把一条规则拆散。
    """
    units: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            units.append("\n".join(current).strip())
            current.clear()

    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            flush()
            continue
        if _is_heading(line):
            flush()
            units.append(line.strip())
            continue
        if _is_list_item(line):
            flush()
            current.append(line.strip())
            continue
        if current and raw_line[:1].isspace():
            # 续行：接在最近的规则后面，保持一条规则的完整语义。
            current.append(line.strip())
            continue
        if current and not _is_list_item(current[0]) and not _is_heading(current[0]):
            current.append(line.strip())
            continue
        flush()
        current.append(line.strip())
    flush()
    return [unit for unit in units if unit]


def _normalize_rule(text: str) -> str:
    return _PUNCT.sub("", str(text or "").lower())


def _rule_tokens(text: str) -> set[str]:
    raw = str(text or "").lower()
    tokens = set(_WORD_RE.findall(raw))
    for chunk in _CJK_RE.findall(raw):
        if len(chunk) == 1:
            tokens.add(chunk)
        for index in range(len(chunk) - 1):
            tokens.add(chunk[index : index + 2])
    return {token for token in tokens if token}


def rule_similarity(left: str, right: str) -> float:
    """两条规则的 Jaccard 相似度（0.0-1.0）；两条都为空时视为相同。"""
    a = _rule_tokens(left)
    b = _rule_tokens(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def rule_overlap(left: str, right: str) -> float:
    """交集除以较短一侧；用于识别「在旧规则后面补写」这类改写。"""
    a = _rule_tokens(left)
    b = _rule_tokens(right)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _coerce_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _join_units(units: Sequence[str]) -> str:
    out = ""
    for unit in units:
        if not out:
            out = unit
            continue
        previous_last = out.split("\n")[-1]
        separator = "\n" if (_is_list_item(unit) and _is_list_item(previous_last)) else "\n\n"
        out += separator + unit
    return out


def merge_instructions(
    *,
    existing_body: str,
    new_instructions: str = "",
    proposed_body: str = "",
    superseded: Iterable[str] | None = None,
) -> dict[str, Any]:
    """把候选规则并进既有正文，返回合并结果与可读的变更说明。

    参数
    ----
    existing_body: 技能当前的完整正文（可以带 ## Evolution Notes）。
    new_instructions: 候选正文；proposed_body 为空时用它作为新规则来源。
    proposed_body: 模型给出的完整合并正文；非空时优先作为新规则来源，但**旧规则
        的保全规则不变**——模型漏掉的旧规则会被保留，不会静默丢失。
    superseded: 模型明确要求删除的旧规则（逐字引用）。

    返回 dict 里有 changed / body / rules_body / notes / added / kept /
    duplicate / revised / removed / reason 字段；changed 为 False 时调用方不得写入。
    """
    rules_text, notes = split_evolution_notes(existing_body)
    old_units = split_rule_units(rules_text)

    proposed_rules, _ = split_evolution_notes(proposed_body)
    source = proposed_rules.strip() if str(proposed_body or "").strip() else str(new_instructions or "")
    new_units = split_rule_units(source)
    superseded_keys = set(_coerce_list(superseded))

    working = list(old_units)
    kept: list[str] = []
    added: list[str] = []
    duplicate: list[str] = []
    revised: list[dict[str, str]] = []
    removed: list[str] = []

    # 显式淘汰：模型逐字列出的旧规则直接删除（唯一允许丢旧规则的通道）。
    for key in superseded_keys:
        for index, unit in enumerate(list(working)):
            if unit == key:
                removed.append(working.pop(index))
                break

    for unit in new_units:
        if unit in superseded_keys:
            # 模型把要删除的规则又写进了合并正文：删除优先。
            continue
        if unit in working:
            duplicate.append(unit)
            continue
        working.append(unit)
        added.append(unit)

    for unit in working:
        if unit in old_units and unit not in kept:
            kept.append(unit)

    changed = working != old_units
    rules_body = _join_units(working)
    body = rules_body if not notes else (rules_body + "\n\n" + notes).strip() + "\n"

    reason = _describe(
        changed=changed, added=added, revised=revised, removed=removed, duplicate=duplicate, kept=kept
    )
    return {
        "changed": changed,
        "body": body,
        "rules_body": rules_body,
        "notes": notes,
        "added": added,
        "kept": kept,
        "duplicate": duplicate,
        "revised": revised,
        "removed": removed,
        "reason": reason,
    }


def _describe(
    *,
    changed: bool,
    added: Sequence[str],
    revised: Sequence[dict[str, str]],
    removed: Sequence[str],
    duplicate: Sequence[str],
    kept: Sequence[str],
) -> str:
    if not changed:
        return "候选与现有习惯重复，没有新的可持久化规则"
    parts: list[str] = []
    if added:
        parts.append(f"新增 {len(added)} 条规则")
    if revised:
        parts.append(f"修改 {len(revised)} 条规则")
    if removed:
        parts.append(f"删除 {len(removed)} 条规则")
    if kept:
        parts.append(f"保留 {len(kept)} 条旧规则")
    if duplicate:
        parts.append(f"跳过 {len(duplicate)} 条重复规则")
    return "、".join(parts) or "规则有变化"
