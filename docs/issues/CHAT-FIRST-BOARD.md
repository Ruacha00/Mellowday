# 聊天优先交付任务板

主规格 S18；技术规格 S19–S22。状态随验证更新，未完成项不得标已交付。

|Issue|原子成果|依赖|负责人|状态|
|---|---|---|---|---|
|CF01|规格与接口冻结、文件归属|无|主 agent|完成|
|CF02|核心示例与可变人格存储/版本|CF01|人格 agent|完成|
|CF03|候选演化、检索、边界与管理 API|CF02|人格 agent|完成|
|CF04|本轮记忆候选、状态与幂等|CF01|主 agent|完成|
|CF05|记忆写入授权及 Skill 授权集成|CF04|主 agent|完成|
|CF06|日历区间、重复及实例例外|CF01|日程 agent|完成|
|CF07|持久提醒/订阅及调度生命周期|CF06|日程 agent|完成|
|CF08|聊天主导航与集中设置|CF01|前端 agent|完成|
|CF09|日历、通知、人格管理界面|CF03,CF07,CF08（接口先行）|前端 agent|完成|
|CF10|运行时接线、禁用 MCP/Plan/产品子代理入口|CF03,CF05,CF07|主 agent|完成|
|CF11|跨模块回归与浏览器验收|CF09,CF10|主 agent+独立审查|完成|
|CF12|备份、容器更新、最终验收、提交推送|CF11|主 agent|完成|

并行：CF02/CF04/CF06/CF08 同时推进。app.py、service.py、runtime/agent.py 和旧业务 tools.py 只有主 agent 修改，其他代理提供独立模块。禁止子代理继续派生、禁止共享环境部署和 git 提交；完成时回报文件、接口、测试、限制。每个负责人把中断恢复所需事实留在本地 checkpoint，不反复扩大范围。

## 验收与依赖依据

|Issue|可独立验收的完成条件|验证位置|
|---|---|---|
|CF01|S18 范围及 S19–S22 接口、写入归属明确|本任务板及对应规格|
|CF02|核心示例兼容旧配置，可变规则独立版本化|test_persona_adaptation.py|
|CF03|有证据、额度、核心冲突检查，暂停/锁定/撤销/重置生效|test_persona_registry_integration.py|
|CF04|仅本轮提取，同轮不重复，删除后不重建|test_turn_memory.py|
|CF05|候选级显式授权、自动候选确认、完整 Skill 变更授权|test_turn_memory.py / test_product_scope.py|
|CF06|旧记录可见、区间交叠、重复与单次例外|test_calendar_schedule.py|
|CF07|独立调度、重启防重、持久未读、删除接收会话暂停|test_calendar_schedule.py / test_product_scope.py|
|CF08|聊天与设置主导航、管理子菜单、旧入口重定向|frontend/tests/chat-first.test.ts|
|CF09|侧边日历 CRUD、订阅、人格控件、通知详情跳转|frontend/tests/browser/acceptance.py|
|CF10|实际运行时接线，执行入口拒绝产品禁用能力|test_product_scope.py / test_persona_registry_integration.py|
|CF11|后端及前端回归通过，真实 HTTP 浏览器无异常|docs/evidence/CF-acceptance.md|
|CF12|原卷完整备份、旧镜像保留、8021 健康、现有分支推送|docs/evidence/CF-acceptance.md|

当前交付范围不含自定义主题汇报、整周汇总、系统推送；模板汇报内容为投递当天日程。模型语义判断仍需更长期评估，不将离线门禁视作真实模型质量保证。
