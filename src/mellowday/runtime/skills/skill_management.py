"""技能管理：查看、停用/恢复、版本历史与版本回退。

本模块只负责把已有机制接到用户可操作的入口上，不另造存储：

* 技能仍然以 <skills_dir>/<slug>/SKILL.md 为唯一存在形式（见 mellowday.paths.skills_dir）。
* **停用** = 把整个技能目录移动到归档目录 <skills_archive_dir>/<slug>-<时间戳>/
  （与既有的自动剪枝 _maybe_prune_stale_skill 同一命名约定）。归档目录是技能根目录的
  直接子目录且自身没有 SKILL.md，因此 discover_skills 不会加载它：停用天然影响检索与
  描述注入，不需要第二个「禁用名单」。
* **恢复** = 把归档目录移动回 <skills_dir>/<slug>/，并刷新发现缓存。
* **版本** 复用演化模块已有的两份记录：当前版本在 SKILL.md 的 frontmatter，历史版本是
  <evolution_dir>/history/<slug>.jsonl 中由 evolve_skill_file 写入的整份文件快照
  （content 字段）。

规则正文的查看与编辑（第三轮 F 项，2026-09-19 新增）
---------------------------------------------------

* get_skill_detail：读当前规则正文与演化溯源；停用中的技能也能看。
* update_skill：**完整替换**式编辑（以用户提交的正文为准，不做规则级合并），写入复用
  evolve_skill_file——整份文件快照进历史 + 补丁位 +1 + 事件日志，因此编辑天然可回退，
  没有第二套存储；没有实质变化时不写文件、不升版本。
* get_skill_version_content：读任意历史版本的正文（当前版本读 SKILL.md，其余读历史
  快照的 content 字段）。

版本回退语义（选定一种，测试与网页层都依赖它）
------------------------------------------------

restore_skill_version **把指定历史版本的元数据与正文写回 SKILL.md，并作为新版本记录**：
版本号在当前版本上做补丁位 +1（复用演化模块的 _bump_patch），同时写入 frontmatter
restored-from（被回退到的版本）与 restored-at；覆盖之前先把当前内容作为快照追加进历史
文件，因此回退本身也可再次回退。版本序列只增不减，list_skill_versions 会看到一条内容
等同旧版本的新条目，不会出现两个同号版本。

失败约定（选定一种，网页层据此映射状态码）
------------------------------------------

* 返回 dict 的接口（disable_skill / enable_skill / restore_skill_version）**不抛异常**：
  域内失败统一返回 {"ok": False, "error_code": ..., "error": ...}。
* list_skill_versions 必须返回列表，未知技能名抛出 UnknownSkillError
  （SkillManagementError 的子类，继承 ValueError）。
* list_skills 永不抛异常。

error_code 取值：invalid_name / version_required / skill_not_found / version_not_found /
skill_disabled / archive_failed / restore_failed。

所有文件 IO 都显式使用 encoding="utf-8"（本机默认编码为 cp936，中文技能名/描述必须无损往返）。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any

from ... import paths
from .frontmatter import format_frontmatter, parse_frontmatter
from .instruction_merge import split_evolution_notes
from .skill_evolution import (
    HISTORY_DIR,
    USAGE_LOG,
    # 下面几个是本包内部辅助函数：复用它们才能保证归档命名、版本号递增与事件日志
    # 和既有演化、剪枝机制完全一致，而不是各写一套。
    _append_jsonl,
    _bump_patch,
    _safe_skill_slug,
    evolve_skill_file,
    get_evolution_dir,
)
from .skills import discover_skills, reset_skill_cache

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class SkillManagementError(ValueError):
    """技能管理域内错误；网页层把基类映射为 400。"""

    error_code = "invalid_name"


class UnknownSkillError(SkillManagementError):
    """技能既不在技能根目录也不在归档目录；网页层映射为 404。"""

    error_code = "skill_not_found"


def _utc_now() -> str:
    return time.strftime(TIMESTAMP_FORMAT, time.gmtime())


def _clean(value: object) -> str:
    return str(value if value is not None else "").strip()


def _failure(message: str, error_code: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error_code": error_code, "error": message, **extra}


def _read_meta(skill_file: Path) -> dict[str, str]:
    try:
        return dict(parse_frontmatter(skill_file.read_text(encoding="utf-8")).meta)
    except Exception:
        return {}


def _skill_name(skill_file: Path, meta: dict[str, str]) -> str:
    return _clean(meta.get("name")) or skill_file.parent.name


def _skill_files(root: Path) -> list[Path]:
    """列出 root 下直接子目录中的 SKILL.md（与 discover_skills 的读取范围一致）。"""
    if not root.is_dir():
        return []
    found: list[Path] = []
    for entry in sorted(root.iterdir()):
        skill_file = entry / "SKILL.md"
        if entry.is_dir() and skill_file.is_file():
            found.append(skill_file)
    return found


def _skill_timestamp(meta: dict[str, str], skill_file: Path) -> str:
    for key in ("updated-at", "restored-at", "last-evolved", "created-at"):
        value = _clean(meta.get(key))
        if value:
            return value
    try:
        return time.strftime(TIMESTAMP_FORMAT, time.gmtime(skill_file.stat().st_mtime))
    except OSError:
        return ""


def _find_active(name: str) -> Path | None:
    """在技能根目录里按名字找 SKILL.md（frontmatter name 优先，回退目录名）。"""
    wanted = _clean(name)
    if not wanted:
        return None
    for skill_file in _skill_files(paths.skills_dir()):
        if _skill_name(skill_file, _read_meta(skill_file)) == wanted:
            return skill_file
    return None


def _find_archived(name: str) -> Path | None:
    """在归档目录里按名字找 SKILL.md；同名多个时取最后归档的一个。"""
    wanted = _clean(name)
    if not wanted:
        return None
    slug = _safe_skill_slug(wanted)
    matches: list[Path] = []
    for skill_file in _skill_files(paths.skills_archive_dir()):
        resolved = _skill_name(skill_file, _read_meta(skill_file))
        dir_name = skill_file.parent.name
        # frontmatter 里的 name 是权威；目录名（<slug>-<时间戳>）只作为文件损坏时的兜底。
        if resolved == wanted or (slug and dir_name.startswith(f"{slug}-")):
            matches.append(skill_file)
    if not matches:
        return None
    matches.sort(key=lambda path: (path.parent.name, str(path)))
    return matches[-1]


def _unique_dir(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    slug = _safe_skill_slug(name)
    candidate = root / slug
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{slug}-{suffix}"
    return candidate


def _unique_archive_dir(name: str) -> Path:
    root = paths.skills_archive_dir()
    root.mkdir(parents=True, exist_ok=True)
    slug = _safe_skill_slug(name)
    base = f"{slug}-{int(time.time())}"
    candidate = root / base
    suffix = 1
    while candidate.exists():
        suffix += 1
        candidate = root / f"{base}-{suffix}"
    return candidate


def _history_rows(name: str) -> list[dict[str, Any]]:
    """读出该技能在演化历史里的全部快照（可能跨多个 history 文件）。"""
    root = get_evolution_dir() / HISTORY_DIR
    if not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if not isinstance(row, dict):
                continue
            if _clean(row.get("skill")) != _clean(name):
                continue
            if not _clean(row.get("content")):
                continue
            rows.append({"row": row, "path": path, "line": index})
    return rows


def _version_key(version: str) -> tuple[int, ...] | None:
    parts = _clean(version).split(".")
    if parts and all(part.isdigit() for part in parts):
        return tuple(int(part) for part in parts)
    return None


def _entry(name: str, skill_file: Path, *, enabled: bool, source: str) -> dict[str, Any]:
    meta = _read_meta(skill_file)
    return {
        "name": name,
        "description": _clean(meta.get("description")),
        "version": _clean(meta.get("version")),
        "enabled": enabled,
        "source": source,
        "path": str(skill_file),
        "skill_dir": str(skill_file.parent),
        "archived_to": "" if enabled else str(skill_file.parent),
        "updated_at": _skill_timestamp(meta, skill_file),
    }


def list_skills() -> list[dict[str, Any]]:
    """列出全部技能（含已停用的），每项含 name/description/version/enabled/source/path。

    读取前会刷新发现缓存，保证管理入口看到的是磁盘现状；已停用的技能从归档目录读取，
    enabled 为 False、archived_to 指向归档目录。本函数永不抛异常。
    """
    reset_skill_cache()
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for skill in discover_skills():
        name = _clean(skill.name)
        if not name or name in seen:
            continue
        skill_dir = Path(skill.skill_dir) if skill.skill_dir else None
        skill_file = skill_dir / "SKILL.md" if skill_dir is not None else None
        if skill_file is None or not skill_file.is_file():
            continue
        seen.add(name)
        entries.append(_entry(name, skill_file, enabled=True, source=_clean(skill.source) or "project"))
    for skill_file in _skill_files(paths.skills_archive_dir()):
        name = _skill_name(skill_file, _read_meta(skill_file))
        if not name or name in seen:
            continue
        seen.add(name)
        entries.append(_entry(name, skill_file, enabled=False, source="project"))
    entries.sort(key=lambda item: (0 if item.get("enabled") else 1, str(item.get("name") or "")))
    return entries


def disable_skill(name: str) -> dict[str, Any]:
    """停用技能：把技能目录移入归档目录，使其不再出现在发现、检索与描述结果中。

    返回 {"ok": True, "name", "archived_to", "path", "changed"}；重复停用是幂等的
    （changed 为 False，archived_to 指向已有归档）。失败返回
    {"ok": False, "error_code", "error"}，不抛异常。
    """
    resolved = _clean(name)
    if not resolved:
        return _failure("skill name is required", "invalid_name")
    active = _find_active(resolved)
    if active is None:
        archived = _find_archived(resolved)
        if archived is not None:
            return {
                "ok": True,
                "name": resolved,
                "archived_to": str(archived.parent),
                "path": str(archived),
                "changed": False,
            }
        return _failure(f"Skill not found: {resolved}", "skill_not_found", name=resolved)

    skill_dir = active.parent
    destination = _unique_archive_dir(resolved)
    try:
        shutil.move(str(skill_dir), str(destination))
    except Exception as exc:
        return _failure(f"could not archive skill {resolved}: {exc}", "archive_failed", name=resolved)

    reset_skill_cache()
    _append_jsonl(
        get_evolution_dir() / USAGE_LOG,
        {
            "event": "disable",
            "time": _utc_now(),
            "actor": "user",
            "skill": resolved,
            "from": str(skill_dir),
            "to": str(destination),
        },
    )
    return {
        "ok": True,
        "name": resolved,
        "archived_to": str(destination),
        "path": str(destination / "SKILL.md"),
        "changed": True,
    }


def enable_skill(name: str) -> dict[str, Any]:
    """恢复被停用的技能：把归档目录移回技能根目录，重新进入发现与检索。

    返回 {"ok": True, "name", "path", "changed"}；已在启用状态或重复恢复是幂等的
    （changed 为 False）。失败返回 {"ok": False, "error_code", "error"}，不抛异常。
    """
    resolved = _clean(name)
    if not resolved:
        return _failure("skill name is required", "invalid_name")
    active = _find_active(resolved)
    if active is not None:
        return {"ok": True, "name": resolved, "path": str(active), "changed": False}

    archived = _find_archived(resolved)
    if archived is None:
        return _failure(f"Skill not found: {resolved}", "skill_not_found", name=resolved)

    source_dir = archived.parent
    destination = _unique_dir(paths.skills_dir(), resolved)
    try:
        shutil.move(str(source_dir), str(destination))
    except Exception as exc:
        return _failure(f"could not restore skill {resolved}: {exc}", "restore_failed", name=resolved)

    reset_skill_cache()
    _append_jsonl(
        get_evolution_dir() / USAGE_LOG,
        {
            "event": "enable",
            "time": _utc_now(),
            "actor": "user",
            "skill": resolved,
            "from": str(source_dir),
            "to": str(destination),
        },
    )
    return {"ok": True, "name": resolved, "path": str(destination / "SKILL.md"), "changed": True}


def list_skill_versions(name: str) -> list[dict[str, Any]]:
    """列出该技能的全部版本（新在前），每项含 version/updated_at/path/current/source。

    当前版本来自 SKILL.md，历史版本来自演化历史里的整份文件快照（path 指向该 history
    文件）。技能已停用时同样可查。未知技能名抛出 UnknownSkillError（ValueError 子类）。
    """
    resolved = _clean(name)
    if not resolved:
        raise SkillManagementError("skill name is required")
    active = _find_active(resolved)
    archived = None if active is not None else _find_archived(resolved)
    target = active or archived
    if target is None:
        raise UnknownSkillError(f"Skill not found: {resolved}")

    meta = _read_meta(target)
    items: list[dict[str, Any]] = [
        {
            "version": _clean(meta.get("version")),
            "updated_at": _skill_timestamp(meta, target),
            "path": str(target),
            "current": True,
            "source": "active" if active is not None else "archived",
        }
    ]
    for entry in _history_rows(resolved):
        row = entry["row"]
        items.append(
            {
                "version": _clean(row.get("version")),
                "updated_at": _clean(row.get("time")),
                "path": str(entry["path"]),
                "current": False,
                "source": "history",
            }
        )

    # 同一个版本号只保留最先出现的一条（当前版本优先），再按版本号从新到旧排序。
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item["version"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)

    def sort_key(indexed: tuple[int, dict[str, Any]]) -> tuple[int, tuple[int, ...], str, int]:
        index, item = indexed
        parsed = _version_key(str(item.get("version") or ""))
        return (
            1 if parsed is not None else 0,
            parsed or (),
            str(item.get("updated_at") or ""),
            -index,
        )

    ordered = sorted(enumerate(unique), key=sort_key, reverse=True)
    return [item for _, item in ordered]


def _find_snapshot(name: str, version: str) -> dict[str, Any] | None:
    """在演化历史里找出指定版本的最后一份快照。"""
    wanted = _clean(version)
    match: dict[str, Any] | None = None
    for entry in _history_rows(name):
        if _clean(entry["row"].get("version")) != wanted:
            continue
        match = entry
    return match


def restore_skill_version(name: str, version: str) -> dict[str, Any]:
    """版本回退：把指定历史版本的内容写回 SKILL.md，并记录为**新版本**（补丁位 +1）。

    语义见模块 docstring：restored-from 记录被回退到的版本，覆盖前会先把当前内容追加为
    历史快照，所以回退可再次回退；版本号只增不减。返回
    {"ok": True, "name", "version"(新版本号), "restored_from"(请求的旧版本), "path", "changed"}；
    请求的版本就是当前版本时不改动文件（changed 为 False）。失败返回
    {"ok": False, "error_code", "error"}（含 skill_not_found / version_not_found /
    skill_disabled），不抛异常。
    """
    resolved = _clean(name)
    wanted = _clean(version)
    if not resolved:
        return _failure("skill name is required", "invalid_name")
    if not wanted:
        return _failure("version is required", "version_required", name=resolved)

    active = _find_active(resolved)
    if active is None:
        if _find_archived(resolved) is not None:
            return _failure(
                f"Skill is disabled: {resolved}; enable it before restoring a version",
                "skill_disabled",
                name=resolved,
            )
        return _failure(f"Skill not found: {resolved}", "skill_not_found", name=resolved)

    try:
        current_raw = active.read_text(encoding="utf-8")
    except OSError as exc:
        return _failure(f"could not read skill {resolved}: {exc}", "restore_failed", name=resolved)
    current_parsed = parse_frontmatter(current_raw)
    current_version = _clean(current_parsed.meta.get("version"))

    if current_version and wanted == current_version:
        return {
            "ok": True,
            "name": resolved,
            "version": current_version,
            "restored_from": current_version,
            "path": str(active),
            "changed": False,
        }

    snapshot = _find_snapshot(resolved, wanted)
    if snapshot is None:
        return _failure(
            f"Unknown version for skill {resolved}: {wanted}", "version_not_found", name=resolved
        )

    history_path = get_evolution_dir() / HISTORY_DIR / f"{_safe_skill_slug(resolved)}.jsonl"
    # 覆盖之前先留一份当前内容的快照：回退本身也必须可回退。
    _append_jsonl(
        history_path,
        {
            "time": _utc_now(),
            "event": "snapshot",
            "actor": "user",
            "skill": resolved,
            "file": str(active),
            "version": current_version,
            "lesson": f"restore to {wanted}",
            "rationale": f"snapshot taken before restoring version {wanted}",
            "content": current_raw,
        },
    )

    restored = parse_frontmatter(str(snapshot["row"].get("content") or ""))
    meta = dict(restored.meta)
    new_version = _bump_patch(current_version)
    meta["name"] = resolved
    meta["version"] = new_version
    meta["restored-from"] = wanted
    meta["restored-at"] = _utc_now()
    meta["updated-at"] = meta["restored-at"]
    if _clean(current_parsed.meta.get("evolution-count")):
        # 演化次数属于技能自身的累计量，回退内容不倒退这个计数。
        meta["evolution-count"] = _clean(current_parsed.meta.get("evolution-count"))
    try:
        active.write_text(format_frontmatter(meta, restored.body), encoding="utf-8")
    except OSError as exc:
        return _failure(f"could not write skill {resolved}: {exc}", "restore_failed", name=resolved)

    reset_skill_cache()
    _append_jsonl(
        get_evolution_dir() / USAGE_LOG,
        {
            "event": "restore",
            "time": _utc_now(),
            "actor": "user",
            "skill": resolved,
            "file": str(active),
            "version": new_version,
            "restored_from": wanted,
            "history": str(history_path),
        },
    )
    return {
        "ok": True,
        "name": resolved,
        "version": new_version,
        "restored_from": wanted,
        "path": str(active),
        "changed": True,
    }


# ------------------------------------------------------------------ 规则正文查看与编辑


def _resolve_skill(name: str) -> tuple[Path | None, bool]:
    """按名字解析技能文件：先找启用中的，再找已停用的；返回 (文件, 是否启用)。"""
    active = _find_active(name)
    if active is not None:
        return active, True
    return _find_archived(name), False


def _body_parts(skill_file: Path) -> tuple[dict[str, str], str, str]:
    """读技能文件，返回 (frontmatter, 规则正文, 演化溯源小节)。"""
    parsed = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
    meta = {str(key): str(value) for key, value in dict(parsed.meta).items()}
    rules, notes = split_evolution_notes(parsed.body)
    return meta, rules, notes


def _normalize_rules(text: str) -> str:
    lines = [line.rstrip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(lines).strip()


def get_skill_detail(name: str) -> dict[str, Any]:
    """读一个技能的完整信息：元信息 + 当前规则正文 + 演化溯源。

    停用中的技能同样可读（enabled=False）。未知技能名返回
    {"ok": False, "error_code": "skill_not_found", ...} 而不是抛异常，
    网页层据此映射 404。
    """
    resolved = _clean(name)
    if not resolved:
        return _failure("skill name is required", "invalid_name")
    skill_file, enabled = _resolve_skill(resolved)
    if skill_file is None:
        return _failure(f"Skill not found: {resolved}", "skill_not_found", name=resolved)
    try:
        meta, rules, notes = _body_parts(skill_file)
    except OSError as exc:
        return _failure(f"could not read skill {resolved}: {exc}", "read_failed", name=resolved)
    return {
        "ok": True,
        "name": _skill_name(skill_file, meta),
        "description": _clean(meta.get("description")),
        "when_to_use": _clean(meta.get("when-to-use")),
        "version": _clean(meta.get("version")),
        "enabled": enabled,
        "source": "project",
        "path": str(skill_file),
        "skill_dir": str(skill_file.parent),
        "tags": _clean(meta.get("tags")),
        "updated_at": _skill_timestamp(meta, skill_file),
        "evolution_count": _clean(meta.get("evolution-count")),
        "body": rules,
        "notes": notes,
    }


def update_skill(
    name: str,
    *,
    description: str | None = None,
    when_to_use: str | None = None,
    instructions: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """编辑技能：复用演化模块的版本机制（整份文件快照 + 补丁位 +1），不另造存储。

    语义（网页层与测试都依赖它）：

    * instructions 是**完整替换**的规则正文——人工编辑以提交内容为准，不做规则级
      合并；空串返回 empty_instructions，不允许把技能改成没有规则的空壳；
    * description / when_to_use 传 None 或空串表示不修改；
    * 既有 ## Evolution Notes 溯源不会被编辑掉，仍接在新正文之后，编辑动作本身也会
      作为一条 note 追加进去；
    * 没有任何实质变化时 changed 为 False，不写文件、不升版本；
    * 已停用的技能要先 enable 再编辑（与版本回退同一套语义，error_code 为 skill_disabled）。

    返回 {"ok": True, "name", "version", "previous_version", "changed", "path"}；
    失败返回 {"ok": False, "error_code", "error"}，不抛异常。
    """
    resolved = _clean(name)
    if not resolved:
        return _failure("skill name is required", "invalid_name")
    active = _find_active(resolved)
    if active is None:
        if _find_archived(resolved) is not None:
            return _failure(
                f"Skill is disabled: {resolved}; enable it before editing",
                "skill_disabled",
                name=resolved,
            )
        return _failure(f"Skill not found: {resolved}", "skill_not_found", name=resolved)

    try:
        meta, current_rules, notes = _body_parts(active)
    except OSError as exc:
        return _failure(f"could not read skill {resolved}: {exc}", "read_failed", name=resolved)

    new_rules = current_rules
    if instructions is not None:
        submitted = _normalize_rules(instructions)
        if not submitted:
            return _failure(
                "instructions must not be empty: a skill needs at least one rule",
                "empty_instructions",
                name=resolved,
            )
        new_rules = submitted

    current_description = _clean(meta.get("description"))
    current_when = _clean(meta.get("when-to-use"))
    new_description = _clean(description) or current_description
    new_when = _clean(when_to_use) or current_when
    current_version = _clean(meta.get("version"))

    if new_rules == current_rules and new_description == current_description and new_when == current_when:
        return {
            "ok": True,
            "name": resolved,
            "version": current_version,
            "previous_version": current_version,
            "changed": False,
            "path": str(active),
        }

    body = new_rules if not notes else new_rules.rstrip() + "\n\n" + notes.strip() + "\n"
    result = evolve_skill_file(
        skill_name=resolved,
        lesson=_clean(note) or "管理页手工编辑规则",
        rationale="user edited the skill in the management page",
        target="active",
        active_dir=str(active.parent),
        actor="user",
        instructions=body,
        description=new_description if new_description != current_description else "",
        when_to_use=new_when if new_when != current_when else "",
    )
    if not result.get("ok"):
        return _failure(str(result.get("error") or "could not update skill"), "update_failed", name=resolved)

    reset_skill_cache()
    return {
        "ok": True,
        "name": resolved,
        "version": _clean(result.get("version")) or _bump_patch(current_version),
        "previous_version": current_version,
        "changed": True,
        "path": str(active),
        "history": str(result.get("history") or ""),
    }


def get_skill_version_content(name: str, version: str) -> dict[str, Any]:
    """读某个版本的规则正文：当前版本读 SKILL.md，历史版本读演化快照里的整份文件。

    返回 {"ok": True, "name", "version", "current", "updated_at", "body", "notes",
    "enabled"}；未知技能给 skill_not_found，未知版本给 version_not_found，
    不抛异常。停用中的技能同样可查（与 list_skill_versions 一致）。
    """
    resolved = _clean(name)
    wanted = _clean(version)
    if not resolved:
        return _failure("skill name is required", "invalid_name")
    if not wanted:
        return _failure("version is required", "version_required", name=resolved)

    active = _find_active(resolved)
    archived = None if active is not None else _find_archived(resolved)
    target = active or archived
    if target is None:
        return _failure(f"Skill not found: {resolved}", "skill_not_found", name=resolved)

    try:
        meta, rules, notes = _body_parts(target)
    except OSError as exc:
        return _failure(f"could not read skill {resolved}: {exc}", "read_failed", name=resolved)

    if wanted == _clean(meta.get("version")):
        return {
            "ok": True,
            "name": resolved,
            "version": wanted,
            "current": True,
            "enabled": active is not None,
            "updated_at": _skill_timestamp(meta, target),
            "body": rules,
            "notes": notes,
            "path": str(target),
        }

    snapshot = _find_snapshot(resolved, wanted)
    if snapshot is None:
        return _failure(
            f"Unknown version for skill {resolved}: {wanted}", "version_not_found", name=resolved
        )
    parsed = parse_frontmatter(str(snapshot["row"].get("content") or ""))
    snap_rules, snap_notes = split_evolution_notes(parsed.body)
    return {
        "ok": True,
        "name": resolved,
        "version": wanted,
        "current": False,
        "enabled": active is not None,
        "updated_at": _clean(snapshot["row"].get("time")),
        "body": snap_rules,
        "notes": snap_notes,
        "path": str(snapshot["path"]),
    }
