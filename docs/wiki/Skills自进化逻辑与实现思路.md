# Skills 自进化逻辑与实现思路

这份文档按当前代码重写，目标是说明 MellowDay 里的 Skills 是怎么被发现、调用、写入、演化和治理的。

它不是一个“自动学习”黑盒，而是一条可审计的在线沉淀链路：

```text
当前任务 -> 检索 Skill -> 执行
下一轮反馈 -> 抽取候选 -> 决策 add / merge / discard
写入 SKILL.md -> 记录 provenance -> 统计使用情况
```

## 1. 设计目标

Skills 负责沉淀“方法”，不是“事实”。
Memory 适合记事实、偏好、项目背景，Skills 适合记可复用的工作流、输出规范、判断标准和触发条件。

这套自进化系统要解决的是：

- 用户反复强调的稳定规则怎么长期保存。
- 新经验怎么不污染一次性任务内容。
- 新 Skill 怎么避免越长越多、越长越重复。
- 每次沉淀的来源、版本和结果怎么追踪。
- 一个 Skill 到底有没有真的被用上。

当前实现的原则很明确：

- 只沉淀稳定、可复用、未来仍适用的规则。
- 不沉淀一次性 payload、密钥、账号、URL、精确日期、临时项目事实。
- 优先合并已有 Skill，而不是无限新增。
- 在线写入保留 provenance，演化前保存版本快照；人工编辑走管理操作历史。

## 2. 总体链路

核心链路分成四段：

1. 在线检索：把候选 Skill 注入当前对话。
2. 在线沉淀：从对话和下一轮反馈中抽取候选。
3. 维护决策：决定 add / merge / discard。
4. 治理反馈：记录 provenance、版本、使用统计和归档信息。

这样拆开的原因是，技能系统最容易出两个问题：

- 把一次性内容误写成长期规则。
- 重复创建很多相似 Skill。

MellowDay 用 pending window、Extractor、Maintainer、provenance 和 usage stats 把这几个风险拆开处理。

## 3. 当前请求中的 Skill 检索

用户输入进入 [src/mellowday/runtime/agent.py](../../src/mellowday/runtime/agent.py) 后，会先检索相关 Skill：

```text
src/mellowday/runtime/agent.py::_augment_user_message_with_skill_context()
  -> src/mellowday/runtime/skills/skills.py::format_retrieved_skill_context()
  -> src/mellowday/runtime/skills/skills.py::retrieve_relevant_skills()
```

检索逻辑是轻量 BM25：

- query 来自当前用户消息。
- skill 文档由 `name`、`description`、`when-to-use` 和正文前 2500 字符组成。
- metadata 权重更高，正文也参与匹配。
- 中英文都会做基础 token 化。
- 默认最多返回 3 个候选。

注入到消息里的形式是：

```text
<retrieved_skills>
1. skill_name (score=..., source=project): description
   When to use: ...
</retrieved_skills>
```

当前只注入候选名称、描述与 when-to-use；检索正文参与评分不等于正文进入模型请求。网页又禁用 skill 工具，因此完整规则的自动投递链仍有缺口。

## 4. Skill 调用方式

网页当前使用候选描述注入。`Agent._augment_user_message_with_skill_context()` 只调用 `format_retrieved_skill_context()`，后者输出名称、描述和触发条件，没有规则正文。必须补齐受预算控制的正文注入并验证实际请求，才能声称完整 Skill 已参与回答。

通用运行时仍有 `execute_skill()`、inline/fork 分支，但网页 `product_mode` 不开放 skill 工具或 REPL 斜杠命令。用户在设置中维护 Skills，模型通过既有业务工具执行规则。

使用统计由回复后的 usage judge 记录，是模型判断；它不能证明未投递的规则正文已执行。

## 5. pending window：把当前轮和下一轮连起来

在线沉淀不是当前轮结束就立刻写 Skill，而是先保存一个 pending window，再等下一轮用户反馈。

相关入口：

- [src/mellowday/runtime/agent.py::_set_pending_skill_extraction_window()](../../src/mellowday/runtime/agent.py)
- [src/mellowday/runtime/agent.py::_pop_pending_skill_extraction_window()](../../src/mellowday/runtime/agent.py)

pending window 保存：

- 最近最多 8 条对话
- 当前轮原始 user 输入
- 当前轮 assistant 输出
- 当轮检索到的 top Skill reference
- session id

下一轮用户输入到来时，这个 window 会和反馈合并，成为 `ready_skill_extraction_window`，再进入在线自进化。

这个设计的意义是：用户下一轮往往会给出纠正或偏好，这比 assistant 自己猜“我学到了什么”更可靠。

## 6. online_ingest：统一在线入口

统一入口在：

```text
src/mellowday/runtime/skills/online_skill_evolution.py::online_ingest()
```

流程是：

```text
messages + retrieved_reference + hint
  -> extract_online_skill_candidate()
  -> 没候选则 action=none
  -> 有候选则 maintain_online_skill_candidate()
  -> record_online_provenance()
```

常见 action：

| action | 含义 |
|------|------|
| `none` | 没抽到值得沉淀的候选 |
| `discard` | 有候选，但重复、低价值或不应沉淀 |
| `add` | 新建 Skill |
| `merge` | 合并进已有 Skill |
| `failed` | 链路异常 |
| `add_denied` / `merge_denied` | 权限拒绝写入 |

## 7. Extractor：只负责抽取候选

入口：

```text
src/mellowday/runtime/skills/online_skill_evolution.py::extract_online_skill_candidate()
```

Extractor 的输入是：

- 对话窗口
- hint
- retrieved_reference

输出是一个候选 Skill 结构，严格 JSON：

```json
{
  "skills": [
    {
      "name": "...",
      "description": "...",
      "when_to_use": "...",
      "instructions": "...",
      "evidence": "...",
      "tags": []
    }
  ]
}
```

硬约束：

- 用户消息是主要证据。
- assistant 消息只作为上下文。
- 不抽取一次性内容、隐私、密钥、URL、账号、精确日期或临时参数。
- 只抽取未来仍有价值的工作流、输出策略、稳定纠正或重复约束。
- 证据弱就返回空。

Extractor 不写文件，只提候选。

## 8. Maintainer：决定 add / merge / discard

入口：

```text
src/mellowday/runtime/skills/online_skill_evolution.py::maintain_online_skill_candidate()
```

维护流程：

```text
candidate
  -> discover_skills()
  -> exact identity match
  -> retrieve_relevant_skills(limit=8, min_score=0.03)
  -> LLM 判断 add / merge / discard
  -> 规则兜底修正
```

规则兜底：

- 如果 name / description / when-to-use 完全重合，强制 merge。
- 如果模型判 add，但相似 Skill top score >= 0.55，也改成 merge。
- 如果 merge 但没有 target Skill，用 retrieved_reference 补位。
- 非法 action 直接降级为 discard。

决策含义：

| 结果 | 后续动作 |
|------|----------|
| `add` | `create_skill_file()` 新建 `SKILL.md` |
| `merge` | `evolve_skill_file()` 演化已有 `SKILL.md` |
| `discard` | 不写文件，只记录 provenance |

## 9. 写入统一收敛到 skill_evolution.py

无论是在线沉淀，还是设置页面的规则维护，最终都收敛到 [src/mellowday/runtime/skills/skill_evolution.py](../../src/mellowday/runtime/skills/skill_evolution.py)。

### 9.1 新建 Skill

```text
create_skill()
  -> create_skill_file()
  -> 检查同名 Skill
  -> 生成安全目录名
  -> 写入 <data>/skills/<slug>/SKILL.md
  -> usage.jsonl 记录 create
```

默认 frontmatter 包括：

- `name`
- `description`
- `version`
- `created-at`
- `user-invocable`
- `context`
- `when-to-use`
- `tags`
- `allowed-tools`

### 9.2 演化 Skill

```text
evolve_skill()
  -> evolve_skill_file()
  -> 定位已有 SKILL.md
  -> 记录演化前完整快照
  -> bump patch version
  -> 更新 last-evolved / evolution-count
  -> 写回合并后的正文
  -> usage.jsonl 记录 evolve
```

快照会写入：

```text
<data>/skill_evolution/history/<skill_slug>.jsonl
```

版本号只做 patch bump：

```text
0.1.0 -> 0.1.1 -> 0.1.2
```

## 10. Provenance：每次沉淀都可追溯

相关入口：

- [src/mellowday/runtime/skills/skill_evolution.py::record_online_skill_provenance()](../../src/mellowday/runtime/skills/skill_evolution.py)
- [src/mellowday/runtime/skills/skill_evolution.py::_update_online_provenance_index()](../../src/mellowday/runtime/skills/skill_evolution.py)

每次在线沉淀都会写：

```text
<data>/skill_evolution/online_provenance.jsonl
```

并按 Skill 聚合到：

```text
<data>/skill_evolution/online_skill_provenance.json
```

记录内容包括：

- action
- skill
- messages
- retrieved_reference
- decision
- result
- error

这条链路的意义是：不只知道“写了什么”，还知道“为什么写、怎么写、谁触发的、最终结果是什么”。

## 11. Usage stats：判断 Skill 是否真的有用

在线沉淀不只看新增，也看使用效果。

相关入口：

- [src/mellowday/runtime/agent.py::_run_skill_usage_tracking()](../../src/mellowday/runtime/agent.py)
- [src/mellowday/runtime/skills/online_skill_evolution.py::judge_retrieved_skill_usage()](../../src/mellowday/runtime/skills/online_skill_evolution.py)
- [src/mellowday/runtime/skills/skill_evolution.py::record_skill_usage_judgments()](../../src/mellowday/runtime/skills/skill_evolution.py)

每轮回复后，如果本轮检索过 Skills，会判断：

- 这个 Skill 是否和用户请求相关。
- assistant 回复是否真的用了这个 Skill 的工作流或策略。

统计写入：

```text
<data>/skill_evolution/skill_usage_stats.json
```

典型字段：

| 字段 | 含义 |
|------|------|
| `retrieved` | 被检索出来的次数 |
| `relevant` | 被判断为相关的次数 |
| `used` | 被判断为实际使用的次数 |
| `last_retrieved` | 最近一次被检索时间 |
| `last_used` | 最近一次实际使用时间 |
| `last_reason` | 最近一次判断原因 |

长期被检索但未使用的 Skill 可按阈值归档；本项目全部为 project 来源，默认不自动清理，须显式开启 `MELLOWDAY_SKILL_PRUNE_PROJECT`。默认门槛为 retrieved ≥ 40 且 used ≤ 0，归档到：

```text
<data>/skills/.archive/
```

## 12. 权限和开关

后台学习开关为 `MELLOWDAY_AUTO_SKILL_EVOLUTION`（默认开启）。`MELLOWDAY_AUTO_SKILL_TARGET` 保留兼容参数，当前活动技能始终归属于同一个数据根目录，不提供跨项目用户技能库。

网页授权规则：

| 来源 | 写入条件 |
|---|---|
| 用户明确的长期任务方法 | 当前消息明确授权，完整结构化候选及合并计划经独立评估匹配，才可自动写入 |
| 模型自行推导的规则 | 先弹出确认 |
| 临时要求 | 作用域门禁跳过学习 |
| 身份、人格、记忆迁移、扩权限 | 不走任务方法自动授权 |

`SkillWriteSummary` 同时携带人类预览和完整变更，`personal_assistant/skill_consent.py` 只核对完整内容。不能凭 300 字预览批准看不见的尾部指令。不确定或检查失败回退确认。

显式来源记忆迁移须经确认、核对快照，再在技能成功后处理；它不是与 Skill 文件的跨存储原子事务。此能力不能挖掘旧聊天来创建记忆。

## 13. 手动维护入口

在设置 → Skills 查看规则正文、编辑、停用/恢复及历史版本。对应 `runtime/skills/skill_management.py` 和 Web 路由。

当前网页不提供 `/extract_now`、`/skill-create`、`/skill-evolve`、`/skill-eval` 命令。离线开发可调用 Python 管理/评测 API，但不能把它们写成聊天命令教程。

临时任务只执行，不沉淀；明确的长期方法按授权协议学习；已有方法的修改与人工编辑都保留版本。

## 14. 当前项目可观察状态

应用 lifespan 首次安装 `calendar-conversation`，内容是日程区间查询、排序、真实记录引用及订阅授权边界。安装标记避免用户停用后再次强制生成。

其他 Skills 取决于实际使用与人工维护，文档不预填用户环境中“已有”的技能列表。审计路径为：

```text
<data>/skill_evolution/usage.jsonl
<data>/skill_evolution/online_provenance.jsonl
<data>/skill_evolution/online_skill_provenance.json
<data>/skill_evolution/skill_usage_stats.json
<data>/skill_evolution/history/
```

“used” 是模型对采用情况的判断，不等于业务结果正确。定时汇报目前采用只读模板，不能说每次后台投递都会运行学习后的 Skill。

## 15. 实现思路总结

这套自进化机制可以概括成四个闭环：

### 15.1 召回闭环

```text
discover_skills()
  -> retrieve_relevant_skills()
  -> retrieved_skills 注入
  -> 候选描述注入（完整正文投递待补齐）
```

### 15.2 沉淀闭环

```text
当前轮任务和回答
  -> pending window
  -> 下一轮用户反馈
  -> Extractor 抽取候选
  -> Maintainer 决策 add / merge / discard
  -> SKILL.md 落盘
```

### 15.3 审计闭环

```text
create / evolve / discard / failed
  -> usage.jsonl
  -> online_provenance.jsonl
  -> online_skill_provenance.json
  -> history snapshot
```

### 15.4 质量反馈闭环

```text
retrieved skills
  -> judge relevance and used
  -> skill_usage_stats.json
  -> stale prune
```

核心取舍是：

- 用 `SKILL.md` 做能力载体，方便人工编辑和版本管理。
- 用轻量检索降低依赖。
- 用下一轮用户反馈提高证据质量。
- 用 Extractor / Maintainer 拆分降低误写风险。
- 用 add / merge / discard 控制规模。
- 用 provenance、history、usage stats 保证可回放、可解释、可治理。

## 16. 关键代码定位

| 逻辑 | 代码入口（`src/mellowday/` 下） |
|---|---|
| Skill 发现/检索 | `runtime/skills/skills.py` |
| 候选描述注入/pending window | `runtime/agent.py` |
| 抽取与维护 | `runtime/skills/online_skill_evolution.py` |
| 完整变更授权 | `personal_assistant/skill_consent.py` |
| 版本/审计/统计 | `runtime/skills/skill_evolution.py` |
| 人工管理 | `runtime/skills/skill_management.py` |
| 内置日程方法 | `personal_assistant/default_skills.py` |

## 17. 一句话总结

MellowDay 的 Skills 自进化，不是让模型随便改自己，而是把用户认可的稳定工作流，经过抽取、决策、写入、审计和统计，沉淀成可复用、可追踪、可治理的 `SKILL.md`。
