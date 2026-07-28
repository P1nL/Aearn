# Harness Cutover and Legacy Retirement Implementation Plan

## Preconditions and Safety Gate

- This plan is intentionally inactive while the task is `planning`. Do not run
  `task.py start`, enable `TUTOR_HARNESS_ENABLED`, call a real provider, start a
  worker/executor, or invoke reset/delete endpoints against a real local user
  before the user accepts the start review.
- Read the applicable Trellis backend/frontend specs with `trellis-before-dev`
  before editing code. The normal reset contract remains intact; this task adds
  a separate cutover path.
- Use only disposable PostgreSQL test users and rollback-scoped test fixtures.
  Never use a `LIKE`/JSON content search as the ownership basis for deletion.

## Ordered Implementation

### 1. Freeze the target delta and scope inventory

- Update `docs/architecture/tutor-harness-transition.md` with the approved
  Child 07 deletion/preservation matrix, gate states, confirmation contract,
  cutover error codes, and the distinction between ordinary reset and cutover.
- Audit all user-scoped legacy entry points before adding a gate: onboarding,
  plan/dashboard/resume, learning session/Graph/SSE, review, notes, local data
  privacy actions, and legacy review worker writes. Record the exact affected
  routes/services in code comments/tests; do not gate health/static catalog
  paths without user scope.
- Inventory target user-owned tables and the LangGraph package tables at runtime
  through an explicit scope registry. Shared `tutor_catalog_snapshots`, course,
  runtime, grounding, and `checkpoint_migrations` metadata are excluded.

### 2. Add cutover persistence and contracts

- Add repeatable `harness_cutovers` schema/indexes/constraints to
  `aearn/services/api/app/db/schema.sql`.
- Add typed request/response models for `GET /api/harness/cutover` and
  `POST /api/harness/cutover/confirm`, including `user_id`, server preview
  version/nonce/hash, `confirm`, and client idempotency identity.
- Implement a dedicated `app/services/tutor/cutover.py` (or equivalently narrow
  cutover repository/service package) that owns canonical summary projection,
  state transitions, confirmation replay validation, runtime gate decisions,
  exact ownership SQL, and safe errors. Keep generic reset/export APIs focused
  on their existing contract.
- Make the summary canonical by serializing only stable cutover version,
  category identifiers, counts, field-state flags, and target/checkpoint safe
  dispositions before hashing. Do not store raw record content.

### 3. Implement the safe deletion/verification transaction

- Add one transaction path that locks the retained user row and cutover record,
  recomputes summary, rejects stale/nonmatching confirmation, takes the target
  contamination/checkpoint-scope fail-closed branches, and then deletes only
  the confirmed user's legacy scope.
- Refactor only low-level reusable SQL from
  `local_user_data_repository.py` as needed. The cutover-specific path must:
  - delete exact `idempotency_records.user_id = :user_id` rows;
  - delete dependent messages/logs/state/facts before sessions/plans;
  - clear `knowledge_points.last_session_id` before legacy session deletion;
  - delete profile rows and normalize exactly the five legacy learner fields;
  - preserve identity and notification/UI preferences; and
  - verify the exact same scope after deletion before writing `verified`.
- Implement the LangGraph checkpointer adapter with `to_regclass` checks and
  thread ids derived from pre-delete learning sessions. Delete rows only from
  `checkpoint_writes`, `checkpoint_blobs`, and `checkpoints` matching those
  thread ids. Missing tables are safe zero; unscoped/unknown persistent state
  is a block, never a table-wide cleanup.
- On injected SQL/verification error, roll back the deletion transaction and
  persist a separate safe failure receipt. The verified record and guided
  entry must never be written on this branch.

### 4. Compose the server runtime gate

- Register the narrow cutover router in `app/main.py` and gate it according to
  the controlled rollout policy.
- Replace Tutor's current flag-only `_require_tutor_route()` check with a
  composition of the global flag and verified per-user cutover state. Preserve
  Child 06's disabled-route behavior before rollout.
- Apply the common transaction-scoped gate/lock to all audited legacy
  user-scoped runtime paths and review worker writer paths. Once global rollout
  is active, nonverified users must get a stable cutover error rather than a
  legacy response or side effect.
- Ensure generic reset/delete cannot downgrade a verified user or create a
  stale legacy route. Preserve the existing local-user delete semantics where
  they do not conflict with soft deletion.

### 5. Make Desktop bootstrap cutover-aware

- Add typed desktop API helpers and discriminated cutover response/error types.
- Extend app bootstrap so the decision is fetched after identity selection and
  before legacy `planId`/dashboard/session restoration.
- Add the blocking cutover page: server category summary, retained-category
  copy, irreversible confirmation action, disable/retry state, and no hidden
  automatic confirmation.
- Add `tutor` as a server-authorized route only after verification. On success,
  write `aearn.bootstrap` with retained `userId` and null `planId`, clear legacy
  app/store/settings-form state, preserve unrelated local UI storage, then mount
  `TutorWorkspacePage` without an initial conversation id.
- Keep existing legacy UI mounted/routable only while rollout is inactive; do
  not delete it in this implementation step.

### 6. Add focused tests and validation fixtures

Create `tests/test_harness_cutover.py` using a disposable DB user and the
existing Tutor/local-user test support. Cover at minimum:

1. legacy data produces exact summary and blocks both runtimes;
2. absent `confirm=true` leaves all rows unchanged;
3. stale summary after a new legacy write fails without deletion;
4. cross-user preview/confirmation is rejected;
5. same confirmation replay is safe and a changed body conflicts;
6. success deletes every legacy category and known owned checkpoint row while
   retaining identity/notification settings and clearing only the five learner
   profile fields;
7. unrelated user legacy/checkpoint rows survive;
8. pre-cutover target data blocks without deleting target or legacy rows;
9. an injected verification failure rolls back deletion, records
   `CUTOVER_VERIFICATION_FAILED`, and blocks both runtimes;
10. verified bootstrap clears only legacy `planId` and reaches a new Tutor
    entry without a legacy request; and
11. the current ordinary reset test still preserves preferences, proving it was
    not silently converted into a cutover.

Use a temporary/checkpoint adapter test double or same-connection temporary
known schema for checkpoint scope coverage. Do not require a live model,
provider, executor, or worker.

### 7. Perform legacy retirement only after replacement proof

Do not merge this physical removal with the first cutover transaction. Only
once all cutover/desktop/integration checks are green:

- run a scoped source/test import/caller search for Graph/router/tools and
  `langgraph` references;
- confirm no legacy route, worker, or desktop code is still a production
  caller;
- remove legacy Graph/routes/tools/tests/dependencies in small verified edits;
  and
- hand the source-of-truth documentation reconciliation to Child 08.

## Planned Files and Risk Points

| Area | Likely files | Primary risk / rollback point |
| --- | --- | --- |
| Schema and service | `app/db/schema.sql`, new `app/services/tutor/cutover.py`, `app/services/repositories/local_user_data_repository.py` | FK delete order, exact ownership, and atomic rollback. |
| API gate | new cutover route/models, `app/main.py`, `app/routes/tutor.py`, audited legacy routes | Never allow global flag alone to authorize a user. |
| Legacy worker | `aearn/services/worker/aearn_worker/worker_app.py` and API-side legacy review services as evidence requires | Prevent a worker from recreating legacy state during cutover. |
| Desktop | `apps/desktop/src/App.tsx`, `stores/useAppStore.ts`, bootstrap storage/API/types, new cutover screen | Do not restore legacy `planId` before the server decision. |
| Tests | `tests/test_harness_cutover.py`, `tests/test_local_user_data_boundary.py`, `tests/test_tutor_routes.py` | Must use test users and assert cross-user isolation/replay behavior. |
| Retirement | Graph/routes/tools/deps/docs only after evidence | Code rollback is never data recovery. |

## Required Verification Before Reporting Implementation Complete

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_harness_cutover.py tests/test_local_user_data_boundary.py tests/test_tutor_routes.py -q
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-harness-cutover-and-legacy-retirement
```

Before a Graph retirement edit, additionally run the focused replacement suite
and a scoped import/caller search, for example:

```powershell
rg -n --glob '*.py' 'app\.agents\.graphs|from langgraph|langgraph-checkpoint|graph_event_stream' aearn\services\api\app aearn\services\api\tests
```

Record whether PostgreSQL-backed tests ran or were skipped because the local
infrastructure was unavailable. A passing task manifest validation is not proof
of data-deletion correctness.
