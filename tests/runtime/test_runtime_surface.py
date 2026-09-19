"""Surface tests for the ported runtime modules.

They cover the I02 acceptance points that do not need a model at all: the
package imports, the trimmed tool surface, the absence of terminal I/O, and the
session / prompt / memory plumbing under MELLOWDAY_DATA_DIR.
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

import pytest

import mellowday.runtime as runtime_pkg
from mellowday import paths
from mellowday.runtime import memory, sessions, tools
from mellowday.runtime.prompt import build_system_prompt

RUNTIME_DIR = Path(runtime_pkg.__file__).resolve().parent


# --- package surface --------------------------------------------------------

def test_runtime_package_imports_all_ported_modules():
    import mellowday.runtime.agent  # noqa: F401
    import mellowday.runtime.mcp_client  # noqa: F401
    import mellowday.runtime.memory  # noqa: F401
    import mellowday.runtime.prompt  # noqa: F401
    import mellowday.runtime.session_memory  # noqa: F401
    import mellowday.runtime.sessions  # noqa: F401
    import mellowday.runtime.subagent  # noqa: F401
    import mellowday.runtime.tools  # noqa: F401


def test_runtime_modules_have_no_terminal_dependencies():
    banned = [
        (re.compile(r"(?<![\w.])print\s*\("), "print("),
        (re.compile(r"(?<![\w.])input\s*\("), "input("),
        (re.compile(r"sys\.stdout"), "sys.stdout"),
        (re.compile(r"^\s*import rich|^\s*from rich", re.MULTILINE), "rich"),
        (re.compile(r"^\s*from agents|^\s*import agents", re.MULTILINE), "source package import"),
        (re.compile(r"\btqdm\b"), "tqdm"),
    ]
    offenders = []
    for path in sorted(RUNTIME_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for pattern, label in banned:
            if pattern.search(text):
                offenders.append(f"{path.name}: {label}")
    assert offenders == []


def test_tools_exports_the_contract_surface():
    for name in (
        "ToolDef",
        "tool_definitions",
        "execute_tool",
        "check_permission",
        "CONCURRENCY_SAFE_TOOLS",
        "get_active_tool_definitions",
        "get_deferred_tool_names",
        "reset_activated_tools",
        "reset_permission_cache",
    ):
        assert hasattr(tools, name), name

    names = {t["name"] for t in tools.tool_definitions}
    assert {"skill", "skill_create", "skill_evolve", "compact_context"} <= names

    # The coding-assistant tool set must be gone.
    assert names.isdisjoint(
        {"read_file", "write_file", "edit_file", "list_files", "grep_search", "run_shell", "tool_search"}
    )
    assert not hasattr(tools, "is_dangerous")
    source = Path(tools.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "os.system" not in source


def test_permission_actions():
    assert tools.check_permission("skill_create", {"name": "x"})["action"] == "confirm"
    assert tools.check_permission("skill_evolve", {"skill_name": "x"})["action"] == "confirm"
    assert tools.check_permission("compact_context", {})["action"] == "allow"
    assert tools.check_permission("now", {})["action"] == "allow"


@pytest.mark.anyio
async def test_unknown_builtin_tool_returns_a_message():
    result = await tools.execute_tool("nope", {})
    assert result == "Unknown tool: nope"


def test_deferred_tools_are_hidden_until_activated():
    tools.reset_activated_tools()
    active = {t["name"] for t in tools.get_active_tool_definitions()}
    assert "agent" not in active
    assert "agent" in tools.get_deferred_tool_names()
    assert "skill" in active


# --- sessions ---------------------------------------------------------------

def test_session_round_trip_stays_under_the_data_dir():
    sessions.save_session(
        "sess-1",
        {
            "metadata": {"id": "sess-1", "startTime": "2026-01-01T00:00:00Z", "model": "test-model"},
            "openaiMessages": [{"role": "user", "content": "hi"}],
        },
    )
    loaded = sessions.load_session("sess-1")
    assert loaded is not None
    assert loaded["metadata"]["id"] == "sess-1"
    assert sessions.get_latest_session_id() == "sess-1"
    assert [s["id"] for s in sessions.list_sessions()] == ["sess-1"]

    sessions.save_folded_session_memory("sess-1", {"trigger": "auto", "episode_memory": {}})
    assert (paths.sessions_dir() / "sess-1.folded-memory.latest.json").exists()
    assert (paths.sessions_dir() / "sess-1.folded-memory.jsonl").exists()

    assert paths.data_dir() in (paths.sessions_dir() / "sess-1.json").parents


def test_load_missing_session_returns_none():
    assert sessions.load_session("does-not-exist") is None


# --- prompt / memory --------------------------------------------------------

def test_system_prompt_is_the_assistant_prompt():
    text = build_system_prompt()
    assert "MellowDay" in text
    assert datetime.date.today().isoformat() in text

    lowered = text.lower()
    for banned in ("claude.md", "git branch", "git status", "repository", "read_file", "run_shell"):
        assert banned not in lowered


def test_system_prompt_survives_a_missing_skills_package():
    # mellowday.runtime.skills is owned by a parallel unit; its absence must not
    # break prompt construction.
    assert isinstance(build_system_prompt(), str)


def test_memory_helpers_use_the_data_dir():
    assert memory.get_memory_dir() == paths.memory_dir()
    assert paths.data_dir() in memory.get_memory_dir().parents

    memory.save_memory("Likes tea", "prefers tea over coffee", "user", "User prefers tea.")
    entries = memory.list_memories()
    assert [e.name for e in entries] == ["Likes tea"]
    assert (paths.memory_dir() / "MEMORY.md").exists()
    assert "Memory System" in memory.build_memory_prompt_section()

    assert memory.delete_memory(entries[0].filename) is True
    assert memory.list_memories() == []


@pytest.mark.anyio
async def test_mcp_manager_without_config_does_not_block_or_raise():
    from mellowday.runtime.mcp_client import McpManager

    manager = McpManager()
    await manager.load_and_connect()
    assert manager.get_tool_definitions() == []
    assert manager.is_mcp_tool("mcp__server__tool") is True
    assert manager.is_mcp_tool("add_todo") is False
    await manager.disconnect_all()


def test_large_tool_results_are_persisted_under_the_data_dir():
    from mellowday.runtime import sessions as session_store
    from mellowday.runtime.agent import Agent

    agent = Agent(model="test-model", api_base="http://127.0.0.1:9/v1", api_key="test-key")
    agent.session_id = "surface-1"
    big = "x" * 40000
    persisted = agent._persist_large_result("add_todo", big)

    assert "Result too large" in persisted
    files = list((paths.data_dir() / "tool_results").glob("*/*.txt"))
    assert len(files) == 1
    assert files[0].read_text(encoding="utf-8") == big
    assert paths.data_dir() in files[0].parents

    # 占位提示里给出 ref，模型据此用运行时的取回工具读原文
    ref = files[0].stem
    assert f'ref "{ref}"' in persisted
    page = session_store.read_tool_artifact("surface-1", ref, offset=0, limit=20000)
    assert page["ok"] is True
    assert page["total_chars"] == len(big)
    assert page["text"] == big[:20000]
    assert page["has_more"] is True
    # 默认一次读取也是有界的，不会把整个大结果塞回上下文
    assert session_store.read_tool_artifact("surface-1", ref)["returned"] == 4000

    assert agent._persist_large_result("add_todo", "small") == "small"
    assert agent._generate_plan_file_path().startswith(str(paths.data_dir()))


@pytest.mark.anyio
async def test_chinese_content_round_trips_through_memory_and_sessions():
    """The host locale is cp936; every runtime file read/write must be utf-8."""
    # Two Chinese names must not collapse onto the same file.
    memory.save_memory("喝茶", "用户喜欢喝茶", "user", "用户偏好：喜欢喝茶，不喜欢咖啡。")
    memory.save_memory("咖啡", "用户不喜欢咖啡", "user", "用户不喜欢咖啡。")

    entries = memory.list_memories()
    assert {e.name for e in entries} == {"喝茶", "咖啡"}
    tea = next(e for e in entries if e.name == "喝茶")
    assert "喜欢喝茶" in tea.content
    assert "喝茶" in memory.load_memory_index()
    assert "喝茶" in memory.format_memory_manifest(memory.scan_memory_headers())

    # Recall reads the memory file back with an explicit encoding.
    async def side_query(system: str, user_text: str) -> str:
        return json.dumps({"selected_memories": [tea.filename]}, ensure_ascii=False)

    recalled = await memory.select_relevant_memories("我平时喜欢喝什么？", side_query, set())
    assert len(recalled) == 1
    assert "喜欢喝茶" in recalled[0].content

    # Sessions keep Chinese history and folded memory intact.
    sessions.save_session(
        "中文会话",
        {
            "metadata": {"id": "中文会话", "startTime": "2026-01-01T00:00:00Z"},
            "openaiMessages": [{"role": "user", "content": "帮我整理今天的会议纪要"}],
        },
    )
    loaded = sessions.load_session("中文会话")
    assert loaded["openaiMessages"][0]["content"] == "帮我整理今天的会议纪要"

    sessions.save_folded_session_memory(
        "中文会话", {"trigger": "auto", "episode_memory": {"task_description": "整理会议纪要"}}
    )
    latest = json.loads(
        (paths.sessions_dir() / "中文会话.folded-memory.latest.json").read_text(encoding="utf-8")
    )
    assert latest["episode_memory"]["task_description"] == "整理会议纪要"

    # Restoring a session must not mangle Chinese either.
    from mellowday.runtime.agent import Agent

    agent = Agent(model="test-model", api_base="http://127.0.0.1:9/v1", api_key="test-key")
    agent.restore_session({"openaiMessages": [{"role": "user", "content": "提醒我下午三点开会"}]})
    assert agent._openai_messages[-1]["content"] == "提醒我下午三点开会"


def test_subagent_configs_stay_read_only_for_explore_and_plan():
    from mellowday.runtime import subagent

    subagent.reset_agent_cache()
    explore = {t["name"] for t in subagent.get_sub_agent_config("explore")["tools"]}
    general = {t["name"] for t in subagent.get_sub_agent_config("general")["tools"]}
    assert explore <= subagent.READ_ONLY_TOOLS
    assert "agent" not in general
