# Aearn 本地开发环境

**状态：** 当前 Tutor Harness + controlled Codex Sidecar 开发/验证环境，2026-09-02。
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

对于精确的 `DEEPSEEK_MODEL=deepseek-v4-flash`，Tutor 默认使用官方上限；
其他模型只使用显式保守配置，不根据相似模型名推断大窗口：

```env
TUTOR_DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS=1000000
TUTOR_DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS=384000
TUTOR_DEEPSEEK_V4_FLASH_MAX_DYNAMIC_TARGET_TOKENS=384000
TUTOR_CONTEXT_WINDOW_TOKENS=5296
TUTOR_CONTEXT_OUTPUT_RESERVE_TOKENS=1200
TUTOR_CONTEXT_PROTOCOL_RESERVE_TOKENS=128
TUTOR_CONTEXT_SAFETY_MARGIN_TOKENS=256
TUTOR_CONTEXT_MAX_DYNAMIC_TARGET_TOKENS=512
TUTOR_CONTEXT_COMPACT_TARGET_TOKENS=16000
TUTOR_CONTEXT_NORMAL_TARGET_TOKENS=64000
TUTOR_CONTEXT_COMPLEX_TARGET_TOKENS=192000
TUTOR_CONTEXT_EXTENDED_TARGET_TOKENS=384000
TUTOR_CONTEXT_WARNING_RATIO=0.8
TUTOR_CONTEXT_CRITICAL_RATIO=0.95
TUTOR_CONTEXT_MAX_EXPANSIONS=1
TUTOR_CONTEXT_FIXED_MODE=
```

DeepSeek V4 Flash 的总窗口为 1M，输出 reserve 为 384K，物理输入 hard limit
因此是 616K；616K 是能力上限，不是每轮填满目标。planner 以共享的确定性
serializer dry-build 完整请求，覆盖 system/teaching policy、严格 JSON contract、
current input、context、metadata、JSON envelope、protocol reserve 与 safety margin，
然后只把剩余 optional budget 交给 ContextBuilder。16K/64K/192K/384K 是可配置
档位目标，仍会被 provider hard limit 和 dynamic cap 裁剪。精确
`deepseek-v4-flash` 使用 `TUTOR_DEEPSEEK_V4_FLASH_MAX_DYNAMIC_TARGET_TOKENS`；
其他模型默认使用保守的 `TUTOR_CONTEXT_MAX_DYNAMIC_TARGET_TOKENS=512`，但可以在
同时显式扩大 generic window/output/reserve 后提高该值。将输出或其他 reserve
配置到不再留下正的必需输入空间会在启动时被拒绝。

`TUTOR_CONTEXT_FIXED_MODE` 留空时按安全结构化事实自适应；可设为 `compact`、
`normal`、`complex` 或 `extended` 作为保守回滚控制。只有受控内部
`insufficient_context` 结果可在同一 TurnRun 中升级一个档位，并继续受
iteration/model-call budget 限制。provider cache 不改变物理输入：预估时不扣除
预期命中，actual `input_tokens` 也不再把 `cached_input_tokens` 加回第二次。

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

`dev` 的顺序是：Docker PostgreSQL/Redis → `app.db.bootstrap` → API → Celery
worker → Celery beat → Tauri Desktop dev server。worker 消费 interactive/proactive/curation
队列；beat 每 5 秒触发 `tutor.interactive.reconcile`，用于恢复丢失 wakeup 或过期 lease。
它们的受管 PID 与日志都在 `aearn/.dev-state.json`、`aearn/.logs/`。

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
uv --directory .\aearn\services\api run python -m celery -A aearn_worker.worker_app:celery_app beat --loglevel=info --pidfile=
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
uv --directory .\aearn\services\api run python -m pytest tests/database/test_db_bootstrap.py tests/integration/test_harness_cutover.py -q
uv --directory .\aearn\services\api run python -m pytest tests/tutor/test_tutor_proactive_default_delivery.py -q
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
- interactive 输入成功不依赖 Celery publish 成功：`tutor_interactive_dispatch_jobs` 是
  PostgreSQL authority，`tutor.interactive.dispatch` 只是高优先级 wakeup，beat 的
  `tutor.interactive.reconcile` 会恢复 pending/retry_wait/lease-expired job。
- 背景 worker 的 `scan_due_signals` 生产语义是 global scan。fixture 需要隔离时
  使用显式 user scope 的 service seam，不要改生产 task 名或队列行为。
- 需要重启或变更 skills、MCP、model catalog 时，按本机工具要求新开会话/重启；
  该操作不属于 Aearn API/worker 的正常开发启动流程。

## 8. 最终学习 Agent 集成验证

核心语言闭环和 cutover/schema 对账必须使用真实本地 PostgreSQL，并保持串行：

```powershell
uv --directory .\aearn\services\api run python -m pytest -q tests/integration/test_learning_agent_integration_matrix.py tests/integration/test_harness_cutover.py
```

最终质量门：

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api run python -m pytest -q

uv --directory .\aearn\services\executor lock --check
uv --directory .\aearn\services\executor run ruff check aearn_executor tests
uv --directory .\aearn\services\executor run mypy aearn_executor --no-incremental
uv --directory .\aearn\services\executor run python -m pytest -q

pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate

git diff --check
```

真实 provider smoke、Docker conformance、reviewed image build/sign/publish 与生产 executor smoke 都是独立、显式批准的发布前步骤；不运行它们时应记录为未执行，而不是由 fixture 结果推断通过。


## Codex Sidecar worker

`pnpm --dir .\aearn dev` 默认启动普通 `tutor-main` solo worker，并显式订阅 `celery,tutor-interactive,tutor-proactive,tutor-curation`；同时启动独立 `tutor-codex` solo worker。普通 Harness dispatch/reconcile 不得只留在默认 `celery` queue，否则 PostgreSQL 中的 pending TurnRun 会一直无人 claim；`pnpm --dir .\aearn dev:no-codex` 是显式 opt-out。Runtime 与 plan-drafting admission 默认开启但各自独立；新 Codex admission 还必须通过 PostgreSQL fresh exact readiness。配置、隔离 Home、health、失败码、日志边界和回滚步骤见 [Codex Sidecar 本地运行与运维边界](./codex-sidecar-runtime.md)。默认测试不调用真实 provider。

## 2026-08-20 Codex raw-runtime 离线验证

本地 contract 验证不需要真实 provider。推荐顺序：

```powershell
uv --directory .\aearn\services\api run pytest tests/codex_sidecar/test_codex_runtime_config.py tests/codex_sidecar/test_codex_runtime_adapter.py tests/codex_sidecar/test_codex_runtime_projection.py tests/codex_sidecar/test_codex_plan_drafting_cutover.py tests/tutor/test_tutor_conversation_runtime.py tests/tutor/test_tutor_conversation_history.py tests/database/test_db_bootstrap.py
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
```

fixture 覆盖 isolated strict config、manual/local compaction、reasoning/summary/commentary/final-answer phase、conversation thread resume、typed planning request、snapshot/SSE reconnect 与 history reducer。不要在该验证序列中设置真实 provider key 或启用 real smoke。

## Course intent metadata checks

Database bootstrap now seeds `tutor_learning_intents` and `language_course_intent_tags` after the published course catalog, then validates bidirectional active coverage. Run bootstrap twice after catalog metadata changes:

```powershell
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run python -m app.db.bootstrap
```

A new active course must add intent tags in the same transaction or bootstrap/publication fails with `language_course_intent_coverage_missing`. Course slug is allowed only in the idempotent bootstrap backfill; runtime code must use course UUID/tag joins. `TUTOR_PLANNING_INTENT_ENABLED=false` disables automatic intent admission and falls back to the full active catalog, but the language selector still has no default selection.


## 2026-09-02：Learning Artifact platform final local verification

Run bootstrap-sensitive API tests in one process. Keep provider and public executor admission disabled unless a separate approval explicitly changes that boundary.

~~~powershell
$env:LLM_TYPE = "disabled"
uv --directory .\aearn\services\api run python -m pytest -q -m "not real_provider"
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check

uv --directory .\aearn\services\api run python -m pytest -q ..\..\packages\shared\tests
uv --directory .\aearn\services\executor run python -m pytest -q --ignore=tests/test_executor_docker_conformance.py
uv --directory .\aearn\services\executor run ruff check aearn_executor tests
uv --directory .\aearn\services\executor run python -m mypy aearn_executor --no-incremental
uv --directory .\aearn\services\executor lock --check

pnpm --dir .\aearn\apps\desktop test
pnpm --dir .\aearn\apps\desktop build
cargo fmt --manifest-path .\aearn\apps\desktop\src-tauri\Cargo.toml --check
cargo check --manifest-path .\aearn\apps\desktop\src-tauri\Cargo.toml
cargo clippy --manifest-path .\aearn\apps\desktop\src-tauri\Cargo.toml --all-targets --all-features -- -D warnings
cargo test --manifest-path .\aearn\apps\desktop\src-tauri\Cargo.toml

# Use a uniquely named disposable local PostgreSQL database, then run:
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run python -m app.db.bootstrap
~~~

The browser matrix uses disposable learner-safe fixtures at 1440x900, 900x900, 390x844, and reduced motion. It must verify no page overflow, clean console, keyboard/focus return, isolated conversation/drawer/Artifact scrolling, and protected-marker absence. Native Preview security evidence may run only the local Tauri/WebView2 harness already defined by the Preview contract; it must not be described as Docker or production container conformance.

Do not set the real-provider marker, enable Docker conformance, build/sign/publish production images, push, deploy, or migrate production data as part of this default matrix. Record those gates as not executed.
