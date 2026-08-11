# Tutor Harness Release Readiness Ledger

**日期：** 2026-07-29
**任务：** `07-22-tutor-integration-qa-and-docs`
**状态：** **In progress — not a release approval**
**证据边界：** 本记录对应当前 `main` 工作树的未提交 Child 08 patch。没有提交、
push、部署或真实 learner/provider/executor 操作。

## 当前结论

**本地完整质量矩阵已通过，但这仍不是 release approval。** 当前 Child 08
working-tree patch 已把 active product runtime 收敛为 verified-only Tutor
Harness：旧 Graph/router/SDK source、旧 Desktop 页面/状态和 API direct dependency
pins 已退休；当前 route registration 只保留 health、users、course、environment、
cutover 和 Tutor 表面。

主动建议不再是默认关闭的 blocker。默认 scheduler 为 enabled/non-hard-paused，
但只允许拥有当前 `verified` cutover receipt 的用户，在 per-user pause、daily
budget、cooldown、concurrency、lease/retry 与 circuit gate 全部通过后，产生至多
一条 learner-safe activity/inbox 建议。curation/inferred memory 和 learner-code
execution 仍默认关闭。fake-provider evidence 不等于真实模型教学质量或生产
worker 可靠性。

本轮最终 serial verification 结果为：API **275 passed**、API Ruff 通过、Mypy
在 **99 source files** 上通过、API lock check 通过、standalone executor **9
passed**、Desktop `tsc && vite build` 通过、Trellis task validation 通过、
active legacy source/dependency audit 为零匹配、current-doc link/whitespace check
通过、`git diff --check` 通过。没有提交、push、部署或 task archive。

## Evidence context and safety posture

| 字段 | 当前事实 |
| --- | --- |
| 基线提交 | `55ae7049f36ba30392da87e94e39f57311c2c7de`，Child 07 journal closeout 之后的 `main` HEAD |
| 当前修改 | Child 08 working-tree patch，包含 legacy retirement、Tutor composition、Desktop、schema、tests 和 documentation reconciliation |
| Fixture policy | disposable PostgreSQL users、fake provider/clock/executor seam；不调用真实模型，不提交 learner code，不保留 raw learner content |
| Provider posture | `LLM_TYPE=disabled` 或注入 deterministic provider；primary-only failure mapping 在 test seam 验证 |
| Executor posture | `TUTOR_EXECUTOR_ENABLED=false`，无 reviewed immutable image lock 时保持 safe unavailable；没有启动 runtime/container |
| Scheduler posture | 默认全局 scheduler enabled；测试可以显式限定 `user_id` 以隔离 fixture，production worker 的 normal scan 保持 `user_id=None` |
| 排序规则 | PostgreSQL/bootstrap-heavy pytest 必须串行运行，不能并行共享 bootstrap schema |

## 已完成的 focused evidence

| Gate | Contract / rejected behavior | 命令或测试 | 当前结果 | 残余风险 |
| --- | --- | --- | --- | --- |
| Config / static quality | proactive default config 与 worker composition 可 import、lint、type-check；Desktop 可编译 | `compileall -q app`、modified-path `ruff`、`mypy app`、`pnpm desktop:check` | **Pass（full matrix 已完成）** | no live provider claim |
| Default proactive delivery | verified terminal signal → candidate → durable exact Skill selection → only `tutor.activity.record` → activity/inbox；unverified is `cutover_unverified` with no provider/run | `tests/test_tutor_proactive_default_delivery.py` + candidates/policy/curation/routes/worker set | **Pass — 23 tests** | fake provider proves boundary, not real teaching quality |
| Core Harness/effects | capability default-deny、finite loop、execution prohibition、run repository/selection evidence、activity projection | capability/run-loop/execution/run-repository/activity focused set | **Pass — 31 tests** | full API suite passed; fake/controlled boundary only |
| Schema/cutover | repeatable bootstrap, exact clean-slate receipt, blocked contamination/checkpoint scope | `tests/test_db_bootstrap.py tests/test_harness_cutover.py` | **Pass — 13 tests** | full serial suite and audit passed; no real account data |
| Background safety | background public text stripped; no chat/notification/runner/subprocess/memory direct write; curation remains default-off | `proactive_worker.py` composition + default-delivery regression | **Pass** | no long-running production worker soak test is claimed |
| Legacy code/package retirement | active Graph/router/SDK source and direct package pins removed in current patch; dated docs moved to archive | current working-tree diff | **Pass — active source/dependency audit returned no matches** | archive/transition historical text remains intentionally retained |
| Documentation split | current runtime/index docs added/updated; transition and four dated docs labelled historical | current documentation patch | **Pass — current-contract link and whitespace check found 0 broken links** | historical docs remain deliberately labelled |

## Proactive default fixture proof

The regression in `tests/test_tutor_proactive_default_delivery.py` deliberately
uses a disposable verified user, deterministic provider and explicit test clock.
It proves all of the following without raw learner content:

1. A durable terminal interactive run becomes a safe terminal signal based only
   on run identity, terminal outcome and terminal timestamp hash.
2. Candidate admission requires the current cutover receipt and default
   scheduler/preference gates.
3. The active run writes durable `tutor_run_skill_selections` evidence for
   `tutor.learner-state@1.0.0`, then commits only `tutor.activity.record`.
4. The outcome appears as learner-safe activity and inbox data. It does not
   add a learner-visible conversation message or desktop notification.
5. An unverified user reaches `cutover_unverified` no-action with no provider
   call and no proactive run.

## Final verification results (2026-07-29)

Commands were executed **serially**. The API suite was rerun after the resolved
fixture-cleanup regression described below; its green result is the final test
result for this patch.

| Command / audit | Result | Notes |
| --- | --- | --- |
| `uv --directory .\aearn\services\api run python -m pytest` | **275 passed in 54.02s** | PostgreSQL/bootstrap-sensitive suite was not run in parallel. |
| `uv --directory .\aearn\services\api run ruff check .` | **All checks passed** | Includes the committed-fixture cleanup regression. |
| `uv --directory .\aearn\services\api run python -m mypy app` | **Success: no issues in 99 source files** | API application surface. |
| `uv --directory .\aearn\services\api lock --check` | **Pass** | Resolved 51 packages; no lock drift. |
| `uv --directory .\aearn\services\executor run python -m pytest` | **9 passed in 6.56s** | Unit/contract coverage; real Docker conformance still requires reviewed locks. |
| `pnpm --dir .\aearn desktop:check` | **Pass** | `tsc && vite build`; 46 modules transformed. |
| `pnpm --dir .\aearn dev:status` | **Command pass** | PostgreSQL/Redis healthy; API/Desktop intentionally not running; local state file reports stale PIDs from 2026-06-11. |
| `python .\.trellis\scripts\task.py validate ...` | **All validations passed** | `implement.jsonl` and `check.jsonl` shapes valid. |
| Scoped active source/dependency audit | **0 matches** | No active `app.agents.graphs`, LangGraph, Agents SDK, `LANGGRAPH_ENABLED`, or direct legacy package pin in API app/tests/manifest/lock. |
| Current-doc link/whitespace check | **Pass** | 40 internal current-contract links checked; 0 broken links. |
| `git diff --check` | **Pass** | No diff whitespace errors. |

### Resolved full-suite fixture regression

The first final API run reached **273 passed, 2 failed**. The failure was not
hidden: `tests/test_tutor_executor_job_store.py` intentionally commits a
`tutor_persistence` fixture for independent connection/`SKIP LOCKED` coverage.
The fixture now creates a verified `harness_cutovers` receipt, but its explicit
cleanup still deleted `users` first. PostgreSQL correctly rejected the delete
with `ForeignKeyViolation`; the aborted cleanup transaction then leaked the
shared `test-executor` health row, causing the next test's `UniqueViolation`.

The fix deletes the exact fixture receipt before its root user, keeps cleanup
scoped to the committed fixture, and records the child-to-root cleanup rule in
`.trellis/spec/backend/quality-guidelines.md` plus the cross-layer queue
checklist. Targeted executor job-store coverage passed **4 passed**, followed
by the final **275 passed** serial API suite.

## Fixture/Desktop smoke record

The prior controlled fixture browser smoke verified a disposable `verified`
user routes directly to the empty Tutor workspace, removes stale local `planId`,
issues no legacy dashboard/resume request, and has no observed horizontal
overflow at `390x844`. It used no live provider, background worker or executor
run. This evidence remains valid only if the final Desktop build and route/
cutover tests pass; it is not a signed Tauri package test.

## Residual risks and non-claims

- Fake/deterministic providers do not prove provider quality, latency, quota,
  availability or pedagogical usefulness.
- Executor unit/contract tests do not prove a reviewed production image fleet;
  image locks remain an explicit deployment prerequisite.
- Scheduler tests do not prove long-running broker/worker operations; they
  prove policy, repository, lease and safe-composition behavior.
- Code/configuration rollback before confirmation is possible only while legacy
  rows remain. After confirmed clean-slate deletion, rollback never restores
  intentionally deleted learner history.
- This ledger is not a release approval, deployment authorization or task
  archive instruction. Any failed/pending final gate keeps the child
  `in_progress`.


## Tutor context governance eval evidence (2026-08-10)

**任务：** `08-04-tutor-context-budget-evals-observability`
**基线：** `f4cc3bb chore: record tutor context summary session`
**状态：** **In progress — not a release approval**

本轮在当前 `main` working tree 上增加 versioned `tutor_context_eval_v2` fixture、
`tutor_context_eval_receipt_v1` 安全结果、`tutor_context_calibration_v1` 分组报告、
PostgreSQL current/history 集成证据，以及默认禁用的固定五轮 real-provider smoke。
没有调用真实 provider，没有提交、push、部署或修改生产数据。

### 当前 focused evidence

| Gate | 命令/证据 | 结果 | 边界 |
| --- | --- | --- | --- |
| Eval schema / safe receipt | `tests/test_tutor_evals.py` | **7 passed** | v1 兼容；v2 receipt 不含 raw prompt/history/provider body/reasoning/credential |
| Smoke default boundary | `tests/test_tutor_context_eval_smoke.py tests/test_tutor_real_provider_smoke.py` | **2 passed, 1 skipped** | `TUTOR_REAL_PROVIDER_SMOKE` 未启用；未构造真实 provider |
| Cross-contract focused batch | eval/smoke + context builder/budget/provider/run-loop/loader/summary/repository/bootstrap | **130 passed, 1 skipped in 4.11s** | PostgreSQL/bootstrap 串行；skip 是显式 real-provider case |
| Calibration | versioned provider/protocol/capability/mode/estimator/config grouping | **Pass** | 样本不足不输出 P50/P95；报告只建议 review，不自动改生产配置 |
| Complete API suite | `uv --directory .\aearn\services\api run python -m pytest -q` | **404 passed, 1 skipped in 33.41s** | 唯一 skip 为未启用的 `real_provider` smoke |
| Ruff | `uv --directory .\aearn\services\api run ruff check app tests` | **Pass** | All checks passed |
| Mypy | `uv --directory .\aearn\services\api run python -m mypy app --no-incremental` | **Pass — 114 source files** | 无类型抑制 |
| Lock | `uv --directory .\aearn\services\api lock --check` | **Pass** | Resolved 51 packages；无 lock drift |
| Desktop | `pnpm --dir .\aearn desktop:check` | **Pass** | `tsc && vite build`；46 modules transformed |
| Trellis / diff hygiene | child validate + `git diff --check` | **Pass** | spec 更新后最终复验 |

### Evidence classification

- **Fake contract verified：** v2 deterministic cases 与前四个 owning contract 的 focused tests。
- **Real provider behavior sampled：** 否；真实 smoke 未获单独批准并稳定 skip。
- **Release approved：** 否；仍需完整串行 suite、Ruff、Mypy、lock、Desktop、Trellis、
  diff hygiene 和人工 release decision。

### 当前非声明和剩余风险

- Fake provider 不能证明真实模型教学质量、缓存命中、延迟、quota 或可用性。
- 固定 numeric latency 只验证 receipt/report contract，不是假装的真实首 token 测量。
- 单次 real-provider smoke 即使未来通过，也只是 bounded behavior sample，不是发布批准。
- 完整本地质量矩阵已经通过，但本任务仍停在 commit 审批门；没有 commit、push、deploy 或 task archive。

## Learning Home / plan builder evidence (2026-08-10)

**任务：** `08-04-learning-home-plan-builder`
**状态：** **In progress — not a release approval**

- 本地 fake/offline 与 PostgreSQL focused matrix 覆盖 planning session、typed draft、stale/idempotent confirm、LearningTrack 创建、capability/run loop/context/usage/cache/summary/SSE 回归。
- `pnpm --dir .\aearn desktop:check` 已验证 TypeScript/Vite production build。
- 真实 provider smoke 默认未执行；本证据不证明真实模型教学质量，也不是 deploy 或 release approval。
- LessonDocument、ReviewSession、练习 Gate 和完整三栏学习工作区仍由后续 child 交付；当前 CTA 明确显示未就绪。
- receipt、SSE 与文档证据不保存 raw prompt/history、provider body、reasoning、credential 或 transport body。

## LessonDocument 与权威来源证据（2026-08-11）

**任务：** `08-04-lesson-document-authority-grounding`
**状态：** **In progress — not a release approval**

本轮在当前 `main` 工作树中新增不可变标准/个性化 `LessonDocument`、来源快照、引用与 Gate slot、assignment 冻结/提案/显式迁移、可恢复 authoring run、verified-only API 和单页网页阅读器。所有 provider 行为使用 fake author/offline fixture；未调用真实 provider，未提交、push、部署或修改生产数据。

### 当前验证证据

| Gate | 命令或证据 | 结果 | 边界 |
| --- | --- | --- | --- |
| Lesson contract / quality / authoring | `tests/test_lesson_document_contracts.py tests/test_lesson_document_quality.py tests/test_lesson_document_authoring.py` | **9 passed** | 严格注册 block union、canonical hash、来源/引用/覆盖质量门和 fake author failure-closed |
| Repository / API / bootstrap / cutover | Lesson repository、Lesson routes、`test_db_bootstrap.py`、LearningTrack repository、cutover | **26 passed** | PostgreSQL 串行；覆盖 7 张 Lesson 表、约束、索引、触发器、reindex 后快照、start freeze、proposal/migration、export/reset |
| Grounding 回归 | source/fetch/processing/retrieval/citation/reindex/index/policy | **47 passed** | `source_version_label`、`source_version_kind` 与原始文档 hash/chunk hash 分离并 round-trip |
| LearningTrack / Tutor 回归 | track routes、plan sessions、context builder、run loop | **40 passed** | Lesson authority 未扩大通用 Tutor capability payload，也未注入完整课程正文 |
| Complete API suite | `uv --directory .\aearn\services\api run python -m pytest -q` | **425 passed, 1 skipped in 60.31s** | 唯一 skip 为默认禁用的真实 provider smoke；没有网络调用 |
| Ruff | `uv --directory .\aearn\services\api run ruff check app tests` | **Pass** | `All checks passed!` |
| Mypy | `uv --directory .\aearn\services\api run python -m mypy app --no-incremental` | **Pass — 128 source files** | 新增生产代码无 `type: ignore` 绕过 |
| Lock | `uv --directory .\aearn\services\api lock --check` | **Pass** | Resolved 51 packages；无 lock drift |
| 网页端阅读器 | `http://127.0.0.1:1420` + disposable stateful mock API | **Pass** | Learning Home → Lesson；missing/preparing/ready、failed→retry、start freeze、refresh proposal、显式迁移；10 种 block、1 条来源、Gate 内 0 个能力按钮；1440px/900px/390px 无水平溢出，控制台 0 error/0 warning |
| Trellis / diff hygiene | child validate + `git diff --check` | **最终复验见本任务汇报** | `implement.jsonl` / `check.jsonl` 均为 7 条；不启动父任务 |

### 网页端证据边界

- 浏览器交互、DOM、响应式和控制台验证优先使用 Codex in-app Browser；in-app screenshot 命令持续超时，因此只对截图采集使用 standalone Playwright fallback。
- 截图证据保存在本机临时目录：`C:\Users\PINKING\AppData\Local\Temp\aearn-lesson-desktop.png` 与 `C:\Users\PINKING\AppData\Local\Temp\aearn-lesson-mobile.png`，未写入工作树。
- 按任务明确边界，没有运行 `pnpm --dir .\aearn desktop:check`、Tauri build 或 Desktop typecheck；网页端 Vite 编译与真实浏览器渲染是本 child 的前端完成门。
- `exercise_gate` 仅展示冻结的公开 contract 和“练习能力将在后续任务开放”，没有 Attempt、运行、提交、评分、通过或路线解锁能力。
- fake author、fixture grounding 与 mock API 只证明 contract、状态机和安全边界，不证明真实模型教学质量、延迟、quota、可用性或发布可靠性；本记录不是 release approval。
