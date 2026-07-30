# Skill-Native Tutor Harness Implementation Plan

## Status and Preconditions

This is a parent-task coordination plan. The user approved `prd.md`,
`design.md`, and this document on 2026-07-26, but the parent remains
planning-only and must not run `task.py start`. Product implementation begins
only after the selected child completes its own current planning review and
receives child-level approval. Do not delete learner data, deploy, or alter
production behavior before the applicable child approval.

The worktree already has unrelated changes. Every child limits edits, tests,
staging, and reviews to its declared paths. No child may revert, stage, or
rewrite unrelated Trellis, docs, or local configuration changes.

### Trellis 0.6.8 Child-Readiness Migration

The `07-22-*` tree keeps its existing identifiers, hierarchy, and `planning`
state after the Trellis upgrade. Do not bulk-author design, implementation,
or context manifests for every child before its dependency slot is active.
Immediately before a selected child can run `task.py start`, perform this
readiness migration in its own planning turn:

1. Re-read its PRD against current code, its explicit upstream dependency
   contracts, and the Phase 0 transition-delta matrix.
2. Add its child-scoped `design.md` and `implement.md` with observable
   acceptance, validation, rollback, and documentation-delta obligations.
3. Curate at least one real spec or research entry in each of
   `implement.jsonl` and `check.jsonl`, then run `task.py validate`.
4. Treat a format-valid seed-only manifest as not ready; do not run
   `task.py start` until the first three checks are complete and the user has
   approved the latest child planning summary.

## Delivery Shape

The parent owns requirements, cross-child contracts, integration acceptance,
and final documentation alignment. A child owns independently testable work.
The listed order is dependency order, not just tree order.

| Order | Planned child task | Depends on | Primary outcome |
| --- | --- | --- | --- |
| 00 | `tutor-harness-contracts-and-run-loop` | none | Durable finite run runtime, bounded Context Builder, input revision, provider/compaction-request contract. |
| 01 | `tutor-skill-catalog-and-capability-gateway` | 00 | Versioned Skills, policy-filtered capabilities, effect contracts. |
| 02 | `tutor-state-traces-and-evals` | 00, 01 | Schema/repositories, trace/event persistence, redaction, curation outbox/proposals, core evals. |
| 03 | `container-sandbox-executor` | 01, 02 | Separate container-grade code executor and audited execution capability. |
| 04 | `tutor-proactive-scheduler` | 00, 01, 02 | Candidate signals plus generic low-priority curation queue, budgets, circuit breakers, and worker recovery. |
| 05 | `tutor-plans-memory-and-activity` | 01, 02, 04 | Plan revisions, inspectable memory, guarded Memory Curator, timeline/inbox, user controls. |
| 06 | `tutor-api-sse-and-desktop` | 00-05 | Durable Tutor API, SSE reconnect/merge UX, guided entry, and transparent memory provenance controls. |
| 07 | `harness-cutover-and-legacy-retirement` | 02, 05, 06 | Verified reset gate, legacy adapter transition and retirement. |
| 08 | `tutor-integration-qa-and-docs` | 00-07 | End-to-end proof, source-of-truth docs, cleanup/runbook. |

Implementation may overlap only after an earlier child freezes its consumed
contract. Schema/API contract changes are never silently made in parallel.

## Phase 0: Documentation Authority, Contract Freeze, and Baseline

Phase 0 runs only after the user approves the latest parent planning review. It
is non-destructive and precedes every child implementation.

1. Create `docs/architecture/tutor-harness-transition.md` and link it narrowly
   from `docs/README.md`. Label current docs as legacy/current baseline and the
   transition document as the approved target; do not archive or broadly rewrite
   old documents yet.
2. Record the authority order: repository evidence for factual behavior, legacy
   docs for migration obligations, and the approved target contract for new
   behavior. Resolve every discrepancy in the delta matrix, never implicitly.
3. Record exact Graph callers, SSE consumers, checkpoints, reset/delete scope,
   worker tasks, runner paths, composer behavior, dependencies, schema version,
   active focused tests, Compose config, and desktop build baseline.
4. Write API/SSE compatibility rows as `legacy`, `adapter`, `new`, or `removed`,
   with consumer coverage and removal gate. Do the same for schema, reset, and
   desktop interaction deltas before code relies on them.
5. Preserve the clean-slate boundary: no learner history is copied as migration;
   destructive cutover remains feature-gated and requires later confirmation.
6. Require every child PRD to name upstream dependencies, authority inputs,
   document delta, verification evidence, and rollback boundary. Before a child
   starts, add its complex-task artifacts and real `implement.jsonl` /
   `check.jsonl` entries.
7. Keep all work isolated from unrelated Trellis/skill/template changes in the
   current worktree.

| Child | Documentation contract required before code dependency |
| --- | --- |
| 00 | Run, input, provider, bounded-context, compaction-request, checkpoint, terminal-outcome contract. |
| 01 | Skill manifest, capability/effect policy, registry-grounding contract. |
| 02 | Additive schema, durable event/replay, curation outbox/proposal, redaction, and evaluation contract. |
| 03 | Executor isolation, allowlist, result-redaction, and operations contract. |
| 04 | Signal, consent/default, budget, pause, proactive delivery, and generic curation queue/retry policy. |
| 05 | Plan revision, learner memory, Curator proposal/commit semantics, activity, and user-control semantics. |
| 06 | Endpoint/event compatibility matrix, memory provenance/control, and target desktop interaction contract. |
| 07 | Deletion/preservation summary, verification outcome, and retirement gates. |
| 08 | Final source-of-truth reconciliation, historical archival, and release proof. |

Rollback point: no runtime behavior or learner data changes; the approved plan
can still be rejected before any child begins implementation.

## Child 00: Tutor Harness Contracts and Run Loop

### Scope

- Add `app/agents/harness/` lifecycle runtime and `app/services/tutor/`
  service-owned orchestration.
- Define types for run, input event, checkpoint, provider decision, Skill ref,
  capability request, effect proposal, terminal outcome, and policy snapshot.
- Define `TutorContextBuilder` selection/budget contracts and an injectable
  typed compaction-request publisher. Child 00 only emits the contract at safe
  points; Child 02 later supplies its durable transactional outbox.
- Build provider-neutral adapter around current DeepSeek and OpenAI-compatible
  clients. Preserve primary-only retry and map final failure to
  `MODEL_UNAVAILABLE`.
- Implement worker lease, bounded loop, safe checkpoints, and input revision
  reload. Do not expose arbitrary capability/UI entry points yet.
- Reuse sound redaction/context primitives; do not copy Graph stages/routing.

### Acceptance

- Fake provider drives zero, one, and multiple safe iterations without a
  learning-stage transition model.
- Second persisted input increments revision and a next decision sees it.
  Effect proposal made at older revision is rejected.
- Context construction is bounded, deterministic from allowed scoped inputs,
  and emits a compaction request only at a terminal/safe checkpoint or context
  high-water mark--never once per streamed token.
- No cross-provider request occurs after primary failure.
- Lease/retry/budget terminal outcomes are stable and redacted.

### Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_loop.py tests/test_tutor_provider_gateway.py tests/test_tutor_context_builder.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

Rollback point: Harness remains feature-disabled; remove only new runtime
registrations. Existing Graph endpoints stay untouched.

## Child 01: Skill Catalog and Capability Gateway

### Scope

- Add developer-owned versioned Skill source, manifest schema/compiler,
  catalog snapshot, and validation tests.
- Replace model-facing stage write tools with capability descriptors and typed
  effect requests while preserving service/repository authority.
- Add capability policy for origin, user scope, active run/input revision,
  consent, budget, source registry, runtime availability, and version.
- Replace open `web_search`/arbitrary `fetch_doc_toc` with registry-bound
  grounding capability contracts.
- Generate MCP-compatible schemas without forcing in-process calls over MCP.

### Acceptance

- Catalog rejects undeclared/invalid capabilities, unversioned Skills, missing
  eval suites, untrusted resources, and model-provided paths.
- Tutor receives only policy-eligible Skills/capabilities; it cannot name an
  arbitrary function, URL, image, SQL, or user id.
- Effects are bounded, typed, redacted, and carry expected input revision.
- Grounding returns only `grounding_sources.py`-governed indexed sources.

### Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_skill_catalog.py tests/test_tutor_capability_gateway.py tests/test_tutor_grounding_policy.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

Rollback point: legacy tools stay available only for legacy adapters while
needed; they are never exposed alongside new Tutor capabilities.

## Child 02: State, Trace, and Evaluation Foundation

### Scope

- Add migrations/repositories for run/input/checkpoint/event, capability
  invocation/effect, catalog snapshot, redacted trace, and eval fixtures.
- Add a transactional redacted curation outbox and typed context-summary/
  memory-entry proposal persistence with closed source ranges, policy/memory-
  setting versions, ordering, idempotency, retry/no-action status, and export
  redaction. Do not implement Curator model behavior in this child.
- Add transactional input acceptance and effect compare-and-set on expected
  input revision.
- Add durable ordered events, replay cursors, user idempotency, retention, and
  export redaction.
- Add initial Harness evaluation runner using fake providers/capabilities.

### Acceptance

- Two workers cannot commit same effect or emit conflicting event sequence.
- Dropped SSE consumer reconnects from cursor and receives remaining terminal
  sequence exactly once.
- Trace/export omit raw prompts, provider payloads, hidden tests, solution
  references, secrets, executor paths, and stack traces.
- Evals cover policy denial, schema rejection, bounded loop, revision conflict,
  and model failure.
- Duplicate outbox delivery cannot create a second summary/memory proposal, and
  retained request/proposal/export fields omit raw prompt/provider/trace bodies.

### Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_repository.py tests/test_tutor_event_replay.py tests/test_tutor_effect_commit.py tests/test_tutor_memory_curation_outbox.py tests/test_tutor_evals.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

Bootstrap-heavy database batches run sequentially; do not parallelize them with
current learning/review/database suites. Rollback is additive migrations behind
feature flag; legacy data remains untouched until cutover.

## Child 03: Container Sandbox Executor

### Scope

- Build separate executor queue/service; API process receives no Docker daemon
  privilege.
- Add image allowlist by digest, typed job contract, no-network launch,
  resource limits, cancellation, output limits, cleanup, and execution audit.
- Integrate `runner.execute` only for current interactive explicit
  run/test/debug/explain intent. Keep runner/evaluation response authority in
  services.
- Remove old subprocess fallback before enabling Harness execution for a
  learner. It can exist only as disabled legacy-adapter fallback during
  migration.

### Acceptance

- Executor rejects proactive runs, unknown images, missing explicit intent,
  non-current user/session scope, and policy/budget violations.
- Tests prove no default network, no host bind mount, read-only root, bounded
  temp storage/resources/output, timeout, and cleanup.
- API receives only bounded execution facts, never Docker errors/paths/raw
  process diagnostics.

### Verification

```powershell
docker compose -f .\aearn\infra\docker-compose.yml config --quiet
uv --directory .\aearn\services\api run python -m pytest tests/test_container_executor.py tests/test_tutor_execution_capability.py tests/test_runner_contracts.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

Rollback point: `runner.execute` remains capability-disabled until executor
health/isolation tests pass. Never silently fall back to host subprocess.

## Child 04: Proactive Scheduler

### Scope

- Add durable user-event/time-signal ingestion, candidate deduplication,
  cooldown, user concurrency, budget, circuit breaker, and audit records.
- Add worker tasks that lease candidate runs through the same Tutor runtime.
- Supply a separate low-priority `curation` queue/lease class for Child 05. It
  consumes Child 02 outbox rows with independent curation budget, cooldown,
  concurrency, retry, and circuit-breaker controls; it is not a proactive Tutor
  candidate and cannot create a teaching result by itself.
- Add global proactive enable/pause, default enabled after cutover, and no
  normal-success notification/chat injection behavior.
- Restrict proactive capabilities to approved read/plan/activity set; exclude
  learner code execution explicitly.

### Acceptance

- Repeated signal creates at most one eligible candidate in dedupe window;
  ineligible candidates persist a no-action reason.
- Paused or budget-exhausted user makes no provider/tool request.
- Successful proactive work creates activity/inbox state, not chat or desktop
  notification.
- Scheduler decisions are traceable and recover safely after worker retry.
- A hard background pause, inferred-memory disable, or curation-budget denial
  prevents a Curator provider call; retry/re-delivery cannot create duplicate
  work for the same outbox key.

### Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_proactive_candidates.py tests/test_tutor_proactive_policy.py tests/test_tutor_memory_curation_scheduler.py tests/test_worker_import.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

Rollback point: globally pause candidate leasing while retaining signal/audit
rows. Existing learning/review behavior cannot depend on a proactive run.

## Child 05: Plans, Memory, Activity, and User Controls

### Scope

- Add immutable plan revision lineage, structured diff, evidence refs,
  policy-permitted autonomous activation, and one-action rollback.
- Replace opaque learner profile writes with evidence-backed memory entries,
  user inspection/correction/deletion/global disable, and objective service
  fact ingestion.
- Implement the guarded Memory Curator / Context Compactor on Child 02's
  redacted outbox and Child 04's generic queue. It uses the configured primary
  provider/model only with lower curation budgets and can output only typed
  context-summary or memory-entry proposals; policy/service/repository code
  validates and commits any projection.
- Add learner-safe activity timeline/inbox repositories and API contracts.
- Ensure Tutor plan/memory/note effects use compare-and-set input revision and
  user-owned idempotency.

### Acceptance

- Activated plan revision has immutable predecessor, learner-safe reason,
  structured diff, source run/evidence, and tested rollback.
- Plan revision does not itself update FSRS; review/FSRS services keep authority.
- Memory separates objective fact from inference; inferences need
  evidence/confidence and all entries support user correction/delete/disable.
- Curator output carries closed source evidence, confidence, provenance,
  staleness/retention, current policy/setting version, and idempotency. It cannot
  directly create activity/inbox/chat, alter plan/review/FSRS/attempt state, or
  fall back to another provider/model.
- Activity/inbox is user-scoped and never exposes trace/provider reasoning.

### Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_plan_revisions.py tests/test_tutor_memory.py tests/test_tutor_memory_curator.py tests/test_tutor_activity.py tests/test_tutor_effect_commit.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

Rollback point: prior active revision is untouched until activation commits.
Rollback is an explicit pointer/action change, never destructive rewrite of
immutable revision data.

## Child 06: Tutor API, SSE, and Desktop

### Scope

- Implement Tutor conversation/input/run/event endpoints and versioned errors.
  Build legacy endpoint adapters only for defined migration window.
- Extend SSE parser for replay cursor, input acknowledgement, run state,
  activity, and current compatible event types.
- Keep composer enabled during active run. Send durable input events instead of
  a competing stream request, frontend abort, or choice modal.
- Build guided goal entry, conversation, activity inbox/timeline, plan
  diff/rollback, memory settings/provenance/retention state, proactive pause,
  and diagnostics access.
- Use the current `aearn/apps/desktop/src/` implementation and approved product
  interaction contracts as the UI baseline. The historical HTML design reference
  is non-authoritative and may be changed, replaced, or removed when scoped
  frontend work requires it.

### Acceptance

- Desktop submits a message and a second message while same run is active; the
  second is acknowledged and merged without destructive cancel.
- Reconnect resumes one assistant/tool-card timeline without duplicate events.
  Partial stale output never commits plan/effect.
- UI exposes action reason, source, execution result, activity/inbox, plan
  diff/rollback, memory control, proactive pause; it never renders raw trace,
  chain-of-thought, Attempt/FSRS internals, provider details, hidden tests.
- Learners can identify a memory entry as trusted-domain fact or Curator
  inference, inspect learner-safe evidence/confidence/provenance/retention,
  correct or delete it, and disable future inferred memory without seeing a
  Curator prompt, source segment, rationale, or provider payload.
- Old event rendering remains compatible while adapter is enabled.

### Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_tutor_input_merge.py -q
pnpm --dir .\aearn desktop:check
```

Browser smoke when services run:

1. Open `http://127.0.0.1:1420` with a disposable fixture user.
2. Complete cutover, send free-text goal, then send another instruction while
   first run streams; verify no modal and visible merge acknowledgement.
3. Inspect activity/inbox, plan revision diff/rollback, memory controls, and
   proactive pause.
4. Verify no console error and narrow-window behavior.

Rollback point: desktop gates Harness UI by server cutover/feature response.
Legacy UI remains isolated until explicit cutover authorizes removal.

## Child 07: Cutover and Legacy Retirement

### Scope

- Extend data summary/reset with server-authoritative legacy detection and
  one-time `harness_cutovers` gate.
- Implement explicit confirmation, atomic deletion/verification, stale
  bootstrap/idempotency invalidation, and desktop blocking state.
- Delete confirmed user's legacy plans, sessions, messages, attempts, reviews,
  notes, profile/preferences, old Agent artifacts, and LangGraph checkpoints.
  Preserve local identity, provider/model config, and UI settings exactly as
  specified.
- Route cut-over users to Tutor endpoints; remove Graph/router/old tools/docs
  and unused dependencies only after replacement coverage is green.

### Acceptance

- Legacy data blocks both runtimes until exact deletion/preservation summary is
  reviewed and confirmation is received.
- Confirmation never happens automatically. Repository verifies all specified
  legacy rows/checkpoints are gone before successful cutover record.
- Verification failure remains blocked with `CUTOVER_VERIFICATION_FAILED`; it
  cannot open half-reset runtime.
- Completed cutover opens guided Tutor goal conversation with retained
  identity/local configuration and no stale plan/session bootstrap.
- Graph/routing code is removed only when endpoint/test/runtime caller search
  is empty and Harness integration suite is green.

### Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_harness_cutover.py tests/test_local_user_data_repository.py tests/test_tutor_routes.py -q
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-agent-harness-rearchitecture
```

Rollback point: legacy feature path is available before confirmation. After a
user confirms deletion, never claim code rollback restores deleted data; warn
about irreversibility before confirmation.

## Child 08: Integration QA and Documentation

### Scope

- Replace/archive obsolete Graph-specific docs only after Harness replacement is
  source-of-truth.
- Update user flows, frontend interaction, API/database, sandbox operations,
  provider config, worker policy, evaluation, acceptance, and runbook docs.
- Run cross-layer tests sequentially where bootstrap DB is shared.
- Audit/remove unused LangGraph, checkpointer, and Agents SDK dependencies once
  no retained caller needs them.

### Required Release Matrix

| Area | Required proof |
| --- | --- |
| Provider | Primary-only retry, `MODEL_UNAVAILABLE`, no cross-provider call. |
| Tutor loop | Finite budgets, lease recovery, Skill validation, input merge, stale effect rejection. |
| Grounding | Registered sources only, valid citations, no arbitrary URL/search capability. |
| Effects | Repository authority, idempotency, revision compare-and-set, redaction. |
| Plans/memory | Revision diff/rollback, evidence-backed memory, Curator proposal-only boundary, redacted outbox/idempotency, provenance/retention, user controls. |
| Sandbox | No default network, limits, allowlist, cleanup, no proactive execution. |
| Scheduler | Deduplication, cooldown, pause, budget/circuit breaker, inbox-only success. |
| API/SSE | Legacy compatibility window, cursor replay, error envelopes, terminal ordering. |
| Desktop | Guided entry, composer enabled, activity/inbox, diagnostics separation, narrow viewport. |
| Cutover | Explicit confirmation, verified deletion, retained settings/identity, no stale bootstrap. |

### Full Verification Sequence

Run bootstrap-heavy API suites sequentially:

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-agent-harness-rearchitecture
git diff --check
```

Then run Docker/executor health checks and designated browser smoke against
this checkout. Record exact commands, results, warnings, and residual risks in
QA/release documentation. A desktop build alone is not proof of input merge,
cutover, container, or worker correctness.

## Cross-Child Integration Gates

1. No UI/client calls an untyped Harness function or capability.
2. No run/effect/SSE implementation uses an in-memory-only source of ordering
   or trace truth.
3. No Harness learner can execute code through current subprocess runner.
4. Proactive work cannot bypass capability/budget checks; plan/memory effects
   cannot bypass evidence and revision validation.
5. No Curator path is per-token or directly writes memory/domain state. It must
   use the ordered redacted outbox, low-priority curation policy, typed proposal,
   and normal policy/service/repository validation path.
6. Composer merge always uses durable input events, never frontend queue alone.
7. No old Graph/router/tool/checkpointer caller or stale data path remains
   before retirement.
8. Source-of-truth docs agree and full matrix passes before parent archive.
9. Every child has an explicit dependency/authority section and its own curated
   context manifests before it starts; parent tree order alone is never an
   executable dependency contract.

## Migration and Rollback Rules

- Use additive Harness migrations/flags before explicit user-confirmed deletion.
- Keep versioned API adapter only while actively tested; do not retain dual
  orchestration indefinitely.
- Never migrate legacy history to new Tutor records. Cutover starts clean.
- Roll back code/configuration by feature flag before cutover; do not silently
  reconstruct intentionally deleted history after cutover.
- Use disposable fixture users for destructive tests.
- Never stage/deploy unrelated dirty worktree changes.

## Parent Completion Criteria

Planning moves to implementation only after user approves all three planning
files. Parent archives only when every child is independently validated,
integration gates pass, source-of-truth docs are updated, full verification is
recorded, and planned legacy retirement is complete.

