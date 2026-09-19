# S09 对话、学习反馈与历史

前置：S08 公共 HTTP/types；后端不新增业务协议。Module 覆盖整个轮次而不是单页生命周期。

验收：

- POST SSE 正确处理 UTF-8 分片、多事件、CRLF、尾部和协议错误；只在 `done` 后结束成功，异常 EOF 明确显示中断且不自动重发。
- `turn_end` 后继续展示学习与确认；候选提出/应用/拒绝/失败/跳过可见。仅带有效 id 的 Web confirmation 可操作；session 绑定，单次提交，accepted:false 不显示执行成功。
- 流归属单个 session，导航离开对话页不关闭流；活动时不能切换/新建/删除 session。停止与断开正确关闭 reader；错误后可继续使用。
- IME Enter 不发送，空输入不发送，发送后流式渲染 Markdown、工具事件与错误。
- 会话列表、载入、删除、继续；历史同时可查消息与原始执行过程。折叠后的模型上下文不替代原历史。
- ref 只从结构化字段取得；分页拼接、搜索/重置、收起/重开、过期响应、删除后错误与跨会话隔离均有行为验证。

文件归属：`frontend/src/conversation/`、`history/`、`api/sse.ts`、对应测试。不得修改运行时、公共 types/http、shell、依赖锁文件。旧式文本匹配检查仍只代表兼容页。
