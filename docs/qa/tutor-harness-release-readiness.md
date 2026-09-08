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
| Default proactive delivery | verified terminal signal → candidate → durable exact Skill selection → only `tutor.activity.record` → activity/inbox；unverified is `cutover_unverified` with no provider/run | `tests/tutor/test_tutor_proactive_default_delivery.py` + candidates/policy/curation/routes/worker set | **Pass — 23 tests** | fake provider proves boundary, not real teaching quality |
| Core Harness/effects | capability default-deny、finite loop、execution prohibition、run repository/selection evidence、activity projection | capability/run-loop/execution/run-repository/activity focused set | **Pass — 31 tests** | full API suite passed; fake/controlled boundary only |
| Schema/cutover | repeatable bootstrap, exact clean-slate receipt, blocked contamination/checkpoint scope | `tests/database/test_db_bootstrap.py tests/integration/test_harness_cutover.py` | **Pass — 13 tests** | full serial suite and audit passed; no real account data |
| Background safety | background public text stripped; no chat/notification/runner/subprocess/memory direct write; curation remains default-off | `proactive_worker.py` composition + default-delivery regression | **Pass** | no long-running production worker soak test is claimed |
| Legacy code/package retirement | active Graph/router/SDK source and direct package pins removed in current patch; dated docs moved to archive | current working-tree diff | **Pass — active source/dependency audit returned no matches** | archive/transition historical text remains intentionally retained |
| Documentation split | current runtime/index docs added/updated; transition and four dated docs labelled historical | current documentation patch | **Pass — current-contract link and whitespace check found 0 broken links** | historical docs remain deliberately labelled |

## Proactive default fixture proof

The regression in `tests/tutor/test_tutor_proactive_default_delivery.py` deliberately
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
hidden: `tests/runners/test_tutor_executor_job_store.py` intentionally commits a
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
| Eval schema / safe receipt | `tests/tutor/test_tutor_evals.py` | **7 passed** | v1 兼容；v2 receipt 不含 raw prompt/history/provider body/reasoning/credential |
| Smoke default boundary | `tests/smoke/test_tutor_context_eval_smoke.py tests/smoke/test_tutor_real_provider_smoke.py` | **2 passed, 1 skipped** | `TUTOR_REAL_PROVIDER_SMOKE` 未启用；未构造真实 provider |
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
- 该 2026-08-10 截面尚未交付 LessonDocument、ReviewSession、练习 Gate 和完整三栏学习工作区；后续 dated sections 记录各 child 的实际完成证据。
- receipt、SSE 与文档证据不保存 raw prompt/history、provider body、reasoning、credential 或 transport body。

## LessonDocument 与权威来源证据（2026-08-11）

**任务：** `08-04-lesson-document-authority-grounding`
**状态：** **In progress — not a release approval**

本轮在当前 `main` 工作树中新增不可变标准/个性化 `LessonDocument`、来源快照、引用与 Gate slot、assignment 冻结/提案/显式迁移、可恢复 authoring run、verified-only API 和单页网页阅读器。所有 provider 行为使用 fake author/offline fixture；未调用真实 provider，未提交、push、部署或修改生产数据。

### 当前验证证据

| Gate | 命令或证据 | 结果 | 边界 |
| --- | --- | --- | --- |
| Lesson contract / quality / authoring | `tests/learning/test_lesson_document_contracts.py tests/learning/test_lesson_document_quality.py tests/learning/test_lesson_document_authoring.py` | **9 passed** | 严格注册 block union、canonical hash、来源/引用/覆盖质量门和 fake author failure-closed |
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

## 练习 Gate、模块诊断与受控执行证据（2026-08-11）

**任务：** `08-04-exercise-gates-execution-unlock`
**状态：** **Completed locally — not a release approval**

本轮在当前 `main` 工作树中新增不可变 exercise/private-rubric/Gate binding authority、assignment-scoped Gate state、append-only Attempt/submission/result/hint、模块诊断与显式 skip 确认、existing execution intent/job owner seam、executor trusted input，以及 Lesson 内网页 Gate/diagnostic UI。所有练习使用 curated fixture 或 disposable fake API；未调用真实 provider、真实生产 executor，未构建/签名/发布 reviewed image fleet，也未提交、push、部署或修改生产数据。

### 当前验证证据

| Gate | 命令或证据 | 结果 | 边界 |
| --- | --- | --- | --- |
| API dependency lock | `uv --directory .\aearn\services\api lock --check` | **Pass** | 无 lock drift |
| API Ruff | `uv --directory .\aearn\services\api run ruff check app tests` | **Pass** | `All checks passed` |
| API Mypy | `uv --directory .\aearn\services\api run python -m mypy app --no-incremental` | **Pass — 138 source files** | 无类型抑制 |
| Complete API suite | `uv --directory .\aearn\services\api run python -m pytest -q` | **442 passed, 1 skipped in 71.60s** | 唯一 skip 为默认禁用的真实 provider smoke；PostgreSQL/bootstrap 串行 |
| Executor dependency lock / Ruff / Mypy | executor `lock --check`、`ruff check aearn_executor tests`、`mypy aearn_executor --no-incremental` | **Pass — 9 source files** | 仅本地 contract；无 Docker/生产 runtime claim |
| Complete executor suite | `uv --directory .\aearn\services\executor run python -m pytest -q` | **11 passed** | 覆盖 Gate private trusted-input scope；未启动 reviewed container fleet |
| Frontend type contract | `pnpm --dir .\aearn\apps\desktop exec tsc --noEmit` | **Pass** | 只做 TypeScript contract 检查；未运行 Desktop/Tauri build |
| 网页 Gate/diagnostic | `http://127.0.0.1:1420` + disposable stateful fake API | **Pass** | prepare/hint；container pending→same Attempt poll；stale；submit；teaching/static/unavailable；diagnostic fail/pass/confirm；1440/900/390 无水平溢出，console 0 error/0 warning，focus 可见 |
| Privacy / DOM | 浏览器 DOM marker audit + API/repository tests | **Pass** | 未出现 `private_test`、`reference_answer`、`rubric_hash`、`container_name`、`docker.sock`、`image_reference`；export 省略完整 submission |
| Trellis / diff hygiene | child validate + `git diff --check` | **Pass — implement 37 / check 27** | Archive this child only; parent remains planning and is not started |

### 网页端证据边界

- in-app Browser 完成导航、状态机、DOM、响应式、console 与 focus 验证；in-app screenshot capture 超时，因此只对截图采集使用 standalone Playwright fallback。
- 截图保存在本机临时目录：`C:\Users\PINKING\AppData\Local\Temp\aearn-gate-desktop-1440.png`、`C:\Users\PINKING\AppData\Local\Temp\aearn-gate-panel-desktop.png`、`C:\Users\PINKING\AppData\Local\Temp\aearn-diagnostic-mobile-390.png`，未写入工作树。
- fake API、curated fixture 和 static evaluator 证明 contract、状态机、隐私与 fail-closed 边界，不证明真实容器隔离、镜像供应链、性能、可靠性或生产 readiness。
- 公开 `container_verified` 仍要求 reviewed immutable image lock 与兼容 executor health；本轮没有这些发布前置条件。`teaching_local` 仍仅 development-only，`static_only` 明确 `not_run`，`unavailable` 不产生 host fallback。
- Local work commit, child archive, and session journal are development closeout only; they do not authorize push, deploy, release, or production-data changes.


## 模型代码审核练习证据（2026-08-12）

**任务：** `08-04-model-code-review-exercises`。本轮实现 `model_code_review` 公私 contract、
六场景/四语言 fixture、确定性 finding scorer、user-scoped authoring、
`model-code-review.validate@1.0.0`、共享 executor trusted-input、Lesson Gate/API 与 Desktop
结构化审核界面，并补齐 local export/reset/cutover。

### 当前自动化证据

- API focused：63 passed。
- API complete：491 passed，1 skipped。
- Executor complete：11 passed；Executor Ruff/Mypy 通过。
- API lock、Ruff（152 source files）与 Mypy 通过。
- Desktop `tsc && vite build` 通过。
- 真实浏览器临时 harness：结构化 finding 增加/字段阻断、evidence assisted 状态与结果映射通过；390/900/1440 均无页面水平溢出，键盘焦点可见，console warning/error 为零。
- PostgreSQL bootstrap 与完整 authoring→publication→evidence→structured Attempt→export→reset
  回归通过；private candidate/rubric/test/matcher 与 finding 自由文本不进入 export。

### 非声明

上述结果不证明真实 provider 的生成质量，也不批准生产 executor image。浏览器证据只使用
临时本地前端 harness 与本地 Vite 服务；不得被解释为生产数据、真实模型或生产容器验证。

## 间隔复习与 ReviewSession 证据（2026-08-12）

**任务：** `08-04-spaced-review-sessions`。本轮实现 track-scoped schedule/event、有限
ReviewSession、warmup/hint/item/finalization、`review_submit` Attempt owner、existing executor
reuse、`AuthoritativeContextSnapshot`、计划迁移、诊断 skip 低频 seed、首页 actionable count、
local export/reset/cutover，以及 verified-only API。旧 `review_states`、`review_logs`、
`review_seed_banks` 和 top-level `/api/reviews` 未恢复。

### 当前自动化证据

- Review focused：**15 passed**，覆盖纯调度、critical prerequisite 即时 Gate、两题 batch、
  exactly-once finalization、候选不足恢复、cross-user、revision migration、API 与 local data。
- Focused Ruff 与 `git diff --check`：**Pass**。
- API dependency lock、Ruff、Mypy（162 source files）：**Pass**。
- 完整 API 串行 suite：**506 passed, 1 skipped in 97.85s**；唯一 skip 为默认禁用的 real-provider smoke。
- Executor lock/Ruff/Mypy 与完整 suite：**Pass，11 passed**。
- Desktop `tsc && vite build`：**Pass**。
- Trellis child validate 与最终 `git diff --check`：**Pass**；任务归档在 product commit 后执行。未获得 push/deploy 授权。

### 非声明

上述证据不证明真实 provider 生成质量、生产 container image 隔离或完整三栏 Review UI；本轮未
调用真实 provider、未启动生产容器 fleet、未 push、未 deploy，也不是 release approval。

## 最终教学 Agent 集成证据（2026-08-12）

**任务：** `08-04-learning-agent-integration-migration-qa-docs`。本轮完成四种核心语言闭环、Review 候选 scope 修复、cutover 全表分类、旧导航/文档收敛与最终 source-of-truth 审计。所有业务 fixture 使用本地 PostgreSQL、确定性 scorer/fake local runner；未调用真实 provider、未启动 Docker conformance 或生产 container fleet。

### 实现与缺陷修复证据

- `test_learning_agent_integration_matrix.py` 对 Python、JavaScript、TypeScript、SQL 分别创建 LearningTrack/plan、可信来源快照、immutable Lesson、active assignment、Gate、terminal safe result、private submission、mastery/progress、due ReviewSession 与 exactly-once review evidence/schedule event。
- 同一矩阵断言空 `image-locks.json` 下 public execution-required Gate 为 `unavailable` 且 `allowed_actions=[]`；注入的本地执行只为 `teaching_local`。Java/HTML/CSS 是扩展验证，Go/C# 为 partial local，Rust 为 public unavailable，C++ 为 public static-only。
- 集成矩阵构造 12 个当前 user/track 不可访问的 `registered_author` 候选，发现 Review SQL 原来会先全局 `LIMIT 12`、再由 service 丢弃跨作用域 publication，合法 curated candidate 可能被饿死。修复后 publication scope 在 SQL 的 `ORDER BY/LIMIT` 前应用，service 端仍保留防御复核。
- cutover target inventory 显式覆盖全部 user-owned `tutor_*` 表；shared allowlist 仅含 catalog、executor health、共享 immutable exercise/rubric 和 diagnostic version。真实 PostgreSQL schema reconciliation test 要求两组恰好覆盖全部 `tutor_*` 表且不重叠。
- Desktop 移除“既有 Graph 流程保持不变”的残留文案；当前源代码只装配 verified Learning Home、planning、LearningTrack workspace、Lesson/Gate、Review 与 track-scoped Tutor。

### 最终自动化证据

| Gate | 命令或证据 | 结果 | 边界 |
| --- | --- | --- | --- |
| 核心语言 / tier matrix | `uv --directory .\aearn\services\api run python -m pytest -q tests/integration/test_learning_agent_integration_matrix.py` | **5 passed** | 四种核心语言 + 扩展/降级/空 lock 真实性 |
| 串行权威与隐私聚焦批次 | planning facts/context eval/references + Action/execution/redaction + cutover/bootstrap/Gate/Review/model-review/integration files | **84 passed in 29.72s** | PostgreSQL bootstrap-heavy tests 单进程串行 |
| API dependency lock | `uv --directory .\aearn\services\api lock --check` | **Pass — Resolved 54 packages** | 无 lock drift |
| API Ruff | `uv --directory .\aearn\services\api run ruff check app tests` | **Pass** | `All checks passed!` |
| API Mypy | `uv --directory .\aearn\services\api run python -m mypy app --no-incremental` | **Pass — 163 source files** | 无新增类型抑制 |
| Complete API suite | `uv --directory .\aearn\services\api run python -m pytest -q -rs` | **515 passed, 1 skipped in 99.04s** | 唯一 skip：显式未启用的 real-provider smoke |
| Executor lock / Ruff / Mypy | executor `lock --check`、`ruff check aearn_executor tests`、`mypy aearn_executor --no-incremental` | **Pass — Resolved 29 packages / 9 source files** | 本地 contract，不是生产容器批准 |
| Complete executor suite | `uv --directory .\aearn\services\executor run python -m pytest -q` | **11 passed in 0.57s** | 未运行 Docker conformance；reviewed lock 数为 0 |
| Desktop typed build | `pnpm --dir .\aearn desktop:check` | **Pass — 60 modules transformed** | `tsc && vite build`；不是 Tauri installer/release build |
| PostgreSQL smoke | `psycopg ... select 1` | **Pass — 1** | 本地数据库可连接 |
| Route retirement audit | 当前 FastAPI route inventory | **Pass — 60 `/api/*` routes；retired routes 0；LearningTrack routes 29** | `/api/dashboard`、`/api/plans`、`/api/learning-sessions`、top-level `/api/reviews` 均未注册 |
| 浏览器轻量复核 | `http://127.0.0.1:1420/` | **Pass** | verified Learning Home；1008px 无水平溢出；console 0 error/0 warning；Graph 残留文案不存在 |
| Trellis / diff hygiene | child validate + `git diff --check` | **Pass** | active task artifacts 与文档无控制字符或 whitespace error |

一次探索性操作曾把三个会调用 `bootstrap_database()` 的聚焦 pytest 进程并行启动，PostgreSQL 按预期出现 `deadlock detected` / `tuple concurrently updated`。这些并行结果不计入证据；随后按开发文档要求在一个 pytest 进程中串行重跑同一权威/隐私范围，结果为 **84 passed**。完整 API suite 也以单进程串行方式通过。

### 权威事实、Action 与隐私结论

- confirmed `weekly_minutes=1800`（30 小时）在超过 recent-history 上限、summary 阻塞/暂不可用和相同 input revision replay 后仍来自 persisted authoritative facts，`confirmed_question_reasked_count` 保持 0；纠正会追加 revision，不原地改写。
- planning、Review、模型代码审核与右侧 Tutor 使用 persisted `AuthoritativeContextSnapshot` 或结构化 safe references；不从聊天正文重新猜 confirmed facts。
- grounding、plan drafting、runner execution 与 model-review validation 通过统一 Action/receipt/verification authority；stale/superseded 或 verification budget failure 不发布第二个 terminal authority。
- execution completion 与 verification success 分列。未 verified/current 的结果不能成为 Tutor fact、Gate/mastery/unlock 或 effect。
- public API、SSE/history/process、trace/checkpoint safe projection、activity/inbox、export 与本 ledger 均不包含完整 submission、hidden tests、expected findings、reference answer/private rubric、raw provider body/reasoning、命令、路径、容器或 secret。

### 非声明与剩余风险

- `aearn/infra/executor/image-locks.json` 仍为空；当前没有任何语言获得 public `container_verified`。
- real-provider smoke 是唯一自动化 skip，原因是未设置 `TUTOR_REAL_PROVIDER_SMOKE=1` 和显式 provider 配置；没有从 fake/offline 结果推断真实模型质量。
- 未运行 Docker conformance、reviewed image build/sign/publish、生产 executor smoke、Tauri installer、push、deploy 或生产数据迁移。
- 本地代码、测试、文档、Trellis child/parent closeout 只证明 repository readiness，不是发布批准。


## Codex Sidecar 集成证据（2026-08-18）

Child 1-6 的 protocol、Runtime、typed tools、durable projection、controlled plan-drafting cutover 与 QA/doc evidence 已在本地集成。完整 API suite 为 **660 passed, 2 skipped**；Codex focused matrix 为 **66 passed**，public/SSE/redaction focused matrix 为 **21 passed**；Ruff、Mypy（192 source files）、compileall、lock、bootstrap twice 与 Desktop build 均通过。进程泄漏计数和 credential literal scan 均为 0。

一次真实 `deepseek-v4-flash` Responses tool-repair smoke 已在 Child 1 获用户明确批准后通过；本 QA 不重复产生第二次付费调用。详细 exact target、failure matrix、rollback、evidence retention 和 non-claims 见 [`codex-sidecar-integration-readiness.md`](./codex-sidecar-integration-readiness.md)。这些本地结果不批准生产 rollout、push、deploy、Codex 安装/升级或所有 Tutor scope 切换。

## 课程意图与 Runtime 流 Parent 最终集成证据（2026-08-21）

Parent `08-21-tutor-planning-intent-runtime-stream-reliability` 已在课程意图 Generated UI 与 Runtime delta coalescing 两个 Child 独立提交、验证和归档后完成最终集成复核。PostgreSQL deterministic matrix 覆盖 Python 自动确认、frontend/backend、多语言、conflict 与 full catalog；fake App Server 覆盖 5,000 单字符 reasoning delta、2,500-delta LearningPlan tool repair、timer/size/boundary flush、feature-off、独立语义预算、source/projection receipt 与 terminal/replay/gap/restart 回归。

Parent 最终质量门为完整 API suite **689 passed, 2 skipped**、Ruff、Mypy（194 source files）、lock、compileall、bootstrap twice、Desktop 48 tests/build、Parent Trellis validate 与 `git diff --check` 全部通过。新一轮三视口 DOM/交互/刷新复验无溢出、overlay 或 console error/warning；截图调用超时，因此截图证据沿用同一工作区 Child 2 已保存的三张临时目录截图，不宣称产生了新的 Parent 截图。详细验收映射见 Parent `research/final-integration-evidence.md`。未调用真实 provider；该证据不构成 push、部署或生产发布批准。

## Closed teaching action Loop 本地证据（2026-08-23）

Trellis Child `08-22-harness-closed-teaching-action-loop` 已在本地 PostgreSQL 与 fake/disabled provider 上完成 backend-only 验证。实现覆盖 exact `tutor.lesson-teaching@1.0.0`、required `TEACHING_SESSION` context、strict one-action `teaching_step`、bounded focus reducer、atomic checkpoint/action-receipt/message/run commit、server-owned Action Shelf、Free Reading reactive policy、authority-refresh successor session、completion pause 与显式 latest-roadmap transition。

最终证据：

- Child 2 focused Harness/teaching/context/provider/eval matrix：**187 passed**；
- PostgreSQL bootstrap 连续执行两次：均完成；bootstrap/cutover/teaching-governance smoke：**5 passed**；
- 完整 API suite：**711 passed, 2 skipped in 213.87s**；两项 skip 保持既有显式 gated posture；
- `ruff check app tests`：通过；
- `mypy app --no-incremental`：**199 source files** 无问题；
- Child Trellis validate 与 `git diff --check`：通过，只有已知工作树 line-ending warning；
- standalone `TeachingSessionService` import smoke：通过，未保留新增 circular import。

验证额外复现并修正了两个数据库/authority 问题：早期 `fk_tutor_teaching_checkpoint_source_stimulus` 的 `RESTRICT` 会使已有 action checkpoint 的 local reset 在中途失败，bootstrap 现只在旧 predicate/constraint 存在时迁移为 deferred `NO ACTION`；progress authority 更新后旧 active session 现追加 `authority_pause` checkpoint 并置为 blocked，successor 冻结新 authority，避免把 completed evidence 写入 stale session。

本轮未调用真实 provider，未运行 Desktop/Tauri、未 push、未部署、未修改生产数据，也不构成发布批准。Desktop 主次布局与 closed teaching action 的跨 Gate/Review 自动触发仍由后续 child 验证。

## 2026-08-23：Adaptive teaching integration Child 4 本地证据

- Focused Child 4 batch：**50 passed**；teaching/Gate/Review/Lesson regression：**33 passed**；`test_tutor_adaptive_teaching_evals.py`：**4 passed**。
- 完整 API suite：**716 passed, 2 skipped**（单进程串行，182.93s）。Ruff 全通过；Mypy：**200 source files**。
- Desktop Vitest：**58 passed**；`desktop:check` / Vite production build通过。
- 生成 disposable PostgreSQL database，空库执行 bootstrap 两次后为 **134 public tables**、`tutor_teaching_sessions=0`，随后强制关闭连接并删除该临时 database。
- Browser 使用 disposable stateful fake API/provider验证 Guided ↔ Free Reading、草稿跨 mode保留、reload/reconnect、Action Shelf与 1440×900 / 900×900 / 390×844；三个视口 `scrollWidth == clientWidth`、overlay=false、console error/warning=0、protected marker=[]。fake SSE主动关闭用于触发可恢复 `STREAM_INCOMPLETE`，未当作生产流稳定性证明。
- 未调用真实 provider、真实 executor或生产数据；未 push、部署或发布。以上仅为本地工程就绪证据，不构成 provider、部署、production migration或 release批准。

## 2026-09-01：Execution result Artifact Child 05 本地证据

本增量完成 strict `safe-execution-result-v2`、v1 history adapter、bounded public table/location/output、terminal Attempt 到唯一 result Artifact/source update 的幂等 projection、terminal-only result-evaluation continuation、bounded safe context，以及 exact result Turn 的 `MODEL_UNAVAILABLE` deterministic fallback。Desktop 完成 Attempt v1/v2 exact parser、failure-first result renderer、hidden identity/diagnostic omission、nonempty output disclosure、内部 table scroll、summary 单次展示和返回 source focus。

验证证据：

- shared execution contract：**34 passed**；executor full suite：**13 passed**，Ruff/Mypy 通过；
- focused serial PostgreSQL/API matrix：**60 passed**；full API suite（显式排除 real-provider marker）：**827 passed, 2 deselected in 554.51s**；
- changed-file API Ruff、13-file slice Mypy、compileall、`git diff --check`：通过；
- Desktop full Vitest：**13 files / 110 tests passed**；`desktop:check`：Vite **109 modules transformed**；
- persisted Artifact conversation event v3 后再次 bootstrap：通过；
- disposable browser fixture 在 **1440×900 / 900×900 / 390×844 / 390×844 reduced-motion** 下 document/body/workspace 均 `scrollWidth == clientWidth`。窄屏 table 只在内部滚动（`318 / 532`），每个视口均为 one Tutor/Composer/source/result；failure/output/table/return focus 可交互，source Artifact scroll 恰好一次，reduced motion 使用 `auto`；无 hidden ID、diagnostic、Submit、protected marker、script、overlay、alert 或 console warning/error。

本轮没有真实 provider smoke、真实 executor/container 运行、Docker conformance、生产 image build/sign/publish、Tauri installer、push、deploy 或生产迁移。以上只证明本地 repository contract 与 learner-safe UI readiness，不构成发布批准。

## 2026-09-02：Code Editor 与隔离 Browser Preview Child04 本地证据

本增量交付 conversation-native 单文件 Monaco、进程内 draft/view state、显式 Run exact source、stale/read-only，以及 Tauri 2.11.1 app-owned `CustomProtocol` child webview。default capability 从 window-wide `windows:["main"]` 收紧为 `webviews:["main"]`；`build.rs` 的 `AppManifest::commands` 让所有 Preview app commands进入 ACL，只给 main autogenerated allow permissions，command仍校验 exact main caller。Preview 使用 incognito、generation-specific data directory、sandboxed learner iframe、strict CSP、navigation/new-window/download deny、source SHA-256、nonce/scope/version/generation/sequence bridge，以及 learner-frame heartbeat驱动的 bounded Preview-only watchdog。web target/native unavailable不回退 main-DOM JavaScript或历史 A3a。

验证证据：

- Desktop full Vitest：**17 files / 126 tests passed**；覆盖 latest-draft Run、untracked/stale result、terminal read-only、model/view state carry-forward/no focus、source scope/hash binding、initial hash race、400ms debounce、bounds、event replay、error hide、bounded heartbeat recreate与 unmount close；
- `desktop:check`：**Pass，Vite 131 modules transformed**；
- Rust `cargo fmt --check`、`cargo check`、`cargo clippy --all-targets --all-features -- -D warnings` 通过；`cargo test`：**9 passed**；
- Rust security matrix覆盖 exact main capability + app-command ACL、CustomProtocol、source escaping、script-only sandbox、CSP no-network/forms/objects/external frames、default-port-only top-level navigation、popup/download deny、nonce/source Artifact/session/version/generation/replay/extra/oversize拒绝、source hash/bounds，以及 recreate data-directory rotation；
- disposable native WebView2 fixture 通过真实 `pnpm desktop:dev` + remote-debugging CDP执行并已删除。`/json/list` 只暴露 **1 个 target**：`page / Aearn / http://127.0.0.1:1420/`；`aearn-preview-*` child未暴露，因此没有把 main target或 Vite web fallback冒充为 child DOM证据；
- native 已知恶意 source断言：interaction event到达；fetch/WebSocket、parent、top navigation、popup被阻断；唯一下载文件前后均不存在；main WebView console无 error/warning。WebView2 learner subframe可观察到 `__TAURI_INTERNALS__` 对象，但 app/core invoke因 child无 capability、app-command ACL和 exact caller guard而不可完成；Preview CSP另行阻断 network/connect；
- main WebView direct command smoke成功创建/关闭 hidden Preview；错误 nonce/version返回 `PREVIEW_HOST_IDENTITY_REJECTED`，错误 source hash返回 `PREVIEW_HOST_SOURCE_INVALID`；
- native smoke发现并修复两项自动化未覆盖问题：Windows CustomProtocol实际回调带默认 HTTPS port，allowlist现允许协议默认端口但拒绝非默认端口/userinfo/fragment；无限循环后复用同一 WebView2 data directory无法可靠恢复，recreate现轮换 generation directory。最终 hang序列为 `ready -> creating -> recreating -> creating -> error`，只自动重建一次并显示 `PREVIEW_HOST_UNRESPONSIVE`，main draft/focus保持；切回安全 source最终恢复 `ready`、console `safe:ready` 与 interaction `native.recovered`；
- 临时 `main.tsx` 修改、fixture、backup与 native进程均已清理，1420/9333端口关闭；Child Trellis validate 与 `git diff --check` 通过。

## 2026-09-02：Teaching Demonstration Artifact Child06 本地证据

本增量只从 published `demo_v2` handle 物化静态/交互演示；模型不能修改 source、步骤、expected event 或 duration。交互完成要求 current isolated Preview 的 exact event key、canonical bounded JSON payload、nonce/generation/continuous sequence；静态完成仅累计 foreground/current/60%-visible/render-ready 的内存 visible clock。一个 append-only completion receipt 绑定一条 completion/continuation lineage，重复请求幂等、冲突证据 fail closed；演示不创建 Attempt、mastery 或 progress。Desktop 以只读代码、3px progress 和 reduced-motion discrete progress 呈现，interactive source 仍只在 Child04 native Preview 内运行。

验证证据：

- focused PostgreSQL/API 25 passed，覆盖 `complete_demo -> receipt -> continuation -> replay/conflict`、bootstrap twice、append-only、cutover/export/reset/delete、priority；full API（排除 `real_provider`）**837 passed, 2 deselected**；Ruff、Mypy（242 source files）、compileall 通过；
- Desktop **18 files / 132 tests passed**，`desktop:check` 通过（Vite **131 modules transformed**）；覆盖 visibility/focus/IntersectionObserver/render-ready/remount/reduced-motion、read-only、exact bridge payload、replay/gap/spoof 和 renderer rerender；
- Rust Preview host **9 passed**，fmt/check/clippy 通过；`task.py validate`、`git diff --check` 通过；
- 未运行真实 provider/executor、Docker conformance、生产 image build/sign/publish、Tauri installer、push、deploy或生产迁移。本记录不构成 production sandbox认证或 release批准。

本轮未调用真实 provider/executor，未运行 Docker conformance、生产 image build/sign/publish、Tauri installer、push、deploy或生产迁移；本记录不构成 production sandbox认证或 release批准。

## 2026-09-02：Knowledge Check、Hint、Remediation Child07 本地证据

本增量交付 strict `knowledge_check_v1` 多题型、server-owned scorer/disclosure、immutable response、H1-H3/direct-answer assistance receipt、D1-D5 base difficulty、capability-scoped remediation/transfer selector，以及 receipt-backed mainline evaluation continuation。普通 teaching context 排除 reserved successor purpose；evaluation context 只保留已持久化的 exact handle，且 required candidate 不能被 1,200 字符 bound 静默驱逐。Artifact facade 不写 Attempt、mastery 或 progress。

验证证据：

- focused serial PostgreSQL/API：**65 passed**；覆盖 action replay/conflict/stale、H1-H3/direct answer、receipt immutability、exact successor/capability/pre-limit filtering、evaluation continuation、route/branch/cutover/bootstrap/schema manifest；
- complete API（`-m "not real_provider"`）：**845 passed, 2 deselected in 277.21s**；API Ruff 全通过，Mypy **243 source files**，lock check 通过；
- Desktop final full Vitest：**19 files / 137 tests passed**；新增解锁页/focus regression 的 focused KnowledgeCheck：**5 passed**；`desktop:check` 通过，Vite **134 modules transformed**；
- 真实 Chromium 临时 Vite harness 直接挂载正式组件/CSS：1440x900、900x900、390x844 与 reduced-motion 均 `document/body overflow=0`；portal parent 为 `BODY`，打开 overlay 的 main height delta 为 `0`；H1/H2/H3 仅产生三个显式 action，Arrow/Home/End 为 H2/H1/H3，非当前页 `aria-hidden + inert`，Escape 恢复 exact“提示”按钮，console warning/error 为零。临时 harness 与 1421 端口已清理；
- persisted `tutor_conversation_event_v3` 后 bootstrap twice 的既有专门回归包含在 full API；Child task validate 与最终 `git diff --check` 在提交前复验。

未运行真实 provider、真实 executor/container、Docker conformance、生产 image build/sign/publish、Tauri installer、push、deploy 或生产迁移。Chromium fake-action harness 证明正式组件交互与布局，不证明 Tauri installer 或生产教学质量，本记录不构成 release approval。


## 2026-09-02：AI Code Review Artifact Child08 本地证据

本增量将既有 model-review authoring/validation/Practice authority additive 接入 conversation-native
`model_code_review_v2`。新的 immutable `LearningItemModelReviewContentV2` 可发布 exact source/modified
diff；v1 item/history 继续 code-only。server canonical builder 生成并复核 code/hash/hunk/line map，
结构化 finding 只接受 current presentation、single hunk/side、完整连续 range 和 presentation-enabled
closed taxonomy。评分、receipt、successor 与 continuation 均为 server authority；不新增第二个
Gate/Review/Attempt/mastery/progress。

唯一一次只读、限时 Child08 Trellis check 报告 **0 P0 / 2 P1 / 3 P2**，随后由主线程全部修复：
production diff 路径、self-hashed malformed map、`uncertain + findings`、缺少 `complete_review` authority
以及 receipt/rollback/scope/export/bootstrap/Desktop 坏路径覆盖。检查子代理没有修改文件，完成后已关闭。

最终验证证据：

- focused serial PostgreSQL/API matrix：**105 passed in 87.62s**；post-check Action/model-review rerun：
  **33 passed in 14.91s**；
- complete API（`LLM_TYPE=disabled`、`-m "not real_provider"`）：
  **856 passed, 2 deselected in 495.41s**；
- API Ruff：通过；Mypy：**245 source files** 无问题；compileall 与 `uv lock --check`：通过，
  **55 packages**；
- Desktop full Vitest：**20 files / 143 tests passed**；`tsc && vite build`：通过，
  **135 modules transformed**；
- real Chromium temporary harness：1440x900 为 `1436/1436`，900x900 为 `896/896`，390x844 与
  reduced-motion 均为 `386/386` document scroll/client width；Monaco 横向内容保持内部，不产生页面
  overflow。真实交互覆盖 finding 添加、切换 uncertain 清空、再次提交 exact v2 payload、可选
  `weak_testing` 不越权显示、terminal read-only；final console warning/error 为 **0/0**；
- private submission 只进入 append-only receipt；UPDATE/DELETE `23514`、缺少 remediation 全回滚、
  cross-scope/stale version、safe export、reset/delete、receipt 存在时 bootstrap twice、fragment 110 v3
  compatibility、contracts-only `artifacts/__init__.py` 均有自动化或直接审计证据；
- docs/spec link/whitespace audit：**10 files / 0 errors**；`git diff --check`：通过，仅配置的
  LF-to-CRLF warning。临时 port 1422 已停止，临时 harness 目录已删除。

本轮未调用真实 provider、真实 executor/container 或 Docker conformance；未执行生产 image
build/sign/publish、Tauri installer、push、deploy 或生产数据迁移。以上是本地 repository/UI
contract readiness，不是 live model quality、生产隔离或 release approval。

## 2026-09-02：SQL Learning Workspace Child09 本地证据

本增量交付 structured `sql_workspace_v2` Learning Item、post-commit local SQLite Run、public grid/hidden
summary redaction、Learning Item-owned Attempt 与 conversation-native Monaco/Schema/Result UI。历史 v1 继续
可读；`artifacts/__init__.py` contracts-only/lazy、fragment 110 event-v3 compatibility 和受保护原型均未改。
唯一一次原生 Child09 check 在明确 10 分钟边界内未返回报告，已强制终止且未修改文件；没有启动第二个
check，主线程完成后续缺陷修复、全量验证、提交与归档。

最终验证证据：

- focused serial PostgreSQL/API matrix：**71 passed in 41.95s**；schema manifest/bootstrap/runner/compiler
  post-fix：**40 passed in 5.67s**；
- complete API（`LLM_TYPE=disabled`、`-m "not real_provider"`）：首次发现新增 fragment 未进入显式
  manifest expectation，修复后为 **865 passed, 2 deselected in 426.02s**；
- API Ruff 与 Mypy：通过，Mypy **246 source files**；compileall、`uv lock --check`、Artifact import smoke
  通过；shared SafeExecutionResult **34 passed**；Executor 非 Docker conformance **11 passed**；
- Desktop full Vitest：**21 files / 146 tests passed**；TypeScript check 与 Vite build 通过，
  **138 modules transformed**；
- real Chromium temporary harness：1440x900 Editor/Schema 为 **574/574px**，900x900 为 **434/434px**，
  390x844 上下 pane 均为 **358x319.7px**；20-row result 在三视口均为内部滚动，document/body 无横向
  overflow。复制 `learners.mentor_id` 前后 Monaco 文本、selection 与焦点不变；等待不自动 Run，点击后
  只提交最新 query；reduced-motion 命中，fresh page console warning/error 为 **0/0**；临时 Vite/fixture 已清理；
- public/hidden dataset 使用不同标记值并验证 public serialization 不含 private identity/value；SQL policy
  覆盖 mutation/multiple statement/PRAGMA/ATTACH、sqlite catalog/unpublished table、extension/file function、
  32-column、row/cell/payload、timeout/resource limit、FK target/type 与 table insertion order；
- PostgreSQL 证据覆盖 admission commit before execution、exact item/materialization/scope、no Gate binding、
  result-evaluation continuation、replay、no mastery write、persisted SQL v2 row bootstrap twice、cutover/export/
  reset 与 explicit schema manifest；Trellis context 和 `git diff --check` 最终通过。

未运行真实 provider、真实 executor/container、Docker conformance、生产 image build/sign/publish、Tauri
installer、push、deploy 或生产数据迁移。该记录是本地 contract/readiness 证据，不构成生产发布批准。


## 2026-09-02：Exact 来源文档 Drawer Child10 本地证据

本增量复用 immutable LessonDocument/source snapshots、persisted lesson_selection context reference 与 source_inspector_v1 Artifact provenance，新增 verified-only exact resolver 和一个稳定挂载的右侧 document drawer。请求只接受 document/hash/assignment/block/citation、context reference ID 或 Artifact ID/version；服务端校验 conversation/track/knowledge scope、safe payload hash、Artifact presentation/source ref、assignment/document/block/excerpt/range/citation。历史 assignment 返回原 frozen document 与“内容已更新”，不按文本或 DOM 顺序猜当前相似段落。Desktop exact parser 复核 source echo、scope、assignment/document/hash/status/citations；Drawer 只滚动自己的 panel，以 absolute dashed overlay 定位，并保持 Tutor/Lesson/Artifact/Monaco/Preview state。

唯一一次原生 Child10 trellis-check 按 read-only、8 分钟范围和 2 分钟 focused-test cap 启动；超过有界等待仍未返回报告后已终止，未改文件，也未启动第二次 check。主线程随后发现并修复 retry 后快速 retarget 可能被旧 promise 覆盖，以及 close commit 前 requestAnimationFrame focus 的真实浏览器竞态；最终由 AbortController ownership 和 post-commit zero-delay timer 覆盖回归。

最终验证证据：

- focused PostgreSQL/API：6 passed；覆盖 direct Lesson、persisted context reference、source-inspector Artifact、strict extra field、stale hash/version、cross-user 与 migration historical；
- complete API（LLM_TYPE=disabled、not real_provider）：865 passed, 2 deselected in 259.03s；Ruff、Mypy（248 source files）、compileall、uv lock --check（55 packages）和 Artifact/Lesson/Tutor import smoke 通过；
- Desktop focused exact-source matrix：6 files / 35 tests；最终 full Vitest：24 files / 160 tests；tsc + Vite production build通过，139 modules transformed；
- disposable Chromium 正式组件/CSS：1440x900、900x900、390x844 与 reduced motion 的 document/body/workspace overflow 全为 0，conversation scroll exact 不变；normal scroll 命中 exact block，historical retarget 保留旧文档；390px drawer 为 88vw，backdrop 不关闭，button/Escape 归还 exact trigger；mount count保持 1且 draft 不变；reduced motion 为 auto + animation none；fresh console warning/error 为 0/0；absolute highlight 期间 target offset/size 与 stage height不变；临时 harness、server、browser 均已清理；
- Trellis validate（implement 4 / check 1）、docs/spec link/control-character audit（6 files / 0 errors）与 git diff --check 通过；artifacts/__init__.py 仍 contracts-only/lazy，schema fragment 110 未修改且 full API保留 event_v3 bootstrap regression。

未调用真实 provider、真实 executor/container、Docker conformance、生产 image build/sign/publish、Tauri installer、push、deploy 或生产数据迁移。以上为本地 contract/UI readiness，不构成 release approval。


## 2026-09-02：Tutor Conversation Learning Artifact platform Child12 integration gate

Child12 does not create another Artifact, Attempt, Result, Branch, Gate, Review, or Item authority. It owns the final executable contract/version reconciliation, AC1-AC20 evidence map, cross-family focused regression, source-of-truth correction, rollout/rollback order, and final local command ledger. The new integration audit compares backend Pydantic unions with the Desktop static registry/actions, required routes/default-off gates, 21-fragment schema order and fragment-110 event-v3 compatibility, contracts-only Artifact package imports, protected prototype presence, concrete family test modules, and current documentation markers.

Pre-check evidence is 98 serial API/PostgreSQL tests and 13 Desktop files / 113 tests. The audit found and corrected one real docs drift: database-schema.md said 20 fragments although SCHEMA_FRAGMENT_NAMES contains 21. The single bounded read-only native check reported **0 P0 / 2 P1 / 2 P2**: family evidence initially proved only file presence, documentation markers were too generic, and the executable matrix did not yet pin every item-reference/action/snapshot boundary. Main-thread fixes converted those checks to exact happy/bad-path symbols, Child12-only headings, backend action fields, Artifact version/item-reference membership, and Desktop v2-v5 compatibility. The check agent changed no files and was closed; no second check ran.

Final local gate:

- complete serial API (`LLM_TYPE=disabled`, `-m "not real_provider"`): **869 passed, 2 deselected in 622.12s**;
- API/worker/shared Ruff and compileall: passed; Mypy: **255 source files**; API lock: **55 packages**;
- shared execution contracts: **34 passed**; executor non-Docker suite: **11 passed in 1.24s**, Ruff passed, Mypy **9 source files**, lock **29 packages**;
- Desktop focused Monaco/SQL stabilization: **2 files / 6 tests**; final full Vitest: **24 files / 160 tests**; TypeScript + Vite production build: **139 modules transformed**. The integration run exposed resource-sensitive per-character `userEvent.type` timeouts in two Monaco mocks; replacing them with one React `change` event preserved the same explicit-action assertions without weakening the global timeout;
- Tauri Rust `cargo fmt --check`, `cargo check`, strict Clippy and `cargo test`: passed, **9 tests**;
- a uniquely named disposable local PostgreSQL database completed explicit bootstrap twice, then schema/bootstrap/cutover plus persisted event-v3 compatibility: **21 passed in 27.37s**; the database was dropped in the same guarded command;
- source-of-truth link/control audit: **8 files / 33 relative links / 0 errors**; all **13** parent/child Trellis contexts validated; final `git diff --check` passed apart from configured LF-to-CRLF warnings.

Child12 changes no product UI runtime. AC19 therefore reuses the recorded current-workspace Child03-10 Chromium/native matrices for 1440x900, 900x900, 390x844, keyboard/focus, reduced motion, scroll isolation, Preview attacks and clean console; this final task claims no new browser or native Preview run. Real provider, Docker conformance, reviewed image build/sign/publish, Tauri installer, production migration, push, deploy, release and production data changes remain not executed. These results are local engineering acceptance, not production release approval.

## 2026-09-08：Python LessonDocument 有界修复本地证据

本轮对已有可信来源的 Lesson authoring 增加同 provider/model 的一次共享修复机会，发送服务端构造的安全反馈，持久化私有 attempt diagnostic，并统一 prepare replay/cancelled GET shape。Desktop 仅收紧重复 citation 校验，现有页面状态机保留。

- 后端实施首轮：独立 PostgreSQL 数据库串行执行反馈、authoring、Lesson service 与 bootstrap 测试，38 passed in 19.04s；Ruff、Mypy app（249 source files）、lock check 通过。
- Desktop 实施：5 files / 41 tests passed；独立审查 TypeScript noEmit 与 4 files / 37 tests passed。
- 浏览器：Playwright CLI/Edge 在本地 Vite 渲染真实 LessonDocumentPage 与 strict API parser，fake failed -> explicit retry -> preparing -> ready，11 个合成正文块和来源可见。最终验证轮次无 console warning/error、pageerror 或 Vite overlay；浏览器本地网络权限修正后 HMR 正常。
- 验证用 API 响应全为 fixture，外部请求阻断，未创建课程、未调用真实 provider。临时浏览器与 Vite 已关闭，初始 API/worker/Desktop 未运行状态保留。
- 最终独立审查无阻塞项：补充 cancelled prepare replay、expired lease reclaim budget、fatal issue 截断保护与 Desktop missing prepare replay；后端 41 passed，Desktop 4 files / 38 passed，Ruff、Mypy app（249 files）、tsc --noEmit、lock check 与 diff check 通过。两轮各自独立测试库均已删除。

不声明真实 provider 生成质量、RAG v2 或 LangChain corpus 发布、全量 Desktop build、生产迁移、push/deploy/release 或现有用户课程数据修改。
