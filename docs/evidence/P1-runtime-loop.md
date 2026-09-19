# P1 运行时闭环验证证据

日期：2026-09-19　分支：refactor/mellowday-runtime

## 1. 离线端到端集成（真实运行时 + 脚本化模型传输）

命令：`python -m pytest tests/integration -q` → 5 passed

覆盖并证实：

1. 自然语言 → 真实 Agent 主循环 → `create_todo` 工具 → SQLite 落库：断言工具事件、回复增量与库中记录标题一致。
2. 工具结果回灌模型：断言同一轮内发生两次模型往返，第二次请求的 messages 中含 `role=tool` 且内容为 `ok=true` 的 JSON。
3. 流式回复：断言 `text_delta` 分片多于 1 个，拼接后与预期文本一致。
4. HTTP 全链路：`POST /api/chat` 返回 SSE 事件流，聊天创建的提醒可通过 `GET /api/records/reminders` 读到；`/api/health` 报告模型已配置；会话出现在 `/api/sessions`。
5. 参数校验：非法 `due_at` 返回 400 而非 500；未知记录类型返回 404。

## 2. 真实服务进程冒烟（无模型凭据）

`python -m mellowday.web_app --port 8021` 启动后实测：

| 请求 | 结果 |
|---|---|
| `GET /api/health` | 200，`{"ok":true,"app":"mellowday","model_configured":false}` |
| `GET /api/config` | 200，不含密钥，`api_key_hint` 为空 |
| `GET /` | 200，3078 字节，页面标识为 MellowDay |
| `GET /app.js` | 200，8912 字节 |
| `POST /api/records/notes` | 201/200，返回记录 id 与 operation_id |
| `GET /api/records/notes` | 读到 1 条 |
| `POST /api/chat`（未配置模型） | 200，事件流为 `error: model not configured` 后 `done`，请求正常收敛 |

## 3. 全量离线测试

命令：`python -m pytest -q` → **106 passed**

## 4. 未完成：真实模型门禁

状态：**未执行**。原因：本机环境未提供任何模型凭据（`MELLOWDAY_API_KEY`、`DEEPSEEK_API_KEY`、`OPENAI_API_KEY` 均未设置，仓库无 `.env`）。

因此以下 P1 验收项尚未取得真实证据，不得视为通过：

- 真实模型完成普通对话；
- 真实模型完成一次工具调用并正确落库；
- 真实模型参数错误时的错误收敛表现。

执行方式（配置凭据后）：

```
set MELLOWDAY_API_KEY=<key>
python scripts/smoke_chat.py "帮我把明晚七点复习加入待办"
```

预期：输出中出现 `tool_start` / `tool_result` 事件与流式 `text_delta`，且 `create_todo` 的记录可在管理页与 `GET /api/records/todos` 中查到。

## 5. 复核结论

- 端到端链路（自然语言 → 工具 → 数据库 → 界面）在离线可控条件下成立。
- 中文内容在存储、运行时事件与 HTTP 流之间字节级无损（已用十六进制比对确认）。
- 未配置凭据时聊天明确报错而非静默失败。
- 真实模型行为仍需凭据到位后验证。
