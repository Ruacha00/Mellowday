# S10 事务、记忆、Skills 与设置

输入：当前 `/api/records`、`skills`、`config`、`health`；输出：产品导航下可实际操作的管理页面。无后端支持的旧配置不伪装可用。

验收：

- todos/calendar/reminders/notes/memories 列表、搜索、新建、编辑、状态、删除与撤销闭环。状态取当前 Store 规则；字段清空有效，失败保留草稿，mutation 不自动重试，撤销冲突可读。
- 记忆 active/expired/deleted/superseded 和替代关系可见；任何恢复遵循后端限制，不绕过已取代事实检查。
- 今日按本地日期和有效状态汇总待办/日历/提醒，时区可见，空日期/完成记录处理明确；只读派生，不生成虚构卡片或自动模型摘要。
- Skills 列表、详情、人工修改、启停、版本原文和整版本恢复；停用编辑禁用；后端失败和无变化回执正确。
- 模型设置含自定义模型、base、thinking、max_turns；空密钥保留，提交后清空输入，只显示脱敏状态；以服务端有效配置为准，提示环境变量优先。
- 健康页展示真实状态，未配置模型不阻止管理；不冒充全局审计、人格设置、推送调度或多提供方注册功能。

文件归属：`frontend/src/records/`、`today/`、`skills/`、`settings/ModelSettingsPage.vue`、`settings/DiagnosticsPage.vue` 与测试；遵守公共接口和 CSS token。不编辑外观设置、shell 或公共包配置。
