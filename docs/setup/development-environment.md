# Aearn 本地开发环境

**状态：** 当前 Tutor Harness 开发/验证环境，2026-07-29。
**权威来源：** `aearn/package.json`、`aearn/services/api/pyproject.toml`、
`aearn/infra/docker-compose.yml`、`aearn/scripts/start-dev.ps1` 与
`.env.example`。
**范围：** 正式实现只在 `aearn/` 下；仓库根目录用于 Git、Trellis 和文档。

## 1. 必需工具

| 工具 | 需求 | 用途 |
| --- | --- | --- |
| Windows PowerShell | 必需 | 项目脚本与本地运维命令 |
| Git | 必需 | 工作树/变更管理 |
| Docker Desktop + Compose | 必需 | PostgreSQL 15、Redis、本地 bootstrap 测试 |
| Python | `>=3.11,<3.13` | FastAPI、worker、tests、type check |
| uv | 必需 | Python environment、lock、test/lint/type check |
| Node.js + pnpm | 必需 | Desktop build/dev |
| Rust stable + Windows C++ Build Tools + WebView2 | Tauri dev/build | Desktop shell |

建议先验证：

```powershell
python --version
uv --version
node --version
pnpm --version
docker --version
docker compose version
rustc --version
cargo --version
```

不要在仓库根目录创建散装虚拟环境或 `requirements.txt`。后端依赖以
`aearn/services/api/pyproject.toml` 为准；当前 API runtime 不依赖
LangChain、LangGraph、LangGraph checkpoint 或 OpenAI Agents SDK。

## 2. 本地基础服务

`aearn/infra/docker-compose.yml` 只运行：

| 服务 | 默认端口 | 用途 |
| --- | ---: | --- |
| PostgreSQL 15 | `5432` | 用户、cutover、Tutor durable state、队列/lease 与测试 bootstrap |
| Redis | `6379` | Celery broker/result backend |

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
docker compose -f .\aearn\infra\docker-compose.yml ps
```

默认本地连接：

```text
postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable
redis://127.0.0.1:6379/0
```

这些值仅是本地 compose 默认，不是生产 secret。真实 `.env`、密钥、缓存、
`.logs/` 和构建产物不得提交。

## 3. 环境变量与默认安全姿态

从 `aearn/.env.example` 复制为本机 `aearn/.env`，按自己的本地服务调整：

```powershell
Copy-Item .\aearn\.env.example .\aearn\.env
```

测试/离线验证可使用：

```env
LLM_TYPE=disabled
TUTOR_EXECUTOR_ENABLED=false
```

`LLM_TYPE=openai` / `deepseek` 时，API 只使用配置的主兼容 provider。配置缺失、
超时、非法或不安全输出统一成为 learner-safe `MODEL_UNAVAILABLE`；不会跨
provider/model fallback。真实 key 只存在本机 `.env`，不要把它放进文档、测试
fixture、日志或 Git。

### 默认 proactive / curation posture

```env
TUTOR_PROACTIVE_SCHEDULER_ENABLED=true
TUTOR_BACKGROUND_HARD_PAUSED=false
TUTOR_PROACTIVE_CUTOVER_ELIGIBLE=true
TUTOR_PROACTIVE_DAILY_BUDGET=1
TUTOR_PROACTIVE_CONCURRENCY_LIMIT=1
TUTOR_INFERRED_MEMORY_ENABLED=false
TUTOR_CURATION_DAILY_BUDGET=0
TUTOR_CURATION_CONCURRENCY_LIMIT=1
TUTOR_CURATION_MAX_OUTPUT_TOKENS=0
```

含义：verified 用户最多得到一条 activity/inbox 主动建议；这不是无条件的后台
模型调用。用户 pause、daily budget、cooldown、concurrency、lease、retry 与
circuit breaker 仍然生效。curation/inferred memory 仍默认关闭。

如果需要在本地排查其他功能而不希望 background 工作被候选任务处理，显式设置
`TUTOR_BACKGROUND_HARD_PAUSED=true` 或不投递 scheduler task；不要把这个临时
覆盖写回 `.env.example`，也不要用 fake 生产用户制造信号。

## 4. Bootstrap、启动与停止

### 一键开发环境

```powershell
pnpm --dir .\aearn dev
pnpm --dir .\aearn dev:status
pnpm --dir .\aearn dev:restart
pnpm --dir .\aearn dev:stop
```

`dev` 的顺序是：Docker PostgreSQL/Redis → `app.db.bootstrap` → API → 一般
Celery worker → Tauri Desktop dev server。它的受管日志在 `aearn/.logs/`。

`dev:status` 会报告 Docker、`/health`、Desktop dev server 和受管 PID。状态可能
是：

- `alive`：进程且启动命令可验证；
- `stale`：保存的 PID 已不存在；
- `untrusted`：PID 存在但命令行不是 Aearn 受管进程。

`dev:stop`/`dev:restart` 只会停止 command 已验证的 Aearn 进程，避免误杀其它
终端。若看到旧 stale PID，先运行 `dev:status`；它不是服务健康通过的证据。

### 手动等价命令

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
uv --directory .\aearn\services\api run python -m celery -A aearn_worker.worker_app:celery_app worker --loglevel=info --pool=solo
pnpm --dir .\aearn desktop:dev
```

Windows 上用 `python -m uvicorn` 和 `python -m celery`，不要直接依赖可执行脚本
shim。启动任意真实 provider/worker 前必须确认是在本地 disposable environment；
测试默认使用 fake provider/clock/executor seam。

## 5. Standalone container executor

executor 不是 `dev` 默认进程，也没有 API/worker/Desktop runtime-client 注入。
仅在单独终端显式运行：

```powershell
pnpm --dir .\aearn executor:once
pnpm --dir .\aearn executor:dev
```

executor 只读取该终端的环境变量；它不会自动加载或改写仓库 `.env`。默认
`TUTOR_EXECUTOR_ENABLED=false`。即使显式设为 `true`，没有 Git-reviewed
`aearn/infra/executor/image-locks.json` digest lock 时仍会保持 safe unavailable，
不会拉取 tag、使用本机镜像替代品、调用 host subprocess 或开放网络。详见
[Container Sandbox Executor Operations](./container-sandbox-executor.md)。

## 6. 开发前后的最小检查

### 后端

```powershell
uv --directory .\aearn\services\api run python -m compileall -q app
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api lock --check
```

### Desktop

```powershell
pnpm --dir .\aearn desktop:check
```

### 数据库/fixture

PostgreSQL bootstrap-heavy pytest 必须串行。不要并行运行同时调用
`bootstrap_database()` 的模块；共享 schema 重建可能导致 PostgreSQL deadlock 或
`tuple concurrently updated`，那不是可忽略的成功。

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py tests/test_harness_cutover.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_proactive_default_delivery.py -q
```

完整质量矩阵、fixture smoke 和实测结果见
[Release Readiness Ledger](../qa/tutor-harness-release-readiness.md)。

## 7. 运行边界与排障

- `GET /health` 只证明 API process 可响应，不证明 verified cutover、provider、
  worker、executor 或 Desktop 已通过。
- `/api/environment/doctor` 用于本地诊断；不要把其输出或 `.env` 内容复制到
  issue/commit 中。
- `GET /api/harness/cutover` 是 Desktop/Tutor 的准入依据；不能用旧 plan/session
  本地缓存替代它。
- 背景 worker 的 `scan_due_signals` 生产语义是 global scan。fixture 需要隔离时
  使用显式 user scope 的 service seam，不要改生产 task 名或队列行为。
- 需要重启或变更 skills、MCP、model catalog 时，按本机工具要求新开会话/重启；
  该操作不属于 Aearn API/worker 的正常开发启动流程。
