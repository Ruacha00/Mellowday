# T6 独立复核：核心演示与最小 P5 对照是否成立

复核时间：2026-09-18（第三轮）　复核人：sessions-store（t6，独立于 t5/verifier）
结论：**needs_revision（不通过，需修订后重跑）**——证据主体真实且大部分可独立复现，但存在 1 个阻断项（当前 demo 脚本崩溃，折叠/重启段无法复跑）与 1 个方法项（通过/失败依赖措辞，同一代码下会翻转）。

## 1. 复核方法（不采信 T5 自述）

1. 独立重跑文档中的命令（真实模型 + 真实 uvicorn + 真实重启子进程）：
   `python scripts/demo_core.py --attempts 2 --json-out docs/evidence/raw/core-demo-report-t6-rerun.json`
   → run `20260918T125044Z-d031`，**16 passed / 3 failed / 2 inconclusive**（T5 文档那次是 18/1/2）。报告：`docs/evidence/raw/core-demo-report-t6-rerun.json`；运行目录：`output/gate-runs/core-demo/20260918T125044Z-d031/`。
2. 另写脚本直接读运行目录产物（只读 SQLite + `artifacts/model-calls.jsonl`），核对工具调用参数与数据库行、事实是否真的进入出站载荷、写入是否有重复。
3. 用原始报告重算 P5 六个格子的命中与分母，并与文档表格逐格比对。
4. 读 `scripts/gate_common.py`、`scripts/gate_l3_learning.py`、`scripts/demo_core.py` 源码，核对文档声称的 7 条方法问题修正是否真的实现（重点 M1 隔离、M3 死请求不算证据）。

## 2. 独立验证为真、可复现的部分

**场景确实执行过（逐项有原始产物，非「代码看起来支持」）**

| 场景 | 我的复核 |
|---|---|
| 规划同时用日历/待办与当前事实 | 计划轮工具调用 `list_todos` / `list_calendar` / `list_reminders` 各 1 次；两条 active 事实正文都出现在出站 payload（按事实 detail 前缀搜索 payload_text 确认）；回复写入 09:30 每日站会 + 6/6 条待办 |
| 纠正→确认→落盘 | 真实 `skill_candidate_proposed` + 1 个确认 token + `skill_candidate_applied`，运行目录内有 SKILL.md 与版本历史 |
| HTTP 审查/编辑/版本/回退 | 真实 uvicorn 进程，`GET /api/skills`、`GET/PUT /api/skills/{name}`、`GET /versions/0.1.0` 全部 200，版本 0.1.0→0.1.1，回退后旧正文命中 |
| 新会话遵循规则 | T5 run 2/2 命中（规则正文/名称在请求里）；我的重跑同样通过 |
| 重复反馈合并 | `skill_candidate_skipped`，版本不变、技能数不变、人工补句仍在 |
| 临时要求不学习 | **两次运行都失败**（T5 run 0.1.1→0.1.2，我的重跑 0.1.2→0.1.3）→ T5 记录的产品缺陷可复现，非偶发 |
| 当前要求覆盖习惯 | 明确要求列全部待办后 6/6 条列出，不被「只排三个」限制 |
| 无关请求不加载规则 | 检索块无该技能、无 skill 调用、正文片段不在 payload；真实新建 1 条待办 |
| 停用/恢复/版本回退 | 停用：提示词无规则、2 个请求 payload_leaks=0；恢复：提示词恢复 + 规则投递；回退：0.1.0 正文恢复 |
| 折叠与重启后继续 | T5 run：`artifacts/restart-phase.json` exit_code=0、restored_message_count=6、任务标题在恢复状态里（**确已执行**）；我的重跑：该段**未执行**（见 F1） |

**工具调用参数 ↔ 数据库最终结果一致（不看回复关键词）**

- T5 run：12 行记录（1 日历 + 6 种子待办 + 取快递 + 写季度报告大纲 + 3 记忆）；`create_todo` 的 2 个参数标题各对应唯一行；`remember_fact` 的 1 个标签对应 1 行；无重复 (kind,title)；无未匹配写入；46 次模型调用 0 错误。
- 我的 run：13 行；4 次写调用（2 次 remember_fact + 2 次 create_todo）全部对应唯一行；无重复；无未匹配；41 次模型调用 0 错误。
- t9 取代在两次运行里都真实发生：纠正写的事实 status=superseded 且带 `meta.superseded_by_skill`，活动事实集里没有它。

**P5 对照（重算而非采信）**

- 三组运行目录的 `data/config.json` **字节完全相同**（sha256 `f06a5f4bea7ca7ce`，模型 deepseek-v4-pro / api.deepseek.com / thinking=false / max_turns=null）→ 同模型参数成立。
- 业务初始数据一致：dev 组（每日站会 + 6 待办 + 2 事实）三组相同；holdout 组（客户复盘会 + 4 待办）三组相同；learned 组的 holdout 记录创建于纠正轮**之后**（12:46:59 > 纠正/落盘 12:46:42），与文档「holdout 在学习轮之后写入」一致。
- 分母写明且我重算一致：off 开发 0/3、off 保留 0/3、fixed 开发 2/3、fixed 保留 3/3、learned 开发 3/3、learned 保留 2/3；每格 valid=3；`failures` 数组 = 未命中样本（8 条），逐样本 `hit == rule.ok == 无失败断言` 全部自洽。
- 未宣称普遍提升：脚本与文档都只报计数，文档明确「两个差值都在抽样噪声范围内，不计算提升比例」。

**门禁方法 7 条问题的修正（读代码 + 独立跑离线段）**

- M1：`RunContext.prepare()` 在导入 mellowday 之前把 `MELLOWDAY_DATA_DIR` 指向本次运行目录、`MELLOWDAY_ENV_FILE` 置空，运行目录必须不存在（禁止复用），并对真实数据目录做只读 stat 快照。独立执行 `python scripts/gate_l3.py --offline` → 12 passed/0 failed，其中 `isolation.real_data_directory_untouched` 通过。
- M3：`gate_common.off_side_verdict()` 只在「每个样本都答了（无错误/非空）+ 阳性对照成立 + payload 无泄漏」时才可能返回 True；样本有错误或空回复时给出 inconclusive 理由「a dead request is not evidence that the habit was absent」。演示里对应检查也如此（我的重跑 `valid: 2, invalid: []`，且该场景整体被 blocked/inconclusive）。
- M2：运行目录必须新建（存在即报错）+ 每个样本记录 `freshness.fresh`；M4：`ModelCallRecorder` 记录每次请求实际 `model` 标识，`switch_verdict()` 按真实序列判定；M5：离线检查逐条核对数据库行（create/update/delete/undo/fact），不是子串断言；M6：报告带工作区指纹、请求参数、完整响应、工具参数与分母；M7：凭据注册脱敏 + 落盘前扫描（两次运行 0 命中），无凭据时退出码 2 且留档。

## 3. 发现（必须修订）

### F1 [blocker] 当前 scripts/demo_core.py 在折叠段崩溃，文档命令无法复现文档结果

- 现象：`NameError: name 'reset_skill_cache' is not defined`，位置 `scripts/demo_core.py:873`（`demo_folding_and_restart` 内），同文件 272/470/538 行都有局部导入，873 行所在函数缺一个。
- 后果：该函数在其后的重启子进程（约 903 行）之前中断 → 我的 run 目录里**没有** `artifacts/restart-phase.json` / `restart-phase.log`，报告里也没有 `demo.session_continues_after_restart` 这一项（只有 21 项中的 `demo.folding_steps_completed` 失败）。折叠场景的「一次性指令不得落为技能」断言（T5 新发现 #2 对应的新检查）同样没有机会执行。
- 归因（如实）：T5 文档那次运行用的是 `scripts/demo_core.py` 哈希 `20565f20a1b801af`（报告内记录），当前文件是 `ea6a43347bdb8bff`（mtime 12:42:43Z，落在 T5 运行之后、P5 运行之前）——即缺陷是 T5 文档之后对脚本的改动引入的，不否定那次运行；但它使「当前交付物按文档命令可复现」不成立。
- 修复：在 `demo_folding_and_restart` 内补 `from mellowday.runtime.skills import reset_skill_cache`（或提到模块级），然后重跑一次核心演示。

### F2 [high] 判据依赖措辞：同一场景在同一代码下会翻转，且失败样本的业务行为其实合规

- 现象：`demo.enabled_rule_changes_behaviour_again` 在 T5 run 为 hits 2/2 通过；我的重跑 hits 0/2 失败。两次运行的差异不是行为，而是措辞：我的两个回复都先列出真实固定日程、且恰好 3 条重点任务，但小节标题写成「先看固定安排 / 今天（明天）重点 3 项 / 三件重点（只排这三件）」，而判据把 spec 的 `sections: ["固定日程", "重点任务"]` 当字面量（`rule.detail.evidence.items.method = "unparseable"`，`items` 未被评估）。
- 判定阈值本身也弱：`gc.on_side_verdict(back_samples, min_hits=1)` → 2 个样本里 1 个命中即通过；因此在措辞敏感的前提下，「通过」只是抽样噪声的产物。
- 这正是本轮要消除的「用关键词/字面量代替业务正确性」的同一类问题，只是方向相反（业务正确被判失败）。建议：断言结构而非标题字面量——(a) 存在一个包含真实日程（09:30 每日站会）的日程小节；(b) 一个「重点/优先」小节且顶层条目恰为 3；(c) 至少 3 条真实待办被采用；(d) 不使用「十几条」长列表；(e) 期望标题可从当次学到的技能正文派生（正文里同时出现「固定日程」「重点任务」时才要求字面标题）。
- 影响：演示的通过/失败会随模型措辞漂移（我的重跑 16/3/2 vs 文档 18/1/2），「18 通过」这一结论不具备稳定性。

### F3 [low] 文档与报告不一致（低报）

- `P3-P4-core-demo.md` 第 8 行场景表写「恢复：提示词恢复 + 2 个新会话里 ≥1 个满足规则（1/2）」，而报告 check 14 记录 `hits: 2, of: 2`（两个样本均命中）。方向是低报，但数字必须对齐。

### F4 [medium]「规则正文确实被投递」的探针写死，跨运行失效

- `body_probe = EDIT_SUFFIX[:12]`（"在给出三个重点任务时，同"）只在正文为中文时命中；我的重跑学到的是英文正文（`daily-planning-with-fixed-schedule-and-top-3-tasks` 正文为英文），于是每个样本 `body_probe_in_payload = false`，判据靠技能名兜底才通过。文档所述「检索块 + skill 工具调用 + 正文片段三类证据」里的第三类在跨运行条件下并不成立。建议探针在运行时从当次技能正文派生（例如取正文中最长的一条规则行）。

## 4. 按要求如实列为「当前交付物未通过/未复现」的场景

- **折叠与重启后继续**：T5 文档那次运行确已执行（restart-phase.json exit 0、恢复 6 条消息、任务标题在恢复状态里），但本次复核无法在当前交付物上复现（F1），因此对**当前交付物**该场景证据缺失，不算通过。
- 其余场景在两次运行中都真实执行过，逐项有原始产物，不列为未通过。

## 5. 限制（诚实声明）

- 我的重跑期间工作区有其它单元改动（`code.workspace_unchanged_during_the_run` 判 inconclusive，changed_files 4 个），因此我的 run 只代表运行开始时的指纹（`d1b2408fe5412a3b`）。
- 抽样规模 T5 用 2（我的重跑同 2），命中类结论只能看方向；P5 每格 3 样本，同样只用于确认结构。
- 我未修改 `scripts/**`、`evals/**`（不在 t6 写入范围），F1/F2/F4 需由其所有者修订后重跑。

## 6. 复核可复现步骤

~~~powershell
cd MellowDay-Rebuild
python scripts/demo_core.py --attempts 2 --json-out docs\evidence\raw\core-demo-report-t6-rerun.json
python scripts/gate_l3.py --offline          # 方法自检（不需凭据）
python scripts/gate_l3_learning.py --offline
# 报告对比：docs/evidence/raw/core-demo-report.json（T5）vs core-demo-report-t6-rerun.json（本次）
# 运行产物：output/gate-runs/core-demo/<run-id>/{data,artifacts}
~~~
