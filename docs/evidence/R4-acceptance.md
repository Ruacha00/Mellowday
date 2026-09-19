# 第四轮应用验收（2026-09-19）

P1–P4 当前运行代码的真实模型与进程/浏览器验收通过，P5 三条件对照完成。P5 是小样本观测，不构成稳定效果提升结论；P6 每日回顾和主动问候未实施。

## 版本与数据隔离

验收分支 `refactor/mellowday-runtime`，验收时 Git HEAD 为准备提交 `b047844`，实际受测工作区指纹为 **`29d01e6e3716cbe7`**。运行时、核心演示与 P5 三臂均记录同一指纹，运行期间没有源码变化。模型为 `deepseek-v4-pro`，端点 `https://api.deepseek.com`。

所有模型验收使用独立数据库、会话和技能目录；原有日常数据目录的前后快照检查通过。验收后调整文档及两个人工验收脚本，并清除四个文件末尾的多余空行；Python AST 与非末尾换行字节均核对相同，没有修改产品逻辑、模型提示或评测判据。构建 Wheel 还会更新被 Git 忽略的 `src/mellowday.egg-info/SOURCES.txt`；它被旧指纹函数纳入，属于生成的打包元数据。交付差异见 `raw/R4-acceptance-fingerprint.json`。

## 验证结果

| 验证 | 结果 | 证据与范围 |
|---|---|---|
| 全量离线测试 | 541 passed，0 failed | `python -m pytest -q -p no:cacheprovider`；119.17s；一个已有依赖弃用警告 |
| 判据负向自检 | 24/24 | `python scripts/demo_core.py --selfcheck`；运行 `20260919T025705Z-c42c` |
| 真实运行时门禁 | 19/19 | [`R4-runtime-acceptance.json`](raw/R4-runtime-acceptance.json)；运行 `20260919T030225Z-7772` |
| 完整核心演示 | 24/24 | [`R4-core-acceptance.json`](raw/R4-core-acceptance.json)；运行 `20260919T030225Z-c1cd` |
| 显式迁移学习门禁 | 25/25 | 已有 [`R4-learning-final.json`](raw/R4-learning-final.json)，运行 `20260919T020559Z-23ea`；核对运行代码未变化，本次没有重复运行 |
| P5 测量完整性 | 各臂 9/9 | [`R4-p5-acceptance.json`](raw/R4-p5-acceptance.json)；18 个真实模型样本，行为结果见下表 |
| 真实进程生命周期 | 17/17 | [`lifecycle.json`](R4-browser/lifecycle.json)；真实 uvicorn + 本地假模型 |
| Chromium 历史与原文 | 39/39 | [`browser-report.json`](R4-browser/browser-report.json)；历史、工具、错误、完整原文分页与收起后重开 |
| Chromium 管理与布局 | 30/30 + 12/12 | [`management.md`](R4-browser/management.md)、[`layout.md`](R4-browser/layout.md)；创建、编辑、状态、撤销、错误反馈与本地时间 |
| 长结果 HTTP 读取 | 27/27 | [`references.md`](R4-browser/references.md)；分页、搜索、会话隔离、删除及非法引用 |
| Wheel 安装式运行 | 7/7 | [`wheel-smoke.json`](R4-browser/wheel-smoke.json)；非源码目录启动、静态文件、落库、进程重启后读回 |
| Docker 当前镜像 | 17/17 | [`R4-docker-acceptance.json`](raw/R4-docker-acceptance.json)；真实模型、时区、非 root、页面及重启持久化 |

浏览器与本地进程检查使用假模型，不等同于真实模型门禁。已查看管理页与长结果截图，无明显遮挡或溢出。长结果 85,663 字完整分页后的文本与保存的原文逐字一致。

核心演示覆盖：读取真实事务与事实、纠正并确认学习、新会话执行、保留人工编辑的规则、一次性要求不学习、当前要求覆盖习惯、无关请求不加载规则、停用后载荷无规则、恢复与版本回退、折叠及真实子进程重启后继续任务。

## P5 当前观测

三臂同指纹、同模型配置、独立进程。每个案例每臂 n=3；`via_facts_samples` 六格均为 0/3。关闭组的规则正文投递为 0/3，固定与学习组每格均为 3/3。

| 条件 | 开发案例规则命中 | 保留案例规则命中 | 运行 ID |
|---|---|---|---|
| 关闭 Skill | 2/3 | 0/3 | `20260919T030226Z-007f` |
| 固定 Skill | 1/3 | 3/3 | `20260919T030403Z-38f3` |
| 学习后 Skill | 2/3 | 3/3 | `20260919T030558Z-5347` |

完整性检查通过不表示所有回复遵守规则。关闭组也可能偶然输出三个重点；固定组开发案例有两次未达到恰好三个重点，学习组开发案例有一次还未采用足够真实待办。全部 7 个未命中样本保留在原始报告 `failures` 中，包含对照组的 4 个样本。不能据此宣称学习组优于固定组，也不能把结果外推为总体效果量。判据区分力和样本量仍是限制。

## 本次纠正的验收问题

进程冒烟原脚本用“最后一次模型请求”检查配置切换后历史长度。实际请求长度为 `2,3,5,2`：第四个是独立后台请求，真实第三轮保留了前两轮消息。原始失败见 [`lifecycle-initial.json`](R4-browser/lifecycle-initial.json)。脚本现按用户轮次定位请求，并断言完整用户消息序列及展示历史；修正后 17/17。两个验收脚本改用唯一临时目录，避免覆盖旧证据。

历史浏览器脚本增加真实点击“继续加载”、收起再展开、读取至末页及全文相等断言。管理页证据脚本同步现行 `due_at_local` 契约，验证网页 API 与业务工具一致。

## Docker 与安装验证

当前 Dockerfile 构建成功，镜像 ID 为 `sha256:d832540bd8249f1b423cb4c6f2515517be8307affbd1a10ef5e5f7f28b09aed3`。使用独立临时容器与命名卷，健康检查通过，uid=1000、时区偏移 +08:00，包从 site-packages 加载，镜像应用目录没有 `.env`。通过真实模型创建一次“明天上午九点”待办，核对 SQLite 接口中只有一条记录且本地时间正确；重启后记录和会话均可恢复。验收容器与临时卷已清理，原有 `mellowday-web-1` 保持运行。

Docker Desktop 曾在本机 `dockerInference` socket 初始化时报错。停止状态下备份并重建临时 `run` 目录后，后续启动一度在 Secrets Engine 的 `engine.sock` 处报同类错误；最新启动日志确认引擎已运行，CLI 返回 29.6.2，构建与容器测试随后成功。未重置 Docker 工厂设置或删除已有镜像、业务数据卷。当前恢复运行不代表已查明所有 socket 报错的根因。

初次容器验收脚本错误使用执行记录事件名 `tool_call` 检查 SSE（实际为 `tool_start`），并在容器重启后复用旧的随机宿主端口；原报告保存在 [`R4-docker-initial.json`](raw/R4-docker-initial.json)。脚本已按实际事件契约检查，并在重启后重新查询端口；第二轮 17/17，产品代码没有因此修改。

Wheel `mellowday-0.1.0-py3-none-any.whl` 含 42 个条目及全部三个网页静态资源，SHA-256 为 `28c099ab3ed78eef1db1a991d9ee1c910146b80272511aaf8933ac412fbb12d5`。在隔离目录安装后启动服务并验证 7 项检查；没有依赖源码目录提供页面。

## 复现

```bash
python -m pytest -q -p no:cacheprovider
python scripts/demo_core.py --selfcheck
python scripts/gate_l3.py --json-out docs/evidence/raw/runtime-new-run.json
python scripts/demo_core.py --attempts 2 --json-out docs/evidence/raw/core-new-run.json
python evals/p5_compare.py --samples 3 --json-out docs/evidence/raw/p5-new-run.json
python -X utf8 tests/web_app/smoke_real_process.py
python -X utf8 tests/web_app/manual_t8_history_panel.py
```

真实模型命令需要本机凭据；报告会脱敏，原始请求与隔离数据保存在被忽略的 `output/gate-runs/`。历史运行报告保持原样。
