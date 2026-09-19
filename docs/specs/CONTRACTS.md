# 接口契约（并行实施基准）

本文件是多个实施单元之间唯一权威的接口约定。任何单元需要改动这里的签名，必须先通知主 agent；主 agent 更新本文件后其他单元才跟进。所有路径均为仓库根相对路径。

## 1. 包与入口

- Python 包：`src/mellowday`，通过 `pyproject.toml`（setuptools，`where=["src"]`）以可编辑方式安装。
- 应用入口：`mellowday.web_app.app:create_app()` 返回 FastAPI 实例；开发启动 `python -m mellowday.web_app`。
- 运行环境：Python 3.11+。已确认本机 Python 3.12 具备 fastapi、uvicorn、openai、anthropic、pytest、httpx。
- 运行数据根：`MELLOWDAY_DATA_DIR`，默认 `<cwd>/data`。**不读取原 ChatBot 工作区的任何配置、数据库或会话。**

## 2. 配置（`mellowday/config.py`，已完成）

- `ModelConfig(api_key, api_base, model, thinking, max_turns)`；环境变量 `MELLOWDAY_API_KEY`、`MELLOWDAY_API_BASE`、`MELLOWDAY_MODEL` 覆盖文件配置。
- `load_model_config()`、`save_model_config(cfg)`、`update_model_config(**changes)`；`ModelConfig.public()` 不含明文密钥。
- 无凭据时管理页仍可用，聊天必须返回明确的配置错误事件而不是静默失败。

## 3. 事件桥（`mellowday/runtime/events.py`，已完成）

- 事件 `dict` 必含 `type`；不得携带密钥。
- 事件类型：`text_delta(text)`、`tool_start(name, arguments)`、`tool_result(name, result)`、`confirmation(summary)`、`notice(message)`、`warning(message)`、`error(message)`、`retry(...)`、`token_usage(input, output)`、`turn_end`、`subagent_start`、`subagent_end`、`busy_start`、`busy_end`、`skill_list`、`memory_list`、`plan`。
- **学习回路事件（I24b 新增，2026-09-19）**：
  - `skill_candidate_proposed {skill, action, summary}` —— 候选进入写入步骤。
  - `skill_candidate_applied {skill, action}` —— `action=add` 新建 / `merge` 演化（即「合并而非追加」）。
  - `skill_write_denied {skill, action, reason, summary}` —— `reason` ∈ `user_denied | no_confirmer | confirm_error:<ExcType> | permission_mode:<mode>`。
  - `skill_candidate_failed {skill, action, reason}` —— 提取或写入抛错，或技能包返回失败。
  - `skill_candidate_skipped {skill, stage, reason}` —— `reason` ∈ `disabled | plan_mode | no_window | no_model_client | skills_unavailable | <维护者 discard 理由>`。
- **确认事件的所有权（强制）**：`confirm_fn` 存在时，**运行时不自己发 `confirmation` 事件**——只有网页层 `confirm_fn` 发出的那条才带一次性 token。运行时的 `_confirm_dangerous` 仅在没有 `confirm_fn`（无人可问）时才发无 token 的 `confirmation`，目的是让拒绝仍然可见。违反此规则会导致前端出现两个确认框、其中一个点击无响应。
- 这五类学习事件必须被前端渲染；运行时侧的每个提前 `return` 都必须发出对应事件，不得静默丢弃。
- 调用方用 `set_sink(fn)`/`reset_sink(token)` 或上下文管理器 `with use_sink(fn):` 安装接收器；sink 存于 `ContextVar`，因此 `Agent.chat` 内部创建的 asyncio task 自动继承，两个并发会话互不串流。
- `emit()` 永不向运行时抛异常。

## 4. 运行时（`mellowday/runtime/`）

### 4.1 agent.py

```python
class Agent:
    def __init__(self, *, model: str, api_base: str | None = None, api_key: str | None = None,
                 thinking: bool = False, max_turns: int | None = None,
                 permission_mode: str = "default",
                 custom_system_prompt: str | None = None,
                 custom_tools: list[ToolDef] | None = None,
                 tool_executor: Callable[[str, dict], Awaitable[str]] | None = None,
                 fact_provider: Callable[[str], Awaitable[list[dict]]] | None = None,
                 confirm_fn: Callable[[str], Awaitable[bool]] | None = None) -> None: ...
    async def chat(self, user_message: str) -> None: ...
    def abort(self) -> None: ...
    def restore_session(self, data: dict) -> None: ...
    def set_confirm_fn(self, fn) -> None: ...
    def get_token_usage(self) -> dict: ...
    def clear_history(self) -> None: ...
```

- 保留源码的主循环机制：回合上限、重试退避、工具调用并行批次（`CONCURRENCY_SAFE_TOOLS`）、上下文压缩管线、Skills 检索注入、会话自动保存。
- **移除终端依赖**：所有输出经 `mellowday.runtime.events`；不得出现 `print(`、`input(`、`sys.stdout`、`rich`。
- **新增业务工具路由**：`_execute_tool_call` 在回退到内置工具前，若 `name` 在 `custom_tools` 名字集合中且 `tool_executor` 非空，则 `return await self.tool_executor(name, inp)`。
- 模型协议：OpenAI 兼容（`api_base` 非空）与 Anthropic 双路径均保留；默认走 OpenAI 兼容。
- 工具结果预算、超长结果落盘（`_persist_large_result`）保留，但落盘目录必须是 `paths.data_dir()` 下，不得写入源码树。

### 4.2 tools.py（内置工具集裁剪）

必须导出：`ToolDef`、`tool_definitions`、`execute_tool(name, inp, state=None)`、`CONCURRENCY_SAFE_TOOLS`、`check_permission(tool_name, inp, mode, plan_file=None)`、`get_active_tool_definitions()`、`get_deferred_tool_names()`、`reset_activated_tools()`、`reset_permission_cache()`。

- **删除**：`read_file`、`write_file`、`edit_file`、`list_files`、`grep_search`、`run_shell` 及 `tool_search`、shell 危险命令判定、路径解析、diff 生成。
- **保留**：Skills 相关工具（`skill`、`skill_create`、`skill_evolve`）与 `compact_context`（后者由 agent.py 执行）。
- `check_permission` 对 `skill_create`/`skill_evolve` 返回 `confirm`（需网页确认），其余返回 `allow`。业务工具的确认由业务层与网页层负责。
- 不得残留 `subprocess`、`os.system`。

### 4.3 prompt.py

`build_system_prompt() -> str` 组装 MellowDay 个人助理提示词，包含：角色与行为准则、当前日期、可用能力概述、Skills 描述、记忆段落。**不得**包含 git 上下文、CLAUDE.md 规则、代码仓库说明、plan mode 编码提示。Skills / 记忆段落的构建必须容错（导入失败或目录为空时跳过），保证单独导入本模块不报错。

### 4.4 sessions.py、session_memory.py、memory.py、subagent.py、mcp_client.py

- `sessions.py`：`save_session(session_id, data)`、`load_session(session_id)`、`list_sessions()`、`get_latest_session_id()`、`save_folded_session_memory(session_id, record)`；目录为 `paths.sessions_dir()`。
- `session_memory.py`：原函数签名不变（`build_openai_transcript`、`build_anthropic_transcript`、`build_folding_user_prompt`、`parse_folded_memory`、`fallback_folded_memory`、`format_folded_memory`、`FOLD_SESSION_MEMORY_SYSTEM`）。
- `memory.py`：记忆索引与召回；目录为 `paths.memory_dir()`。
- `subagent.py`、`mcp_client.py`：保留机制，默认不启用；`McpManager` 不得在无配置时阻塞启动。

### 4.5 skills 包（`mellowday/runtime/skills/`）

```python
# 必须从 mellowday.runtime.skills 可导入
SkillDefinition, discover_skills, get_skill_by_name, execute_skill, resolve_skill_prompt,
build_skill_descriptions, retrieve_relevant_skills, format_retrieved_skill_context,
reset_skill_cache, create_skill, evolve_skill, record_feedback, skill_stats,
record_usage_judgments
# 演化与评测
create_skill_file, evolve_skill_file, resolve_skill_file, load_skill_stats, format_skill_stats,
record_skill_invocation, record_skill_feedback, record_online_provenance,
extract_online_skill_candidate, maintain_online_skill_candidate, online_ingest,
judge_retrieved_skill_usage
```

- Skills 根目录 = `paths.skills_dir()`；演化目录 = `paths.evolution_dir()`。
- 检索保持源码的词项（token）路线，不引入向量库。
- 不导入源码仓库中的示例 Skills（尤其中文网文类）。
- 演化与评测的**函数签名保持不变**，网页层只做适配调用。

#### 技能管理（I24a 新增，2026-09-19）

```python
list_skills() -> list[dict]        # name/description/version/enabled/source/path；含已停用项，不抛异常
disable_skill(name) -> dict        # {ok, name, archived_to, path, changed}
enable_skill(name) -> dict         # {ok, name, path, changed}
list_skill_versions(name) -> list[dict]   # {version, updated_at, path, current, source}，新在前
restore_skill_version(name, version) -> dict  # {ok, name, version, restored_from, path, changed}
SkillManagementError, UnknownSkillError
```

- **停用语义**：把 `skills/<slug>/` 整体移入 `skills_archive_dir()/<slug>-<时间戳>/`，复用既有剪枝命名；归档目录无直接 `SKILL.md`，发现逻辑天然不加载。停用后 `discover_skills` / `get_skill_by_name` / `retrieve_relevant_skills` / `build_skill_descriptions` / `build_system_prompt` 均不得再出现该技能，恢复后必须重新出现。幂等。
- **版本回退语义**：把旧版本正文写回 `SKILL.md` 并**记为新版本**（补丁位 +1，frontmatter 加 `restored-from`/`restored-at`），覆盖前先把当前内容追加为历史快照，因此回退本身可再回退，版本列表只增不减。返回的 `version` 是新版本号，`restored_from` 是请求的旧版本号。
- **失败约定**：返回 dict 的接口统一给 `{ok: false, error_code, error}` 而不抛异常；`error_code` ∈ `invalid_name / version_required / skill_not_found / version_not_found / skill_disabled / archive_failed / restore_failed`。`list_skill_versions` 对未知技能名抛 `UnknownSkillError`（`ValueError` 子类）。
- **停用中的技能不能回退版本**：需先 `enable`，否则返回 400 + `skill_disabled`。

#### 技能管理 Web 接口（I24a）

`mellowday/web_app/skills_api.py` 只导出 `router`（`APIRouter`）：

```
GET  /api/skills                              -> {"skills": [...]}
POST /api/skills/{name}/disable               -> 运行时字典原样返回
POST /api/skills/{name}/enable
GET  /api/skills/{name}/versions              -> {"name":..., "versions":[...]}
POST /api/skills/{name}/versions/{version}/restore
```

状态码：`skill_not_found`/`version_not_found` → 404；`invalid_name`/`version_required`/`skill_disabled` → 400；非法输入绝不 500。

**挂载顺序（强制）**：`app.include_router(skills_router)` 必须位于兜底路由 `/api/{unmatched:path}` **之前**，否则 `/api/skills` 会被兜底 404 吃掉。

#### 技能规则查看与编辑（第三轮 t3 新增）

```
GET  /api/skills/{name}                    -> {ok,name,description,when_to_use,version,enabled,source,path,updated_at,body(规则正文),notes(演化溯源)}
PUT  /api/skills/{name}   {description?,when_to_use?,instructions?,note?}
                                           -> {ok,name,version,previous_version,changed,path}
GET  /api/skills/{name}/versions/{version} -> {ok,name,version,current,enabled,updated_at,body,notes}
```

- 停用中的技能**可读**；`PUT` 到停用技能返回 400 `skill_disabled`。
- `instructions` 是**完整替换**；空串返回 400 `empty_instructions`。
- 无实质变化时 `changed=false`，**不写文件、不升版**。
- 写入必须复用既有 `evolve_skill_file`（历史快照 + 补丁位 +1 + usage 事件），**不得**另建一套存储。
- 未知技能/版本返回 404。编辑后必须刷新技能缓存，使后续新会话立即按新规则执行。

## 5. 存储与业务层

### 5.1 `mellowday/storage/store.py`

```python
class Store:
    def __init__(self, data_dir: Path | None = None) -> None: ...
    def list_records(self, kind: str, *, include_done: bool = True) -> list[dict]: ...
    def get_record(self, kind: str, record_id: str) -> dict | None: ...
    def create_record(self, kind: str, data: dict) -> dict: ...
    def update_record(self, kind: str, record_id: str, data: dict) -> dict: ...
    def delete_record(self, kind: str, record_id: str) -> dict: ...
    def search_records(self, kind: str, query: str) -> list[dict]: ...
    def undo(self, operation_id: str) -> dict: ...
```

- `kind` ∈ `{"todos", "calendar", "reminders", "notes", "memories"}`；未知 kind 抛 `ValueError`。
- SQLite 文件：`paths.store_path()`；`Store(data_dir)` 时库文件为 `data_dir/"mellowday.sqlite3"`。
- 记录字段：`id`(str, uuid4 hex)、`kind`、`title`、`detail`、`due_at`(ISO8601 或 None)、`status`、`created_at`、`updated_at`、`source`、`meta`(JSON)。
- 每个写操作生成 `operation_id`，`undo(operation_id)` 只能消费一次，重复调用返回同一结果且不产生二次副作用。
- 记忆类记录带 `status` ∈ `{"active","expired","deleted"}`；失效记录不进入召回。
- **裁决（2026-09-19，I04）**：`list_records(kind, *, include_done=True)` 中 `True` = 返回全部状态、`False` = 只返回有效状态（memories 即只留 active）。管理面需要看到并有权恢复已失效/已删除的记忆，因此默认值保持 `True`；而一切**召回路径**（`recall_memories` 工具与运行时记忆注入）永远只取 active，与 `include_done` 无关。两层语义不同，不要合并。
- 写方法返回「记录字段 + `operation_id`」平铺结构（不是嵌套 `record`）；`update_record` / `delete_record` 在记录不存在时抛 `KeyError`，未知 kind 抛 `ValueError`；Web 层分别映射为 404 / 400。

### 5.2 `mellowday/personal_assistant/tools.py`

```python
def tool_definitions() -> list[dict]:   # {name, description, input_schema}
async def execute_tool(store: Store, name: str, arguments: dict) -> str  # 返回 JSON 字符串
```

覆盖能力：列出/新建/修改/删除 待办、日历事件、提醒、笔记；记忆的写入/检索/更新/删除；`now` 时间参考。工具名使用 snake_case 且不含来源名称。返回值为 JSON 字符串，含 `ok`、`id`（新建时）、`error`（失败时）。**不得**暴露 shell、文件读写或任意代码执行。

## 6. Web 层（`mellowday/web_app/`）

- `create_app()`；路由前缀 `/api`。
- `POST /api/chat`：body `{"session_id": str|None, "message": str}` → SSE 或 NDJSON 事件流，事件体为第 3 节定义的结构。
- `GET /api/sessions`、`GET /api/sessions/{id}`、`DELETE /api/sessions/{id}`。
- `GET/PUT /api/config`（模型配置，PUT 不回显密钥）。
- `GET/POST/PATCH/DELETE /api/records/{kind}[/{id}]`、`POST /api/confirmations/{token}`。
- 每会话一个 `Agent` 实例，单会话串行（同一 session 的并发请求排队）；不同会话状态隔离。
- 静态前端挂载于 `/`，源文件在 `src/mellowday/web_app/static/`。

## 6bis. 会话生命周期契约（I18-I20，2026-09-19 复核后新增）

### 会话标识

- `session_id` 允许字符集：`[A-Za-z0-9_-]`，长度 1-64。
- 校验统一在 `SessionRegistry` 边界完成；不合法一律拒绝（API 返回 400），**不得创建任何文件或目录**。
- `None`/空串表示新建会话，由服务端生成合法 id。
- 任何把 `session_id` 拼进路径的代码都必须经过校验，禁止直接拼接。
- **裁决（2026-09-19，I19）**：非法 `session_id` → API 返回 400；`GET`/`DELETE` 未知会话 → 404（`GET` 不再返回空 200）；`DELETE` 成功 → `{"ok": true, "session_id": ...}`。未匹配的 `/api/*` 一律 404 JSON，不得落到静态文件挂载（Windows 下会因盘符不同抛 ValueError 变 500）。
- 会话标识相关公开接口：`validate_session_id`、`resolve_session_id`、`new_session_id`、`InvalidSessionId`、`SessionRegistry.peek/exists/adrop`。

### 一次回合的生命周期

1. 取得会话锁后，才允许启动执行任务。
2. **锁释放前必须确保执行任务已结束**：客户端断开、生成器被关闭或异常退出时，先取消任务并 await 其结束（吞掉 `CancelledError`），再释放锁。
3. 同一会话任意时刻至多一个执行中的回合。
4. 回合结束后必须落一条助手回复到展示历史（包括被取消的回合，若已产生文本）。

### 会话删除

`DELETE /api/sessions/{id}` 必须同时清理：展示历史、运行时会话文件（`sessions_dir()/{id}.json`）、折叠摘要（`{id}.folded-memory.*`）、内存中的会话状态与待确认项，并中止进行中的回合。删除后重新查询不得恢复任何内容。

### 配置生效

- 模型配置（`model`/`api_base`/`api_key`/`thinking`）在**每一轮开始时**重新读取并应用到会话的 Agent。
- 配置变化不得清空会话历史或工具状态；仅替换模型与凭据相关字段。
- `GET /api/config` 永远不回显密钥；设置页模型选项必须包含当前默认模型，并允许自定义输入。

## 6ter. 原始执行历史契约（I23）

- 每轮的原始执行记录（用户消息、助手文本、工具调用与工具结果、错误）必须以**追加**方式独立保存。
- 该记录独立于运行时的消息列表：上下文折叠、`_auto_save` 覆盖都不得改变或截断它。
- 网页历史接口读取该记录，用于展示与回放；折叠摘要只属于运行时状态。
- 折叠后重启进程，必须能依据运行时会话文件继续未完成任务。

### 6ter.1 原文与展示视图必须分开（第三轮裁决，2026-09-19）

`GET /api/sessions/{id}` 同时返回两个字段，**职责不同、不得互相替代**：

| 字段 | 内容 | 用途 |
|---|---|---|
| `trace` | **原始记录，不截断**。长参数与长结果完整保存。 | 真实发生过的内容；回放与排查的依据 |
| `trace_display` | 同一批条目的**有界展示视图**（预览、长度、引用标识）。 | 网页渲染，避免把超大 payload 塞进页面 |

- `trace` 保持既有语义不变：它是原始记录，**不得**改成截断视图。把它改成有界视图会移除网页端唯一的原文出口（Python 侧 `read_trace` 之外再无入口），与「原始历史独立保存」的验收冲突。
- 截断只允许出现在展示路径上；原始记录中的长内容必须完整且可解析（不得因为截断让工具结果的 JSON 不可解析）。
- 需要完整原文时通过受限引用读取（分页或按引用标识取回），范围**仅限业务数据或本次工具产物**；不得因此恢复任意文件读取能力。
- 会话删除必须同时清理这些产物：工具产物目录（`data_dir()/tool_results/<session>/`）与 `sessions_dir()` 下的会话文件一样，属于会话生命周期，删除后不得残留。
- 网页历史面板必须真的消费上述字段（可查看工具调用、结果与错误），否则「网页可查看原始执行记录」不算接通。

#### 6ter.2 大结果必须以结构化字段暴露引用（第三轮裁决）

事实（已核实）：`runtime/agent.py` 的 `LARGE_RESULT_THRESHOLD = 30 * 1024`。超过阈值的工具结果，
`_persist_large_result()` 会把**完整原文**写入 `data_dir()/tool_results/<session>/<ref>.txt`，
并让进入上下文与事件的字符串变成**占位提示**（含 ref 文本与 1200 字符预览）。
也就是说：trace 里大结果的 `result` 字段是占位提示，**不是原文**；原文只存在于产物文件。

- `tool_result` 事件在大结果时**必须携带结构化字段**：`ref`（裸名，非路径）、`chars`、`preview`、`truncated: true`；小结果不带这些字段。
- **禁止**让下游（如网页展开器）用正则从占位提示文本里抠 ref：那是脆弱耦合，占位文案一变就静默失效。
- trace 条目必须透传这些字段；原始 `result` 字段的语义不变（仍然是当时进入上下文的那段文本）。
- 浏览完整原文只能经由受限引用读取（ref 为裸名、限定本会话产物），不得因此恢复任意文件读取能力。

## 6quater. 事实来源契约（I22）

- **用户事实只有一个来源：SQLite 的 `memories` 记录。** Markdown 记忆文件不再是事实来源，也不得作为召回输入。
- 每轮对话在组装上下文时自动召回相关事实（不依赖模型显式调用工具）；召回只取 `status=active`。
- 召回查询必须支持无空格语言（中文）：不得以「是否包含空白字符」作为是否召回的判据。
- 事实被更新或删除后，后续任何轮次都不得再使用旧值。

### 6quater.1 事实与流程规则的边界（第四轮整改，2026-09-19）

- 事实描述用户或环境；偏好表达用户取向；流程规则规定执行任务的方法。相关事实可以与技能同时存在，例如下班时间可以作为规划规则的前提。
- 不以文本相似度、关键词或全库事实与技能正文不重叠作为正确性条件。创建、编辑、启停技能及写入事实都不得自动吞掉相关事实。
- `remember_fact(kind="workflow")` 返回结构化 `workflow_requires_skill`，引导到技能写入流程；普通 fact/preference 不作关键词猜测。模型是否正确分类仍需实际载荷门禁验证。

### 6quater.2 显式确认迁移

- 在线候选可带 `source_memory_ids`，仅接受调用方提供的 active 事实快照中的 ID；默认空列表。
- 写入确认同时展示实际规则、来源 ID 和完整事实原文。含迁移来源的候选缺少确认器或被拒绝时不得写入。
- 只有确认后成功的 add/merge 才调用 provider 的 `supersede_rule_facts`。discard、失败、未知 ID、不带来源的写入均不得改变事实状态。
- 钩子接收完整快照，只在当前 title/detail/meta/updated_at/status 与确认前一致时标记 superseded；确认期间被修改的记录保留，并显示迁移未完成提示。
- superseded 记录保留来源技能、时间、原因；退出召回但仍可管理。复用既有事实失效机制标记旧值，避免旧历史被误认为当前事实；不模糊删除历史原文。失效说明与当前召回事实应分开判断，新会话停用门禁仍检查规则泄漏。
- `fact_provider("")` 返回完整 active 集合，供旧值有效性核对和候选来源快照使用；非空查询可按相关度限量。缺少写回钩子必须显示 warning。
- 不自动恢复历史上被旧启发式误标的记录；此类数据应逐项核对后经管理界面恢复。
- 验收分别验证已确认迁移、拒绝与过期快照的无副作用、相关前提事实保留，以及停用后的实际出站载荷。没有明确迁移提案不能计作迁移成功。

## 6quinquies. 学习闭环契约（I24）

- 用户明确纠正后产生的技能候选，写入前必须经过确认；确认复用现有 `confirmation` 事件与一次性 token 机制。
- 被拒绝、跳过或失败的候选写入**必须在界面可见**，不得静默丢弃。
- 断流（客户端中断）时不再产出 `done` 事件；被外部取消的回合错误文案为「本轮已中断」。
- 助手展示历史的唯一写入点是 `_commit_turn`（会话已删除时跳过）；回合文本在 event sink 产生时即记录，不依赖客户端是否消费。
- 重复反馈合并进同一技能，不无限追加新技能。
- 停用/恢复技能必须影响后续会话的实际行为，并可查看与恢复历史版本。

#### 6quinquies.1 合并语义（第三轮修正，替换此前的强制 merge 行为）

- **`discard` 是终态**：身份命中只允许把 `add` 升级为 `merge`，**不得**把 `discard` 改写成任何写入。
  （此前 `if exact_target: action = "merge"` 会让模型明确丢弃的候选也落盘，属继承缺陷。）
- **合并必须保留仍有效的旧规则**：旧规则默认全部保留，模型漏写的旧规则会被补回；
  只有模型**逐字声明** `superseded_rules` 才允许删除某条旧规则——这是唯一的删除通道。
- 缺少 `merged_instructions` 时走确定性保留式合并，**绝不**用单条候选正文覆盖原文。
- 规则只按精确文本去重，不以相似度自动删除或替换；数字、否定及标点变化不得静默忽略。
- 一次性/长期作用域以最新用户轮为准，历史轮信号不得覆盖当前意图。
- 相同反馈且无实质变化时：`changed=false`，不写文件、不升版、不重复打扰确认，按可见 `skipped` 上报。
- 写入确认文本必须包含**实际候选规则**与**旧→新逐条对照**（含保留/删除清单）；
  最后一行必须保持 `online skill evolution: <action> <name>` 的机器可读格式（运行时解析依赖该行）。
- 技能文件内的溯源段落不得重复拼接同名的 `## Evolution Notes`。

## 6sexies. 部署契约（S07 / I26-I27）

- **端口**：容器内 `0.0.0.0:8000`；宿主机 `${MELLOWDAY_WEB_PORT:-8021}`，默认仅绑定 `127.0.0.1`。
- **数据**：`MELLOWDAY_DATA_DIR=/app/data`，由命名卷持久化，非 root 用户可写。容器重建不得丢数据。
- **编码**：容器内显式 `LANG=C.UTF-8`、`LC_ALL=C.UTF-8`、`PYTHONIOENCODING=utf-8`。不得依赖默认 locale——本项目在 cp936 上出现过中文被静默丢弃。
- **凭据**：镜像内**不得**含 `.env` 或任何密钥；凭据只在运行时通过环境变量注入。构建期不得调用模型。
- **打包**：静态资源必须随包发布（`[tool.setuptools.package-data]`）。安装式部署若界面 404，先查此处。
- **健康检查**：`GET /api/health`；容器必须能在无凭据时 healthy（未配置模型也应可用管理页）。
- **运行身份**：非 root（uid 1000）。

## 7. 内部来源约束（强制）

- 公开代码、包名、配置、界面文案、README、注释**不得**出现来源项目名称或“重构自 X”表述。内部映射只写入 `.local-planning/`（已被 gitignore）。
- 不修改 `D:\Projects\Agent Learn\Project\ChatBot` 与源码基线目录中的任何文件（源码目录只读）。
- 单元实施者不执行 `git commit` / `git push`。

## 8. 验证要求

- 每个单元交付可运行测试；离线测试不得声称“真实模型已通过”。
- 阶段门禁（真实模型）由主 agent 统一执行并记录证据到 `docs/evidence/`。
- 每个单元完成时必须声明级别：L1 机制导入 / L2 流程接通 / L3 验收通过。只做了 L1 却声明 L2 视为未完成。
- 断流、非法输入、并发、删除后残留等边界必须有回归测试，不能只测正常路径。

### 8bis. 第三轮实施纪律（每个单元动手前必读）

**测试质量**
- 测试必须断言**行为结果**（数据库里真的有什么、模型真的收到了什么、文件真的还在不在），不得用「字符串出现在源码里」「函数存在」「常量名正确」代替。
- 每条修复都要先写出**能在旧代码上失败**的复现测试，再改代码；做不到就先说明为什么。
- 完成的测试要做一次变异校验：把修复改回去，确认测试会红。变异不红的测试视为无效。

**环境陷阱（本项目已多次踩中）**
- 本机 locale 是 cp936。所有文件读写必须显式 `encoding="utf-8"`，否则中文会被**静默**丢弃或覆盖。
- 控制台显示的中文乱码**不代表**数据损坏。判断编码问题要比对字节（hex）或写入 UTF-8 文件后再读，不要靠肉眼下结论。
- 未指定 `encoding` 的 `read_text()`/`write_text()`、未指定 `TZ` 的容器、进程级全局缓存（如 `_cached_skills` 不按数据目录区分）都是已知陷阱。

**数据安全（强制）**
- 测试与门禁一律使用隔离的 `MELLOWDAY_DATA_DIR`，**不得**读写用户日常使用的 `data/`（其中含真实会话、事实与技能）。
- 门禁要隔离**完整**数据目录：数据库、会话、技能、版本记录、运行配置，不能只换 Store 的目录（技能走 `paths.skills_dir()`，与 Store 无关）。
- 凭据不得出现在日志、报告、提交或任何公开产物中；不要打印密钥，不要把它写进证据文件。

**结论纪律**
- 不得把「函数存在」「离线测试通过」「真实模型个别成功」混称为阶段完成。
- 抽样得到的比例只用于确认方向，不作为效果量；报告必须写明分母。
- 请求报错或空回复**不能**作为「某规则没有生效」的正面证据。
- 公开材料统一使用 MellowDay；来源对应与内部比较只写在 `.local-planning/`。
- 不执行 `git commit` / `git push` / 部署；保留现有未提交工作。
