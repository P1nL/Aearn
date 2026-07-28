# Harness Cutover and Legacy Retirement Design

## Status, Authority, and Decisions

This is the Child 07 planning design. It operationalizes the parent Harness
contract without changing runtime behavior. Implementation may begin only after
this artifact, `implement.md`, and the start review are accepted.

The design intentionally separates three concerns that must not be collapsed:

1. **Per-user cutover gate and destructive legacy cleanup**;
2. **Server-authorized default route selection after a verified cutover**; and
3. **Physical retirement of legacy Graph/runtime code after replacement proof**.

The parent contract requires a clean-slate transition, not a legacy-to-target
history migration. Child 06's `/api/tutor/*` adapter and `TutorWorkspacePage`
are pre-cutover surfaces. `TUTOR_HARNESS_ENABLED` is necessary rollout
composition, but a verified user-scoped cutover remains independently required.

### Closed scope decisions from existing evidence

| Decision | Resolution | Evidence and rationale |
| --- | --- | --- |
| Existing `users` learning fields | Clear `learning_style`, `teaching_preference`, `encouragement_preference`, `profession`, and `background_context`; retain `id`, `display_name`, `preferred_time_slots`, and `reminder_preference`. | The parent requires extending the current reset because it retains legacy learning preferences. Notification/time fields are local UI/user settings; the other fields are legacy learner profile inputs. |
| Target `tutor_*` rows before cutover | Do not delete or migrate them. Detect user-scoped rows and block with a safe target-state error. | Target tables are additive, feature-off, and are not legacy. Silent destruction would violate the exact-scope contract; silently preserving them would violate clean first entry. |
| PostgreSQL LangGraph checkpoints | Support only the installed package's documented `checkpoints`, `checkpoint_blobs`, and `checkpoint_writes` schema, scoped to derived user-owned learning thread ids. Preserve `checkpoint_migrations`. | Current code has no `PostgresSaver` nor `compile(checkpointer=...)`; when it constructs a thread state it uses `aearn:learning:<session_id>`. Unknown table/schema/thread ownership blocks instead of guessing. |
| Existing generic reset | Keep it as a legacy Settings/Privacy operation preserving user preferences. Implement a separate cutover service and use only safe, reusable low-level helpers. | Existing product docs and tests promise that ordinary reset preserves preferences and returns to onboarding; cutover has intentionally different semantics. |
| Global rollout flag | Leave defaults unchanged. When an operator later turns `TUTOR_HARNESS_ENABLED=true`, server routing additionally consults the per-user gate. | No current deployment configuration is changed by this child; the global flag never replaces user confirmation. |

## Authority and Data Matrix

The summary is a server-generated canonical manifest. It contains categories,
counts, version, and safe flags only; it never contains messages, code,
provider payloads, hidden tests, raw checkpoint values, or a client-selected
SQL target.

| Category | Records / fields | Cutover action | Verification |
| --- | --- | --- | --- |
| Legacy plan hierarchy | `learning_plans`, `plan_modules`, `knowledge_points`, `exercises`, `code_blanks`, `test_cases`, `teaching_chunks` | Delete confirmed user's hierarchy in dependency-safe order. | All per-user hierarchy counts are zero. Shared `language_courses` and `runtime_profiles` remain. |
| Legacy learning/review facts | `learning_sessions`, `attempts`, `review_states`, `review_logs`, `review_seed_banks`, `exercise_variant_cache` | Delete. Clear `knowledge_points.last_session_id` before session deletion. | All user-scoped fact counts are zero. |
| Legacy visible content | `notes`, onboarding conversations/messages, learning messages, review messages | Delete. | All linked messages/conversations are zero. |
| Legacy Agent profile | `learner_profiles` and the five legacy learner fields on `users` | Delete the profile and normalize the five fields to `NULL`. | Profile count is zero and each cleared field is `NULL`. |
| Legacy idempotency | `idempotency_records` with `user_id = :user_id` | Delete only exact user-owned rows. Never use key/JSON text matching. | Exact active/user-owned count is zero. Unscoped historic rows are not claimed as owned and cannot reopen a gated legacy route. |
| LangGraph checkpoint store | package tables `checkpoint_writes`, `checkpoint_blobs`, `checkpoints`, scoped by derived `aearn:learning:<session_id>` values | Delete only matching derived thread ids, in all three tables. Preserve package migration metadata. | Each known table reports zero matching rows after delete. Missing tables are recorded as `not_configured`, not created. |
| Identity and local configuration | `users.id`, `display_name`, create/update lifecycle, `preferred_time_slots`, `reminder_preference`; process configuration such as provider/model settings | Preserve. | Retained values equal the locked pre-delete snapshot (except normal `updated_at`). |
| Desktop bootstrap/UI state | `aearn.bootstrap.userId`, `aearn.bootstrap.planId`, in-memory app/settings stores | Retain only user id; clear plan id and all legacy user-scoped state. Do not delete unrelated UI storage. | Client begins fresh Tutor route and no legacy plan/session request is made. |
| Target Harness state | User-scoped `tutor_*` / `tutor_api_idempotency_records` | Do not delete, migrate, or permit. Block cutover if any exist. Global `tutor_catalog_snapshots` remains untouched. | Target-state detector returns zero before a first verified cutover. |

## Persistent Gate Model

### `harness_cutovers`

Child 07 adds an additive, repeatable SQL table with one row per
`(user_id, cutover_version)`. The exact physical names may follow local schema
conventions, but its constraints are mandatory:

| Field | Invariant |
| --- | --- |
| `user_id`, `cutover_version` | Composite unique identity; `user_id` has a restrictive FK to the retained `users` row. |
| `state` | One of `required`, `summary_ready`, `verified`, `verification_failed`, `blocked_target_state`, or `blocked_checkpoint_scope`. The transient deletion lock is transaction-local, not a committed success-looking state. |
| `summary_hash`, `preview_nonce`, `summary_version` | Set only from a canonical server summary. A confirmation must match all three after locking and recomputation. |
| `confirmation_idempotency_key`, `confirmation_request_hash` | Bind a replay to exactly one user, summary, and request body. Same request replays the verified/blocked receipt; changed body conflicts. |
| `confirmed_at`, `verified_at`, `failure_code`, `failure_at` | Safe audit only. Never store deleted learning content or raw checkpoint values. |
| `created_at`, `updated_at` | Standard audit timestamps. |

`verified` is durable and is the only per-user authorization to open the Tutor
runtime once the global rollout flag is enabled. The table is an audit and gate,
not a migration ledger that can recreate deleted history.

### Canonical summary and confirmation protocol

```
Desktop bootstrap
  -> GET /api/harness/cutover?user_id=U
  -> server locks/reads U, computes canonical summary and safe gate decision
  -> Desktop shows legacy, blocking cutover, target-state, or verified route

Explicit destructive action
  -> POST /api/harness/cutover/confirm
       { user_id, summary_version, preview_nonce, summary_hash,
         client_action_id, confirm: true }
  -> server owns locking, recomputation, deletion, verification, and result
```

The client never sends counts, retained fields, table names, target ids,
checkpoint thread ids, or a confirmation result. The response supplies only a
learner-safe state and next action. Stable errors include:

- `CUTOVER_REQUIRED` for gated runtime requests;
- `CUTOVER_CONFIRMATION_REQUIRED` for missing/false confirmation;
- `CUTOVER_SUMMARY_STALE` for a stale nonce/hash or changed legacy data;
- `CUTOVER_CONFIRMATION_CONFLICT` for same idempotency key with a different
  request;
- `CUTOVER_TARGET_STATE_PRESENT` and `CUTOVER_CHECKPOINT_SCOPE_UNRESOLVED` for
  non-destructive safety blocks; and
- `CUTOVER_VERIFICATION_FAILED` for a rolled-back destructive attempt whose
  result cannot be proven.

A user with no legacy data and no target contamination can receive a
server-recorded `verified` empty-state result without a destructive prompt.
The "never auto-confirm" rule applies to any operation that can delete data.

## Runtime Gate and Concurrency

### Gate outcome

When `TUTOR_HARNESS_ENABLED=false`, current legacy behavior remains unchanged
and Tutor routes keep returning their existing feature-off envelope. No
cutover is automatically performed.

When the rollout flag is enabled:

| User state | Legacy runtime | Tutor runtime | Desktop behavior |
| --- | --- | --- | --- |
| legacy data + valid preview / no confirmation | Deny | Deny | Blocking cutover summary. |
| `verification_failed`, target-state, or checkpoint-scope block | Deny | Deny | Blocking error/retry/help state; never expose a legacy escape hatch. |
| `verified` | Deny | Allow | Fresh guided Tutor entry. |
| no legacy + no target state | Record/return verified empty state | Allow | Fresh guided Tutor entry. |

The cutover status and confirmation endpoints remain narrowly available to
resolve a nonverified state. The ordinary legacy reset/delete controls must not
clear or bypass a `verified` gate.

### Serializing user activity and deletion

A common `CutoverRuntimeGate` owns the transaction-scoped user lock and gate
lookup. Each user-scoped legacy mutation/read that can restore or expose
legacy workflow state takes `SELECT ... FOR KEY SHARE` on the active user row
within its database transaction before business work. Confirmation takes the
same row `FOR UPDATE`, so it cannot race an accepted legacy mutation. The
implementation audit includes API routes, Graph/streaming entry points, and
legacy review worker writes; it deliberately does not apply a blanket gate to
health, static catalog, or cross-user-independent diagnostics.

The confirmation transaction is serializable and performs this sequence:

1. Lock the active user and `harness_cutovers` row; verify rollout enabled,
   confirmation body, idempotency binding, and current state.
2. Recompute canonical legacy counts, target-state counts, known checkpoint
   inventory, and summary hash while locked. Reject stale or unprovable scope
   before deletion.
3. Delete exact user-scoped legacy rows in FK-safe order. The SQL helper never
   relies on a JSON/text match for ownership. Normalize the five legacy user
   preference fields only after their prior retained snapshot is held.
4. Delete only derived matching LangGraph checkpoint rows when known tables are
   present. The exact baseline `thread_id` list comes from the user's
   `learning_sessions` before those sessions are deleted.
5. Recompute the same verification matrix in the transaction: every deleted
   category/checkpoint scope is zero; retained identity/notification values are
   unchanged; target-state remains zero.
6. Set `harness_cutovers.state='verified'` and its receipt fields, then commit.

If any statement, row count, lock, or verification check fails, rollback the
whole deletion transaction. A new short transaction records a safe
`verification_failed` receipt and `CUTOVER_VERIFICATION_FAILED`; it does not
claim that any deletion succeeded. A retry must fetch a fresh summary.

### Known checkpoint adapter

The installed package defines `checkpoints`, `checkpoint_blobs`, and
`checkpoint_writes`, all keyed by `thread_id`. Current Graph code does not
actually persist with that saver, but its only current checkpoint thread
construction is:

```text
aearn:learning:<learning_session_id>
```

The adapter must use `to_regclass`/catalog inspection before issuing any delete.
It never creates these tables. If a known table is absent, its count is zero
with a safe `not_configured` disposition. If a table exists but an unexpected
legacy thread namespace or a historic deployment schema cannot be attributed
from user-owned sessions, the operation is blocked and no broad table delete is
attempted. `checkpoint_migrations` is global package metadata and is never a
user deletion target.

## Desktop Boundary

The Desktop gets a dedicated `HarnessCutoverPage`/controller rather than
reusing the ordinary Reset Privacy flow.

1. After local identity is loaded but before `planId` restoration, fetch the
   server cutover decision for the selected user.
2. If rollout is inactive, preserve the present legacy bootstrap behavior.
3. If the result requires cutover or is safely blocked, call the existing
   user-scoped clearing primitives without issuing dashboard/resume/learning/
   review/note requests; mount only the blocking page.
4. Show the server summary as categories and counts, exact retained categories,
   irreversibility text, disabled/double-submit handling, and retryable safe
   errors. No checkbox, reload, or route change constitutes confirmation.
5. On verified response, write `{userId, planId: null}`, clear all legacy
   Zustand state and stale Settings form state, reload the retained user, and
   route to `TutorWorkspacePage` with the server-authorized state.
6. `TutorWorkspacePage` is allowed to call its target controls/endpoints only
   after the verified decision; it begins with no legacy plan/session/conversation
   id and creates a new guided Tutor conversation only on user intent.

Current code persists only `aearn.bootstrap`; it has no recognized visual
settings key to delete. The implementation must preserve unknown local UI
settings instead of clearing all browser storage.

## Legacy Retirement Is a Separate Gate

No Graph source, legacy endpoint, test, dependency, or source-of-truth document
is removed by the destructive transaction. The post-cutover retirement sequence
requires all of the following evidence first:

1. Feature-enabled per-user cutover tests and fresh Tutor entry integration are
   green without a real provider, worker, or executor.
2. Desktop default routing no longer reaches legacy bootstrap, plan, session,
   review, note, or Graph SSE flows for verified users.
3. Legacy review worker behavior is gated or has no remaining user-owned legacy
   work after cutover; no background process can recreate rows during cutover.
4. A scoped source/test caller search for Graph/router/tool imports is empty,
   except intentionally recorded historical/transition references owned by
   Child 08.
5. Child 08 updates the source-of-truth docs and the package/dependency search
   proves `langgraph` / `langgraph-checkpoint-postgres` are unused before they
   are removed.

Before confirmation, code/config rollback can return the legacy route only
while its data remains. After confirmation, rolling back code never claims to
restore intentionally deleted data.

## Security, Operations, and Non-goals

- Do not export, log, or return raw user content, code, hidden tests,
  provider/model credentials, checkpoint payloads, or SQL diagnostics in the
  summary/receipt.
- Do not invoke a provider, launch an executor, start a worker, enable a flag,
  or operate on a real local user during implementation tests.
- Do not treat an empty Graph caller search as a substitute for cutover
  verification, and do not treat `task.py validate` as a data safety test.
- This design does not migrate history, recover confirmed deletions, or delete
  target state encountered before a first cutover.
