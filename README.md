# Mellowday

> 慢慢过日子，也好好记得你。

Mellowday（悠日）是一位本地优先、自行部署的个人日常助手。她既陪你聊天，也帮你照看生活里的任务、提醒、日程、笔记和那些值得记住的小事。

当前仓库包含首个可独立运行的纵向切片：浏览器 Conversation Surface 通过 Web App 后端调用公共 Agent Core facade，并由确定性的 Fake Provider 返回 Assistant Chat Content。产品边界和关键决策见 [Mellowday Product Direction](docs/product-direction.md)。

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

## Development

一个命令同时启动后端健康检查和浏览器 Conversation Surface：

```bash
python -m mellowday.web_app
```

打开 <http://127.0.0.1:8000/>；健康检查位于 <http://127.0.0.1:8000/healthz>。当前切片刻意使用 Fake Provider，不需要模型凭据或网络访问。

## Test and build

```bash
python -m mypy src
python -m pytest -q
python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist
```

测试覆盖两个已确认的公共边界：Agent Core facade，以及包含 API 和真实浏览器旅程的完整 Web App 边界。隔离构建测试会在不复制 `chatbot/` 参考树的临时项目中生成 wheel，并检查运行时包不包含对该目录的导入。
