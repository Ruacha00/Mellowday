# MellowDay Docker 部署

第四轮当前镜像于 2026-09-19 完成独立容器重验（17/17）：真实模型写入、时区、静态资源、非 root、重启持久化与会话恢复均通过。见 [R4 应用验收](evidence/R4-acceptance.md)。以下旧运行日志保留为历史记录。

本文说明如何用 Docker Compose 构建并运行 MellowDay，并附上在本机实际执行过的验证记录。
所有命令都在仓库根目录执行。

## 交付文件

| 文件 | 作用 |
|---|---|
| `Dockerfile` | 三阶段镜像（base / dependencies / production），非 root 运行、显式 UTF-8、HEALTHCHECK 打 `/api/health` |
| `docker-compose.yml` | `name: mellowday`，单服务 `web`，端口只绑 127.0.0.1，命名卷持久化 `/app/data` |
| `.dockerignore` | 把 `.env` / `.env.*`、个人数据目录与构建产物挡在构建上下文之外 |
| `.env.docker.example` | 宿主机环境变量模板（凭据留空），复制为 `.env` 后填写 |
| `tests/deployment/test_packaging.py` | 离线回归测试：wheel 必须包含 `web_app/static/*` |
| `docs/deployment.md` | 本文件 |

镜像本身不含任何密钥：`Dockerfile` 只 `COPY` `pyproject.toml` 与 `src/`，模型凭据只在运行时
经 compose 注入。

## 快速开始

```bash
cp .env.docker.example .env      # 填入 MELLOWDAY_API_KEY
docker compose up -d --build
docker compose ps                # 等待 STATUS 出现 (healthy)
```

浏览器打开 <http://127.0.0.1:8021>。未配置密钥时界面照常可用，聊天会返回明确的配置错误
（`model not configured: set MELLOWDAY_API_KEY`）。

常用命令：

```bash
docker compose logs -f web       # 运行日志
docker compose restart           # 重启（数据卷保留）
docker compose stop              # 停止容器，但保留容器本身
docker compose down              # 删除容器与网络，保留数据卷
docker compose down -v           # 连数据卷一起删除（会丢失全部会话与事务数据）
```

**`down` 与 Docker Desktop 的关系**：`docker compose down` 会**删除容器**，而 Docker Desktop 的 Containers 页面只列容器。
因此 `down` 之后 MellowDay 会从该界面「消失」，但它并没有被卸载——镜像 `mellowday:local` 与数据卷 `mellowday_mellowday-data` 仍在，
在 Images / Volumes 页面或 `docker compose ls` 里都能看到。执行 `docker compose up -d` 界面即恢复，数据不丢。
只想暂停而不希望容器消失时用 `docker compose stop`。

服务已设置 `restart: unless-stopped`：容器一旦启动，Docker Desktop 或主机重启后会自动恢复。

## 镜像约定

| 约定 | 取值 | 说明 |
|---|---|---|
| 基础镜像 | `python:3.12-slim-bookworm` | 与项目 `requires-python = ">=3.11"` 一致 |
| 工作目录 | `/app` | |
| 运行用户 | `mellowday`，uid/gid 1000 | 非 root；`/app/data` 归该用户所有 |
| 监听地址 | 容器内 `0.0.0.0:8000` | 宿主机 `127.0.0.1:${MELLOWDAY_WEB_PORT:-8021}` |
| 数据目录 | `MELLOWDAY_DATA_DIR=/app/data` | 命名卷 `mellowday-data`（compose 实际名 `mellowday_mellowday-data`） |
| 编码 | `LANG=LC_ALL=C.UTF-8`、`PYTHONIOENCODING=utf-8`、`PYTHONUTF8=1`、`PYTHONUNBUFFERED=1` | 本项目在 cp936 上踩过中文乱码，容器里不依赖默认区域设置 |
| 时区 | `TZ=Asia/Shanghai`（镜像默认，compose 可用 `${TZ}` 覆盖） | 基础镜像默认 UTC，会把相对时间存错，详见下节 |
| 安装方式 | `pip install .`（非 editable） | 顺带验证 wheel 打包，包含静态界面 |
| 健康检查 | `GET /api/health`，15s 间隔 / 20s 启动宽限 / 5 次重试 | slim 镜像没有 curl，用 `python -c urllib` 探测 |
| 构建期凭据 | 无 | 没有构建参数或密钥；构建只做 pip 安装 |

`production` 阶段从 `dependencies` 阶段复制 `site-packages` 与 `/usr/local/bin`，因此改源码不会
重新解析依赖。依赖清单在 `Dockerfile` 的 `dependencies` 阶段显式列出，与 `pyproject.toml` 的
`[project] dependencies` 保持一致；即使两者漂移，`pip install .` 也会把缺的补上（只是会慢一点）。

构建上下文只传 `pyproject.toml` 和 `src/`，`.dockerignore` 是第二道防线：`.env`、`.env.*`、
`data/`（个人会话与数据库）、`tests/`、`docs/` 等都不进上下文。

## 时区（`TZ`）：默认必须是用户所在时区，不能是 UTC

助手把「明天上午九点」这类相对时间按**自己的时钟**解析，并带着那个偏移量落库。
基础镜像默认是 UTC，于是同一句话会被存成 `09:00Z`；浏览器再按本地时区渲染，UTC+8 的用户看到的就成了 **17:00**。
系统提示里的 `Current time ... (timezone UTC (UTC+0000))` 会让模型自洽地算错，所以这不是模型的问题，是容器配置的问题。

修复：镜像设 `ENV TZ=Asia/Shanghai`，compose 再显式传 `TZ: ${TZ:-Asia/Shanghai}`，两者都可由环境变量覆盖。
`python:3.12-slim-bookworm` 自带 `tzdata`（`/usr/share/zoneinfo/Asia/Shanghai` 存在），无需额外安装。

同一次验证里先后创建的两条待办，直接留下了修复前后的对照（同一数据库）：

| 记录 | 请求 | `due_at`（UTC 存储） | `due_at_local`（用户看到） |
|---|---|---|---|
| 修复前 | 明天上午九点 | `2026-09-19T09:00:00+00:00` | **17:00+08:00 ← 错** |
| 修复后 | 明天上午九点 | `2026-09-19T01:00:00+00:00` | **09:00+08:00 ← 对** |

部署到其他时区时用 `TZ=Europe/Berlin docker compose up -d` 覆盖即可；
**不要**用宿主机的 `.env` 之外的隐含约定，容器不会自动继承宿主机时区。

## compose 说明

- `env_file: [{path: .env, required: false}]`：`.env` 缺失也能启动（此时模型未配置，管理页仍可用）。
- `environment:` 显式透传 `MELLOWDAY_API_KEY` / `MELLOWDAY_API_BASE` / `MELLOWDAY_MODEL`，
  避免配置来源不可见；三项默认空值，空值表示走应用内默认（`https://api.deepseek.com`、`deepseek-v4-pro`）。
- `MELLOWDAY_DATA_DIR=/app/data` 写在 `environment` 里：compose 中 `environment` 优先于 `env_file`，
  所以宿主机 `.env` 里指向 Windows 目录的同名变量不会把容器数据写到别处。
- `MELLOWDAY_ENV_FILE=""`：容器内显式关闭 `src/mellowday/env.py` 的 `.env` 文件读取，凭据只来自环境变量。
- 端口绑定 `127.0.0.1`：应用自身没有鉴权，不允许暴露到局域网。

## 实测记录

环境：Docker 29.6.2（server 29.6.2，linux/amd64），Docker Compose v5.3.1，基础镜像
`python:3.12-slim-bookworm` 已在本机。以下命令与输出均为实际执行结果（凭据已隐去）。

### 1. 构建

```text
$ docker compose --progress plain build --no-cache
#9 [internal] load build context
#9 transferring context: 5.48kB done
#16 [production 6/7] RUN pip install --no-cache-dir .  && rm -rf /app/src /app/build /app/pyproject.toml ...
#16   Building wheel for mellowday (pyproject.toml): finished with status done
#16   Created wheel for mellowday: mellowday-0.1.0-py3-none-any.whl size=148614
#16   Successfully installed mellowday-0.1.0
#18 naming to docker.io/library/mellowday:local done
=== docker compose build exit=0 ===
```

构建期不访问模型：`dependencies` 阶段只有 pip 下载，`production` 阶段只有打包与安装；镜像历史里
没有任何密钥（见第 8 项）。Dockerfile 内还内置了一道打包自检——`pip install .` 之后断言
`site-packages/mellowday/web_app/static/index.html` 存在，静态界面没进 wheel 会直接构建失败。

### 2. 启动并达到 healthy

```text
$ docker compose up -d
 Network mellowday_default Created / Volume mellowday_mellowday-data Created
 Container mellowday-web-1 Started          exit=0

$ docker compose ps
NAME              IMAGE             COMMAND                  SERVICE   STATUS                    PORTS
mellowday-web-1   mellowday:local   "python -m mellowday…"   web       Up 7 seconds (healthy)    127.0.0.1:8021->8000/tcp
```

容器从启动到 healthy 约 7 秒。

### 3. 健康检查接口

```text
$ curl.exe -s --noproxy "*" -w ("|HTTP_CODE=%{http_code}|CONTENT_TYPE=%{content_type}") http://127.0.0.1:8021/api/health
{"ok":true,"app":"mellowday","version":"0.1.0","model_configured":true}|HTTP_CODE=200|CONTENT_TYPE=application/json
```

### 4. 静态界面（打包是否真的成功）

```text
$ curl.exe -s --noproxy "*" -o $env:TEMP\mellowday-index.html -w ("HTTP_CODE=%{http_code}|BYTES=%{size_download}|CONTENT_TYPE=%{content_type}") http://127.0.0.1:8021/
HTTP_CODE=200|BYTES=4381|CONTENT_TYPE=text/html; charset=utf-8
title line : <title>MellowDay</title>
brand line : <div class="brand"><span class="dot"></span> MellowDay</div>
MellowDay occurrences in served HTML: 2

$ curl.exe -s --noproxy "*" -o NUL -w "%{http_code}|%{content_type}|%{size_download}" http://127.0.0.1:8021/app.js   # 同一条命令依次跑 /app.js 与 /styles.css
/app.js     -> 200|text/javascript; charset=utf-8|40505
/styles.css -> 200|text/css; charset=utf-8|9036
```

两个静态资源的字节数与 `src/mellowday/web_app/static/` 下的源文件完全一致（40505 / 9036），
说明浏览器拿到的是打包进 wheel 的那份文件，而不是源码树里的副本——镜像里根本没有源码树：

```text
$ docker run --rm --entrypoint python mellowday:local -c "import os, mellowday.paths as p; print('package_dir:', p.package_dir()); print('static_dir:', p.static_dir()); print('files:', sorted(os.listdir(p.static_dir())))"
package_dir: /usr/local/lib/python3.12/site-packages/mellowday
static_dir: /usr/local/lib/python3.12/site-packages/mellowday/web_app/static
files: [app.js, index.html, styles.css]
```

### 5. 真实模型对话（凭据经 compose 注入，不写入镜像）

```text
$ POST http://127.0.0.1:8021/api/chat   {"message": "你好，请用一句话介绍你自己。", "session_id": "docker-smoke-1"}
HTTP 200 text/event-stream; charset=utf-8
event type counts : {session: 1, busy_start: 1, busy_end: 2, text_delta: 28, token_usage: 1, turn_end: 1, done: 1}
seconds to first text_delta : 2.12
seconds total : 2.47
assistant chars : 46
health : {"ok":true,"app":"mellowday","version":"0.1.0","model_configured":true}
```

回复内容（UTF-8 中文，容器内编码链正确）：

```text
你好，我是 MellowDay，你的私人助理，帮你把日程、待办、提醒和笔记打理得井井有条。
```

凭据来源：宿主机 `.env` 的 `MELLOWDAY_API_KEY` 经 compose `env_file` / `environment` 注入容器；
镜像内既没有 `.env`（第 8 项），也没有任何环境变量携带密钥。

### 6. 数据持久化

```text
$ POST /api/records/todos {"title": "Docker-persistence-probe 中文 <时间戳>"}
created id      : 02529a42c9944ce290c2df5138b228ae
created_at      : 2026-09-18T11:19:17.839274+00:00
before restart  : found = True | total todos = 1
container StartedAt before restart: 2026-09-18T11:18:14.329151337Z

$ docker compose restart          # exit 0
container StartedAt after  restart: 2026-09-18T11:19:18.826868591Z
StartedAt changed     : True
after restart   : found = True | total todos = 1
sessions after restart: [docker-smoke-1]
```

重启后同一条记录的 `id`、`title`、`created_at` 完全一致，保存在命名卷 `mellowday-data` 里；
第 5 项的会话 `docker-smoke-1` 也一并存活。

### 7. 非 root 运行

```text
$ docker compose exec -T web id
uid=1000(mellowday) gid=1000(mellowday) groups=1000(mellowday)
$ docker compose exec -T web whoami
mellowday
$ docker compose exec -T web python -c "import os; print('uid', os.getuid(), '| gid', os.getgid(), '| cwd', os.getcwd(), '| home', os.path.expanduser('~'))"
uid 1000 | gid 1000 | cwd /app | home /home/mellowday
$ docker compose exec -T web python -c "import os; print('W_OK /app/data =', os.access('/app/data', os.W_OK), '| uid owner of /app/data =', os.stat('/app/data').st_uid)"
W_OK /app/data = True | uid owner of /app/data = 1000
```

同一个容器内确认环境变量与编码：

```text
$ docker compose exec -T web printenv | Select-String -Pattern 'MELLOWDAY|^LANG=|^LC_ALL=|PYTHON'
MELLOWDAY_MODEL=
MELLOWDAY_DATA_DIR=/app/data        # environment 覆盖了 env_file 里的 Windows 路径
MELLOWDAY_ENV_FILE=
MELLOWDAY_API_KEY=<present, 36 chars, redacted>
MELLOWDAY_API_BASE=
LANG=C.UTF-8
LC_ALL=C.UTF-8
PYTHONIOENCODING=utf-8
PYTHONUTF8=1
PYTHONUNBUFFERED=1

$ docker compose exec -T web python -c "import locale, sys; print('getdefaultencoding', sys.getdefaultencoding()); ..."
getdefaultencoding utf-8
getfilesystemencoding utf-8
getpreferredencoding utf-8
stdout.encoding utf-8
setlocale LC_CTYPE=C.UTF-8;LC_NUMERIC=C;LC_TIME=C;...

$ docker compose exec -T web python -c "p='/app/data/cjk-probe.txt'; open(p,'w',encoding='utf-8').write('\\u4e2d\\u6587\\u63a2\\u9488'); print('roundtrip:', open(p,encoding='utf-8').read(), '| raw bytes:', open(p,'rb').read())"
roundtrip: 中文探针 | raw bytes: b'\xe4\xb8\xad\xe6\x96\x87\xe6\x8e\xa2\xe9\x92\x88'
```

### 8. 镜像内没有 `.env` 与密钥

```text
$ docker run --rm --entrypoint ls mellowday:local -a /app
.
..
data                       <- 只有数据卷挂载点，没有 .env

$ docker run --rm -i --entrypoint python mellowday:local -   # 遍历整个镜像文件系统
dotenv files anywhere in the image: NONE
files containing an API-key-shaped string: [pip/_vendor/packaging/licenses/_spdx.py]
```

唯一命中来自 pip 自带文件里的 SPDX 许可证标识 `sk-linking-protocols-exception`，不是密钥。
镜像的 `Config.Env` 只有 PATH / 语言 / pip 相关变量，`docker history --no-trunc` 中也没有任何
密钥出现在构建步骤里。

### 9. 清理

验证结束后执行：

```text
$ docker compose down
 Container mellowday-web-1 Removed
 Network mellowday_default Removed
```

**保留数据卷** `mellowday_mellowday-data`：第 6 项的持久化证据（待办记录与会话）留在卷里。已经
实测过跨 `down` / `up` 的复用：

```text
$ docker compose up -d      # 复用上面保留下来的卷
health after reusing the retained volume: healthy
todos still in volume: [Docker-persistence-probe 中文 2026-09-18 19:19:17]
$ docker compose down       # exit 0，容器与网络删除，卷保留
```

需要彻底清空时执行 `docker compose down -v`。

## 回归测试

```bash
python -m pytest tests/deployment/test_packaging.py -q
# 5 passed
```

`tests/deployment/test_packaging.py` 断言 `[tool.setuptools.package-data]` 为 `mellowday` 包声明了
`web_app/static/*`、该模式确实匹配三个静态文件、文件在源码树中存在、`paths.static_dir()` 落在包内。
它不需要构建 wheel、不联网、不需要 Docker。把声明删掉后该用例会失败（已用变异验证：删掉声明后
2 项失败）。

## 已知风险与排查

1. **容器里 `/` 返回 404 或 static assets not installed**：先看 wheel 是否真的带上了静态资源
   （`docker run --rm --entrypoint python mellowday:local -c "import mellowday.paths as p; print(sorted(p.static_dir().iterdir()))"`），
   再看 `src/mellowday/web_app/app.py` 末尾的静态挂载判断——它按 `paths.static_dir()` 是否存在决定
   是否 `app.mount("/", StaticFiles(...))`，路径判断错了就会退化成 JSON 兜底页。
2. **数据卷不可写 / Permission denied on /app/data**：`/app/data` 在镜像里已 `chown` 给 uid 1000，
   新建的命名卷会继承该属主。如果卷是很早以前用 root 建的，执行 `docker compose down -v` 重建。
3. **端口被占用**：改宿主机端口即可，`MELLOWDAY_WEB_PORT=8031 docker compose up -d`。容器内始终是 8000。
4. **宿主机 `.env` 里的 `MELLOWDAY_DATA_DIR`**：它是 Windows 路径，对容器无意义；compose 已用
   `environment` 覆盖为 `/app/data`，不要把该变量再写进 `.env.docker.example`。
5. **改了静态资源但界面没变**：静态文件在构建期打进 wheel，必须重新 `docker compose build`；
   镜像里没有挂载源码，改宿主机文件不会影响运行中的容器。
6. **`pip install .` 需要网络**：构建阶段会访问 PyPI 解析依赖，这不涉及模型凭据；完全离线的构建
   环境需要预先准备本地镜像源或缓存。