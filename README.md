# Mellowday

> 慢慢过日子，也好好记得你。

Mellowday（悠日）是一位本地优先、自行部署的个人日常助手。她既陪你聊天，也帮你照看生活里的任务、提醒、日程、笔记和那些值得记住的小事。

仓库包含可独立安装和运行的完整产品：浏览器 Conversation Surface 与集成的 Settings、可替换的模型 Provider、本地持久化的 Persona、Memory、Conversation History 和 Life Records、Daily Review，以及受限且只读的 Proactive Chat。Web App 通过公共 Agent Core facade 驱动对话和扩展能力；管理界面、诊断与审计保持中性、精确。产品边界和关键决策见 [Mellowday Product Direction](docs/product-direction.md)。

## Prerequisites

- Python 3.12+

## Install

创建并激活虚拟环境后，安装开发依赖和 Chromium 测试浏览器：

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
python -m mypy src
python -m pytest -q
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
```

测试覆盖两个已确认的公共边界：Agent Core facade，以及包含 API 和真实浏览器旅程的完整 Web App 边界。隔离构建测试会在不复制 `chatbot/` 参考树的临时项目中生成 wheel，并检查运行时包不包含对该目录的导入。
