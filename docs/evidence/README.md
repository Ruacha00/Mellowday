# 验证证据

最新增量：[前端动效与流畅度](MOTION-acceptance.md)。40 项前端回归、9 组既有浏览器流程、5 组动效专项检查通过；4 倍 CPU 降速的实测数据与限制单独记录。

## 当前版本：Vue 前端与双容器交付（2026-09-19）

当前前端/部署结论见 [FD 验收报告](FD-acceptance.md)：后端 542 项、前端 40 项，浏览器 9 组主流程加 4 组边界验证、Nginx 长流/断开、卷恢复与上一版回退均有新证据。日常 8021 已切换至 frontend + api，并保留原卷和本地完整备份。下述 R4 是既有运行时证据，不替代本轮 Vue 验收。

## 既有运行时：第四轮整改（2026-09-19）

当前版本应用验收已完成：离线 **541/0**，真实运行时 **19/19**、核心演示 **24/24**；本轮显式迁移学习门禁已有 **25/25**。P5 三臂同指纹、同配置，各 **9/9** 测量完整性检查，样本表现逐格报告。最新结论见 [R4 应用验收](R4-acceptance.md)；下方第三轮材料保留为历史证据。


本目录保存可复核的实施证据。每份证据包含：执行时间、命令、原始输出摘要、结论与未完成项。

规则：
- 离线测试只证明离线结论；凡涉及真实模型的结论必须注明模型标识、运行编号与工作区指纹。
- 指标必须写明分母；抽样只用于确认方向，不作为效果量。
- 不记录任何来源项目名称；凭据不得进入任何报告。
- **失败与反例一律保留**，不得为了让表格好看而删除或放宽判据。

## 按阶段索引

| 证据 | 内容 | 级别 |
|---|---|---|
| [`FD-acceptance.md`](FD-acceptance.md) | Vue、双容器、当前真实模型冒烟、备份恢复与回退 | 按项列明 |
| [`R4-acceptance.md`](R4-acceptance.md) | 当前运行时、核心演示、P5、浏览器与安装验收汇总 | 按项列明 |
| [`P1-real-model.md`](P1-real-model.md) | P1 真实模型门禁：对话、流式、工具落库、跨会话读回、事实召回、错误收敛 | L3 |
| [`P1-runtime-loop.md`](P1-runtime-loop.md) | P1 离线端到端与服务进程冒烟 | L2 |
| [`P3-P4-core-demo.md`](P3-P4-core-demo.md) | **核心演示定稿**（t23 权威运行、逐行分母、第 9 节含三问回答与口径修复表） | L3 |
| [`P5-minimal-comparison.md`](P5-minimal-comparison.md) | 最小 P5 对照：关闭/固定/学习后三条件、六格分母、不宣称提升比例 | L2（小样本） |
| [`T25-final-review.md`](T25-final-review.md) | **终局独立复核（pass）**：自己重跑、自己核对数据库与调用日志、自己重算六格 | L3 |
| [`T18-independent-review-round3.md`](T18-independent-review-round3.md) | 第三轮独立复核（needs_revision）：N4/N5/N6 的来源 | L3 |
| [`T14-independent-review-round2.md`](T14-independent-review-round2.md) | 第二轮独立复核（needs_revision）：N1/N2/N3 的来源 | L3 |
| [`T6-independent-review.md`](T6-independent-review.md) | 首次独立复核（needs_revision）：F1–F4 的来源 | L3 |
| [`P3-P4-l3-gate.md`](P3-P4-l3-gate.md) | ⚠️ **部分结论已作废**（顶部已标注）：当时的停用侧结论只验证技能通道，属假阳性 | — |
| [`P3-P4-l3-gate-method.md`](P3-P4-l3-gate-method.md) | 门禁 7 条方法问题 → 修正 → 验证 | — |
| [`I10-skills-retrieval-zh.md`](I10-skills-retrieval-zh.md) | 中文词项检索基线（Recall@1 6/6、误召回 1/7） | L1 |
| [`I04-I06-storage-tools.md`](I04-I06-storage-tools.md) | 存储与业务工具验证 | L1 |
| [`I21-browser/`](I21-browser/) | 管理页真实浏览器证据（含截图与脚本） | L2 |

原始报告（机器可读）在 [`raw/`](raw/)，其中 `code-*.json` 之外的文件名含义见下节。

## 门禁与报告的当前约定

- 门禁脚本：`scripts/gate_common.py`（隔离 / 脱敏 / 请求录制 / 判据）、`scripts/gate_l3.py`、`scripts/gate_l3_learning.py`、`scripts/demo_core.py`（含 `--selfcheck`）。
- 稳定文件名的报告（`raw/gate-l3-report.json`、`raw/gate-l3-learning-report.json`、`raw/core-demo-report.json`、`raw/p5-comparison-report.json`）含义是「最近一次运行」；
  每次运行的不可变副本、原始请求/响应与**隔离数据目录**在 `output/gate-runs/<gate>/<run-id>/`（gitignored）。
- 退出码：0 全部通过；1 有失败或无法判定；2 表示 L3 部分**没有运行**（无凭据或 `--offline`），此时模型相关检查为 `pending` 并写明原因。
- **工作区指纹**：报告记录运行起止的指纹。指纹不同或运行期间有文件变更时，该检查判 `inconclusive`，跨臂对照不得作为结论。
- **判据自身的负向对照**：`python scripts/demo_core.py --selfcheck`（无需模型）必须通过，否则测量工具不可信。

## 尚未纳入证据面（如实记录）

- 长结果经 ref 的 HTTP 取回（功能有测试与真实进程证据，但未进核心演示 / P5）。
- 更大样本的 P5 对照；判据收紧后需重测（会改变分母）。
- P6 每日回顾与主动问候：本轮范围明确不含。
