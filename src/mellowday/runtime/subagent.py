"""子代理系统 —— 内置代理类型 + 自定义代理类型的 fork-return 模式。

机制与运行时保持一致：调用方指定代理类型，拿到 system_prompt 与工具子集，
再把它当作一个隔离的 Agent 运行，最后把结果回传主 Agent。

内置类型：explore（只读调查）、plan（结构化计划）、general（给定工具集）。
子代理默认不启用：agent 工具是 deferred 的，只有被显式激活后才会暴露给模型。

自定义代理是带 YAML frontmatter 的 Markdown 文件，从运行时数据目录
（data_dir()/agents）与当前工作目录的 .mellowday/agents 读取；同名时项目级优先。
"""

from __future__ import annotations

from pathlib import Path

from mellowday import paths
from mellowday.runtime.tools import tool_definitions, ToolDef

try:  # shared YAML frontmatter parser
    from mellowday.runtime.frontmatter import parse_frontmatter
except Exception:  # pragma: no cover - this module must import without other runtime packages
    from mellowday.runtime.memory import parse_frontmatter

# ─── Read-only tools (for explore and plan agents) ──────────

# explore / plan 子代理只能拿到这几个只读工具，避免它们改动持久化数据。
READ_ONLY_TOOLS = {"skill", "compact_context"}

# explore 子代理的系统提示词：定位为“调查专家”，强调只读、高效检索和清晰汇报。
EXPLORE_PROMPT = """You are a read-only research sub-agent for MellowDay.

=== CRITICAL: READ-ONLY MODE - NO STATE CHANGES ===
This is a READ-ONLY task. You are STRICTLY PROHIBITED from:
- Creating new records or files
- Modifying or deleting existing records
- Running any action that changes stored state

Your role is EXCLUSIVELY to look things up and analyse what you find.

Your strengths:
- Locating facts across the assistant's stored records
- Following one question through several tool calls without losing the thread
- Reporting precisely what you observed

Guidelines:
- Make efficient use of the tools you have; issue independent calls in parallel.
- Quote the values you actually saw (names, dates, numbers) instead of paraphrasing.
- Complete the request quickly and report your findings clearly."""

# plan 子代理的系统提示词：只读分析现状，并输出结构化的方案。
PLAN_PROMPT = """You are a Plan sub-agent — a READ-ONLY sub-agent specialized for designing plans.

IMPORTANT CONSTRAINTS:
- You are READ-ONLY. Do not change any stored data.
- You only have the observation tools you were given.

Your job:
- Understand the current situation from the evidence you can gather
- Design a step-by-step plan
- Point out what information is still missing
- Consider trade-offs and risks

Return a structured plan with:
1. Summary of the current state
2. Step-by-step plan
3. Information still needed
4. Risks or considerations"""

# general 子代理的系统提示词：允许使用除 agent 外的完整工具集，适合独立完成更复杂任务。
GENERAL_PROMPT = """You are an autonomous sub-agent for MellowDay. Given the task, use the tools available to you to complete it. Complete the task fully—don't gold-plate, but don't leave it half-done. When you finish, reply with a concise report covering what you did and any key findings — the caller will relay this to the user, so it only needs the essentials.

Your strengths:
- Investigating a question across many stored records
- Assembling facts that are spread over several places
- Performing multi-step research tasks

Guidelines:
- Be thorough: check more than one place before concluding something is missing.
- Report uncertainty explicitly instead of guessing.
- NEVER delete or overwrite stored data unless the task explicitly asks for it."""

# ─── Custom agent discovery ─────────────────────────────────

# 自定义代理发现结果的进程内缓存；读取 agents/*.md 后复用，避免每次调用 agent 工具都扫目录。
_cached_custom_agents: dict[str, dict] | None = None


def _discover_custom_agents() -> dict[str, dict]:
    """发现用户级和项目级自定义代理，并按代理名称返回配置。"""
    global _cached_custom_agents
    if _cached_custom_agents is not None:
        return _cached_custom_agents

    agents: dict[str, dict] = {}
    # User-level (lower priority)
    _load_agents_from_dir(paths.data_dir() / "agents", agents)
    # Project-level (higher priority, overwrites)
    _load_agents_from_dir(Path.cwd() / ".mellowday" / "agents", agents)

    _cached_custom_agents = agents
    return agents


def _load_agents_from_dir(directory: Path, agents: dict[str, dict]) -> None:
    """从指定目录读取 Markdown 代理定义，并合并到 agents 字典中。"""
    if not directory.is_dir():
        return
    for entry in directory.iterdir():
        if not entry.suffix == ".md":
            continue
        try:
            raw = entry.read_text(encoding="utf-8")
            result = parse_frontmatter(raw)
            meta = result.meta
            name = meta.get("name") or entry.stem
            allowed_tools = None
            if "allowed-tools" in meta:
                # allowed-tools 是逗号分隔的工具白名单；缺省时会在 get_sub_agent_config 中开放全部非 agent 工具。
                allowed_tools = [s.strip() for s in meta["allowed-tools"].split(",")]
            agents[name] = {
                "name": name,
                "description": meta.get("description", ""),
                "allowed_tools": allowed_tools,
                "system_prompt": result.body,
            }
        except Exception:
            # 单个自定义代理文件解析失败时不影响整个程序启动或其他代理加载。
            pass


def get_sub_agent_config(agent_type: str) -> dict:
    """根据代理类型生成 Agent 运行时需要的 system_prompt 和 tools 配置。"""
    custom = _discover_custom_agents().get(agent_type)
    if custom:
        if custom["allowed_tools"]:
            # 自定义代理显式声明工具白名单时，只授予白名单中的工具。
            tools = [t for t in tool_definitions if t["name"] in custom["allowed_tools"]]
        else:
            # 不允许子代理再调用 agent 工具，避免递归创建子代理导致控制流复杂化。
            tools = [t for t in tool_definitions if t["name"] != "agent"]
        return {"system_prompt": custom["system_prompt"], "tools": tools}

    # 内置 explore / plan 使用相同的只读工具集合。
    read_only = [t for t in tool_definitions if t["name"] in READ_ONLY_TOOLS]

    if agent_type == "explore":
        return {"system_prompt": EXPLORE_PROMPT, "tools": read_only}
    elif agent_type == "plan":
        return {"system_prompt": PLAN_PROMPT, "tools": read_only}
    else:  # general
        return {"system_prompt": GENERAL_PROMPT, "tools": [t for t in tool_definitions if t["name"] != "agent"]}


# ─── 可用的agent类型(for system prompt) ──────────────


def get_available_agent_types() -> list[dict[str, str]]:
    """返回系统提示词中可展示的全部代理类型说明，包括内置代理和自定义代理。"""
    types = [
        {"name": "explore", "description": "Fast, read-only investigation with limited tools"},
        {"name": "plan", "description": "Read-only analysis with structured plans"},
        {"name": "general", "description": "Full tools for independent tasks"},
    ]
    for name, defn in _discover_custom_agents().items():
        types.append({"name": name, "description": defn["description"]})
    return types


def build_agent_descriptions() -> str:
    """把自定义代理类型格式化成 Markdown，供主 Agent 注入到系统提示词中。"""
    types = get_available_agent_types()
    if len(types) <= 3:
        return ""  # Only built-in types, already in system prompt

    custom = types[3:]
    lines = ["\n# Custom Agent Types", ""]
    for t in custom:
        lines.append(f"- **{t['name']}**: {t['description']}")
    return "\n".join(lines)


def reset_agent_cache() -> None:
    """清空自定义代理缓存；测试或运行中刷新代理配置时使用。"""
    global _cached_custom_agents
    _cached_custom_agents = None
