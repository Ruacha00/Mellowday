# 核心演示：P3/P4 用户流程端到端（真实模型 + 真实进程）

> **t23（收尾运行：冻结代码 + 修好的探针口径，本文件的权威运行）**：run `20260918T152024Z-d43a`，指纹 **`0c0c0d7f636fde67`**（105 个源文件），
> 工作区在运行期间 **0 变化**（`code.workspace_unchanged_during_the_run` 通过，起止指纹相同），
> 结果 **23 通过 / 1 失败 / 0 无法判定（24 项）**。同一指纹下的另两项收尾证据：P5 三臂均 `9/9` 检查通过、
> 六格为 off 0/3 与 0/3、fixed 2/3 与 3/3、learned 3/3 与 3/3（事实通道 0/3）；学习门禁 **38 通过 / 0 失败 / 0 无法判定**。
> 唯一失败是第 8 行「停用后行为不再出现」：2 个停用侧样本里 1 个仍产出规则形状的回复，
> 但该样本的请求载荷里 **0 处规则文本**（三段式定位全空、无 skill 调用、系统提示不含该技能）——
> 判为**结构判据的机会性假阳性**（同一判据在 t23a 的 P5 `off` 臂上也曾给出 1/3 命中），
> 失败数字与反例原文保留在第 8 行与第 9 节：**不放宽判据、不删反例**。
> **t25 的独立重跑**（sessions-store 自跑，run `20260918T153652Z-e83e`，**同一指纹** `0c0c0d7f636fde67`，
> `gate_file_hashes` 与本轮逐项一致，24 通过 / 0 失败）**没有复现**这条假阳性（该子项 2/2 通过）：
> 两次同指纹运行给出 1/2 与 2/2，与「结构判据机会性假阳性」的归因一致。本文件仍以 t23 那次为权威运行（含红色项），
> t25 重跑作为补充数据点，报告留档 `docs/evidence/raw/core-demo-report-t25-rerun.json`。
>
> **t20（N4/N5/N6 修复之前的最后一次完整运行，保留为修复前数据点）**：run `20260918T135711Z-92f6`，指纹 `c1b5db51612630d3`，
> 工作区 0 变化，39 次请求，结果 **20 通过 / 1 失败 / 1 无法判定**：第 1 行失败＝N6（`list_calendar(status='open')` 静默返回 0）、
> 第 8 行无法判定＝N4（规则经重复反馈轮进事实库）＋N5（停用侧探针只覆盖技能通道）。见第 8 节。
>
> **t13（含 t16 的代码）**：run `20260918T132917Z-97b4`，指纹 `039361a98e2a0b84`，21 通过 / 0 失败 / 1 无法判定；
> 折叠 + 重启段**真的注册并执行**了（见第 1 节第 9 行与第 6 节）。
> 下文表格保留 t5（run `…6493`）、t13、t20 的数字作对照，凡冲突处以 t23 为准。

日期：2026-09-18（第三轮）
脚本：`scripts/demo_core.py`（+ `scripts/demo_support.py`，两者共用 `scripts/gate_common.py` 的隔离与录制机制）
命令：`python scripts/demo_core.py --attempts 2`
当前运行（t23）：`20260918T152024Z-d43a`　15:20:24Z → 15:24:05Z　模型 `deepseek-v4-pro`（`https://api.deepseek.com`，`stream=true`，`thinking=false`）
工作区指纹：`0c0c0d7f636fde67`（105 个源文件；运行期间 0 变化。同一指纹下的 P5 三臂与学习门禁见第 9 节）
结果：23 通过 / 1 失败 / 0 无法判定（0 待验）
报告：`docs/evidence/raw/core-demo-report.json`；原始请求/响应：`output/gate-runs/core-demo/20260918T152024Z-d43a/artifacts/model-calls.jsonl`；隔离数据目录：同 run 目录下的 `data/`
历史对照（t5，数字仍保留在本文第 2、3 节）：`20260918T122948Z-6493`，起始指纹 `26bd0d56ab3041e1`（运行期间 4 个源文件被其它单元改动，当时判 inconclusive），18 通过 / 1 失败 / 2 无法判定，46 次模型请求 0 错误

**这份证据的定位**：本演示说明「用户能走完整条流程」，并把它抓到的问题原样留在报告里。
停用侧的**载荷**结论（规则文本是否还进得了请求）由本演示与学习门禁各给一份、互相印证；
停用侧的**行为**结论以学习门禁为准（它的 off 侧有同轮对照与更明确的判据，见第 9 节），
本演示第 8 行的行为子项在 t23 **失败**且不修饰（原因见第 8、9 节）。

---

## 1. 演示覆盖的场景与证据

| # | 场景（任务要求） | 结论（t23 运行 `…d43a`；括号内为历史） | 该行分母 | 关键证据与已观测波动 |
|---|---|---|---|---|
| 1 | 已有日历与待办 + 当前用户事实规划明天 | **t23 通过**（t20 曾失败＝N6） | **1 个样本**（1 轮对话） | t23：回复含 09:30 每日站会（`calendar_event_in_reply=true`）、6/6 条真实待办、2 条事实中 1 条被反映（`metrics={todos_in_reply:6, todos_of:6, facts_reflected:1, facts_of:2}`，两个分母在 t23 各自命名）；两条事实正文都出现在出站 payload；trace 里 `list_todos` / `list_calendar` / `list_reminders` 各 1 次，日历查询用的是 `status="scheduled"`。**N6 修法**（t22，`src/mellowday/personal_assistant/tools.py`）：通用词 `open/pending/active/…` 映射为「未完成」并在 `status_filter.applied="not-done"` 回显，未知状态词返回结构化错误并列出合法取值，**不再静默返回空集**；实测学习臂 5/6 个样本用 `status="open"` 查日历、`count=2`（含 每日站会），确定性回归 `tests/runtime/test_tool_status_filter.py` 16 passed。**修复前反例保留**（t20 run `20260918T135711Z-92f6`、T18 run `20260918T135245Z-08a5`：`status="open"` → 0 条 → 回复完全没提站会）。单样本行，不作稳定性声明 |
| 2 | 用户明确纠正规划方式并审查确认规则变更 | 通过 | **1 轮纠正 + 6 次 HTTP 调用** | 纠正轮：候选事件 + 1 个确认 token + `skill_candidate_applied`，落盘 `日常规划输出规则` v0.1.0（运行目录内）；随后经真实 uvicorn 进程：`GET /api/skills` 列出、`GET /api/skills/{name}` 读到正文、`PUT` 人工补一句「建议执行顺序」→ `changed=true` 版本 0.1.0→0.1.1、旧正文仍可取（`GET /versions/0.1.0`），新正文进入下一轮提示词 |
| 3 | 全新会话按新规则规划 | t23 **通过**（结构断言） | **1 个样本**（t13 抽样 2/2） | **结构断言 5/5 通过**（不依赖小节标题）：真实日程 每日站会 出现且自成一块、≥3 条真实待办被采用、存在「顶层恰 3 条且其中 ≥2 条是真实待办」的重点块、任一块条目 ≤10；阈值与分母写在报告 `evidence.thresholds`（`priority_items=3`、`priority_items_min_real_todos=2`、`min_real_todos=3`、`max_items_per_block=10`）。**规则投递（t23 修好口径后的四通道）**：`<retrieved_skills>` 块命中 1/1、请求载荷正文探针命中 1/1、**skill 工具结果命中 1/1**、skill 调用 1 次；正文探针 `"1. 先列出当天已有的固定日程。"`（运行时取自当次正文的指令区）。判据自带可执行负向对照（第 7 节） |
| 4 | 重复反馈合并 | 通过 | **1 次重复反馈** | 同一纠正再说一次：事件为 `skill_candidate_skipped`（no durable change，不升版不写文件），技能数不变，人工补的那句仍在正文里 |
| 5 | 临时要求不学习 | t23 **通过**（**单样本**，见右侧波动） | **1 个样本** | t23：一次性要求那轮没有写入（无 `skill_candidate_applied`、版本没变：`versions_unchanged=true`、`one_off_rule_lines=0`）。**已观测波动（不删）**：该检查在多次运行里翻转过——t5（run `…6493`）失败：`skill_candidate_proposed(mode=merge)` + `skill_candidate_applied`、版本 0.1.0→0.1.1（见 2.1）；t6 复核的另一次同样失败；t13 的两次运行（`…0ab6`、`…97b4`）通过；t23 通过。原因：该判据是「学习窗口 + 模型选择」的联合结果，单样本不足以当稳定结论；t12 的确定性门槛有自己的离线负向对照，那才是该结论的依据 |
| 6 | 当前要求覆盖习惯 | 通过 | **1 个样本** | 明确要求「列出所有待办」后，回复列出 6/6 条待办（不受「只排三个」限制）；单样本 |
| 7 | 无关请求不加载规划规则 | **t23 通过（不再加载，抽样 2/2）**；与 t20 的 2/2 一致 | **抽样 2/2**（每样本扫 2–3 次出站请求） | t23：两条无关请求（`帮我记一条待办：明天上午十点去取快递。`、`今天天气怎么样？`）的 payload **都没有 `<retrieved_skills>` 块（0/2）、没有 skill 工具调用（0/2）、没有规则正文探针（0/2）**；同时真实新建 1 条待办（`rows_created=1`）。**同轮正对照**（t23 新增检查 `demo.planning_request_in_this_run_can_load_the_rule`，4 条通道全 1）：同一运行的规划请求经 `<retrieved_skills>` 块、请求载荷正文探针、**skill 工具结果**与 skill 调用四条通道都拿到了规则 → 「无关请求不加载」可归因于相关性，而不是检索整体失效；若该对照为 0，第 7 行会判 **inconclusive**（判据这么写）。**探针口径（N5 之后必须随数字一起读）**：技能**名字**仍然出现在无关请求的 payload 里——那是系统提示里的技能索引（检索目录，按设计存在），判据因此不看名字，只看块 / 工具调用 / 正文；t23 的正文探针来自**当次正文的指令区**（`pick_body_probe`，已排除 front matter 与标题行）。**修复前反例保留，不删**：t14 复核的运行（run `20260918T134139Z-2e68`，指纹 `039361a98e2a0b84`）该检查失败——`<retrieved_skills>` 带上了「每日规划输出规则 (score=0.085)」，根因 `runtime/skills/skills.py` 的 `min_score=0.08`，**t19 已修**（下限 0.15 + ≥2 个多字词项）；t20（`20260918T135711Z-92f6`）与 t23 各 2/2。稳定性：三个不同指纹下各 2/2，仍属小样本（每轮 n=2） |
| 8 | 规则停用/恢复/版本回退 | **停用侧载荷通过、停用侧行为失败（1/2，见下）；恢复侧 2/2；版本回退通过** | 停用侧 **2 个样本 / 4 次出站请求**；恢复侧 **2/2**；回退 **1 次** | **停用载荷（通过）**：技能名从系统提示消失（`prompt_lacks_rule=true`）、无 skill 工具调用（0/2）、无 `<retrieved_skills>` 块（0/2），三段式定位（召回事实段 / 已失效旧值段 / 其余请求文本）在 4 次请求里**全空**（`present_anywhere: []`、`via_recalled_facts: 0`、`via_superseded_values: 0`）；探针集 = 技能名 + **正文指令行**（`1. 先列出当天已有的固定日程。`）+ `固定日程`/`重点任务` 两个事实通道词。**停用行为（t23 失败，原样保留）**：`demo.disabled_rule_stops_changing_behaviour` 判 1/2——样本 `off-024Z-d43a-1` 在**载荷里 0 处规则文本**的情况下仍产出「每块恰 3 条」的结构形状（`a_block_presents_exactly_3_priority_tasks=true`），被判成「习惯还在」。这是**结构判据的机会性假阳性**：那一块是按时间的三段排期（09:30 站会 / 09:45 取快递 / 10:00–12:00 写季度报告），其中 2 项是真实待办就满足了「≥2 条真实待办」的松阈值；同一判据在 t23a 的 P5 `off` 臂上也曾给出 1/3 命中（t23d 的 `off` 臂为 0/3）。**同一指纹**的学习门禁给出停用侧行为 0/2（对照侧 2/2）与载荷 0/2，故「停用后行为不再出现」的权威结论以门禁为准；本演示只如实保留这条反例。**恢复（通过）**：提示词恢复 + 抽样 2/2 满足结构断言（阈值 ≥1）；**版本回退（通过）**：版本列表 2 条，恢复 0.1.0 正文成功且人工补句消失。**N4 已修**（t21/t24，同一指纹下验证）：门禁的 deny→learn 序列里，被拒绝确认那一轮写下的孤儿事实 `规划时的习惯` 被学到的技能认领（`orphans_that_needed_claiming=1`、`claimed=1`、`active_rule_facts=0`），P5 六格的 `via_facts_samples` 全为 0/3。**N5 已修**（t23）：判据改为**复用**门禁的三段式分类器（不再有第二套实现），并新增自检 `selfcheck.leak_judgement_reports_a_rule_only_in_the_facts_segment`（只放在事实段里的规则文本必须报为泄漏）。数字归属：t5 恢复侧 1/2（T6 F4），t13/t20 恢复侧 2/2 |
| 9 | 长对话折叠与重启后继续未完成任务 | 通过 | **1 次折叠（7→2 条消息）+ 1 轮续跑 + 1 次真实重启（子进程退出码 0）** | 折叠：运行 7→2 条消息、写入 1 条折叠记忆且含任务主题「写季度报告大纲」；折叠后同一会话继续推进（结构断言与回复 367 字符）且未重复建待办（1 行）；一次性编辑要求**没有**产生新技能（`new_skills=0`、`quoting_a_one_off=0`）；**真实重启**：`--phase continue` 子进程恢复 6 条消息、任务标题在恢复态里、回复仍点名「写季度报告大纲」（77 字符），`restart-phase.json/.log` 齐备。t13 的旧数字（8→2、恢复 6 条）见历史运行 |

工具与数据库一致性（每次都由真实工具调用 + SQLite 行核对，不靠文案）。t23 结束时的隔离数据目录：
**待办 8 行**（业务种子 6 + 无关请求新建 1「取快递」+ 折叠场景 1「写季度报告大纲」）、**日历 1 行**（每日站会 09:30，状态 `scheduled`）、
**提醒/笔记 0 行**、**记忆 4 行**（`工作节奏`/`下班时间` 为 `active`；`规划输出规则`/`规划方式偏好` 为 `superseded` —— 重叠副本被标记取代而不是删除，与门禁的取代断言互相印证），
演示期间无重复行。

## 2. 失败案例（原样记录，不修饰；本节是 t5 那次的记录，t20/t23 的失败在第 8、9 节）

### 2.1 「临时要求不学习」被违反（检查失败）

- 检查：`demo.temporary_request_is_not_learned`
- 用户这一次说的话：`这次先只要一句话概括明天的重点，也不用记住这条要求。`（明确说了「不用记住」）
- 实际发生：该轮学习窗口产出了**持久写入**——

~~~json
[{"type": "skill_candidate_proposed", "skill": "日常规划输出规则", "action": "merge",
  "summary": "候选习惯「日程规划输出规则」会合并进已有习惯「日常规划输出规则」：0.1.1 → 0.1.2，只影响之后的新会话。\n变更概要：新增 1 条规则、保留 5 条旧规则 …"},
 {"type": "skill_candidate_applied", "skill": "日常规划输出规则", "action": "merge"}]
~~~

- 版本历史（`data/skill_evolution/history/日常规划输出规则.jsonl`）：0.1.0（人工编辑）→ **0.1.1**（`12:31:49Z`，理由 `existing skill already covers this capability`）→ 0.1.2（回退前的快照）。
- 后果：用户在一次性请求里表达的内容被写进持久规则（候选正文里出现「若用户临时要求一句话概括或列出全部待办，按当次要求执行，但不改变上述默认规则」这样的常驻条款）。这属于 I11「一次性要求不落为永久规则」的反例。
- 备注：同一轮之后再发出「列出所有待办」的**明确覆盖**请求时，学习侧正确判为 `skill_candidate_skipped / reason=no_durable_value`（通过）；也就是说缺陷出在「一次性请求的那一轮」，而不是覆盖请求那一轮。

### 2.2 折叠场景里的一次性指令也落了盘（本次未设检查，仅记录）

折叠场景第二轮我说的是：`第二条再展开一点，加上要对比的两个数据口径。`（一次性编辑要求）。运行结束后运行目录里多出一个技能：

~~~text
data/skills/季度报告大纲-核心成果需含数据对比口径/SKILL.md   version 0.1.0
creation evidence: 用户反馈：第二条再展开一点，加上要对比的两个数据口径。
~~~

这是同一类缺陷的第二个独立实例（一次性任务指令变成永久技能）。本轮的演示脚本没有对这一条设检查，因此它没有出现在检查列表里，只作为**运行产物发现**记录在此；T5 重跑（t11）会补上对应断言，避免它继续只靠人工翻目录才发现。

## 3. 作废的结论：停用规则（事实通道污染，pre-t9 现象；t23 的现状见第 9 节）

- 检查：`demo.disabled_rule_stops_changing_behaviour` → **inconclusive / BLOCKED**，不给通过结论。
- 本轮实测：停用后 2 个请求 payload_leaks=0、活动规则事实 0 条（即本轮模型没有把规则写成事实，或写了但已被 t9 取代——见第 4 节）。
- 为什么仍然作废：该条件的结果**运行间不稳定**。同一条流程在更早的运行里确实把规则写成了用户事实，而事实由运行时注入**每一个**会话，于是停用技能后规则仍在载荷里：

| 运行 | 事实标签 | 停用侧事实通道 |
|---|---|---|
| `l3-learning 20260918T115840Z-f535` | 规划偏好 | 2/2 |
| `l3-learning 20260918T120611Z-7a79` | 规划方式 | 2/2 |
| `l3-learning 20260918T121315Z-f8f1`（t1–t3 之后） | 规划方式 | 2/2 |
| `core-demo 20260918T121554Z-31d1` | 规划方式 | 事实行已写入并被注入 |

- 裁决与去向：主控已按 CONTRACTS.md 6quater.1 裁决（规则归属技能库；同一纠正窗口内与该规则实质重叠的事实标记为「已被该技能取代」、保留可查、不再进入任何注入通道），由 t9 实施。停用侧行为结论改由 t11 在去重逻辑落地后给出。

## 4. 本次运行中的 t9 观察（补充记录，不作为门禁结论）

本次运行前 t9 已落地，运行目录的 SQLite 里可以看到去重真的执行了：

~~~json
{"title": "规划方式偏好",
 "detail": "帮用户规划一天时：先列出当天已有的固定日程，然后只排三个重点任务，不要一次列很多条。",
 "status": "superseded",
 "meta": {"memory_kind": "preference",
          "superseded_at": "2026-09-18T12:30:21.561516+00:00",
          "superseded_by_skill": "日常规划输出规则",
          "superseded_reason": "superseded by skill"}}
~~~

即：纠正轮同时写入事实与技能后，事实被标记 `superseded` 并带上 `superseded_by_skill`，因此 `include_done=False` 的活动事实集合里没有它，停用侧载荷里也没有它（payload_leaks=0）。**这只是单次运行的观察**；「取代在真实序列下确实触发、且折叠/重启后仍不回注」需要门禁级断言（`status=superseded` 记录存在 + 载荷探针覆盖「已失效旧值」段落），由 t11 执行。

## 5. 限制与复现

- **结构判据的区分力（t23 新增，已知）**：`evaluate_structural_rule` 的「重点块」判据是「某块顶层恰 3 条、其中 ≥2 条是真实待办」，因此一份**按时间排期的三段计划**也会被判成「三个重点任务」。t23 第 8 行的停用侧行为失败（1/2）就是这个形状：载荷里 0 处规则文本，回复里却有一块恰 3 条的时间段。建议下一轮把该判据收紧为「恰 3 条**且 3 条都是真实待办**、条目文本不带时钟前缀（`^\d{1,2}[:：]\d{2}`）」，并因此重测 P5 六格——收紧会同时改变已记录的分母，属于判据变更而非修 bug。
- **探针口径必须跟数字一起读（t23 修正）**：① 正文探针取自**指令区**（`pick_body_probe` 跳过 front matter、标题与元数据行；指令行过短时回退到 6 字探针，不会静默变成空串）；② 判「规则是否被加载」必须同时看**请求载荷**与 **skill 工具结果**——运行时刻意把规则正文放在工具结果里交给模型，只看请求载荷会把「已投递」误报成「未投递」；③ 技能**名字**出现在系统提示的技能索引里，这是检索目录，按设计存在，所以判据不看名字，只看 `<retrieved_skills>` 块、skill 工具调用与正文探针。
- **历史指纹变动（t5／t11 时期的记录）**：t5 那次运行期间有 4 个源文件被其它单元改动（含 `evals/p5_compare.py`、`src/mellowday/web_app/app.py`、两个测试文件），当时的 `code.workspace_unchanged_during_the_run` 判 inconclusive；那条记录描述的是起始指纹 `26bd0d56ab3041e1` 的代码。
- **抽样规模**：命中类结论抽样 2 次（分母已写在每个检查的 `metrics` 里），只用于确认方向，不作为效果量；第 8 行停用侧 2 个样本、恢复侧 2 个样本。
- **单样本行（第 1、2、4、5、6、9 行）**：这些场景各只跑了 1 个样本，结论只能说明「该次运行如此」。尤其第 5 行：`demo.temporary_request_is_not_learned` 在多次运行里**翻转过**（t5 `…6493` 失败、t6 复核的一次失败、t13 `…0ab6`/`…97b4` 通过、t23 `…d43a` 通过）——单次通过不能写成「一次性要求永不进入学习」；t12 的确定性门槛有自己的离线负向对照（K1–K4 变异），那才是该结论的依据。第 7 行同理：见该行的修复前反例。
- **本文件描述的是哪一次运行**：**t23 的 run `20260918T152024Z-d43a`**（指纹 `0c0c0d7f636fde67`，105 个源文件，工作区在运行期间 0 变化）。t20（`20260918T135711Z-92f6`）、t13（`20260918T132917Z-97b4`）与 t5（`20260918T122948Z-6493`）的数字作为历史对照保留在本文第 2、3、8 节。
- **真实进程边界**：规则审查/编辑/版本/回退走真实 uvicorn 子进程（HTTP）；对话走运行时同一路径 `SessionRegistry.run_turn`（与网页层等价），HTTP/SSE 的端到端由 `tests/web_app/smoke_real_process.py` 覆盖。HTTPS 长结果引用取回（t10）当时未纳入。
- **不影响日常数据**：真实数据目录只做只读元数据快照，`demo.real_data_directory_untouched` 通过（0 变化）；凭据只写入 `output/` 下运行目录的 `config.json`，报告与日志 0 命中。

~~~powershell
cd MellowDay-Rebuild

# 完整演示（需要凭据；运行目录自动隔离，报告不落密钥）
python scripts/demo_core.py --attempts 2

# 只看确定性部分（不调用模型，退出码 2 = L3 未运行）
python scripts/demo_core.py --offline

# 复核
#   报告：docs/evidence/raw/core-demo-report.json
#   原始请求/响应：output/gate-runs/core-demo/<run-id>/artifacts/model-calls.jsonl
#   隔离数据（数据库/会话/Skills/版本历史/配置）：output/gate-runs/core-demo/<run-id>/data/
#   重启续跑子进程日志：output/gate-runs/core-demo/<run-id>/artifacts/restart-phase.log

# 判据的可执行负向对照（不需要模型，退出码 0 = 每个对照都符合预期）
python scripts/demo_core.py --selfcheck
~~~

## 7. 判据的可执行负向对照（T14 复核 N2）

`evaluate_structural_rule()` 同时决定演示的命中判定与 P5 六格的分母，是一个**测量工具**；测量工具必须自带可执行负向对照，否则「判据对不对」只是不可检验的假设。

~~~powershell
python scripts/demo_core.py --selfcheck            # 判据负向对照（无需模型）
python scripts/demo_core.py --selfcheck --json-out <path>   # 同时留档报告
~~~

t23 运行结果：**24 通过 / 0 失败**（退出码 0，run `20260918T152023Z-b5d2`，指纹 `0c0c0d7f636fde67`；留档 `docs/evidence/raw/core-demo-selfcheck-report.json`，同副本 `output/t23d-selfcheck.json`），
包含六条结构判据对照、**三条 t23 新增的口径对照**与十五条共享谓词对照：

| 对照 | 输入 | 期望 |
|---|---|---|
| `selfcheck.structural_judgement_accepts_a_conforming_reply` | 合规回复（字面标题） | 判为满足 |
| `selfcheck.structural_judgement_ignores_section_titles` | 合规回复（换用其它标题） | 判为满足（T6 F2 的回归点） |
| `selfcheck.structural_judgement_accepts_three_priorities_plus_the_rest` | 「3 条重点 + 6 条其余待办」 | 判为满足（曾被我第一版判据误判） |
| `selfcheck.structural_judgement_rejects_a_long_list` | 单块 8 条待办 | 判为不满足 |
| `selfcheck.structural_judgement_rejects_four_priorities` | 4 条重点任务 | 判为不满足 |
| `selfcheck.structural_judgement_rejects_a_reply_without_real_records` | 没有任何真实记录 | 判为不满足 |
| `selfcheck.leak_judgement_reports_a_rule_only_in_the_facts_segment`（t23 新增） | 规则文本**只**出现在注入的「召回事实」段（t20 现场的形状） | 必须报为泄漏；旧探针在这里报 0 |
| `selfcheck.body_probe_comes_from_the_instructions_not_the_front_matter`（t23 新增） | SKILL.md 的 front matter 描述行比所有指令行都长；另有一个指令行都很短的正文 | 探针取自指令区（front matter 会被运行时刻意剥掉）；短正文回退到短探针，不得静默变成空探针 |
| `selfcheck.delivery_is_seen_even_when_only_the_tool_result_carries_the_rule`（t23 新增） | 规则正文只出现在 skill 工具的结果里 | 投递判据必须认得这条通道（否则把「已投递」误报成「未投递」） |
| `selfcheck.*`（15 条，来自 `gate_common.run_predicate_selfcheck`） | 上一代门禁曾判通过的输入（空回复、400 错误、配置只改文件、丢失前一轮…） | 全部拒绝或按要求处理 |

这六条对照同时说明「三个合成用例」不是一次性人工验证：它们是仓库内可重复执行的断言，任何人可用一条命令复现。

## 8. t20（**修复前**数据点，早于 N4/N5/N6 的修复）：结论、失败与归因

运行：`20260918T135711Z-92f6`　13:57:11Z → 14:01:04Z　指纹 `c1b5db51612630d3`（运行期间 0 变化）　39 次请求
结果：**20 通过 / 1 失败 / 1 无法判定**。这是**修复前数据点**（早于 N4/N5/N6 的修复），失败与无法判定均如实保留、不跳过也不放宽。

| 项 | 结果 | 归因（产品/判据） | 证据 |
|---|---|---|---|
| 第 1 行 规划读取真实记录 | **失败** | **N6**（产品，已派单 t22） | `list_calendar {"status": "open"}` → 0 条（事件状态是 `scheduled`）→ 回复缺 09:30 每日站会；T18 另一次运行同样复现 |
| 第 7 行 无关请求不加载规则 | **通过（2/2）** | t19 修复已生效 | 两条无关请求 payload 均无 `<retrieved_skills>`、无 skill 调用、无正文探针；对照（follow 样本）有该技能 |
| 第 8 行 停用侧 | **无法判定（BLOCKED）** | **N4**（产品，已派单 t21）+ **N5**（判据，已并入 t23） | 两个停用侧样本 `via_recalled_facts=['固定日程','重点任务']`（N4）；技能通道 `payload_leaks=0` 未覆盖事实段（N5 假阴性现场复现） |
| 折叠 + 重启 | **通过** | — | 8→2 条消息、`restart-phase.json/.log` 齐备、子进程退出码 0、四项折叠/重启检查全绿 |

P5（同批运行，见 `P5-minimal-comparison.md` 的 t20 附注）与 I10 基线：

- P5 三组已按 t20 要求改为**每臂独立进程**（`arms_isolated_in_separate_processes=true`，三条子进程日志与 arm JSON 留档）；
  但三臂的起始指纹分别是 `c1b5db51612630d3` / `eb9c80b9c1d64ebd` / `053257977297ac73`——
  **运行期间有代码变更**（`src/mellowday/runtime/agent.py` 与三个新测试文件，属 t21 的在飞改动），
  因此三臂的 `code.workspace_unchanged_during_the_run` 均判 inconclusive，**跨臂对照被代码变动干扰**，本轮 P5 只作修复前数据点。
- I10 检索基线：`python -m pytest tests/runtime/test_skills_retrieval_zh.py tests/runtime/test_retrieval_no_leak.py -q` → **33 passed**，未回退。
- 已知报告字段缺口（不影响上述结论）：第 7 行 detail 的 `positive_control_from_the_same_run` 在本轮为空——写这一段时我按 `follow_turn.samples` 取值，而该步实际记录的是单个样本 dict（`follow_turn.delivery`）。对照证据在报告里仍然可见：第 3 行的 follow 检查显示 `retrieved_block_mentions_rule=true`、规则正文投递 1/1。取值已改为兼容两种形状（`_as_sample_list`），随 t23 的重跑生效。

## 9. t23 收尾运行（修复后，同一指纹上的三项证据）：三个问题的回答

### 9.1 运行清单（同一个指纹）

| 证据 | run id | 指纹 | 结果 |
|---|---|---|---|
| 核心演示 | `20260918T152024Z-d43a` | `0c0c0d7f636fde67` | **23 通过 / 1 失败 / 0 无法判定（24 项）** |
| P5 `off` / `fixed` / `learned` | `20260918T152406Z-90e9` / `20260918T152559Z-2dfb` / `20260918T152801Z-a226` | 三臂同 `0c0c0d7f636fde67` | 每臂 **9/9** 检查通过（含隔离、规则状态、载荷断言、workspace、凭据） |
| 学习门禁 `gate_l3_learning.py --attempts 2 --selfcheck` | `20260918T153014Z-0a6c` | `0c0c0d7f636fde67` | **38 通过 / 0 失败 / 0 无法判定（38 项）** |
| 判据自检 `demo_core.py --selfcheck`（不调用模型） | `20260918T152023Z-b5d2` | `0c0c0d7f636fde67` | **24 通过 / 0 失败**（`docs/evidence/raw/core-demo-selfcheck-report.json`） |
| 独立复核重跑（t25，sessions-store 自跑） | `20260918T153652Z-e83e` | `0c0c0d7f636fde67` | **24 通过 / 0 失败**；第 8 行行为子项 **2/2 通过**（假阳性未复现）。`gate_file_hashes` 与本轮逐项一致 → 确为同一版代码；报告 `docs/evidence/raw/core-demo-report-t25-rerun.json` |

四次运行/自检的指纹相同（105 个源文件）；每份报告都带 `code.workspace_unchanged_during_the_run`（起止相同、0 个文件变化），
凭据扫描 0 命中，真实数据目录只做只读快照（`demo.real_data_directory_untouched`：78 个文件、0 变化）。

稳定性的另一条数据点：同一天还有一次**同一代码路径**的完整运行（t23a，run `20260918T150344Z-4dd7`，指纹 `553590fa8fa3cca7`，
早于 t23 的两处口径修正——正文探针的 front matter 与指标键重名）：演示 23 通过 / 0 失败（23 项）、
P5 off 1/3 与 0/3、fixed 3/3 与 3/3、learned 2/3 与 3/3、门禁 38/0/0。
两次对比说明：**六格里 `off` 组会因结构判据的机会性命中而波动**（1/3 与 0/3），而 fixed/learned 的差异在 n=3 的抽样噪声内。

上表最后一行是**第三方独立重跑**（t25 复核者自己启动、自己留档）：同一指纹下第 8 行行为子项 2/2 —— 这条假阳性在两次运行间来回，
所以第 8 行行为结论的正确读法是「同指纹门禁的 0/2 对 对照 2/2，加上演示两次的 1/2 与 2/2」，而不是任何单次运行的单项数字。

### 9.2 被点名的三个问题，逐条回答

**N4（技能停用时，三个载荷段是否都干净？）—— 是，两份证据、0 命中。**
演示：停用侧 2 个样本 / 4 次出站请求，探针集 = 技能名 + 正文指令行 + `固定日程`/`重点任务`，
三段式定位（召回事实段 / 已失效旧值段 / 其余请求文本）**全空**（`present_anywhere: []`、`via_recalled_facts: 0`、`via_superseded_values: 0`），
无 `<retrieved_skills>` 块、无 skill 调用、系统提示不含该技能。门禁：停用侧 2 个样本 / 4 次请求同样 0/2（`l3.disable_side_payload_carries_no_rule_text`）。
**取代也确实发生了**：门禁的 deny→learn 序列里，被拒绝的确认那一轮写下的孤儿事实 `规划时的习惯` 被学到的技能认领
（`orphans_that_needed_claiming=1`、`orphans_claimed_by_the_learned_skill=1`、`superseded_by_skill=日程规划输出规则`、
`active_rule_facts=0`）；P5 六格的 `via_facts_samples` 全为 **0/3**（18 个样本）。
修复前反例（保留）：t20 的两个停用侧样本 `via_recalled_facts=['固定日程','重点任务']`。

**N5（停用侧探针的假阴性是否修好？）—— 是，而且这轮又抓到并修好了同一类缺陷的三个新形状。**
`scripts/demo_core.py` 现在直接**复用** `gate_common.payload_probe_locations`（三段式分类器，只有一份实现），
并新增自检对照 `selfcheck.leak_judgement_reports_a_rule_only_in_the_facts_segment`：把规则句子**只**放进召回事实段，
旧探针在这里报 0、新判据必须报泄漏（当前 24/0）。另外三个同形状缺陷见 9.3（N5-a…d）。

**N6（`list_calendar(status='open')` 还会让模型说「没有日程」吗？）—— 不会再由这个缺陷导致。**
t22 在 `src/mellowday/personal_assistant/tools.py` 里把通用状态词（`open/pending/active/进行中/未完成…`）映射为「未完成」，
并在结果里回显 `status_filter: {requested: "open", applied: "not-done"}`；未知状态词返回**结构化错误并列出合法取值**，不再静默返回空集。
实测（同一指纹）：学习臂 6 个样本里有 **5 个**用 `status="open"`（其中 1 个还带 `limit`）查日历，返回 `count=2`（含 09:30 每日站会）；
演示第 1 行回复含 09:30 每日站会（`calendar_event_in_reply=true`）。确定性回归 `tests/runtime/test_tool_status_filter.py`：**16 passed**（我独立跑过）。
修复前反例保留：t20 `status="open"` → count 0 → 回复缺站会；T18 的 run `20260918T135245Z-08a5` 同样复现。

### 9.3 t23 自己发现并修好的口径缺陷（承接 N5 的「判据别撒谎」与 N7 的文档口径）

| 编号 | 形状 | 修复 | 可执行对照 |
|---|---|---|---|
| N5-a | 停用侧探针只找技能名与写死的正文片段，规则经**事实段**到达时报「无泄漏」（t20 现场） | 判据改为复用门禁的三段式分类器；探针集含正文指令行与事实通道词 | `selfcheck.leak_judgement_reports_a_rule_only_in_the_facts_segment` |
| N5-b | 正文探针取自 SKILL.md 的 **front matter**，而运行时**刻意剥掉** front matter 再交给模型 → 「已投递」被报成「未投递」（本次实测：`body_probe_in_payload=false` 而正文确实在工具结果里） | `pick_body_probe` 跳过 front matter、标题行与元数据行；指令行过短时回退到 6 字探针，不静默变空 | `selfcheck.body_probe_comes_from_the_instructions_not_the_front_matter` |
| N5-c | 投递判据只看**请求载荷**，不看 **skill 工具结果**（本运行里规则正文正是从工具结果进的模型） | `rule_delivery` 增加 `skill_tool_call_present` / `body_probe_in_tool_results` 两个通道字段 | `selfcheck.delivery_is_seen_even_when_only_the_tool_result_carries_the_rule` |
| N5-d | 第 7 行的「同轮正对照」只是一段 detail：旧实现取错了字段，本轮早期显示 `false/false` 却仍判通过——「无关请求不加载」就失去了对照 | 新增独立检查 `demo.planning_request_in_this_run_can_load_the_rule`（四条通道任一为真才算对照成立）；对照为假时第 7 行判 **inconclusive** | t23d：对照四条通道全 1（块 / 载荷正文 / 工具结果 / skill 调用）；第 7 行 2/2 未加载 |
| N7-a | 第 1 行 `metrics` 里两个不同的分母共用键 `"of"`（后写的覆盖前写的），报告打出「todos 6/2」 | 分母各自命名：`todos_of` / `facts_of` | t23d 报告：`{todos_in_reply: 6, todos_of: 6, facts_reflected: 1, facts_of: 2}` |
| N7-b | 探针集里重复项（`固定日程`/`重点任务` 各出现两次）在报告里读起来像两次独立探针 | `payload_probe_locations` 输出去重（保序） | 门禁报告 `per_sample_locations.probes` 已去重；外层输入列表仍如实保留调用方传入的顺序 |

### 9.4 仍然保留的失败、反例与下一轮建议

- **第 8 行停用侧行为：失败 1/2，不修饰、不放宽**。样本 `off-024Z-d43a-1` 的载荷里 0 处规则文本，但回复里有一块按时间排列且恰好 3 条的内容
  （09:30 站会 / 09:45 取快递 / 10:00–12:00 写季度报告），其中 2 项是真实待办，于是被现行结构判据判成「三个重点任务」。
  同指纹的门禁给出停用侧行为 **0/2**（对照侧 2/2）与载荷 0/2，所以「停用后行为不再出现」以门禁为准；这条演示反例作为**判据灵敏度**的证据保留。
  **两次运行的对照**：t23 为 1/2（这条反例），t25 的独立重跑为 2/2（未复现）；同一判据在 t23a 的 P5 `off` 臂上也出现过 1/3 机会性命中。
- **建议（下一轮，需主控派单）**：把「重点块」判据收紧为「恰 3 条**且 3 条都是真实待办**、条目不带时钟前缀」，并因此重测 P5 六格与演示第 3/8 行；
  收紧会改变已记录的分母，属于**判据变更**，不能与本轮数字混用。
- **P5 的方向性结论**（只描述这张表）：`off` 组 0/3 与 0/3 都拿不到规则形状，fixed 2/3 与 3/3、learned 3/3 与 3/3；
  `via_facts_samples` 全 0/3。fixed 与 learned 的逐格差异在 n=3 的抽样噪声内，脚本不计算也不声明优劣。
- **未纳入**：长结果经 ref 取回（t10 的 HTTP 路由）未进入本轮；主动问候/每日回顾（P6）不在本轮。

## 6. T6 复核（review-round-1）提出的 F1–F4：修复记录与验证

| 编号 | 问题 | 修复 | 验证 |
|---|---|---|---|
| F1 | `demo_folding_and_restart` 缺局部导入 `reset_skill_cache` → `NameError`，折叠段在启动重启子进程之前中断 | 在该函数内补 `from mellowday.runtime.skills import reset_skill_cache` | t13（`…97b4`）与 t23（`…d43a`，7→2 条消息、恢复 6 条、子进程退出码 0）该组**完整执行**：`demo.folding_replaces_history_with_folded_memory`、`demo.session_continues_after_folding`、`demo.one_off_instructions_do_not_create_skills`、`demo.session_continues_after_restart` 四项全部注册并通过；`demo.folding_steps_completed` 不再出现；产物 `artifacts/restart-phase.json`（659 B：恢复 6 条消息、任务标题在恢复态里、回复点名「写季度报告大纲」）与 `artifacts/restart-phase.log`（52 B）、子进程退出码 0 |
| F2 | 判据依赖小节字面量（固定日程/重点任务），合规回复只因换了标题就判失败 | 新增 `evaluate_structural_rule()`：真实日程出现且自成一块 + 存在「顶层恰 3 条且 ≥2 条是真实待办」的重点块 + ≥3 条真实待办被采用 + 任一块条目 ≤10（十几条才算长列表） | 三个合成用例锁定语义：合规（两种标题写法）通过、8 条长列表失败、4 条重点失败；实跑 `demo.new_session_follows_the_rule` 5/5 结构断言通过（阈值与分母写在 `evidence.thresholds`），`p5` 的六格也改用同一判据 |
| F3 | 探针写死中文片段 `EDIT_SUFFIX[:12]`，技能正文被改写成别的语言后所有样本「未投递」 | `pick_body_probe()` 改为运行时从**当次正文的规则区**（第一个 `## ` 小节之前）取最长一行；正文探针与命中情况写进报告 | 本次运行 `probes.body_probe = "1. 先列出当天已有的固定日程，"`（不再是写死片段，也不是审计行），`follow_turn.delivery.body_probe_in_payload = true`；`p5_compare` 复用同一函数。**t23 追加（同一类缺陷的第二形状）**：该函数当时仍会取到 SKILL.md 的 front matter 描述行，而运行时**刻意剥掉** front matter 再交给模型 —— 于是「已投递」被报成「未投递」（t23a 实测 `body_probe="description: 在为用"`、`body_probe_in_payload=false`，而正文确实在 skill 工具结果里）。现改为跳过 front matter/标题/元数据行（短行回退 6 字），并加自检对照；t23d 的探针变为 `1. 先列出当天已有的固定日程。` 且四个投递通道全为 1 |
| F4 | 文档场景表第 8 行恢复侧数字与报告不一致（文档 (1/2) vs 报告 2/2） | 数字改为按运行标注并写明子指标含义 | 现已按最新运行写 **2/2（恢复侧抽样命中/有效，阈值 ≥1）**，并注明 t5 那次该子项为 1/2；两处数字各自标注所属运行 |

补充说明（供复核者）：

- **t23 已改掉**「停用侧检查的 `reason` 还是 t9 时代措辞」这件事：脚本现在把历史污染观测放进 `limitations_and_history`
  字段（标注为历史），`reason` 只描述当次判定；停用侧不再以「历史上有污染」为由判 BLOCKED，而是用**当次的载荷证据**判。
  「取代是否真的发生」由同一指纹下的学习门禁给出（t23：`l3.correction_supersedes_the_overlapping_fact` 通过，
  `orphans_that_needed_claiming=1`、`claimed=1`、`active_rule_facts=0`）。
- `evals/p5_compare.py` 的六格断言沿用结构断言；t23 的六格（off 0/3 与 0/3、fixed 2/3 与 3/3、learned 3/3 与 3/3，
  三臂同指纹 `0c0c0d7f636fde67`、`arms_isolated_in_separate_processes=true`、workspace 未变、同模型配置、凭据 0 命中）
  见 `docs/evidence/raw/p5-comparison-report.json` 与 `P5-minimal-comparison.md` 的 t23 附注；
  t13 的旧数字（fixed 2/3 与 1/3、learned 2/3 与 3/3，指纹 `039361a98e2a0b84`）作为历史保留在 P5 文档里。
