# Tutor Proactive Scheduler Implementation Plan

## Status and Preconditions

This is the selected next child in planning only. Do not run `task.py start`
until the user reviews this child-level plan. Do not change legacy Graph
behavior, API/SSE/Desktop behavior, user data, deployment configuration, or
production scheduling during this work.

Before source edits:

1. Load `trellis-before-dev` and the backend/database specs for the affected
   API and worker layers.
2. Confirm the current worktree is clean or isolate only intentional Child 04
   changes; do not stage/revert unrelated files.
3. Repair the existing fake-only catalog-eval fixture regression by recomputing
   its full snapshot digest from `compile_published_skill_catalog()`. Preserve
   the strict digest/hash assertion and run `tests/test_tutor_evals.py` green.
4. Re-run the Child 00-02 focused regression set and confirm the transition
   contract still exposes the finite loop, origin-aware policy, durable
   outbox, redaction, and idempotency boundaries consumed here.
5. Keep inline-mode context behavior: no JSONL dispatch-manifest curation is
   required; source work is instead grounded through `trellis-before-dev`.

## Ordered Implementation Checklist

### 1. Publish the Scheduler Delta and Typed Origin Boundary

- Extend `docs/architecture/tutor-harness-transition.md` with the Child 04
  signal, pause, budget, candidate, curation-queue, and delivery constraints.
- Add the persisted `origin` to `TutorRunSnapshot` and its row mapping. Update
  fakes/tests so interactive origin is explicit, unknown origin is rejected,
  and policy resolution cannot silently assume an interactive permission set.
- Introduce typed scheduler configuration/policy facts with fail-closed defaults
  for global enable, hard pause, candidate and curation budgets, lease duration,
  retry/backoff, concurrency, and circuit breaker.

**Risk / rollback:** this is an additive contract change. Default all new
feature paths to denial, and revert isolated target modules if an interactive
contract changes unexpectedly.

### 2. Add Additive Scheduler Schema and Repository Contracts

- Add target-only tables/indexes for proactive preferences, signals, candidates,
  scheduler audit, and curation jobs. Add a conversation visibility/kind marker
  for internal background conversations rather than reusing user-visible chat.
- Implement repository methods for signal ingestion/replay, dedupe-window
  candidate creation, policy/no-action audit, locked lease claim/heartbeat,
  retry backoff, terminal recording, and one-to-one curation job seeding.
- Preserve `tutor_memory_curation_outbox` as the semantic evidence envelope;
  queue mechanics live in the new job table and do not erase source evidence.
- Add database constraints and partial unique indexes that reject duplicate
  active candidates/jobs, cross-user references, invalid state transitions, and
  lease ownership races.

**Risk / rollback:** bootstrap remains repeatable and all changes are additive.
Do not rename, drop, backfill, or migrate legacy tables or existing `tutor_*`
records destructively.

### 3. Implement Deterministic Candidate Policy and Run Composition

- Build a service that accepts typed committed signals and bounded time-scan
  inputs, derives a stable dedupe identity, and persists every allow/deny
  result. No caller may directly invoke a model from a signal.
- Resolve global hard pause, user setting, verified-cutover eligibility,
  cooldown, user concurrency, daily budget, circuit breaker, capability allow
  list, and source scope before any lease/run is created.
- Compose a dedicated background conversation and `origin="proactive"` run
  through the existing finite `TutorRunLoop`. Ensure policies exclude
  `runner.execute` and any direct data write capability.
- Use an injected, typed future delivery/effect port. Until Child 05 supplies a
  permitted activity/inbox handler, successful model output may resolve only to
  safe no-action/terminal evidence, never a chat message or notification.

**Risk / rollback:** do not make target scheduler work a prerequisite for the
legacy review worker. A global pause must stop new claims immediately while
keeping audit evidence intact.

### 4. Add Worker Task Wrappers and Bounded Time Signals

- Add separate Celery task names/routes for time-signal scanning, candidate
  draining, and curation draining. Wrapper functions are thin and delegate to
  API service/repository code.
- Treat broker delivery as at-least-once: PostgreSQL claim and idempotency are
  authoritative. A retry must neither create a second active Tutor run nor
  invoke a provider after policy denial.
- Configure optional bounded beat enqueueing only behind target feature flags;
  test service logic with fixed time rather than relying on a live worker.
- Keep legacy review task names and behavior unchanged.

### 5. Add the Low-Priority Curation Queue

- Seed one curation job per eligible Child 02 outbox key and enforce distinct
  curation budget, concurrency, cooldown, retry, and circuit-breaker settings.
- Check hard background pause and inferred-memory disable before invoking the
  injected Curator processor. Record safe no-action/failed/stale outcomes.
- Invoke only the proposal-returning Child 05 processor contract. Do not add a
  Curator model implementation, direct memory write, activity/inbox write,
  plan action, review/FSRS write, chat output, or fallback provider here.

### 6. Build Focused Tests and Static Boundaries

- Add tests for dedupe replay, no-action persistence, cooldown/budget/concurrency
  denial, lease recovery, circuit-breaker behavior, explicit proactive origin,
  background-conversation invisibility, and no `runner.execute` policy path.
- Add curation tests for queue idempotency, hard pause, inferred-memory disable,
  independent curation budgets, stale outbox policy/version handling, retry,
  and proof that no provider call occurs after denial.
- Add worker import/routing tests that prove target task wrappers are discoverable
  without altering legacy review registration or making a live broker call.
- Add static/import checks that prevent route/SSE/Desktop modules and legacy
  Graph/review code from composing proactive Harness work directly.

### 7. Record the Narrow Documentation Delta

- Update the transition contract, worker README, and backend operational notes
  only for verified Child 04 behavior and feature-off operation.
- Do not claim product availability, public API/SSE delivery, desktop controls,
  user-visible activity/inbox semantics, or cutover completion. Those remain
  owned by Children 05-08.

## Required Validation

Run database/bootstrap-heavy tests sequentially:

```powershell
# Existing catalog fixture regression gate
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_evals.py -q

# Upstream contracts consumed by Child 04
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_tutor_skill_catalog.py tests/test_tutor_capability_gateway.py tests/test_tutor_grounding_policy.py tests/test_db_bootstrap.py tests/test_tutor_run_repository.py tests/test_tutor_event_replay.py tests/test_tutor_memory_curation_outbox.py tests/test_tutor_effect_commit.py tests/test_tutor_trace_redaction.py -q

# New Child 04 tests
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_proactive_candidates.py tests/test_tutor_proactive_policy.py tests/test_tutor_memory_curation_scheduler.py tests/test_worker_import.py -q

uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-proactive-scheduler
git diff --check
```

Exercise a worker only after local PostgreSQL and Redis are running. Do not
enable real model credentials for normal test coverage; use deterministic fakes
and disposable fixture users. A live worker smoke must verify that a paused or
budget-denied candidate produces no provider/capability invocation and no chat
or desktop notification.

## Review Gates and Rollback

- Review the exact source of every proactive signal; it must follow a committed
  domain fact or a documented bounded time policy, not a legacy stage flow.
- Review all schema constraints, lock queries, and state transitions for
  at-most-one active claim and idempotent broker redelivery.
- Review policy tests for fail-closed defaults, origin propagation, code-execute
  denial, hard pause, inferred-memory disable, and distinct curation budgets.
- Review redaction to ensure scheduler audits and queue rows contain no prompt,
  provider payload, raw learner text, code, hidden test, secret, host path, or
  cross-user data.
- Roll back by disabling scheduler task routing/claims and setting global hard
  pause. Do not delete signal/audit data, change legacy review behavior, or use
  code rollback as a claim that any later cutover deletion can be recovered.
