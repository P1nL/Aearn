# Aearn Tutor Harness 验收计划

**状态：** 当前 integration/QA 契约，2026-08-10。
**范围：** 当前 Tutor runtime、cutover、provider attempt 计量、LearningTrack、
Desktop、background scheduler、executor boundary、legacy retirement 与文档一致性。
**权威来源：** 当前代码/测试/schema；实测命令结果进入
[Release Readiness Ledger](./tutor-harness-release-readiness.md)。本计划不是
release approval，任何未通过或未执行 gate 都必须在 ledger 中保留。

## 1. 验收原则

1. **使用 fixture，不使用真实学习者。** 测试使用 disposable PostgreSQL user、
   fake provider、fake clock、fake executor/worker seam；不得调用真实模型、
   执行 learner code 或记录真实 learner content。
2. **共享 bootstrap 必须串行。** 同时运行调用 `bootstrap_database()` 的 pytest
   可能造成 database deadlock/tuple conflict。测试命令必须按本计划给出的顺序
   执行，失败不能用“并发问题”掩盖。
3. **每个坏路径要被拒绝。** 除了成功路径，必须证明切换绕过、跨用户读写、
   stale effect、无 Skill evidence、provider fallback、未注册 grounding、
   proactive code execution、raw diagnostics leak 和旧 runtime 再进入都失败。
4. **静态搜索或 build 不是前端交互证据。** legacy source/dependency/doc audit、后端测试、Desktop typed build 与网页端 fixture/browser smoke 必须按各自边界完成；最终集成必须运行 `desktop:check`，涉及交互变化时仍需真实浏览器验证。
5. **不写敏感证据。** 测试报告和 ledger 只能记录命令、计数、stable error、
   revision、fixture posture 和 residual risk；不记录 raw message/code/prompt、
   provider payload、hidden tests、checkpoint 或 secret。

## 2. 优先级与通过规则

| 级别 | 定义 | 未通过后果 |
| --- | --- | --- |
| P0 | 破坏 server-authoritative gate、用户范围、持久化、安全执行或公开 API/SSE 的缺陷 | 阻止 release/任务归档 |
| P1 | 明显的 Desktop、重试、可访问性、队列恢复或文档矛盾 | 必须修复或在 ledger 明确残余风险；本 child 默认不以“已批准发布”关闭 |
| P2 | 文案、视觉、非安全边缘可用性 | 记录并设定后续 owner，不掩盖 P0/P1 |

通过判定：P0 全部通过；P1 不得有未记录的回归；所有 final commands 成功或有精确
阻塞说明。`task.py validate`、green build 或 docs 更新单独不能代替任何 P0。

## 3. 自动化验证矩阵

| ID | 优先级 | Gate | 必须证明 | 主要证据 |
| --- | --- | --- | --- | --- |
| RT-01 | P0 | Provider boundary | 只调用配置的 primary provider；配置/响应/guardrail 失败映射 `MODEL_UNAVAILABLE`，无 cross-provider/model fallback | `test_tutor_provider_gateway.py`、`test_tutor_run_loop.py` |
| RT-02 | P0 | Bounded run loop | iteration/model/capability/effect/context/lease budget 有界；取消与 lost lease 安全结束 | `test_tutor_run_loop.py`、`test_tutor_execution_contracts.py` |
| RT-03 | P0 | Skill/capability/grounding | exact `id@version` evidence、descriptor default-deny、registry-only grounding；不能传 URL/path/shell/SQL/任意 user target | `test_tutor_skill_catalog.py`、`test_tutor_capability_gateway.py`、`test_tutor_grounding_policy.py` |
| RT-04 | P0 | Durable input/effect/replay | first-turn/fresh-turn、active normal Send FIFO Queue、显式 Steer revision、idempotency、ordered events、stale effect 与 retry logical receipt rejection/reuse、trace redaction 和 current lease CAS | `test_tutor_run_repository.py`、`test_tutor_input_merge.py`、`test_tutor_queue_control.py`、`test_tutor_effect_commit.py`、`test_tutor_trace_redaction.py` |
| RT-05 | P0 | Learner-state | immutable plan、direct-predecessor rollback、memory correction/delete、activity/inbox scope | `test_tutor_memory.py`、`test_tutor_activity.py`、Tutor route tests |
| RT-06 | P0 | API/SSE | verified gate、stable error envelope、cursor suffix、terminal ordering、stream never calls provider | `test_tutor_routes.py`、`test_tutor_sse.py` |
| RT-07 | P0 | Cutover | exact server summary/nonce/hash, atomic deletion verification, retained identity/preferences, target contamination/checkpoint fail-closed, legacy denial | `test_harness_cutover.py`、`test_db_bootstrap.py` |
| RT-08 | P0 | Default proactive delivery | verified fixture terminal signal → candidate → exact Skill selection → `tutor.activity.record` → activity/inbox；unverified candidate has `cutover_unverified` and no provider/run | `test_tutor_proactive_default_delivery.py`、`test_tutor_proactive_policy.py` |
| RT-09 | P0 | Scheduler/curation | dedupe、pause、budget、cooldown、concurrency、lease/retry/circuit、global vs scoped semantics；curation default no-call | `test_tutor_proactive_candidates.py`、`test_tutor_memory_curation_scheduler.py`、`test_tutor_memory_curator.py` |
| RT-10 | P0 | Executor boundary | default disabled/unavailable、immutable lock/profile、network none、no host fallback、cleanup/uncertain launch | API execution tests + `aearn/services/executor/tests/` |
| RT-11 | P0 | Worker import/composition | worker has only target task wrappers; no executor runtime client import; scheduler production scan remains global | `test_worker_import.py` |
| RT-12 | P0 | Provider usage/cache accounting | Responses/Chat usage 归一化；cached 不重复计数；repair attempt 分列；缺失 usage 不伪造；跨用户、冲突重放和 UPDATE/DELETE 被拒绝；receipt 不进入公开投影 | `test_tutor_provider_gateway.py`、`test_tutor_run_loop.py`、`test_tutor_run_repository.py`、`test_db_bootstrap.py` |
| RT-13 | P0 | Adaptive context budget | capability 显式冻结；完整 serializer + reserve 预估不越 hard limit；四档可裁剪；current input 不驱逐；`insufficient_context` 最多有界升级；cache 不放宽物理预算；policy/metadata 不进入公开 API/SSE | `test_tutor_context_budget.py`、`test_tutor_context_builder.py`、`test_tutor_provider_gateway.py`、`test_tutor_run_loop.py`、`test_tutor_input_merge.py`、`test_tutor_run_repository.py` |
| RT-14 | P0 | Long-context summary | stable timeline retirement、v2 strict JSON、semantic dedupe、leased transient evidence load、committed latest-summary retrieval、current/recent 优先级、stale/invalid fail-closed、append-only/scope FK；不删除 raw history，不受 inferred-memory opt-out 误伤 | `test_tutor_context_summary.py`、`test_tutor_context_loader.py`、`test_tutor_context_builder.py`、`test_tutor_memory_curator.py`、`test_tutor_memory_curation_outbox.py`、`test_tutor_memory_curation_scheduler.py`、`test_tutor_provider_gateway.py`、`test_db_bootstrap.py` |
| RT-15 | P0 | Context governance eval / observability | versioned v2 fixture、safe receipt、current/history/usage/budget/summary cross-contract cases、attempt-level usage、calibration grouping、real-provider smoke default skip；receipt 不含 raw prompt/history/provider body/reasoning/credential | `test_tutor_evals.py`、`test_tutor_context_eval_smoke.py`、`test_tutor_real_provider_smoke.py` 与 RT-12/13/14 owning tests |
| RT-19 | P0 | Codex Sidecar | exact Windows stdio/version/provider/Responses、isolated Home、readiness admission、typed tool repair、projection redaction、Runtime-filtered worker、steer/interrupt、same-Runtime Retry 与 rollback；真实 smoke 必须单独批准 | `test_codex_sidecar_spike.py`、`test_codex_runtime_*`、`test_codex_learning_plan_tools*`、`test_codex_plan_drafting_cutover.py`、[`codex-sidecar-integration-readiness.md`](./codex-sidecar-integration-readiness.md) |
| UX-01 | P1 | Frontend bootstrap | local identity → server cutover → `welcome/cutover/tutor`; stale `planId` cleared and no legacy request emitted | fixture web browser smoke |
| UX-02 | P1 | Responsive/error UX | narrow viewport no horizontal overflow; Composer/primary actions visible; stable public error/retry states | fixture web browser smoke |
| DOC-01 | P0 | Current documentation | README/source-of-truth docs name Tutor as active runtime; transition/archive docs are visibly historical; no current Graph/SDK claim | link audit + `rg` audit + doc review |
| RET-01 | P0 | Legacy retirement | no production/test Graph/router/tool/SDK caller or direct dependency pin remains; historical evidence is archived/labelled | scoped source/dependency audit + full build/test |

## 4. Required fixture flows

### FI-01：verified cutover 与 Tutor-only entry

1. Create one disposable local user with legacy rows or use an isolated fixture.
2. Read `/api/harness/cutover`; assert server summary only names safe categories.
3. Submit the exact confirmation. Assert receipt is `verified`, legacy scope is
   empty, required identity/preferences are preserved, and pre-cutover
   `tutor_*` rows would have blocked rather than been deleted.
4. Assert `/api/tutor/*` works only after the receipt; direct legacy endpoint
   remains `409 CUTOVER_REQUIRED` for the verified fixture.
5. Delete the disposable user/fixture afterward. Do not place fixture content in
   docs or logs.

### FI-02：interactive run、SSE 与 safe projection

1. Use a deterministic provider/dispatcher seam and a verified fixture user.
2. Create a Tutor conversation and one non-terminal foreground turn; submit ordinary follow-ups and assert they enter a maximum-10 FIFO Queue without superseding the active turn.
3. Verify edit/delete/reorder CAS, explicit Steer monotonic `input_revision`, Interrupt pause, ordinary Send without implicit resume, explicit resume/execute fresh claim, completed-only duplicate-safe drain, pending-request block and Retry lineage/effect dedupe.
4. Verify idempotent replay, run-local/conversation cursor, `input_accepted` before terminal frame, and read-only SSE replay.
5. Inject provider/config/policy failure and assert stable public code without provider body or internal trace.

### FI-03：verified-only proactive default path

1. Seed a terminal interactive run for a verified fixture user only.
2. Execute `scan_due_signals` and `drain_candidates` through the API-side test
   seam with fake provider/clock.
3. Assert source hash contains only durable run ID/outcome/timestamp facts;
   persisted exact selection is `tutor.learner-state@1.0.0` and only
   `tutor.activity.record` commits.
4. Assert activity/inbox rows exist, no learner-visible background chat exists,
   and no runner/subprocess/memory effect is requested.
5. Repeat for an unverified user. Assert `cutover_unverified`, no provider
   call and no proactive run.

### FI-04：provider usage/cache receipt

1. 使用 fixed Responses 与 Chat Completions envelope，不调用真实 provider。
2. 断言 `input_tokens=175420`、`cached_input_tokens=170368` 派生
   `uncached_input_tokens=5052`，reported total 与 calculated total 分列，cached 不再加回 input。
3. 让首次响应因 JSON/decision 校验失败并执行一次 repair；断言两个实际 attempt
   分别持久化，而 run-level `model_call_count` 仍只增加一次 decision boundary。
4. 断言 usage 缺失保存为 `NULL`/unavailable；transport 无 envelope 不产生 token；
   superseded run 只保留安全 receipt，不写 public message/title/capability/effect。
5. 使用真实 PostgreSQL 断言 exact replay 幂等、不同事实冲突、跨 user/conversation
   FK 拒绝、derived token CHECK 生效且 receipt UPDATE/DELETE 被 append-only trigger 拒绝。
6. 检查日志、trace、history、SSE 与 learner export 不含 prompt、provider body、
   reasoning 文本、URL/header 或 credential。

### FI-05：adaptive context budget

1. 使用 synthetic capability 分别构造 compact/normal/complex/extended 输入，断言相同输入与 policy 得到相同 mode、optional budget、selected/skipped/truncated metadata。
2. 用共享 serializer 重新序列化 planner 结果，断言 system、strict decision contract、current input、context、metadata、JSON envelope、protocol reserve 与 safety margin 的总估算等于 checkpoint 记录，且不超过 input hard limit。
3. 构造 tight budget，断言低优先级 activity/非必要 capability schema 先被跳过，authoritative current input 保留；构造 required serialized overflow，断言 provider call 为零并返回 `TUTOR_CONTEXT_REQUIRED_OVERFLOW`。
4. 让 decision gate 首次返回受控 `REBUILD_CONTEXT / insufficient_context`，断言最多升级一个 mode，并继续受 `max_iterations`、`max_model_calls` 与 frozen `max_expansions` 限制。
5. 使用 fixed provider usage receipt 比较 estimate/actual；`input_tokens` 已含 cached，校准不得将 `cached_input_tokens` 再加回，也不得在请求前假设 cache hit。
6. 使用真实 PostgreSQL 断言 capability/mode target/ratio/expansion/estimator version 在 `policy_json` round-trip，且改变 estimator version 会改变 `policy_fingerprint`；公开 history/SSE 不出现内部 token 明细。

### FI-06：长对话摘要检索与压缩

1. 在同一 conversation 写入超过 recent window 的 prior messages，再接受 fresh
   TurnRun current input；断言 current input 独立，recent suffix 按
   `(created_at,id)` 稳定排序，retirement set 是未覆盖的连续前缀。
2. 用 high-water 与 terminal 触发同一 evidence；断言只产生一个
   `context_summary` outbox/job，trace/outbox/proposal/receipt 不含 raw marker。
3. 在合法 lease 下让 primary Curator 返回 strict `tutor_context_summary_v2`；断言
   proposal、structured summary、coverage 和 committed receipt 原子 round-trip，下一
   TurnRun 只加载一份最新 valid summary。
4. 构造“旧摘要认为未完成、current input 声明已完成”的冲突；断言 provider initial
   与 repair policy 都遵守 `current > recent > summary > memory/activity`。
5. 破坏 source hash、跨 conversation covered message、schema/retention/stale 状态；
   断言 provider 不被调用或 loader 回退 recent-only，summary UPDATE 被 append-only
   trigger 拒绝，legacy v1 row 不冒充 v2。
6. 关闭 inferred memory，保留正常 curation scheduler/用户 background gate；断言
   context summary 仍可生成，provider hard limit、adaptive budget、finite TurnRun 与
   PostgreSQL persistence contract 不变。

### FI-07：Tutor context governance eval 与 calibration

1. 加载 `tutor_context_governance_v2.json`，使用固定 capability、budget policy、
   clock/latency 数值、deterministic estimator 和 fake provider；旧
   `tutor_harness_foundation_v1.json` 必须继续兼容。
2. 断言 current input pinned 且只出现一次、equal timestamp history 按
   `(created_at,message_id)` 排序、optional context 先驱逐、required input
   无法表示时 provider call 为零。
3. 断言 cached 是 actual input 子集、uncached 正确派生、repair 两次 attempt
   分列而 decision count 仍为一、reported/calculated total 不互相覆盖。
4. 断言 compact 与有界 expansion mode、physical hard limit、summary retirement
   coverage、correction override、stale summary exclusion 和 deterministic replay。
5. Eval receipt 只输出数字、布尔、枚举、版本和不透明 source ID；calibration
   按 provider/protocol/capability/mode/estimator/config 分组，样本不足时不输出
   P50/P95，也不自动修改生产配置。
6. `TUTOR_REAL_PROVIDER_SMOKE` 默认未设置；普通 CI 必须 skip。只有单独批准且
   provider 配置完整时，才运行固定五轮 smoke，并明确它只是 real behavior sample，
   不是 fake contract 或 release approval。

### FI-08：Desktop normal/narrow path

1. Bootstrap Desktop with a disposable verified user and deliberately stale
   `planId`.
2. Assert network begins with profile/cutover, no dashboard/resume/legacy route
   request occurs, and bootstrap persistence has `planId=null`.
3. At normal and narrow viewport, assert Tutor Composer and primary action are
   reachable and document width does not overflow.
4. Do not submit a live provider request or enable executor merely to make this
   smoke look more realistic.

## 5. Final command matrix

Run in this order after all code/docs edits. Do **not** run bootstrap-heavy
pytest commands in parallel.

```powershell
# Context governance focused gate; real-provider case is collected as skip by default.
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_evals.py tests/test_tutor_context_eval_smoke.py tests/test_tutor_real_provider_smoke.py tests/test_tutor_context_builder.py tests/test_tutor_context_budget.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_tutor_context_loader.py tests/test_tutor_context_summary.py tests/test_tutor_run_repository.py tests/test_db_bootstrap.py -q

# API suite: serial execution only.
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api lock --check

# Standalone executor contract checks. Docker conformance remains opt-in and
# fails closed when reviewed immutable locks are absent.
uv --directory .\aearn\services\executor run python -m pytest

# Local managed process status. Frontend validation is performed in the web browser.
pnpm --dir .\aearn dev:status

# Trellis/doc hygiene.
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-tutor-context-budget-evals-observability
git diff --check
```


Optional real-provider behavior sample; do not run without separate approval:

```powershell
$env:TUTOR_REAL_PROVIDER_SMOKE = "1"
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_real_provider_smoke.py -q -m real_provider
```

The command must never be part of the default matrix and must not print provider
request/response bodies, prompt/history, reasoning, credentials, paths, or commands.

The API full suite itself includes the final fake-provider proactive smoke.
When it fails, run the affected test module serially for diagnosis, repair the
owning boundary, then rerun the full matrix; do not edit ledger wording to
mask it.

## 6. Legacy retirement / documentation audit

The expected active source audit after retirement is empty for production and
current tests:

```powershell
rg -n --glob '*.py' 'app\.agents\.graphs|from langgraph|langgraph-checkpoint|graph_event_stream|from agents|import agents|LANGGRAPH_ENABLED' aearn\services\api\app aearn\services\api\tests
rg -n 'LANGGRAPH_ENABLED|langchain|langgraph|openai-agents' aearn\services\api\pyproject.toml aearn\services\api\uv.lock
```

Historical documents under `docs/archive/2026-07-29/` and the transition record
may intentionally mention those terms; every such file must have a visible
historical label. The docs index and all current source-of-truth files must not
route a reader to the historical runtime as active.

## 7. Release evidence and non-claims

The final ledger records for every gate: command/procedure, working revision,
fixture posture, result, warnings, residual risk, and follow-up owner. It must
state explicitly that:

- deterministic/fake-provider checks do not prove real model quality, latency,
  quota or teaching usefulness;
- container contract checks do not prove a production image fleet when no
  reviewed image locks are present;
- post-cutover code rollback never restores intentionally deleted legacy data;
- a passing Trellis manifest/documentation audit is not a deployment or release
  approval.

Only after the entire matrix, retirement audit, fixture smoke, source-of-truth
review and intentional human release decision can a separate release process
be considered. This child must otherwise remain `in_progress`.

## 2026-08-10：Learning Home / plan builder 验收增量

| ID | 优先级 | 区域 | 验收 | 证据 |
|---|---|---|---|---|
| RT-16 | P0 | Planning persistence | session create/resume/cancel、append-only draft、source run replay、stale confirm、原子 track 创建、跨用户 404 | `test_learning_plan_sessions.py`、`test_learning_plan_draft_capability.py`、LearningTrack/DB tests |
| RT-17 | P0 | Plan capability | exact Skill、active plan scope only、compact payload 仍受 12×360 限制、registry source、safe receipt、其他 scope default-deny | capability/catalog/policy/run-loop focused regression |
| UX-02 | P1 | Learning Home / Planner | 三/二/一列、添加卡末尾并直接进入 planner、无语言选择器；首页与 planner 无左侧栏，planner 无 hero/外层对话卡片；未激活状态只有中央 Composer，首条消息/run 后才出现 GPT 式消息流与底部 Composer；进入 planner 即出现右缘按钮与四角圆角浮动窗口，`current_draft` 为空时只有 emoji 且 Composer 聚焦前后外壳视觉稳定，草案到达后同一窗口原位展示路线；窗口可收起/重开、与视口右缘保留明显留白且不挤压对话列；恢复/确认与 downstream 真实未就绪 | local web browser smoke |

## 2026-08-11：LessonDocument 验收矩阵

| ID | 优先级 | 区域 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-18 | P0 | Lesson contract | 十类注册 block、canonical hash、未知字段/HTML/script/hidden-answer 拒绝、事实 citation coverage、personalized 保留标准 coverage/Gate | `test_lesson_document_contracts.py`、`test_lesson_document_quality.py` |
| RT-19 | P0 | Lesson persistence | shared standard、track-scoped personalized、source snapshot reindex 后可读、assignment start/freeze/proposal/migration、append-only schema | `test_lesson_document_repository.py`、bootstrap/LearningTrack/cutover regression |
| RT-20 | P0 | Lesson authoring/API | durable lease、primary-only strict port、safe attempts、no evidence/provider/invalid/quality/stale fail closed、verified/cross-user/locked/version/idempotency | `test_lesson_document_authoring.py`、`test_lesson_documents.py` |
| UX-03 | P1 | Lesson reader | Home continue -> Lesson；missing/preparing/ready；十类 block；inline citation/source panel；start freeze；proposal/migrate；Gate 由 typed seam 接入服务端 authority；1440/900/390 无溢出/overlay/console error | local web browser smoke at `http://127.0.0.1:1420` |

真实 provider smoke 默认不执行；fake author contract、PostgreSQL durable evidence、网页端 fixture 与 release approval 必须分别标记。前端默认不运行 Desktop build/typecheck。

## 2026-08-11：练习 Gate 与模块诊断验收矩阵

| ID | 优先级 | 区域 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-21 | P0 | Exercise/Gate contract | 四类 curated fixture、public/private quality boundary、`gate_kind`/`requirement_kind` 分离、canonical hash、static 不声明执行、observational evidence 不降级 | `test_exercise_gate_contracts.py`、`test_exercise_gate_quality.py` |
| RT-22 | P0 | PostgreSQL authority | 12 张 Practice 表、bootstrap twice、scope/one-of/immutability、Attempt idempotency、required submit 原子 Gate/mastery/progress/unlock、run 不推进、export/reset/cutover redaction | `test_exercise_gate_repository.py`、`test_db_bootstrap.py`、LearningTrack/Lesson/cutover regressions |
| RT-23 | P0 | Existing execution queue | Gate Attempt 复用 existing intent/job、无假 Tutor conversation/message/effect、old Tutor claim/lease/launch token 回归、executor trusted input exact private scope | `test_exercise_gate_repository.py`、Tutor execution regression、`test_exercise_trusted_input.py`、executor suite |
| RT-24 | P0 | Gate/API privacy | verified-only、locked/cross-scope 404、version/idempotency conflict、pending same-Attempt poll、stable 422/503、public projection 不含 submission/rubric/reference/container/path | `test_exercise_gates.py`、protected-marker audit |
| RT-25 | P0 | Module diagnostic | 只允许模块边界、direct API bypass 被拒绝、fail/partial 不创建 revision/不跳过/不降 mastery、pass 必须 confirm 后才激活 `diagnostic_skipped` | `test_module_diagnostics.py` |
| UX-04 | P1 | Gate/diagnostic web | prepare/hint/run/submit/poll/stale；四 tier 诚实 UI；失败诊断“未跳过任何知识点”；pass impact + explicit confirm；1440/900/390 无溢出、focus 可见、console/overlay clean | real browser at `http://127.0.0.1:1420` with disposable stateful fake API |

默认质量门为 API/executor lock、Ruff、Mypy、完整串行 pytest、前端 `tsc --noEmit`、真实网页端 smoke、Trellis validate 与 `git diff --check`。本任务不运行 Desktop/Tauri build。真实 provider、reviewed image fleet、Docker conformance 和生产 executor smoke 未获批准，不能从 fake/curated 证据推断 release readiness。


## 2026-08-12：模型代码审核验收矩阵

| ID | Priority | Surface | Required proof |
| --- | --- | --- | --- |
| RT-25 | P0 | Contract/scorer | 六种场景、四种语言、verdict/finding shape、duplicate/omission/severity/false-positive 确定性 |
| RT-26 | P0 | Authoring/Action/executor | exact descriptor、internal proactive run、existing queue、九项 validation check、stale/failed fail-closed |
| RT-27 | P0 | PostgreSQL lifecycle | bootstrap twice、scope/one-of/append-only、`NO ACTION DEFERRABLE` 环形 FK、publication replay、export/reset/cutover |
| RT-28 | P0 | Gate/API privacy | preparing/ready/failed、structured submit/evidence、exactly-once result/mastery/unlock、protected marker 不外泄 |
| RT-29 | P1 | Desktop | finding 增删/校验/result mapping、assisted badge、390/900/1440、键盘/focus、console clean |

默认 suite 使用 deterministic fixture/fake executor，不访问真实 provider，不启动生产容器 fleet。
完整发布验证仍需单独批准的 reviewed executor image 与真实 provider smoke；它们不由本矩阵自动
宣称通过。

## 2026-08-12：间隔复习与 ReviewSession 验收矩阵

| ID | 优先级 | 区域 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-30 | P0 | 调度纯函数 | Again/Hard/Good/Easy 单调、independent 优于 hinted、critical failure、overdue escalation、3650 天上界、diagnostic skip 低频 seed | `test_review_scheduler.py` |
| RT-31 | P0 | Queue/Gate | user/track scoped actionable count；普通 due 不阻断；未来 due 的 critical prerequisite 立即进入 queue/Gate；track card count 一致 | `test_review_sessions.py`、`test_reviews.py`、LearningTrack regression |
| RT-32 | P0 | ReviewSession lifecycle | create/retry/resume、冻结 context/item、warmup 无长期写、hint independence、batch 未完成禁止 finalize、全部 terminal 后 exactly-once | `test_review_sessions.py`、`test_reviews.py` |
| RT-33 | P0 | Evidence/migration | finalization 原子写 Attempt aggregate/mastery/schedule event/state；stable key retained、removed suspended；confirmed diagnostic skip seed | review repository、module diagnostic、LearningTrack tests |
| RT-34 | P0 | Scope/privacy/local data | cross-user 404、version/idempotency、候选不足无 fallback、public/export 不含 submission/private rubric/context hash、reset/cutover child-to-root | `test_review_sessions.py`、`test_reviews.py`、`test_db_bootstrap.py` |
| RT-35 | P0 | Regression gate | API lock、Ruff、Mypy、完整串行 pytest、executor regression、Desktop typed build、Trellis validate、`git diff --check` | release-readiness ledger |

默认 suite 使用 PostgreSQL、curated immutable exercises、deterministic scorer 和 fake/local execution
contract，不访问真实 provider、不启动或批准生产 container fleet。ReviewSession 后端/API 通过不等于
三栏工作区 UI、真实模型题目质量、生产 executor 安全或 release approval。

## 2026-08-12：最终学习 Agent 集成验收矩阵

| ID | 优先级 | 区域 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-36 | P0 | 核心语言闭环 | Python、JavaScript、TypeScript、SQL 各完成 plan -> source-backed Lesson -> start -> Gate -> terminal safe feedback -> private persistence -> mastery/progress -> due ReviewSession -> review evidence/schedule event | `test_learning_agent_integration_matrix.py` |
| RT-37 | P0 | 扩展与降级真实性 | Java、HTML/CSS 只记录扩展 runner/contract；Go/C# 保持 partial；Rust public unavailable；C++ public static-only；无 `container_verified` 夸大 | integration matrix + language/runner tests |
| RT-38 | P0 | Container fail-closed | `image-locks.json` 为空时，即使 catalog 与 executor health 可见，public execution-required Gate 仍 unavailable；local fixture 只为 `teaching_local` | integration matrix + execution-tier/executor tests |
| RT-39 | P0 | Cutover/schema inventory | 所有 `tutor_*` 表必须在 user-owned target inventory 或 shared allowlist 中；任一 target state 阻断 cutover；旧数据不静默转换 | `test_harness_cutover.py::test_cutover_inventory_explicitly_classifies_every_tutor_table` + cutover suite |
| RT-40 | P0 | Authority/privacy | confirmed facts、AuthoritativeContextSnapshot、Action receipt/verification、stale/superseded fencing、safe projection/export redaction 无回归 | context eval/action runtime/context reference/public API suites |
| RT-41 | P0 | 最终质量门 | API/executor lock、Ruff、Mypy、完整 pytest、Desktop build、DB smoke、Trellis validate、diff hygiene 全部通过 | release-readiness ledger |

真实 provider 与 Docker/container smoke 仍为可选、独立、需批准证据；它们不能替代上述确定性 contract 测试，也不能由上述测试自动推断为发布批准。

## 2026-08-13：Prompt 合同与受控 Model Review authoring 增量

| ID | 优先级 | 区域 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-42 | P0 | Tutor continuation | 五类 exact enum、`planning_input/question_key` pairing、未知值/错配拒绝、DB/API/Desktop 同步 | `test_tutor_provider_gateway.py`、`test_db_bootstrap.py`、Desktop `tsc --noEmit` |
| RT-43 | P0 | Model Review author boundary | model schema 仅含教学场景与 candidate code；template identity/tests/rubric/proof/score server-owned；六场景 registry 全覆盖 | `test_model_review_authoring_contract.py` |
| RT-44 | P0 | Controlled validation DSL | visible/hidden、连续 order、proof coverage、exact runtime/count/outcome；sandbox wire 剥离 expected/proof/id metadata | Model Review repository tests、executor `test_exercise_trusted_input.py` |
| RT-45 | P0 | 全量 prompt audit | Tutor/Lesson/Adaptive/Curator/Error Explanation 均有严格 schema、稳定 schema name 与合法示例；union/block 示例足够覆盖分支 | `test_prompt_contracts.py`、curation/adaptive/provider focused tests |

本增量不调用真实 provider，也不批准生产 executor image。受控 template 和 fake result 只证明合同、
隔离和 fail-closed 行为；真实生成质量与 runtime/container conformance 仍需独立批准。


## 2026-08-14：类型化 request / fresh authority turn 验收

| ID | 优先级 | 区域 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-46 | P0 | Request authority | 五种 kind/actor/schema 在 DB、Python、API、snapshot/events、TypeScript 一致；同 conversation 最多一个 pending；跨 user/conversation 与 provider-authored schema fail closed | `test_db_bootstrap.py`、`test_tutor_interaction_requests.py` |
| RT-47 | P0 | Fresh response turn | clarification/planning/approval 终结来源 turn，response CAS 创建不同 fresh run/job，deadline/counters/lease 不继承；同 body 重放、不同 body/stale version 冲突 | `test_tutor_sse.py`、`test_tutor_interaction_requests.py` |
| RT-48 | P0 | Planning catalog | 七字段 immutable catalog、published language options、整数/文本/单选/多选边界与 confirmed reask gate；typed answer 写 exact planning fact | `test_tutor_interaction_requests.py`、`test_learning_plan_sessions.py` |
| RT-49 | P0 | Approval/authority | approval 必须匹配 proposal identity；普通文本不可批准；learner 不可写 capability/external receipt；issuer/scope/hash/identity 幂等与 ambiguous pending | `test_tutor_interaction_requests.py`、`test_tutor_action_runtime.py` |
| RT-50 | P0 | Public safety | request/item/event 只含 bounded prompt/presentation/IDs/enums；raw learner input 不进入 SSE event，authority raw result/args/secret 不进入 snapshot/history | `test_tutor_sse.py`、public allowlist tests |

上述验证默认使用 fake provider 和本地 PostgreSQL；不调用真实 provider、不执行生产 cutover、不部署。


## 2026-08-14：Tutor Queue 与显式控制验收增量

| ID | 优先级 | 区域 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-43 | P0 | Queue/control state | active Send 只排队；10 项上限；edit/delete/reorder 全量 CAS；Steer 同 run 新 revision；Interrupt public interrupted + pause；普通 Send 不 resume；resume/execute fresh claim | `test_tutor_queue_control.py`、`test_tutor_input_merge.py`、route/snapshot/SSE regression |
| RT-44 | P0 | Drain/Retry/effect lineage | 只有 completed 自动 FIFO drain；failed/interrupted/pending request pause；duplicate worker 不重复 claim；Retry fresh predecessor/root；committed logical effect receipt 复用，ambiguous fail closed | `test_tutor_queue_control.py`、`test_tutor_effect_commit.py`、`test_tutor_execution_effect.py`、worker/repository regression |
| FE-08 | P1 | Typed API seam | snapshot/Queue exact DTO、queued input union、control mutation parser 拒绝 extra/unknown state；现有 UI 对 queued response 不崩溃，最终 Queue UI 由 Desktop migration child 完成 | Desktop `tsc && vite build`、Vitest |

默认验证使用 fake/disabled provider 与本地 PostgreSQL，不调用真实 provider、不执行生产 cutover、
不部署，也不据此宣称真实模型质量或 release approval。


## 2026-08-14：thread/turn v2 全局 cutover 验收增量

| ID | 优先级 | 范围 | 证据 |
| --- | --- | --- | --- |
| RT-45 | P0 | singleton/advisory/generation | 并发 prepare 单 winner、同 key replay、不同 generation conflict | `test_tutor_thread_turn_cutover.py` |
| RT-46 | P0 | legacy convergence/effect block | waiting fresh-turn error、active interrupted/lease clear、ambiguous effect blocked、late write fenced | cutover + run-loop/effect tests |
| RT-47 | P0 | effective gate/rollback/410 | env+DB matrix、worker/reconciler block、legacy POST no-side-effect 410、rollback no reopen | route/worker/cutover tests |
| FE-09 | P1 | capability exact DTO | Desktop parser/build 拒绝 unknown state/field，客户端不猜测 enable | Desktop Vitest + `desktop:check` |

默认验证不调用真实 provider、不执行生产 cutover、不部署。


## 2026-08-14：Codex-like Tutor Desktop migration 验收增量

| ID | 优先级 | 范围 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| FE-10 | P0 | Snapshot / SSE authority | Desktop 首屏只用 conversation snapshot；opaque cursor、重复 sequence、gap/cursor invalid/reconnect 均 fail closed 并重新 snapshot；主 UI 无 run-local SSE | `useTutorConversationStream.test.ts`、Desktop Vitest、browser reconnect smoke |
| FE-11 | P0 | Composer / typed request | running Send 默认 Queue；pending request 完全占 composer；clarification/planning/approval 使用 exact request version；authority 只读等待；无 `/runs/{id}/inputs` caller | source guard test、typed fixture browser flow、API request tests |
| FE-12 | P0 | Queue / controls | Queue n/10、edit/up/down/delete/Steer/execute/resume、Stop 与 Retry 使用 snapshot expected versions；409 后刷新 snapshot 并保留本地 draft | Queue API tests、Desktop build、browser keyboard/responsive smoke |
| FE-13 | P1 | Timeline / migration / accessibility | process 不渲染；Tutor message 仅以 `public_thinking_steps[]` 显示 DSH-derived Think；legacy waiting 显示 fresh-turn card；interrupted 为中性终态；390/900/1440、focus、reduced motion、console clean | Desktop Vitest、Browser/Tauri smoke |

上述 Desktop 验收使用 fake/disabled provider 与本地 fixture；不调用真实 provider、不执行生产 cutover、不部署。


### 本地集成证据（2026-08-14）

- Desktop：Vitest `21 passed`；`pnpm --dir .\aearn desktop:check` 通过；Tauri dev 完成编译并启动。
- API：本 child focused suite `18 passed`；完整 API pytest `569 passed, 1 skipped`；Ruff、Mypy、`uv lock --check`、`compileall` 通过。
- Browser/Tauri：验证 snapshot-first timeline、DSH-derived Think、`process` 不渲染、running Send 入 Queue、Queue edit/reorder/delete/Steer/execute、Stop/Retry 状态、390×844、900×900 与 1440×900 无横向溢出、键盘发送、reduced-motion、SSE 断线可见错误与恢复后重连；console error 为 0。
- pending request 的 composer-seat 替换与 exact request version 由 Desktop component test 和 API request suite 覆盖；本地 fake dispatcher fixture 未作为真实 provider 或发布就绪证据。
- 未调用真实 provider，未执行生产 cutover、部署或生产数据修改。

## 2026-08-15：Tutor 公开思考文本流验收增量

| ID | 优先级 | 范围 | 验收 | 证据 |
| --- | --- | --- | --- | --- |
| RT-51 | P0 | Provider/projector | v4 exact field；任意 JSON 分片、escape、Unicode/surrogate；只观察 `output_text.delta`；reasoning 忽略；累计安全、160 字分片与最终文本一致 | `test_tutor_public_thinking_stream.py`、`test_tutor_provider_gateway.py`、LLM adapter regression |
| RT-52 | P0 | Durable lifecycle | begin/append/reset/complete/discard/accept 的 run/revision/generation/lease fence；repair、Interrupt、supersede、stale callback 不混流；message/request 原子接受 | `test_tutor_conversation_runtime.py`、`test_tutor_run_loop.py`、`test_db_bootstrap.py` |
| RT-53 | P0 | Snapshot/SSE/privacy | snapshot/event/cursor v2；`active_thinking` exact；`turn_output` closed payload；duplicate/gap/reconnect fresh snapshot；legacy steps/text兼容；无 reasoning/prompt/body/diagnostic | conversation history/SSE/routes/public API suites、Desktop parser tests |
| FE-14 | P0 | Think 状态机 | accepted 后静态 `● Think` 无 button；首文本默认展开；每 tick 一个 grapheme；换行保留；final answer 后一次折叠；重开/refresh 不抢状态；历史不重放 | `TutorConversationSurface.test.tsx`、`useGraphemeTypewriter.test.tsx`、stream hook tests |
| FE-15 | P1 | Browser/a11y | 1440×900、900×900、390×844；普通/慢/burst/reset/reconnect/success；无溢出/overlay/console warning；focus 与 reduced motion 正确；DOM/network 无 protected marker | disposable fake API/provider 浏览器证据 |

默认验证使用 fake/local provider transport 与本地 PostgreSQL；不调用真实 provider、不执行生产 cutover、
不部署，也不把确定性 contract 测试解释为真实模型质量或发布批准。数据库相关 pytest 必须串行运行，
避免并发 schema bootstrap 造成测试环境死锁。
