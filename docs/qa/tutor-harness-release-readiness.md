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
- 该 2026-08-10 截面尚未交付 LessonDocument、ReviewSession、练习 Gate 和完整三栏学习工作区；后续 dated sections 记录各 child 的实际完成证据。
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
| 核心语言 / tier matrix | `uv --directory .\aearn\services\api run python -m pytest -q tests/test_learning_agent_integration_matrix.py` | **5 passed** | 四种核心语言 + 扩展/降级/空 lock 真实性 |
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
