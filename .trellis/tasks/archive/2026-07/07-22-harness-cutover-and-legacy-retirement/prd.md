# Harness Cutover and Legacy Retirement

## Goal

Deliver the one-time, verified, clean-slate cutover from the legacy learning
runtime to the Skill-Native Tutor Harness. The cutover must be
server-authoritative, explicitly confirmed when it destroys data, and unable to
open either runtime after a partial or unverifiable operation.

## Dependencies and Documentation Authority

- Depends on completed Child 02 durable target persistence, Child 05 learner
  state, and Child 06 public API/SSE/Desktop compatibility. The parent task
  hierarchy is not a substitute for these contracts.
- `docs/architecture/tutor-harness-transition.md` is the narrow target contract
  during migration. The current user/reset, API, database, Graph, and desktop
  specifications remain baseline evidence until this child and Child 08 publish
  a verified replacement delta.
- This is a complex child. `design.md`, `implement.md`, and curated context
  manifests are required before `task.py start`.

## Confirmed Repository Facts

- The normal Tutor route is intentionally feature-off: with
  `TUTOR_HARNESS_ENABLED=false`, `/api/tutor/*` returns `CUTOVER_REQUIRED`
  before opening a target connection. This flag is a deployment composition
  control, not evidence that a user has cut over.
- Current `reset_user_data()` is a reusable legacy reset, not a cutover. It
  preserves every `users` preference column, deletes legacy rows through a
  broad `idempotency_records` `LIKE` clause, has no one-time receipt, no
  cutover hash, no target-state check, and no post-delete verification.
- The legacy Graph runtime is still called by onboarding, learning, review,
  streaming, and agent/tool code. It cannot be removed in the first deletion
  change.
- `langgraph-checkpoint-postgres==3.0.2` is installed, but the current code has
  no `PostgresSaver` import and compiles Graphs without a checkpointer. Its
  known PostgreSQL tables are nevertheless `checkpoints`, `checkpoint_blobs`,
  and `checkpoint_writes`; current learning thread ids are exactly
  `aearn:learning:<learning_session_id>`.
- Target `tutor_*` tables are additive and feature-off. They are not legacy
  data. A user-scoped target row before cutover is a safety inconsistency that
  must block cutover rather than be silently deleted or preserved.
- Desktop persistence currently has only `localStorage["aearn.bootstrap"]`;
  its `userId` identifies the local user and its `planId` is legacy state.

## Requirements

### 1. Server-authoritative gate

- Add one versioned `harness_cutovers` record per local user and cutover
  version. It stores only a safe summary fingerprint, preview nonce,
  confirmation/idempotency receipt, state, timestamps, and safe failure code.
- The server, not the Desktop, computes the legacy summary and canonical hash.
  The client may never submit counts, table names, a user-independent token, or
  a deletion scope.
- When the Harness rollout composition is active, every user-scoped legacy
  runtime path and every Tutor path must consult the same gate before its
  runtime/domain work. A user with legacy data, unresolved checkpoint scope,
  target-state contamination, or failed verification is blocked from both
  runtimes. Only the cutover status/confirmation paths remain available.
- A verified user may enter only the guided Tutor entry. `TUTOR_HARNESS_ENABLED`
  must still be true, but cannot by itself authorize a user.

### 2. Exact deletion and preservation matrix

The cutover must delete only records proven to belong to the confirmed user.
It must not reuse the generic reset's JSON/text `LIKE` ownership heuristic.

| Disposition | Scope |
| --- | --- |
| Delete | Legacy plans, modules, knowledge points, generated exercises, blanks, test cases, teaching chunks, sessions, attempts, reviews, notes, onboarding/learning/review conversations and messages, `learner_profiles`, and user-scoped legacy idempotency records. |
| Clear as legacy learner preferences | `users.learning_style`, `teaching_preference`, `encouragement_preference`, `profession`, and `background_context`. These are learning/profile inputs used by the legacy runtime, not Harness memory. |
| Delete after exact thread derivation | `checkpoints`, `checkpoint_blobs`, and `checkpoint_writes` rows for known user-owned Graph thread ids only. Preserve the global `checkpoint_migrations` table. |
| Preserve | `users.id`, `display_name`, lifecycle identity fields, and notification/UI settings (`preferred_time_slots`, `reminder_preference`). Provider/model configuration stays in application configuration and is never read, changed, or exported by cutover. |
| Preserve but invalidate client use | `localStorage["aearn.bootstrap"].userId`; clear only its legacy `planId` and all user-scoped legacy in-memory stores. Do not delete unrelated local UI settings. |
| Block, never auto-delete | User-scoped pre-cutover `tutor_*` records and `tutor_api_idempotency_records`. They are target state, not legacy. `tutor_catalog_snapshots` is shared global metadata and is never user deletion scope. |

### 3. Explicit confirmation and atomic verification

- A destructive confirmation requires the exact server-issued preview nonce,
  canonical summary hash, current cutover version, `confirm=true`, and a stable
  client idempotency key. A stale preview, cross-user request, replay with a
  changed body, or missing confirmation performs no deletion.
- Confirmation serializes with all user-scoped legacy mutations through the
  same database user-row lock. It recomputes the summary while locked, deletes
  in foreign-key-safe order inside one transaction, verifies every required
  legacy/checkpoint count and cleared preference field, then records `verified`
  in the same commit.
- If deletion or verification fails, the destructive transaction rolls back;
  a separate safe receipt records `verification_failed` and
  `CUTOVER_VERIFICATION_FAILED`. Both runtimes remain blocked. No code path may
  report success after a partial delete.
- Startup, deploy, worker boot, route bootstrap, retry, and feature flag
  changes never create an implicit confirmation or deletion.

### 4. Desktop cutover experience

- The desktop asks the server for a cutover decision before it restores legacy
  `planId`, dashboard, learning, review, notes, or Tutor state.
- The blocking screen lists deleted and retained categories, warns that
  confirmed deletion cannot be recovered by rolling back code, requires a
  deliberate confirm action, shows recoverable blocked/error states, and never
  auto-confirms.
- On verified success it retains the local user identity, clears stale
  user-scoped stores and legacy bootstrap `planId`, reloads the retained user,
  and enters a blank guided `TutorWorkspacePage` conversation. It does not
  resurrect a legacy plan/session or a pre-cutover Tutor conversation.

### 5. Legacy retirement is a separate proof gate

- The first cutover implementation must leave Graph/router/tool source in
  place behind the server gate. It may not remove packages, routes, docs, or
  tests merely because deletion code exists.
- Physical retirement may begin only after target integration/replacement
  tests are green, default Desktop routing is verified, worker/legacy callers
  are gated, and a scoped caller search is empty. Code rollback before
  confirmation is allowed; it is never data recovery after confirmation.

## Acceptance Criteria

- [ ] A user with legacy records is blocked from both runtimes until seeing an
  exact server summary and explicitly confirming it; no request auto-confirms.
- [ ] The confirmation protocol rejects stale, cross-user, missing-confirm,
  and changed-body replays without deleting data.
- [ ] A successful cutover proves all listed legacy rows and owned checkpoint
  rows are absent, learner-preference fields are cleared, identity and
  notification/UI settings remain, and no stale legacy bootstrap survives.
- [ ] Target data present before cutover or an unprovable checkpoint scope
  fails closed without deleting either target or legacy data.
- [ ] Injected deletion/verification failure rolls back deletion, persists a
  safe `CUTOVER_VERIFICATION_FAILED` state, and leaves both runtimes blocked.
- [ ] A verified user reaches a fresh guided Tutor entry only; a nonverified
  user cannot bypass the gate by enabling a client route or reusing a plan id.
- [ ] Graph/routing/dependency removal happens only after recorded replacement
  proof, green integration coverage, and an empty scoped caller search.

## Out of Scope

- Migrating legacy learner history into Tutor tables.
- Deleting shared course, runtime, grounding, catalog, or checkpointer-migration
  metadata.
- Silently deleting pre-cutover target `tutor_*` state.
- Implicit startup/deployment deletion, live provider calls, worker start, or
  data recovery claims after a confirmed cutover.
