# Mellowday

> 慢慢过日子，也好好记得你。

Mellowday（悠日）是一位本地优先、自行部署的个人日常助手。她既陪你聊天，也帮你照看生活里的任务、提醒、日程、笔记和那些值得记住的小事。

仓库包含可独立安装和运行的完整产品：浏览器 Conversation Surface 与集成的 Settings、可替换的模型 Provider、本地持久化的 Persona、Memory、Conversation History 和 Life Records、Daily Review，以及受限且只读的 Proactive Chat。Web App 通过公共 Agent Core facade 驱动对话和扩展能力；管理界面、诊断与审计保持中性、精确。产品边界和关键决策见 [Mellowday Product Direction](docs/product-direction.md)。

## 当前交付状态

最新的 React/Vite Web App 已切换为生产入口，浏览器自托管模式可以完整运行；Windows Desktop Application、安装器和便携包尚未实现，因此当前版本还不是最终桌面交付物。

## Windows 快速启动

源码检出需要 Python 3.12+、Node.js 22.12+ 和 npm。在 PowerShell 中运行：

```powershell
.\mellowday.ps1 start -Timezone Asia/Shanghai
```

首次启动会自动创建 `.venv`、构建生产 React 前端并安装 Mellowday；后续启动直接复用该环境。打开 <http://127.0.0.1:8000/>，按 `Ctrl+C` 停止。自定义数据目录时可增加 `-DataDirectory D:\MellowdayData`。

更新源码或前端依赖后运行 `.\mellowday.ps1 setup`。生成经过完整验证的 wheel 时运行 `.\mellowday.ps1 package`，产物位于 `dist\`。

## Prerequisites

- Python 3.12+
- Node.js 22.12+ and npm when running from a source checkout

## Install

以下手动流程适用于非 Windows 环境或需要分别控制各步骤的开发场景。创建并激活虚拟环境后，安装开发依赖和 Chromium 测试浏览器：

```bash
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

仅运行应用时可改用：

```bash
python -m pip install -r requirements.txt
```

## Local run

初始化本地数据并启动 Conversation Surface、Settings、后台调度器和健康检查：

```bash
python -m mellowday migrate
python -m mellowday serve
```

Set `MELLOWDAY_TIMEZONE` to the installation's IANA timezone (for example,
`Asia/Shanghai`) before starting the app. If it is unset, Mellowday uses `TZ`
and then falls back to `UTC`.

打开 <http://127.0.0.1:8000/>；健康检查位于 <http://127.0.0.1:8000/healthz>。默认情况下，所有应用数据保存在当前操作系统的用户数据目录中；可用 `MELLOWDAY_DATA_DIR` 指定位置。Provider 在 Settings 中配置并保存在本地；未配置 Provider 时，Settings、本地管理和健康检查仍然可用，对话会明确报告缺少配置。

## Self-hosted release

Production installation, configuration, migration, startup, backup, restore,
testing, and upgrade procedures are documented in
[Self-hosting Mellowday](docs/self-hosting.md). The intentionally preserved
Tool, Skill, and Provider contracts are documented in
[Agent Core extension interfaces](docs/extensions.md).

## Test and build

```bash
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run check
npm --prefix frontend run build
python -m mypy src build_backend.py
python -m pytest -q
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
```

The Vite build is a required predecessor of Python packaging. The custom
build backend validates the generated manifest and every referenced frontend
artifact before creating a wheel. Use `npm --prefix frontend run dev` for the
frontend development server. The production FastAPI root serves the generated
React application; the former `/replacement` entry redirects to `/`.

测试覆盖两个已确认的公共边界：Agent Core facade，以及包含 API 和真实浏览器旅程的完整 Web App 边界。隔离构建测试会在不复制 `chatbot/` 参考树的临时项目中生成 wheel，并检查运行时包不包含对该目录的导入。
