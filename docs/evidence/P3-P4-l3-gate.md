# L3 门禁：真实模型下的行为验证（P3 事实 / P4 学习闭环）

> ## ⚠️ 部分结论已作废（2026-09-19 第三轮更正）
>
> 本文档中「习惯仅在启用时进入新会话提示词（确定性）」与「停用后行为中绝不出现」两条结论**不再成立**，请勿引用。
>
> 原因：本轮更严格的门禁检查了**实际请求载荷**并分别统计两个通道，发现同一条纠正会同时落进技能库与用户事实库；
> 停用技能后技能通道确实清零（0/2），但事实通道仍把该规则注入每一轮请求（**payload_leaks=2**，
> 「the disabled rule text was still delivered to the model in 2 of 2 requests」，其中一轮回复仍完整满足该规则）。
> 本文档当时只验证了技能通道，属于门禁覆盖不足，因此那两条「通过」是**假阳性**。
>
> 证据：`docs/evidence/P3-P4-l3-gate-method.md`、`docs/evidence/raw/gate-l3-learning-report.json`
> （检查项 `l3.disabled_rule_stops_changing_behaviour`、`l3.correction_does_not_duplicate_the_rule_into_the_memory_store`）。
>
> 修复中：t9（规则归属单一来源，契约 6quater.1）；修复后由 t11（T5 重跑）重新取证。
> 本文件其余结论（事实自动召回、模型切换、删除清理等）仍然有效。

日期：2026-09-19　模型：`deepseek-v4-pro`　端点：`https://api.deepseek.com`
脚本：`scripts/gate_l3.py`（行为门禁）、`scripts/gate_l3_learning.py`（学习闭环门禁）
原始报告：`docs/evidence/raw/gate-l3-report.json`、`docs/evidence/raw/gate-l3-learning-report.json`

## 门禁设计：确定性与抽样分开

「模型是否遵循习惯」在 temperature=1 下单次采样是不稳定的，只跑一次会让门禁两个方向都说谎。因此分两类：

- **确定性检查**：新会话的 system prompt 里到底有没有这条规则。这是产品契约本身，与模型心情无关。
- **抽样检查**：跑 2 次并记录命中比例，用于确认行为方向。

第一版门禁把「停用后行为消失」写成单次断言，结果是**假通过**——当时习惯根本没生效，标记永远不出现，检查自然「通过」。已加 `meaningful: habit_on` 前置条件，杜绝这种空洞通过。

## 结果一：可复用习惯的行为门禁（6/6 通过）

| 检查 | 结果 | 证据摘要 |
|---|---|---|
| 习惯仅在启用时进入新会话提示词 | PASS | 启用 true / 停用 false / 恢复 true |
| 启用时改变行为（抽样 2 次） | PASS | 命中 1/2，答复首行输出标记并给出两日行程 |
| 停用后行为中绝不出现 | PASS | 命中 0/2 |
| 保存的事实无需工具调用即被使用 | PASS | 新会话直接答「你通常六点（18:00）下班。」，`tools: []` |
| 改模型即时生效且历史不丢 | PASS | `deepseek-v4-pro` → `deepseek-flash`，同会话两轮，历史 4 条 |
| 删除会话清理全部产物 | PASS | 无残留文件、`exists=false`、trace 为空 |

## 结果二：学习闭环门禁（3/3 通过）

一次明确纠正 →（自动提取候选）→（用户确认）→ 写入 → 新会话遵循：

```
用户：帮我规划一下明天要做的事
用户：不对。以后帮我规划的时候，必须先列出当天已有的固定日程，
      然后只排三个重点任务，不要一次列十几条。
```

- 事件序列：`skill_candidate_proposed` →（带 token 的 confirmation，门禁自动批准）→ `skill_candidate_applied`。
- 落库技能：`daily-planning-output-format` v0.1.0。
- 该规则进入全新会话的 system prompt。
- 两个全新会话都按新规则作答（命中 2/2，包含「固定日程」与「三个重点任务」）。

**这是 P4「一次纠正改变后续新会话行为」首次取得真实模型证据。**

## 门禁过程中发现并修复的严重缺陷（I25）

第一次运行学习门禁时，纠正轮**完全没有输出**，报错：

```
BadRequestError: 400 - Duplicate value for 'tool_call_id' of call_00_... in message[4]
```

根因：`_chat_openai` 中「分批 + 执行工具」的整段代码被错误地缩进在 `for tc in tool_calls:` 循环**内部**，
因此每处理一个工具调用就把此前累计的全部工具再处理一遍。事件流留下了明确指纹——工具结果按 1、2、3 累积重复：

```
tool_start list_todos     → tool_result list_todos
tool_start list_calendar  → tool_result list_todos   ← 重复
                             tool_result list_calendar
tool_start list_reminders → tool_result list_todos   ← 重复
```

后果有两条，都很严重：

1. **同一轮 N 个工具调用会被执行 1+2+…+N 次** → 重复业务写入（同一条待办被建多次）。
2. 同一个 `tool_call_id` 被重复追加进消息列表 → API 永久拒绝该会话，之后每一轮都失败。

这解释了为什么学习闭环此前完全跑不通：触发纠正的规划轮一调用多个工具，会话即刻损坏。

**该结构在参考实现中同样存在**（源文件 1688 行与 1687 行同为 16 空格缩进），因此是继承缺陷，不是移植引入的回归。

修复：把该段整体减少一级缩进，移到 `for tc in tool_calls:` 循环之后，使分批与执行每轮只发生一次。
新增 `tests/runtime/test_parallel_tool_calls.py`（3 项）锁定：三个并行工具各执行一次、tool 消息 id 唯一且与调用一一对应、两个工具只产生两条结果事件。
变异校验：把缩进改回去，3 项全部失败；恢复后全部通过。

## 仍未取得真实证据的部分

- 主动问候与每日回顾（P6）尚未实现，无门禁。
- 对照评测（P5，关闭 Skill / 固定 Skill / 学习后 Skill 三条件）尚未运行。
- 「习惯影响行为」的抽样命中率为 1/2 与 2/2，样本量小，只用于确认方向，不作为效果量指标。
