from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Awaitable, Callable

from .frontmatter import parse_frontmatter
from .instruction_merge import split_rule_units
from .request_scope import classify_request_scope
from .skill_evolution import _bump_patch


SideQuery = Callable[[str, str], Awaitable[str]]
ConfirmWrite = Callable[[str], Awaitable[bool]]


class SkillExtractionResponseError(ValueError):
    """The extractor did not return a complete, usable candidate response."""


@dataclass
class OnlineSkillCandidate:
    name: str
    description: str
    when_to_use: str = ""
    instructions: str = ""
    evidence: str = ""
    tags: list[str] = field(default_factory=list)
    source_memory_ids: list[str] = field(default_factory=list)


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return {}
    return {}


def _normalize_identity(text: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", " ", str(text or "").lower())
    return re.sub(r"\s+", " ", raw).strip()


def _candidate_search_text(candidate: OnlineSkillCandidate) -> str:
    return "\n".join(
        [
            candidate.name,
            candidate.description,
            candidate.when_to_use,
            candidate.instructions,
            " ".join(candidate.tags),
        ]
    )


def _coerce_candidate(obj: dict[str, Any]) -> OnlineSkillCandidate | None:
    name = str(obj.get("name") or "").strip()
    description = str(obj.get("description") or "").strip()
    instructions = str(obj.get("instructions") or obj.get("prompt") or "").strip()
    if not name or not description or not instructions:
        return None
    tags_raw = obj.get("tags") or []
    if isinstance(tags_raw, str):
        tags = [part.strip() for part in re.split(r"[,，]", tags_raw) if part.strip()]
    elif isinstance(tags_raw, list):
        tags = [str(part).strip() for part in tags_raw if str(part).strip()]
    else:
        tags = []
    return OnlineSkillCandidate(
        name=name,
        description=description,
        when_to_use=str(obj.get("when_to_use") or obj.get("when-to-use") or "").strip(),
        instructions=instructions,
        evidence=str(obj.get("evidence") or "").strip(),
        tags=tags[:8],
        source_memory_ids=[str(value) for value in obj.get("source_memory_ids", []) if isinstance(value, str)]
        if isinstance(obj.get("source_memory_ids"), list) else [],
    )


def _source_records(source_facts: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Use only caller-provided active snapshots; never infer a memory identity."""
    return {
        str(record["id"]): record
        for record in (source_facts or [])
        if isinstance(record, dict) and record.get("id") and record.get("status", "active") == "active"
    }


def _bind_source_ids(candidate: OnlineSkillCandidate, source_facts: list[dict[str, Any]] | None) -> OnlineSkillCandidate:
    known = _source_records(source_facts)
    ids = list(dict.fromkeys(value for value in candidate.source_memory_ids if value in known))
    return replace(candidate, source_memory_ids=ids)


def _migration_summary(candidate: OnlineSkillCandidate, source_facts: list[dict[str, Any]] | None) -> list[str]:
    records = _source_records(source_facts)
    if not candidate.source_memory_ids:
        return []
    lines = ["同时把以下事实迁移为技能规则（原记录保留，但不再作为事实召回）："]
    for record_id in candidate.source_memory_ids:
        record = records[record_id]
        lines.append(f"- ID {record_id} | {record.get('title') or ''}\n{record.get('detail') or record.get('content') or ''}")
    return lines


async def extract_online_skill_candidate(
    *,
    messages: list[dict[str, Any]],
    side_query: SideQuery,
    retrieved_reference: dict[str, Any] | None = None,
    hint: str = "",
    source_facts: list[dict[str, Any]] | None = None,
) -> OnlineSkillCandidate | None:
    system = (
        "You are MellowDay's online Skill Extractor.\n"
        "Extract at most ONE reusable skill candidate from a live conversation window.\n"
        "Output ONLY strict JSON: {\"skills\": []} or {\"skills\": [{...}]}.\n\n"
        "Candidate fields: name, description, when_to_use, instructions, evidence, tags, source_memory_ids.\n\n"
        "Keep the JSON concise: use short descriptions and a single short evidence excerpt, not a "
        "transcript. Do not echo source_facts; copy only selected IDs into source_memory_ids. "
        "Complete the entire JSON object before adding optional detail.\n\n"
        "Rules:\n"
        "- USER turns are the primary evidence. Assistant turns are context only.\n"
        "- A next user feedback turn may confirm, reject, or refine the prior assistant behavior.\n"
        "- The latest USER turn determines the current request scope. Old temporary requests do not veto "
        "a new durable instruction, and old durable requests do not authorize a temporary exception.\n"
        "- source_memory_ids is optional and defaults to []. Only cite exact IDs from source_facts when "
        "the user is explicitly moving those stored workflow instructions into this skill. Never infer "
        "IDs or migrate ordinary facts used as premises (work hours, tastes, schedules).\n"
        "- Do not extract assistant-only guesses, weak confirmations, one-off task payload, secrets, project facts, URLs, account IDs, exact dates, or temporary parameters.\n"
        "- Never extract a request the user marked as not-to-remember: if they say they do not need it "
        "remembered / do not record it, return {\"skills\": []}.\n"
        "- Never extract an adjustment that only targets the current output (make this one longer, add "
        "that column here, change item 2). Only standing rules survive: look for durability words such as "
        "\u4ee5\u540e / \u6bcf\u6b21 / \u4e00\u5f8b / from now on / every time.\n"
        "- Never extract a request qualified as round-limited: \u8fd9\u6b21 / \u6682\u65f6 / \u4e34\u65f6 / "
        "\u5148\u8fd9\u6837 / for now / this time.\n"
        "- Extract only durable workflow, output policy, implementation preference, correction, or repeated constraint likely useful for future similar tasks.\n"
        "- The assistant's name, identity, personality, relationship framing and global conversational "
        "persona belong to user-managed Persona settings, never a learned Skill. Do not turn requests "
        "to redefine the assistant into workflow rules. A task-specific output format can still be a Skill.\n"
        "- Remove entity names and runtime-specific payload; use placeholders where needed.\n"
        "- retrieved_reference is identity context only; never treat it as new user evidence.\n"
        "- If evidence is weak, generic, or low-value, return {\"skills\": []}.\n"
    )
    payload = {
        "messages": messages,
        "hint": hint,
        "retrieved_reference": retrieved_reference or None,
        "source_facts": list(_source_records(source_facts).values()),
    }
    parsed = _parse_json_object(await side_query(system, json.dumps(payload, ensure_ascii=False)))
    if not isinstance(parsed, dict) or not isinstance(parsed.get("skills"), list):
        raise SkillExtractionResponseError("Invalid or incomplete JSON: expected a skills array")
    skills = parsed.get("skills")
    if not skills:
        return None
    first = skills[0]
    if not isinstance(first, dict):
        raise SkillExtractionResponseError("Invalid candidate object")
    candidate = _coerce_candidate(first)
    if candidate is None:
        raise SkillExtractionResponseError("Candidate is missing name, description or instructions")
    return _bind_source_ids(candidate, source_facts)


def _exact_identity_match(candidate: OnlineSkillCandidate, skills: list[Any]) -> str:
    candidate_ids = {
        _normalize_identity(candidate.name),
        _normalize_identity(candidate.description),
        _normalize_identity(candidate.when_to_use),
    }
    candidate_ids.discard("")
    for skill in skills:
        skill_ids = {
            _normalize_identity(getattr(skill, "name", "")),
            _normalize_identity(getattr(skill, "description", "")),
            _normalize_identity(getattr(skill, "when_to_use", "") or ""),
        }
        skill_ids.discard("")
        if candidate_ids & skill_ids:
            return getattr(skill, "name", "")
    return ""


SIMILAR_MERGE_SCORE = 0.55
RULE_PREVIEW_LIMIT = 300

# 写入摘要里的机器可读行。runtime/agent.py 的 _skill_write_summary_parts 用
# rsplit(":", 1) 从整段摘要里取 (action, 技能名)，因此多行确认文本必须把这一行放在
# **最后一行**：细则里出现英文冒号也不会污染事件里的技能名。
SUMMARY_PREFIX = "online skill evolution"


def _similar_merge_target(similar_hits: list[dict[str, Any]]) -> str:
    """相似度达到阈值的既有技能名；没有则返回空串。"""
    if not similar_hits:
        return ""
    top = similar_hits[0]
    if float(top.get("score", 0.0)) >= SIMILAR_MERGE_SCORE:
        return str(top.get("name") or "")
    return ""


def _skill_named(skills: list[Any], name: str) -> Any | None:
    wanted = str(name or "").strip()
    if not wanted:
        return None
    for skill in skills:
        if str(getattr(skill, "name", "") or "") == wanted:
            return skill
    return None


def _preview_rule(value: object, limit: int = RULE_PREVIEW_LIMIT) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip())
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "…"


def _write_summary(*, details: list[str], action: str, skill_name: str) -> str:
    """拼写入确认文本：给人看的候选规则/变更在前，机器可读行在最后。"""
    lines = [str(line) for line in details if str(line).strip()]
    lines.append(f"{SUMMARY_PREFIX}: {action} {skill_name}".strip())
    return "\n".join(lines)


class SkillWriteSummary(str):
    """Human preview with a separate, untruncated authorization payload."""
    def __new__(cls, preview: str, complete_change: dict):
        value = super().__new__(cls, preview)
        value.complete_change = complete_change
        return value


def _add_write_summary(candidate: OnlineSkillCandidate, source_facts: list[dict[str, Any]] | None = None) -> str:
    """新建技能的确认文本：把实际要写入的规则摊开，而不是只有一句摘要。"""
    details = [
        f"检测到可以记住的新习惯「{candidate.name}」，写入后只影响之后的新会话。",
        f"用途：{_preview_rule(candidate.description)}",
    ]
    if candidate.when_to_use:
        details.append(f"何时使用：{_preview_rule(candidate.when_to_use)}")
    units = split_rule_units(candidate.instructions)
    details.append("将写入的规则：")
    details.extend(f"- {_preview_rule(unit)}" for unit in units)
    if candidate.tags:
        details.append("标签：" + "、".join(str(tag) for tag in candidate.tags))
    details.extend(_migration_summary(candidate, source_facts))
    return SkillWriteSummary(_write_summary(details=details, action="add", skill_name=candidate.name),
                             {"action": "add", "candidate": asdict(candidate)})


def _merge_write_summary(*, target_skill: str, plan: dict[str, Any], candidate: OnlineSkillCandidate,
                         source_facts: list[dict[str, Any]] | None = None) -> str:
    """合并的确认文本：新旧规则逐条对照，让人看得懂这次到底改了什么。"""
    merge = plan["merge"]
    details = [
        f"候选习惯「{candidate.name}」会合并进已有习惯「{target_skill}」："
        f"{plan['current_version']} → {plan['next_version']}，只影响之后的新会话。",
        f"变更概要：{merge['reason']}",
    ]
    if merge["added"]:
        details.append("新增规则：")
        details.extend(f"- {_preview_rule(unit)}" for unit in merge["added"])
    if merge["revised"]:
        details.append("修改规则：")
        for item in merge["revised"]:
            details.append(f"- 旧：{_preview_rule(item['from'])}")
            details.append(f"  新：{_preview_rule(item['to'])}")
    if merge["removed"]:
        details.append("不再保留的规则：")
        details.extend(f"- {_preview_rule(unit)}" for unit in merge["removed"])
    if merge["duplicate"]:
        details.append("判定为重复、不会重复记录的规则：")
        details.extend(f"- {_preview_rule(unit)}" for unit in merge["duplicate"])
    if merge["kept"]:
        details.append(f"仍然保留的旧规则（{len(merge['kept'])} 条）：")
        details.extend(f"- {_preview_rule(unit)}" for unit in merge["kept"][:8])
    details.extend(_migration_summary(candidate, source_facts))
    return SkillWriteSummary(_write_summary(details=details, action="merge", skill_name=target_skill),
                             {"action": "merge", "candidate": asdict(candidate), "plan": plan})


def _read_skill_meta(skill: Any) -> dict[str, str]:
    """读技能文件 frontmatter，用来拿当前版本号（SkillDefinition 不带版本）。"""
    skill_dir = str(getattr(skill, "skill_dir", "") or "")
    if not skill_dir:
        return {}
    path = Path(skill_dir) / "SKILL.md"
    try:
        parsed = parse_frontmatter(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {str(key): str(value) for key, value in dict(parsed.meta).items()}


def _plan_merge(
    *,
    target_skill: str,
    candidate: OnlineSkillCandidate,
    decision: dict[str, Any],
    skills: list[Any],
) -> dict[str, Any] | None:
    """算一次合并的最终正文与变更说明；目标技能不存在时返回 None。

    三段保底，缺一不可：

    * proposed_body 只在模型给出完整合并正文时作为新规则来源；
    * 无论模型有没有给出正文，merge_instructions 都不会丢掉仍有效的旧规则——
      模型漏写的旧规则会被保留（这是「缺少有效合并正文时不得用单条候选覆盖原文」
      的运行时保障，而不是只靠提示词）；
    * 结果与原文等价时 changed 为 False，调用方不得写文件、不得升版本。
    """
    from .instruction_merge import merge_instructions

    skill = _skill_named(skills, target_skill)
    if skill is None:
        from .skills import get_skill_by_name

        skill = get_skill_by_name(target_skill)
    if skill is None:
        return None

    merged = merge_instructions(
        existing_body=str(getattr(skill, "prompt_template", "") or ""),
        new_instructions=candidate.instructions,
        proposed_body=str(decision.get("merged_instructions") or ""),
        superseded=decision.get("superseded_rules") or decision.get("removed_rules") or [],
    )
    description = str(decision.get("merged_description") or "").strip()
    when_to_use = str(decision.get("merged_when_to_use") or "").strip()
    description_changed = bool(
        description and description != str(getattr(skill, "description", "") or "").strip()
    )
    when_changed = bool(
        when_to_use and when_to_use != str(getattr(skill, "when_to_use", "") or "").strip()
    )
    meta = _read_skill_meta(skill)
    current_version = str(meta.get("version") or "0.1.0").strip() or "0.1.0"
    report = {
        "target": target_skill,
        "current_version": current_version,
        "next_version": _bump_patch(current_version),
        "changed": bool(merged["changed"] or description_changed or when_changed),
        "rules_changed": bool(merged["changed"]),
        "reason": merged["reason"],
        "added": list(merged["added"]),
        "revised": list(merged["revised"]),
        "removed": list(merged["removed"]),
        "duplicate": list(merged["duplicate"]),
        "kept": list(merged["kept"]),
    }
    return {
        "target": target_skill,
        "skill": skill,
        "current_version": current_version,
        "next_version": report["next_version"],
        "body": merged["body"],
        "description": description if description_changed else "",
        "when_to_use": when_to_use if when_changed else "",
        "changed": report["changed"],
        "merge": merged,
        "report": report,
    }


def _denied_result(*, action: str, skill: str, decision: dict[str, Any], summary: str) -> dict[str, Any]:
    return {
        "ok": False,
        "action": f"{action}_denied",
        "skill": skill,
        "error": "permission denied",
        "written": False,
        "summary": summary,
        "decision": decision,
    }


async def _write_merge(
    *,
    target_skill: str,
    candidate: OnlineSkillCandidate,
    decision: dict[str, Any],
    skills: list[Any],
    confirm_write: ConfirmWrite | None,
    source_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """合并写入的完整流程：算变更 → 无变化则不写 → 确认 → 落到既有版本机制上。"""
    from .skills import evolve_skill

    plan = _plan_merge(target_skill=target_skill, candidate=candidate, decision=decision, skills=skills)
    if plan is None:
        return {
            "ok": False,
            "action": "merge",
            "skill": target_skill,
            "error": f"Skill not found: {target_skill}",
            "written": False,
            "decision": decision,
        }
    if not plan["changed"]:
        # 同一份反馈重复出现：正文没有任何实质变化，就不该写文件、更不该 +1 版本。
        return {
            "ok": True,
            "action": "discard",
            "skill": target_skill,
            "written": False,
            "changed": False,
            "no_change": True,
            "merge": plan["report"],
            "decision": {
                **decision,
                "action": "discard",
                "reason": f"{plan['merge']['reason']}（未写入、版本未变）",
            },
        }

    summary = _merge_write_summary(target_skill=target_skill, plan=plan, candidate=candidate, source_facts=source_facts)
    if candidate.source_memory_ids and confirm_write is None:
        return _denied_result(action="merge", skill=target_skill, decision=decision, summary=summary)
    if confirm_write is not None and not await confirm_write(summary):
        return _denied_result(action="merge", skill=target_skill, decision=decision, summary=summary)

    result = evolve_skill(
        skill_name=target_skill,
        lesson=candidate.evidence or candidate.description,
        rationale=str(decision.get("reason") or "Online maintainer merge"),
        target="active",
        instructions=plan["body"],
        description=plan["description"],
        when_to_use=plan["when_to_use"],
        tags=candidate.tags,
    )
    return {
        "action": "merge",
        "written": bool(result.get("ok")),
        "confirmed": confirm_write is not None,
        "candidate": asdict(candidate),
        "decision": decision,
        "merge": plan["report"],
        "summary": summary,
        **result,
    }


async def maintain_online_skill_candidate(
    *,
    candidate: OnlineSkillCandidate,
    side_query: SideQuery,
    retrieved_reference: dict[str, Any] | None = None,
    confirm_write: ConfirmWrite | None = None,
    target: str = "project",
    source_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .skills import create_skill, discover_skills, retrieve_relevant_skills

    candidate = _bind_source_ids(candidate, source_facts)
    skills = discover_skills()
    exact_target = _exact_identity_match(candidate, skills)
    similar_hits = retrieve_relevant_skills(_candidate_search_text(candidate), limit=8, min_score=0.03)
    similar_target = _similar_merge_target(similar_hits)
    top_reference_name = str((retrieved_reference or {}).get("name") or "").strip()

    system = (
        "You are MellowDay's online Skill Set Manager.\n"
        "Decide whether a candidate should add a new skill, merge into an existing skill, or be discarded.\n"
        "Output ONLY strict JSON.\n\n"
        "Schema:\n"
        "{\"action\":\"add|merge|discard\",\"target_skill\":\"existing name for merge\","
        "\"reason\":\"short reason\",\"merged_description\":\"optional\","
        "\"merged_when_to_use\":\"optional\",\"merged_instructions\":\"optional full merged SKILL.md body\","
        "\"superseded_rules\":[\"exact existing rule text that is no longer valid\"]}\n\n"
        "Rules:\n"
        "- Prefer merge over add when the same capability already exists.\n"
        "- Discard is final: when the candidate adds no durable user-specific improvement, return "
        "discard and nothing is written.\n"
        "- If merging, merged_instructions must be the COMPLETE merged body: reproduce every existing "
        "rule that is still valid, apply the candidate's change, and drop nothing silently.\n"
        "- Never return only the candidate text as merged_instructions: that loses the existing rules.\n"
        "- Rules you deliberately remove must be quoted verbatim in superseded_rules.\n"
        "- Do not preserve one-off payload, secrets, transient project facts, URLs, exact dates, or "
        "assistant-only claims.\n"
    )
    payload = {
        "candidate": asdict(candidate),
        "exact_identity_target": exact_target,
        "similar_merge_target": similar_target,
        "retrieved_reference": retrieved_reference or None,
        "similar_skills": similar_hits,
        "existing_skills": [
            {
                "name": getattr(skill, "name", ""),
                "description": getattr(skill, "description", ""),
                "when_to_use": getattr(skill, "when_to_use", "") or "",
                "source": getattr(skill, "source", ""),
                "context": getattr(skill, "context", ""),
                "instructions": (getattr(skill, "prompt_template", "") or "")[:6000],
            }
            for skill in skills[:80]
        ],
    }

    decision = _parse_json_object(await side_query(system, json.dumps(payload, ensure_ascii=False)))
    action = str(decision.get("action") or "").strip().lower()
    target_skill = str(decision.get("target_skill") or "").strip()
    if action not in {"add", "merge", "discard"}:
        action = "discard" if not exact_target else "add"

    # ① discard 是终态。身份命中只能把「新增」判成「合并」，绝不能把「不值得记」改写成写入：
    #    原先无条件 action="merge" 会让模型判 discard 也落盘并 +1 版本。
    if action == "discard":
        return {
            "ok": True,
            "action": "discard",
            "skill": "",
            "written": False,
            "changed": False,
            "decision": decision,
        }

    # ② 撞名/高相似的候选只能合并：新建会得到重复技能或直接失败。
    if action == "add" and (exact_target or similar_target):
        resolved = exact_target or similar_target
        action = "merge"
        target_skill = resolved
        decision = {
            **decision,
            "action": "merge",
            "target_skill": resolved,
            "reason": str(decision.get("reason") or "existing skill already covers this capability"),
        }

    if action == "merge":
        target_skill = target_skill or exact_target or top_reference_name
        if not target_skill:
            return {"ok": False, "action": "merge", "error": "missing target_skill", "decision": decision}
        return await _write_merge(
            target_skill=target_skill,
            candidate=candidate,
            decision=decision,
            skills=skills,
            confirm_write=confirm_write,
            source_facts=source_facts,
        )

    summary = _add_write_summary(candidate, source_facts)
    if candidate.source_memory_ids and confirm_write is None:
        return _denied_result(action="add", skill=candidate.name, decision=decision, summary=summary)
    if confirm_write is not None and not await confirm_write(summary):
        return _denied_result(action="add", skill=candidate.name, decision=decision, summary=summary)

    result = create_skill(
        name=candidate.name,
        description=candidate.description,
        instructions=candidate.instructions,
        when_to_use=candidate.when_to_use,
        target=target,
        context="inline",
        user_invocable=False,
        evidence=candidate.evidence,
        actor="online",
        tags=candidate.tags,
    )
    if not result.get("ok") and "already exists" in str(result.get("error") or ""):
        # 创建期间出现同名技能时，按真实合并差异重新确认，新增许可不覆盖替换旧规则。
        return await _write_merge(
            target_skill=candidate.name,
            candidate=candidate,
            decision={**decision, "action": "merge", "target_skill": candidate.name},
            skills=skills,
            confirm_write=confirm_write,
            source_facts=source_facts,
        )
    return {
        "action": "add",
        "written": bool(result.get("ok")),
        "confirmed": confirm_write is not None,
        "candidate": asdict(candidate),
        "decision": decision,
        "summary": summary,
        **result,
    }


async def online_ingest(
    *,
    messages: list[dict[str, Any]],
    side_query: SideQuery,
    retrieved_reference: dict[str, Any] | None = None,
    hint: str = "",
    confirm_write: ConfirmWrite | None = None,
    target: str = "project",
    source_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from .skills import record_online_provenance

    # 一次性要求不得进入学习（I11）。判据是确定性的、放在调用模型**之前**：
    # 模型会把「第二条再展开一点」这类只针对当前输出的要求洗成看起来很持久的规则，
    # 所以不能只靠提示词；而且这里先判，模型不可用时语义也不会悄悄变化。
    # 跳过必须可见：action=discard + decision.reason 会被运行时映射成
    # skill_candidate_skipped 事件（不是因为「没提取到候选」而静默）。
    scope = classify_request_scope(messages)
    if not scope["learnable"]:
        result = {
            "ok": True,
            "action": "discard",
            "skill": "",
            "written": False,
            "changed": False,
            "one_off": True,
            "reason": str(scope["reason"]),
            "scope": {
                "hard": scope["hard"],
                "soft": scope["soft"],
                "durable": scope["durable"],
                "last_user": str(scope["last_user"])[:200],
            },
            "decision": {
                "action": "discard",
                "reason": str(scope["reason"]),
                "source": "request_scope",
            },
        }
        record_online_provenance(
            action="discard",
            result=result,
            messages=messages,
            retrieved_reference=retrieved_reference,
            decision=result["decision"],
        )
        return result

    try:
        candidate = await extract_online_skill_candidate(
            messages=messages,
            side_query=side_query,
            retrieved_reference=retrieved_reference,
            hint=hint,
            source_facts=source_facts,
        )
    except Exception as exc:
        result = {"ok": False, "action": "failed", "error": f"{type(exc).__name__}: {exc}"}
        record_online_provenance(
            action="failed",
            result=result,
            messages=messages,
            retrieved_reference=retrieved_reference,
            error=result["error"],
        )
        return result

    if candidate is None:
        result = {"ok": True, "action": "none"}
        record_online_provenance(
            action="none",
            result=result,
            messages=messages,
            retrieved_reference=retrieved_reference,
        )
        return result

    try:
        result = await maintain_online_skill_candidate(
            candidate=candidate,
            side_query=side_query,
            retrieved_reference=retrieved_reference,
            confirm_write=confirm_write,
            target=target,
            source_facts=source_facts,
        )
    except Exception as exc:
        result = {"ok": False, "action": "failed", "skill": candidate.name, "error": str(exc)}

    record_online_provenance(
        action=str(result.get("action") or "none"),
        skill_name=str(result.get("skill") or candidate.name),
        result=result,
        messages=messages,
        retrieved_reference=retrieved_reference,
        decision=result.get("decision") if isinstance(result.get("decision"), dict) else None,
        error="" if result.get("ok") else str(result.get("error") or ""),
    )
    return result


async def judge_retrieved_skill_usage(
    *,
    hits: list[dict[str, Any]],
    user_message: str,
    assistant_text: str,
    side_query: SideQuery | None = None,
) -> list[dict[str, Any]]:
    if not hits:
        return []
    if side_query is None:
        assistant_lower = assistant_text.lower()
        return [
            {
                "name": hit.get("name", ""),
                "source": hit.get("source", ""),
                "skill_dir": hit.get("skill_dir", ""),
                "retrieved": True,
                "relevant": False,
                "used": str(hit.get("name", "")).lower() in assistant_lower,
                "score": float(hit.get("score", 0.0)),
                "reason": "heuristic fallback",
            }
            for hit in hits
        ]

    system = (
        "Judge whether retrieved skills were relevant to the user request and actually used in the assistant reply.\n"
        "Output ONLY strict JSON: {\"judgments\":[{\"name\":\"...\",\"relevant\":true|false,\"used\":true|false,\"reason\":\"short\"}]}.\n"
        "A skill is used only if the reply follows its distinctive workflow or policy, not merely because it was retrieved."
    )
    payload = {"user_message": user_message, "assistant_reply": assistant_text, "retrieved_skills": hits}
    parsed = _parse_json_object(await side_query(system, json.dumps(payload, ensure_ascii=False)))
    raw_judgments = parsed.get("judgments") if isinstance(parsed.get("judgments"), list) else []
    by_name = {str(item.get("name") or ""): item for item in raw_judgments if isinstance(item, dict)}
    judgments: list[dict[str, Any]] = []
    for hit in hits:
        name = str(hit.get("name") or "")
        raw = by_name.get(name, {})
        judgments.append(
            {
                "name": name,
                "source": hit.get("source", ""),
                "skill_dir": hit.get("skill_dir", ""),
                "retrieved": True,
                "relevant": bool(raw.get("relevant")),
                "used": bool(raw.get("used")),
                "score": float(hit.get("score", 0.0)),
                "reason": str(raw.get("reason") or ""),
            }
        )
    return judgments
