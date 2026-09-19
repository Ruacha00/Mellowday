# MellowDay

面向个人生活与事务管理的智能助理：聊天、待办、日历、提醒、笔记，加上长期事实记忆与可学习、可版本化的工作流程。

## 当前状态

前端已加入页面淡入、抽屉滑动、控件反馈和回复等待动效，支持系统减少动态效果；本机 4 倍 CPU 降速实测帧间隔 P95 为 16.8ms，范围与限制见[动效验收](docs/evidence/MOTION-acceptance.md)。

新增 Vue 3 / TypeScript / Vite 前端，恢复五种主题与对话、今日、生活、记忆、设置导航，接入现有运行时。Compose 分为 frontend 与 api 两个容器，继续使用原数据卷。当前后端 542 项、前端 40 项离线测试通过，浏览器、真实容器与备份回退均已验收。见[专项 Spec](docs/specs/FRONTEND-ROLLOUT.md)、[原子任务板](docs/issues/FRONTEND-BOARD.md)及[前端部署验收](docs/evidence/FD-acceptance.md)。

此前第四轮完成应用验收：541 项离线测试通过，真实运行时门禁 19/19、核心演示 24/24；显式迁移学习门禁已有 25/25 证据。P5 三条件对照已在相同代码与模型配置下重跑，结果及限制见[运行时验收报告](docs/evidence/R4-acceptance.md)。Docker 独立容器验收 17/17、Wheel 安装式运行 7/7 通过。完整技术栈支持
「自然语言 → 模型 → 工具调用 → 数据库 → 流式回复」，并支持从用户纠正中学习可复用的工作习惯。

已实现：

- 对话运行时：流式回复、工具调度、回合上限、重试退避、错误收敛、会话隔离与恢复；断流后正确回收，同一会话严格串行。
- 上下文管理：工具结果预算、超长结果落盘、折叠摘要与恢复；**原始执行记录完整保存**（含工具调用与结果），折叠与重启都不覆盖它。
- 个人事务工具：待办、日历事件、提醒、笔记的查询与增删改；状态词有别名与结构化校验，不会静默返回空集。
- 事实记忆：**SQLite 为唯一来源**，每轮对话自动召回；事实更新/删除后不再作为当前值注入；
  事实仅在技能提案明确列出来源记录并获确认后迁移；相关的事实前提继续保留，不按文字相似度自动取代。
- 工作流程 Skills：中文词项检索、加载、演化与版本；可查看规则正文、编辑、停用/恢复、回退版本。
- 学习闭环：用户明确纠正 → 提取候选 → 确认 → 落盘；一次性要求不会被学习；
  候选由模型决定新增、合并或丢弃；合并保留未被逐字声明取代的旧规则；写入被拒绝或跳过时界面可见。
- 网页入口：流式对话、事务管理页（编辑/完成/撤销/本地时间）、习惯管理页、模型设置、历史会话
  （可查看工具调用、结果与错误，长结果可经引用分页取回原文）。

人格与陪伴：在「设置 → 人格与陪伴」管理称呼、性格、说话方式和交流边界，保存后从下一轮回复生效。配置独立保存在本地 `persona.json`，聊天和技能学习没有人格写入工具。人格不改变工具权限或管理数据。详见 [S13](docs/specs/S13-persona-companionship.md) 与[产品任务板](docs/issues/PRODUCT-CORE-BOARD.md)。

尚未实现（计划中）：

- P6：每日回顾与主动问候的可配置节流（本轮范围明确不含）。
- 更大样本的对照评测；长结果 ref 分页与重新展开已取得真实浏览器证据，尚未纳入 P5 业务指标。

验收证据见 [docs/evidence](docs/evidence/README.md)，逐项级别与已知限制见
[任务板](docs/issues/BOARD.md) 与 [实施计划](IMPLEMENTATION_PLAN.md) 的定位表。
仓库内的自动化测试仍全部是离线测试；真实模型结论一律标注运行编号与工作区指纹。

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

`frontend/` 负责 Vue 页面、主题、POST SSE 与管理交互。Nginx 同源转发 `/api`，Python 负责模型、工具、学习、确认和持久化。今日页只派生已有记录，不等同于 P6 每日回顾或主动通知。

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
  personal_assistant/              业务工具层（21 个工具）
  storage/                         SQLite 事务存储与一次性撤销
  web_app/                         FastAPI 服务、事件流、会话注册表、静态界面
tests/                             离线测试
evals/                             三条件对照评测（开发/保留案例）
```

三类持久信息彼此独立：**用户事实**（结构化，可改可删）、**工作流程 Skill**（可检索指令，带版本与反馈证据）、**事务记录**（待办/日历/提醒/笔记）。会话摘要属于会话状态，不会自动升级为永久事实。

## 文档

- [重构实施计划](IMPLEMENTATION_PLAN.md)
- [阶段与 Spec 索引](docs/specs/README.md)
- [接口契约](docs/specs/CONTRACTS.md)
- [原子任务板](docs/issues/BOARD.md)
- [验证证据](docs/evidence/README.md)
