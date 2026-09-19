# S11 双容器与持久化

目标：`frontend` Nginx + `api` FastAPI；项目名 mellowday、现有卷键 mellowday-data、入口 127.0.0.1:8021 保持兼容。API 单 worker、单副本，无宿主公开端口。

验收：

- Node 仅构建阶段，Nginx 只运行产物；API 沿用 Python 非 root、多阶段、UTF-8 和 TZ，所有数据在 /app/data。
- `/api` 前缀保留，未知 API 返回 JSON；缺失资源 404，hash 路由正常，HTML 不陈旧缓存、hash 资源可缓存。
- POST SSE 关闭 buffering/cache/压缩，600 秒读取超时，不重试 POST；暂停期间首段已到达浏览器，停止和断开传至 API。
- Nginx 能应对 API IP 变化；健康检查含前端与代理，无凭据管理仍可用。
- 两个上下文均排除密钥/个人数据；环境变量仅注入后端运行期。
- 隔离项目/端口/卷构建验收；重启、重建、备份恢复、旧版本回退保留记录、会话、工具原文和技能版本。

现有 wheel 的旧静态入口暂保留兼容；正式 Compose 验收必须访问 Vue 入口。生产数据切换前停止写入并完整备份，绝不 `down -v` 或删除卷处理权限。Docker Desktop 故障与应用部署分别记录。

文件归属：Docker/Compose/.dockerignore、部署文档、部署检查脚本；不修改前端业务和 runtime。
