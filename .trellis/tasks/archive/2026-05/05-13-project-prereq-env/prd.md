# 配置项目前置环境

## Goal

根据 `docs/setup/development-environment.md` 配置 `Aearn MVP` 的本机前置开发环境，为后续 Milestone 1 的项目骨架、数据库 migration、API mock、前端联调和 Agent 状态机实现做准备。

## Background / Known Context

- Source of truth: `docs/setup/development-environment.md`。
- 该文档明确说明当前仓库 `01_` 到 `07_` 目录是历史教程样例，不应继续作为最终应用目录。
- 正式实现建议新建独立目录：`aearn/`。
- `docs/` 必须保留为产品、架构、API、数据库、前端交互和验收规格的 source of truth。
- `07_RefundApprovalAgent/` 只作为 LangChain 1.x、LangGraph 1.x、FastAPI、PostgreSQL checkpoint/store、Redis session 的参考实现。
- `06_ReActAgentHILApiMultiSessionTaskTest/` 只作为 Celery、Redis task、异步任务状态管理的临时参考。
- 前一版 “为当前存在的 06 与 07 创建环境” 是错误方案，已废弃，不得执行。
- 本机只读探测结果：`pwsh`、Git、Docker Compose、Node、pnpm、Rust/Cargo、Python、uv 均可用。
- 当前 `aearn/` 目录不存在。
- 文档要求的开发输入已存在：`docs/architecture/api-contract.md`、`docs/architecture/database-schema.md`、`docs/product/frontend-interaction-spec.md`。
- 已读取 `docs/` 下全部文本类文档与设计资产索引：文档栈以 `docs/README.md` 为索引，`product/user-flows.md` 是产品边界 source of truth，`setup/development-environment.md` 是 Milestone 0 前置环境 source of truth。
- 跨文档发现一个执行前需处理的目录差异：`setup/development-environment.md` 建议 `apps/api`、`apps/desktop`、`packages/shared-contracts`、`infra/docker`、`migrations`、`tests`；`plans/learning-agent-implementation-plan.md` 的实施目录假设为 `apps/desktop`、`services/api`、`services/worker`、`packages/shared`、`infra`。
- 用户已确认正式目录结构按 `docs/plans/learning-agent-implementation-plan.md` 执行。
- 设计原型 `docs/design/learning-agent-claude-desktop-framework.html` 仍包含旧痕迹：`publishDrawer`、`复盘草稿`、`Attempt 记录配置`。这些与 Draft V1.1 文档中 “MVP 不保留独立复盘草稿 / 设置页不得暴露 Attempt 规则开关” 冲突。前置环境配置不修复该 HTML，但后续前端实现不得照搬这些旧痕迹。

## Requirements

- 按文档创建正式项目目录 `aearn/`，不要把旧 `01_` 到 `07_` 目录直接改成正式项目。
- 创建实施计划指定的基础结构：`apps/desktop/`、`services/api/`、`services/worker/`、`packages/shared/`、`infra/`。
- 提供统一 Docker Compose：`aearn/infra/docker-compose.yml`，包含 PostgreSQL `postgres:15` 和 Redis `redis:latest`。
- 提供 `.env.example`，包含文档列出的本地开发环境变量；不得创建或提交真实密钥。
- 为后端提供依赖固化入口，优先使用 `pyproject.toml` 和 `uv`，依赖版本与文档一致。
- 建立可安装并可导入 `fastapi`、`langgraph`、`langchain`、`redis`、`celery` 的后端虚拟环境。
- 建立或生成 Tauri 空应用，使 Node、pnpm、Rust/Cargo 和 Tauri 前置能力可验证。
- 启动或验证 PostgreSQL 和 Redis 可用。
- 不实现业务 API、不写正式 Agent prompt、不接真实 runner sandbox、不做 Java / C++ 编译沙箱。

## Acceptance Criteria

- [x] `aearn/` 目录结构存在。
- [x] `aearn/infra/docker-compose.yml` 存在，并能启动 PostgreSQL 和 Redis。
- [x] `docker compose ps` 显示 PostgreSQL 和 Redis 正常运行，或等价健康检查通过。
- [x] `aearn/.env.example` 存在，且真实 `.env` 不进入 Git。
- [x] 后端虚拟环境可安装并导入 `fastapi`、`langgraph`、`langchain`、`redis`、`celery`。
- [x] 数据库连接串 `postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable` 可连通。
- [x] Redis 连接串 `redis://127.0.0.1:6379/0` 可连通。
- [x] Node、pnpm、Rust、Cargo 可用。
- [x] Tauri 空应用能启动或至少通过可行的非交互构建/检查命令验证。
- [x] 已确认 `docs/architecture/api-contract.md`、`docs/architecture/database-schema.md`、`docs/product/frontend-interaction-spec.md` 可作为开发输入。

## Verification

- Toolchain verified: PowerShell 7.6.0, Git 2.50.1.windows.1, Docker 29.3.0, Docker Compose v5.1.0, Node v22.14.0, Corepack 0.31.0, pnpm 10.8.0, Rust/Cargo 1.95.0, Python 3.12.7, uv 0.11.7.
- Backend environment installed with `uv --directory .\aearn\services\api sync`.
- Backend imports passed with `uv --directory .\aearn\services\api run python -c "import fastapi, langgraph, langchain, redis, celery; print('backend imports ok')"`.
- Desktop build passed with `pnpm --dir .\aearn\apps\desktop build`.
- Tauri CLI verified with `pnpm --dir .\aearn\apps\desktop tauri --version`, returning `tauri-cli 2.11.1`.
- Rust/Tauri check initially failed because `src-tauri/icons/icon.ico` was missing; a minimal local icon was added, then `cargo check` passed under `apps\desktop\src-tauri`.
- Docker Desktop was not initially running; it was started locally, then `postgres:15` was pulled and `docker compose -f .\aearn\infra\docker-compose.yml up -d` started both services.
- Container health passed: `aearn_postgres` and `aearn_redis` are `healthy`.
- PostgreSQL container check passed with `docker exec aearn_postgres pg_isready -U postgres -d postgres`.
- Redis container check passed with `docker exec aearn_redis redis-cli ping`.
- Python PostgreSQL connection passed with `127.0.0.1`; `localhost` timed out in the current Windows environment, so `.env.example` uses `127.0.0.1`.
- Python Redis connection passed with `redis.from_url('redis://127.0.0.1:6379/0').ping()`.

## Out of Scope

- 不配置真实 LLM API key、代理、OneAPI 或 Ollama 模型服务。
- 不实现业务 API、数据库 migration、Agent 状态机或前端业务页面。
- 不提交真实 API key、数据库密码或生产配置。
- 不归档或删除旧 `01_` 到 `07_` 目录，除非用户另行明确要求。
- 不修复 HTML 原型中的旧流程痕迹，除非用户另行明确要求。

## Open Questions

- 是否允许我按当前 Trellis 规划进入执行阶段，创建 `aearn/` 骨架、安装依赖并启动 Docker 服务？
