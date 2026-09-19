#!/usr/bin/env python3
"""Event-driven conversation runtime for MellowDay.

The conversation loop, retry/backoff, tool scheduling, context-compaction
pipeline, skill injection and session persistence are kept as they were.
Terminal input/output is gone: every user-visible message is emitted through
mellowday.runtime.events. Business tools are routed to a caller-supplied
tool_executor instead of being hard-coded here.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Callable, Awaitable, Any

import anthropic
import openai

from mellowday import paths
from mellowday.runtime.mcp_client import McpManager
from mellowday.runtime.memory import (
    MAX_SUPERSEDED_FACTS,
    active_fact_records,
    diff_fact_state,
    fact_snapshot,
    fact_supersession_hook,
    format_memories_for_injection,
    recall_facts,
    strip_fact_reminders,
)
from mellowday.runtime.prompt import build_system_prompt
from mellowday.runtime.session_memory import (
    FOLD_SESSION_MEMORY_SYSTEM,
    build_anthropic_transcript,
    build_folding_user_prompt,
    build_openai_transcript,
    fallback_folded_memory,
    format_folded_memory,
    parse_folded_memory,
)
from mellowday.runtime.sessions import (
    read_tool_artifact,
    save_folded_session_memory,
    save_session,
    save_tool_artifact,
)
from mellowday.runtime.subagent import get_sub_agent_config
from mellowday.runtime.tools import ToolDef, tool_definitions, execute_tool, CONCURRENCY_SAFE_TOOLS, check_permission, \
    get_active_tool_definitions
from mellowday.runtime.events import print_info, print_divider, print_assistant_text, print_sub_agent_start, print_sub_agent_end, \
    start_spinner, stop_spinner, print_cost, print_tool_call, print_confirmation, print_retry, \
    print_error, print_warning, emit_skill_event, emit


# 指数退避重试


def _is_retryable(error: Exception) -> bool:
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status in (429, 503, 529):
        return True
    msg = str(error)
    if "overloaded" in msg or "ECONNRESET" in msg or "ETIMEDOUT" in msg:
        return True
    return False


def _safe_utf8_text(value: object) -> str:
    return str(value).encode("utf-8", errors="replace").decode("utf-8")


def _sanitize_for_utf8(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_utf8_text(value)
    if isinstance(value, list):
        return [_sanitize_for_utf8(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_for_utf8(item) for item in value)
    if isinstance(value, dict):
        return {
            _sanitize_for_utf8(key): _sanitize_for_utf8(item)
            for key, item in value.items()
        }
    return value


async def _with_retry(fn, max_retries: int = 3):
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as error:
            if attempt >= max_retries or not _is_retryable(error):
                raise
            delay = min(1000 * (2 ** attempt), 30000) / 1000 + (hash(str(time.time())) % 1000) / 1000
            status = getattr(error, "status_code", None) or getattr(error, "status", None)
            reason = f"HTTP {status}" if status else (getattr(error, "code", None) or "network error")
            print_retry(attempt + 1, max_retries, reason)
            await asyncio.sleep(delay)

MODEL_CONTEXT = {
    "claude-opus-4-6": 200000,
    "claude-sonnet-4-6": 200000,
    "claude-sonnet-4-20250514": 200000,
    "claude-haiku-4-5-20251001": 200000,
    "claude-opus-4-20250514": 200000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "deepseek-chat":200000,
    "deepseek-v4-pro":200000,
    "deepseek-flash":200000,
    "deepseek-reasoner":200000,
}

def _get_context_windows(model:str)->int:
    return MODEL_CONTEXT.get(model, 200000)


#多层级压缩常数
SNIP_THRESHOLD = 0.60
AUTO_COMPACT_THRESHOLD = 0.70
SNIP_PLACEHOLDER = "[Content snipped - re-read if needed]"
SNIPPABLE_TOOLS = {"read_file", "grep_search", "list_files", "run_shell"}
MICROCOMPACT_IDLE_S = 5 * 60  # 5 minutes

KEEP_RECENT_RESULTS = 3



def _get_max_output_tokens(model: str) -> int:
    m = model.lower()
    if "opus-4-6" in m:
        return 64000
    if "sonnet-4-6" in m:
        return 32000
    if any(x in m for x in ("opus-4", "sonnet-4", "haiku-4")):
        return 32000
    return 16384

#转换tool的形式到openai
def _to_openai_tools(tools: list[ToolDef]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


#: 过长工具结果的取回工具。定义在运行时（而不是业务工具目录）里，因为它的作用域是
#: 「本次会话自己落盘的工具产物」：ref 只能来自运行时给出的占位提示，没有任何参数可以
#: 指定文件路径，所以它不会把被删除的文件读取能力带回来。执行点在 Agent._read_tool_result。
READ_TOOL_RESULT_DEF: dict = {
    "name": "read_tool_result",
    "description": (
        "读取本会话某次工具调用被判定为过长、因此只给了 ref 的结果原文。"
        "用 offset+limit 分页读取，或用 query 直接定位长结果中间的目标内容。"
        "只能读取运行时保存的工具产物，不能读取任何文件路径。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "过长结果提示里给出的 ref（形如 <session>-<时间>-<工具>-<随机后缀>）",
            },
            "offset": {
                "type": "integer",
                "minimum": 0,
                "description": "从第几个字符开始返回，默认 0",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20000,
                "description": "本次最多返回多少字符，默认 4000",
            },
            "query": {
                "type": "string",
                "description": "要在原文中定位的文本；给出后返回它附近的一段，忽略 offset/limit",
            },
        },
        "required": ["ref"],
        "additionalProperties": False,
    },
}


class Agent:
    def __init__(self,
                 *,
                 permission_mode:str="default",
                 model:str="deepseek-chat",
                 api_base: str | None=None,
                 anthropic_base_url: str | None=None,
                 api_key: str | None=None,
                 thinking: bool=False,
                 max_cost_usd: float | None=None,
                 max_turns: int | None=None,
                 confirm_fn:Callable[[str], Awaitable[bool]] | None=None,
                 custom_system_prompt: str | None=None,
                 custom_tools: list[ToolDef] | None=None,
                 tool_executor: Callable[[str, dict], Awaitable[str]] | None=None,
                 fact_provider: Callable[[str], Awaitable[list[dict]]] | None=None,
                 is_sub_agent: bool=False,
                 product_mode: bool=False,):
        self.product_mode = product_mode
        self.permission_mode = permission_mode
        self.thinking = thinking
        self.model = model
        self.use_openai = bool(api_base)
        self.is_sub_agent = is_sub_agent
        self.tools = list(custom_tools) if custom_tools is not None else list(tool_definitions)
        if not any(tool.get("name") == "read_tool_result" for tool in self.tools):
            #运行时工具：取回过长工具结果的原文，作用域仅限本会话自己落盘的工具产物。
            self.tools.append(dict(READ_TOOL_RESULT_DEF))
        #业务工具由调用方执行：名字来自 custom_tools，实际执行交给 tool_executor。
        self.tool_executor = tool_executor
        #事实来源（I22）：fact_provider(query) 返回候选事实记录（SQLite memories，只含 active）。
        #由调用方注入（web 层把 Store 的检索封进来）；未注入时运行时不召回，也不报错。
        self.fact_provider = fact_provider
        self._custom_tool_names = {t["name"] for t in (custom_tools or [])}
        self.max_cost_usd = max_cost_usd
        self.max_turns = max_turns
        self.confirm_fn = confirm_fn
        self._custom_system_prompt = custom_system_prompt
        self.effective_window=_get_context_windows(model) -20000
        self.session_id = uuid.uuid4().hex[:8]
        self.session_start_time= time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime())

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.last_input_token_count = 0
        self.current_turns = 0
        self.last_api_call_time = 0


        self._aborted = False
        #本轮经由记忆工具写进事实库的记录：写入期去重的输入（CONTRACTS 6quater.1）。
        #存储异步任务
        self._current_task:asyncio.Task | None = None
        #权限白名单
        self._confirmed_paths: set[str] = set()


        # 计划模式”（Plan Mode）状态的变量
        self._pre_plan_mode: str | None=None
        self._plan_file_path: str | None=None
        self._plan_approval_fn : Callable[[str], Awaitable[bool]] | None=None
        self._context_cleared : bool=False

        #思考模式
        self._thinking_mode = self._resolve_thinking_mode()

        #子agent的输出缓存
        self._output_buffer: list[str] | None=None
        self._turn_output_buffer: list[str] | None = None

        #MCP集成
        self._mcp_manager = McpManager()
        self._mcp_initialized = False

        #记忆回溯
        #记忆agent已经回答过的信息
        self._already_surfaced_memories: set[str] = set()
        #当前会话占用的字节数
        self._session_memory_bytes = 0

        #区分message的历史消息
        self._anthropic_messages: list[str] = []
        self._openai_messages: list[str] = []
        self._last_retrieved_skill_reference: dict[str, Any] | None = None
        self._last_retrieved_skill_hits: list[dict[str, Any]] = []
        self._pending_skill_extraction_window: dict[str, Any] | None = None
        self._background_skill_tasks: set[asyncio.Task] = set()
        self._folded_session_memories: list[dict[str, Any]] = []
        self._fold_last_time: float = 0.0
        self._fold_count: int = 0
        self._tool_error_streak: int = 0
        self._same_tool_repeat_count: int = 0
        self._last_tool_name: str = ""

        #事实失效关系（I22/D）：已提供给模型的当前值 -> 值；失效旧值清单（有界）。
        #两者随会话文件保存，折叠与重启都不丢，因此恢复后仍然知道哪个旧值已经过期。
        self._observed_facts: dict[str, dict[str, Any]] = {}
        self._superseded_facts: list[dict[str, Any]] = []

        #构建系统提示词
        self._base_system_prompt = custom_system_prompt or build_system_prompt()

        if self.permission_mode == "plan":
            self._plan_file_path = self._generate_plan_file_path()
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
        else:
            self._system_prompt = self._base_system_prompt

        #初始化大模型客户端
        if self.use_openai:
            # OpenAI 兼容端点常常在本地运行且不需要密钥，但 SDK 要求非空值。
            self._openai_client = openai.AsyncOpenAI(
                base_url=api_base,
                api_key=api_key or os.environ.get("OPENAI_API_KEY") or "not-required",
            )
            self._anthropic_client = None
            self._openai_messages.append({"role": "system", "content": self._system_prompt})
        else:
            kwargs : dict[str,Any] = {}
            if api_key:
                kwargs["api_key"] = api_key
            if anthropic_base_url:
                kwargs["base_url"] = anthropic_base_url
            self._anthropic_client = anthropic.AsyncAnthropic(**kwargs)
            self._openai_client = None

        self._refresh_runtime_system_prompt()

    #判断返回模型的思考模式
    def _resolve_thinking_mode(self) -> str:
        if not self.thinking:
            return "disabled"
        if not self._model_supports_thinking():
            return "disabled"

        if self._model_supports_adaptive_thinking():
            return "adaptive"
        return "enabled"

    def _model_supports_thinking(self) -> bool:
        m = self.model.lower()
        if "claude-3-" in m or "3-5-" in m or "3-7-" in m:
            return False
        if "claude" in m and any(x in m for x in ("opus", "sonnet", "haiku")):
            return True
        return False
    def _model_supports_adaptive_thinking(self) -> bool:
        m = self.model.lower()
        return "opus-4-6" in m or "sonnet-4-6" in m

    #生成一个用于保存 AI 计划（Plan）的 Markdown 文件的绝对路径。
    def _generate_plan_file_path(self) -> str:
        d = paths.data_dir() / "plans"
        d.mkdir(parents=True, exist_ok=True)
        return str(d / f"plan-{self.session_id}.md")

    def _build_plan_mode_prompt(self) -> str:
        return f"""

    # Plan Mode Active

    Plan mode is active. You MUST NOT change any stored record or take any irreversible action while planning.

    ## Planning Notes File: {self._plan_file_path}
    This session's planning notes file is recorded above. Present the plan itself in your reply so the user can review it.

    ## Workflow
    1. **Gather**: collect the facts you need using the tools available to you.
    2. **Design**: decide the concrete steps, naming the records and dates involved.
    3. **Present**: write a structured plan in your reply:
       - **Context**: Why this is needed
       - **Steps**: What will change, record by record
       - **Verification**: How the user can check the result
    4. **Exit**: Call exit_plan_mode when your plan is ready for user review.

    IMPORTANT: When your plan is complete, you MUST call exit_plan_mode. Do NOT ask the user to approve — exit_plan_mode handles that."""

    #判断当前的任务所有的任务是否完成
    @property
    def is_processing(self)->bool:
        return self._current_task is not None and not self._current_task.done()

    #大模型调用的工厂方法,构建一个用于记忆召回（memory recall）的 sideQuery 可调用对象，兼容anthropic, openai。
    def _build_side_query(self, *, max_tokens: int = 256):
        if self._anthropic_client:
            client = self._anthropic_client
            model = self.model
            async def _sq(system:str, user_message:str)->str:

                resp = await client.messages.create(
                    model=model, max_tokens=max(1, int(max_tokens)), system=system,
                messages=[{"role": "user", "content": user_message}],
                )
                text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
                if not text.strip():
                    block_types = [str(getattr(b, "type", "")) for b in getattr(resp, "content", [])]
                    logging.warning(
                        "side_query returned empty Anthropic-compatible response: model=%s stop_reason=%s content_block_types=%s",
                        getattr(resp, "model", model),
                        getattr(resp, "stop_reason", ""),
                        block_types,
                    )
                return text
            return _sq
        if self._openai_client:
            client = self._openai_client
            model = self.model
            async def _sq_openai(system:str, user_message:str)->str:
                resp = await client.chat.completions.create(
                    model=model,
                    max_tokens=max(1, int(max_tokens)),
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_message},
                    ],

                )
                if not resp.choices:
                    logging.warning("side_query returned no OpenAI-compatible choices: model=%s", model)
                    return ""
                choice = resp.choices[0]
                content = choice.message.content or ""
                if not content.strip():
                    logging.warning(
                        "side_query returned empty OpenAI-compatible response: model=%s finish_reason=%s message=%s",
                        model,
                        getattr(choice, "finish_reason", ""),
                        choice.message,
                    )
                return content
            return _sq_openai
        return None
    #异步任务取消（Abort）
    def abort(self) -> None:
        self._aborted = True
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    def set_confirm_fn(self, fn:Callable[[str], Awaitable[bool]]) -> None:
        self.confirm_fn = fn

    def set_plan_approval_fn(self, fn:Callable[[str], Awaitable[bool]]) -> None:
        self._plan_approval_fn = fn


    #计划模式开关（“状态切换与现场保护”机制）
    def toggle_plan_mode(self) -> str:
        """
               1. 退出计划模式（从 plan 切回原模式）
               当当前模式已经是 plan 时，执行 if 分支：
               恢复之前的状态：self.permission_mode = self._pre_plan_mode or "default"。
                   在进入计划模式时，程序会把原本的模式保存在 _pre_plan_mode 里。退出时，就把它重新拿出来赋值回去，恢复到切换前的状态。
               清理计划模式的痕迹：把 _pre_plan_mode 和 _plan_file_path（计划文件路径）清空，并将系统提示词 _system_prompt 恢复为最基础的 _base_system_prompt。
               同步 OpenAI 消息：如果底层使用的是 OpenAI 接口，它还会同步更新消息列表里的第一条系统提示词，确保 AI 的上下文也跟着切换回来。
               反馈返回：打印退出提示，并返回恢复后的模式名称。

               2. 进入计划模式（从其他模式切入 plan）
       当当前模式不是 plan 时，执行 else 分支：
       保护当前现场：self._pre_plan_mode = self.permission_mode。先把当前正在使用的模式（比如正常模式或自动接受模式）暂存起来，方便以后能原路返回。
       切换并初始化：将当前模式设为 "plan"，生成一个专属的计划文件路径，并扩展系统提示词。通过拼接 _build_plan_mode_prompt()，给 AI 注入“只动脑不动手、输出结构化计划”的专属指令。
       同步 OpenAI 消息：同样地，如果使用 OpenAI，也会实时更新上下文里的系统提示词。
       反馈与返回：打印进入提示（包含计划文件的路径），并返回 "plan"。
        """
        if self.product_mode:
            return self.permission_mode
        if self.permission_mode == "plan":
            self.permission_mode = self._pre_plan_mode or "default"
            self._pre_plan_mode = None
            self._plan_file_path = None
            self._system_prompt = self._base_system_prompt
            if self.use_openai and self._openai_messages:
                self._openai_messages[0]["content"] =self._system_prompt
            print_info(f"Exited plan mode -> {self.permission_mode} mode")
            return self.permission_mode
        else:
            self._pre_plan_mode = self.permission_mode
            self.permission_mode = "plan"
            self._plan_file_path = self._generate_plan_file_path()
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
            print_info(f"Entered plan mode. Plan file: {self._plan_file_path}")
            return "plan"

    def get_token_usage(self) -> dict:
        return {"input":self.total_input_tokens, "output":self.total_output_tokens}

    #主入口

    async def  chat(self, user_message:str)->None:
        # Adopt user-managed conversation settings before the first model call,
        # including turns that produce no tool calls at all.
        self._persona_query = _safe_utf8_text(user_message)
        self._refresh_runtime_system_prompt()
        #懒加载MCP服务在第一次chat的时候
        if not self._mcp_initialized and not self.is_sub_agent and not self.product_mode:
            self._mcp_initialized = True
            try:
                await self._mcp_manager.load_and_connect()
                mcp_defs = self._mcp_manager.get_tool_definitions()
                if mcp_defs:
                    self.tools = self.tools + mcp_defs
            except Exception as e:
                print_error(f"MCP init failed: {e}")

        original_user_message = _safe_utf8_text(user_message)
        ready_skill_extraction_window: dict[str, Any] | None = None
        self._last_retrieved_skill_reference = None
        self._last_retrieved_skill_hits = []
        if not self.is_sub_agent:
            ready_skill_extraction_window = self._pop_pending_skill_extraction_window(original_user_message)
            user_message, self._last_retrieved_skill_reference = self._augment_user_message_with_skill_context(
                original_user_message
            )

        self._aborted = False
        self._turn_output_buffer = []
        #本轮的记忆工具写入从零开始计；上一轮的记录已经进了上一轮的提取窗口。
        #事实召回用用户的原话（不含技能上下文拼接），中文原句直接参与词项匹配。
        coro = (
            self._chat_openai(user_message, original_user_message)
            if self.use_openai
            else self._chat_anthropic(user_message, original_user_message)
        )
        self._current_task = asyncio.create_task(coro)
        try:
            await self._current_task
        except asyncio.CancelledError:
            self._aborted = True

        finally:
            self._current_task = None
        assistant_text = "".join(self._turn_output_buffer or []).strip()
        self._turn_output_buffer = None
        if not self.is_sub_agent and not self._aborted:
            self._schedule_background_skill_task(self._run_skill_usage_tracking(original_user_message, assistant_text))
            if ready_skill_extraction_window:
                #同一纠正窗口内写进事实库的记录：窗口那一轮 + 本轮（技能正是在本轮落盘）。
                self._schedule_background_skill_task(
                    self._run_online_skill_evolution(ready_skill_extraction_window),
                    stage="online_skill_evolution",
                )
            self._set_pending_skill_extraction_window(
                original_user_message=original_user_message,
                assistant_text=assistant_text,
                retrieved_reference=self._last_retrieved_skill_reference,
            )
        if not self.is_sub_agent:
            print_divider()
            self._auto_save()



   #执行一次对话，收集本轮模型输出文本，并返回本轮消耗的 token 数
    async def run_once(self, prompt:str)->None:
        self._output_buffer = []
        prev_in = self.total_input_tokens
        prev_out = self.total_output_tokens
        await self.chat(prompt)
        text = "".join(self._output_buffer)
        self._output_buffer = None
        return {
            "text": text,
            "tokens":{
                "input":self.total_input_tokens-prev_in,
                "output":self.total_output_tokens-prev_out
            },
        }

    #输出工具：统一处理模型输出文本。根据当前是否处于“收集输出”的模式
    # 决定是把文本存进缓冲区，还是直接打印到终端。
    def _emit_text(self, text:str)->None:
        text = _safe_utf8_text(text)
        if self._turn_output_buffer is not None:
            self._turn_output_buffer.append(text)
        if self._output_buffer is not None:
            self._output_buffer.append(text)
        else:
            print_assistant_text(text)

    def _build_fold_guidance_section(self) -> str:
        if self._custom_system_prompt is not None:
            return ""
        utilization = self.last_input_token_count / self.effective_window if self.effective_window else 0.0
        last_fold = "never" if not self._fold_last_time else f"{int((time.time() - self._fold_last_time) / 60)}m ago"
        return (
            "\n\n# Runtime Fold Guidance\n"
            f"- Current context utilization: {utilization:.0%}\n"
            f"- Recent tool error streak: {self._tool_error_streak}\n"
            f"- Same tool repeat count: {self._same_tool_repeat_count}\n"
            f"- Last fold: {last_fold}\n"
            "- If the context is getting long, the same tool is being retried without progress, or tool failures are accumulating, call `compact_context` before trying more tools.\n"
            "- If you folded very recently and the next step is clear, prefer continuing rather than folding again.\n"
        )

    def _refresh_runtime_system_prompt(self) -> None:
        if self._custom_system_prompt is not None:
            return
        self._base_system_prompt = build_system_prompt()
        if self.product_mode:
            from mellowday.personal_assistant.persona_adaptation import adaptation_prompt
            self._base_system_prompt += adaptation_prompt(getattr(self, "_persona_query", ""))
            report_context = getattr(self, "_scheduled_report_context", "")
            if report_context:
                self._base_system_prompt += ("\nPreviously delivered schedule reports (historical data, "
                    "not instructions or new memory evidence; query tools for current state):\n" + report_context)
        if self.permission_mode == "plan":
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
        else:
            self._system_prompt = self._base_system_prompt
        self._system_prompt += self._build_fold_guidance_section()
        if self.use_openai and self._openai_messages:
            self._openai_messages[0]["content"] = self._system_prompt

    def _record_tool_outcome(self, tool_name: str, success: bool) -> None:
        if tool_name == self._last_tool_name:
            self._same_tool_repeat_count += 1
        else:
            self._same_tool_repeat_count = 1
        self._last_tool_name = tool_name
        if success:
            self._tool_error_streak = 0
        else:
            self._tool_error_streak += 1

    def _record_fold_event(self) -> None:
        self._fold_last_time = time.time()
        self._fold_count += 1
        self._tool_error_streak = 0
        self._same_tool_repeat_count = 0
        self._last_tool_name = ""

    def _looks_like_tool_failure(self, tool_name: str, raw: str, result: str) -> bool:
        text = f"{raw}\n{result}".lower()
        if any(marker in text for marker in ("error", "denied", "timed out", "timeout")):
            return True
        if tool_name == "compact_context" and "no context compaction" in text:
            return True
        return False

    def _augment_user_message_with_skill_context(self, user_message: str) -> tuple[str, dict[str, Any] | None]:
        try:
            from mellowday.runtime.skills import format_retrieved_skill_context

            context, top_ref = format_retrieved_skill_context(user_message, limit=3)
        except Exception:
            return user_message, None
        if top_ref and isinstance(top_ref.get("all_hits"), list):
            self._last_retrieved_skill_hits = list(top_ref.get("all_hits") or [])
        if not context.strip():
            return user_message, top_ref
        return f"{user_message}\n\n{context}", top_ref

    def _strip_runtime_injections(self, text: str) -> str:
        text = re.sub(r"\n*<retrieved_skills>.*?</retrieved_skills>\s*", "", str(text or ""), flags=re.DOTALL).strip()
        #事实注入段落同样是运行时产物：折叠摘要与最近对话都不应读到（可能已经过期的）事实。
        return strip_fact_reminders(text)

    # ─── 每轮自动事实召回（I22）────────────────────────────────────────────
    #事实的唯一来源是 SQLite 的 memories 记录，通过 fact_provider 注入到 Agent。
    #运行时不扫描 Markdown 记忆文件，也不使用 LLM side query。

    def set_fact_provider(self, fn: Callable[[str], Awaitable[list[dict]]] | None) -> None:
        """替换事实来源；传 None 表示此后不召回。"""
        self.fact_provider = fn

    def _message_without_fact_reminder(self, message: dict[str, Any]) -> dict[str, Any]:
        """返回同一条消息的副本，但去掉自动注入的事实段落（不改原对象）。"""
        content = message.get("content")
        if isinstance(content, str):
            cleaned = strip_fact_reminders(content)
            return message if cleaned == content else {**message, "content": cleaned}
        if isinstance(content, list):
            blocks: list[Any] = []
            changed = False
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text") or "")
                    cleaned = strip_fact_reminders(text)
                    if cleaned != text:
                        changed = True
                        #整块只承载注入段落时直接丢弃，避免留下空文本块。
                        if not cleaned.strip():
                            continue
                        block = {**block, "text": cleaned}
                blocks.append(block)
            if changed and blocks:
                return {**message, "content": blocks}
        return message

    def _drop_previous_fact_injections(self) -> None:
        """移除上一轮注入的事实段落。

        事实被更新或删除后，旧值不得继续被使用：每轮注入新值之前先把上一轮的注入从
        历史消息里清掉，然后重置会话内的事实去重集合与注入字节计数。
        """
        for history in (self._openai_messages, self._anthropic_messages):
            for index, message in enumerate(history):
                if not isinstance(message, dict) or message.get("role") != "user":
                    continue
                cleaned = self._message_without_fact_reminder(message)
                if cleaned is not message:
                    history[index] = cleaned
        self._already_surfaced_memories.clear()
        self._session_memory_bytes = 0

    async def _inject_recalled_facts(self, history: list[dict], query: str) -> None:
        """每轮对话开始时自动召回事实，并把它注入本轮上下文。

        注入位置：本轮最后一条 user 消息的尾部，内容是一段 <system-reminder>
        （由 mellowday.runtime.memory.format_memories_for_injection 生成）。调用点在
        _chat_openai / _chat_anthropic 的第一次 _run_compression_pipeline() 之后、第一次
        模型调用之前，因此模型本轮一定看得到事实，不需要自己调用工具。

        同一段注入还承担第二件事（I22/D）：上一轮提供给模型的事实如果已经被更新或删除，
        旧值会作为「已失效」列在同一段里。历史消息（助手回复、工具结果、折叠摘要）本身
        不被改写——真实发生过的事情保持原样——但模型不会再有权把其中的旧值当成当前事实。

        fact_provider 未注入时（或子 agent）不召回也不报错；召回失败不影响本轮对话。
        """
        self._drop_previous_fact_injections()
        if self.is_sub_agent or self.fact_provider is None:
            return
        try:
            raw_candidates = await self.fact_provider(query)
        except Exception:
            return
        records_now = active_fact_records(raw_candidates)
        current = fact_snapshot(records_now)
        #校验只在「上轮确实提供过事实、而本轮候选里没有全部出现」时进行：否则会把
        #「本轮没召回」误判成「已被删除」。fact_provider("") 返回当前全部 active。
        if self._observed_facts and any(key not in current for key in self._observed_facts):
            current = await self._facts_with_full_active_set(current)
        self._record_fact_changes(current)

        try:
            memories = await recall_facts(
                query,
                self.fact_provider,
                self._already_surfaced_memories,
                self._session_memory_bytes,
                records=records_now,
            )
        except Exception:
            return
        #本轮提供给模型的值：下一轮用它们判断哪些旧值已经失效。
        for memory in memories:
            snapshot = current.get(memory.path)
            if snapshot is not None:
                self._observed_facts[memory.path] = dict(snapshot)

        injection_text = _safe_utf8_text(
            format_memories_for_injection(memories, superseded=self._superseded_facts)
        )
        if not injection_text:
            return
        if not injection_text:
            return

        last = history[-1] if history else None
        if isinstance(last, dict) and last.get("role") == "user":
            content = last.get("content")
            if isinstance(content, str):
                last["content"] = content + "\n\n" + injection_text
            elif isinstance(content, list):
                content.append({"type": "text", "text": injection_text})
            else:
                history.append({"role": "user", "content": injection_text})
        else:
            history.append({"role": "user", "content": injection_text})

        for memory in memories:
            #记录本轮已经在上下文里的事实，避免同一轮内重复注入。
            self._already_surfaced_memories.add(memory.path)
            self._session_memory_bytes += memory.size

    async def _facts_with_full_active_set(
        self, current: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        """用「全部 active」补齐失效校验集合。

        fact_provider("") 的约定是返回当前全部 active 事实（build_fact_provider 就是这样）。
        读不到时返回原集合：宁可漏报一次失效，也不能把仍然有效的事实说成已经过期。
        """
        if self.fact_provider is None:
            return current
        try:
            raw_all = await self.fact_provider("")
        except Exception:
            return current
        merged = dict(current)
        for key, value in fact_snapshot(active_fact_records(raw_all)).items():
            merged.setdefault(key, dict(value))
        return merged

    def _record_fact_changes(self, current: dict[str, dict[str, Any]]) -> None:
        """把「上一轮提供给模型、现在已经失效」的值记进失效清单。

        历史消息保持原样，因此旧值仍会出现在上下文里；这一张有界的清单是唯一能说明
        「它是历史、不是当前事实」的地方。
        """
        if not self._observed_facts:
            return
        for entry in diff_fact_state(self._observed_facts, current):
            self._observed_facts.pop(entry["key"], None)
            self._remember_superseded(entry)
        self._prune_superseded(current)

    def _remember_superseded(self, entry: dict[str, Any]) -> None:
        """登记一条失效旧值；同一个旧值只留一条，清单有上限。"""
        identity = (str(entry.get("key")), str(entry.get("detail")))
        remaining = [
            existing
            for existing in self._superseded_facts
            if (str(existing.get("key")), str(existing.get("detail"))) != identity
        ]
        remaining.append(entry)
        self._superseded_facts = remaining[-MAX_SUPERSEDED_FACTS:]

    def _prune_superseded(self, current: dict[str, dict[str, Any]]) -> None:
        """又变成当前值的旧条目从失效清单里去掉，避免把当前值标成过期。

        比对按「值」而不是只按记录 id：事实被删掉后以同样的内容重建（新 id）时，那条
        旧条目也不该继续要求模型把这句话当成历史。
        """
        live_values = {
            " ".join(str(record.get("detail") or "").split())
            for record in current.values()
            if isinstance(record, Mapping)
        }
        self._superseded_facts = [
            entry
            for entry in self._superseded_facts
            if " ".join(str(entry.get("detail") or "").split()) not in live_values
        ]

    def _message_text(self, msg: dict[str, Any]) -> str:
        content = msg.get("content")
        if isinstance(content, str):
            return self._strip_runtime_injections(content)
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(str(block.get("text") or ""))
                    elif "content" in block and block.get("type") not in {"tool_result", "tool_use"}:
                        parts.append(str(block.get("content") or ""))
            return self._strip_runtime_injections("\n".join(parts))
        return ""

    def _recent_dialog_messages(self, *, max_messages: int = 8) -> list[dict[str, str]]:
        raw_messages = self._openai_messages if self.use_openai else self._anthropic_messages
        out: list[dict[str, str]] = []
        for msg in raw_messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            text = self._message_text(msg)
            if text:
                out.append({"role": role, "content": text})
        return out[-max(2, int(max_messages)) :]

    # ─── 在线技能学习：确认接线与可见性（I24，契约 6quinquies）──────────────
    #用户明确纠正后产生的候选，写入前必须经过确认；被拒绝、跳过或失败的候选
    #写入必须通过事件在界面可见，不得静默丢弃；重复反馈合并进同一技能。

    @staticmethod
    def _skill_write_summary_parts(summary: str) -> tuple[str, str]:
        """从 online_ingest 的写入摘要里解析出 (action, 技能名)。

        技能包写的摘要是 "online skill evolution: add|merge <name>"；形状不认识
        时退回 ("", 整段摘要)，而不是丢掉信息。
        """
        text = _safe_utf8_text(summary).strip()
        tail = text.rsplit(":", 1)[-1].strip() if ":" in text else text
        action, _, name = tail.partition(" ")
        if name.strip():
            return action.strip().lower(), name.strip()
        return "", tail

    async def _ask_skill_write_confirmation(self, summary: str, *, skill: str, action: str) -> bool:
        """调用调用方提供的 confirm_fn，并把「没人可问 / 拒绝 / 确认失败」发成事件。

        网页层的 confirm_fn 自己会发出带一次性 token 的 confirmation 事件，运行时
        不重复发一条没有 token 的同类事件（前端只有带 token 的那条点得动）。
        """
        if self.confirm_fn is None:
            #没有人可以问，就不能默认放行；拒绝本身必须可见。
            emit_skill_event(
                "skill_write_denied", skill=skill, action=action,
                reason="no_confirmer", summary=summary,
            )
            return False
        try:
            approved = bool(await self.confirm_fn(summary))
        except Exception as error:
            emit_skill_event(
                "skill_write_denied", skill=skill, action=action,
                reason=f"confirm_error:{type(error).__name__}", summary=summary,
            )
            return False
        if not approved:
            emit_skill_event(
                "skill_write_denied", skill=skill, action=action,
                reason="user_denied", summary=summary,
            )
        return approved

    async def _confirm_online_skill_write(self, summary: str) -> bool:
        """可交互的在线技能写入确认（extract_now 使用）。

        bypassPermissions/acceptEdits 是用户预先给出的长期授权；plan/dontAsk 下
        没有可询问的人，一律拒绝。其余情况必须问 confirm_fn。
        """
        action, skill = self._skill_write_summary_parts(summary)
        emit_skill_event("skill_candidate_proposed", skill=skill, action=action, summary=summary)
        if self.permission_mode in {"bypassPermissions", "acceptEdits"}:
            return True
        if self.permission_mode in {"plan", "dontAsk"}:
            emit_skill_event(
                "skill_write_denied", skill=skill, action=action,
                reason=f"permission_mode:{self.permission_mode}", summary=summary,
            )
            return False
        return await self._ask_skill_write_confirmation(summary, skill=skill, action=action)

    async def _confirm_background_online_skill_write(self, summary: str) -> bool:
        """后台（回合结束后）的在线技能写入确认。

        后台写入同样必须经过确认：提供 confirm_fn 时直接 await 它（网页层会发出
        带一次性 token 的 confirmation 事件）；没有 confirm_fn 等于没有人可问，
        保持拒绝，但拒绝会变成可见事件，不再静默丢弃。
        """
        action, skill = self._skill_write_summary_parts(summary)
        emit_skill_event("skill_candidate_proposed", skill=skill, action=action, summary=summary)
        if self.confirm_fn is None and self.permission_mode in {"bypassPermissions", "acceptEdits"}:
            #预先授权自动接受，且没有人需要询问。
            return True
        return await self._ask_skill_write_confirmation(summary, skill=skill, action=action)

    def _online_evolution_enabled(self) -> bool:
        raw = os.environ.get("MELLOWDAY_AUTO_SKILL_EVOLUTION", "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def _schedule_background_skill_task(self, coro, *, stage: str = "skill_usage_tracking") -> None:
        """把学习/统计协程放到后台执行，并登记以便回合或会话结束时回收。

        stage 用于区分「在线技能演化」与「技能使用统计」：前者被跳过时要用事件
        说明原因，后者的跳过不是写入，不需要打扰用户。
        """
        if self.permission_mode == "plan":
            try:
                coro.close()
            except Exception:
                pass
            if stage == "online_skill_evolution":
                emit_skill_event("skill_candidate_skipped", stage=stage, reason="plan_mode")
            return
        task = asyncio.create_task(coro)
        self._background_skill_tasks.add(task)

        def _done(done_task: asyncio.Task) -> None:
            self._background_skill_tasks.discard(done_task)
            if done_task.cancelled():
                return
            error = done_task.exception()
            if error is None:
                return
            #后台任务失败不能静默：技能演化失败必须可见，其余只记日志。
            if stage == "online_skill_evolution":
                emit_skill_event(
                    "skill_candidate_failed", stage=stage,
                    reason=f"{type(error).__name__}: {error}"[:300],
                )
            else:
                logging.warning("background skill task failed: %s: %s", type(error).__name__, error)

        task.add_done_callback(_done)

    @property
    def has_pending_background_skill_tasks(self) -> bool:
        """是否还有后台学习/统计任务在跑。"""
        return any(not task.done() for task in self._background_skill_tasks)

    async def drain_background_skill_tasks(self, timeout: float | None = None) -> None:
        """等待后台学习任务结束；调用时机见下方说明，永不抛异常。

        调用时机：**每一轮对话结束、事件流关闭之前**，以及删除会话之前。
        在线学习在回合结束后才向用户发起确认，因此它的确认提示与
        skill_candidate_* 事件只有在事件接收器（sink）和确认通道还活着的时候
        才能到达用户；先关闭事件流再等待，学习结果会重新变成不可见。

        timeout=None（默认）等到全部结束；给一个秒数则最多等这么久，超时后
        **不取消**仍在运行的任务（它们可以继续等用户确认），只是不再阻塞调用方。
        timeout=0 等价于「只回收已经结束的任务」。

        任务自己的失败已经由 _schedule_background_skill_task 的回调转成事件，
        这里只负责等它结束，不向上抛异常。
        """
        deadline = None if timeout is None else time.monotonic() + max(0.0, float(timeout))
        while True:
            pending = [task for task in self._background_skill_tasks if not task.done()]
            if not pending:
                return
            if deadline is None:
                await asyncio.gather(*pending, return_exceptions=True)
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            #asyncio.wait 超时不会取消子任务；gather 被 wait_for 取消时会把取消传播下去。
            await asyncio.wait(pending, timeout=remaining)

    def cancel_background_skill_tasks(self) -> None:
        """取消后台学习任务，不等待（用于会话被删除等必须立刻停写的场景）。

        当学习结果还需要展示时用 drain_background_skill_tasks() 等待结束。
        """
        for task in list(self._background_skill_tasks):
            if not task.done():
                task.cancel()

    def _pop_pending_skill_extraction_window(self, next_user_feedback: str) -> dict[str, Any] | None:
        pending = self._pending_skill_extraction_window
        self._pending_skill_extraction_window = None
        if not pending:
            return None
        messages = list(pending.get("messages") or [])
        feedback = _safe_utf8_text(next_user_feedback).strip()
        if feedback:
            messages.append({"role": "user", "content": feedback})
        pending["messages"] = messages[-10:]
        pending["next_user_feedback"] = feedback
        return pending

    def _set_pending_skill_extraction_window(
        self,
        *,
        original_user_message: str,
        assistant_text: str,
        retrieved_reference: dict[str, Any] | None,
    ) -> None:
        if not original_user_message.strip() or not assistant_text.strip():
            return
        self._pending_skill_extraction_window = {
            "messages": self._recent_dialog_messages(max_messages=8),
            "latest_user": original_user_message,
            "latest_assistant": assistant_text,
            "retrieved_reference": self._compact_retrieved_reference(retrieved_reference),
            "session_id": self.session_id,
        }

    def _compact_retrieved_reference(self, ref: dict[str, Any] | None) -> dict[str, Any] | None:
        if not ref:
            return None
        return {k: v for k, v in ref.items() if k != "all_hits"}

    async def _run_online_skill_evolution(self, window: dict[str, Any], *, interactive_confirm: bool = False) -> dict[str, Any]:
        """跑一次在线学习，并把每一种结果都变成可见事件；返回技能包的结果。

        返回值的形状与 online_ingest 一致（ok/action/skill/error）；提前返回时
        返回 {"ok": False, "action": "skipped"|"failed", "error": <原因>}，调用方
        （例如 extract_now 的网页入口）据此判断到底有没有写入，不能默认成功。

        这里**没有静默分支**：每一次提前 return 都发 skill_candidate_skipped 说明
        原因；写入成功发 skill_candidate_applied；被拒绝发 skill_write_denied；
        抛错发 skill_candidate_failed。技能包负责真正的落盘与「合并而非追加」的
        判定（identity 命中或相似度达到阈值时走 evolve），运行时只负责调用与上报。
        """
        if not self._online_evolution_enabled():
            return self._report_online_skill_skip("disabled")
        if self.permission_mode == "plan":
            return self._report_online_skill_skip("plan_mode")
        messages = list(window.get("messages") or [])
        if not messages:
            return self._report_online_skill_skip("no_window")

        # Candidate JSON includes the rule and explicit source links; leave room for a complete response.
        side_query = self._build_side_query(max_tokens=4096)
        if side_query is None:
            return self._report_online_skill_skip("no_model_client")

        try:
            from mellowday.runtime.skills import online_ingest
        except Exception:
            return self._report_online_skill_skip("skills_unavailable")

        #确认回调自己会报告拒绝原因；这个标记只用于「技能包没有调用 confirm_write
        #却返回 *_denied」的兜底上报，避免出现「没有写入也没有事件」的静默结果。
        denied_reported = False
        approved_write = False
        source_facts: list[dict] = []
        if self.fact_provider is not None:
            try:
                source_facts = active_fact_records(await self.fact_provider(""))
            except Exception as error:
                print_warning(f"Source memories unavailable for skill proposal: {error}")

        async def confirm_write(summary: str) -> bool:
            nonlocal denied_reported, approved_write
            if self.product_mode and not interactive_confirm:
                from mellowday.personal_assistant.skill_consent import explicitly_authorized
                if await explicitly_authorized(messages, summary, side_query):
                    approved_write = True
                    emit_skill_event("skill_candidate_proposed", action="explicit_instruction", summary=summary)
                    return True
            confirm = (
                self._confirm_online_skill_write
                if interactive_confirm
                else self._confirm_background_online_skill_write
            )
            approved = await confirm(summary)
            approved_write = bool(approved)
            if not approved:
                denied_reported = True
            return approved

        try:
            result = await online_ingest(
                messages=messages,
                source_facts=source_facts,
                side_query=side_query,
                retrieved_reference=window.get("retrieved_reference") or None,
                hint=str(window.get("hint") or ""),
                confirm_write=confirm_write,
                target=os.environ.get("MELLOWDAY_AUTO_SKILL_TARGET", "project"),
            )
        except Exception as error:
            #学习失败绝不能影响这一轮对话（调用方在后台任务回调里吞掉异常），
            #更不能静默消失。
            reason = f"{type(error).__name__}: {error}"[:300]
            emit_skill_event(
                "skill_candidate_failed",
                skill=str((window.get("retrieved_reference") or {}).get("name") or ""),
                reason=reason,
            )
            return {"ok": False, "action": "failed", "error": reason}
        self._report_online_skill_result(result, denied_reported=denied_reported)
        if approved_write and result.get("ok") and result.get("action") in {"add", "merge"}:
            self._migrate_confirmed_source_facts(result, source_facts)
        return result

    def _migrate_confirmed_source_facts(self, result: Mapping[str, Any], sources: list[dict]) -> None:
        """Apply only the explicit record links shown in the accepted skill proposal.

        Similar text is not proof that a fact is a workflow. The provider checks
        each full snapshot again, so an edit made while confirmation was open
        cannot be overwritten by this operation.
        """
        candidate = result.get("candidate") or {}
        ids = candidate.get("source_memory_ids", []) if isinstance(candidate, Mapping) else []
        if not isinstance(ids, list) or not ids:
            return
        selected = [record for record in sources if record.get("id") in ids]
        skill = str(result.get("skill") or result.get("name") or "")
        hook = fact_supersession_hook(self.fact_provider)
        if not selected or not skill:
            return
        if hook is None:
            print_warning("Skill saved, but the selected source memories could not be migrated.")
            return
        try:
            migrated = hook(selected, skill=skill, reason="explicit source memories in confirmed skill proposal")
        except Exception as error:
            print_warning(f"Skill saved; source memory migration failed: {error}")
            return
        keys = {str(record.get("id")) for record in migrated}
        # Keep the same invalidation semantics as a fact removed by the user:
        # historical replies/results remain true records of what was said, but
        # the next request must identify their old fact values as no longer current.
        observed_sources = {key: value for key, value in self._observed_facts.items() if key in keys}
        for entry in diff_fact_state(observed_sources, {}):
            self._observed_facts.pop(entry["key"], None)
            self._remember_superseded(entry)
        if len(keys) != len(selected):
            print_warning("Some source memories changed after the proposal and were kept unchanged.")
        if keys:
            print_info(f"已将 {len(keys)} 条确认过的来源记忆归入习惯「{skill}」；原记录保留。")

    def _report_online_skill_skip(self, reason: str) -> dict[str, Any]:
        """上报一次「还没到写入就结束」的学习，并返回可判断的结果。"""
        emit_skill_event("skill_candidate_skipped", stage="online_skill_evolution", reason=reason)
        return {"ok": False, "action": "skipped", "error": reason}

    def _report_online_skill_result(self, result: dict[str, Any], *, denied_reported: bool = False) -> None:
        """把 online_ingest 的返回值翻译成可见事件与运行时状态刷新。"""
        action = str(result.get("action") or "").strip().lower()
        skill = _safe_utf8_text(result.get("skill") or "")
        if not result.get("ok"):
            if action.endswith("_denied"):
                if not denied_reported:
                    emit_skill_event(
                        "skill_write_denied", skill=skill, action=action[: -len("_denied")],
                        reason=str(result.get("error") or "denied"),
                    )
                return
            error = _safe_utf8_text(result.get("error") or result)
            emit_skill_event(
                "skill_candidate_failed", skill=skill, action=action, reason=error[:300],
            )
            print_error(f"Online skill evolution failed: {error}")
            return
        if action in {"add", "merge"}:
            self._refresh_runtime_system_prompt()
            emit_skill_event("skill_candidate_applied", skill=skill, action=action)
            print_info(f"Online skill {action}: {skill}")
            return
        if action == "discard":
            #技能包判定候选不值得写入（重复且没有新的持久价值）——属于「跳过」，
            #必须可见，但它不是一次失败。
            decision = result.get("decision") if isinstance(result.get("decision"), dict) else {}
            emit_skill_event(
                "skill_candidate_skipped", skill=skill, stage="online_skill_evolution",
                reason=_safe_utf8_text(decision.get("reason") or "no_durable_value"),
            )
        #action == "none"（本轮没有提取到候选）不是一次被丢弃的写入，不发事件。

    async def _run_skill_usage_tracking(self, original_user_message: str, assistant_text: str) -> None:
        if not self._online_evolution_enabled() or self.permission_mode == "plan":
            return
        hits = list(self._last_retrieved_skill_hits or [])
        if not hits or not assistant_text.strip():
            return
        side_query = self._build_side_query(max_tokens=700)
        try:
            from mellowday.runtime.skills import judge_retrieved_skill_usage, record_usage_judgments

            judgments = await judge_retrieved_skill_usage(
                hits=hits,
                user_message=original_user_message,
                assistant_text=assistant_text,
                side_query=side_query,
            )
            result = record_usage_judgments(judgments)
            if result.get("pruned"):
                self._refresh_runtime_system_prompt()
        except Exception:
            return

    async def extract_now(self, hint: str = "") -> dict[str, Any]:
        """立即对上一轮的对话窗口做一次可交互的技能提取。

        确认走 confirm_fn（网页层会发出带一次性 token 的 confirmation 事件）。
        返回值里的 ok 只表示「提取流程跑完」，**不能据此认为已经写入**：
        action 为 add/merge 且 written 为 True 才是真的写入成功；被拒绝时
        action 是 *_denied 并伴随 skill_write_denied 事件。
        """
        pending = self._pending_skill_extraction_window
        if not pending:
            return {"ok": False, "error": "no pending online skill extraction window"}
        window = dict(pending)
        window["hint"] = hint
        outcome = await self._run_online_skill_evolution(window, interactive_confirm=True)
        self._pending_skill_extraction_window = None
        action = str(outcome.get("action") or "")
        return {
            "ok": True,
            "action": action,
            "skill": str(outcome.get("skill") or ""),
            "written": bool(outcome.get("ok")) and action in {"add", "merge"},
        }


    def clear_history(self)->None:
        self._anthropic_messages = []
        self._openai_messages = []
        self._pending_skill_extraction_window = None
        self._last_retrieved_skill_reference = None
        self._last_retrieved_skill_hits = []
        self._fold_last_time = 0.0
        self._fold_count = 0
        self._tool_error_streak = 0
        self._same_tool_repeat_count = 0
        self._last_tool_name = ""
        if self.use_openai:
            self._openai_messages.append({"role": "system", "content":self._system_prompt})
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.last_input_token_count = 0
        print_info("Conversation cleared.")

    def show_cost(self):
        total = self._get_current_cost_usd()
        budget_info = f" / ${self.max_cost_usd} budget" if self.max_cost_usd else ""
        turn_info = f" | Turns: {self.current_turns}/{self.max_turns}" if self.max_turns else ""
        print_info(
            f"Tokens: {self.total_input_tokens} in / {self.total_output_tokens} out\n  Estimated cost: ${total:.4f}{budget_info}{turn_info}")

    #获取当前的花费，
    def _get_current_cost_usd(self) -> float:
        return (self.total_input_tokens / 1_000_000) * 3 + (self.total_output_tokens / 1_000_000) * 15

    #检查预算
    def _check_budget(self) -> dict:
        if self.max_cost_usd is not None and self._get_current_cost_usd() >= self.max_cost_usd:
            return {"exceeded": True, "reason": f"Cost limit reached (${self._get_current_cost_usd():.4f} >= ${self.max_cost_usd})"}
        if self.max_turns is not None and self.current_turns >= self.max_turns:
            return {"exceeded": True, "reason": f"Turn limit reached ({self.current_turns} >= {self.max_turns})"}
        return {"exceeded": False}

    #压缩会话
    async def compact(self)->None:
        compacted = await self._compact_conversation(trigger="manual")
        if not compacted:
            print_info("Nothing to compact yet.")


    #恢复会话信息
    def restore_session(self, data:dict)->None:
        if data.get("anthropicMessages"):
            self._anthropic_messages = self._normalize_anthropic_messages(_sanitize_for_utf8(data["anthropicMessages"]))
        if data.get("openaiMessages"):
            self._openai_messages = _sanitize_for_utf8(data["openaiMessages"])
        if isinstance(data.get("foldedSessionMemories"), list):
            self._folded_session_memories = _sanitize_for_utf8(data["foldedSessionMemories"])
        fact_state = data.get("factState")
        if isinstance(fact_state, Mapping):
            observed = fact_state.get("observed")
            if isinstance(observed, Mapping):
                self._observed_facts = {
                    str(key): dict(value)
                    for key, value in _sanitize_for_utf8(observed).items()
                    if isinstance(value, Mapping)
                }
            superseded = fact_state.get("superseded")
            if isinstance(superseded, list):
                self._superseded_facts = [
                    dict(item)
                    for item in _sanitize_for_utf8(superseded)
                    if isinstance(item, Mapping)
                ][-MAX_SUPERSEDED_FACTS:]
        print_info(f"Session restored ({self._get_message_count()} messages).")



#整理 Anthropic 的历史消息，修正部分角色错误，并丢弃不合法的工具调用消息。
    def _normalize_anthropic_messages(self, messages: list[dict]) -> list[dict]:
        role_normalized = []
        for msg in messages:
            copied = dict(msg)
            content = copied.get("content")
            if copied.get("role") == "user" and isinstance(content, list):
                if any(isinstance(block, dict) and block.get("type") == "tool_use" for block in content):
                    copied["role"] = "assistant"
            role_normalized.append(copied)

        normalized = []
        i = 0
        while i < len(role_normalized):
            msg = role_normalized[i]
            tool_use_ids = self._anthropic_tool_use_ids(msg)
            if not tool_use_ids:
                normalized.append(msg)
                i += 1
                continue

            next_msg = role_normalized[i + 1] if i + 1 < len(role_normalized) else None
            result_ids = self._anthropic_tool_result_ids(next_msg) if next_msg else set()
            if tool_use_ids.issubset(result_ids):
                normalized.append(msg)
                normalized.append(next_msg)
                i += 2
                continue

            i += 1
        return normalized

    @staticmethod
    def _anthropic_tool_use_ids(msg: dict | None) -> set[str]:
        if not msg or msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
            return set()
        return {
            block.get("id")
            for block in msg["content"]
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id")
        }

    @staticmethod
    def _anthropic_tool_result_ids(msg: dict | None) -> set[str]:
        if not msg or msg.get("role") != "user" or not isinstance(msg.get("content"), list):
            return set()
        return {
            block.get("tool_use_id")
            for block in msg["content"]
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id")
        }

    def _get_message_count(self) -> int:
        return len(self._openai_messages) if self.use_openai else len(self._anthropic_messages)

    def _auto_save(self) -> None:
        try:
            save_session(self.session_id, {
                "metadata": {
                    "id": self.session_id,
                    "model": self.model,
                    "cwd": str(Path.cwd()),
                    "startTime": self.session_start_time,
                    "messageCount": self._get_message_count(),
                },
                "anthropicMessages": _sanitize_for_utf8(self._anthropic_messages) if not self.use_openai else None,
                "openaiMessages": _sanitize_for_utf8(self._openai_messages) if self.use_openai else None,
                "foldedSessionMemories": _sanitize_for_utf8(self._folded_session_memories),
                #事实失效关系随会话保存：折叠与重启之后，运行时仍然知道哪些旧值已经过期。
                "factState": {
                    "observed": _sanitize_for_utf8(self._observed_facts),
                    "superseded": _sanitize_for_utf8(self._superseded_facts),
                },
            })
        except Exception:
            pass

    #自动压缩
    async def _check_and_compact(self)->None:
        if self.last_input_token_count > self.effective_window * AUTO_COMPACT_THRESHOLD:
            print_info("Context window filling up, compacting conversation...")
            await self._compact_conversation(trigger="auto")

    async def _compact_conversation(self, *, trigger: str = "manual")->bool:
        if self.use_openai:
            compacted = await self._compact_openai(trigger=trigger)
        else:
            compacted = await self._compact_anthropic(trigger=trigger)
        if compacted:
            print_info("Conversation compacted.")
        return compacted

    async def _compact_anthropic(self, *, trigger: str)->bool:
        if len (self._anthropic_messages)<4:
            return False

        # 折叠摘要不得把注入的事实正文带进摘要：事实只有一个来源，旧值不能从摘要回流。
        transcript = build_anthropic_transcript(
            [self._message_without_fact_reminder(m) for m in _sanitize_for_utf8(self._anthropic_messages)]
        )
        if not transcript.strip():
            return False
        memory = await self._generate_folded_session_memory(transcript)
        self._record_folded_session_memory(trigger, memory)
        self._record_fold_event()
        self._anthropic_messages = [{"role": "user", "content": format_folded_memory(memory)}]
        self.last_input_token_count = 0
        self._refresh_runtime_system_prompt()
        return True

    async def _compact_openai(self, *, trigger: str)->bool:
        if len (self._openai_messages)<4:
            return False
        system_msg = self._openai_messages[0]
        # 折叠摘要不得把注入的事实正文带进摘要：事实只有一个来源，旧值不能从摘要回流。
        transcript = build_openai_transcript(
            [self._message_without_fact_reminder(m) for m in _sanitize_for_utf8(self._openai_messages)]
        )
        if not transcript.strip():
            return False
        memory = await self._generate_folded_session_memory(transcript)
        self._record_folded_session_memory(trigger, memory)
        self._record_fold_event()
        self._openai_messages=[
            system_msg,
            {"role": "user", "content": format_folded_memory(memory)},
        ]
        self.last_input_token_count=0
        self._refresh_runtime_system_prompt()
        return True

    async def _generate_folded_session_memory(self, transcript: str) -> dict[str, Any]:
        side_query = self._build_side_query(max_tokens=6000)
        if side_query is None:
            return fallback_folded_memory(transcript)
        try:
            raw = await side_query(FOLD_SESSION_MEMORY_SYSTEM, build_folding_user_prompt(transcript))
            return parse_folded_memory(raw)
        except Exception:
            return fallback_folded_memory(transcript)

    def _record_folded_session_memory(self, trigger: str, memory: dict[str, Any]) -> None:
        record = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "trigger": trigger,
            "session_id": self.session_id,
            **memory,
        }
        self._folded_session_memories.append(record)
        try:
            save_folded_session_memory(self.session_id, _sanitize_for_utf8(record))
        except Exception:
            pass

    #多层级压缩流水线
    def _run_compression_pipeline(self)->None:
        if self.use_openai:
            self._budget_tool_results_openai()
            self._snip_stale_results_openai()
            self._microcompact_openai()
        else:
            self._budget_tool_results_anthropic()
            self._snip_stale_results_anthropic()
            self._microcompact_anthropic()

    #第一层级压缩，预算压缩
    def _budget_tool_results_anthropic(self)->None:
        #计算利用率：utilization = 已用Token / 有效窗口大小。
        utilization = self.last_input_token_count / self.effective_window if self.effective_window else 0
        #如果利用率低于 50%，说明空间还很充裕，直接返回，不做任何处理。
        if utilization < 0.5:
            return
        #动态预算（Budget）：危急状态（>70%）：如果利用率很高，允许单个工具结果保留 15,000 个字符。
        # 警戒状态（50%-70%）：如果利用率中等，只允许保留 30000 个字符。
        budget = 15000 if utilization > 0.7 else 30000

        for msg in self._anthropic_messages:

            #只处理 role 为 "user" 的消息。在工具调用流程中，工具的执行结果通常是以“用户”的身份反馈给模型的。

            if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
                continue
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("content"), str) and len(block["content"]) > budget:
                    #计算保留长度 (keep)：keep = (budget - 80) // 2 这里预留了约 80 个字符的空间给中间的提示语，剩下的长度平分给开头和结尾。
                    keep = (budget - 80) // 2
                    #重组新内容 = 开头部分 + 提示语 + 结尾部分
                    block["content"] = block["content"][:keep] + f"\n\n[... budgeted: {len(block['content']) - keep * 2} chars truncated ...]\n\n" + block["content"][-keep:]

    def _budget_tool_results_openai(self)->None:
        #计算利用率：utilization = 已用Token / 有效窗口大小。
        utilization = self.last_input_token_count / self.effective_window if self.effective_window else 0
        #如果利用率低于 50%，说明空间还很充裕，直接返回，不做任何处理。
        if utilization < 0.5:
            return
        #动态预算（Budget）：危急状态（>70%）：如果利用率很高，允许单个工具结果保留 15,000 个字符。
        # 警戒状态（50%-70%）：如果利用率中等，只允许保留 30000 个字符。
        budget = 15000 if utilization > 0.7 else 30000

        for msg in self._openai_messages:
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str) and len(msg["content"]) > budget:
                keep = (budget - 80) // 2
                msg["content"] = msg["content"][:keep] + f"\n\n[... budgeted: {len(msg['content']) - keep * 2} chars truncated ...]\n\n" + msg["content"][-keep:]


    #第二级策略：修剪过期的工具执行结果
    def _snip_stale_results_anthropic(self) -> None:
        utilization = self.last_input_token_count / self.effective_window if self.effective_window else 0
        if utilization < SNIP_THRESHOLD:
            return
        results = []
        for mindex,  msg in enumerate(self._anthropic_messages):
            if msg.get("role") != "user" or not isinstance(msg.get("content"), list):
                continue

            for bindex, block in enumerate(msg["content"]):
                if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("content"), str) and block["content"] != SNIP_PLACEHOLDER:
                    tool_use_id = block.get("tool_use_id")
                    # 对每个 tool_result，通过 tool_use_id 反查它来自哪个工具
                    tool_info = self._find_tool_use_by_id(tool_use_id)
                    if tool_info and tool_info["name"] in SNIPPABLE_TOOLS:
                        results.append({"mindex": mindex, "bindex": bindex, "name": tool_info["name"], "file_path": tool_info.get("input", {}).get("file_path")})

        if len(results) <= KEEP_RECENT_RESULTS:
            return

        to_snip =  set()
        seen_files: dict[str, list[int]] = {}

        for i, r in enumerate(results):
            if r["name"] == "read_file" and r.get("file_path"):
                seen_files.setdefault(r["file_path"], []).append(i)
        #如果一个文件被读取了多次，只保留最后一次读取的结果，把前面几次读取的内容全部标记为“修剪”（Snip）。
        for indices in seen_files.values():
            if len (indices) >1 :
                for j in indices[:-1]:
                    to_snip.add (j)

        snip_before = len(results) - KEEP_RECENT_RESULTS
        for i in range (snip_before):
            to_snip.add(i)

        for idx in to_snip:
            r = results[idx]
            self._anthropic_messages[r["mindex"]]["content"][r["bindex"]]["content"] = SNIP_PLACEHOLDER

    def _snip_stale_results_openai(self) -> None:
        utilization = self.last_input_token_count / self.effective_window if self.effective_window else 0
        if utilization < SNIP_THRESHOLD:
            return
        tool_msgs = []
        for i, msg in enumerate(self._openai_messages):
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str) and msg["content"] != SNIP_PLACEHOLDER:
                tool_msgs.append(i)
        if len(tool_msgs) <= KEEP_RECENT_RESULTS:
            return
        snip_count = len(tool_msgs) - KEEP_RECENT_RESULTS
        for i in range(snip_count):
            self._openai_messages[tool_msgs[i]]["content"] = SNIP_PLACEHOLDER

    #微压缩

    #基于“时间”的上下文瘦身策略，
    #如果已经很久没说话了，说明之前的工具执行结果你已经看完了，那就把它们清理掉，腾出空间

    def _microcompact_anthropic(self) -> None:
        if not self.last_api_call_time or (time.time() - self.last_api_call_time) < MICROCOMPACT_IDLE_S:
            return

        all_results = []
        for mindex, msg in enumerate(self._anthropic_messages):
            if msg.get("role")!="user" or not isinstance(msg.get("content"), list):
                continue
            for bindex, block in enumerate(msg["content"]):
                if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("content"), str) and block["content"] not in (SNIP_PLACEHOLDER, "[Old result cleared]"):
                    all_results.append((mindex, bindex))

        clear_count = len(all_results) - KEEP_RECENT_RESULTS
        for i in range(max(0, clear_count)):
            mi, bi = all_results[i]
            self._anthropic_messages[mi]["content"][bi]["content"] = "[Old result cleared]"

    def _microcompact_openai(self) -> None:
        if not self.last_api_call_time or (time.time() - self.last_api_call_time) < MICROCOMPACT_IDLE_S:
            return
        tool_msgs = []
        for i, msg in enumerate(self._openai_messages):
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str) and msg["content"] not in (SNIP_PLACEHOLDER, "[Old result cleared]"):
                tool_msgs.append(i)
        clear_count = len(tool_msgs) - KEEP_RECENT_RESULTS
        for i in range(max(0, clear_count)):
            self._openai_messages[tool_msgs[i]]["content"] = "[Old result cleared]"

    def _find_tool_use_by_id(self, tool_use_id: int) -> dict | None:
        for msg in self._anthropic_messages:
            if msg.get("role") != "assistant" or not isinstance(msg.get("content"), list):
                continue

            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") == tool_use_id:
                    return {"name": block["name"], "input": block.get("input", {})}

    #大结果持久化
    #如果工具返回的结果太大（超过 30KB），不要硬塞进上下文里，而是把它存成一个临时文件。
    # 然后在对话里只留一个‘文件路径’和‘内容预览’。如果模型后面还需要看完整内容，它可以再次调用工具去读取这个文件

    #: 超过这个字节数的工具结果不放进上下文，改为落盘 + 占位提示。
    LARGE_RESULT_THRESHOLD = 30 * 1024
    #: 占位提示里带多少字符的预览（真正的原文保存在 ref 指向的产物文件里）。
    LARGE_RESULT_PREVIEW_CHARS = 1200

    def _persist_large_result(self, tool_name: str, result: str) -> str:
        """过长工具结果：完整原文落盘，返回进入上下文的那段文本。"""
        shown, _artifact = self._prepare_tool_result(tool_name, result)
        return shown

    def _persist_and_emit_tool_result(self, tool_name: str, raw: str) -> str:
        """落盘（需要时）并发出 tool_result 事件，返回模型看到的那段文本。

        落盘与发事件必须在同一处完成：事件上的 ref 必须就是这份结果被写入的产物，而不是
        下游从占位文案里正则抠出来的值（文案一变就静默失效）。小结果不带任何结构化字段。
        """
        shown, artifact = self._prepare_tool_result(tool_name, raw)
        event: dict[str, Any] = {
            "type": "tool_result",
            "name": tool_name,
            "result": _safe_utf8_text(shown),
        }
        if artifact:
            event["ref"] = artifact["ref"]
            event["chars"] = artifact["chars"]
            event["preview"] = artifact["preview"]
            #展示文本被截短：完整原文在 ref 指向的产物文件里（不是丢失）。
            event["truncated"] = True
        emit(event)
        return shown

    def _prepare_tool_result(self, tool_name: str, result: str) -> tuple[str, dict[str, Any] | None]:
        """过长工具结果：完整原文落盘，上下文里只留带 ref 的占位提示。

        原文写入 paths.data_dir() 下的工具产物目录（按会话分子目录），文件名带随机后缀，
        因此折叠、自动保存与重启都不会覆盖它。模型要读原文时用运行时的 read_tool_result
        工具按 ref 分页或定位，而不是重新获得任意文件读取能力。

        返回 (进入上下文的文本, 产物描述或 None)。
        """
        #转换成字节
        if (len (result.encode())) <= self.LARGE_RESULT_THRESHOLD:
            return result, None

        lines = result.split("\n")
        size_kb = len(result.encode()) / 1024
        description: dict[str, Any] | None = None
        try:
            artifact = save_tool_artifact(self.session_id, tool_name, result)
            ref = str(artifact.get("ref") or "")
            if ref:
                description = {
                    "ref": ref,
                    "chars": int(artifact.get("chars") or len(result)),
                    "preview": str(artifact.get("preview") or ""),
                }
        except Exception:
            ref = ""
            description = None
        if not ref:
            #落盘失败必须如实说明：不能给出一个「原文已保存」的假提示。
            return (
                f"[Result too large ({size_kb:.1f} KB, {len(lines)} lines) and it could not be "
                f"saved; only the beginning is shown.]\n\n"
                f"Preview (first {self.LARGE_RESULT_PREVIEW_CHARS} chars):\n"
                f"{result[: self.LARGE_RESULT_PREVIEW_CHARS]}"
            ), None
        shown = (
            f'[Result too large: {len(result)} chars / {size_kb:.1f} KB from tool "{tool_name}". '
            f'Complete output saved as ref "{ref}"; the preview below is only the beginning. '
            f'Read the original with the read_tool_result tool: '
            f'read_tool_result(ref="{ref}", offset=0, limit=4000) to page through it, or '
            f'read_tool_result(ref="{ref}", query="...") to jump to a passage.]\n\n'
            f"Preview (first {self.LARGE_RESULT_PREVIEW_CHARS} chars):\n"
            f"{result[: self.LARGE_RESULT_PREVIEW_CHARS]}"
        )
        return shown, description

    #: 返回事实记录的业务工具：它们的返回值同样要进入「旧值是否失效」的跟踪。
    FACT_READING_TOOLS = frozenset(
        {"recall_memories", "remember_fact", "update_memory", "forget_memory"}
    )

    def _note_facts_from_tool_result(self, tool_name: str, result: str) -> None:
        """把工具结果里携带的事实记进观察集合（只取 active）。

        模型可能从 recall_memories 的结果里读到事实值并复述给用户；这些值之后就属于
        「已经提供给模型」的集合，事实被更新或删除时一样要列进失效清单。
        """
        if tool_name not in self.FACT_READING_TOOLS or not isinstance(result, str):
            return
        try:
            payload = json.loads(result)
        except Exception:
            return
        if not isinstance(payload, Mapping):
            return
        records: list[Any] = []
        memories = payload.get("memories")
        if isinstance(memories, list):
            records.extend(memories)
        record = payload.get("record")
        if isinstance(record, Mapping):
            records.append(record)
        if not records:
            return
        for key, snapshot in fact_snapshot(records).items():
            self._observed_facts[key] = dict(snapshot)

    def _read_tool_result(self, inp: Any) -> str:
        """过长结果的受限取回：只能读本会话自己落盘的工具产物。

        没有路径参数，ref 必须是运行时给过的引用，因此它不会成为一个通用的文件读取入口。
        """
        args: Mapping[str, Any] = inp if isinstance(inp, Mapping) else {}
        ref = str(args.get("ref") or "").strip()
        if not ref:
            return json.dumps(
                {"ok": False, "error": "missing_argument", "message": "缺少必填参数：ref"},
                ensure_ascii=False,
            )
        query = args.get("query")
        query_text = str(query) if isinstance(query, str) and query.strip() else None
        outcome = read_tool_artifact(
            self.session_id,
            ref,
            offset=self._int_arg(args.get("offset"), default=0, minimum=0),
            limit=self._int_arg(args.get("limit"), default=4000, minimum=1, maximum=20000),
            query=query_text,
        )
        return json.dumps(outcome, ensure_ascii=False, default=str)

    @staticmethod
    def _int_arg(value: Any, *, default: int, minimum: int, maximum: int | None = None) -> int:
        """工具参数里的整数：模型常把数字写成字符串，这里一并接受。"""
        if isinstance(value, bool) or value is None:
            number = default
        elif isinstance(value, int):
            number = value
        elif isinstance(value, str) and value.strip().lstrip("-").isdigit():
            number = int(value.strip())
        else:
            number = default
        number = max(minimum, number)
        if maximum is not None:
            number = min(maximum, number)
        return number

    #执行工具入口

    async def _execute_tool_call(self, name: str, inp: dict) -> str:
        if self.product_mode and name not in self._custom_tool_names | {"read_tool_result", "compact_context"}:
            return json.dumps({"ok": False, "error": "tool_not_available",
                               "message": "该能力不属于个人助手的可用工具。"}, ensure_ascii=False)
        if name == "compact_context":
            return await self._execute_compact_context_tool(inp)
        if name == "read_tool_result":
            #运行时的受限取回工具：在业务工具路由之前处理，ref 由本会话产出并校验。
            return self._read_tool_result(inp)
        if name in ("enter_plan_mode", "exit_plan_mode"):
            return await self._execute_plan_mode_tool(name)
        if name == "agent":
            return await self._execute_agent_tool(inp)
        if name == "skill":
            return await self._execute_skill_tool(inp)
            # Route MCP tool calls to the MCP manager
        if self._mcp_manager.is_mcp_tool(name):
            return await self._mcp_manager.call_tool(name, inp)
        #业务工具路由：名字在 custom_tools 中且注入了执行器时，交给调用方执行。
        if self.tool_executor is not None and name in self._custom_tool_names:
            result = await self.tool_executor(name, inp)
            #工具结果里读到的事实同样是「提供给模型的值」，必须一起进入失效跟踪，
            #否则模型从 recall_memories 拿到的旧值不会被标注为已失效。
            self._note_facts_from_tool_result(name, result)
            return result
        result = await execute_tool(name, inp)
        if name in {"skill_create", "skill_evolve"}:
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and parsed.get("ok"):
                    self._refresh_runtime_system_prompt()
            except Exception:
                pass
        return result

    async def _execute_compact_context_tool(self, inp: dict) -> str:
        reason = str(inp.get("reason") or "").strip()
        compacted = await self._compact_conversation(trigger="tool")
        if not compacted:
            self._record_tool_outcome("compact_context", False)
            return "No context compaction was performed because there is not enough conversation history yet."
        self._record_tool_outcome("compact_context", True)
        self._context_cleared = True
        suffix = f"\nReason: {reason}" if reason else ""
        return (
            "Context compacted into structured session memory. "
            "Continue from the folded memory now present in the conversation context."
            f"{suffix}"
        )


    @staticmethod
    def _skill_name_from_arguments(inp: dict) -> str:
        """Resolve the skill name from the tool arguments.

        The schema names the field skill_name, but models routinely send "name"
        or "skill" instead. Accepting the aliases costs nothing, whereas
        ignoring them loses the invocation entirely - and the failure looks
        like a missing skill rather than a wrong argument key.
        """
        for key in ("skill_name", "name", "skill"):
            value = inp.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    async def _execute_skill_tool(self, inp: dict) -> str:
        try:
            from mellowday.runtime.skills import execute_skill
        except Exception:
            return "Skills are unavailable in this runtime."
        skill_name = self._skill_name_from_arguments(inp)
        result = execute_skill(skill_name, inp.get("args", ""))

        if not result:
            received = ", ".join(sorted(str(key) for key in inp)) or "none"
            return (
                f"Unknown skill: {skill_name or '(no name supplied)'}. "
                f"Call this tool with the registered skill name in skill_name. "
                f"Arguments received: {received}."
            )

        #fork 表示这个 skill 不直接把 prompt 塞回当前对话，而是要启动一个子 Agent 单独完成任务。
        if result["context"] == "fork":
            # result["allowed_tools"] - 直接访问
            tools = (
                [t for t in self.tools if t["name"] in  result["allowed_tools"] ]
                #result.get("allowed_tools") - 安全访问
                # 存在key：返回对应的值（可能是 None、[]、["tool1"] 等）
                # 不存在key：返回 None（不会抛异常）
                if result.get("allowed_tools")
                else  [t for t in self.tools if t["name"] != "agent"]
            )

            print_sub_agent_start("skill-fork", inp.get("skill_name", ""))
            sub_agent = Agent(
                model=self.model,
                api_base=str(self._openai_client.base_url) if self.use_openai and self._openai_client else None,
                custom_system_prompt=result["prompt"],
                custom_tools=tools,
                is_sub_agent=True,
                permission_mode="plan" if self.permission_mode == "plan" else "bypassPermissions",
            )
            try:
                sub_result = await sub_agent.run_once(inp.get("args") or "Execute this skill task.")
                self.total_input_tokens += sub_result["tokens"]["input"]
                self.total_output_tokens += sub_result["tokens"]["output"]
                print_sub_agent_end("skill-fork", inp.get("skill_name", ""))
                return sub_result["text"] or "(Skill produced no output)"
            except Exception as e:
                print_sub_agent_end("skill-fork", inp.get("skill_name", ""))
                return f"Skill fork error: {e}"

        return f'[Skill "{inp.get("skill_name", "")}" activated]\n\n{result["prompt"]}'

    async def _execute_plan_mode_tool(self, name):
        if name == "enter_plan_mode":
            if self.permission_mode == "plan":
                return "Already in plan mode."
            self._pre_plan_mode = self.permission_mode
            self.permission_mode = "plan"
            self._plan_file_path =  self._generate_plan_file_path()
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
            if self.use_openai and self._openai_messages:
                self._openai_messages[0]["content"] = self._system_prompt
            print_info("Entered plan mode (read-only). Plan file: " + self._plan_file_path)
            return f"Entered plan mode. You are now in read-only mode.\n\nYour plan file: {self._plan_file_path}\nWrite your plan to this file. This is the only file you can edit.\n\nWhen your plan is complete, call exit_plan_mode."
        if name == "exit_plan_mode":
            if self.permission_mode != "plan":
                return "Not in plan mode."
            plan_content = "(No plan file found)"
            if self._plan_file_path and Path(self._plan_file_path).exists():
                plan_content = self._plan_file_path
            # 交互式审批流程（如果有审批函数）
            if self._plan_approval_fn:
                result = self._plan_approval_fn(plan_content)
                choice = result.get("choice", "manual-execute")

                if choice =="keep-planning":
                    feedback = result.get("feedback") or "Please revise the plan."
                    return (
                        f"User rejected the plan and wants to keep planning.\n\n"
                        f"User feedback: {feedback}\n\n"
                        f"Please revise your plan based on this feedback. When done, call exit_plan_mode again."
                    )

                if choice == "clear-and-execute":
                    target_mode = "acceptEdits"
                elif choice == "execute":
                    target_mode = "acceptEdits"
                else:  # manual-execute
                    target_mode = self._pre_plan_mode or "default"

                #离开计划模式
                self._pre_plan_mode = target_mode
                self._pre_plan_mode = None
                saved_plan_path = self._plan_file_path
                self._plan_file_path = None
                self._system_prompt = self._base_system_prompt
                if self.use_openai and self._openai_messages:
                    self._openai_messages[0]["content"] = self._system_prompt

                if choice == "clear-and-execute":
                    self._clear_history_keep_system()
                    self._context_cleared = True
                    print_info(f"Plan approved. Context cleared, executing in {target_mode} mode.")
                    return (
                        f"User approved the plan. Context was cleared. Permission mode: {target_mode}\n\n"
                        f"Plan file: {saved_plan_path}\n\n"
                        f"## Approved Plan:\n{plan_content}\n\n"
                        f"Proceed with implementation."
                    )
                print_info(f"Plan approved. Executing in {target_mode} mode.")
                return (
                    f"User approved the plan. Permission mode: {target_mode}\n\n"
                    f"## Approved Plan:\n{plan_content}\n\n"
                    f"Proceed with implementation."
                )
            # 没有审批函数时的回退（例如子代理）
            self.permission_mode = self._pre_plan_mode or "default"
            self._pre_plan_mode = None
            self._plan_file_path = None
            self._system_prompt = self._base_system_prompt
            if self.use_openai and self._openai_messages:
                self._openai_messages[0]["content"] = self._system_prompt

            print_info("Exited plan mode. Restored to " + self.permission_mode + " mode.")
            return f"Exited plan mode. Permission mode restored to: {self.permission_mode}\n\n## Your Plan:\n{plan_content}"

        return f"Unknown plan mode tool: {name}"

    def _clear_history_keep_system(self) -> None:
        """清空历史信息，但是保留系统prompt."""
        self._anthropic_messages = []
        self._openai_messages = []
        if self.use_openai:
            self._openai_messages.append({"role": "system", "content": self._system_prompt})
        self.last_input_token_count = 0
        self._fold_last_time = 0.0
        self._fold_count = 0
        self._tool_error_streak = 0
        self._same_tool_repeat_count = 0
        self._last_tool_name = ""

    async def _execute_agent_tool(self, inp:dict) -> str:
        agent_type = inp.get("type", "general")
        description = inp.get("description", "sub-agent task")
        prompt = inp.get("prompt", "")
        print_sub_agent_start(agent_type, description)

        config = get_sub_agent_config(agent_type)

        sub_agent = Agent(
            model=self.model,
            api_base=str(self._openai_client.base_url) if self.use_openai and self._openai_client else None,
            custom_system_prompt=config["system_prompt"],
            custom_tools=config["tools"],
            is_sub_agent=True,
            permission_mode="plan" if self.permission_mode == "plan" else "bypassPermissions",
        )
        try:
            result = await sub_agent.run_once(prompt)
            self.total_input_tokens += result["tokens"]["input"]
            self.total_output_tokens += result["tokens"]["output"]
            print_sub_agent_end(agent_type, description)
            return result["text"] or "(Sub-agent produced no output)"
        except Exception as e:
            print_sub_agent_end(agent_type, description)
            return f"Sub-agent error: {e}"

#--------------Anthropic 后端---------------
    async def  _chat_anthropic(self, user_message: str, recall_query: str | None = None) -> None:
        self._anthropic_messages = self._normalize_anthropic_messages(_sanitize_for_utf8(self._anthropic_messages))
        user_message = _safe_utf8_text(user_message)
        # 先把本轮用户输入放入 Anthropic 消息历史，后续每轮模型调用都会带上这段上下文。
        self._anthropic_messages.append({"role": "user", "content": user_message})

        # 本轮事实召回用用户原话（不含技能上下文拼接）；中文原句直接参与词项匹配。
        recall_text = _safe_utf8_text(recall_query) if recall_query is not None else user_message

        # 每轮对话只做一次自动事实召回（I22），结果注入本轮上下文，不依赖模型调用工具。
        facts_injected = False
        while True:
            # 外部请求中止时，结束整个 agent loop。
            if self._aborted:
                break

            # 每轮调用模型前尝试压缩上下文，避免消息历史过长。
            self._run_compression_pipeline()

            # 注入位置：本轮第一次模型调用之前，最后一条 user 消息的尾部（<system-reminder>）。
            if not facts_injected:
                facts_injected = True
                await self._inject_recalled_facts(self._anthropic_messages, recall_text)

            if not self.is_sub_agent:
                start_spinner()


            # 保存“提前执行”的工具任务。key 是 Anthropic 返回的 tool_use block id。
            early_executions: dict[str, asyncio.Task] = {}


            def _on_tool_block(block:dict):
                # 流式响应中一旦完整收到 tool_use block，如果工具是并发安全且权限允许，
                # 就可以提前开始执行，减少等待完整模型响应后的空档时间。
                if block["name"] in CONCURRENCY_SAFE_TOOLS:
                    perm = check_permission(block["name"], block["input"], self.permission_mode, self._plan_file_path)
                    if perm["action"]=="allow":
                        task =asyncio.create_task(self._execute_tool_call(block["name"], block["input"]))
                        early_executions[block["id"]] = task


            # 调用 Anthropic 流式接口；流式过程中完成 tool block 时会触发 _on_tool_block。
            response = await self._call_anthropic_stream(on_tool_block_complete=_on_tool_block)
            if not self.is_sub_agent:
                stop_spinner()

            # 记录本次模型调用的耗时点和 token 消耗，用于成本展示与预算控制。
            self.last_api_call_time = time.time()
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self.last_input_token_count = response.usage.input_tokens

            # Anthropic 的响应内容里可能混有 text block 和 tool_use block，这里只挑出工具调用。
            tool_uses = [b for b in response.content if b.type == "tool_use"]

            # 把模型返回的所有 content block 写入消息历史，后续 tool_result 要与这些 tool_use 对应。
            self._anthropic_messages.append({
                "role": "assistant",
                "content": [self._block_to_dict(b) for b in response.content],
            })

            # 没有工具调用，说明模型已经给出最终回复，本轮对话结束。
            if not tool_uses:
                if not self.is_sub_agent:
                    print_cost(self.total_input_tokens, self.total_output_tokens)
                break

            # 有工具调用时，进入下一轮工具执行。这里同时检查 turn/budget 限制。
            self.current_turns += 1
            budget = self._check_budget()
            if budget["exceeded"]:
                print_info(f"Budget exceeded: {budget['reason']}")
                self._anthropic_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tu.id,
                            "content": f"Tool execution skipped: {budget['reason']}",
                        }
                        for tu in tool_uses
                    ],
                })
                break


            # 收集本轮所有工具结果，之后作为 tool_result 消息回传给模型。
            tool_results: list[dict] = []
            context_break = False

            for tu in tool_uses:
                # context_break 表示某个工具执行期间清理了上下文，需要停止继续处理本轮剩余工具。
                if context_break or self._aborted:
                    break

                # 将工具入参转为普通 dict，便于权限检查、打印和实际执行。
                inp = dict(tu.input) if hasattr(tu, "items") else tu.input
                print_tool_call(tu.name, inp)

                # 如果这个工具已经在流式阶段提前开始执行，这里只需要等待它完成并收集结果。
                early_task = early_executions.get(tu.id)
                if early_task:
                    try:
                        raw = await early_task
                    except Exception as e:
                        raw = f"Error executing tool: {e}"
                    raw = _safe_utf8_text(raw)
                    res = self._persist_and_emit_tool_result(tu.name, raw)
                    self._record_tool_outcome(tu.name, not self._looks_like_tool_failure(tu.name, raw, res))
                    tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": res})
                    continue

                # 如果不是提前执行的工具，就在真正执行前做权限检查。

                perm = check_permission(tu.name, inp, self.permission_mode, self._plan_file_path)
                if perm["action"] == "deny":
                    # 权限拒绝时，也要返回一个 tool_result，让模型知道该工具调用失败的原因。
                    print_info(f"Denied: {perm.get('message', '')}")
                    self._record_tool_outcome(tu.name, False)
                    tool_results.append({"type": "tool_result", "tool_use_id": tu.id,
                                         "content": f"Action denied: {perm.get('message', '')}"})
                    continue

                if perm["action"] == "confirm" and perm.get("message") and perm["message"] not in self._confirmed_paths:
                    # 高风险操作需要用户确认；同一个 message 确认过后会缓存，避免重复询问。
                    confirmed = await self._confirm_dangerous(perm["message"])
                    if not confirmed:
                        self._record_tool_outcome(tu.name, False)
                        tool_results.append(
                            {"type": "tool_result", "tool_use_id": tu.id, "content": "User denied this action."})
                        continue
                    self._confirmed_paths.add(perm["message"])

                # 权限通过后执行工具，并把大输出持久化为可回传的摘要或引用。
                try:
                    raw = await self._execute_tool_call(tu.name, inp)
                except Exception as e:
                    raw = f"Error executing tool: {e}"
                raw = _safe_utf8_text(raw)
                res = self._persist_and_emit_tool_result(tu.name, raw)
                self._record_tool_outcome(tu.name, not self._looks_like_tool_failure(tu.name, raw, res))

                if self._context_cleared:
                    # 工具执行过程中如果清理了上下文，就把结果作为新的用户消息写入，
                    # 并停止继续处理本轮剩余工具，避免旧上下文和新上下文混在一起。
                    self._context_cleared = False
                    self._anthropic_messages.append({"role": "user", "content": res})
                    context_break = True
                    break

                # Anthropic 要求 tool_result 使用 tool_use_id 对应到前面的 tool_use block。
                tool_results.append({"type": "tool_result", "tool_use_id": tu.id, "content": res})

            if not context_break and tool_results:
                # Anthropic 要求 assistant/tool_use 后面紧跟一条 user/tool_result 消息，
                # 且这条消息必须包含本轮所有 tool_use 的对应结果。
                self._anthropic_messages.append({"role": "user", "content": tool_results})

            self._context_cleared = False

            # 工具结果可能很长，每轮工具执行后检查是否需要压缩上下文。
            self._refresh_runtime_system_prompt()
            await self._check_and_compact()

    @staticmethod
    def _block_to_dict(block) -> dict:
        if block.type == "text":
            return {"type": "text", "text": _safe_utf8_text(block.text)}
        if block.type == "tool_use":
            raw_input = dict(block.input) if hasattr(block.input, 'items') else block.input
            return {"type": "tool_use", "id": _safe_utf8_text(block.id), "name": _safe_utf8_text(block.name), "input": _sanitize_for_utf8(raw_input)}
        # Fallback
        return {"type": _safe_utf8_text(block.type)}

    async def _call_anthropic_stream(self, on_tool_block_complete=None):

        async def _do():
            max_output =  _get_max_output_tokens(self.model)

            create_params: dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_output if self._thinking_mode != "disabled" else 16384,
                "system": _safe_utf8_text(self._system_prompt),
                "tools": _sanitize_for_utf8(get_active_tool_definitions(self.tools)),
                "messages": _sanitize_for_utf8(self._anthropic_messages),
            }
            #如果开启了思考模式，就给 Anthropic 请求加上 thinking 参数。
            if self._thinking_mode  in ("adaptive", "enabled"):
                create_params["thinking"]={"type": "enabled", "budget_tokens": max_output - 1}

            first_text = True

            tool_blocks_by_index: dict[int, dict] = {}

            async with self._anthropic_client.messages.stream(**create_params)as stream:
                async for event in stream:
                    if not hasattr(event, 'type'):
                        continue
                    # 当事件是工具调用开始：
                    if event.type == "content_block_start":
                        cb = getattr(event, 'content_block', None)
                        #如果 block 类型是 tool_use，就记录这个工具调用：
                        if cb and getattr(cb, 'type', None) == "tool_use":
                            #因为工具参数 JSON 是流式分片返回的，所以先准备一个空字符串 input_json。
                            tool_blocks_by_index[event.index]= {
                                "id": cb.id, "name": cb.name, "input_json": "",
                            }
                    #当事件是内容增量，分三种情况。
                    elif event.type == "content_block_delta":
                        delta = event.delta
                        # 第一种，普通文本：模型输出正文时，
                        # 调用 _emit_text()。如果是普通交互，就打印；
                        # 如果是 run_once()，就写入 _output_buffer。
                        if hasattr(delta, "text"):
                            if first_text:
                                stop_spinner()
                                self._emit_text("\n")
                                first_text = False
                            self._emit_text(delta.text)
                        #第二种，thinking 内容：
                        #如果模型返回思考内容，也输出出来，并在开头加：[thinking]
                        elif hasattr(delta, 'thinking'):
                            if first_text:
                                stop_spinner()
                                self._emit_text("\n  [thinking] ")
                                first_text = False
                            self._emit_text(delta.thinking)
                        #第三种，工具参数 JSON 片段：工具调用的参数不是一次性返回，
                        # 而是一段一段返回，所以这里不断拼接到 input_json。
                        elif hasattr(delta, 'partial_json'):
                            tb = tool_blocks_by_index.get(event.index)
                            if tb:
                                tb["input_json"] += _safe_utf8_text(delta.partial_json)
                    #当一个 content block 结束：
                    #如果结束的是之前记录的工具调用，就把拼好的 JSON 解析出来：
                    elif event.type == "content_block_stop":
                        tb = tool_blocks_by_index.pop(event.index, None)
                        if tb and on_tool_block_complete:
                            import json as _json
                            try:
                                parsed = _json.loads(tb["input_json"] or "{}")
                            except Exception:
                                parsed = {}
                            #然后调用回调：
                            #这个回调的作用通常是：工具调用一完整，
                            # 就可以提前开始执行工具，不必等整条 assistant 消息全部结束。
                            on_tool_block_complete({
                                "type": "tool_use", "id": _safe_utf8_text(tb["id"]),
                                "name": _safe_utf8_text(tb["name"]), "input": _sanitize_for_utf8(parsed),
                            })
                final_message = await stream.get_final_message()

            #过滤思考的message（因为 thinking 内容一般不应该进入历史消息，否则后续上下文会变大，也可能不符合 API 消息格式要求。）
            final_message.content = [b for b in final_message.content if b.type != "thinking"]
            return final_message
#调用 _do()，如果遇到可重试错误，就由 _with_retry() 负责重试。
        return await _with_retry(_do)

    #openAI后端

    async def _chat_openai(self, user_message:str, recall_query: str | None = None) -> None:
        user_message = _safe_utf8_text(user_message)
        self._openai_messages.append({"role": "user", "content": user_message})

        # 本轮事实召回用用户原话（不含技能上下文拼接）；中文原句直接参与词项匹配。
        recall_text = _safe_utf8_text(recall_query) if recall_query is not None else user_message

        # 每轮对话只做一次自动事实召回（I22），结果注入本轮上下文，不依赖模型调用工具。
        facts_injected = False
        while True:
            if self._aborted:
                break

            self._run_compression_pipeline()

            # 注入位置：本轮第一次模型调用之前，最后一条 user 消息的尾部（<system-reminder>）。
            if not facts_injected:
                facts_injected = True
                await self._inject_recalled_facts(self._openai_messages, recall_text)

            if not self.is_sub_agent:
                start_spinner()

            response = await self._call_openai_stream()

            if not self.is_sub_agent:
                stop_spinner()

            self.last_api_call_time = time.time()

            if response.get("usage"):
                self.total_input_tokens += response["usage"]["prompt_tokens"]
                self.total_output_tokens += response["usage"]["completion_tokens"]
                self.last_input_token_count = response["usage"]["prompt_tokens"]

            choice = response.get("choices", [{}])[0] if response.get("choices") else {}
            message = choice.get("message", {})

            self._openai_messages.append(message)

            tool_calls = message.get("tool_calls")

            if not tool_calls:
                if not self.is_sub_agent:
                    print_cost(self.total_input_tokens, self.total_output_tokens)
                break

            self.current_turns += 1
            budget = self._check_budget()
            if budget["exceeded"]:
                print_info(f"Budget exceeded: {budget['reason']}")
                break

            oai_checked: list[dict] = []
            for tc in tool_calls:
                if self._aborted:
                    break

                if tc.get("type") != "function":
                    continue

                fn_name = tc["function"]["name"]
                try:
                    inp = json.loads(tc["function"]["arguments"])
                except Exception:
                    inp = {}

                print_tool_call(fn_name, inp)

                perm = check_permission(fn_name, inp, self.permission_mode, self._plan_file_path)

                if perm["action"] == "deny":
                    print_info(f"Denied: {perm.get('message', '')}")
                    self._record_tool_outcome(fn_name, False)
                    oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": False,
                                        "result": f"Action denied: {perm.get('message', '')}"})
                    continue
                if perm["action"] == "confirm" and perm.get("message") and perm["message"] not in self._confirmed_paths:
                    confirmed = await self._confirm_dangerous(perm["message"])
                    if not confirmed:
                        self._record_tool_outcome(fn_name, False)
                        oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": False,
                                            "result": "User denied this action."})
                        continue
                    self._confirmed_paths.add(perm["message"])
                oai_checked.append({"tc": tc, "fn": fn_name, "inp": inp, "allowed": True})

            oai_batches: list[dict] = []
            for ct in oai_checked:
                safe = ct["allowed"] and ct["fn"] in CONCURRENCY_SAFE_TOOLS
                if safe and oai_batches and oai_batches[-1]["concurrent"]:
                    oai_batches[-1]["items"].append(ct)
                else:
                    oai_batches.append({"concurrent": safe, "items": [ct]})

            oai_context_break = False
            for batch in oai_batches:
                if oai_context_break or self._aborted:
                    break

                if batch["concurrent"]:
                    async def _run_oai_safe(ct_item: dict) -> tuple[dict, str]:
                        raw = await self._execute_tool_call(ct_item["fn"], ct_item["inp"])
                        raw = _safe_utf8_text(raw)
                        res = self._persist_and_emit_tool_result(ct_item["fn"], raw)
                        return ct_item, res

                    results = await asyncio.gather(*[_run_oai_safe(ct) for ct in batch["items"]])
                    for ct_item, res in results:
                        self._record_tool_outcome(
                            ct_item["fn"],
                            not self._looks_like_tool_failure(ct_item["fn"], "", res),
                        )
                        self._openai_messages.append(
                            {"role": "tool", "tool_call_id": ct_item["tc"]["id"], "content": res})
                else:
                    for ct in batch["items"]:
                        if not ct["allowed"]:
                            self._openai_messages.append(
                                {"role": "tool", "tool_call_id": ct["tc"]["id"], "content": ct["result"]})
                            continue

                        raw = await self._execute_tool_call(ct["fn"], ct["inp"])
                        raw = _safe_utf8_text(raw)
                        res = self._persist_and_emit_tool_result(ct["fn"], raw)
                        self._record_tool_outcome(
                            ct["fn"],
                            not self._looks_like_tool_failure(ct["fn"], raw, res),
                        )

                        if self._context_cleared:
                            self._context_cleared = False
                            self._openai_messages.append({"role": "user", "content": res})
                            oai_context_break = True
                            break

                        self._openai_messages.append(
                            {"role": "tool", "tool_call_id": ct["tc"]["id"], "content": res})

            self._context_cleared = False
            self._refresh_runtime_system_prompt()
            await self._check_and_compact()

    async def _call_openai_stream(self) -> dict:
        async def _do():
            stream = await self._openai_client.chat.completions.create(
                model=self.model,
                tools=_sanitize_for_utf8(_to_openai_tools(get_active_tool_definitions(self.tools))),
                messages=_sanitize_for_utf8(self._openai_messages),
                stream=True,
                stream_options={"include_usage": True},
            )

            content = ""
            first_text = True
            tool_calls: dict[int, dict] = {}
            finish_reason = ""
            usage = None

            async for chunk in stream:
                if chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                    }

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                if delta and delta.content:
                    if first_text:
                        stop_spinner()
                        self._emit_text("\n")
                        first_text = False
                    self._emit_text(delta.content)
                    content += _safe_utf8_text(delta.content)

                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        existing = tool_calls.get(tc.index)
                        if existing:
                            if tc.function and tc.function.arguments:
                                existing["arguments"] += _safe_utf8_text(tc.function.arguments)
                        else:
                            tool_calls[tc.index] = {
                                "id": _safe_utf8_text(tc.id or ""),
                                "name": _safe_utf8_text((tc.function.name if tc.function else "") or ""),
                                "arguments": _safe_utf8_text((tc.function.arguments if tc.function else "") or ""),
                            }

                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

            assembled = None
            if tool_calls:
                assembled = [
                    {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                    for _, tc in sorted(tool_calls.items())
                ]

            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": assembled,
                    },
                    "finish_reason": finish_reason or "stop",
                }],
                "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
            }

        return await _with_retry(_do)

    async def _confirm_dangerous(self, command: str) -> bool:
        """Ask the caller to confirm a risky action.

        Without a confirm_fn there is nobody to ask, so the action is refused
        and the refusal is still made visible with a confirmation event; the
        runtime never reads from a terminal.

        With a confirm_fn, that function owns the user-visible prompt: the web
        layer answers by emitting the `confirmation` event carrying its
        one-shot token. Emitting another, token-less confirmation here would
        render a second prompt the web client cannot answer.
        """
        if self.confirm_fn is None:
            print_confirmation(command)
            return False
        try:
            return bool(await self.confirm_fn(command))
        except Exception:
            return False
