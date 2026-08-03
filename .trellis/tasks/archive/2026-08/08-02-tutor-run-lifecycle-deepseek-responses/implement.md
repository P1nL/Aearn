# Implementation Plan: Tutor TurnRun 生命周期、公开历史与 DeepSeek Responses

## Parent Task Role

此任务是父级规划和集成任务。不得直接在父任务启动全量实现；实现通过两个可独立验证的 child 完成。开始任何 child 前，先检查现有未提交修改与目标范围的重叠，复用正确的已有工作，不覆盖用户修改，也不混入无关改动。

## Required Child Order

1. `08-02-deepseek-responses-decision-contract`
2. `08-02-tutor-conversation-turnrun-history`（依赖 Child 1 的 `conversation_title` 与 explicit-continuation contract）

父任务保留到两个 child 都完成、跨层测试通过、source-of-truth 文档一致后再收口。

## Child 1 — DeepSeek V4 Flash Responses 与 Tutor 决策契约

### Scope

- 实施当天重新核验 DeepSeek 官方 `deepseek-v4-flash` Responses 请求、SSE 事件、完成/不完整/失败表达和最终可见文本字段。
- 在 `llm_client.py` 以精确模型选择 Responses/Chat Completions；不进行协议 fallback。
- 只读取最终可见文本，拒绝 reasoning-only 内容。
- 扩展严格 `TutorDecision`：`conversation_title`、受控 continuation、canonical example、同模型有限 repair、低随机性和安全诊断码。
- 使用 fake transport/client 验证协议与错误分类；同步直接相关 API/runtime 文档。

### Focused checks

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_provider_gateway.py -q
uv --directory .\aearn\services\api run ruff check app/services/llm app/services/tutor app/agents/harness tests/test_tutor_provider_gateway.py
uv --directory .\aearn\services\api run python -m mypy app
git diff --check
```

### Gate

评审 exact-model selector、final-text parser、canonical prompt 和无 fallback 行为。Child 1 归档后才能启动 Child 2。

## Child 2 — Conversation TurnRun、公开历史与 Desktop 导航

### Scope

- 用 conversation lock 和 foreground index 实现每普通消息一 run、latest-input-wins、atomic first turn 与 idempotency replay。
- 在 run loop、capability/effect 边界和 terminal persistence 增加 supersede/cancel 二次检查。
- 添加 title、public-process projection、history/list/cursor schema/repository/public API。
- 将 `POST /runs/{run_id}/inputs` 限制为 explicit continuation。
- 重构 Desktop draft、selection、history hydration、recent/all navigation、局部滚动和紧凑 disclosure card。
- 同步数据库、API、runtime 和前端交互 docs。

### Focused checks

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_loop.py tests/test_tutor_run_repository.py tests/test_tutor_input_merge.py tests/test_tutor_sse.py tests/test_tutor_routes.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_provider_gateway.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
git diff --check
```

Add focused tests for atomic first turn/replay, ten normal turns, post-provider supersede race, capability/effect suppression, history cursor/user scope, title write-once, legacy history and public-process redaction.

### Gate

Verify empty drafts never persist, superseded runs cannot publish/commit, public history has no raw trace/reasoning, and selected conversations own the only active SSE subscription.

## Cross-Child Integration Checklist

- [x] Child 1 exposes one typed strict decision/title/continuation contract consumed by Child 2.
- [x] Child 2 maps provider-safe diagnostics to generic public errors and never exposes internal diagnostic code through run/SSE/history.
- [x] API docs describe first turn, normal turn, continuation, list and history semantics.
- [x] Database docs describe additive fields/indexes and no retroactive legacy process cards.
- [x] Runtime docs describe finite normal runs and cancellation safety boundaries.
- [x] Frontend docs describe draft, selection, cursor pagination, disclosure accessibility and local scrolling.

### Current integration verification (2026-08-03)

- Full API lock/test command: `uv --directory .\aearn\services\api lock --check && uv --directory .\aearn\services\api run python -m pytest -q` -> **321 passed**.
- Static/API checks: `ruff check app tests` passed; `python -m mypy app` passed for **99 source files**.
- Desktop build: `pnpm --dir .\aearn desktop:check` passed (`tsc && vite build`).
- Diff hygiene: `git diff --check` passed; only expected LF/CRLF warnings were printed.
- Task validation is rerun after final spec/documentation updates; no commit, deployment, or archive is implied by this checklist.

## High-Risk Files

- `aearn/services/api/app/services/llm/llm_client.py`
- `aearn/services/api/app/services/tutor/provider_gateway.py`
- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/app/routes/tutor.py`
- `aearn/services/api/app/models/tutor.py`
- `aearn/services/api/app/db/schema.sql`
- `aearn/apps/desktop/src/App.tsx`, `api.ts`, `types.ts`, `hooks/useTutorSSE.ts`, `pages/TutorWorkspacePage.tsx`, `styles.css`
- `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md`, `docs/architecture/tutor-harness-runtime.md`, `docs/product/frontend-interaction-spec.md`

## Non-Negotiable Checks

- No normal input reuses an old interactive run.
- No stale/superseded run writes a learner-visible message, dispatches capability or commits an effect.
- No raw CoT/reasoning/provider response/prompt/tool argument enters public state.
- No provider/model/protocol fallback.
- No client-only durable history/process/title calculation.
- No empty conversation from clicking `新对话`.
- No manual title rename API/UI and no real-provider test calls.

## Before `task.py start`

- Parent and both child PRD/design/implement artifacts are complete and reviewed.
- User explicitly approves implementation, not merely planning/task creation.
- Start only Child 1, never the parent or Child 2.
- Load `trellis-before-dev` and relevant backend/frontend spec indexes before code edits.
