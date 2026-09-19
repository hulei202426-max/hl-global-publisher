# (HL)全球发布 — Render 部署指南（单管理员私有测试版）

## 上线前的限制
- 这是单管理员测试版，不是可对外销售的多租户 SaaS。所有社交平台始终显示未连接，绝不真正发帖。
- 使用付费持久化磁盘和托管 PostgreSQL；不要使用 Render 临时文件系统存放视频。Render 磁盘容量及 PostgreSQL 套餐按其后台当前价格确认。
- Render 磁盘绑定单个服务实例；Web 服务只运行 **1 个实例**，应用也只运行 **1 个 worker**，以避免重复执行调度器。
- 管理员令牌只在 HTTPS 页面输入；不要发送给任何人，不要提交到 GitHub。测试版缺少正式账号登录、限流、恶意文件扫描、备份与团队隔离，勿对公众开放。

## 1. GitHub 上传
1. 创建一个 **Private** 私有仓库，例如 `hl-global-publisher`。
2. 将压缩包内 `HL_Global_Publisher_Render/` 文件夹中的文件上传到仓库根目录（不是上传 ZIP 本身）。
3. 确认根目录包含 `Dockerfile`、`requirements.txt`、`app/`。不要上传 `.env`、视频、密码。

## 2. Render 创建数据库
Dashboard → New → Postgres，创建数据库。选择适合的视频项目所在区域，记录其 **Internal Database URL**（只粘贴在 Render 环境变量，不公开）。检查套餐、保留期限和备份能力。

## 3. Render 创建 Web Service
Dashboard → New → Web Service → Connect GitHub → 选择私有仓库。
- Runtime: Docker（识别仓库根目录 Dockerfile）
- Region: 与 PostgreSQL 相同
- Instance: 选择支持 Persistent Disk 的付费实例，先确认价格再创建。
- Health Check Path: `/api/health`
- Persistent Disk mount path: `/srv/uploads`；容量先按需要选择，上传上限每文件 250 MiB。
- Scaling: 1 instance；不要配置多个实例或多个 Uvicorn workers。
- Environment Variables:
  - `DATABASE_URL`: Render Postgres 的 **Internal Database URL**；代码兼容 `postgresql://`、`postgres://` 和 `postgresql+psycopg://` 前缀。
  - `APP_ADMIN_TOKEN`: 在你本机生成 32 字符以上随机密钥；不要用示例字符串。
  - `UPLOAD_DIR`: `/srv/uploads`
  - `RENDER`: `true`（Render 一般自动提供）
  - `PYTHONUNBUFFERED`: `1`（可选）
- 不需要单独设置 Start Command，Dockerfile 已处理 `$PORT`。
- 请勿设置 `POSTGRES_PASSWORD` 给 Web 服务：托管数据库只需要 `DATABASE_URL`。

## 4. 首次验证
1. 等待 Render 日志出现服务启动成功；打开 `https://<your-service>.onrender.com/api/health` 应返回 `ok: true`。
2. 打开根网址，输入你设置的 `APP_ADMIN_TOKEN`，点击连接。
3. 确认五个平台都是“未连接”；上传一个小 MP4，刷新后确认文件存在，再创建任务。
4. 如果启用重新部署，上传文件应继续存在（持久化磁盘）。数据库也应继续保留任务。
5. 测试后保管好令牌；需要开放给真实客户前必须增加正式登录、租户隔离、对象存储、备份、滥用防护与平台 OAuth 审核。

## 常见错误
- `Render requires ...`: 检查 DATABASE_URL 是否为 PostgreSQL 且 UPLOAD_DIR 为绝对路径。
- `Set APP_ADMIN_TOKEN ...`: 密钥长度至少 32 字符。
- `permission denied /srv/uploads`: 磁盘挂载权限可能与容器非 root 用户冲突；查看 Render 磁盘权限配置并调整磁盘所有权或部署策略，不要将密钥写入镜像。
- 数据库连接失败：确认同一区域及使用 Internal Database URL。
- 视频上传 413：检查服务上传限制与文件是否超过 250 MiB。
