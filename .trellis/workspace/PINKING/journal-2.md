# Journal - PINKING (Part 2)

> Continuation from `journal-1.md` (archived at ~2000 lines)
> Started: 2026-06-03

---



## Session 60: Complete local product readiness closeout

**Date**: 2026-06-03
**Task**: Complete local product readiness closeout
**Branch**: `main`

### Summary

Completed P4 parent readiness for local-product-completion, documented equivalent agent eval gate coverage, stabilized review tests against live-model leakage, verified full backend/frontend checks, and archived the parent task.

### Main Changes

- Added a structured `LearningPublicOutput` boundary for learning messages so only validated `public_message` reaches JSON/SSE clients, persistence, and replay.
- Removed internal policy objects from the learning prompt payload and compiled stage behavior into backend-owned instructions.
- Added model-generated review seed bank generation with learner-state context and no fixed fallback bank.
- Added review message history persistence/replay and desktop restore support for reused review sessions.
- Updated backend/frontend code-specs plus API, product, and QA docs for the new public-output and review contracts.

### Git Commits

| Hash | Message |
|------|---------|
| `e430294` | (see git log) |

### Testing

- [OK] `uv --directory .\aearn\services\api run python -m pytest tests\test_onboarding_m2.py tests\test_learning_public_output.py tests\test_llm_integration.py tests\test_learning_sessions_m3.py tests\test_reviews_m4.py tests\test_notes_m5.py tests\test_dashboard_resume_m6.py tests\test_worker_import.py -q` -> 195 passed, 3 warnings
- [OK] `uv --directory .\aearn\services\api run ruff check .`
- [OK] `uv --directory .\aearn\services\api run python -m mypy app`
- [OK] `pnpm --dir .\aearn desktop:check`
- [OK] `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-07-learning-message-output-boundary`
- [OK] `git diff --check`

### Status

[OK] **Completed**

### Next Steps

- 当前 child 已完成并归档；不在本次 session 启动父任务。


## Session 61: Chat-first conversation experience

**Date**: 2026-06-03
**Task**: Chat-first conversation experience
**Branch**: `main`

### Summary

Completed chat-first onboarding normalization, expanded public route language boundaries, updated learning composer error copy, and verified backend/frontend gates.

### Main Changes

- 将 recent retirement 从固定窗口改为由实际 ContextBuilder item/token selection 决定，current input 保持独立且不可被摘要驱逐。
- 实现 `tutor_context_summary_v2`、prior lineage、coverage/source hash、leased transient evidence retrieval、strict primary Curator 和 semantic curation dedupe。
- 增加 PostgreSQL additive 字段、scope composite FK、append-only summary trigger、bootstrap assertions，以及 loader/builder/curation/run-loop 回归测试。
- 同步 Tutor runtime、database schema、acceptance plan 和 backend quality spec。

### Git Commits

| Hash | Message |
|------|---------|
| `8c2c58d` | (see git log) |

### Testing

- [OK] 聚焦 context/curation/run-loop/bootstrap Pytest：59 passed。
- [OK] 最终完整串行 API Pytest：397 passed。
- [OK] Ruff、Mypy（112 source files）、`uv lock --check`、Trellis validate、`git diff --check`。

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 62: Dynamic onboarding route generation

**Date**: 2026-06-03
**Task**: Dynamic onboarding route generation
**Branch**: `main`

### Summary

Implemented no-fallback dynamic onboarding route generation, fixed DeepSeek plan generation by prefetching authoritative doc TOCs before direct JSON calls, updated tests/docs/specs, and verified backend/frontend quality gates.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `0245827` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 63: DeepSeek learning session compatibility

**Date**: 2026-06-03
**Task**: DeepSeek learning session compatibility
**Branch**: `main`

### Summary

Completed DeepSeek direct Chat Completions learning flow, SQL practice template fix, regression tests, and backend spec updates.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `219a885` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 64: Exercise generation knowledge alignment closeout

**Date**: 2026-06-04
**Task**: Exercise generation knowledge alignment closeout
**Branch**: `main`

### Summary

Implemented model-first bounded freeform adaptive exercise generation with enriched route skill context, bounded retry feedback, honest unavailable failures, semantic validators across public languages, SQL alias normalization, cache versioning, and regression coverage.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `9ec26e3` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 65: Learning documentation panel flow closeout

**Date**: 2026-06-05
**Task**: Learning documentation panel flow closeout
**Branch**: `main`

### Summary

Implemented the learning documentation reading flow, right-side documentation panel, explicit concept-check trigger, review sidebar due-state handling, composer reference prefill, tests, docs, and code-spec updates.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `babe2b6` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 66: Refine learning flow concept docs

**Date**: 2026-06-07
**Task**: Refine learning flow concept docs
**Branch**: `main`

### Summary

Refined the learning page flow: official-docs panel now uses two source-attributed sections, concept check results render as compact feedback, unclear/incorrect repair attempts share a limit, practice unlock copy is model-backed without deterministic fallback, internal policy leakage is guarded, and docs/spec/tests were aligned.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f7dadea` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 67: Learning output and review flow hardening

**Date**: 2026-06-07
**Task**: Learning output and review flow hardening
**Branch**: `main`

### Summary

Implemented structured public-message output boundary for learning messages, model-generated review seed banks with learner-state context, and review conversation history replay; validated backend focused and milestone batches plus ruff, mypy, desktop build, task validation, and diff check.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `09d67d6` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 68: Review batch finalization

**Date**: 2026-06-08
**Task**: Review batch finalization
**Branch**: `main`

### Summary

Implemented backend-owned review batch flow with candidate-pool selection, session-local intermediate submits, final FSRS aggregation, docs/spec sync, and verification.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `70b6bf0` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 69: Review task tree closeout

**Date**: 2026-06-08
**Task**: Review task tree closeout
**Branch**: `main`

### Summary

Archived the completed review graph adaptive flow parent and remaining completed child tasks after verification.

### Main Changes

(Add details)

### Git Commits

(No commits - planning session)

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 70: Review conversation card persistence

**Date**: 2026-06-10
**Task**: Review conversation card persistence
**Branch**: `main`

### Summary

Fixed review warmup judgement and conversation-flow exercise cards: warmup uses model/free-text stage judgement, completed exercise cards persist submitted answers and feedback, next exercises render as new in-flow cards, dev:test-data seeds deterministic review QA data. Verified desktop:check, review pytest, local user boundary pytest, ruff, and git diff --check.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `95d8a3b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 71: Review warmup natural conversation

**Date**: 2026-06-11
**Task**: Review warmup natural conversation
**Branch**: `main`

### Summary

Implemented natural review warmup, off-topic steering, model-unavailable handling, desktop skip removal, tests and docs.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a089af8` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 72: Full product QA

**Date**: 2026-06-11
**Task**: Full product QA
**Branch**: `main`

### Summary

Completed end-to-end Aearn full product QA, including review.zh.md, warmup natural-conversation verification, desktop flow checks, backend guardrails, live-model QA, and PASS report after contained fixes.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `cc2ef95` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 73: Regenerate current project docs

**Date**: 2026-06-18
**Task**: Regenerate current project docs
**Branch**: `main`

### Summary

Created docs/current current-state package, classified old-doc archive/writeback decisions, wrote back low-risk stale docs, fixed desktop Vite chunk warning with manual chunks, and verified desktop/backend checks.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `01ba0d8` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 74: Complete Tutor Harness runtime seam

**Date**: 2026-07-26
**Task**: Complete Tutor Harness runtime seam
**Branch**: `main`

### Summary

Implemented and verified the feature-disabled Tutor Harness contracts, bounded context builder, primary-only provider gateway, finite run loop, transition documentation, and backend code-spec; preserved legacy product traffic and unrelated Trellis upgrade changes.

### Main Changes

- Detailed change bullets were not supplied; see the summary above.

### Git Commits

| Hash | Message |
|------|---------|
| `9f65449` | (see git log) |
| `30772e9` | (see git log) |

### Testing

- Validation was not recorded for this session.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 75: Add Tutor Skill Catalog Capability Gateway

**Date**: 2026-07-27
**Task**: Add Tutor Skill Catalog Capability Gateway
**Branch**: `main`

### Summary

Implemented a versioned Tutor Skill catalog, policy-gated decision/capability boundaries, registry-only grounding, focused tests, and the reusable backend code-spec while preserving the feature-disabled Harness boundary.

### Main Changes

- Detailed change bullets were not supplied; see the summary above.

### Git Commits

| Hash | Message |
|------|---------|
| `92492c6` | (see git log) |

### Testing

- Validation was not recorded for this session.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 76: Complete Tutor State, Traces, and Evals

**Date**: 2026-07-27
**Task**: Complete Tutor State, Traces, and Evals
**Branch**: `main`

### Summary

Implemented and independently verified the feature-off Tutor durable persistence, safe trace/export, internal replay, effect CAS, curation envelope, deterministic evals, and target contracts.

### Main Changes

- Detailed change bullets were not supplied; see the summary above.

### Git Commits

| Hash | Message |
|------|---------|
| `00b57a9f585796e5b7c46c7e8bf91849b765f115` | (see git log) |

### Testing

- Validation was not recorded for this session.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 77: Complete Container Sandbox Executor

**Date**: 2026-07-27
**Task**: Complete Container Sandbox Executor
**Branch**: `main`

### Summary

Implemented and verified the feature-disabled isolated container executor: shared immutable contracts and catalog, scoped durable intent/job lifecycle, executor-only Docker boundary, seven runtime protocol definitions, redaction, and fail-closed health/lock gates. No public traffic or legacy runner behavior changed.

### Main Changes

- Detailed change bullets were not supplied; see the summary above.

### Git Commits

| Hash | Message |
|------|---------|
| `cd7bcce198973988fdd7889075a22a1b22406e6a` | (see git log) |

### Testing

- Validation was not recorded for this session.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 78: Complete Tutor Proactive Scheduler foundation

**Date**: 2026-07-28
**Task**: Complete Tutor Proactive Scheduler foundation
**Branch**: `main`

### Summary

Implemented and verified the feature-disabled Tutor proactive scheduler: durable signals and candidates, fail-closed origin-aware policy, PostgreSQL leases and curation jobs, separate worker wrappers, tests, and operational documentation. No public routes, chat delivery, desktop behavior, push, or deployment changed.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `9b615cd` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 79: Deliver Tutor learner state projections

**Date**: 2026-07-28
**Task**: Deliver Tutor learner state projections
**Branch**: `main`

### Summary

Implemented feature-disabled immutable plan revisions and rollback, governed learner memory, primary-only Curator projections, safe activity and inbox state, schema/contracts/tests, and verified the Tutor regression suite.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `d796435` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 80: Tutor API SSE and Desktop pre-cutover delivery

**Date**: 2026-07-28
**Task**: Tutor API SSE and Desktop pre-cutover delivery
**Branch**: `main`

### Summary

Delivered and verified Child 06 public Tutor API/SSE adapter, input merge dispatcher, isolated cursor-replay desktop workspace, learner controls, and contract/spec updates; legacy routing remains unchanged.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f0ee786` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 81: Complete verified Tutor harness cutover

**Date**: 2026-07-28
**Task**: Complete verified Tutor harness cutover
**Branch**: `main`

### Summary

Implemented the server-authoritative per-user cutover gate, verified legacy cleanup, runtime denial, Desktop bootstrap flow, and focused API/worker/Desktop verification.

### Main Changes

- Added the server-authoritative `harness_cutovers` receipt, canonical summary/hash/nonce protocol, and idempotent confirmation endpoints.
- Enforced verified-only Tutor admission plus active-rollout legacy runtime denial; ordinary reset cannot bypass a pending cutover.
- Implemented exact user-scoped legacy/checkpoint cleanup with target-state and unknown-scope fail-closed branches, atomic verification, and rollback receipts.
- Added the Desktop cutover page and bootstrap reset path that preserves `userId`, clears only legacy `planId`/user-scoped state, and avoids legacy restoration requests.

### Git Commits

| Hash | Message |
|------|---------|
| `002ba372843caf314c7c04904ce8b20f32a9b524` | (see git log) |

### Testing

- [OK] `ruff check app tests` and `python -m mypy app` (146 source files).
- [OK] Focused API/worker suite: 20 passed; one third-party LangGraph deprecation warning only.
- [OK] `pnpm --dir .\aearn desktop:check`, repeatable database bootstrap, Trellis manifest validation, and `git diff --check`.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 82: Complete Tutor Harness integration and legacy retirement

**Date**: 2026-07-30
**Task**: Complete Tutor Harness integration and legacy retirement
**Branch**: `main`

### Summary

Completed Child 08: activated verified-only proactive delivery, physically retired legacy Graph and SDK runtime paths, published the current Tutor Harness contract, and passed the final sequential verification matrix.

### Main Changes

- Activated the verified-only proactive default path with per-user cutover admission, bounded daily/concurrent delivery, and learner-safe activity/inbox effects.
- Retired active Graph/router/SDK runtime, legacy Desktop flows, obsolete worker paths, and direct dependency pins after the caller audit was clean.
- Published the current Tutor Harness architecture, release-readiness ledger, historical-document archive, and cross-layer Trellis quality guidance.

### Git Commits

| Hash | Message |
|------|---------|
| `469ab8c` | (see git log) |
| `4d9c90b` | (see git log) |

### Testing

- [OK] API: 275 passed; `ruff check .`; `python -m mypy app` (99 source files); and `uv lock --check`.
- [OK] Executor: 9 passed; Desktop: `pnpm --dir .\aearn desktop:check`.
- [OK] Trellis task validation, current-document link audit, scoped legacy/dependency audit, and `git diff --check`.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 83: Close Tutor Harness rearchitecture parent

**Date**: 2026-07-30
**Task**: Close Tutor Harness rearchitecture parent
**Branch**: `main`

### Summary

Closed the planning-only Tutor Harness rearchitecture parent after all nine independently validated children were archived; confirmed cross-child integration gates, completed legacy retirement, current source-of-truth documentation, and the recorded release verification matrix.

### Main Changes

- Closed the planning-only parent without invoking `task.py start`; all nine independently verifiable children are archived under the July 2026 task archive.
- Confirmed the final cross-child boundary: verified-only Tutor entry, governed capabilities and durable effects, container execution safety, proactive/Curator limits, API/SSE/Desktop contract, and clean-slate legacy retirement.
- Preserved a coherent source-of-truth trail through the current Tutor Harness documentation, release-readiness ledger, and dated historical Graph/SDK records.

### Git Commits

| Hash | Message |
|------|---------|
| `9f65449` | (see git log) |
| `30772e9` | (see git log) |
| `92492c6` | (see git log) |
| `00b57a9` | (see git log) |
| `cd7bcce` | (see git log) |
| `9b615cd` | (see git log) |
| `d796435` | (see git log) |
| `f0ee786` | (see git log) |
| `002ba37` | (see git log) |
| `469ab8c` | (see git log) |
| `4d9c90b` | (see git log) |

### Testing

- [OK] Parent context manifest validation passed; task tree reports 9/9 children done and all nine child directories are archived.
- [OK] Child 08 release evidence records sequential API (275 passed), Ruff, Mypy, lock, executor (9 passed), Desktop, docs-audit, and cutover/legacy-retirement checks.
- [OK] Final repository state is clean and `git diff --check` passes before parent archive.

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 84: 稳定 Tutor TurnRun 与 DeepSeek 决策契约

**Date**: 2026-08-03
**Task**: 稳定 Tutor TurnRun 与 DeepSeek 决策契约
**Branch**: `main`

### Summary

完成 Tutor 每普通消息独立 TurnRun、DeepSeek Responses 严格决策、公开历史与 Desktop 导航，并通过完整本地质量门。

### Main Changes

## Completed

- Implemented strict DeepSeek primary JSON decision handling: exact `deepseek-v4-flash` Responses routing, bounded same-primary repair, strict typed title/continuation contract, and redacted provider failures.
- Changed ordinary Tutor chat to durable conversation history plus a fresh finite TurnRun per normal learner message; first turn is atomic/idempotent and latest input supersedes the older foreground run.
- Added server-owned conversation list/history cursors and allowlisted public-process projections; Desktop now supports local drafts, recent/all conversation navigation, hydration, compact disclosure cards, and selected-run-only SSE.
- Closed the post-provider race with an autocommit dispatcher, run-loop rechecks before every unsafe boundary, and locked terminal persistence guards.
- Fixed proactive effect CAS to pass the injected Clock into repository time checks, preventing deterministic scheduler/test leases from being evaluated against wall-clock time.

## Verification

- `uv --directory .\aearn\services\api lock --check && uv --directory .\aearn\services\api run python -m pytest -q` -> 321 passed.
- `uv --directory .\aearn\services\api run ruff check app tests` -> passed.
- `uv --directory .\aearn\services\api run python -m mypy app` -> 99 source files, no issues.
- `pnpm --dir .\aearn desktop:check` -> `tsc && vite build` passed.
- Trellis task validation and `git diff --check` passed; the in-app browser smoke remained blocked by the local browser kernel asset error.

## Closeout

- Archived `08-02-deepseek-responses-decision-contract`, `08-02-tutor-conversation-turnrun-history`, and parent `08-02-tutor-run-lifecycle-deepseek-responses`.
- No push or deployment was performed.


### Git Commits

| Hash | Message |
|------|---------|
| `ffaa073` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 85: 完成 LearningTrack 领域基础并清理工作树

**Date**: 2026-08-05
**Task**: 完成 LearningTrack 领域基础并清理工作树
**Branch**: `main`

### Summary

提交此前已验证的 DeepSeek V4 Flash token budget 修复；完成 LearningTrack、版本化计划、掌握度证据、Tutor scope 与 execution tier 领域基础；通过 PostgreSQL、Pytest、Ruff、Mypy、lock、Trellis validate 和 diff 检查；隔离无关 Trellis/agent 工具链修改并归档首个产品 child。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `36905cb` | (see git log) |
| `82c3edf` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 86: 完成 Tutor 最新输入与教学相关性 child

**Date**: 2026-08-08
**Task**: 完成 Tutor 最新输入与教学相关性 child
**Branch**: `main`

### Summary

实现并验证 Tutor 权威当前输入、最新历史选择和教学策略，归档当前 child。

### Main Changes

## 完成内容

- 归档 child `08-04-tutor-latest-input-teaching-relevance`，父任务保持 planning，未启动其他 child。
- 通过精确 `tutor_run_input_events(run_id, input_revision)` 证据加载权威当前输入，并与可裁剪历史分离。
- ContextBuilder 优先保留当前输入、选择最新历史后按时间顺序呈现；无法安全表示时在 provider 前类型化失败。
- 初始与 repair provider 提示共享最新意图教学策略，补充确定性 eval 与显式 opt-in live smoke。
- 更新后端质量规范与 Tutor Harness 架构文档。

## 验证

- focused Pytest: 71 passed
- input merge/run loop/SSE: 23 passed
- PostgreSQL bootstrap/repository/context loader: 15 passed
- full Pytest: 365 passed
- Ruff: passed
- Mypy: 109 source files, passed
- uv lock --check: passed
- task.py validate: passed
- git diff --check: passed（仅 Windows LF/CRLF 提示）

## 提交

- `784239e feat(tutor): preserve authoritative latest input context`
- `81faa49 chore(task): archive 08-04-tutor-latest-input-teaching-relevance`

未执行 live-provider smoke、push、deploy 或生产数据修改。


### Git Commits

| Hash | Message |
|------|---------|
| `784239e` | (see git log) |
| `81faa49` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 87: 完成 Tutor Provider Usage 与缓存计量

**Date**: 2026-08-08
**Task**: 完成 Tutor Provider Usage 与缓存计量
**Branch**: `main`

### Summary

实现 provider-neutral LLMUsage、Responses/Chat usage 解析、每个实际 attempt 的安全 receipt、PostgreSQL append-only 持久化与作用域约束；补齐 focused/完整 Pytest、Ruff、Mypy、lock、Trellis validate 和文档规格验证。

### Main Changes

- 新增 provider-neutral `LLMUsage`，归一化 Responses 与 Chat Completions 的 input、cached、output、reported total 和 reasoning token。
- 为首次请求与 same-provider repair 分别生成 `TutorProviderAttemptReceipt`，并保持 run-level `model_call_count` 的 decision-boundary 语义。
- 新增 scoped append-only `tutor_provider_attempt_receipts`、幂等重放、复合外键、derived token CHECK 和 immutable trigger。
- 更新 Tutor runtime、数据库、QA 文档与 Trellis 后端可执行规格。

### Git Commits

| Hash | Message |
|------|---------|
| `43d954f9a3a1061d2a1efe3a16e9b808257eb3fa` | (see git log) |

### Testing

- [OK] focused Pytest：81 passed。
- [OK] 完整 API Pytest：374 passed。
- [OK] PostgreSQL scope、幂等、CHECK、FK 与 append-only trigger 覆盖通过。
- [OK] Ruff、Mypy（110 source files）、`uv lock --check`、Trellis validate 与 `git diff --check` 通过。

### Status

[OK] **Completed**

### Next Steps

- 当前 child 已归档；下一条 dependency-satisfied child 是 `08-04-tutor-adaptive-context-budget-planner`，待单独启动。


## Session 88: Tutor 自适应上下文预算规划器

**Date**: 2026-08-08
**Task**: Tutor 自适应上下文预算规划器
**Branch**: `main`

### Summary

实现 provider-bounded 全请求上下文规划、确定性序列化、自适应预算模式、受限重建、安全策略持久化与 cache-aware 校准，并通过聚焦测试、PostgreSQL 约束测试、全量 Pytest、Ruff、Mypy、uv lock 和 diff 检查。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `d681f1a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 89: 完成 Tutor 长对话摘要检索与压缩闭环

**Date**: 2026-08-08
**Task**: 完成 Tutor 长对话摘要检索与压缩闭环
**Branch**: `main`

### Summary

完成 budget-selected recent window、结构化 summary v2、leased transient evidence retrieval、幂等 curation persistence、latest valid summary recovery、PostgreSQL scope/append-only constraints、聚焦与全量验证，并同步 backend spec 与 source-of-truth 文档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ddc6233` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 90: 完成 Tutor 上下文治理评估与可观测性

**Date**: 2026-08-10
**Task**: 完成 Tutor 上下文治理评估与可观测性
**Branch**: `main`

### Summary

完成 versioned v2 eval fixture、安全 receipt、usage/cache/repair attempt 计量、四档预算与 summary 综合回归、calibration 报告和默认禁用的五轮真实 provider smoke；完整 API 404 passed、1 skipped，Ruff、Mypy、lock、Desktop、Trellis 与 diff hygiene 通过。

### Main Changes

- 新增 `tutor_context_eval_v2` fixture、`tutor_context_eval_receipt_v1` 安全证据与 `tutor_context_calibration_v1` 分组报告。
- 组合 current input、history、usage/cache、四档预算、repair attempt、summary retirement/correction/stale contract，并增加 PostgreSQL 集成 fixture。
- 增加默认禁用的 `TUTOR_REAL_PROVIDER_SMOKE` 固定五轮边界，区分 fake contract、real behavior sample 与 release approval。
- 同步 Tutor runtime、QA acceptance、release-readiness 与 backend executable quality spec。

### Git Commits

| Hash | Message |
|------|---------|
| `f0f8eb8` | feat(tutor): add context governance evals |

### Testing

- [OK] Complete serial API suite: `404 passed, 1 skipped in 33.41s`；skip 为未启用的 real-provider smoke。
- [OK] Ruff、Mypy（114 source files）、`uv lock --check`、Desktop `tsc && vite build`。
- [OK] Trellis validate、fixture JSON validation 与 `git diff --check`。

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 91: 完成学习首页与对话式计划制定

**Date**: 2026-08-10
**Task**: 完成学习首页与对话式计划制定
**Branch**: `main`

### Summary

实现服务端权威的 LearningTrack 首页、对话式计划草案能力、可确认计划会话与独立浮动计划窗口；完成后端测试、网页端交互验证、规范同步和任务归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `802693a` | (see git log) |
| `3ebc420` | (see git log) |
| `bf0a414` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 92: 完成 LessonDocument 与权威来源课程能力

**Date**: 2026-08-11
**Task**: 完成 LessonDocument 与权威来源课程能力
**Branch**: `main`

### Summary

完成不可变标准与个性化 LessonDocument、权威来源快照、受控 authoring、assignment 冻结与显式迁移、verified-only API 和网页端阅读器；完整 API suite 425 passed、1 skipped，Ruff、Mypy、lock、Trellis validate、git diff 与多视口浏览器验收通过。

### Main Changes

- 新增严格注册的十类 Lesson block、canonical hash、来源引用与个性化继承质量门。
- 新增不可变标准/个性化文档、来源快照、assignment 冻结/提案/显式迁移和 durable authoring lifecycle。
- 扩展 Grounding source version 与原始文档 hash，完成 verified-only Lesson API、用户数据治理和 cutover inventory。
- 新增网页端 Lesson 阅读器、严格 unknown parser、引用证据面板和失败重试/版本迁移状态。
- 同步 product、architecture、QA source-of-truth 与 backend/frontend Trellis code-spec。

### Git Commits

| Hash | Message |
|------|---------|
| `b73dfa0` | (see git log) |
| `b4a56e8` | (see git log) |
| `a1e335e` | (see git log) |

### Testing

- [OK] 聚焦后端矩阵 122 passed。
- [OK] 完整 API suite 425 passed、1 skipped；唯一 skip 为默认禁用的真实 provider smoke。
- [OK] Ruff、Mypy（128 source files）、lock check、Trellis validate 与 `git diff --check` 通过。
- [OK] 网页端 1440px、900px、390px 浏览器状态流、引用、冻结、proposal、迁移和无溢出验证通过；按任务边界未运行 Desktop build/typecheck。

### Status

[OK] **Completed**

### Next Steps

- 父任务继续保持 `planning`；下一候选子任务为 `08-04-exercise-gates-execution-unlock`。


## Session 93: 完成练习 Gate、模块诊断与受控执行

**Date**: 2026-08-11
**Task**: 完成练习 Gate、模块诊断与受控执行
**Branch**: `main`

### Summary

完成服务端权威练习 Gate、append-only Attempt、模块诊断显式确认、现有 execution queue 复用、网页端 Gate/诊断交互、source-of-truth 与可执行规范同步；完整 API/executor/TypeScript/浏览器/Trellis 验证通过，未运行真实 provider、reviewed image fleet、Desktop build 或部署。

### Main Changes

- 新增不可变 exercise/private rubric/Gate binding authority、append-only Attempt/result/hint、模块诊断与显式 skip 确认。
- 以 owner/source one-of 复用现有 execution intent/job 队列，并扩展 executor trusted-input scope，不创建第二队列或虚假 Tutor effect。
- 完成 Lesson Gate 面板、same-Attempt 轮询、stale result、四 execution tier 披露和模块诊断 modal。
- 同步 product、API、数据库、Harness runtime、QA source-of-truth 与 backend/frontend Trellis 可执行规范。

### Git Commits

| Hash | Message |
|------|---------|
| `9904619` | (see git log) |

### Testing

- [OK] API lock/Ruff/Mypy 通过；完整 suite 为 442 passed、1 skipped。
- [OK] Executor lock/Ruff/Mypy 通过；完整 suite 为 11 passed。
- [OK] 前端 `tsc --noEmit` 通过；1440px、900px、390px 真实网页端 Gate/诊断流程通过。
- [OK] Trellis validate 为 implement 37 条、check 27 条；归档自引用路径已重写并复验通过；`git diff --check` 通过。

### Status

[OK] **Completed**

### Next Steps

- 当前子任务已归档；父任务继续保持 `planning`，不在本次收尾中启动后续子任务。


## Session 94: Tutor 权威上下文事实与运行时收口

**Date**: 2026-08-12
**Task**: Tutor 权威上下文事实与运行时收口
**Branch**: `main`

### Summary

完成 Tutor 权威规划事实重建、Provider/决策协议强化、桌面端交互改进及 Trellis 工具链更新；验证通过后归档当前任务，并准备转入统一受控 Action Runtime。

### Main Changes

- 提交 Trellis 工作流与本地 Agent 工具链更新
- 实现权威 planning facts、typed provider runtime 与诊断能力
- 改进 Tutor 桌面会话体验与交互规格

### Git Commits

| Hash | Message |
|------|---------|
| `4d1531d` | (see git log) |
| `69d0a64` | (see git log) |
| `33df9f9` | (see git log) |

### Testing

- [OK] 后端上下文矩阵 60 passed、运行时矩阵 97 passed
- [OK] Ruff、mypy、Trellis validate、desktop:check 均通过

### Status

[OK] **Completed**

### Next Steps

- 启动 08-12-tutor-controlled-action-runtime 并复核已有决策协议实现与剩余缺口


## Session 95: 完成 Tutor 统一受控 Action Runtime

**Date**: 2026-08-12
**Task**: 完成 Tutor 统一受控 Action Runtime
**Branch**: `main`

### Summary

实现统一 Action descriptor/invocation/receipt 生命周期、PostgreSQL 持久化、资源与预算门禁、取消/重试/验证/恢复、权威 context 回灌，并迁移 grounding、plan drafting 与 runner authority adapter；完整 API 482 passed、executor 11 passed，Ruff/Mypy/Trellis validation 全绿。

### Git Commits

| Hash | Message |
|------|---------|
| `74555e4` | (see git log) |

### Status

[OK] **Completed**


## Session 96: 完成模型代码审核练习

**Date**: 2026-08-12
**Task**: 完成模型代码审核练习
**Branch**: `main`

### Summary

完成 model_code_review 后端、Desktop、PostgreSQL 生命周期、export/reset/cutover、文档与真实浏览器验收；完整 API/Executor/Desktop/Trellis 质量门通过并归档子任务。

### Main Changes

- 实现模型代码审核 contract、确定性评分、authoring/validation/publication 与统一 Action/executor 接入
- 实现 Desktop 结构化 finding、证据与结果交互
- 补齐安全 export/reset/cutover、NO ACTION DEFERRABLE 数据库约束与 source-of-truth

### Git Commits

| Hash | Message |
|------|---------|
| `cb2d15a` | (see git log) |
| `9747472` | (see git log) |
| `18e2aed` | (see git log) |
| `982bb8e` | (see git log) |

### Testing

- [OK] API 491 passed, 1 skipped；Ruff/Mypy/lock 通过
- [OK] Executor 11 passed；Ruff/Mypy/lock 通过
- [OK] Desktop build、Trellis validate、git diff check 与 390/900/1440 浏览器验收通过

### Status

[OK] **Completed**

### Next Steps

- 启动并执行 08-04-spaced-review-sessions


## Session 97: 完成间隔复习与 ReviewSession

**Date**: 2026-08-12
**Task**: 完成间隔复习与 ReviewSession
**Branch**: `main`

### Summary

完成 track-scoped 间隔复习队列、有限 ReviewSession、关键前置短 Gate、复习 Attempt/finalization、计划迁移、诊断 skip 调度以及 API/数据库/导出/文档集成。

### Main Changes

- 新增 tutor_review_* authority、纯调度策略与 verified-only LearningTrack review API。
- 复用现有 ExerciseVersion、模型代码审核评分和 executor queue，保持旧 /api/reviews 与 review_states 退役。
- 同步 source-of-truth 与后端 code-spec，并记录退役路径文件名不可复用的 cutover 守卫。

### Git Commits

| Hash | Message |
|------|---------|
| `0e3ea7f` | (see git log) |

### Testing

- [OK] Review focused 15 passed；完整 API 506 passed、1 skipped。
- [OK] API lock/Ruff/Mypy 通过；Executor 11 passed；Desktop production build 通过。
- [OK] Trellis validate 与 git diff --check 通过。

### Status

[OK] **Completed**

### Next Steps

- 启动 08-04-learning-workspace-context-references，实现三栏工作区与结构化上下文引用。


## Session 98: 完成三栏学习工作区与结构化上下文引用

**Date**: 2026-08-13
**Task**: 完成三栏学习工作区与结构化上下文引用
**Branch**: `main`

### Summary

交付 Tutor 结构化上下文引用的 PostgreSQL/API/history/context-loader 全链路，以及响应式 TrackLearningWorkspace、Lesson 选段、Gate/执行/Review 反馈引用和完整 ReviewSession Desktop 主路径；全量 API 509 passed, 1 skipped，Ruff、mypy、Desktop build 与 1440x900/1024x768/390x844 浏览器验收通过。

### Git Commits

| Hash | Message |
|------|---------|
| `b43eb6a` | (see git log) |
| `eb6e8a1` | (see git log) |

### Status

[OK] **Completed**


## Session 99: 完成编程语言教学 Agent 任务树

**Date**: 2026-08-13
**Task**: 完成编程语言教学 Agent 任务树
**Branch**: `main`

### Summary

完成最终集成修复、四语言端到端矩阵、cutover schema 清单、source-of-truth 收敛，并归档最后子任务与父任务。

### Main Changes

- 修复 Review 候选在 LIMIT 前未按用户/主线发布范围过滤的问题。
- 显式分类全部 tutor_* cutover target/shared 表并新增 schema reconciliation 回归。
- 完成 Python、JavaScript、TypeScript、SQL 计划到复习证据矩阵和语言 tier 真实性审计。
- 更新当前架构、产品、API、数据库、开发、executor、验收与 readiness 文档。

### Git Commits

| Hash | Message |
|------|---------|
| `1b081f5` | (see git log) |

### Testing

- [OK] API lock/Ruff/Mypy 通过；全量 515 passed, 1 skipped。
- [OK] 权威事实、Action、cutover、安全投影与集成串行批次 84 passed。
- [OK] Executor lock/Ruff/Mypy 通过，11 passed；Desktop check、DB smoke、Trellis validate、diff hygiene 与响应式浏览器检查通过。

### Status

[OK] **Completed**

### Next Steps

- 真实 provider smoke、reviewed container image fleet、push、deploy 与生产迁移仍需单独批准。


## Session 100: Tutor 会话事件与持久调度底座

**Date**: 2026-08-14
**Task**: Tutor 会话事件与持久调度底座
**Branch**: `codex/codex-like-tutor-conversation`

### Summary

完成 Codex-like Tutor Child 1：建立 thread_turn_v2 公开会话/轮次/条目契约、conversation-global append-only 事件与 snapshot/SSE、PostgreSQL 权威 durable dispatch job、Celery wakeup/reconciler、legacy_v1 兼容、规格与架构文档；完整 API 测试 548 passed、1 skipped，Ruff、Mypy、lock、compileall、Trellis validate 与 diff check 通过。

### Git Commits

| Hash | Message |
|------|---------|
| `19dbd2e` | (see git log) |
| `b04898d` | (see git log) |

### Status

[OK] **Completed**


## Session 101: 完成 DSH 派生 UI Foundation

**Date**: 2026-08-15
**Task**: 完成 DSH 派生 UI Foundation
**Branch**: `codex/codex-like-tutor-conversation`

### Summary

完成白色浅色 Aearn semantic tokens、DSH-derived primitives/icons、sonner adapter、MIT NOTICE/upstream mapping 与 Vitest 组件测试基础，并归档 Child 2。

### Main Changes

- 新增 aearn/apps/desktop/src/ui/dsh-derived 的 tokens、primitives、icons、feedback 与公共 exports。
- 新增 THIRD_PARTY_NOTICES.md、UPSTREAM.md，并把 UI foundation 可执行契约同步到 frontend component code-spec。
- 新增 Vitest、Testing Library、jsdom 配置与 14 个组件/边界测试，不接入 Tutor 业务状态。

### Git Commits

| Hash | Message |
|------|---------|
| `555bc06f` | (see git log) |
| `c2e89987` | (see git log) |
| `49fb4140` | (see git log) |

### Testing

- [OK] pnpm --dir .\aearn\apps\desktop test：2 files / 14 tests passed。
- [OK] pnpm --dir .\aearn desktop:check：TypeScript 与 Vite production build passed。
- [OK] cargo check：Tauri Rust shell passed；生成 schema 的仅换行变化已恢复。
- [OK] task.py validate、pnpm frozen lockfile、git diff --check passed。

### Status

[OK] **Completed**

### Next Steps

- 启动 08-14-tutor-typed-request-authority-turns，先核对 Child 1 已归档并读取后端 specs/source-of-truth。


## Session 102: 完成 Tutor 类型化请求与权威续轮

**Date**: 2026-08-15
**Task**: 完成 Tutor 类型化请求与权威续轮
**Branch**: `codex/codex-like-tutor-conversation`

### Summary

完成五类 typed request、来源 turn 终结、fresh response/authority turn、planning catalog、approval/receipt CAS、public snapshot/event 与 Desktop type/API seam，并归档 Child 3。

### Main Changes

- 新增 tutor_interaction_requests、response_to_request_id、completion_reason 与复合 scope/CAS 约束。
- v2 continuation 改为 typed request；learner response 与 verified authority receipt 创建 fresh TurnRun 和独立 dispatch job。
- 同步 API/runtime/database/acceptance source-of-truth 与 backend/frontend code-spec。

### Git Commits

| Hash | Message |
|------|---------|
| `a1523e5f` | (see git log) |
| `90ad4a57` | (see git log) |

### Testing

- [OK] API 全量 pytest：560 passed, 1 skipped。
- [OK] Ruff、Mypy、uv lock --check、compileall、DB bootstrap twice、Trellis validate、git diff --check 通过。
- [OK] Desktop Vitest：14 passed；desktop:check 的 tsc + Vite build 通过。

### Status

[OK] **Completed**

### Next Steps

- 启动 08-13-tutor-queue-steer-interrupt-control，消费 pending request authority，不重定义 request contract。
