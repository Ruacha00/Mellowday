# T5 重跑（t11）：t9 落地后的复核，以及 t5 结论的存废

日期：2026-09-18（第三轮）
命令：`python scripts/gate_l3_learning.py --attempts 2 --selfcheck`、`python scripts/demo_core.py --attempts 2`、`python evals/p5_compare.py --samples 3`
脚本：`scripts/gate_common.py`（新增「已失效旧值」段落探针与三段式定位）、`scripts/gate_l3_learning.py`（新增取代断言、停用侧载荷断言、折叠/重启不回注断言）、`evals/p5_compare.py`（新增载荷级规则文本断言与事实库活动规则断言）

## 0. 这次重跑在什么代码上跑的

- **晚于 t9**（写入期去重：同一纠正窗口内与规则实质重叠的事实被标记 superseded），
  **早于 t12**（一次性要求不得被学习仍在 skills-ux 手上）——
  因此本轮里的两条「一次性要求不学习」断言**预期失败**，如实记录为已知失败，不作为本轮结论。
- 工作区指纹（运行开始时刻）见第 3 节；运行期间是否发生变动、以及变动是否使
  `code.workspace_unchanged_during_the_run` 判 inconclusive，也在第 3 节如实记录。
- ⚠️ 与 t5 的关键差异：t9 之后，规则的归属是**单一来源**（技能库）；事实库里的重叠副本被
  标记取代而不是继续注入。t5 期间「关闭技能 ≠ 规则不存在」的污染前提已经消失，这就是本轮
  可以给出停用侧结论的原因。

## 1. 本轮新增的断言（为什么必须新增）

| 断言 | 解决的问题 |
|---|---|
| `l3.correction_supersedes_the_overlapping_fact` | 「规则没出现」与「重复副本确实被取代」是两回事。断言要求：纠正窗口写入的事实行存在 `status=superseded` 且 `meta.superseded_by_skill` 指向刚学到的技能；若该窗口本轮没有写事实，则判 **inconclusive**（避免又一次空洞通过） |
| `l3.disable_side_payload_carries_no_rule_text (sampled N)` | 停用侧不看技能列表、不看系统提示，只看**实际请求载荷**：三段式定位（召回事实段 / 已失效旧值段 / 其余请求文本）里都不允许出现规则文本 |
| `l3.fold_and_restore_do_not_reintroduce_the_rule` | 折叠记忆不得含规则文本；用新的 Store/Registry 恢复会话（与进程重启同一条 `load_session` 路径）后，注入段与请求里仍不得出现规则文本 |
| `p5.off_payload_carries_no_rule_text (sampled N)` | P5 的「关闭 Skill」条件同样改为载荷级断言：每个样本的请求里都不得出现规则措辞 |
| `p5.<条件>_rule_is_not_active_in_the_fact_store` | 任何条件下都不得存在**活动**的规则事实（活动副本会被注入每一个会话）；已被取代的行是预期结果，如实记录 |

三处探针定位（新增自检 `selfcheck.probe_location_separates_fact_blocks_from_the_rest`）：
召回事实段 `Recalled facts about the user …`、已失效旧值段
`Facts that were current earlier in this conversation and are NOT current any more:`、其余请求文本。

## 2. t5 结论的存废

| t5 结论 | 存废 | 理由 |
|---|---|---|
| 规划读取真实记录与当前事实（P3 事实注入） | **仍成立** | 与事实通道污染无关；本轮核心演示复跑再次覆盖 |
| 纠正 → 确认 → 落盘规则；真实 HTTP 审查/编辑/版本/回退 | **仍成立** | 与事实通道无关 |
| 全新会话遵循规则；重复反馈不升版；明确要求覆盖习惯；无关请求不加载规则 | **仍成立** | 与事实通道无关（无关请求的「不加载」在 t5 已按载荷级判定） |
| 折叠 + 真实重启续跑 | **仍成立** | 与事实通道无关 |
| **停用规则后不再生效** | t5 判 BLOCKED（作废） → **本轮给出结论** | t9 之后规则归属单一来源；本轮以载荷级断言重测 |
| P5 三条件的对照数字 | t5 的数字仍可引用，但**不作为最终结论** | t5 的「关闭 Skill」只断言了技能列表/系统提示；本轮改为载荷级断言并重测 |
| 一次性要求不学习（两条） | **仍失败（早于 t12）** | 见第 3 节失败清单；由 t12 负责 |

## 3. 本轮运行结果

### 3.1 运行清单（每次跑在哪棵树上，如实标注）

| 运行 | run id | 运行开始的工作区指纹 | 结果 | workspace 检查 |
|---|---|---|---|---|
| 学习门禁（真实模型） | `20260918T125255Z-9760` | `bae0da166b100d5e` | 31 通过 / 5 失败 / 2 无法判定（共 38） | **inconclusive**：运行期间 3 个文件变化（`runtime/skills/__init__.py`、`runtime/skills/online_skill_evolution.py`、`tests/runtime/test_one_off_not_learned.py`）＝ t12 的在飞改动 |
| 核心演示（真实模型） | `20260918T125625Z-54b4` | `137e87a093107d66` | 19 通过 / 1 失败 / 1 无法判定（共 21） | passed：运行期间 0 变化 |
| P5 关闭 Skill | `20260918T130048Z-691c` | `137e87a093107d66` | 9/9 通过 | passed：0 变化 |
| P5 固定 Skill | `20260918T130243Z-2a59` | `137e87a093107d66` | 9/9 通过 | passed：0 变化 |
| P5 学习后 Skill | `20260918T130501Z-f567` | `137e87a093107d66` | 9/9 通过 | passed：0 变化 |

要点：学习门禁那次**早于 t12**（t12 的文件正在写入，指纹 `bae0da166b100d5e`）；核心演示与 P5 三组的指纹同为 `137e87a093107d66`，即已经包含 t12 的改动（但 t12 当时尚未宣告完成）。三份报告的 `code.gate_file_hashes` 都指向同一版门禁脚本（`demo_core.py=ea6a43347bdb8bff`、`gate_l3_learning.py=3d371b4a76ce91fc`），本轮之后我又修了脚本（F1/F5/折叠断言），因此**t11 的这两项（折叠/重启、离线报告路径）需在 t13 重取**。

### 3.2 停用条件：仍未通过，但根因已经不同（新发现 F6）

本轮新增的载荷级断言给出的结论：

| 断言 | 结果 | 证据 |
|---|---|---|
| `l3.correction_supersedes_the_overlapping_fact` | **无法判定**（不是通过） | 「纠正窗口本轮没有写事实」，取代没有触发点；按设计不给空洞通过 |
| `l3.disable_side_payload_carries_no_rule_text (sampled 2)` | **失败** | 两个停用侧样本的**召回事实段**都出现 `['固定日程','重点任务']`；已失效旧值段 0；其余请求文本 0 |
| `l3.fold_and_restore_do_not_reintroduce_the_rule` | **失败** | 折叠后继续与恢复后注入段仍在召回事实段里带出规则文本 |
| `l3.disabled_rule_stops_changing_behaviour (sampled 2)` | **失败** | 2/2 样本仍满足规则；原因同上 |

**根因（F6）**：那条规则事实是**被拒绝的确认**那一轮写下的，而不是确认成功的那一轮：

- deny 会话的纠正轮工具调用 = `['remember_fact','list_calendar']` → 模型把纠正写成了用户事实；
- 同一轮里技能写入被拒绝（`denied_confirmation_writes_nothing` 通过，技能列表没有新增）→ **没有技能可以承认取代这条事实**；
- 之后确认成功的学习会话里，取代只覆盖**自己窗口内**写下的事实（本轮 `facts_written_in_the_correction_window = 0`）→ 那条 active 事实活下来，被注入每一个会话。

证据链（都可复核）：报告 `supersession.active_facts_carrying_the_rule`（标签「规划方式偏好」、内容＝规则）、run 目录 `data/mellowday.sqlite3` 里该行的 `status=active`、deny 样本的工具调用，以及停用侧样本的三段式定位。

**判据现状**：停用条件**不能给通过结论**（与 t5 相同的结论），但原因不同——不是「t9 没实现」，而是「**被拒绝的纠正路径留下的孤儿事实**没有被任何技能认领」。三种可选处理（需主控裁决）：

1. 取代判据不看窗口，只看「与规则实质重叠的 active 事实」——技能一旦写入，把全库中与它实质重叠的 active 事实都标记取代（最彻底，但要防止误伤用户独立表达的同义偏好）；
2. 拒绝技能写入时提示/处理该窗口写下的事实（把「事实是唯一副本」的情形显式化）；
3. 明确「没有技能时，事实就是该规则的唯一来源」，并把停用语义限定为「技能存在时才谈停用」——那么门禁的 deny→learn 序列本身要改写。

另外，`l3.a_new_session_follows_the_learned_rule` 有 1 个样本因小节标题措辞不同而判失败（未满足 `section:重点任务 / term:每日站会`）——这与 T6 的 F2 同类（字面量代替结构），属于 t13 要改掉的判据问题，不是产品结论。

### 3.3 P5 重跑（t12 之后的树，本轮有效数字）

> 说明（t13 更新）：本节表格由**当时**的字面量小节判据（固定日程/重点任务）产生。t13 已把判据改为
> 结构断言（真实日程 + 恰 3 条重点块 + ≥3 条真实待办 + 无长列表），并在含 t16 的冻结代码
> （指纹 `039361a98e2a0b84`）上重跑，六格为 off 0/3 与 0/3、fixed 2/3 与 1/3、learned 2/3 与 3/3
> （见 `docs/evidence/P3-P4-core-demo.md` 与 `raw/p5-comparison-report.json`）。
> 本节数字保留用于「t5 vs t11」的逐格对照，不作为最终结论。
> **t23 的最终对照**（三臂同指纹 `0c0c0d7f636fde67`、每臂独立进程、事实通道 0/3）：
> off 0/3 与 0/3、fixed 2/3 与 3/3、learned 3/3 与 3/3 —— 见 `P5-minimal-comparison.md` 的 t23 附注。

| 条件 | 案例 | t5（pre-t9 的树） | t11 重跑 | 说明 |
|---|---|---|---|---|
| `off` | 开发 | 0/3 | **0/3** | 一致 |
| `off` | 保留 | 0/3 | **0/3** | 一致 |
| `fixed` | 开发 | 2/3 | **2/3** | 一致 |
| `fixed` | 保留 | 3/3 | **3/3** | 一致 |
| `learned` | 开发 | 3/3 | **2/3** | n=3，差值在抽样噪声内 |
| `learned` | 保留 | 2/3 | **2/3** | 一致 |

本轮新增/加强的断言，三组全部通过：

- `p5.off_payload_carries_no_rule_text (sampled 6)`：关闭条件下 6 个样本的**请求载荷**（召回段 / 已失效旧值段 / 其余）都没有规则措辞——这是 T5 之后把「关闭 Skill」从「技能列表/系统提示」改成语义正确的载荷级断言；
- `p5.<条件>_rule_is_not_active_in_the_fact_store`：任何条件下都不存在活动的规则事实；
- `code.workspace_unchanged_during_the_run`：三组均通过（`137e87a093107d66`），即这次 P5 重跑期间工作区**没有**变化；
- 同模型配置（`same_model_configuration=true`）、凭据扫描 0 命中、9 个未命中样本逐条留档（`failures`）。

**t5 的 P5 结论是否仍成立**：数字层面**逐格一致**（除 learned/dev 的 3/3→2/3 属抽样噪声），因此 t5 的对照结论**仍然成立**；加强之处只是关闭条件现在由载荷级断言证明。仍然**不宣称**任何普遍提升，也不计算提升比例。

### 3.4 失败与未执行清单（本轮）

| 项 | 性质 | 处理 |
|---|---|---|
| `demo.folding_steps_completed` 失败（`NameError: reset_skill_cache`） | **脚本缺陷 F1**（T6 报出，已修） | 折叠/重启断言**未执行**，不计入产品结论；t13 重取 |
| T6 F2（措辞敏感判据）、F3（写死中文探针）、F4（文档数字笔误） | 判据/文档缺陷 | 已列入 t13；本轮学习门禁的 wording 敏感样本即 F2 类 |
| F5：离线运行覆盖稳定报告路径 | 工具缺陷（本轮出现两次，两次都从运行目录不可变副本恢复） | 已修：离线运行默认写运行目录，显式 `--json-out` 才覆盖稳定路径 |
| 折叠断言中的「摘要不得含规则词」 | 判据过严（对话本身就在谈这条规则） | 已改为「注入段（召回 + 已失效旧值）不得含规则文本」，摘要内容只记录不断言；t13 生效 |
| F6：被拒绝路径留下的孤儿事实 | **产品发现**（见 3.2） | t16 已按方案①修复（取代范围＝全库 active）；t15 在 t16 树上取得通过结论，见第 5 节 |

## 5. t15：t16 落地后的停用侧权威数字（学习门禁，最终代码）

命令：`python scripts/gate_l3_learning.py --attempts 2 --selfcheck`
运行：`20260918T134647Z-2bb7`　13:46:47Z → 13:50:07Z　模型 `deepseek-v4-pro`　28 次请求
工作区指纹：起始 `aea106645695158c`（运行期间 `runtime/skills/skills.py` 被另一单元改动 → `code.workspace_unchanged_during_the_run` 按规则判 inconclusive，只影响该项）
结果：**37 通过 / 0 失败 / 1 无法判定（共 38）**

| 关键检查 | 结果 | 证据（含分母） |
|---|---|---|
| `l3.correction_supersedes_the_overlapping_fact` | **通过** | 被拒绝那一轮写下的规则事实（标签「规划习惯」，在 deny 阶段处于 active）在后续学习轮被技能认领：`status=superseded`、`meta.superseded_by_skill=日程规划输出规则`、`superseded_at=2026-09-18T13:48:09Z`；指标 `orphans_that_needed_claiming=1 / claimed=1 / active_rule_facts=0`。这正是 F6 要求的「确实发生取代」，而非「规则没出现」 |
| `l3.disable_side_payload_carries_no_rule_text (sampled 2)` | **通过** | 2/2 停用侧样本的三段定位全部为空：召回段 []、已失效旧值段 []、其余请求文本 [] |
| `l3.disabled_rule_stops_changing_behaviour (sampled 2)` | **通过** | 命中 0/2、有效 2/2，对照成立（启用侧抽样命中）→ 停用后行为确实不再出现 |
| `l3.fold_and_restore_do_not_reintroduce_the_rule` | **通过** | 折叠 8→2 条消息；折叠后继续与恢复后请求的**注入段**规则文本命中 0；折叠摘要提到规则（4 处）只作记录——对话本身就在谈这条纠正，不算泄漏 |
| 库内事实终态 | — | `规划习惯` 为 `superseded` 且带技能指针；无 active 的规则事实 |

**这解决了 3.2 的悬案**：t11 判 inconclusive/失败的原因（被拒绝路径留下的孤儿事实没人认领）在 t16 之后消失；停用侧结论由「BLOCKED」转为**通过**，且判据是载荷级 + 取代记录级，而不是「技能列表里看不到」。

### 5.1 本任务中修掉的两个门禁自身缺陷（如实记录）

第一次在 t16 树上跑（run `20260918T134239Z-73e8`）时，上面两项报红；追查后确认**都是门禁自身的问题**，产品行为是对的：

1. `meta` 解析：Store 返回的 `meta` 已经是 dict，我却又对它做 `json.loads(str(...))` → 解析失败 → 指针列表为空 → 正确的取代被判成「未被认领」。改为「已是 mapping 直接用，否则解析字符串」。
2. 折叠断言残留：`ok_fold` 里仍留着两条「整个请求都不得出现规则文本」（`present_anywhere`）的条件——而学习会话的对话本身就在讨论这条纠正，永远不可能满足。已删除，只断言两个注入段。

这两条与 T14 复核的 N2（测量工具必须带可执行负向对照）是同一类风险：判据错会把正确行为判成缺陷，也会把缺陷判成通过。修好后的重跑即上表结果。

### 5.2 t13 结论的有效性（t15 不重跑演示与 P5）

按主控口径，t15 **只补学习门禁**。t13 在含 t16 的同一代码（指纹 `039361a98e2a0b84`）上取得的结论继续成立：
核心演示 21 通过 / 0 失败 / 1 无法判定（折叠+重启段真的执行，restart-phase.json 齐备）；P5 off 0/3 与 0/3、fixed 2/3 与 1/3、learned 2/3 与 3/3，
三组同模型配置、同业务种子、凭据 0 命中、off 侧载荷断言通过、不计算提升比例。

## 4. 复现

~~~powershell
cd MellowDay-Rebuild

# 学习门禁（含取代断言、停用侧载荷断言、折叠/重启不回注断言）
python scripts/gate_l3_learning.py --attempts 2 --selfcheck

# 核心演示（含两条一次性要求断言：早于 t12 时预期失败）
python scripts/demo_core.py --attempts 2

# P5 对照（三条件 × 两案例 × 3 样本；关闭条件为载荷级断言）
python evals/p5_compare.py --samples 3

# 离线自检（不调用模型）
python scripts/gate_l3_learning.py --offline --selfcheck
python evals/p5_compare.py --offline
~~~
