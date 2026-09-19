# S21 日历区间与持久定时消息

上位范围 S18。SQLite 持久存储区间事件、重复规则、订阅与投递实例，保留旧 records 数据并适配旧日历/提醒。事件包含 id,title,detail,start_at,end_at,all_day,timezone,recurrence(none/daily/weekly/weekdays),reminder_minutes,status；时区显式，重复按当地墙钟，查询按区间交叠。支持单次及整个系列编辑/取消，例外不影响其他实例。

接口：GET /api/calendar/events?start=&end= → {events}；POST /api/calendar/events；PUT/DELETE /api/calendar/events/{id}，重复实例可带 occurrence_start 与 scope=single/series。GET/POST /api/calendar/subscriptions，PUT/DELETE /api/calendar/subscriptions/{id}；订阅字段 title,time,timezone,recurrence,weekday(0=周一),session_id,enabled。GET /api/calendar/notifications → {notifications}；POST /api/calendar/notifications/{id}/read。通知 id,kind,title,body,event_id,session_id,scheduled_at,created_at,read。

后端循环独立于网页；持久实例唯一键防重，发送前复核取消/改期。重启补发过期事项摘要、订阅只生成最近一期。事项模板可靠回退；汇报只读查询事实化正文，可由受限 Skill 格式化，不允许新增写动作。模型失败不能捏造完成，保留可诊断状态。接收会话删除暂停订阅，不能复活会话。

负责人独占新增 schedule*.py/calendar*.py 及对应 tests；提供 router、start/stop 生命周期及 tool_definitions/execute 接口，不编辑 app.py/service.py/旧 tools.py。根 agent 集成；与前端负责人直接对齐接口变化。测试用受控时钟验证区间、重复、单次例外、重启幂等、暂停、取消及旧数据可见。
