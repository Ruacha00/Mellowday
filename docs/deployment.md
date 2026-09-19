# MellowDay 部署

Vue 静态前端由 Nginx 提供，`/api` 同源转发到 Python/FastAPI。API 使用既有运行时与 SQLite/会话/技能目录，保持单实例、单 worker。当前无应用鉴权，默认仅绑定本机回环地址。

## 新环境启动

需要 Docker Desktop Linux 容器引擎、Compose 2.24+。仓库根目录执行 PowerShell：

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.docker.example .env }
# 在本地 .env 填入模型配置；已有配置不要覆盖。
docker compose config --quiet
docker compose up -d --build --wait
docker compose ps
python scripts/check_deployment.py --url http://127.0.0.1:8021
```

打开 [MellowDay](http://127.0.0.1:8021)。`frontend` 提供页面、hash 路由和 `/api`，`api` 只在 Compose 网络监听 8000。健康检查包含页面及代理；无密钥时管理页仍可用，健康不表示模型权限、余额或真实调用已通过。

镜像为 `mellowday-frontend:local` 和 `mellowday-api:local`，可用 `MELLOWDAY_FRONTEND_IMAGE`、`MELLOWDAY_API_IMAGE` 指定标签。Node 只存在于构建阶段，运行前端只需 Nginx。模型凭据仅注入 API 运行环境。

## 端口、时区与持久化

| 配置 | 默认与作用 |
| --- | --- |
| `MELLOWDAY_WEB_PORT` | 8021，前端宿主端口 |
| `MELLOWDAY_API_KEY` / `MELLOWDAY_API_BASE` / `MELLOWDAY_MODEL` | 运行时模型配置，环境值覆盖页面保存值 |
| `TZ` | Asia/Shanghai，模型解析相对时间的时区 |
| `MELLOWDAY_DATA_DIR` | Compose 强制 /app/data，不使用宿主 Windows 路径 |
| `MELLOWDAY_ENV_FILE` | Compose 置空，不再次读取环境文件 |

项目名保持 `mellowday`，卷键保持 `mellowday-data`，默认实际卷名 `mellowday_mellowday-data`。使用不同 `-p` 会产生独立卷，升级先核对真实挂载。完整数据包括 SQLite/WAL、配置、会话、展示历史、trace、长结果、技能归档与学习记录；只备份数据库不足以恢复应用。

```powershell
docker compose stop
docker compose start
# 更新代码后：
docker compose up -d --build --wait
```

普通 `docker compose down` 不删除命名卷。日常停止、更新和权限修复不要执行 `down -v` 或删除数据卷。

## 从旧单容器版本切换

旧服务 `web` 占用同一 8021 端口。不能让新前端与其争用端口，也不能让两个 API 同时写同一卷。

1. 保存旧 Compose、镜像 ID/独立标签、项目名、端口与卷名。用 `docker inspect mellowday-web-1 --format '{{json .Mounts}}'` 核对挂载，不输出含凭据的完整 inspect。
2. 等活动轮次结束，停止旧 `web` 写入，完整备份数据卷到不入库的本地目录；包含 SQLite WAL/SHM。
3. 先在独立测试卷恢复，核对记录 ID、会话、trace、原文 ref、技能版本。保留备份与旧镜像。
4. 新 Compose 沿用相同卷；旧 `web` 已停止且属于本项目时，运行 `docker compose up -d --wait --remove-orphans` 移除旧容器并启动新服务。此命令不删除卷。
5. 运行只读检查并打开页面，验证旧数据与重启持久化。失败则停止新 API，用旧镜像/Compose 接回相同卷和原端口。

聊天优先版本新增记忆轮次、日历例外、订阅投递及人格适应存储；原 records 继续作为事项权威来源。旧 wheel 的静态入口仍保留。回退先验证新写入数据兼容；若必须恢复备份，明确恢复点之后的新增数据影响。权限应匹配 API UID 1000；遇到拒绝访问先备份并针对核实后的卷修复属主，不重建空卷。

本机演练发现，原日常镜像缺少工具原文 HTTP 接口。它已单独保留为 `mellowday:pre-vue-20260919`，完整能力回退使用已验收的 `mellowday:acceptance-r4`。回退前必须验证所选镜像本身支持需要的接口，不能只验证卷存在。本轮备份、镜像身份和数据一致性摘要见验收报告，个人数据及具体恢复文件只保存在本地忽略目录。

## 开发与 Python 单独运行

```powershell
python -m pip install -e .
python -m mellowday.web_app --host 127.0.0.1 --port 8000
# 另一个终端：
Set-Location frontend
npm ci
npm run dev
```

[开发页面](http://127.0.0.1:5173) 由 Vite 将 `/api` 代理到 8000，可设置 `MELLOWDAY_DEV_API_URL` 改目标。Python 单独启动的根页面为原静态兼容入口；正式 Vue UI 使用 Vite 或 Nginx。pip 安装不要求 Node，新 Vue dist 不打入当前 wheel。

## 验收

```powershell
python -m pytest -q -p no:cacheprovider
Set-Location frontend
npm ci
npm run check
npm run test -- --run
npm run build
npm run test:e2e
```

浏览器验收需 Python Playwright/Chromium：`python -m pip install playwright==1.58.0`、`python -m playwright install chromium`。脚本使用隔离数据、真实 HTTP API 和脚本化 agent，不请求外部模型。真实模型证据单列。`scripts/check_deployment.py --write-test-data` 会创建记录，只对隔离验收卷使用。

补充脚本 `frontend/tests/browser/interaction_edges.py --url <隔离地址> --output <结果路径>` 验证停止后继续、错误草稿、配置上限清空和今日页；`proxy_stream.py` 使用同样的 URL/output 参数验证 65 秒 SSE 等待与断开。两者仅连接脚本化 fixture，不能对日常数据运行。完整浏览器验收要求新建隔离卷，避免前次确认回执影响一次性操作断言。

## 故障定位

- 502：检查 `docker compose ps` 和 `docker compose logs --tail 60 api frontend`；Nginx 动态解析 api 服务地址，后端不能扩成多个 worker。
- 流式响应不即时：确认 `/api` 禁止 buffering/cache/压缩，读取超时为 600 秒；停止通过关闭当前 POST 连接回收对应轮次。
- API 返回 HTML：检查代理与 fallback；未知 API 是 JSON 404，缺失 JS/CSS 也应返回 404。
- 容器包源下载失败：区分引擎与容器出网。需要代理时向构建传 Docker 的 `HTTP_PROXY`/`HTTPS_PROXY` 参数，地址使用容器可达的宿主地址。不要关闭 TLS 校验或把代理凭据写入 Dockerfile。
- Docker Desktop Inference manager 启动错误发生在引擎启动前，应用 Compose 无法修复；先检查 `docker version` 的 Server 信息和 Desktop 日志。

范围见 [S11](specs/S11-container-delivery.md)、[S12](specs/S12-acceptance.md)，本轮证据见[验收报告](evidence/FD-acceptance.md)。
