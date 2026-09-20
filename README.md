<div align="center">

<a id="top"></a>

<img src="frontend/public/runtime/themes/mint-emblem.webp" width="180" alt="MellowDay 薄荷绿植物标识">

# MellowDay

**慢慢过日子，也好好记得你。**

面向个人生活与事务管理的智能助理，将聊天、待办、日历、提醒与笔记放在一起，<br>
结合长期事实记忆与可学习、可版本化的工作流程。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![Vue 3](https://img.shields.io/badge/Vue-3-4FC08D?style=flat-square&logo=vuedotjs&logoColor=white)](frontend/package.json)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](pyproject.toml)
[![Docker Compose](https://img.shields.io/badge/Deploy-Docker_Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](docker-compose.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-6B7280?style=flat-square)](LICENSE)

[功能一览](#features) · [快速开始](#quick-start) · [配置说明](#configuration) · [测试与验收](#validation) · [项目架构](#architecture) · [文档导航](#documentation)

</div>

---

<a id="features"></a>

## ✨ 功能一览

聊天是主入口；人格、记忆、Skills、事务记录与模型管理集中在「设置」子菜单。固定日历按钮与聊天工具均可唤起侧边日历。

| 能力 | 当前支持 |
| :--- | :--- |
| 💬 对话与事务 | 通过聊天管理待办、日历、提醒和笔记，支持模型工具循环、上下文折叠、完整执行记录与会话恢复。 |
| 🎭 人格设置 | 单一角色，可编辑核心人格与说话示例；表达规则按当前对话证据小幅更新，支持暂停、锁定、撤销和重置。 |
| 🧠 事实记忆 | 每个当前用户轮次仅评估一次；明确要求保存的对应事实可直接写入，自动候选与冲突更新需要确认。 |
| 📅 侧边日历 | 基于 FullCalendar，提供月、周、日视图，支持区间、全天、时区、每日／每周／工作日重复，以及单次或系列编辑。 |
| 🔔 提醒与订阅 | 后端持久投递明确提醒与主动订阅的当天日程汇报；网页关闭后仍积累未读，重新打开即可查看。 |
| 🧩 工作流程 Skills | 提供可编辑的内置日程 Skill，保留技能检索、演化与版本管理；定时汇报使用只读日程模板。 |

### 当前边界

- **人格与记忆**：不会自动改写核心身份或关系，不挖掘历史记忆；在设置中删除或修改的记忆，不从旧轮次恢复。人格演化与记忆筛选依赖模型判断，边界与证据检查不等于长期语义正确性保证。聊天完成后会有独立评估调用。
- **提醒与汇报**：没有系统推送。停机恢复时合并过期提醒，订阅只补最近一期。订阅频率支持每天、每周、工作日，内容目前为投递当天日程，尚非自定义主题或整周汇总。
- **Skills 与产品范围**：当前检索仅注入候选描述，完整规则正文投递尚待补齐。网页产品禁用 MCP、Plan Mode 与产品子代理入口；不提供主动问候、独立今日概览或每日回顾页面。

<a id="quick-start"></a>

## 🚀 快速开始

### Docker 部署（推荐）

准备 Docker Desktop Linux 容器引擎和 **Docker Compose 2.24+**，在仓库根目录执行：

```bash
# 首次使用时复制配置文件；已有 .env 请保留
cp -n .env.docker.example .env
# 编辑 .env，填入 MELLOWDAY_API_KEY

docker compose up -d --build --wait
docker compose ps
```

<details>
<summary>🪟 Windows PowerShell 命令</summary>

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.docker.example .env }
# 编辑 .env，填入 MELLOWDAY_API_KEY

docker compose up -d --build --wait
docker compose ps
```

</details>

等到服务状态显示 `healthy`，浏览器打开 **[http://127.0.0.1:8021](http://127.0.0.1:8021)**。

| 部署要点 | 说明 |
| :--- | :--- |
| 数据持久化 | 数据存放在命名卷 `mellowday-data`，普通停止不删除卷。 |
| 模型凭据 | 镜像内不含任何凭据，密钥只在运行时注入。 |
| 访问范围 | 端口默认只绑定回环地址，应用自身没有鉴权。 |
| 旧版本升级 | 旧单容器用户先按[升级步骤](docs/deployment.md#从旧单容器版本切换)备份并停止旧 `web`，再切换。 |

> [!IMPORTANT]
> 容器默认时区为 `Asia/Shanghai`。助手按容器时钟解析「明天上午九点」这类相对时间：若使用 UTC，可能存为 `09:00Z`，UTC+8 的用户将看到 17:00。需要其他时区时，在 `.env` 中设置 `TZ=Europe/Berlin` 等时区，再运行 `docker compose up -d`。

完整部署、升级与故障定位说明见[部署文档](docs/deployment.md)。

### 本地 Python 运行

需要 **Python 3.11+**：

```bash
python -m pip install -e .
cp -n .env.example .env
# 编辑 .env 填入模型凭据，或直接设置环境变量
python -m mellowday.web_app --port 8021
```

浏览器打开 [http://127.0.0.1:8021](http://127.0.0.1:8021)，可使用原静态兼容入口。无模型配置仍可管理记录。

> [!NOTE]
> 新 Vue 前端的开发方式见[开发与 Python 单独运行](docs/deployment.md#开发与-python-单独运行)。前端开发需要 Node.js 22.12.0+；仅运行 Python 不需要 Node.js。PowerShell 中复制配置文件请使用上方的 `Test-Path` / `Copy-Item` 写法，并将源文件改为 `.env.example`。

<a id="configuration"></a>

## ⚙️ 配置说明

| 变量 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `MELLOWDAY_API_KEY` | 模型凭据，聊天时必填 | 空 |
| `MELLOWDAY_API_BASE` | OpenAI 兼容接口地址 | `https://api.deepseek.com` |
| `MELLOWDAY_MODEL` | 模型标识 | `deepseek-v4-pro` |
| `MELLOWDAY_DATA_DIR` | 会话、技能、记忆与数据库的存放目录 | `./data` |

模型配置也可以在网页「设置」中保存，接口不会回显密钥。Docker Compose 内的数据目录固定为 `/app/data`，由命名卷持久化；更多容器配置见[端口、时区与持久化](docs/deployment.md#端口时区与持久化)。

<a id="validation"></a>

## 🧪 测试与验收

### 离线测试

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

以上为 Python 离线测试：模型侧使用脚本化的假客户端，不发起网络请求，也不代表真实模型已通过。前端检查与浏览器验收见[部署文档 · 验收](docs/deployment.md#验收)。

### 真实模型验收

配置模型凭据后执行：

```bash
python scripts/smoke_chat.py "帮我把明晚七点复习加入待办"
```

该脚本逐条打印结构化事件，包括回复增量、工具调用、工具结果与错误，用于人工确认流式回复与一次真实工具调用的落库结果。

<a id="architecture"></a>

## 🏗️ 项目架构

`frontend/` 负责 Vue 页面、主题、POST SSE 与管理交互。Nginx 同源转发 `/api`，Python 负责模型、工具、学习、确认和持久化。日程通过聊天与侧边日历展示，调度循环独立于浏览器生命周期。

```text
浏览器 · Vue 3
      │
      ▼
Nginx · 静态资源与 /api 同源转发
      │
      ▼
FastAPI · 对话运行时 / 工具 / 人格 / 记忆 / Skills / 调度
      │
      ▼
持久化 · SQLite / 会话 / 技能目录
```

### 目录结构

```text
frontend/                          Vue 前端、主题与管理交互
src/mellowday/
  runtime/                         对话运行时
    agent.py                       主循环、工具调度、压缩流水线
    events.py                      结构化事件桥（ContextVar，会话间不串流）
    tools.py                       内置工具集与权限判定
    prompt.py                      个人助理系统提示词
    memory.py                      事实记忆索引与召回
    sessions.py, session_memory.py  会话持久化与折叠摘要
    skills/                        Skills 发现、检索、演化、版本与评测
  personal_assistant/               人格、记忆、事务、日历与调度
  storage/                         SQLite 事务存储与一次性撤销
  web_app/                         FastAPI 服务、事件流、会话注册表、静态界面
tests/                             离线测试
evals/                             三条件对照评测（开发／保留案例）
docs/                              部署、升级与故障定位文档
```

### 数据如何组织

三类持久信息彼此独立：

| 信息类型 | 内容与管理方式 |
| :--- | :--- |
| 🧠 用户事实 | 结构化事实，可修改、可删除。 |
| 🧩 工作流程 Skill | 可检索指令，带版本与反馈证据。 |
| 📝 事务记录 | 待办、日历、提醒与笔记。 |

会话摘要属于会话状态，不会自动升级为永久事实。

<a id="documentation"></a>

## 📚 文档导航

| 文档 | 内容 |
| :--- | :--- |
| [文档索引](docs/README.md) | 项目文档入口。 |
| [部署与升级](docs/deployment.md) | Docker 部署、本地开发、数据持久化、升级与故障定位。 |
| [对照评测用法](evals/README.md) | 三条件对照评测的运行与结果说明。 |
| [素材来源与授权](ASSET_SOURCES.md) | 项目使用的素材及其授权信息。 |

## 📄 开源许可

本项目采用 [MIT License](LICENSE)。素材来源与授权另见 [ASSET_SOURCES.md](ASSET_SOURCES.md)。

---

<div align="center">

[返回顶部 ↑](#top)

</div>
