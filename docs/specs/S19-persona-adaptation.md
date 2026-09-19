# S19 核心人格与有界适应

上位范围 S18。保持六字段核心 API 兼容，新增 examples 字段（旧文档缺省为空），核心更新下一轮生效。可变人格使用独立持久存储、全局版本及来源记录；更新器只能提交场景、行为、示例，不能写核心字段。条目上限、每轮/每日更新上限及核心版本检查形成结构性边界，语义判定辅以拒绝身份、事实、任务权限变化的模型判断，不声称绝对语义保证。

后台只使用有依据的用户反馈提取候选；显式长期反馈或多轮独立支持可自动应用，不请求批准；临时要求和助手自产证据不能持久化。无候选正常结束。每轮按相关性选择少量有效条目，不全量注入。暂停、锁定、撤销、重置必须真实持久化；撤销抑制同一候选重学。核心修改后重评/停用旧核心下的自动条目，锁定冲突也不能覆盖新核心。

接口：GET /api/persona/adaptation → {paused,version,rules,history}；PUT 同路径 {paused}；POST /api/persona/adaptation/{id}/lock {locked}；POST /api/persona/adaptation/{id}/undo；POST /api/persona/adaptation/reset。核心仍 GET/PUT /api/persona。规则字段 id,scene,behavior,example,enabled,locked,source,created_at。只读空态不写坏文件。

后端负责人提供独立 router 与 async adapt_turn(session_id,turn_id,user_text,side_query)；根 agent 负责 Web 调用及运行时相关规则注入。测试覆盖持久化、幂等、来源、临时请求、预算、暂停锁定撤销、核心不可改。前端由 S22 实现。
