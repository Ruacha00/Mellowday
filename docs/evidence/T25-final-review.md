# T25 终局独立复核：t23 收口证据是否可信

复核时间：2026-09-18（第三轮）　复核人：sessions-store（t25，独立于 t23/verifier）
结论：**pass**。收口证据在同一指纹上被我独立复现；三个产品缺陷（N4/N6/N8）与 N5 探针口径都在最终树上用我自己的观察验证；未发现把「机制导入」当成「验收通过」的表述。

## 0. 我的独立复现（不采信 t23 自述）

| 项目 | 我的运行 | 结果 |
|---|---|---|
| 核心演示（真实模型 + 真实 uvicorn + 真实重启子进程） | run `20260918T153652Z-e83e`，报告 `docs/evidence/raw/core-demo-report-t25-rerun.json` | **24 通过 / 0 失败 / 0 无法判定（24 项）**；起始指纹 `0c0c0d7f636fde67`（与 t23 四次运行相同）；`code.workspace_unchanged_during_the_run` 通过（起止相同、0 变化） |
| 判据自检 `demo_core.py --selfcheck` | `20260918T153725Z-3d64` | **24 通过 / 0 失败**，含 `leak_judgement_reports_a_rule_only_in_the_facts_segment`、`body_probe_comes_from_the_instructions_not_the_front_matter`、`delivery_is_seen_even_when_only_the_tool_result_carries_the_rule` |
| 确定性行为套件（N4/N6/N8） | 我直接跑 `tests/runtime/{test_rule_fact_disabled_skill_claim,test_rule_fact_invariant,test_rule_fact_write_time_supersession,test_rule_fact_orphan_supersession,test_tool_status_filter}.py` | **42 passed** |
| N5 判据（自己的合成用例） | 用 `gate_common.payload_probe_locations` 直接分类 | 规则句只在召回段 → `in_recalled_facts_block` 命中；缺失 → 全空；名字探针在「只在事实段」时为假 |
| N6（自己的工具探针） | 真实 `Store` + `execute_tool` | `status="open"` → `count=1`（含 09:30 每日站会，`due_at_local` 正确）、`status_filter={requested:open, applied:not-done}`；未知词 → 结构化错误且**无 records**；无 status/精确词/include_done 语义不变 |
| N4/N8（自己的运行时探针） | `service.build_agent` + 真实技能库 + 真实 Store | 启用窗口与**停用窗口**写下的规则事实都被立即取代，`superseded_skill_state` 分别记 enabled/disabled；取代不启用技能、记录保留；无关事实（美式咖啡）不被误取代 |
| P5 重算 | 从 `docs/evidence/raw/p5-comparison-report.json` 重算 | 三臂**同一指纹** `0c0c0d7f636fde67`、每臂 9/9 且 workspace 通过；六格 `off 0/3 与 0/3`、`fixed 2/3 与 3/3`、`learned 3/3 与 3/3`，与文档逐格一致；`same_model_configuration=true`；不计算提升比例 |

## 1. 九组场景与折叠+重启段（acceptance 第 1 条）

我的 run 的 24 项检查全部通过，九组场景**都真实执行**且留有产物：
1 规划用到日历/待办与事实（`calendar_event_in_reply=true`）、2 纠正→确认→落盘、3 新会话遵循规则（结构断言 5/5）、4 重复反馈合并（skipped）、5 临时要求不学习（本样本无写入）、6 覆盖习惯（6/6 待办）、7 无关请求不加载（**sampled 2**）、8 停用/恢复/回退、9 折叠与重启。
折叠+重启段**注册并执行**：`demo.folding_replaces_history_with_folded_memory`、`demo.session_continues_after_folding`、`demo.one_off_instructions_do_not_create_skills`、`demo.session_continues_after_restart` 四项都在，产物 `artifacts/restart-phase.json`（678 B）与 `restart-phase.log`（restored 6 messages, reply 61 chars）齐备，子进程退出码 0。

## 2. 工具参数 ↔ 数据库最终行（acceptance 第 2 条）

我自写脚本只读 `data/mellowday.sqlite3` 与 `artifacts/model-calls.jsonl`：13 行记录；4 次写调用（2×`remember_fact` + 2×`create_todo`）各有唯一对应行；无重复 (kind,title)、无未匹配写入；36 次模型调用 0 错误。两条规则事实（纠正轮 `规划方式` 与重复反馈轮 `每日规划规则`）**都被取代**并带溯源（`superseded_by_skill=daily_planning_focus_rule`、`superseded_at`、`superseded_reason`；后者写入与取代相隔 31 ms，即写时即取代），活动事实只剩两条种子事实。

## 3. P5 三臂同指纹与分母（acceptance 第 3 条）

- 三臂运行 `152406Z-90e9` / `152559Z-2dfb` / `152801Z-a226` 起始指纹**同为** `0c0c0d7f636fde67`，每臂 `code.workspace_unchanged_during_the_run` **通过**，`arms_isolated_in_separate_processes=true`，报告 `same_model_configuration=true`，凭据扫描 0 命中；t20 的跨指纹边界已消除。
- 我重算六格与文档逐格一致，每格 valid=3；`failures` 数组等于未命中样本；逐样本 `hit == structural.ok == 无失败断言`。
- 未宣称提升比例：报告 `note` 与文档读数边界都明确「只报告计数、不计算提升比例、n=3 只确认方向」，并且**不**回答「学习规则是否优于人工技能」。

## 4. N5 探针口径（acceptance 第 4 条）

- 演示现在复用 `gate_common.payload_probe_locations` 单一实现，并新增检查 `demo.disabled_rule_leaves_no_rule_text_in_the_payload (sampled 2)`；我的 run 该项通过，样本给出三段式定位全空（`via_recalled_facts=0`、`via_superseded_values=0`、`present_anywhere=[]`）。
- 我自己的合成用例确认判据方向正确：把规则句**只**放进召回段 → 分类器报 `in_recalled_facts_block`（构成泄漏）；放错段标记时仍报 `present_anywhere`（不会假阴性）；缺失 → 全空（不会假阳性）。也确认了旧式「规则名」探针在事实段泄漏时为假——这正是 N5 的成因。
- 文档第 8 行与第 9 节的口径（三段式 + 对照 + 不放宽判据）与实现一致。

## 5. N4/N6/N8 在最终树上的行为（acceptance 第 5 条）

- **N4（重复反馈窗口）**：我的演示 run 里该窗口写下的事实 `每日规划规则` 在 31 ms 内被取代并带溯源；活动事实集无规则事实。
- **N8（停用期间重述）**：我的运行时探针显示停用技能仍是认领者，事实被取代且 `superseded_skill_state=disabled`、reason 写明「currently disabled」；取代不启用技能、记录保留；无关事实不被误取代（对照）。
- **N6（状态词）**：我的工具探针 `status="open"` 返回 `count=1` 且含真实日程并回显 `status_filter`；未知词返回结构化错误（无 `records`）；演示第 1 行因此通过；学习门禁与 P5 六格的 `via_facts_samples` 全 0 与取代断言互相印证。

## 6. 指纹与运行期间的文件变更（acceptance 第 6 条）

- 我的 run 起始/结束指纹相同（`0c0c0d7f636fde67`，105 个源文件），0 个文件变化 → 本结论对应**就是** t23 描述的那版代码；t23 的四次运行/自检与我这次五份证据共享同一指纹。
- 我未修改 `src/**`、`scripts/**`、`evals/**`；本轮只在 `docs/evidence/` 下新增本文件与重跑报告（我的探针脚本都在系统临时目录）。

## 7. 仍未通过 / 仍无法判定 / 未纳入（acceptance 第 7 条，如实列出）

1. **t23 演示第 8 行「停用后行为不再出现」在 t23 的 run 里失败 1/2**（样本 `off-024Z-d43a-1`：载荷 0 处规则文本，但回复里有一块按时间排列且恰 3 条、其中 2 项是真实待办的内容，被现行结构判据判成「三个重点任务」）。**我的 run 在同一指纹下该项通过（sampled 2）**，且三段的载荷定位全空 → 与 t23 的归因（结构判据的机会性假阳性）一致；文档已把行为侧权威交给学习门禁（我核对 `gate-l3-learning-report.json`：38/0/0，`l3.disabled_rule_stops_changing_behaviour` 0/2 有效、对照 2/2、`payload_leaks=0`）。这是**判据灵敏度**的已知边界，已列入下一轮收紧建议，不影响本轮收口结论。
2. **判据灵敏度的两个已知反例**：演示第 8 行（1/2）与 t23a 的 P5 `off` 开发格（1/3）——同一种假阳性；文档已记录并给出收紧方案（恰 3 条且 3 条都是真实待办、条目不带时钟前缀），并声明收紧会改变分母、不能与本轮数字混用。
3. **未纳入本轮**：长结果经 ref 取回（t10 的 HTTP 路由）未进入演示/P5；主动问候/每日回顾（P6）不在本轮；P5 的 dev 与 holdout 共用一个臂内运行目录（文档已声明，命中判定只针对该用例自己的清单——我在 t18 期的 n=1 探针里见过 dev 样本因优先排 holdout 任务而被判失败，说明该判据不会误判为命中）。
4. **表述核对**：全文检索未发现「代码看起来支持/机制已导入即可通过/普遍提升」一类表述；事实是文档明确区分「载荷结论（演示+门禁互相印证）」与「行为结论（以门禁为准）」，并把 t23 的失败数字与反例原文保留。

## 8. 复现命令

~~~powershell
cd MellowDay-Rebuild
python scripts/demo_core.py --attempts 2 --json-out docs\evidence\raw\core-demo-report-t25-rerun.json
python scripts/demo_core.py --selfcheck
python -m pytest tests/runtime/test_rule_fact_disabled_skill_claim.py tests/runtime/test_rule_fact_invariant.py tests/runtime/test_rule_fact_write_time_supersession.py tests/runtime/test_rule_fact_orphan_supersession.py tests/runtime/test_tool_status_filter.py -q
# 我自己的三个探针（系统临时目录，脚本不在仓库内）：N5 判据合成用例 / N6 工具状态词 / N4+N8 运行时取代
~~~
