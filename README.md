# MellowDay

面向个人生活与事务管理的智能助理：聊天、待办、日历、提醒、笔记，加上长期事实记忆与可学习、可版本化的工作流程。

## 当前状态

当前产品范围以 [S18](docs/specs/S18-chat-first-product-scope.md) 为准，技术规格分为 [人格](docs/specs/S19-persona-adaptation.md)、[本轮记忆](docs/specs/S20-current-turn-memory.md)、[日历与消息](docs/specs/S21-calendar-delivery.md)、[聊天界面](docs/specs/S22-chat-first-interface.md)。实施依赖见[原子任务板](docs/issues/CHAT-FIRST-BOARD.md)。旧验收报告保留历史结论，不代表当前范围。

- 聊天为主入口；人格、记忆、Skills、事务记录与模型管理集中在设置子菜单。固定日历按钮与聊天工具可唤起侧边日历。
- 单一角色：用户编辑核心人格及说话示例；可变表达规则按当前对话证据小幅更新，支持暂停、锁定、撤销和重置。不会自动改写核心身份或关系。
- 记忆仅评估当前用户轮次一次，不挖掘历史。明确要求保存对应事实可直接写入；自动候选与冲突更新需要确认。在设置中删除或修改后，不从旧轮次恢复。
- FullCalendar 提供月、周、日视图，支持区间、全天、时区、每日/每周/工作日重复，以及单次或系列编辑。
- 后端持久投递明确提醒与主动订阅的当天日程汇报；网页关闭后仍积累未读，重新打开可查看。停机恢复合并过期提醒，订阅只补最近一期；没有系统推送。
- 提供可编辑的内置日程 Skill；当前检索仅注入候选描述，完整规则正文投递尚待补齐。定时汇报使用只读日程模板。订阅频率支持每天、每周、工作日，内容目前为投递当天日程，尚非自定义主题或整周汇总。
- 保留模型工具循环、技能检索及演化、上下文折叠、完整执行记录、会话恢复。网页产品禁用 MCP、Plan Mode 与产品子代理入口。

无需主动问候、独立今日概览或每日回顾页面。人格演化与记忆筛选依赖模型判断，边界与证据检查不等于长期语义正确性保证。聊天完成后会有独立评估调用。

此前动效和历史部署证据见 [docs/evidence](docs/evidence/README.md)；本轮交付见[聊天优先验收](docs/evidence/CF-acceptance.md)。

## 运行

### Docker（推荐）

```bash
cp .env.docker.example .env   # 填入 MELLOWDAY_API_KEY
docker compose up -d --build --wait
docker compose ps             # 等到 STATUS 显示 (healthy)
```

浏览器打开 http://127.0.0.1:8021 。数据存放在命名卷 `mellowday-data`，普通停止不删除卷。旧单容器用户先按[升级步骤](docs/deployment.md#从旧单容器版本切换)备份并停止旧 web，再切换。
镜像内不含任何凭据，密钥只在运行时注入；端口默认只绑定回环地址（应用自身没有鉴权）。
**时区**：容器默认 `TZ=Asia/Shanghai`。助手按容器时钟解析「明天上午九点」这类相对时间，用 UTC 会把它存成 09:00Z，UTC+8 的用户会看到 17:00。换时区用 `TZ=Europe/Berlin docker compose up -d`。
完整说明见 [部署文档](docs/deployment.md)。

### 本地 Python

```bash
python -m pip install -e .
cp .env.example .env        # 填入模型凭据，或直接设置环境变量
python -m mellowday.web_app --port 8021
```

浏览器打开 http://127.0.0.1:8021 可使用原静态兼容入口。新 Vue 前端开发方式见[部署文档](docs/deployment.md#开发与-python-单独运行)。无模型配置仍可管理记录。

### 配置

| 变量 | 说明 | 默认 |
|---|---|---|
| `MELLOWDAY_API_KEY` | 模型凭据（必填才能聊天） | 空 |
| `MELLOWDAY_API_BASE` | OpenAI 兼容接口地址 | `https://api.deepseek.com` |
| `MELLOWDAY_MODEL` | 模型标识 | `deepseek-v4-pro` |
| `MELLOWDAY_DATA_DIR` | 会话、技能、记忆与数据库的存放目录 | `./data` |

也可以在网页「设置」中保存，接口不会回显密钥。

### 真实模型验收

```bash
python scripts/smoke_chat.py "帮我把明晚七点复习加入待办"
```

该脚本逐条打印结构化事件（回复增量、工具调用、工具结果、错误），用于人工确认流式回复与一次真实工具调用的落库结果。

## 测试

```bash
python -m pytest -q
```

全部为离线测试：模型侧使用脚本化的假客户端，不发起网络请求，也不代表真实模型已通过。

## 架构

`frontend/` 负责 Vue 页面、主题、POST SSE 与管理交互。Nginx 同源转发 `/api`，Python 负责模型、工具、学习、确认和持久化。日程通过聊天与侧边日历展示，调度循环独立于浏览器生命周期。

```text
src/mellowday/
  runtime/                         对话运行时
    agent.py                       主循环、工具调度、压缩流水线
    events.py                      结构化事件桥（ContextVar，会话间不串流）
    tools.py                       内置工具集与权限判定
    prompt.py                      个人助理系统提示词
    memory.py                      事实记忆索引与召回
    sessions.py, session_memory.py 会话持久化与折叠摘要
    skills/                        Skills 发现、检索、演化、版本与评测
  personal_assistant/              人格、记忆、事务、日历与调度
  storage/                         SQLite 事务存储与一次性撤销
  web_app/                         FastAPI 服务、事件流、会话注册表、静态界面
tests/                             离线测试
evals/                             三条件对照评测（开发/保留案例）
```

三类持久信息彼此独立：**用户事实**（结构化，可改可删）、**工作流程 Skill**（可检索指令，带版本与反馈证据）、**事务记录**（待办/日历/提醒/笔记）。会话摘要属于会话状态，不会自动升级为永久事实。

## 文档

- [Wiki 总览与阅读导航](docs/wiki/README.md)
- [架构设计](docs/wiki/架构设计.md) · [源码阅读](docs/wiki/核心源码阅读指南.md) · [Skills 学习机制](docs/wiki/Skills自进化逻辑与实现思路.md)

- [重构实施计划](IMPLEMENTATION_PLAN.md)
- [阶段与 Spec 索引](docs/specs/README.md)
- [接口契约](docs/specs/CONTRACTS.md)
- [原子任务板](docs/issues/BOARD.md)
- [验证证据](docs/evidence/README.md)
