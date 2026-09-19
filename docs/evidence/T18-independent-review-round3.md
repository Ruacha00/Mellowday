# T18 复核（第三轮）：t17 修复后的核心演示与 P5 是否成立

复核时间：2026-09-18（第三轮）　复核人：sessions-store（t18，独立于 t17/verifier）
结论：**needs_revision**。t17 的 N1/N2/N3 三项修复经独立验证成立；但我的独立重跑发现演示的**停用侧证据存在假阴性**（facts 通道泄漏未被判据覆盖），并顺带确认一个仍未闭合的产品缺陷（重复反馈窗口写下的规则事实未被取代）。

我的独立重跑：run `20260918T135245Z-08a5`，**19 passed / 1 failed / 2 inconclusive**（报告：`docs/evidence/raw/core-demo-report-t18-rerun.json`，22 项）。起始指纹 `a62e2089c7c0ed97`（含 t17 的脚本与 t19 已在树上的检索下限改动）。

## 1. t17 的 N1/N2/N3：独立验证成立

- **N2（可执行负向对照）**：我自己跑 `python scripts/demo_core.py --selfcheck` → **21 passed / 0 failed / 0 pending，退出码 0**，其中六条结构判据对照齐全：`accepts_a_conforming_reply`、`ignores_section_titles`、`accepts_three_priorities_plus_the_rest`、`rejects_a_long_list`、`rejects_four_priorities`、`rejects_a_reply_without_real_records`；另有 15 条来自 `gate_common.run_predicate_selfcheck` 的共享谓词对照。报告落在 `output/gate-runs/core-demo-selfcheck/20260918T135240Z-5f95/`。
- **N1（第 7 行 + 产品发现）**：文档第 7 行现在是「该次运行通过（单样本）」，同一行记录了 t14 的反例（run `…2e68`，`<retrieved_skills>` 带上规则、score 0.085）、根因（`min_score=0.08`）与派单（t19），并写明「不能当作无关请求永不加载的证明」。**我的这次 run 里该检查通过**（`rule_loaded=false`、`retrieved_block_mentions_rule=false`），与 t19 的 `RETRIEVAL_MIN_SCORE=0.15` + ≥2 多字词项改动一致——即这条修复在演示路径上有效。
- **N3（分母与波动）**：场景表新增「该行分母」列（第 1/2/4/5/6/7/9 行为 1 个样本；第 3 行 2/2；第 8 行恢复侧 2/2；第 9 行为 1 次折叠+1 轮续跑+1 次重启），限制段列出单样本行与 `demo.temporary_request_is_not_learned` 的四次运行翻转。

## 2. 独立验证仍然成立的部分

- **F1–F4 未回归**：我的 run 里 `restart-phase.json`（732 B）与 `restart-phase.log`（restored 6 messages, reply 79 chars）齐备，check 19 通过；check 16/17/18（折叠、续跑、折叠不产生技能）通过；`evaluate_structural_rule` 仍只断言结构。
- **工具参数 ↔ 数据库**：13 行记录；4 次写调用（2×`remember_fact` + 2×`create_todo`）各有唯一对应行；无重复 (kind,title)、无未匹配写入；38 次模型调用 0 错误（自写脚本只读 SQLite + `model-calls.jsonl`）。
- **事实进入载荷**：seq 1–3 的 payload 均含两条 active 事实正文；回复引用了习惯。
- **门禁方法与学习门禁**：`off_side_verdict` 的「死请求不算证据」规则仍在；学习门禁报告（t15，mtime 21:50）为 **37 passed / 0 failed / 1 inconclusive**，含 `l3.correction_supersedes_the_overlapping_fact`、`l3.disabled_rule_stops_changing_behaviour (sampled 2)`、`deterministic.disabled_rule_leaves_the_prompt` 与三段载荷探针——文档第 8 行「停用侧权威结论取自学习门禁」的说法有据。
- **P5 产物**（未重跑，仍是 t13 的 run `133334Z-7136 / 133510Z-caac / 133705Z-e37c`，指纹 `039361a98e2a0b84`）：三组 `config.json` 字节相同（`f06a5f4bea7ca7ce`）、种子一致、learned 的 holdout 在纠正之后创建、每格 valid=3，我重算的六格与文档逐格一致。

## 3. 发现（必须在下一轮修订）

### N4 [high，产品] 重复反馈窗口写下的规则事实没有被取代，停用技能后规则仍经 facts 通道进入请求

我的 run 的 SQLite（`output/gate-runs/core-demo/20260918T135245Z-08a5/data/mellowday.sqlite3`）：

~~~text
memories 规划方式 active→superseded   created 13:53:06  meta.superseded_by_skill=每日任务规划规则（13:53:19）
memories 规划规则 active              created 13:53:56  meta 无 superseded_*
~~~

`规划规则` 是在**重复反馈**那轮写下的（seq 11，属 `demo.repeated_feedback_keeps_the_edited_rule`），之后没有被任何技能取代。于是停用技能之后的 4 个 off 样本请求（seq 21–24）里，payload 的 `<system-reminder> Recalled facts` 块仍然带着规则：

~~~text
- 规划规则 [preference]: 帮用户规划某天时：先列出当天已有固定日程，然后只排三个重点任务，不要一次列十几条。
~~~

这正是 I24「停用习惯要真的改变行为」与 P5「off = 没有规则」的前提被打破的情形；t9/t16 覆盖了纠正窗口与被拒绝路径，**重复反馈窗口是第三个未覆盖的入口**。

### N5 [high，判据/证据] 演示停用侧的泄漏探针看不到 facts 通道，导致假阴性（check 12 在规则文本已在 payload 里时仍判通过）

- 我的 run 里 `demo.disabled_rule_leaves_prompt_and_skill_channel` **passed**，其 detail 为 `payload_probes=["每日任务规划规则", "1. 先查看并列出当天已有的固定"]`、`payload_probes_found=[]`、`payload_probe_present: false`（即 `payload_leaks=0`）。
- 但同一样本的 `channels.via_recalled_facts` 记录为 `["固定日程", "重点任务"]`——facts 通道命中了，却没有参与泄漏判定；而真正泄漏的 `规划规则` 正文（N4）根本不在探针集合里。
- 影响：文档第 8 行「停用侧 2 个请求 payload 未出现规则文本（payload_leaks=0）」在这类情况下是**假阴性**；`demo.unrelated_request_does_not_load_the_rule` 的 `rule_loaded` 同样只看技能通道（我的 run 该样本 facts 通道为空，所以这次结论恰好成立，但判据本身不覆盖 facts 通道）。
- 修法：泄漏判定纳入 facts 通道与「已失效旧值」段（学习门禁已有三段探针可复用），每样本记录探针位置；随后重跑并更新文档第 8 行与相关数字。

### N6 [medium，产品+文档] `list_calendar(status=...)` 的状态词陷阱：模型猜 `open` → 返回 0 条 → 对用户宣称「没有日程」

- 我的 run：`demo.planner_reads_real_records_and_current_facts` **失败**——`list_calendar {"status": "open"}` 返回 `count: 0`（日历记录的默认状态是 `scheduled`），回复因此写「没有日程和提醒」，漏掉真实的「09:30 每日站会」。
- 同一模式在 P5 探针 run（`output/gate-runs/p5-comparison-learned/20260918T135729Z-e4ce`）再次出现：holdout 样本 `list_calendar {"status": "open", "limit": 50}` → 0 条 → 回复「下周一目前日历里没有固定日程」（而 `客户复盘会` 确实存在，13:58:03 写入、status=scheduled）→ 结构断言的 `real_calendar_entry_present`/`calendar_entry_listed` 失败。
- 这是两次独立运行里的同一类**对用户数据的错误陈述**（工具静默接受不存在于该 kind 的状态词）。建议：`list_calendar` 接受/别名 `open` 等常见状态词，或在工具描述里明确日历状态词；文档场景表第 1 行（单样本行）应记录这条反例。

### N7 [low，文档] 数字与探针口径、以及 P5 表的时间边界

- 第 8 行的 `payload_leaks=0` 需要按 N5 修好后的探针定义重述（否则读者会以为它覆盖了全部通道）。
- P5 表仍是 t13 的 run（指纹 `039361a98e2a0b84`，早于 t19 的检索下限改动）。我做了一次 n=1 的探针（`docs/evidence/raw/p5-learned-probe-t18.json`，learned 单臂、每案例 1 样本）：**规则仍经技能通道投递**（`rule_loaded 1/1`、`via_skill_samples 1`、`via_facts_samples 0`），两个样本都因结构断言失败（dev 排了 holdout 的任务；holdout 漏了真实日程）。这既说明 t19 没有切断技能通道投递，也说明 n=1 不能替代一次正式重跑——P5 表需要在 t19 冻结后整体重跑一次再定稿。

## 4. 逐项场景（我的 run）

| 场景 | 我的 run | 备注 |
|---|---|---|
| 规划用日历/待办与事实 | **失败** | facts 与待办都对，日历因 N6 被判缺失 |
| 纠正→审查确认→新会话遵循 | 通过 | check 4/6/7 |
| 重复反馈合并 | 通过 | check 8（但该轮写下的 `规划规则` 事实未取代，见 N4） |
| 临时要求不学习 | 通过 | check 9：仅 `skill_candidate_skipped` |
| 覆盖习惯 | 通过 | check 10 |
| 无关请求不加载 | 通过 | check 11（t19 生效；但判据不含 facts 通道，见 N5） |
| 停用/恢复/回退 | 停用侧 inconclusive（设计） | check 12 通过但属假阴性（N5）；check 14/15 通过 |
| 折叠与重启续跑 | 通过 | check 16/17/19 + restart-phase.json/log |

## 5. 限制

- 我的 run 期间 `evals/p5_compare.py` 被改动，`code.workspace_unchanged_during_the_run` inconclusive（唯一 changed_file），结论对应起始指纹 `a62e2089c7c0ed97`。
- 我未修改 `scripts/**`、`evals/**`、`src/**`（不在 t18 写入范围）；本轮只在 `docs/evidence/` 下新增本文件、我的重跑报告与一次 P5 learned 单臂探针报告。

## 6. 复现

~~~powershell
cd MellowDay-Rebuild
python scripts/demo_core.py --attempts 2 --json-out docs\evidence\raw\core-demo-report-t18-rerun.json
python scripts/demo_core.py --selfcheck
python evals/p5_compare.py --samples 1 --only learned --json-out docs\evidence\raw\p5-learned-probe-t18.json
# N4 的证据：只读运行目录 SQLite 的 memories 行 + 该 run 的 model-calls.jsonl 里 off 样本请求的 Recalled facts 段
~~~
