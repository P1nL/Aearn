# Aearn Tutor Harness 验收计划

**状态：** 当前 integration/QA 契约，2026-08-08。
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
4. **静态搜索不是唯一证据。** legacy source/dependency/doc audit、测试、Desktop
   build 和 fixture smoke 要同时通过，才可称实现退休完成。
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
| RT-04 | P0 | Durable input/effect/replay | input revision merge、idempotency、ordered events、stale effect rejection、trace redaction 和 current lease CAS | `test_tutor_run_repository.py`、`test_tutor_input_merge.py`、`test_tutor_trace_redaction.py` |
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
| UX-01 | P1 | Desktop bootstrap | local identity → server cutover → `welcome/cutover/tutor`; stale `planId` cleared and no legacy request emitted | `pnpm --dir .\aearn desktop:check` + fixture browser/Desktop smoke |
| UX-02 | P1 | Responsive/error UX | narrow viewport no horizontal overflow; Composer/primary actions visible; stable public error/retry states | fixture browser/Desktop smoke |
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
2. Create a Tutor conversation, submit input, then submit a follow-up while the
   first interactive run is non-terminal.
3. Verify monotonic `input_revision`, idempotent replay, run-local cursor,
   `input_accepted` before terminal frame, and a read-only SSE replay.
4. Inject provider/config/policy failure and assert stable public code without
   provider body or internal trace.

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

### FI-07：Desktop normal/narrow path

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
# API suite: serial execution only.
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api lock --check

# Standalone executor contract checks. Docker conformance remains opt-in and
# fails closed when reviewed immutable locks are absent.
uv --directory .\aearn\services\executor run python -m pytest

# Desktop and local managed process status.
pnpm --dir .\aearn desktop:check
pnpm --dir .\aearn dev:status

# Trellis/doc hygiene.
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-integration-qa-and-docs
git diff --check
```

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
