# Tutor State, Traces, and Evaluation Foundation Implementation Plan

## Preconditions Before Start

- The parent remains `planning`; only
  `.trellis/tasks/07-22-tutor-state-traces-and-evals` may enter
  `in_progress` after the user approves this final plan.
- Load the curated backend specs/research manifests, this PRD/design, the
  parent implementation order, and `docs/architecture/tutor-harness-transition.md`
  before modifying code.
- Recheck the current worktree and avoid staging the 80 pre-existing unrelated
  Trellis/tooling/document/output changes. Do not reset, restore, clean, or
  force-stage broad `.trellis/` paths.
- Preserve `TUTOR_HARNESS_ENABLED=false`; no product composition, route, SSE,
  Desktop, worker, legacy Graph/router/tool, provider-routing, or deployment
  change is permitted.
- Database/bootstrap-heavy tests run sequentially. Confirm the project-local
  PostgreSQL prerequisite when executing those tests; if unavailable, report
  the specific blocker rather than replacing transactional tests with fakes.

## Ordered Implementation Checklist

### 1. Freeze the Durable Contracts and Additive Schema

- Inspect existing Harness contracts, ports, run loop, catalog selection, schema
  bootstrap, repository conventions, and current redaction helpers immediately
  before editing; reuse typed metadata and hash contracts rather than copying
  ad-hoc JSON models.
- Add narrow immutable persistence DTOs/enums/receipt types for input
  acceptance, lifecycle persistence, replay, safe trace/export, catalog
  snapshot/selection, capability/effect receipts, and outbox/proposal envelopes.
  Keep raw learner text out of all diagnostic DTOs.
- Append a marked additive Tutor Harness block to
  `aearn/services/api/app/db/schema.sql` with the table family, foreign keys,
  constraints, indexes, and trigger handling defined in `design.md`.
- Extend `tests/test_db_bootstrap.py` with target-table/constraint smoke checks
  and repeatability coverage. Do not introduce Alembic, a version table, or
  destructive legacy-table edits.

**Risk / rollback:** SQL mistakes are broad because bootstrap executes the full
schema. Keep every DDL change additive/idempotent and prove two applies before
wiring repositories. Rollback is removal of unused composition code, never
schema/data deletion.

### 2. Implement PostgreSQL Repository and Transaction Helpers

- Add a narrow Tutor persistence module under `app/services/tutor/` following
  existing injected-port and caller-owned-connection patterns. It must scope
  every read/write by user and run/conversation identity.
- Implement run creation/load, catalog snapshot persistence, exact selection
  persistence, lease acquire/heartbeat, current revision, cancellation lookup,
  and internal `events_after` reads with bounded ordered suffixes.
- Implement `accept_input` as one transaction: request key/body hash replay or
  conflict, raw message insert only in `tutor_messages`, monotonic revision
  update under a run lock, input-event insert, and one safe ordered event.
- Add focused PostgreSQL tests for authorization/scope, same-key replay,
  body-hash conflict, concurrent revision allocation, terminal-state rejection,
  sequence uniqueness, and cursor suffix behavior.

**Risk / rollback:** Do not copy the legacy unlocked idempotency read/insert
pattern for concurrency-sensitive Tutor writes. Use natural unique constraints,
row locks/conditional updates, and catch/reload only when it preserves the
same deterministic receipt.

### 3. Integrate a Transactional Lifecycle Adapter

- Define/implement the explicit lifecycle persistence boundary for checkpoint,
  waiting/terminal result, safe event, redacted trace, and compaction request.
  Its PostgreSQL implementation must write the complete lifecycle receipt in
  one transaction and return a stable stale/final/lease result to losing work.
- Refactor `TutorRunLoop` at its existing persistence call sites so it delegates
  safe checkpoint/terminal/result/compaction persistence to the lifecycle
  adapter rather than independently committing store/publisher calls.
- Retain compatible in-memory fakes/defaults for Child 00 tests and add a
  deterministic failure-injection fake proving no partial lifecycle receipt.
- Preserve loop ordering: refresh at unsafe boundaries, retain bounded context
  behavior, retain primary-only provider failure behavior, and never silently
  enable a public composition path.

**Risk / rollback:** Constructor changes can regress Child 00 tests. Supply
explicit fake implementations and migrate tests atomically; never make an
individual database write appear transactionally safe by composing it with a
separate publisher commit.
### 4. Persist Capability, Effect, and Catalog Replay Evidence

- Replace only the composed target's run-local Skill-selection store with a
  durable adapter that records exact catalog digest/id/version/manifest/
  instruction/evaluation hashes by run revision and emits a safe selection
  event. Reject `current`, ranges, unknown snapshots, and hash mismatches.
- Persist capability invocation receipts with descriptor/policy/revision/lease
  facts, bounded safe argument/result summaries, status/code, and event link.
  Do not store raw provider payloads or arbitrary capability targets.
- Add `commit_effect_if_current` with run row lock/conditional checks on user
  scope, active owner/generation/expiry, terminal state, expected revision, and
  idempotency. Persist stale rejection plus a safe event without calling a
  domain committer.
- Keep all effects default-deny in actual composition. Define the future
  in-transaction handler seam but do not add a plan/review/memory/FSRS/activity
  effect or an external at-least-once side effect in this child.

**Risk / rollback:** A pre-read revision check is not CAS. Ensure test doubles
record whether their committer was invoked; stale/duplicate paths must prove it
was not invoked twice.

### 5. Build the Safe Projection and Curation Storage Envelope

- Create one reusable safe projection/export utility around the existing
  Harness/runtime redaction rules. Apply it before trace/event/outbox/proposal
  writes and again on all diagnostic/export reads.
- Add bounded redacted trace persistence linked to lifecycle/event facts. Test
  all protected key/value variants, including provider errors, secrets, hidden
  tests, solution material, full code, paths, stack traces, shell/SQL targets,
  and credential-bearing URLs.
- Persist the deterministic typed compaction outbox atomically with terminal,
  safe-checkpoint, or high-water lifecycle writes. Store closed ranges,
  source hashes, policy/memory-setting versions, retention/staleness and stable
  idempotency; do not publish a worker job.
- Persist one structurally bounded proposal envelope per outbox identity with
  deduplicated pending/no-action/stale/failed state. Reject direct writes to
  messages, plans, learner memory, review/FSRS, attempts, activity/inbox, or
  runner state through this repository.

**Risk / rollback:** A JSON column is not permission to store arbitrary data.
Enforce schema-level/repository-level bounds and project defensively on export.
Do not let an outbox/proposal table become a second raw conversation store.

### 6. Add Deterministic Evaluation Fixtures and Focused Tests

- Add source-controlled fixtures under `tests/fixtures/tutor_evals/` and a
  deterministic fake-only evaluation runner. Version fixture formats and pin
  expected catalog/Skill identity so tests cannot resolve a mutable alias.
- Cover policy denial, strict provider envelope rejection, bounded loop exit,
  input/CAS race, primary-only `MODEL_UNAVAILABLE`, duplicate replay/outbox/
  proposal behavior, terminal uniqueness, and redaction leakage.
- Add new focused test modules for repository/input/event replay/effect CAS/
  curation envelope/trace redaction/evals, plus targeted regression assertions
  in Child 00/01 tests where constructor or adapter contracts changed.
- Run database transactions/concurrency coverage sequentially; do not make the
  eval runner rely on a live model, network, worker, or wall clock.

### 7. Update the Target Contract and Complete Review

- Update `docs/architecture/tutor-harness-transition.md` with Child 02's
  target schema ownership, exact selection replay, internal event cursor,
  lifecycle atomicity, trace/export rule, outbox/proposal envelope, and explicit
  Child 04/05/06 ownership boundaries.
- Update `.trellis/spec/backend/quality-guidelines.md` only if implementation
  discovers a reusable Harness persistence/redaction rule not already present.
  Do not broadly rewrite legacy/current source-of-truth documents.
- Inspect the complete diff and all staged files. Verify forbidden Harness
  imports (legacy Graph/router/tools, DB connections inside catalog/harness,
  worker/route/SSE/Desktop accidental wiring) and verify no previously dirty
  user-owned files were staged.

## Required Validation

Run focused tests first. Database/bootstrap-heavy commands must run one after
another, not in parallel:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_repository.py tests/test_tutor_event_replay.py tests/test_tutor_effect_commit.py tests/test_tutor_memory_curation_outbox.py tests/test_tutor_trace_redaction.py tests/test_tutor_evals.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_tutor_skill_catalog.py tests/test_tutor_capability_gateway.py tests/test_tutor_grounding_policy.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-state-traces-and-evals
git diff --check
```

If the existing local `uv` trampoline cannot canonicalize Mypy, use the listed
`python -m mypy app --no-incremental` variant from the API service directory;
do not change project tooling merely to bypass a local launcher issue.
## Review Gates

Before implementation dispatch:

- Confirm the task has current `prd.md`, `design.md`, `implement.md`, and real
  curated entries in both manifests; run task validation and present this plan
  for a fresh user approval.
- Confirm Child 00/01 commits and the transition contract still supply the
  required upstream contracts. If their surface changed, return to planning
  rather than guessing a compatibility adapter.

Before the work commit:

- Confirm all new persistence is `tutor_*`, additive, scoped, and feature-off.
- Confirm every raw learner text write is restricted to `tutor_messages` and
  every diagnostic/event/outbox/proposal/export path passes the dual safe
  projection.
- Confirm terminal/outbox/event/checkpoint lifecycle calls share one database
  transaction, effect CAS checks lease and revision together, and no actual
  domain effect/Curator/worker/API/SSE/Desktop behavior slipped into scope.
- Run the full required validation sequence, inspect `git diff --check`, and
  stage only the intentional Child 02 code/tests/contract/spec changes. Do not
  push without a separate user request.

## Rollback Summary

- **Before composition/enablement:** revert the isolated Tutor persistence
  adapter, loop integration, fixtures, and target transition wording. Legacy
  product behavior remains untouched because the feature is still disabled.
- **Schema/data:** retain the additive `tutor_*` tables; do not drop rows or
  modify legacy learner data as a rollback shortcut.
- **Failure containment:** return typed safe stale/lease/denial/failure receipts
  and preserve no partial lifecycle transaction. Default-deny is the fallback,
  never broad capability/effect/provider behavior.