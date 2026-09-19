# T14 复核（第二轮）：t13 修复后的核心演示与 P5 是否成立

复核时间：2026-09-18（第三轮）　复核人：sessions-store（t14，独立于 t13/verifier）
结论：**needs_revision（证据主体与 F1–F4 修复均成立，但文档有两处claim 需要修订）**。我的独立重跑：run `20260918T134139Z-2e68`，**19 passed / 1 failed / 2 inconclusive**（t13 报告 `…97b4` 为 21/0/1）。

## 1. 复核方法

1. 独立重跑文档命令（真实模型 + 真实 uvicorn + 真实重启子进程），报告写到独立文件，不覆盖 t13 的报告：
   `python scripts/demo_core.py --attempts 2 --json-out docs/evidence/raw/core-demo-report-t14-rerun.json`
2. 自写脚本只读运行目录产物：SQLite 行 vs 工具调用参数、事实是否进入出站载荷、写入是否有重复。
3. 用原始报告重算 P5 六格命中与分母，并核对三组 config 字节、种子与 holdout 写入时刻。
4. 读 `scripts/demo_core.py` / `evals/p5_compare.py` / `scripts/gate_common.py` 源码核对 F1–F4 与门禁方法修正；对新的结构判据做 5 个真实样本的人工审计。

## 2. t13 的四项修复：独立验证全部成立

| 修复 | 我的独立验证 |
|---|---|
| F1 折叠段崩溃 | `demo_core.py:1005` 已补 `from mellowday.runtime.skills import reset_skill_cache`；**我的 run** 产出 `artifacts/restart-phase.json`（659 B，restored_message_count=6、task_title_in_restored_state=true）与 `restart-phase.log`（restart phase: restored 6 messages, reply 68 chars），`demo.session_continues_after_restart` **通过**（check 19），报告 22 项（旧版只有 21 项且缺该检查） |
| F2 字面量判据 | `evaluate_structural_rule()`（demo_core.py:124）只断言结构：真实日程出现且自成一块、存在「顶层恰 3 条且 ≥2 条是真实待办」的重点块、≥3 条真实待办被采用、任一块 ≤10 条；显式**不**断言小节标题，阈值写入 `evidence.thresholds`；`evals/p5_compare.py` 也改用同一函数（导入共享实现）。我对 5 个真实样本逐条人工审计（off 组 6 条列表 → 不构成重点块，判失败正确；fixed 组某样本声称「日历里没有固定日程」且把 6 条待办塞进「固定日程」→ 日历断言失败，判失败正确；合规回复判通过）——判据语义与业务要求一致，且不再依赖措辞 |
| F3 探针写死 | `pick_body_probe(body, description)`（demo_core.py:85）在运行时从当次正文规则区派生；我的 run 报告里 `probes.body_probe = "description: 在帮助"`（当次正文派生），`evals/p5_compare.py` 同样使用该函数 |
| F4 文档数字 | `P3-P4-core-demo.md` 第 8 行现写「抽样 2 次全部满足结构断言（2/2，阈值 ≥1）」并注明 t5 那次为 1/2、数字按运行标注 |

## 3. 逐项场景核对（我的独立 run）

| 场景 | 我的 run 结果 | 独立核对方式 |
|---|---|---|
| 规划同时用日历/待办与当前事实 | 通过 | check 3 + 我自写分析：计划请求 payload 含两条 active 事实正文，回复含 09:30 每日站会与 6/6 待办 |
| 工具参数 ↔ 数据库最终结果 | 通过 | 12 行记录；`remember_fact`/`create_todo` 每次写调用的参数都有唯一对应行；无重复 (kind,title)、无未匹配写入；38 次模型调用 0 错误 |
| 纠正→审查确认→新会话遵循 | 通过 | check 4/6/7；真实 uvicorn 的 GET/PUT/versions 全 200 |
| 重复反馈合并 | 通过 | check 8（skipped，不升版） |
| 临时要求不学习 | 通过（本次） | check 9：learning_events 仅 `skill_candidate_skipped`，`skill_candidate_applied_in_this_turn: []`；**注意**：该检查是单样本，t5 那次与我的 t6 复核那两次都判失败——见 N3 |
| 当前要求覆盖习惯 | 通过 | check 10（列出 6/6 待办） |
| 无关请求不加载规划规则 | **失败** | check 11：payload 的 `<retrieved_skills>` 块带上了「每日规划输出规则」(score=0.085)，`retrieved_block_mentions_rule=true`；回复与新建待办都正常——是**检索通道真的加载了规则**，见 N1 |
| 停用/恢复/版本回退 | 停用侧 inconclusive（设计如此） | check 12 通过（提示词无规则、payload_leaks=0）、check 14 通过（恢复后 2 样本满足结构断言）、check 15 通过（回退 0.1.0）；check 13 仍是 blocked/inconclusive，文档已写明「本演示不给结论，权威结论取自学习门禁」 |
| 折叠与重启后继续 | 通过 | check 16/17/19 + 我直接读 restart-phase.json/log；check 18（折叠场景不得产生技能：`new_skills: []`）通过 |

没有任何场景停留在「代码看起来支持」：9 个场景组在我的 run 里都真实执行并留有产物。

## 4. P5 核对（重算，不采信表格）

- 三组运行 `133334Z-7136` / `133510Z-caac` / `133705Z-e37c`，指纹同为 `039361a98e2a0b84`（与我的演示重跑起始指纹一致）。
- 三组 `data/config.json` **字节完全相同**（sha256 `f06a5f4bea7ca7ce`）→ 同模型参数成立。
- 种子一致：dev（每日站会 + 6 待办 + 2 事实）、holdout（客户复盘会 + 4 待办）三组相同；learned 组 holdout 记录创建于纠正写事实（13:37:23）之后（13:37:33）→ 「holdout 在学习轮之后写入」仍成立。
- 我重算的命中与文档表格逐格一致：off 0/3、0/3；fixed 2/3、1/3；learned 2/3、3/3；每格 valid=3；`failures` 数组 = 未命中样本；逐样本 `hit == structural.ok == 无失败断言` 自洽；断言名已是结构名（`a_block_presents_exactly_3_priority_tasks` 等），不再是小节字面量。
- 未宣称提升比例：脚本与文档只报计数；文档明确「两个差值都在抽样噪声范围内」。

## 5. 门禁方法 1–7（复核要点）

- M1 完整数据目录隔离：`RunContext.prepare()` 在导入 mellowday 前 pin `MELLOWDAY_DATA_DIR`、置空 `MELLOWDAY_ENV_FILE`、运行目录必须新建、真实目录只做只读快照；我此前独立跑 `gate_l3.py --offline` 12 passed（含 `real_data_directory_untouched`），本次演示 check 20 也通过（0 变化）。
- M3 死请求不算证据：`off_side_verdict()` 要求「每个样本都答了 + 阳性对照成立 + 无 payload 泄漏」才可能返回 True，否则给出 inconclusive 理由；演示里 check 13 的 blocked 语义与之一致。
- M2/M4/M5/M6/M7 与 T6 复核时相同（运行目录新建 + freshness、按实际发出的 model 标识判定、数据库行级断言、指纹/参数/完整响应/分母、凭据脱敏与落盘前扫描 0 命中）。
- 仍未闭合（t13 已如实声明）：学习门禁尚未在 t16 树上重跑——停用侧行为与「取代是否真的发生」的权威结论只能由它给出；我的 run 里 `scripts/gate_l3_learning.py` 在运行期间被改动（check 21 inconclusive 的唯一 changed_file），也印证这块仍在施工。

## 6. 需要修订的两处（findings）

### N1 [medium] 文档第 7 行「无关请求不加载规划规则 = 通过」是单样本结论，我的独立重跑在同一代码上失败且原因是真实加载

- 我的 run（`…2e68`）check 11：`retrieved_block_mentions_rule=true`，payload 里 `<retrieved_skills>` 明确带「每日规划输出规则 (score=0.085)」；回复与业务写入都正常，失败点就是「检索块把规则带进了无关请求」。
- 归因：这是**产品行为**（检索器把规划技能投给了「记一条待办」这类无关请求），不是 t13 的回归；演示脚本判失败是正确的。
- 必需修订：文档第 7 行改为「该次运行通过（1 个样本）」并记录这次反例；同时请主控把「无关请求被检索到规划规则（score 0.085）」作为产品发现派单（检索阈值/命中条件）。

### N2 [medium] 文档声称「三个合成用例锁定语义」，但仓库里没有这些用例的任何可执行产物

- 全仓检索 `evaluate_structural_rule` / `structural`：只有定义与调用点（`scripts/demo_core.py`、`evals/p5_compare.py`）与文档文字，没有测试、没有 selfcheck 分支、没有 fixture；`scripts/demo_core.py` 的 `--selfcheck/--no-selfcheck` 参数（第 250 行）是**无人使用**的开关（没有 `run_predicate_selfcheck` 调用）。
- 影响：这个判据现在同时决定演示的命中与 P5 六格的分母，却没有负向对照（对比：`gate_common.run_predicate_selfcheck` 有 15+ 条负向自检）。我用 5 个真实样本的人工审计替代（结论一致，见第 2 节），但「锁定」一词需要有产物支撑。
- 必需修订：把三个合成用例提交为可执行负向对照（例如给 `demo_core.py --selfcheck` 接上 `run_predicate_selfcheck` 并加入结构判据用例），或把文档措辞改为「一次性人工验证」。

### N3 [low] 单样本场景的波动没有在文档里说明

- `demo.temporary_request_is_not_learned` 在四次运行里 flip：t5 `…6493` 失败、t6 复核 `…d031` 失败、t13 `…97b4` 通过、t14 `…2e68` 通过；第 7 行同样是 1 个样本。文档的限制段只写了「命中类结论抽样 2 次」。
- 必需修订：每行标注分母（第 5/7 行是 1 个样本），并把已观测到的波动（至少这条）写进限制，避免把单次抽样当成稳定结论。

## 7. 限制

- 我的 run 期间 `scripts/gate_l3_learning.py` 被其它单元改动，`code.workspace_unchanged_during_the_run` 判 inconclusive（changed_files 仅此 1 个）；我的结论对应起始指纹 `039361a98e2a0b84`（与 t13 的运行指纹相同，因此两次运行面对的是同一版演示代码）。
- 我未修改 `scripts/**`、`evals/**`（不在 t14 写入范围）；本轮只在 `docs/evidence/` 下新增本文件与我的重跑报告。

## 8. 复现

~~~powershell
cd MellowDay-Rebuild
python scripts/demo_core.py --attempts 2 --json-out docs\evidence\raw\core-demo-report-t14-rerun.json
# 对比：docs/evidence/raw/core-demo-report.json（t13 …97b4） vs core-demo-report-t14-rerun.json（本次 …2e68）
# 运行产物：output/gate-runs/core-demo/<run-id>/{data,artifacts}（含 restart-phase.json/log）
~~~
