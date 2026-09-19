"""记忆与事实召回。

**事实的唯一来源是 SQLite 的 memories 记录**（由 mellowday.personal_assistant 的工具写入，
由 mellowday.storage.store.Store 读取）。本模块不再扫描 Markdown 记忆文件来召回；文件部分
只作为遗留的文件存储保留（list/save/delete/索引），不参与任何召回。

召回流程（I22）：

1. Agent 在每轮对话组装上下文时调用 `recall_facts`，把用户这一轮的输入交给
   `fact_provider`；
2. `fact_provider` 返回候选事实记录（每一项都是 dict，含 id/title/detail 等，调用方保证
   只返回 active），运行时在本地按词项命中排序并做条数/字节预算；
3. 选中的事实以 `<system-reminder>` 段落注入本轮 user 消息，注入点是
   `Agent._inject_recalled_facts`（agent.py），模型无需显式调用工具；
4. 下一轮注入之前会先移除上一轮注入的段落，因此事实被更新或删除后，旧值不会继续留在
   对话历史里（折叠摘要的输入也会先移除这些段落）。
5. 历史本身保留真实发生过的事情：助手回复、工具结果与折叠摘要不会被改写或删除。为了让
   模型不把其中的旧值当成当前事实，运行时逐轮比对「上一轮提供给模型的值」与「现在的当前
   值」，把变化或消失的旧值列进同一段注入的失效清单（当前值 / 旧值 / 来源 / 失效原因与
   时间）。这就是「当前值 + 失效关系」的最小表达：不建知识图谱，只维护一张有界的清单。

召回不使用 LLM side query：`fact_provider` 是本地数据库读取，直接 await 即可，所以没有
模型、没有网络也能工作。词项切分对中文等无空格语言使用「相邻双字」词项，绝不把
「输入是否包含空白字符」作为是否召回的判据。
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mellowday import paths

try:  # shared YAML frontmatter parser
    from mellowday.runtime.frontmatter import parse_frontmatter, format_frontmatter
except Exception:  # pragma: no cover - memory must import without the skills package
    try:
        from mellowday.runtime.skills.frontmatter import parse_frontmatter, format_frontmatter
    except Exception:
        parse_frontmatter = None  # type: ignore[assignment]
        format_frontmatter = None  # type: ignore[assignment]


if parse_frontmatter is None or format_frontmatter is None:  # pragma: no cover
    # Minimal stand-in so the memory store still works when no shared parser is
    # importable. The shared parser above is preferred whenever it exists.
    from dataclasses import dataclass as _dataclass, field as _field

    @_dataclass
    class _FrontmatterResult:
        meta: dict[str, str] = _field(default_factory=dict)
        body: str = ""

    def parse_frontmatter(content: str) -> "_FrontmatterResult":
        lines = str(content or "").split("\n")
        if not lines or lines[0].strip() != "---":
            return _FrontmatterResult(body=str(content or ""))
        end_idx = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break
        if end_idx == -1:
            return _FrontmatterResult(body=str(content or ""))
        meta: dict[str, str] = {}
        for i in range(1, end_idx):
            colon_idx = lines[i].find(":")
            if colon_idx == -1:
                continue
            key = lines[i][:colon_idx].strip()
            if key:
                meta[key] = lines[i][colon_idx + 1:].strip()
        return _FrontmatterResult(meta=meta, body="\n".join(lines[end_idx + 1:]).strip())

    def format_frontmatter(meta: dict[str, str], body: str) -> str:
        lines = ["---"]
        for key, value in meta.items():
            lines.append(f"{key}: {value}")
        lines.extend(["---", "", body])
        return "\n".join(lines)

# side query 是一个异步函数：输入 system prompt 和 user prompt，返回模型文本。
# 这里标成 Any 是为了避免在运行时引入复杂 Awaitable 类型约束。
SideQueryFn = Callable[[str, str], Any]  # actually Awaitable[str]

#: fact_provider：输入本轮用户文本，返回候选事实记录列表。
FactProvider = Callable[[str], Awaitable[list[dict]]]


VALID_TYPES = {"user", "feedback", "project", "reference"}
MAX_INDEX_LINES = 200       # MEMORY.md 注入 system prompt 前最多保留的行数。
MAX_INDEX_BYTES = 25000     # MEMORY.md 注入 system prompt 前最多保留的字节数。

# ─── 事实召回（唯一召回路径）───────────────────────────────────────────────

#: 每轮最多注入的事实条数（有词项命中时）。
MAX_RECALLED_FACTS = 5
#: 候选总量不超过这个数时视为「小库」。
SMALL_STORE_FACTS = 5
#: 小库且本轮没有任何词项命中时，按 provider 顺序保留的条数。
UNMATCHED_FALLBACK_FACTS = 3
#: 单条事实注入前的最大字节数。
MAX_FACT_BYTES_PER_RECORD = 2048
#: 当前会话最多注入的事实总量（字节）。
MAX_SESSION_MEMORY_BYTES = 60 * 1024

#: 失效清单最多保留多少条旧值（对话里出现过的旧值数量本身有限，这里再兜一层上限）。
MAX_SUPERSEDED_FACTS = 8
#: 一条旧值在注入段落里的最大字符数。
MAX_SUPERSEDED_DETAIL_CHARS = 200

#: 注入段落的第一行；既用于阅读，也作为「这一段是本模块注入的事实」的稳定标记，
#: 下一轮替换旧值、以及折叠摘要前都靠它定位并移除整段。
FACT_REMINDER_MARKER = (
    "Recalled facts about the user (current values from the memory store):"
)

#: 失效清单的小标题：同一段注入里紧接着当前值。
SUPERSEDED_FACTS_MARKER = (
    "Facts that were current earlier in this conversation and are NOT current any more:"
)

#: 失效清单的收尾规则：旧值只是历史，不得当成用户当前的情况。
SUPERSEDED_FACTS_RULE = (
    "Those superseded values are history only: never repeat them as the user's current "
    "situation, even when an earlier reply, tool result or folded summary mentions them."
)

#: 用户本轮明确要求优先于任何已存偏好（I08 的「当前明确指令覆盖默认习惯」）。
FACT_PRECEDENCE_RULE = (
    "The user's explicit request in the current message always wins over any stored habit or "
    "preference listed above."
)

_FACT_REMINDER_RE = re.compile(
    r"\n*<system-reminder>\s*" + re.escape(FACT_REMINDER_MARKER) + r".*?</system-reminder>\s*",
    re.DOTALL,
)

# 中文（CJK）连续片段、以及拉丁字母/数字单词。中文没有空格，按相邻双字切词项。
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_WORD_RE = re.compile(r"[0-9a-z_]+")


def query_terms(query: str) -> set[str]:
    """把查询切成用于命中的词项。

    中文等无空格语言取相邻双字（bigram），因此「我几点下班」能得到
    {我几, 几点, 点下, 下班}，可以和事实文本「用户每天 18:00 下班」命中；
    整段中文不会因为「没有空白字符」而被跳过。单个汉字的查询直接取该字。
    """
    text = str(query or "").casefold()
    terms: set[str] = set()
    for run in _CJK_RUN_RE.findall(text):
        if len(run) == 1:
            terms.add(run)
            continue
        for index in range(len(run) - 1):
            terms.add(run[index:index + 2])
    for word in _WORD_RE.findall(text):
        if len(word) >= 2 or word.isdigit():
            terms.add(word)
    return terms


def _fact_label(record: Mapping[str, Any]) -> str:
    value = record.get("title") or record.get("label")
    return str(value).strip() if value else "事实"


def _fact_kind(record: Mapping[str, Any]) -> str:
    meta = record.get("meta")
    if isinstance(meta, Mapping):
        value = meta.get("memory_kind")
        if value:
            return str(value).strip()
    return "fact"


def _fact_detail(record: Mapping[str, Any]) -> str:
    for field in ("detail", "content", "text"):
        value = record.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _fact_key(record: Mapping[str, Any]) -> str:
    """一条事实在会话内的去重键：优先用记录 id。"""
    value = record.get("id")
    if value:
        return str(value)
    return f"{_fact_label(record)}|{_fact_detail(record)}"[:200]


def score_fact(query: str, record: Mapping[str, Any]) -> float:
    """单条事实与本轮输入的词项命中分（0 表示没有命中）。"""
    return _score_terms(query_terms(query), record)


def _score_terms(terms: set[str], record: Mapping[str, Any]) -> float:
    if not terms:
        return 0.0
    label = _fact_label(record).casefold()
    body = " ".join(
        str(record.get(field) or "") for field in ("detail", "content", "text")
    ).casefold()
    score = 0.0
    for term in terms:
        if term in label:
            score += 2.0
        elif term in body:
            score += 1.0
    return score / (2.0 * len(terms))


def score_facts(
    query: str, records: Sequence[Mapping[str, Any]]
) -> list[tuple[float, dict[str, Any]]]:
    """给候选事实打分并按分数降序返回；同分保持 provider 给出的顺序。"""
    terms = query_terms(query)
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        scored.append((_score_terms(terms, record), index, dict(record)))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [(score, record) for score, _, record in scored]


def _active_candidates(raw: Any) -> list[dict[str, Any]]:
    """过滤出可注入的候选。

    `fact_provider` 的实现方保证只返回 active；这里再兜一层，防止非 active 事实上屏，
    并丢掉既没有标题也没有正文的空记录。
    """
    if not isinstance(raw, (list, tuple)):
        return []
    records: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        status = item.get("status")
        if status is not None and str(status).casefold() != "active":
            continue
        if not _fact_detail(item) and not str(item.get("title") or "").strip():
            continue
        records.append(dict(item))
    return records


def _truncate_utf8(text: str, limit: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


class RelevantMemory:
    """一条准备注入对话的事实。"""

    __slots__ = ("path", "content", "mtime_ms", "header")

    def __init__(self, path: str, content: str, mtime_ms: float, header: str):
        self.path = path
        self.content = content
        self.mtime_ms = mtime_ms
        self.header = header

    @property
    def size(self) -> int:
        """当前内容占用的字节数，供 Agent 统计本会话注入预算。"""
        return len(self.content.encode())


def select_fact_records(
    query: str, records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """从候选里挑出本轮要注入的事实。

    规则：

    * 有词项命中的候选按分数取前 `MAX_RECALLED_FACTS` 条；
    * 一条都没命中、且候选总量很小（不超过 `SMALL_STORE_FACTS`）时，按 provider 顺序
      保留至多 `UNMATCHED_FALLBACK_FACTS` 条——个人助理的事实库通常只有几条，措辞不同
      不应该让「记住过的事实」完全用不上；
    * 候选很多又都没命中时返回空，避免把无关事实塞进上下文。
    """
    scored = score_facts(query, records)
    hits = [(score, record) for score, record in scored if score > 0.0]
    if hits:
        return [record for _, record in hits[:MAX_RECALLED_FACTS]]
    if records and len(scored) <= SMALL_STORE_FACTS:
        return [record for _, record in scored[:UNMATCHED_FALLBACK_FACTS]]
    return []


def active_fact_records(raw: Any) -> list[dict[str, Any]]:
    """可注入的 active 候选记录（公开入口）。

    运行时用它把同一次数据库读取同时用于召回与失效校验：召回需要原始记录形状
    （id/title/detail/meta），失效比对需要 key 稳定，两边都从这里出发就不会各读一次。
    """
    return _active_candidates(raw)


def fact_supersession_hook(fact_provider: Any) -> Any:
    """取回 provider 暴露的写回钩子（没有则返回 None）。

    仅用于已明确展示来源记录并获确认的事实迁移。调用方传入确认前的完整快照，
    provider 负责核对当前记录未变更后写回同一数据库；运行时不另建事实库。
    缺失钩子必须显示迁移未完成，不得以文字相似度推断取代关系。
    """
    hook = getattr(fact_provider, "supersede_rule_facts", None)
    return hook if callable(hook) else None


def fact_snapshot(records: Any) -> dict[str, dict[str, Any]]:
    """把候选记录整理成 {去重键: {title, detail, kind, updated_at}}，只保留 active。

    运行时用它保存「这一轮提供给模型的事实当时是什么值」，下一轮再和新的当前值比对，
    从而知道哪些旧值已经失效。
    """
    snapshot: dict[str, dict[str, Any]] = {}
    for record in _active_candidates(records):
        detail = _fact_detail(record)
        if not detail:
            continue
        snapshot[_fact_key(record)] = {
            "title": _fact_label(record),
            "detail": detail,
            "kind": _fact_kind(record),
            "updated_at": str(record.get("updated_at") or ""),
        }
    return snapshot


def diff_fact_state(
    observed: Mapping[str, Mapping[str, Any]],
    current: Mapping[str, Mapping[str, Any]],
    *,
    now: str | None = None,
) -> list[dict[str, Any]]:
    """比较「上一轮提供给模型的值」与「现在的当前值」，返回失效条目。

    只有已经提供给模型的事实才需要在这里出现：它们可能已经出现在助手回复、工具结果或
    折叠摘要里。返回的每条记录都是「当前值 / 旧值 / 来源 / 失效原因与时间」这个最小关系
    的一次表达，而不是一个通用知识图谱。
    """
    stamp = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    changed: list[dict[str, Any]] = []
    for key, previous in observed.items():
        if not isinstance(previous, Mapping):
            continue
        old_detail = " ".join(str(previous.get("detail") or "").split())
        current_record = current.get(key)
        if current_record is None:
            changed.append(
                {
                    "key": str(key),
                    "title": str(previous.get("title") or ""),
                    "kind": str(previous.get("kind") or "fact"),
                    "detail": old_detail,
                    "reason": "removed",
                    "replaced_by": "",
                    "at": stamp,
                }
            )
            continue
        new_detail = " ".join(str(current_record.get("detail") or "").split())
        title_changed = str(current_record.get("title") or "") != str(previous.get("title") or "")
        if new_detail != old_detail or title_changed:
            changed.append(
                {
                    "key": str(key),
                    "title": str(previous.get("title") or ""),
                    "kind": str(previous.get("kind") or "fact"),
                    "detail": old_detail,
                    "reason": "updated",
                    "replaced_by": new_detail,
                    "at": stamp,
                }
            )
    return changed


async def recall_facts(
    query: str,
    fact_provider: FactProvider | None,
    already_surfaced: set[str] | None = None,
    session_memory_bytes: int = 0,
    *,
    records: Sequence[Mapping[str, Any]] | None = None,
) -> list[RelevantMemory]:
    """按本轮用户输入召回事实；失败或没有 provider 时返回空列表。

    这是运行时唯一的召回入口：候选来自 `fact_provider`（SQLite 的 memories 记录），
    不读取 Markdown 记忆文件，也不发 side query。

    `records` 允许调用方复用它已经取回的候选：运行时每轮只读一次数据库，把同一次读取
    的结果同时用于召回与「旧值是否失效」的校验。
    """
    text = str(query or "").strip()
    if records is None:
        if fact_provider is None:
            return []
        if not text:
            return []
        if session_memory_bytes >= MAX_SESSION_MEMORY_BYTES:
            return []
        try:
            raw = await fact_provider(text)
        except Exception as exc:  # 召回失败不能影响主对话
            logging.getLogger(__name__).warning("fact recall failed: %s", exc)
            return []
        records = raw

    records = _active_candidates(records)
    if already_surfaced:
        records = [r for r in records if _fact_key(r) not in already_surfaced]
    if not records:
        return []

    chosen = select_fact_records(text, records)
    if not chosen:
        return []

    budget = max(0, MAX_SESSION_MEMORY_BYTES - max(0, int(session_memory_bytes)))
    now_ms = time.time() * 1000
    memories: list[RelevantMemory] = []
    used = 0
    for record in chosen:
        detail = _truncate_utf8(_fact_detail(record), MAX_FACT_BYTES_PER_RECORD)
        if not detail:
            continue
        size = len(detail.encode())
        if memories and used + size > budget:
            break
        header = f"{_fact_label(record)} [{_fact_kind(record)}]"
        memories.append(
            RelevantMemory(path=_fact_key(record), content=detail, mtime_ms=now_ms, header=header)
        )
        used += size
    return memories


def format_superseded_facts(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """把失效条目渲染成注入段落里的行。

    一行表达四件事：哪个事实（标签 + 类型）、旧值是什么、它为什么不再有效（被改成什么 /
    已从记忆库删除）、什么时候失效。没有这一行，历史消息里的旧值就没有任何标记说明它
    已经过期。
    """
    lines: list[str] = []
    for entry in list(entries)[:MAX_SUPERSEDED_FACTS]:
        if not isinstance(entry, Mapping):
            continue
        label = str(entry.get("title") or "事实").strip() or "事实"
        kind = str(entry.get("kind") or "fact").strip() or "fact"
        previous = " ".join(str(entry.get("detail") or "").split())[:MAX_SUPERSEDED_DETAIL_CHARS]
        if not previous:
            continue
        at = str(entry.get("at") or "").strip()
        stamp = f" ({at})" if at else ""
        if str(entry.get("reason")) == "updated":
            current = " ".join(str(entry.get("replaced_by") or "").split())[
                :MAX_SUPERSEDED_DETAIL_CHARS
            ]
            replacement = f' — replaced by "{current}"' if current else " — value changed"
            lines.append(f'- {label} [{kind}]: "{previous}"{replacement}{stamp}')
        else:
            lines.append(f'- {label} [{kind}]: "{previous}" — no longer in the memory store{stamp}')
    return lines


def format_memories_for_injection(
    memories: Sequence[RelevantMemory],
    *,
    superseded: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """把召回的事实与失效的旧值包成一个 `<system-reminder>` 段落。

    这是每轮注入的完整单元：先给当前值（模型本轮唯一可以当作当前事实的内容），再列出
    对话历史里出现过的、已经失效的旧值。历史本身不被改写——助手回复、工具结果与折叠摘要
    保持真实发生过样子——失效关系只在这里表达。两者都为空时不注入。
    """
    notes = format_superseded_facts(superseded or [])
    if not memories and not notes:
        return ""
    lines = [FACT_REMINDER_MARKER]
    if memories:
        for memory in memories:
            detail = " ".join(memory.content.split())
            if memory.header:
                lines.append(f"- {memory.header}: {detail}")
            else:
                lines.append(f"- {detail}")
    else:
        lines.append("- (no relevant current fact for this request)")
    if notes:
        lines.append("")
        lines.append(SUPERSEDED_FACTS_MARKER)
        lines.extend(notes)
        lines.append(SUPERSEDED_FACTS_RULE)
    if memories:
        lines.append(FACT_PRECEDENCE_RULE)
    return "<system-reminder>\n" + "\n".join(lines) + "\n</system-reminder>"


def strip_fact_reminders(text: str) -> str:
    """移除文本里由本模块注入的事实段落。

    下一轮注入新事实前、以及生成折叠摘要之前都会先调用它，保证事实被更新或删除后，
    旧值不会再从历史消息里被读到。
    """
    if not text or "<system-reminder>" not in text:
        return text
    stripped = _FACT_REMINDER_RE.sub("", text)
    return stripped.strip() if stripped != text else text


# ─── 遗留 Markdown 文件存储（不是事实来源，不参与召回）────────────────────
# 下面这些函数是移植时保留的文件型记忆工具，只用于文件级维护与历史兼容。
# 事实来源是 SQLite 的 memories 记录：写入走 remember_fact/update_memory/forget_memory，
# 召回走 recall_facts，都不要从这里取事实。


class MemoryEntry:
    """完整 memory 条目，用于文件列表和 CRUD 操作。"""

    __slots__ = ("name", "description", "type", "filename", "content")

    def __init__(self, name: str, description: str, type: str, filename: str, content: str):
        self.name = name
        self.description = description
        self.type = type
        self.filename = filename
        self.content = content


def get_memory_dir() -> Path:
    """返回记忆目录（运行时数据目录之下），不存在时自动创建。"""
    return paths.memory_dir()


def _get_index_path() -> Path:
    """MEMORY.md 是当前项目 memory 文件的索引文件。"""
    return get_memory_dir() / "MEMORY.md"


def _slugify(text: str) -> str:
    """把记忆名称转成适合文件名的短 slug（保留中文等 Unicode 字符）。"""
    s = re.sub(r"[^\w]+", "_", text.lower(), flags=re.UNICODE)
    s = s.strip("_")
    return s[:40]


def list_memories() -> list[MemoryEntry]:
    """读取当前项目所有 memory 文件，并按修改时间倒序返回。"""
    d = get_memory_dir()
    entries: list[MemoryEntry] = []
    for f in sorted(d.glob("*.md")):
        # MEMORY.md 是索引，不是一条真实记忆。
        if f.name == "MEMORY.md":
            continue
        try:
            result = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
            meta = result.meta
            # 没有 name/type 的文件不算合法 memory。
            if not meta.get("name") or not meta.get("type"):
                continue
            # type 不合法时降级为 project，避免坏文件中断列表。
            t = meta["type"] if meta["type"] in VALID_TYPES else "project"
            entries.append(MemoryEntry(
                name=meta["name"],
                description=meta.get("description", ""),
                type=t,
                filename=f.name,
                content=result.body,
            ))
        except Exception:
            pass
    # 最近修改的记忆排在前面，方便展示。
    entries.sort(key=lambda e: (d / e.filename).stat().st_mtime, reverse=True)
    return entries


def save_memory(name: str, description: str, type: str, content: str) -> str:
    """保存一条 memory 文件，并刷新 MEMORY.md 索引。"""
    d = get_memory_dir()
    filename = f"{type}_{_slugify(name)}.md"
    text = format_frontmatter({"name": name, "description": description, "type": type}, content)
    (d / filename).write_text(text, encoding="utf-8")
    _update_memory_index()
    return filename


def delete_memory(filename: str) -> bool:
    """按文件名删除 memory 文件，删除成功后刷新索引。"""
    filepath = get_memory_dir() / filename
    if not filepath.exists():
        return False
    filepath.unlink()
    _update_memory_index()
    return True


def _update_memory_index() -> None:
    """根据当前 memory 文件重新生成 MEMORY.md。"""
    memories = list_memories()
    lines = ["# Memory Index", ""]
    for m in memories:
        lines.append(f"- **[{m.name}]({m.filename})** ({m.type}) — {m.description}")
    _get_index_path().write_text("\n".join(lines), encoding="utf-8")


def load_memory_index() -> str:
    """读取 MEMORY.md，并在注入 system prompt 前做长度保护。"""
    index_path = _get_index_path()
    if not index_path.exists():
        return ""
    content = index_path.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")
    if len(lines) > MAX_INDEX_LINES:
        content = "\n".join(lines[:MAX_INDEX_LINES]) + "\n\n[... truncated, too many memory entries ...]"
    if len(content.encode()) > MAX_INDEX_BYTES:
        content = content[:MAX_INDEX_BYTES] + "\n\n[... truncated, index too large ...]"
    return content


class MemoryHeader:
    """轻量 memory 文件摘要（遗留文件存储用）。"""

    __slots__ = ("filename", "file_path", "mtime_ms", "description", "type")

    def __init__(self, filename: str, file_path: str, mtime_ms: float,
                 description: str | None, type: str | None):
        self.filename = filename
        self.file_path = file_path
        self.mtime_ms = mtime_ms
        self.description = description
        self.type = type


MAX_MEMORY_FILES = 200                    # 参与扫描的最多 memory 文件数。


def scan_memory_headers() -> list[MemoryHeader]:
    """快速扫描 memory 文件头，用于文件级展示（不参与事实召回）。"""
    d = get_memory_dir()
    headers: list[MemoryHeader] = []
    for f in d.glob("*.md"):
        if f.name == "MEMORY.md":
            continue
        try:
            stat = f.stat()
            raw = f.read_text(encoding="utf-8", errors="replace")
            # 只解析前 30 行，通常 frontmatter 足够在文件开头完成。
            first30 = "\n".join(raw.split("\n")[:30])
            result = parse_frontmatter(first30)
            meta = result.meta
            t = meta.get("type")
            headers.append(MemoryHeader(
                filename=f.name,
                file_path=str(f),
                mtime_ms=stat.st_mtime * 1000,
                description=meta.get("description"),
                type=t if t in VALID_TYPES else None,
            ))
        except Exception:
            pass
    headers.sort(key=lambda h: h.mtime_ms, reverse=True)
    return headers[:MAX_MEMORY_FILES]


def format_memory_manifest(headers: list[MemoryHeader]) -> str:
    """把 memory 文件摘要列表格式化成一行一条的清单。"""
    lines = []
    for h in headers:
        tag = f"[{h.type}] " if h.type else ""
        ts = datetime.fromtimestamp(h.mtime_ms / 1000, tz=timezone.utc).isoformat()
        if h.description:
            lines.append(f"- {tag}{h.filename} ({ts}): {h.description}")
        else:
            lines.append(f"- {tag}{h.filename} ({ts})")
    return "\n".join(lines)


def memory_age(mtime_ms: float) -> str:
    """把修改时间转换成适合展示的相对时间。"""
    days = max(0, int((time.time() * 1000 - mtime_ms) / 86_400_000))
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


SELECT_MEMORIES_PROMPT = """You are selecting memories that will be useful to a personal assistant as it processes a user's request. You will be given the user's query and a list of available memory files with their filenames and descriptions.

Return a JSON object with a "selected_memories" array of filenames for the memories that will clearly be useful (up to 5). Only include memories that you are certain will be helpful based on their name and description.
- If you are unsure if a memory will be useful, do not include it.
- If no memories would clearly be useful, return an empty array."""


async def select_relevant_memories(
    query: str,
    side_query: SideQueryFn,
    already_surfaced: set[str],
) -> list[RelevantMemory]:
    """遗留的 Markdown 召回（side query 选文件）。

    Agent 不再调用它：事实召回走 recall_facts + fact_provider（见模块开头）。
    保留本函数只为文件级维护与回归测试，避免把 Markdown 文件当成事实来源。
    """
    headers = scan_memory_headers()

    if not headers:
        return []

    candidates = [h for h in headers if h.file_path not in already_surfaced]
    if not candidates:
        return []

    manifest = format_memory_manifest(candidates)

    try:
        text = await side_query(
            SELECT_MEMORIES_PROMPT,
            f"Query: {query}\n\nAvailable memories:\n{manifest}",
        )
        match = re.search(r"{[\s\S]*}", text)
        if not match:
            return []
        parsed = json.loads(match.group(0))
        selected_filenames = set(parsed.get("selected_memories", []))
        selected = [h for h in candidates if h.filename in selected_filenames][:5]

        result: list[RelevantMemory] = []
        for h in selected:
            content = Path(h.file_path).read_text(encoding="utf-8", errors="replace")
            if len(content.encode()) > 4096:
                content = content[:4096] + "\n\n[... truncated, memory file too large ...]"
            result.append(RelevantMemory(
                path=h.file_path,
                content=content,
                mtime_ms=h.mtime_ms,
                header=f"Memory (saved {memory_age(h.mtime_ms)}): {h.file_path}",
            ))
        return result
    except Exception as e:
        if "cancel" in str(e).lower():
            return []
        logging.getLogger(__name__).warning("memory recall failed: %s", e)
        return []


def build_memory_prompt_section() -> str:
    """生成注入 system prompt 的事实记忆说明。

    这里只写静态说明：事实存在 SQLite 里，由 remember_fact/recall_memories/
    update_memory/forget_memory 读写；与当前这轮相关的事实会在每轮对话开始时自动注入，
    因此 system prompt 里不再列出任何 Markdown 记忆索引（Markdown 不是事实来源）。
    """
    return """# Memory System

The user's durable facts live in one store. The remember_fact, recall_memories,
update_memory and forget_memory tools are the only way to read or write it;
never touch its storage directly.

## Fact Types
- **fact**: an objective, durable detail about the user
- **preference**: a standing preference or habit of the user
- **important**: something the user marked as important

## How to Save Facts
Call remember_fact with a short label, a kind from the list above, and the fact
itself. Save only when the user asks you to remember something, or when the fact
is clearly durable and reusable. When a fact changes, update the stored record
instead of adding a second one.

## Automatic Recall
Facts relevant to the current request are attached to the conversation
automatically at the start of every turn, and they always carry the current
value. Read them before asking the user to repeat something they already told
you. Call recall_memories only when you need a fact that was not attached.

## What NOT to Save
- Ephemeral details of the current request
- Anything the user asked you to forget
- Guesses you cannot attribute to the user
"""
