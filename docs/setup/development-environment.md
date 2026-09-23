# Aearn 本地开发环境

**状态：** 当前 Tutor Harness + controlled Codex Sidecar 开发/验证环境，2026-09-02。
**权威来源：** `aearn/package.json`、`aearn/services/api/pyproject.toml`、
`aearn/infra/docker-compose.yml`、`aearn/scripts/start-dev.ps1` 与
`.env.example`。
**范围：** 正式实现只在 `aearn/` 下；仓库根目录用于 Git、Trellis 和文档。

## 2026-09-08：真实课程测试前置与数据保留

- 在 Windows 使用 PowerShell 7 (`pwsh`)，不得通过嵌套脚本回退到 Windows PowerShell 5.1。
- 真实模型测试前先核对已应用的 schema；`tutor_lesson_authoring_attempt_receipts.diagnostic_json` 必须是非空 jsonb 对象、默认 `{}`。已有库先备份，再通过现有增量 schema 修复，不能通过清库绕过兼容问题。
- 回归测试设置独立的 `DATABASE_URL`，先查询 `current_database()` 确认目标；不要让会 bootstrap/清理 fixture 的测试使用待检查的真实测试数据所在库。离线验证显式设置 `LLM_TYPE=disabled`。
- Grounding 的 official 标签不等于真实抓取。新课程只准入带 `grounding_provenance_v1/http_fetch` 的、与来源/URL/正文哈希一致的片段。历史 metadata 缺失为 unknown，不自动升级为可信来源；fixture 只供显式测试 seam。
- 网络抓取在数据库事务之外执行。仅在指定 source 的所有 seed 成功、所有片段来源校验通过后，将 `persist_grounding_reindex_report(..., mode="fetch")` 与 `replace_grounding_chunks(..., source_ids=(指定来源,))` 在同一事务提交。失败保留原索引。不要运行 fixture reindex 来修复真实课程。
- Python tutorial 的 seed 包含目录、introduction 与 controlflow，避免仅抓目录却声称获得变量/控制流正文。新索引不会重写历史冻结 LessonDocument。
- SQL 的 `postgresql-sql-docs` 保持 `seed_urls_only` 与 `trusted_de_facto`，除目录外包含 `tutorial-select.html` 查询正文。新增 seed 不会自动重建已有索引，也不代表 SQLite 方言适配已验收。
- Lesson author 示例必须服从实际证据 trust tier：无 official 证据时不展示或要求 `authority_note`；有 official 证据时该示例只引用真实 official handle。供应商/方言边界可使用有证据的 concept/comparison；不得提升来源等级或放宽质量门禁。
- knowledge-bound `lesson_teaching` 输入必须已有当前 TeachingSession/checkpoint。准备未完成时返回 `409 TEACHING_NOT_READY`，不得先调用通用模型再等待工件出现；已有幂等输入依照原绑定回放。

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

对于精确的 `DEEPSEEK_MODEL=deepseek-flash`，Tutor 默认使用官方上限；
其他模型只使用显式保守配置，不根据相似模型名推断大窗口：

```env
TUTOR_DEEPSEEK_V4_FLASH_CONTEXT_WINDOW_TOKENS=1000000
TUTOR_DEEPSEEK_V4_FLASH_INPUT_LIMIT_TOKENS=131072
TUTOR_DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS=61440
TUTOR_DEEPSEEK_V4_FLASH_MAX_DYNAMIC_TARGET_TOKENS=130688
TUTOR_CONTEXT_WINDOW_TOKENS=5296
TUTOR_CONTEXT_OUTPUT_RESERVE_TOKENS=1200
TUTOR_CONTEXT_PROTOCOL_RESERVE_TOKENS=128
TUTOR_CONTEXT_SAFETY_MARGIN_TOKENS=256
TUTOR_CONTEXT_MAX_DYNAMIC_TARGET_TOKENS=512
TUTOR_CONTEXT_COMPACT_TARGET_TOKENS=16000
TUTOR_CONTEXT_NORMAL_TARGET_TOKENS=64000
TUTOR_CONTEXT_COMPLEX_TARGET_TOKENS=96000
TUTOR_CONTEXT_EXTENDED_TARGET_TOKENS=130688
TUTOR_CONTEXT_WARNING_RATIO=0.8
TUTOR_CONTEXT_CRITICAL_RATIO=0.95
TUTOR_CONTEXT_MAX_EXPANSIONS=1
TUTOR_CONTEXT_FIXED_MODE=
```

Aearn 保留 DeepSeek Flash 的 1M（1,000,000 tokens）物理上下文能力，同时将
普通单次模型请求的输入限制为 128K（131,072 tokens），输出限制为 60K
（61,440 tokens）。Tutor 的预算 capability 为了复用“输入 + 输出 reserve”核算模型，
内部记录 192,512；该值不是模型物理窗口。131,072 是普通请求输入能力上限，
不是每轮填满目标。planner 以共享的确定性
serializer dry-build 完整请求，覆盖 system/teaching policy、严格 JSON contract、
current input、context、metadata、JSON envelope、protocol reserve 与 safety margin，
然后只把剩余 optional budget 交给 ContextBuilder。16K/64K/96K/130,688 是可配置
档位目标，仍会被 provider hard limit 和 dynamic cap 裁剪。精确
`deepseek-flash` 使用 `TUTOR_DEEPSEEK_V4_FLASH_MAX_DYNAMIC_TARGET_TOKENS`；
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

## Local rejected-provider diagnostics

Normal logs contain only server-schema field paths, expected enum values/rules,
safe error codes, and `run_id + input_revision + decision_iteration + attempt`.
Unknown fields stay hashed. Rejected values and full responses never enter logs,
public API/SSE, or PostgreSQL diagnostic receipts.

For local development, set `TUTOR_PROVIDER_DEBUG_CAPTURE_MODE=rejected` and supply
either `TUTOR_PROVIDER_DEBUG_CAPTURE_KEY_BASE64` or
`TUTOR_PROVIDER_DEBUG_CAPTURE_KEY_FILE` (an external file containing one base64
32-byte random key; the direct key takes precedence). Keep the key outside Git
and separate from the capture directory, with filesystem access restricted to
the current operator. Production/template default remains `off`. Restart the
relevant API/worker processes after changing environment configuration.

Only rejected attempts are saved with AES-GCM authentication; accepted responses
are discarded. Existing limits apply: 1 MiB per capture and 24-hour retention
(expired files are pruned when the store opens/writes). A capture can be truncated;
`truncated` and `captured_bytes` are recorded. `tutor_provider_diagnostic_capture`
logs `saved`, `empty`, `not_captured`, or `failed`; saved captures include an
`artifact_id`. Diagnostic failures never replace the original Tutor error.

From the repository root in PowerShell 7:

```powershell
# List metadata only; replace the UUID with the run_id from the failure log.
uv --directory .\aearn\services\api run python -m app.services.llm.provider_debug_cli list --run-id <RUN_ID>
# Inspect metadata by artifact_id (32 hexadecimal characters).
uv --directory .\aearn\services\api run python -m app.services.llm.provider_debug_cli show <ARTIFACT_ID>
# Explicit local-only opt-in to decrypt the response body into this terminal.
uv --directory .\aearn\services\api run python -m app.services.llm.provider_debug_cli show <ARTIFACT_ID> --body
```

`--body` output is sensitive: do not paste it into issues or commits. The CLI
does not create plaintext files and there is no diagnostic HTTP endpoint.
Enabling capture cannot recover responses discarded while capture was off.
This facility covers Harness provider requests, not Codex Sidecar's private tool
transcripts or every subsystem's logs.

## Course intent metadata checks

Database bootstrap now seeds `tutor_learning_intents` and `language_course_intent_tags` after the published course catalog, then validates bidirectional active coverage. Run bootstrap twice after catalog metadata changes:

```powershell
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run python -m app.db.bootstrap
```

A new active course must add intent tags in the same transaction or bootstrap/publication fails with `language_course_intent_coverage_missing`. Course slug is allowed only in the idempotent bootstrap backfill; runtime code must use course UUID/tag joins. With `TUTOR_PLANNING_INTENT_ENABLED=true`, explicit language is the only auto-confirm path, semantic candidates require learner confirmation, and insufficient evidence uses clarification rather than the full catalog. `TUTOR_PLANNING_INTENT_ENABLED=false` is the explicit legacy rollback to the full active catalog; that selector still has no default selection. Routine verification uses fake provider/App Server fixtures only.


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


## 2026-09-23：RAG Corpus 手工 CLI（fixture-only）

入口为 `python -m app.services.grounding.corpus_cli`，仅供本地 operator 手工运行；没有 HTTP/admin
接口、Desktop 控件、学习者调用路径或定时任务。CLI **不会自动 bootstrap**。

本阶段只接受服务端注册 Subject 的 `fixture-v1`。材料来自确定性 fixture，使用
`fixtures.aearn.invalid` 标识，不是下载的权威资料；四条路线仍为 shadow，六个生态仍为 fixture-only。
即使操作生成了 published corpus / active pointer，也不表示公开课程、真实题库或教学准入已完成。
`--mode fetch` 当前明确返回 `FETCH_NOT_READY`（退出码 2），不抓取、不静默改用 fixture。

### 临时库演示

先自行创建一个本轮专用、以 `aearn_rag260_` 开头的本地临时数据库，再显式设置 `DATABASE_URL`。
不要把已有学习库作为演示库。下面从仓库根目录使用 PowerShell 7 运行，先拒绝错误目标，再在该临时库
执行 bootstrap（bootstrap 是独立开发步骤，不是 CLI 的副作用）。

```powershell
if (-not $env:DATABASE_URL) { throw '先显式设置本轮临时库 DATABASE_URL' }
$dbUri = [Uri]$env:DATABASE_URL
if ($dbUri.Host -notin @('localhost', '127.0.0.1') -or
    -not $dbUri.AbsolutePath.Trim('/').StartsWith('aearn_rag260_')) {
    throw '本演示仅允许本地 aearn_rag260_* 临时库'
}
$env:PYTHON_DOTENV_DISABLED = '1'
$env:LLM_TYPE = 'disabled'
uv --directory .\aearn\services\api run python -m app.db.bootstrap
if ($LASTEXITCODE -ne 0) { throw '临时库 bootstrap 失败' }

function Invoke-RagCorpus {
    $json = uv --directory .\aearn\services\api run python -m app.services.grounding.corpus_cli @args
    $exitCode = $LASTEXITCODE
    $result = ($json -join "`n") | ConvertFrom-Json
    if ($exitCode -ne 0) { throw "Corpus CLI 失败：$($result.code)（$exitCode）" }
    return $result
}

$key = [guid]::NewGuid().ToString('N')
$candidate = Invoke-RagCorpus reindex --subject route.python --subject-version fixture-v1 --mode fixture --idempotency-key "$key-reindex"
$validated = Invoke-RagCorpus validate --corpus-id $candidate.corpus_id --expected-generation 0 --idempotency-key "$key-validate"
Invoke-RagCorpus diff --candidate-id $candidate.corpus_id --idempotency-key "$key-diff"
$status = Invoke-RagCorpus status --subject route.python
$generation = if ($null -eq $status.active) { 0 } else { $status.active.generation }
Invoke-RagCorpus activate --candidate-id $candidate.corpus_id --expected-generation $generation --summary-hash $validated.summary_hash --idempotency-key "$key-activate"
Invoke-RagCorpus status --subject route.python
```

`reindex` 只建立候选，`validate` 和 `diff` 不激活。`activate` 必须显式提交刚取得的 summary hash
和 active generation；若并发修改导致冲突，不要改用猜测值或自动绕过 CAS。

### 命令与恢复语义

| 命令 | 必须携带的操作参数 |
| --- | --- |
| `status` | `--subject` |
| `reindex` | `--subject --subject-version fixture-v1 --mode fixture --idempotency-key` |
| `validate` | `--corpus-id --expected-generation --idempotency-key` |
| `diff` | `--candidate-id --idempotency-key` |
| `activate` | `--candidate-id --expected-generation --summary-hash --idempotency-key` |
| `rollback` | `--subject --target-corpus-id --expected-generation --idempotency-key` |
| `retire` | `--corpus-id --idempotency-key` |

同一幂等键和请求重放原操作回执；不要换键来掩盖失败，也不要让同一键承载另一请求。回滚只把指针指向
先前 published 版本并递增 generation，不删除历史；不能退役当前 active 版本。fixture 的来源、版本和
facet 由服务端定义，操作者不能通过命令行传任意 URL/正文或声明校验通过。

操作结果为单行有界 JSON。退出码：`0` 成功/合法重放；`2` 参数、版本、fetch未就绪或校验失败；
`3` 幂等/代际/状态冲突；`4` 安全化内部错误。不会输出 DSN、密码、原始异常或来源正文。
普通 `--help` 是本地帮助文本，不是操作回执。演示结束后，仅清理自己创建且已无连接的临时数据库，
不要删除 Docker 数据卷或原有学习数据库。
