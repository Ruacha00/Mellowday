"""Built-in tool surface for the MellowDay runtime.

MellowDay is a personal assistant, not a coding agent, so the software
engineering tools of the original runtime (file reads and writes, code search,
shell execution) are gone. The assistant's own capabilities arrive as *business
tools* through Agent(custom_tools=..., tool_executor=...); what remains here is
the tool infrastructure the runtime itself owns:

* the Skills tools (skill, skill_create, skill_evolve);
* compact_context, whose execution lives in mellowday.runtime.agent;
* deferred definitions for plan mode and sub-agents;
* permission checks and deferred-tool bookkeeping used by the agent loop.
"""
from __future__ import annotations

import json

ToolDef = dict  # Anthropic tool schema dict
PermissionMode = str  # "default" | "plan" | "acceptEdits" | "bypassPermissions" | "dontAsk"

# Tools that may run in parallel batches inside one model turn (read-only, no
# side effects on stored data).
CONCURRENCY_SAFE_TOOLS = {"skill"}


# --- Tool definitions ------------------------------------------------------

tool_definitions: list[ToolDef] = [
    {
        "name": "skill",
        "description": "Invoke a registered skill by name. Skills are reusable prompt templates stored in the assistant's skill library. Returns the skill's resolved prompt to follow.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "The exact registered skill name, exactly as listed in the Available Skills section",
                },
                "args": {"type": "string", "description": "Optional arguments to pass to the skill"},
            },
            "required": ["skill_name"],
        },
    },
    {
        "name": "compact_context",
        "description": "Compact the current conversation context into structured session memory when the context is long, tool results are noisy, or a strategy reset is useful. This preserves task progress, current next steps, and tool-use experience, then continues from the folded memory.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Brief reason for compacting now, such as long context, many tool calls, repeated failures, or strategy change.",
                },
            },
        },
    },
    {
        "name": "skill_evolve",
        "description": "Persist an explicit reusable user correction or workflow preference into an existing skill. Creates a version snapshot before editing the skill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "The registered skill name to evolve"},
                "lesson": {"type": "string", "description": "Durable reusable rule to add to the skill"},
                "rationale": {"type": "string", "description": "Why this lesson should affect future similar tasks"},
                "target": {
                    "type": "string",
                    "enum": ["active", "project", "user"],
                    "description": "Which skill file to update. Defaults to active.",
                },
            },
            "required": ["skill_name", "lesson"],
        },
    },
    {
        "name": "skill_create",
        "description": "Create a new reusable skill from explicit durable workflow guidance when no suitable existing skill exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Concise reusable skill name"},
                "description": {"type": "string", "description": "One-sentence description of what the skill does and when to use it"},
                "instructions": {"type": "string", "description": "Reusable SKILL.md body. Focus on durable method, constraints, and workflow, not one-off task content."},
                "when_to_use": {"type": "string", "description": "Trigger condition for auto-invocation"},
                "target": {
                    "type": "string",
                    "enum": ["project", "user"],
                    "description": "Where to create the skill. Defaults to project.",
                },
                "context": {
                    "type": "string",
                    "enum": ["inline", "fork"],
                    "description": "Skill execution mode. Defaults to inline.",
                },
                "user_invocable": {"type": "boolean", "description": "Whether users can invoke it manually with /<skill>. Defaults to false."},
                "allowed_tools": {"type": "string", "description": "Optional comma-separated allowed tools for fork mode"},
                "evidence": {"type": "string", "description": "Short user-provided evidence showing why this is reusable"},
            },
            "required": ["name", "description", "instructions"],
        },
    },
    {
        "name": "enter_plan_mode",
        "description": "Enter plan mode to switch to a read-only planning phase.",
        "input_schema": {"type": "object", "properties": {}},
        "deferred": True,
    },
    {
        "name": "exit_plan_mode",
        "description": "Exit plan mode after you have finished writing your plan to the plan file.",
        "input_schema": {"type": "object", "properties": {}},
        "deferred": True,
    },
    {
        "name": "agent",
        "description": "Launch a sub-agent to handle a task autonomously. Sub-agents have isolated context and return their result.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "Short (3-5 word) description of the sub-agent's task"},
                "prompt": {"type": "string", "description": "Detailed task instructions for the sub-agent"},
                "type": {"type": "string", "enum": ["explore", "plan", "general"], "description": "Agent type. Default: general"},
            },
            "required": ["description", "prompt"],
        },
        "deferred": True,
    },
]


# --- Deferred tool activation ----------------------------------------------

_activated_tools: set[str] = set()


def reset_activated_tools() -> None:
    _activated_tools.clear()


def get_active_tool_definitions(all_tools: list[ToolDef] | None = None) -> list[ToolDef]:
    """Return the tool definitions that are currently available.

    Deferred tools stay hidden until something activates them, and the internal
    "deferred" marker is stripped before the list goes to a model API.
    """
    tools = all_tools if all_tools is not None else tool_definitions
    return [
        {k: v for k, v in t.items() if k != "deferred"}
        for t in tools
        if not t.get("deferred") or t["name"] in _activated_tools
    ]


def get_deferred_tool_names(all_tools: list[ToolDef] | None = None) -> list[str]:
    tools = all_tools if all_tools is not None else tool_definitions
    return [t["name"] for t in tools if t.get("deferred") and t["name"] not in _activated_tools]


# --- Permissions -----------------------------------------------------------

def check_permission(
    tool_name: str,
    inp: dict,
    mode: str = "default",
    plan_file_path: str | None = None,
) -> dict:
    """Return {"action": "allow"|"deny"|"confirm", "message": ...}.

    Creating or evolving a skill changes durable behaviour, so those two ask the
    user first; everything else - including business tools - is allowed here.
    The business and web layers own their own confirmation flows. The mode and
    plan_file_path arguments are kept so the original signature still works.
    """
    if tool_name == "skill_evolve":
        return {"action": "confirm", "message": f"evolve skill: {inp.get('skill_name', '')}"}
    if tool_name == "skill_create":
        return {"action": "confirm", "message": f"create skill: {inp.get('name', '')}"}
    return {"action": "allow"}


# --- Tool execution --------------------------------------------------------

MAX_RESULT_CHARS = 50000


def _truncate_result(result: str) -> str:
    if len(result) <= MAX_RESULT_CHARS:
        return result
    keep_each = (MAX_RESULT_CHARS - 60) // 2
    return (
        result[:keep_each]
        + f"\n\n[... truncated {len(result) - keep_each * 2} chars ...]\n\n"
        + result[-keep_each:]
    )


async def execute_tool(
    name: str, inp: dict, state: dict[str, float] | None = None
) -> str:
    """Execute a built-in tool by name.

    The agent and skill tools are dispatched by the Agent class before reaching
    this function, to avoid a circular import. Unknown names return a plain
    string instead of raising, so a hallucinated tool call never breaks the
    conversation.
    """
    if name == "skill_evolve":
        try:
            from mellowday.runtime.skills import evolve_skill
        except Exception:
            return "Skills are unavailable in this runtime."

        result = evolve_skill(
            skill_name=inp.get("skill_name", ""),
            lesson=inp.get("lesson", ""),
            rationale=inp.get("rationale", ""),
            target=inp.get("target", "active"),
        )
        return _truncate_result(json.dumps(result, ensure_ascii=False, indent=2))

    if name == "skill_create":
        try:
            from mellowday.runtime.skills import create_skill
        except Exception:
            return "Skills are unavailable in this runtime."

        result = create_skill(
            name=inp.get("name", ""),
            description=inp.get("description", ""),
            instructions=inp.get("instructions", ""),
            when_to_use=inp.get("when_to_use", "") or inp.get("when-to-use", ""),
            target=inp.get("target", "project"),
            context=inp.get("context", "inline"),
            user_invocable=bool(inp.get("user_invocable", False)),
            allowed_tools=inp.get("allowed_tools"),
            evidence=inp.get("evidence", ""),
        )
        return _truncate_result(json.dumps(result, ensure_ascii=False, indent=2))

    return f"Unknown tool: {name}"


def reset_permission_cache() -> None:
    """Kept for callers that reset runtime caches; no rule files are loaded now."""
    return None
