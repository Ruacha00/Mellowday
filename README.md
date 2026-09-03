# Mellowday

[![Release checks](https://github.com/Ruacha00/mellowday/actions/workflows/release.yml/badge.svg?branch=main)](https://github.com/Ruacha00/mellowday/actions/workflows/release.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

> 慢慢过日子，也好好记得你。

Mellowday（悠日）是一个为单个用户设计的本地优先个人助手。它可以陪你聊天，也能管理任务、提醒、日程、笔记和长期记忆。应用数据保存在本地；需要模型推理时，由你选择并配置 Provider。

## 能做什么

- 按你设定的称呼和语气聊天，并保留聊天记录。
- 分开管理长期记忆、任务、提醒、日程和笔记，不会把普通聊天误作待办。
- 汇总当天的任务和日程，打开“今日”就能看到。
- 可以在合适的时间主动问候你，但不会借机修改任何记录。
- 模型服务、聊天人设、历史记录和运行状态都可以在设置页面管理。

## 可以这样用

- “明天下午三点提醒我交报告。”
- “记住我不吃香菜。”
- “下周三上午有个牙医预约，帮我记下来。”
- “我今天还有什么安排？”

## 当前状态

React/Vite Web App 已经是生产入口，浏览器自托管模式可以完整运行。计划中的 Windows Desktop Application、安装器和便携包尚未实现；当前版本不是最终的桌面交付物。

## 快速开始

源码运行需要：

- Python 3.12 或更高版本
- Node.js 22.12 或更高版本
- npm

在 Windows PowerShell 中执行：

```powershell
.\mellowday.ps1 start -Timezone Asia/Shanghai
```

首次启动会创建 `.venv`、安装依赖并构建前端。完成后打开 <http://127.0.0.1:8000/>，然后在 Settings 中配置模型 Provider。按 `Ctrl+C` 停止服务。

默认数据保存在 `%LOCALAPPDATA%\Mellowday`。如需指定位置：

```powershell
.\mellowday.ps1 start -Timezone Asia/Shanghai -DataDirectory D:\MellowdayData
```

## 开发与验证

更新源码或前端依赖后，重新准备本地环境：

```powershell
.\mellowday.ps1 setup
```

运行完整检查并在 `dist\` 中生成 wheel：

```powershell
.\mellowday.ps1 package
```

也可以分别运行各项检查：

```bash
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run check
npm --prefix frontend run build
python -m mypy src build_backend.py
python -m pytest -q
```

## 项目结构

| 模块 | 职责 |
| --- | --- |
| Agent Core | 模型循环、会话、扩展接口、权限、确认和运行时事件 |
| Personal Assistant | 聊天人设、长期记忆、生活记录、每日回顾和主动问候 |
| Web App | React 界面、FastAPI 后端、实时事件和本地管理功能 |
| Desktop Shell | 计划中的 Windows 主入口，负责窗口、托盘、通知和后台进程生命周期 |

仓库根目录中的实现可独立构建，不依赖只读的 `chatbot/` 参考树，也不包含 QQ/OneBot 适配器。

## 反馈

遇到问题或有功能建议，可以提交 [GitHub Issue](https://github.com/Ruacha00/mellowday/issues)。项目由 [Ruacha](https://github.com/Ruacha00) 维护。

## 许可证

Mellowday 的源代码和项目自有视觉素材采用 [MIT License](LICENSE)。随应用分发的 Inter 字体使用 SIL Open Font License 1.1。
