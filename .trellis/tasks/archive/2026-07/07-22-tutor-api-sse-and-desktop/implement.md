# Tutor API, SSE, and Desktop Implementation Plan

## Preconditions

1. Child 00–05 contracts are archived and the current `main` worktree is clean.
2. The transition contract, Child 06 PRD/design, backend/frontend specs, and
   source code have been re-read. The implementation uses the current routes,
   Tutor repositories, `aearn/apps/desktop/src/`, and no historical tutorial
   runtime.
3. `TUTOR_HARNESS_ENABLED` remains false by default. No step enables it,
   invokes a real provider in tests, starts a worker, performs a cutover, or
   deletes/migrates legacy learner data.
4. This is Codex inline execution. Work remains local to this child; no
   implementation/check sub-agent is dispatched.

## Ordered Implementation Checklist

### 1. Freeze the Public Compatibility Contract

- Add the Child 06 endpoint/event/adapter matrix to the transition contract.
- Declare numeric per-run SSE ids, `Last-Event-ID` parser behavior, event
  mapping, mutation idempotency, stable errors, and the pre-cutover gate.
- Keep broad legacy API/product documentation unchanged until Child 08; mark
  only the target transition contract that this child owns.

### 2. Extend Target-Only Read and Action Persistence

- Add narrow repository methods for learner-visible conversation lookup,
  reusable interactive run selection under a conversation lock, scoped public
  assistant terminal-message lookup, plan revision history/diff, and safe
  evidence references.
- Add a target-only API idempotency receipt and database constraints/indexes;
  validate replay body hashes and return existing learner-safe response data.
- Add an explicit user-control rollback method. It may move only from the active
  revision to its recorded predecessor, writes an append-only action with no
  fabricated Agent effect, and preserves immutable revision data.
- Keep all writes scoped by `user_id`, conversation/run association, and target
  tables. Do not write `learning_plans`, profiles, reviews, FSRS, attempts,
  Graph checkpoints, or legacy idempotency records.

### 3. Add Typed Tutor Route Models and Service Boundary

- Create a narrow `routes/tutor.py` plus Pydantic request/response models under
  the existing API model convention. Register it in `app/main.py`.
- Centralize feature-gate, user/run/conversation validation, idempotency,
  repository construction, error mapping, and safe serializers in a Tutor API
  service/helper module rather than duplicating SQL in routes.
- Add conversation create/resume, conversation/run input, run state, activity,
  inbox, memory, plan revision/rollback, and preference endpoints.
- Preserve mutation retry/replay behavior and return one stable JSON envelope
  for all non-2xx outcomes. A disabled route returns `CUTOVER_REQUIRED` before
  target-domain writes.

### 4. Implement Durable SSE Cursor Adaptation

- Add a scoped async SSE generator backed only by `events_after()`, public
  message lookup, and run state. It does not call the provider, loop, worker,
  or legacy Graph while streaming.
- Parse `Last-Event-ID`, map durable events to legacy-compatible and new event
  names, frame single-line JSON with numeric ids, poll safely while nonterminal,
  and terminate with `done` or `error` only for a terminal outcome.
- Ensure terminal output and any activity projection are learner-safe; do not
  treat diagnostic safe-projection rows as a general conversation store.

### 5. Add Pre-Cutover Desktop Contracts and Components

- Add typed Tutor API helpers, public response guards, and an isolated
  `useTutorSSE` hook that remembers/reuses the highest durable cursor and
  deduplicates frames.
- Build focused Tutor workspace/activity/memory/plan/preference components using
  existing UI primitives and global CSS. Keep the existing app route legacy by
  default; the future Child 07 server gate owns activation.
- Keep the composer enabled while a run is active; a follow-up sends the durable
  input mutation and renders the acknowledgement instead of aborting, opening a
  choice modal, or issuing a competing legacy SSE request.
- Keep all protected internals absent from types, components, labels, errors,
  and diagnostic panels.

### 6. Add Focused Tests and Cross-Layer Checks

- Add API tests for disabled gate, conversation/run ownership, input replay and
  conflict, active-run merge, terminal rejection, stable envelopes, plan/memory
  user controls, and no legacy mutation.
- Add SSE tests for cursor replay, duplicate-free ordered timeline, terminal
  mapping, invalid cursor, no unsafe payload fields, and incomplete reconnect
  behavior.
- Add direct repository tests for public read/action idempotency and
  predecessor-only rollback; run bootstrap-related database tests sequentially.
- Add desktop static/type coverage where practical; at minimum run the full
  desktop TypeScript/Vite check and inspect no legacy runtime route changed.

### 7. Record Verified Contract Delta

- Update `docs/architecture/tutor-harness-transition.md` with only proven Child
  06 public compatibility facts and remaining Child 07 cutover gate.
- Update the relevant Trellis backend/frontend quality guidance only for a new
  reusable contract discovered during implementation.
- Do not claim that legacy routes are removed, the Harness is active, a provider
  is enabled, or user data has been reset.

## Required Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_tutor_input_merge.py tests/test_learning_plan_revisions.py tests/test_tutor_memory.py tests/test_tutor_activity.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-api-sse-and-desktop
git diff --check
```

Run database/bootstrap-heavy API tests sequentially. Browser smoke is optional
only when the local services are already running; it must use a disposable
fixture user and may not trigger a real provider, an enabled scheduler, or a
cutover.

## Review Gates and Rollback

- The compatibility matrix and request/response union types must be complete
  before routes/UI are wired.
- No response, event, store, or component may expose raw trace, Curator prompt,
  provider/model data, code, path, hidden-test, Attempt, or FSRS internals.
- No legacy Graph route may import the new Tutor route/service or read a target
  feature flag implicitly.
- Rollback is feature-gate/UI routing only before Child 07. Do not use Git or
  schema rollback to represent restoration of user data.