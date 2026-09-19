# L3 门禁方法修正：7 条方法与它们的验证证据

日期：2026-09-18/19（第三轮）　脚本：`scripts/gate_common.py`、`scripts/gate_l3.py`、`scripts/gate_l3_learning.py`
上一版证据：`docs/evidence/P3-P4-l3-gate.md`（结论基于**方法有缺陷**的门禁，须用本版重跑后才有效）
产物：`docs/evidence/raw/gate-l3-report.json`、`docs/evidence/raw/gate-l3-learning-report.json`；每次运行的不可变副本、原始请求/响应（JSONL）与隔离数据目录在 `output/gate-runs/<gate>/<run-id>/`。

本文只解决门禁的**方法问题**：证明上一版门禁为什么不能作为验收证据，以及每一条方法问题被什么机制挡住、又如何被验证。核心演示与最小 P5 对照（T5）用本版门禁执行；本文不宣称 P3/P4 产品验收通过（学习门禁本轮恰好抓到两条未通过项，见第 4 节）。

**产物命名说明（避免误引）**：上一版门禁与本版使用同一个稳定文件名，本版第一次运行就覆盖了上一版的 `raw/gate-l3-report.json` 与 `gate-l3-learning-report.json`。本文引用的上一版内容是覆盖前读出的原文（逐字保留）。本版因此增加了「运行目录内不可变副本 + `run_id` + 起止时间 + 每次请求全文」；稳定路径的含义是「最近一次运行」而不是「唯一一次运行」。

~~~text
输出目录结构（每次运行）
output/gate-runs/<gate>/<run-id>/
  data/                        本次运行唯一的数据目录：数据库、会话、Skills、归档、演化记录、config.json
  artifacts/model-calls.jsonl  每次模型请求：模型标识、参数、payload 全文、完整响应、工具调用、用量、时延、错误
  artifacts/workspace-fingerprint.json  被测源码树的内容指纹（含 scripts/ 自身）
  artifacts/<gate>-report.json          本次运行的报告不可变副本
~~~

---

## 1. 上一版门禁的 7 条方法问题（含现场证据）

### M1 只隔离了 Store，其余运行数据全部落在真实数据目录

旧脚本只做了 `Store(data_dir=<real>/gate-l3)` + 删目录，但 `mellowday.paths` 的其余路径（Skills、会话、折叠记忆、演化记录、`config.json`、日志）都按 `MELLOWDAY_DATA_DIR`（默认 `data/`）解析：

| 现场文件（真实数据目录，时间来自上一轮门禁） | 来源 |
|---|---|
| `data/skills/旅行行程规划/SKILL.md`（2026-09-18 18:56:57） | `gate_l3.py` 的 `create_skill_file` |
| `data/skills/daily-planning-output-format/SKILL.md`（19:07:53） | `gate_l3_learning.py` 学习到的规则落盘 |
| `data/sessions/` 58 个文件（含 `habit-on-*`、`cfg-1.*`、`fact-1.*`、`learn-1.*`、`after-learn-*`） | 两个门禁的会话 |
| `data/config.json`（19:01:40） | 模型切换检查里的 `config.update_model_config` |
| `data/gate-l3/`、`data/gate-learn/`、`data/gate-learn2/`（各 1 个文件） | 唯一被隔离的部分：SQLite |

后果两条：门禁**改写日常数据**（Skills 与运行配置），且它自己的结论**依赖这些残留**。

### M2 「新会话」并不新：会话 id 跨运行复用

旧脚本从不清理 `data/sessions/`，同一批 id 被多次运行复用：`habit-on-2.*` 的时间是 18:59:57，而 `habit-on-0/1.*` 是 19:00:56/19:01:15；上一版报告的模型切换检查写着 `history_records: 12`，而该检查自己只产生 4 条记录。

### M3 报错的请求被当成「停用后没有出现规则」的成功证据

上一版 `gate-l3-report.json` 的 `disabled habit never appears in behaviour`：

~~~json
{ "check": "disabled habit never appears in behaviour", "ok": true, "hit": 0, "of": 2,
  "samples": [ { "hit": false, "reply": "",
                 "errors": ["BadRequestError: Error code: 400 - {'error': {'message':
                   \"Duplicate value for 'tool_call_id' of call_00_g6Mp8nRA4cqRFFjnIDJS2541
                   in message[4]\" ...}}"] },
               { "hit": false, "reply": "好的，我很乐意帮你规划杭州之行。…" } ] }
~~~

判据是 `not any(s["hit"] for s in off_samples)`：第一个样本请求根本没成功（空回复 + 400），照样让这一条通过。

### M4 模型切换只看了配置文件，没有看真正发出去的模型标识

旧检查先 `config.update_model_config(model=switched)` 再跑第一轮——第一轮用的已经是新模型；判据只有 `bool(second["reply"])` 与 `len(registry.history("cfg-1")) >= 4`，没有任何一步记录请求里的 `model` 字段，还改写了真实 `data/config.json`。

### M5 用关键词代替业务正确性

旧判据全部是「回复里有没有某个子串」：`MARKER in reply`、`not any(hit)`、`"18:00" in reply or "六点" in reply`、`all(t in reply for t in RULE_TERMS)`——没有一行数据库、没有一个工具参数、没有规则的结构要求。最直接的反例在上一版学习报告里：`hit 2/2` 通过，其中一个样本的回复是

~~~
**三个重点任务**
还没排——需要你告诉我明天想推进哪些事，我再帮你定成三条（并可以设时间提醒）。
~~~

用户纠正要求「只排三个重点任务」，这条回复一个都没排，检查仍然 PASS。

### M6 没有代码版本、指纹、实际模型标识、参数、完整响应、工具参数、数据库结果与分母

上一版报告字段只有 `model`、`api_base`、`checks[]`、`passed`、`failed`、`learned`：没有代码版本与工作区指纹（本重建代码是 untracked，只有 `b047844` 这个旧提交可查）、没有每次请求的模型标识与参数、没有完整响应与工具参数（只截 200–260 字符的回复片段）、没有数据库行、没有失败清单与分母。

### M7 没有凭据隔离，也没有诚实的「未运行」

旧脚本没有任何脱敏，错误文本与回复原文直接进 stdout 与 JSON 报告，而运行配置与报告同在一个仓库树里——HTTP 错误体一旦带出凭据就会落进 `docs/evidence/raw/`。无凭据时 `return 2` 且不写报告：哪些验收项没做、为什么没做，没有任何留档。

---

## 2. 修正后的门禁结构

### 2.1 共享机制 `scripts/gate_common.py`

| 机制 | 作用 |
|---|---|
| `RunContext.prepare()` | 在任何 `mellowday` 模块被导入之前，把 `MELLOWDAY_DATA_DIR` 指向本次运行目录、把 `MELLOWDAY_ENV_FILE` 置空（禁止 .env 反指真实目录），凭据只一次性写进运行目录自己的 `config.json` |
| `stat_snapshot()/snapshot_diff()/pollution_report()` | 运行前后对真实数据目录做**只读元数据快照**（路径/大小/mtime，不打开文件），证明未被触碰 |
| `bootstrap_credentials()` | 凭据只从环境变量或本机 `config.json` 读一次并立即注册脱敏；报告只含 `api_key_present` 与不可逆指纹 |
| `register_secret/redact/scan_for_secrets/install_stdout_redaction` | stdout/stderr 与所有写盘内容统一脱敏；报告写盘前再扫一次凭据，命中即判失败 |
| `code_provenance()/workspace_fingerprint()` | git HEAD/分支/脏文件 + 源码树内容指纹（含 `scripts/` 自身哈希）；运行期间源码被改动会记成 `code.workspace_unchanged_during_the_run` 未通过 |
| `ModelCallRecorder` | 挂在 SDK 方法（`AsyncCompletions.create` / `AsyncMessages.create`）上，记录每次请求的模型标识、参数、消息条数、工具清单、payload 全文、完整响应、工具调用、用量、时延与错误；运行中重建客户端也不会漏记 |
| `sample_is_valid/off_side_verdict/on_side_verdict/switch_verdict/continuity_verdict` | 全部判据集中一处，可被 `--selfcheck` 用坏样本直接检验 |
| `sample_sessions()/session_freshness()/payload_fact_block()/payload_channel_evidence()` | 每个抽样会话记录使用前的 `history_before/trace_before`，并区分规则文本是**经技能通道**还是**经事实通道**进入请求 |
| `trace_kind()` | 原始执行记录的 kind 键（契约里是 `type`）统一读取，读不到内容时不会把「空」当成「没有发生过」 |
| `Report` | 状态四值 `passed/failed/inconclusive/pending`；抽样检查带 `metrics`（命中/有效/分母）；写盘前凭据扫描；报告同时写稳定路径与运行目录不可变副本 |

### 2.2 退出码语义

| 码 | 含义 |
|---|---|
| 0 | 全部检查通过（含 L3 真模型检查） |
| 1 | 有失败或有无法判定的检查（**绝不等于通过**） |
| 2 | L3 部分没有运行（无凭据或 `--offline`）：全部标 `pending` 并写明原因，报告里 `l3.status=not_run` |

### 2.3 检查清单

`gate_l3.py`（行为门禁，30 项）：

1. 隔离：`isolation.run_directory_starts_empty`、`isolation.real_data_directory_untouched`
2. 确定性：`deterministic.habit_is_advertised_and_retrievable_only_while_enabled`（提示词与检索两条路径，启用→停用→恢复）
3. 离线事务：7 条 `offline.*`（工具写入/更新/删除/undo 与数据库一致、事实失效退出召回集、未知记录报错不抛异常）
4. `l3.model_control_reproduces_the_habit`：正向对照——端点与模型确实能做出规则要求的行为，否则「停用后没有出现」不成立
5. `l3.habit_changes_behaviour_when_enabled`：抽样，命中/有效/分母，且要求规则文本确实进入请求 payload
6. `l3.disabled_habit_never_appears`：每个样本都必须有回复、payload 不得出现规则文本、正向对照必须成立，否则 inconclusive
7. `l3.stored_fact_is_injected_without_a_tool_call`：事实文本出现在出站 payload、回复引用数值、trace 无工具调用、数据库行完好
8. `l3.model_switch_reaches_the_next_request`：按实际发送的模型序列 原模型 → 新模型 → 恢复原模型，且后一轮 payload 含前一轮对话
9. `l3.business_write_matches_the_database`：真实工具调用 + SQLite 行（标题、时刻换算）+ 不得虚假声称成功 + 出现行必须有对应 tool_call
10. `l3.deleting_a_session_removes_every_artifact`：删除后无残留、无 trace、无历史，其它会话文件未被牵连

`gate_l3_learning.py`（学习闭环门禁，33 项）：

1. 同上隔离与离线检查；另外种下 1 条真实固定日程与 6 条真实待办（否则「只排三个」无法与「把输入复述一遍」区分）
2. `l3.pre_learning_control_does_not_follow_the_rule`：学会之前同样的请求不得已经满足规则
3. `l3.denied_confirmation_writes_nothing`：拒绝确认不得写入，且拒绝可见；若没有提出候选则 inconclusive
4. `l3.correction_produces_a_rule`：候选事件 + 确认 token + applied 事件 + 真实 `SKILL.md`（含版本与路径，位于运行目录内）
5. `deterministic.rule_text_covers_the_correction`：落盘正文覆盖纠正的两个要求
6. `deterministic.rule_enters_a_new_session_prompt`：新会话提示词含技能名与描述（规则正文由技能调用按请求投递，由 payload 探针验证）
7. `l3.correction_does_not_duplicate_the_rule_into_the_memory_store`：纠正不得同时落进用户事实库——事实会被注入**每一个**会话，与技能启停无关
8. `l3.a_new_session_follows_the_learned_rule`：抽样；每条有效样本都必须体现真实记录、三个重点任务、条目 ≤3，且规则文本确实进入请求
9. `deterministic.disabled_rule_leaves_the_prompt` 与 `l3.disabled_rule_stops_changing_behaviour`：停用后提示词与行为两侧同时消失；失败时区分是「技能仍被投递」还是「事实通道仍在投递」
10. 对比回合前把业务行还原到种下状态（`restore_business_baseline()`），使 before/after/停用 三个条件面对同一份数据；事实库**故意不还原**，因为「重复写入事实库」本身是被检查对象

---

## 3. 逐条修正 → 验证（本轮真实运行）

| 方法问题 | 修正 | 验证证据 |
|---|---|---|
| M1 只隔离 Store | `RunContext.prepare()` 在导入前锁定完整数据目录；只读快照比对 | `isolation.real_data_directory_untouched`：真实目录 78 文件快照，`added/removed/changed = 0/0/0`，两次运行都通过；运行目录内含数据库、`sessions/`、`skills/`、`skill_evolution/`、`config.json`（见第 4 节结构） |
| M2 会话复用 | 会话 id 带 run id；使用前断言 `history_before==0 and trace_before==0`；运行目录 `exist_ok=False` | 两个门禁的每条抽样都带 `freshness` 字段：`history_before/trace_before = 0/0`、`fresh=true`（例如 `habit-on-441Z-3795-0/1`、`after-611Z-7a79-0/1`、`off-611Z-7a79-0/1`） |
| M3 报错当证据 | `sample_is_valid()` + `off_side_verdict(control_ok=...)` + 出站 payload 探针 | 行为门禁停用侧：`hits 0/2, valid 2/2, control_ok true, payload_leaks 0`；自检 `selfcheck.off_side_rejects_dead_requests` 在同一输入上给出「旧判据通过 / 新判据拒绝」 |
| M4 切换未验证 | 记录每次请求的模型标识，按序列判定；连续性用后一轮 payload 里的前一轮文本判定 | `requests_model_sequence` = 13×`deepseek-v4-pro` → 2×`deepseek-flash` → 2×`deepseek-v4-pro`；第一轮请求 seq 1–13、第二轮 14–15；`continuity = {prior_user_message: true, prior_assistant_reply: true, history_has_four_records: true}`；历史 6 条 |
| M5 关键词代替正确性 | `evaluate_rule()`（首行/小节/条目预算/任一组合）+ 工具参数与 SQLite 行 + 真实记录出现在计划里 | 习惯侧每条样本断言 `marker_on_first_line / section:第一天 / section:第二天 / no_section:第三天`；习惯停用侧 payload 无规则文本；业务侧 2/2 样本：trace 各 1 次 `create_todo`、新增 1 行、落库时刻 `2027-03-01T02:00:00+00:00` = 请求的 10:00+08:00；事实侧 `fact_text_in_outbound_payload=true`、`tool_calls_in_trace=[]`；学习侧每条样本必须出现真实行 `每日站会` 且重点任务条目恰为 3 |
| M6 证据缺失 | 运行元数据、代码版本与指纹、模型配置、每次请求全文（另存 JSONL）、数据库视图、失败清单、每个指标的分母 | 报告含 `run/code/isolation/model_config/requests/model_calls/database_after/artifacts`；两次运行指纹：行为 `6ed0818ddbc14150`（88 文件，运行期间未变）、学习 `6ed0818ddbc14150`（运行期间 1 文件变化 → `code.workspace_unchanged_during_the_run` inconclusive）；每次请求写入 `artifacts/model-calls.jsonl`（行为 22 条、学习 25 条，0 错误） |
| M7 凭据与假 L3 | 脱敏表 + stdout 包装 + 报告写盘前扫描；无凭据/离线一律 `pending` 且退出码 2 | `secrets.no_credential_in_artifacts`：行为报告扫描 68,911 字符、学习报告 126,309 字符，命中 0；独立复核：两个报告里 `sk-[A-Za-z0-9]{24,}`、`Bearer …`、带值的 `api_key` 字段均为 0 匹配，只有 `api_key_present` 与 `api_key_fingerprint`；离线运行输出 `7/9 pending` 且退出码 2 |

### 3.1 判据自检（负向对照，`--selfcheck`，两次运行 11/11 通过）

| 自检项 | 输入 | 结果 |
|---|---|---|
| `selfcheck.off_side_rejects_dead_requests` | 空回复 + 400 错误 | 拒绝；报告同时打印同一输入上旧判据的结论（「通过」） |
| `selfcheck.off_side_requires_a_meaningful_control` | 有效样本、无正向对照 | 拒绝 |
| `selfcheck.off_side_accepts_a_valid_absence` | 有效样本 + 成立对照 | 通过 |
| `selfcheck.on_side_never_passes_without_an_answer` | 全为无效样本 | 拒绝 |
| `selfcheck.rule_check_needs_the_marker_on_the_first_line` | 标记出现在第二行 | 拒绝（完整满足规则的回复仍通过） |
| `selfcheck.switch_check_rejects_a_config_only_change` | 序列 `A→A` | 拒绝（`A→B→A` 通过） |
| `selfcheck.continuity_check_rejects_a_lost_turn` | 后一轮 payload 不含前一轮 | 拒绝 |
| `selfcheck.leak_scan_catches_a_credential_shape` | 含凭据形状的文本 | 命中；干净文本不命中 |
| `selfcheck.paths_resolve_inside_the_run_directory` | 真实 `paths.data_dir()` | 等于运行目录 |
| `selfcheck.trace_reader_uses_the_record_kind_key` | `type` 与 `kind` 两种键 | 都识别；普通记录不误判 |
| `selfcheck.recorder_is_installed` | 录制器安装 | 通过（真正的验证由 L3 段完成） |

### 3.2 门禁自己被抓到的 4 个方法缺陷（本轮真实运行的副产品）

新门禁第一次真实运行时，第一个「失败」不是产品缺陷，而是**门禁自己**的：

1. `trace_tool_calls()` 按 `entry["kind"]` 读原始执行记录，而契约把类型存在 `type` 上——于是「没有工具调用」这类断言在空记录上**恒真**。修正：新增 `trace_kind()` 同时识别两种键并补自检；业务检查再加一条「出现了行却没有对应 tool_call」的硬失败。
2. 业务抽样把**所有**同名行算进单个样本（样本 0 写下的行被样本 1 看到），第一版报告因此报出「同一请求写了 2 行」的假失败。修正：按 id 增量只统计本回合新增的行，并记录 `request_seqs`。
3. 凭据形状启发式 `sk-[A-Za-z0-9_\\-]{8,}` 命中了模型自己写的标签 `task-skill-…`，把它脱敏成 `task-<redacted>` 后又判自己「泄露凭据」。修正：收紧为 `sk-[A-Za-z0-9]{24,}`（真实密钥形状）；注册密钥的精确比对仍是权威判据。
4. 学习门禁曾在运行时崩溃（变量未传入函数）而**没有写报告**。修正：两个门禁把 L3 段包在 try/except 里，异常记为 `l3.runner_completed_without_an_exception` 失败项后照常写报告——崩溃也必须留下证据。

---

## 4. 本轮运行结果

模型：`deepseek-v4-pro`，端点 `https://api.deepseek.com`，凭据来源「本机 `data/config.json`」，请求参数：`stream=true`、`thinking=false`、`max_turns=null`。

### 4.1 行为门禁 `gate_l3.py` —— 30/30 通过

~~~
命令： python scripts/gate_l3.py --attempts 2 --selfcheck
run_id： 20260918T120441Z-3795      2026-09-18T12:04:41Z → 12:06:10Z
指纹：  6ed0818ddbc14150（88 个源文件，运行期间未变化）
结果：  30 passed / 0 failed / 0 inconclusive / 0 pending，退出码 0
请求：  22 次，0 错误；模型标识 {deepseek-v4-pro, deepseek-flash}；用量 101,713 / 3,939 tokens
产物：  output/gate-runs/l3-behaviour/20260918T120441Z-3795/
~~~

| 检查 | 结果与分母 |
|---|---|
| 隔离（运行目录、真实目录） | 通过；真实目录 78 文件快照 0 变化 |
| 习惯提示词与检索（启用/停用/恢复） | 通过（技能名+描述在提示词与检索结果里出现/消失/恢复） |
| 离线事务 7 项 | 全部通过（含 undo 还原、事实失效退出召回集、未知记录不抛异常） |
| 正向对照（规则明确给出时模型能做到） | 通过 |
| 启用侧行为（抽样 2） | 2/2 命中；每条断言 `marker_on_first_line / section:第一天 / section:第二天 / 无第三、四天` 全真；规则文本 2/2 进入请求 payload |
| 停用侧行为（抽样 2） | 命中 0/2，有效 2/2，对照成立，payload 泄漏 0 |
| 事实注入 | 通过：事实文本出现在出站 payload、回复含 `18:00` 与 `六点`、trace 无工具调用、库中 1 行 |
| 模型切换 | 通过：13×`deepseek-v4-pro` → 2×`deepseek-flash` → 2×`deepseek-v4-pro`；后一轮 payload 含前一轮 user 与 assistant 文本；历史 6 条 |
| 业务写入与数据库（抽样 2） | 2/2：trace 各 1 次 `create_todo` + 1 条 tool_result，各新增 1 行，落库 `2027-03-01T02:00:00+00:00`（= 10:00+08:00），无虚假声称 |
| 会话删除 | 通过：残留 0、`exists_after=false`、trace 0、历史 0、其它会话文件未被牵连 |
| 凭据扫描 | 通过：68,911 字符 0 命中 |

### 4.2 学习门禁 `gate_l3_learning.py` —— 30 通过 / 2 失败 / 1 无法判定

~~~
命令： python scripts/gate_l3_learning.py --attempts 2 --selfcheck
run_id： 20260918T120611Z-7a79      2026-09-18T12:06:11Z → 12:08:59Z
指纹：  6ed0818ddbc14150（运行期间 1 个源文件被其它单元改动 → workspace 检查 inconclusive）
结果：  30 passed / 2 failed / 1 inconclusive / 0 pending，退出码 1
请求：  25 次，0 错误；模型 `deepseek-v4-pro`；用量 120,294 / 10,030 tokens
产物：  output/gate-runs/l3-learning/20260918T120611Z-7a79/
~~~

通过的部分（P4 正向链路首次带真实记录闭环）：

| 步骤 | 证据 |
|---|---|
| 学前对照 | 通过：同一请求在学会之前**不满足**规则（回复用「明天已有安排」+ 6 条待办列表，条目数 > 3） |
| 拒绝确认不写入 | 通过：出现过 1 个确认（token），拒绝后 `skills_written=[]` |
| 纠正产生规则 | 通过：`skill_candidate_proposed` → 确认 token → `skill_candidate_applied`；落盘 `每日规划先列固定日程并限三项重点任务` v0.1.0，路径在运行目录内 |
| 规则正文覆盖纠正 | 通过：`固定日程 / 重点任务` 两个要求都在正文里 |
| 进入新会话提示词 | 通过：技能名与描述都在 `build_system_prompt()` 里 |
| 新会话遵循规则（抽样 2） | 2/2 命中：`固定日程` 与 `重点任务` 小节、真实行 `每日站会` 出现在计划里、重点任务恰为 3 条；规则文本 2/2 进入请求 |
| 停用后提示词 | 通过：技能名从提示词消失 |

未通过的两条（**同一个产品缺陷**，两次独立运行都可复现：`…f535` 与 `…7a79`）：

| 检查 | 结果 | 证据 |
|---|---|---|
| `l3.correction_does_not_duplicate_the_rule_into_the_memory_store` | 失败 | 事实库里出现 1 条 active 事实：标签 `规划方式`，内容「帮我规划当天安排时，必须先列出当天已有的固定日程（日历事件），然后只排三个重点任务，不要一次列十几条。」 |
| `l3.disabled_rule_stops_changing_behaviour` | 失败（命中 1/2；技能通道 0/2，事实通道 **2/2**） | 停用技能后的两次请求 payload 里都没有技能名，但都含 `<system-reminder> Recalled facts … - 规划方式 [preference]: … 先列出当天已有的固定日程，然后只排三个重点任务 …`；其中一次回复仍然完整满足规则 |

根因不是门禁：纠正发生后，运行时**既**把规则写成技能（P4 的正链路），**又**把同一句话记成用户事实；而事实由 `build_fact_provider` 在每一轮注入到**任何**会话，与技能的启用状态无关。因此「停用这个习惯」在用户可见行为上不生效——这正是 I12/I24 的验收语句「停用/恢复规则实际影响后续执行」的反例。

---

## 5. 结论、给团队的产品发现与限制

### 5.1 方法层面（本文的验收对象）

- 七条方法问题逐条有实现对位与运行证据（第 3 节）；每条修正都有一个**负向对照**（3.1）说明它真的能失败。
- 门禁不再改动本机日常数据目录：两次真实运行都从只读快照证明 0 变化；运行数据（数据库/会话/Skills/配置）全部在 `output/gate-runs/<gate>/<run-id>/data/`。
- 每个样本都有分母（命中/有效/总样本）与「无效样本」清单；报错的请求只可能让检查 inconclusive，不可能让它通过。
- 报告可溯源：`run_id`、起止时间、`argv`、Python 与 SDK 版本、git HEAD/脏文件数、88 文件的工作区内容指纹（含门禁脚本自身哈希）、每次请求的模型标识/参数/完整响应/工具调用/用量，以及运行目录内的原始 JSONL。

### 5.2 产品发现（交主控裁决，本文不修改产品代码）

1. **学习闭环把同一条纠正写进两个通道**：技能库（可启停、可版本回退）与用户事实库（每轮强制注入、无启停）。后果：停用习惯无效；而且事实库里的规则会被后续「重述」学习流程视为可合并的既有内容，产生漂移。
   - 对 T5 的直接影响：P5「关闭 Skill」条件必须同时处理事实通道（否则该条件并不等于「没有这条规则」）；建议 T5 在对照里显式记录事实通道状态，或先由 T2/T3 决定口径。
   - 三种可选口径（需主控定）：(a) 纠正只落技能库，不写事实；(b) 停用技能时同时失效由该纠正派生的事实（需要 provenance 关联）；(c) 明确「习惯 = 技能 + 事实」，把启停做成统一开关。
2. 若采用 (a)/(c)，本门禁的两条失败检查即刻转绿——这正是本版本门禁的价值：它把「停用习惯无效」从一个主观判断变成了可复现的失败项。

### 5.3 限制与待验项

- **代码版本正在变动**：学习运行期间有 1 个源文件被其它单元改动（`code.workspace_unchanged_during_the_run` inconclusive），两份报告描述的是 `fingerprint 6ed0818ddbc14150` 这一版；T1–T3 落地后 T5 必须重跑，并以新指纹为准。
- **抽样规模小**：`--attempts 2`，只用于确认方向与结构，不作为效果量指标；分母已写在每个 `metrics` 里。
- **门禁走的是运行时路径而非 HTTP**：调用 `SessionRegistry.run_turn`（与网页层同一条路径），HTTP/SSE 端到端由 `tests/web_app/smoke_real_process.py` 覆盖，本门禁不重复。
- **凭据处理**：凭据只从本机 `data/config.json`（或环境变量）读一次，写入运行目录自己的 `config.json`（`output/` 已被 `.gitignore:30` 忽略），报告与日志中 0 命中；本机密钥未进入仓库，也没有提交/推送。
- **未验证**：P5 三条件对照（T5）、主动问候/每日回顾（P6，本轮无门禁）、以及上述产品缺陷修复后的复跑。

### 5.4 复现步骤

~~~powershell
cd MellowDay-Rebuild

# 1) 判据自检 + 离线检查：不需要模型；退出码 2 表示 L3 未运行
python scripts/gate_l3.py --offline --selfcheck
python scripts/gate_l3_learning.py --offline --selfcheck

# 2) 真实模型 L3（凭据来自环境变量或本机 data/config.json，只读一次，不落报告）
python scripts/gate_l3.py --attempts 2 --selfcheck
python scripts/gate_l3_learning.py --attempts 2 --selfcheck

# 3) 复核产物
#    报告：docs/evidence/raw/gate-l3-report.json、gate-l3-learning-report.json
#    不可变副本、原始请求/响应、指纹：output/gate-runs/<gate>/<run-id>/artifacts/
#    隔离数据目录（数据库/会话/Skills/配置）：output/gate-runs/<gate>/<run-id>/data/
~~~

运行目录以 `exist_ok=False` 创建：同一 run id 不可能被复用；`--run-id` 可固定 id 便于对照，但必须先移除同名目录（刻意如此：宁可失败，也不要悄悄复用旧会话）。真实数据目录在运行前后只做只读元数据快照，任何差异都会让 `isolation.real_data_directory_untouched` 失败。
