"""Business tools the MellowDay assistant can call.

Two entry points are exported:

* tool_definitions() returns JSON-schema descriptions of every tool.
* execute_tool(store, name, arguments) runs one tool against a
  mellowday.storage.store.Store and always answers with a JSON string.

Remembered facts have exactly one source: the "memories" records in SQLite.
Markdown memory files are not a fact source and never feed recall. The runtime
takes its candidates from build_fact_provider(store) (see CONTRACTS 6quater).

Capabilities are limited to the assistant's own records - todos, calendar
events, reminders, notes and remembered facts - plus a clock reading.  There is
deliberately no shell, filesystem or code-execution tool here, and nothing in
this module reads or writes files directly: every change goes through the
transactional store.

Result envelope::

    {"ok": true, ...}                       on success
    {"ok": false, "error": "...", ...}      on any failure

Failures are reported as data.  Invalid arguments, missing fields, unknown
tools and unknown record kinds never raise out of execute_tool.
"""
from __future__ import annotations

import copy
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from mellowday.runtime.memory import score_facts
from mellowday.storage.store import DEFAULT_STATUS, DONE_STATUSES, MEMORY_STATUSES, Store
from mellowday.timefmt import to_local_iso

__all__ = [
    "tool_definitions",
    "execute_tool",
    "build_fact_provider",
    "supersede_rule_facts",
    "SUPERSEDED_BY_SKILL",
]

MEMORY_KINDS: tuple[str, ...] = ("fact", "preference", "important")

#: 被技能取代的事实的记忆状态（CONTRACTS 6quater.1）。
#: Store 的 DONE_STATUSES 已经把它算作「不再有效」，因此 include_done=False 的召回与
#: search_records 都不会再返回它；记录本身保留，管理面（include_done=True）仍可查看。
SUPERSEDED_BY_SKILL = "superseded"

_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class ToolArgumentError(ValueError):
    """Raised for invalid tool arguments; converted into a JSON error reply."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------- schema

_ID_SCHEMA = {"type": "string", "minLength": 1, "description": "记录 id"}
_TITLE_SCHEMA = {"type": "string", "minLength": 1, "description": "标题"}
_DETAIL_SCHEMA = {
    "type": "string",
    "description": "详细内容；修改时传空字符串表示清空该字段（与管理页「清空备注」语义一致）",
}
_DUE_SCHEMA = {
    "type": "string",
    "description": (
        "ISO 8601 时间，例如 2026-09-20T09:00:00+08:00；只写日期时按当天零点处理。"
        "修改时传 null 或空字符串表示清空该时间。"
        "返回值中的 due_at 是 UTC，due_at_local 是同一时刻的本地时间；"
        "向用户展示时间必须使用 due_at_local，直接引用 due_at 会差一个时区偏移。"
    ),
}
_STATUS_SCHEMA = {"type": "string", "description": "状态，例如 open/done、scheduled/cancelled"}
_META_SCHEMA = {
    "type": "object",
    "description": "附加键值数据，随记录一起保存",
    "additionalProperties": True,
}
_SOURCE_SCHEMA = {"type": "string", "description": "记录来源，默认 assistant"}
_INCLUDE_DONE_SCHEMA = {
    "type": "boolean",
    "description": "是否包含已完成或已失效的记录，默认 true",
}
_LIMIT_SCHEMA = {
    "type": "integer",
    "minimum": 1,
    "maximum": 200,
    "description": "最多返回条数",
}


def _object(
    properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


# ─── 状态词：每个类型自己的取值 + 通用别名（t22 / N6）────────────────────────
# 背景（真实事故）：list_calendar(status="open") 曾静默返回空集，模型据此对用户
# 说「没有日程」，而 09:30 的每日站会确实存在。现在的规则：
#   1) 先认通用词（未完成 / 已完成），并回显实际应用的过滤；
#   2) 再按该类型真实存在的状态词精确匹配；
#   3) 两者都不是 → 结构化错误并列出合法取值，**绝不静默返回空集**。

#: 「未完成」的通用词（等价 include_done=False）。
_NOT_DONE_ALIASES = frozenset(
    {"open", "pending", "active", "todo", "not-done", "not_done", "未完成", "进行中", "待办", "待处理"}
)
#: 「已完成」的通用词（等价该类型的完成集合）。
_DONE_ALIASES = frozenset({"done", "completed", "complete", "finished", "已完成", "完成"})

#: 结果 status_filter.applied 的两个语义取值。
NOT_DONE_FILTER = "not-done"
DONE_FILTER = "done"


def _known_statuses(kind: str) -> tuple[str, ...]:
    """该类型真实存在的状态词。

    直接取自 Store 的默认状态与完成集合，避免这里再抄一份而随时间漂移。
    """
    return tuple(sorted({DEFAULT_STATUS[kind], *DONE_STATUSES[kind]}))


def _status_alias(value: str) -> str | None:
    """通用状态词 → 语义别名；不是通用词时返回 None。"""
    text = str(value or "").strip().casefold()
    if text in _NOT_DONE_ALIASES:
        return NOT_DONE_FILTER
    if text in _DONE_ALIASES:
        return DONE_FILTER
    return None


def _status_schema(kind: str) -> dict[str, Any]:
    """list 工具自己的 status 描述：按类型列出状态词与通用词。"""
    known = "、".join(_known_statuses(kind))
    return {
        "type": "string",
        "description": (
            f"按状态过滤。{kind} 的状态词：{known}。"
            "通用词也可以：open/pending/active/未完成/进行中 表示「未完成」，"
            "done/completed/已完成 表示「已完成」；工具会在 status_filter 里回显实际应用的过滤。"
            "与 include_done 同时给出时取交集。不传 status 时按 include_done 返回。"
        ),
    }


def _list_props(kind: str) -> dict[str, Any]:
    return {
        "include_done": _INCLUDE_DONE_SCHEMA,
        "status": _status_schema(kind),
        "limit": _LIMIT_SCHEMA,
    }


_CREATE_PROPS = {
    "title": _TITLE_SCHEMA,
    "detail": _DETAIL_SCHEMA,
    "due_at": _DUE_SCHEMA,
    "status": _STATUS_SCHEMA,
    "source": _SOURCE_SCHEMA,
    "meta": _META_SCHEMA,
}
_UPDATE_PROPS = {"id": _ID_SCHEMA, **_CREATE_PROPS}


def _tool(name: str, description: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "description": description, "input_schema": schema}


_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    # ------------------------------------------------------------------ 待办
    _tool(
        "list_todos",
        "列出用户的待办事项，可按状态过滤、限制条数。",
        _object(_list_props("todos")),
    ),
    _tool(
        "create_todo",
        "新建一条待办事项；title 必填，可用 due_at 指定截止时间。",
        _object(_CREATE_PROPS, ["title"]),
    ),
    _tool(
        "update_todo",
        "修改一条待办事项的标题、内容、截止时间或状态（如标记 done）；"
        "detail 传空字符串、due_at 传 null 表示清空该字段。",
        _object(_UPDATE_PROPS, ["id"]),
    ),
    _tool(
        "delete_todo",
        "删除一条待办事项，返回被删除的记录和可用于撤销的 operation_id。",
        _object({"id": _ID_SCHEMA}, ["id"]),
    ),
    # ------------------------------------------------------------------ 日历
    _tool(
        "list_calendar",
        "列出日历事件，可按状态过滤、限制条数。",
        _object(_list_props("calendar")),
    ),
    _tool(
        "create_calendar_event",
        "新建一条日历事件；title 必填，due_at 表示事件开始时间。",
        _object(_CREATE_PROPS, ["title"]),
    ),
    _tool(
        "update_calendar_event",
        "修改一条日历事件的时间、标题或状态；due_at 传 null 表示清空该时间。",
        _object(_UPDATE_PROPS, ["id"]),
    ),
    _tool(
        "delete_calendar_event",
        "删除一条日历事件，返回被删除的记录和可用于撤销的 operation_id。",
        _object({"id": _ID_SCHEMA}, ["id"]),
    ),
    # ------------------------------------------------------------------ 提醒
    _tool(
        "list_reminders",
        "列出提醒，可按状态过滤、限制条数。",
        _object(_list_props("reminders")),
    ),
    _tool(
        "create_reminder",
        "新建一条提醒；title 必填，due_at 表示提醒时间。",
        _object(_CREATE_PROPS, ["title"]),
    ),
    _tool(
        "update_reminder",
        "修改一条提醒的时间、内容或状态；detail 传空字符串、due_at 传 null 表示清空该字段。",
        _object(_UPDATE_PROPS, ["id"]),
    ),
    _tool(
        "delete_reminder",
        "删除一条提醒，返回被删除的记录和可用于撤销的 operation_id。",
        _object({"id": _ID_SCHEMA}, ["id"]),
    ),
    # ------------------------------------------------------------------ 笔记
    _tool(
        "list_notes",
        "列出笔记，可按状态过滤、限制条数。",
        _object(_list_props("notes")),
    ),
    _tool(
        "create_note",
        "新建一条笔记；title 必填，正文写在 detail 中。",
        _object(_CREATE_PROPS, ["title"]),
    ),
    _tool(
        "update_note",
        "修改一条笔记的标题、正文或状态；detail 传空字符串表示清空正文。",
        _object(_UPDATE_PROPS, ["id"]),
    ),
    _tool(
        "delete_note",
        "删除一条笔记，返回被删除的记录和可用于撤销的 operation_id。",
        _object({"id": _ID_SCHEMA}, ["id"]),
    ),
    # ------------------------------------------------------------------ 记忆
    _tool(
        "remember_fact",
        "记住用户的长期事实或个人偏好（如口味）；要求助理如何规划、排序、输出的流程由在线技能学习提案确认，不能以fact/preference保存。",
        _object(
            {
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "description": "要记住的事实内容",
                },
                "label": {"type": "string", "description": "这条事实的简短标签"},
                "kind": {
                    "type": "string",
                    "enum": [*MEMORY_KINDS, "workflow"],
                    "description": (
                        "fact 客观事实、preference 个人偏好、important 重要信息；"
                        "workflow 表示要求助理如何执行任务的长期流程，工具会拒绝事实写入并提示使用技能。"
                    ),
                },
                "source": _SOURCE_SCHEMA,
                "meta": _META_SCHEMA,
            },
            ["content"],
        ),
    ),
    _tool(
        "recall_memories",
        "检索已记住的用户事实；不传 query 时返回当前全部有效记忆。",
        _object(
            {
                "query": {"type": "string", "description": "检索关键词，留空表示浏览全部"},
                "limit": _LIMIT_SCHEMA,
            }
        ),
    ),
    _tool(
        "update_memory",
        "按用户要求纠正事实、修改标签或状态（active/expired/deleted）。不能用于将记忆迁移为技能；迁移须保留原记录，等待在线技能提案确认并成功写入。",
        _object(
            {
                "id": _ID_SCHEMA,
                "content": {
                    "type": "string",
                    "minLength": 1,
                    "description": "新的记忆内容",
                },
                "label": {"type": "string", "description": "新的简短标签"},
                "status": {
                    "type": "string",
                    "enum": sorted(MEMORY_STATUSES),
                    "description": "记忆状态",
                },
            },
            ["id"],
        ),
    ),
    _tool(
        "forget_memory",
        "仅在用户要求忘记/删除记忆时使用。不得用删除代替迁移为技能：迁移由在线技能确认链处理，调用本工具不会保存技能。返回删除记录和 operation_id。",
        _object({"id": _ID_SCHEMA}, ["id"]),
    ),
    # ---------------------------------------------------------------- 时间参考
    _tool(
        "current_time",
        "获取当前时间，用于推算相对日期（今天、明天、下周等）。",
        _object({}),
    ),
]


def tool_definitions() -> list[dict[str, Any]]:
    """Return a fresh copy of every tool description."""
    return copy.deepcopy(_TOOL_DEFINITIONS)


def build_fact_provider(
    store: Store, *, limit: int = 50
) -> Callable[[str], Awaitable[list[dict]]]:
    """Wrap a Store into the runtime's fact_provider (CONTRACTS 6quater).

    The returned coroutine is what mellowday.runtime.agent.Agent calls at the
    start of every turn. It reads the "memories" records from SQLite - the only
    fact source - with include_done=False so that expired or deleted facts can
    never be recalled, and puts the term hits first. Final selection (count and
    size budgets) is the runtime's job.

    Term matching is language-neutral: Chinese input carries no whitespace, so
    hits are computed from adjacent character pairs instead of space separated
    tokens. When nothing matches, the candidates are still returned in store
    order so the runtime can fall back for a small fact store.

    An *empty* query means "the current active set", and that answer is complete:
    the runtime uses it to decide whether a fact it already showed is still valid
    and can supply source snapshots for an explicitly confirmed skill migration.
    A capped list there would be read as "those facts are gone", so the
    limit only applies to term-matched calls.
    """
    if not isinstance(store, Store):
        raise TypeError("build_fact_provider 需要 Store 实例")

    async def provider(query: str) -> list[dict]:
        records = store.list_records("memories", include_done=False)
        if not records:
            return []
        text = str(query or "").strip()
        if not text:
            return [dict(record) for record in records]
        hits = [record for score, record in score_facts(text, records) if score > 0.0]
        return [dict(record) for record in (hits or records)[:limit]]

    def supersede_rule_facts_hook(
        facts: Sequence[Mapping[str, Any]],
        *,
        skill: str,
        at: str | None = None,
        reason: str = "superseded by skill",
        skill_state: str | None = None,
    ) -> list[dict[str, Any]]:
        """Apply explicitly selected, confirmed source snapshots; never infer overlap.

        The caller must obtain confirmation for the named records and skill.
        Changed or incomplete snapshots are skipped by the storage adapter.
        """
        return supersede_rule_facts(
            store, facts, skill=skill, at=at, reason=reason, skill_state=skill_state
        )

    #provider 上的写回钩子：运行时用 getattr(provider, "supersede_rule_facts") 取用。
    provider.supersede_rule_facts = supersede_rule_facts_hook  # type: ignore[attr-defined]
    return provider


def supersede_rule_facts(
    store: Store,
    facts: Sequence[Mapping[str, Any]],
    *,
    skill: str,
    at: str | None = None,
    reason: str = "superseded by skill",
    skill_state: str | None = None,
) -> list[dict[str, Any]]:
    """Migrate explicitly confirmed source snapshots to the named skill.

    No similarity matching or database-wide selection occurs here. The caller
    supplies the exact records shown for confirmation. Only unchanged active
    snapshots are migrated; the record and provenance remain available to users.
    """
    if not isinstance(store, Store):
        raise TypeError("supersede_rule_facts 需要 Store 实例")
    stamp = at or datetime.now(timezone.utc).isoformat()
    name = str(skill or "").strip()
    if not name:
        return []
    superseded: list[dict[str, Any]] = []
    for fact in facts or ():
        if not isinstance(fact, Mapping):
            continue
        record_id = str(fact.get("id") or "").strip()
        if not record_id:
            continue
        current = store.get_record("memories", record_id)
        if current is None:
            continue
        if str(current.get("status") or "").casefold() != "active":
            continue
        # Confirmation may wait while the user edits the source record. Never
        # migrate its new contents on the strength of an old proposal or ID alone.
        snapshot_fields = ("title", "detail", "meta", "updated_at", "status")
        if any(key not in fact or fact[key] != current.get(key) for key in snapshot_fields):
            continue
        meta = dict(current.get("meta") or {})
        meta["superseded_by_skill"] = name
        meta["superseded_at"] = stamp
        meta["superseded_reason"] = str(reason or "")
        state = str(skill_state or "").strip().lower()
        if state in {"enabled", "disabled"}:
            # Record the state at this explicitly approved migration.
            meta["superseded_skill_state"] = state
        record = store.update_record(
            "memories",
            record_id,
            {"status": SUPERSEDED_BY_SKILL, "meta": meta},
        )
        superseded.append(
            {
                "id": record.get("id"),
                "title": record.get("title"),
                "detail": record.get("detail"),
                "status": record.get("status"),
                "meta": record.get("meta"),
                "operation_id": record.get("operation_id"),
            }
        )
    return superseded


# ---------------------------------------------------------------- arguments

def _require_str(arguments: Mapping[str, Any], name: str) -> str:
    if name not in arguments or arguments[name] is None:
        raise ToolArgumentError("missing_argument", f"缺少必填参数：{name}")
    value = arguments[name]
    if not isinstance(value, str) or not value.strip():
        raise ToolArgumentError("invalid_arguments", f"参数 {name} 必须是非空字符串")
    return value.strip()


def _optional_str(arguments: Mapping[str, Any], name: str) -> str | None:
    if name not in arguments or arguments[name] is None:
        return None
    value = arguments[name]
    if not isinstance(value, str):
        raise ToolArgumentError("invalid_arguments", f"参数 {name} 必须是字符串")
    text = value.strip()
    return text or None


def _optional_bool(arguments: Mapping[str, Any], name: str, *, default: bool) -> bool:
    if name not in arguments or arguments[name] is None:
        return default
    value = arguments[name]
    if not isinstance(value, bool):
        raise ToolArgumentError("invalid_arguments", f"参数 {name} 必须是布尔值")
    return value


def _optional_int(
    arguments: Mapping[str, Any], name: str, *, default: int | None = None
) -> int | None:
    if name not in arguments or arguments[name] is None:
        return default
    value = arguments[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolArgumentError("invalid_arguments", f"参数 {name} 必须是整数")
    if value < 1:
        raise ToolArgumentError("invalid_arguments", f"参数 {name} 必须大于 0")
    return value


def _optional_mapping(arguments: Mapping[str, Any], name: str) -> dict[str, Any] | None:
    if name not in arguments or arguments[name] is None:
        return None
    value = arguments[name]
    if not isinstance(value, Mapping):
        raise ToolArgumentError("invalid_arguments", f"参数 {name} 必须是对象")
    return {str(key): item for key, item in value.items()}


def _plain(record: Mapping[str, Any]) -> dict[str, Any]:
    """Record payload for the model.

    `due_at` stays UTC (that is how it is stored and compared), and
    `due_at_local` carries the same instant in the user's timezone. Every
    user-facing time must be read from `due_at_local`; quoting the UTC field
    shows a time that is wrong by the UTC offset.

    The conversion lives in mellowday.timefmt so the chat surface and the web
    records API cannot drift apart.
    """
    data = {key: value for key, value in record.items() if key != "operation_id"}
    local = to_local_iso(data.get("due_at"))
    if local is not None:
        data["due_at_local"] = local
    return data


def _collect_fields(
    arguments: Mapping[str, Any], *, title_required: bool
) -> dict[str, Any]:
    """Collect the writable fields of a create or update call.

    "Absent" and "present but empty" mean different things: a field that is not
    in the arguments is left untouched by Store.update_record, while an explicit
    empty value clears it. The management page already sends detail: "" and
    due_at: null to clear a field, so the chat tools must accept the same intent,
    otherwise "把备注清空" is impossible from a conversation.
    """
    data: dict[str, Any] = {}
    title = _optional_str(arguments, "title")
    if title_required and not title:
        raise ToolArgumentError("missing_argument", "缺少必填参数：title")
    if title is not None:
        data["title"] = title
    for field in ("detail", "due_at", "status", "source"):
        if field not in arguments:
            continue
        value = arguments[field]
        explicitly_empty = value is None or (isinstance(value, str) and not value.strip())
        if explicitly_empty:
            # 显式空值 = 清空：detail / due_at 有意义，status / source 忽略（清空状态没有语义）。
            if field == "detail":
                data["detail"] = ""
            elif field == "due_at":
                data["due_at"] = None
            continue
        text = _optional_str(arguments, field)
        if text is not None:
            data[field] = text
    meta = _optional_mapping(arguments, "meta")
    if meta is not None:
        data["meta"] = meta
    return data


# ------------------------------------------------------------------ handlers

def _list_handler(kind: str) -> Callable[[Store, Mapping[str, Any]], dict[str, Any]]:
    """列表工具：先认通用状态词，再按该类型真实状态词精确过滤，都不认就报结构化错误。

    这条规则是 t22/N6 的修复：过去未知状态词会被当成「没有匹配的记录」而静默返回空集，
    模型据此对用户说「没有日程」——那是在陈述一个错误的用户可见事实。
    """
    known_words = _known_statuses(kind)
    known = {value.casefold() for value in known_words}
    done_statuses = {str(value).casefold() for value in DONE_STATUSES[kind]}

    def handler(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
        include_done = _optional_bool(arguments, "include_done", default=True)
        status = _optional_str(arguments, "status")
        limit = _optional_int(arguments, "limit")

        applied: str | None = None
        if status is None:
            records = store.list_records(kind, include_done=include_done)
        else:
            requested = str(status).strip()
            alias = _status_alias(requested)
            if alias == NOT_DONE_FILTER:
                #「未完成」通用词：等价 include_done=False（这就是它的全部含义）。
                records = store.list_records(kind, include_done=False)
                applied = NOT_DONE_FILTER
            elif alias == DONE_FILTER:
                #「已完成」通用词：该类型的完成集合（可能要包含已完成记录，所以先取全量）。
                records = [
                    record
                    for record in store.list_records(kind, include_done=True)
                    if str(record.get("status") or "").casefold() in done_statuses
                ]
                applied = DONE_FILTER
            elif requested.casefold() in known:
                wanted = requested.casefold()
                records = [
                    record
                    for record in store.list_records(kind, include_done=include_done)
                    if str(record.get("status") or "").casefold() == wanted
                ]
                applied = wanted
            else:
                #未知状态词绝不静默返回空集：把该类型的合法取值直接告诉模型。
                raise ToolArgumentError(
                    "invalid_arguments",
                    f"不认识的状态「{requested}」；{kind} 可用状态：{'、'.join(known_words)}；"
                    "也可以用通用词 open/pending/active/未完成/进行中（未完成）或 "
                    "done/completed/已完成（已完成）。",
                )
        if limit is not None:
            records = records[:limit]

        payload: dict[str, Any] = {
            "kind": kind,
            "count": len(records),
            "records": [_plain(record) for record in records],
        }
        if applied is not None:
            #回显实际应用的过滤：模型看得见工具是怎么理解它的状态词的（t22/N6）。
            payload["status_filter"] = {"requested": status, "applied": applied}
        if "include_done" in arguments:
            payload["include_done"] = include_done
        return payload

    return handler


def _create_handler(kind: str) -> Callable[[Store, Mapping[str, Any]], dict[str, Any]]:
    def handler(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
        data = _collect_fields(arguments, title_required=True)
        record = store.create_record(kind, data)
        return {
            "id": record["id"],
            "operation_id": record["operation_id"],
            "record": _plain(record),
        }

    return handler


def _update_handler(kind: str) -> Callable[[Store, Mapping[str, Any]], dict[str, Any]]:
    def handler(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
        record_id = _require_str(arguments, "id")
        data = _collect_fields(arguments, title_required=False)
        if not data:
            raise ToolArgumentError(
                "missing_argument",
                "至少需要提供 title、detail、due_at、status、source 或 meta 之一",
            )
        record = store.update_record(kind, record_id, data)
        return {"record": _plain(record), "operation_id": record["operation_id"]}

    return handler


def _delete_handler(kind: str) -> Callable[[Store, Mapping[str, Any]], dict[str, Any]]:
    def handler(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
        record_id = _require_str(arguments, "id")
        record = store.delete_record(kind, record_id)
        return {
            "record": _plain(record),
            "operation_id": record["operation_id"],
            "deleted": True,
        }

    return handler


def _remember_fact(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
    content = _require_str(arguments, "content")
    label = _optional_str(arguments, "label")
    memory_kind = _optional_str(arguments, "kind") or "fact"
    if memory_kind == "workflow":
        return {
            "ok": False,
            "error": "workflow_requires_skill",
            "message": "可复用的执行流程应通过技能提案和确认保存，不能写入事实记忆。",
            "suggested_tools": ["skill_create", "skill_evolve"],
        }
    if memory_kind not in MEMORY_KINDS:
        raise ToolArgumentError(
            "invalid_arguments", "kind 必须是 fact、preference 或 important 之一"
        )
    source = _optional_str(arguments, "source") or "assistant"
    meta: dict[str, Any] = dict(_optional_mapping(arguments, "meta") or {})
    meta["memory_kind"] = memory_kind
    record = store.create_record(
        "memories",
        {
            "title": label,
            "detail": content,
            "status": "active",
            "source": source,
            "meta": meta,
        },
    )
    return {
        "id": record["id"],
        "operation_id": record["operation_id"],
        "record": _plain(record),
    }


def _recall_memories(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
    query = _optional_str(arguments, "query") or ""
    limit = _optional_int(arguments, "limit", default=20) or 20
    # 事实只有一个来源：SQLite 的 memories 记录；这条召回路径永远只取 active。
    active = store.list_records("memories", include_done=False)
    if query:
        # 中文等无空格语言按相邻双字词项命中，不能靠「是否有空白字符」或整串 LIKE 匹配。
        memories = [record for score, record in score_facts(query, active) if score > 0.0][:limit]
    else:
        memories = active[:limit]
    return {"query": query, "count": len(memories), "memories": memories}


def _update_memory(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
    record_id = _require_str(arguments, "id")
    data: dict[str, Any] = {}
    content = _optional_str(arguments, "content")
    if content is not None:
        data["detail"] = content
    if "label" in arguments:
        data["title"] = _optional_str(arguments, "label")
    status = _optional_str(arguments, "status")
    if status is not None:
        if status not in MEMORY_STATUSES:
            raise ToolArgumentError(
                "invalid_arguments", "status 必须是 active、expired 或 deleted 之一"
            )
        data["status"] = status
    if not data:
        raise ToolArgumentError(
            "missing_argument", "至少需要提供 content、label 或 status 之一"
        )
    record = store.update_record("memories", record_id, data)
    return {"record": _plain(record), "operation_id": record["operation_id"]}


def _forget_memory(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
    record_id = _require_str(arguments, "id")
    record = store.update_record("memories", record_id, {"status": "deleted"})
    return {
        "record": _plain(record),
        "operation_id": record["operation_id"],
        "forgotten": True,
    }


def _current_time(store: Store, arguments: Mapping[str, Any]) -> dict[str, Any]:
    del store, arguments
    now = datetime.now(timezone.utc)
    local = now.astimezone()
    return {
        "iso": now.isoformat(),
        "utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": now.date().isoformat(),
        "local": local.isoformat(),
        "timezone": local.tzname() or "UTC",
        "weekday": _WEEKDAYS[now.weekday()],
        "timestamp": now.timestamp(),
    }


_HANDLERS: dict[str, Callable[[Store, Mapping[str, Any]], dict[str, Any]]] = {
    "list_todos": _list_handler("todos"),
    "create_todo": _create_handler("todos"),
    "update_todo": _update_handler("todos"),
    "delete_todo": _delete_handler("todos"),
    "list_calendar": _list_handler("calendar"),
    "create_calendar_event": _create_handler("calendar"),
    "update_calendar_event": _update_handler("calendar"),
    "delete_calendar_event": _delete_handler("calendar"),
    "list_reminders": _list_handler("reminders"),
    "create_reminder": _create_handler("reminders"),
    "update_reminder": _update_handler("reminders"),
    "delete_reminder": _delete_handler("reminders"),
    "list_notes": _list_handler("notes"),
    "create_note": _create_handler("notes"),
    "update_note": _update_handler("notes"),
    "delete_note": _delete_handler("notes"),
    "remember_fact": _remember_fact,
    "recall_memories": _recall_memories,
    "update_memory": _update_memory,
    "forget_memory": _forget_memory,
    "current_time": _current_time,
}


def _dump(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


async def execute_tool(store: Store, name: str, arguments: dict) -> str:
    """Run one business tool and return its JSON result.

    The coroutine never raises for bad input: unknown tools, invalid or missing
    arguments, unknown record kinds and missing records all come back as
    {"ok": false, ...}.
    """
    try:
        if not isinstance(store, Store):
            return _dump(
                {"ok": False, "error": "invalid_store", "message": "需要有效的 Store 实例"}
            )
        if not isinstance(arguments, Mapping):
            return _dump(
                {
                    "ok": False,
                    "error": "invalid_arguments",
                    "message": "arguments 必须是 JSON 对象",
                }
            )
        handler = _HANDLERS.get(str(name))
        if handler is None:
            return _dump(
                {"ok": False, "error": "unknown_tool", "message": f"未知工具：{name}"}
            )
        try:
            payload = handler(store, arguments)
        except ToolArgumentError as exc:
            return _dump({"ok": False, "error": exc.code, "message": str(exc)})
        except KeyError as exc:
            target = exc.args[0] if exc.args else "id"
            return _dump(
                {"ok": False, "error": "not_found", "message": f"记录不存在：{target}"}
            )
        except ValueError as exc:
            return _dump({"ok": False, "error": "invalid_arguments", "message": str(exc)})
        return _dump({"ok": True, **payload})
    except Exception as exc:  # defensive: a tool must never crash the caller
        return _dump(
            {
                "ok": False,
                "error": "internal_error",
                "message": f"{type(exc).__name__}: {exc}",
            }
        )
