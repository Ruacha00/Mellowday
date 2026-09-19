# 前端与双容器交付 Spec 索引

2026-09-19，接续已验收运行时。方案：Vue 3 + TypeScript + Vite + Vue Router；同源 Nginx + FastAPI。旧产品实现可调整，业务事实、权限确认、学习、会话语义以当前后端契约为准。运行时保持现有实际源码主链，不另造 AgentCore；具体来源对应只存本地内部记录。

| Spec | 范围 | 依赖 | 验收责任 |
| --- | --- | --- | --- |
| [S08](S08-frontend-foundation.md) | 工程、主题、导航、可访问性 | 现有 CONTRACTS | 主 agent |
| [S09](S09-conversation-history.md) | POST SSE、轮次、确认、学习、历史/ref | S08 的公共 HTTP 契约 | 对话 agent，主 agent 集成 |
| [S10](S10-management.md) | 记录、今日、Skills、设置 | S08 的公共 HTTP 契约 | 主 agent 实现，对话 agent 独立复核 |
| [S11](S11-container-delivery.md) | 双镜像、同源代理、持久化 | S08 构建；流测试依赖 S09 | 主 agent 实现，审计 agent 核对镜像边界 |
| [S12](S12-acceptance.md) | 行为、视觉、代理、升级回退证据 | S09、S10、S11 | 主 agent |

任务拆分及先后次序见 [原子任务板](../issues/FRONTEND-BOARD.md)。旧 S01–S07 证据保持原意，本轮新结果单独记录。P6 功能不包含在本轮。

S08–S12 已实施并验收，结果见 [FD 验收报告](../evidence/FD-acceptance.md)。最终复核补充 FD17–FD20：配置上限清空、状态大小写、最近会话导航归属和 Skills 刷新竞态；均由独立的行为测试验证。

## 公共前端接口（并行实现时冻结）

- `src/api/http.ts`：`requestJson<T>(path: string, init?: RequestInit): Promise<T>`，path 使用完整 `/api/...`；HTTP 非 2xx 或 `{ok:false}` 抛出可读 `ApiError`，不重试 mutation。
- `src/api/types.ts`：共享 `RecordKind`、`LifeRecord`、`SessionSummary`、`SessionDetail`、`TraceEntry`、`RuntimeEvent`、`ModelConfig`；可选字段保留，不臆造后端字段。
- `conversation/useConversation.ts`：导出 `useConversation()` 单例 composable；至少返回 refs `sessionId`、`sessions`、`busy`、`pendingConfirmation`、`error`，方法 `refreshSessions()`、`selectSession(id)`、`newSession()`；供 shell 显示最近会话和全局运行提示。其余 Interface 由对话模块封装。`busy` 时禁止换会话/删除。
- 路由页面均为默认导出的 Vue SFC：`conversation/ConversationPage.vue`、`history/HistoryPage.vue`、`records/RecordsPage.vue`（prop `kind: RecordKind`）、`today/TodayPage.vue`、`skills/SkillsPage.vue`、`settings/ModelSettingsPage.vue`、`settings/DiagnosticsPage.vue`。外观页面归主 agent。
- 共用视觉类：`page-stack`、`panel`、`page-heading`、`eyebrow`、`muted`、`notice`/`notice.error`、`button`/`button.primary`/`button.danger`、`field`、`form-grid`、`empty-state`、`row-actions`、`badge`。页面可有 scoped CSS，但不编辑全局主题。
- CSS token：`--bg`、`--surface`、`--surface-strong`、`--ink`、`--ink-muted`、`--accent`、`--accent-strong`、`--on-accent`、`--border`、`--focus`、`--line`；使用 inherit 字体。
- 所有 API 页面需要 loading/empty/error/success，失败不丢草稿；所有请求归属当前页面或会话，异步过期响应不得覆盖新状态。

## 协作与恢复规则

最多三个子 agent；同一文件只由一人写；禁止子 agent 递归派生、切分支、提交、推送、编辑参考目录或真实数据。发现公共契约缺口先通知主 agent。每批自行运行针对性检查，返回文件列表、验证、剩余问题。相同失败最多两轮修正，之后交主 agent 定位根因；不得通过降级断言无限重试。

压缩后先读本索引、任务板、CONTRACTS 与 `.local-planning/checkpoints/frontend-rollout.md`，再检查 git status 和 live agents。以磁盘文件、实际测试输出和 agent 状态为准，不重复派发已完成任务。真实模型、卷迁移、整体集成由主 agent 串行执行。

## 集成裁决

停止当前轮次通过取消该 POST/reader，让服务端按连接回收对应任务；不额外发送延迟的 session 级 abort，以免取消随后开始的新一轮。设置页明确发送 `max_turns:null` 可清除先前限制，空密钥仍表示保留。
