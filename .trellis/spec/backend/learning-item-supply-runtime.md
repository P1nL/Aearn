# Learning Item Supply Runtime (P3)

## 1. Scope / Trigger

Apply to item_supply jobs/repository/budget/scheduler, parameter profiles/calibration and additive schema 450. This is an internal, default-off runtime contract. P1 remains pure; P2 storage 440 and legacy v1 governance remain protected. Dedicated PostgreSQL/synthetic observations do not establish live generation, trusted source authorization, sandbox readiness, publication, Practice/Gate or RAG E completion.

## 2. Signatures

- `ItemSupplyRuntimeRepository(conn)`: register_profile, ensure_shared_root, ensure_private_root, enqueue, claim, refresh_lease, heartbeat, checkpoint, next_stage, mark_preparing, fail, complete, cancel, cancel_shared_subscription; caller owns the transaction.
- `ItemSupplyBudgetRepository(conn)`: register_global_limit, register_user_limit, reserve, settle. Limits are trusted server configuration, not client authority.
- `CoverageObligationV1`: frozen blueprint/scope/objective/purpose/runtime/visibility/policy and private owner; canonical_key excludes request/job/candidate keys and parameter versions.
- `JobLeaseV1`: job identity, visibility/owner/epoch, worker identity, generation, state_version, expiry, parent deadline, frozen profile. `CheckpointV1` carries stage, attempt, status and exact receipt digest.
- `ExecutionParameterProfileV1`: strict versioned provider/model/role/kind/risk/difficulty/input/runtime bucket, initial/current/last_stable/floor/ceiling, window, trusted initial evidence and change reason.
- `calibrate(profile, observations, policy, *, now, rollback_count=None, window=None)` is pure/offline. `apply_decision` and `begin_canary` are trusted pure composition helpers, not public model authority; neither can bypass cooldown. `freeze_profile(profile, *, bound_at, ancestor_deadline=None)` freezes `parent_deadline_at`. `claim_bounded` requires explicit owner partition, bounded limit and registered handlers.
- Schema: `450_learning_item_supply_runtime.sql` is explicit in the ordered fragment manifest; all business tables require exhaustive cutover/export/reset classification.

## 3. Contracts

- Canonical roots are rebuilt from persisted server authority. Equivalent requests, job restart/cancel or new profile versions cannot clear usage or reservation history. New roots remain subject to cumulative system/provider/window/pool and private user caps.
- Frozen job-control snapshots use the `item_supply_job_snapshot_v1` envelope: profile values are under `profile_snapshot_json.profile.values`, not directly under `profile_snapshot_json.values`. SQL consumers must follow the same shape as `_snapshot`. A completed generating checkpoint advances `next_stage` to `validating` while the control remains `state=leased`; never broaden the live-state fence to repair a stage/profile decoding mismatch.
- Base/enhancement pools are separate. Requests, input/output tokens, execution seconds, fetches, candidates and revision/investigation rounds keep their units; do not equate an arbitrary sum with coverage of every resource dimension.
- Reserve selects active server-clock windows and locks all limit dimensions in a deterministic order, then the private user dimensions. Check cumulative effective usage and insert in the same transaction. Concurrent requests cannot both spend the last capacity. Authoritative clock_timestamp is refreshed after contended control and budget/root/window locks; recheck lease and every active window after waiting. Caller now and a clock read before blocking cannot authorize expired work.
- Settlements are append-only and idempotent by exact facts. Unknown usage conservatively retains reservation; unavailable monetary cost is NULL, not zero. Later known reconciliation records true consumption, including overage, without enlarging caps or erasing history.
- Schema 450 contains 18 classified tables (11 shared, 7 private). Anonymous `tutor_item_supply_runtime_global_usage_facts` retains only opaque reservation/settlement UUIDs, sequence, resource, known/unknown state and actual amount. Write settlement, actual resource children, then anonymous facts atomically. No owner/epoch/scope/content/hash/client key/provider body; no private FK preventing reset. Global effective usage survives private purge. Latest unknown conservatively retains max(reservation, already known overage) until explicit known reconciliation.
- Lease generation, owner/epoch, current scope and CAS protect stage effects. Expired/stale workers cannot checkpoint, admit or publish. A stale generation may only reconcile the reservation that actually belongs to its identity. This cost permission requires the original namespace to remain valid. After revision invalidation or owner reset, new live late-actual writes are rejected; retained anonymous facts and conservative reservations survive. Do not claim a trusted provider reconciliation endpoint exists.
- Checkpoint recovery selects the first missing stage, retains completed evidence and respects the frozen parent deadline. Heartbeat cannot extend that deadline; transient retries are bounded, deterministic/safety/scoring failure is not retried blindly.
- Cancelling a private subscription must not cancel another consumer's shared job. Private jobs cannot switch owner. No explicit owner means no global item-supply scan.
- Profiles are strict and immutable snapshots for in-flight work. No/biased/right-censored samples, quality/coverage/scorer/safety blockers or changed provider/model/runtime/load cannot justify shrinkage. Change one dimension per canary; shadow is not quality evidence. Use last_stable rollback, cooldown and freeze against oscillation. Revalidate all supplied copied/constructed inputs before early hold. Exact matching canary failures take priority over mixed-population rejection; unrelated failures cannot roll back another profile. Commit and begin_canary respect cooldown; rollback/freeze may still respond immediately to blockers.
- `LEARNING_ITEM_SUPPLY_SCHEDULER_ENABLED` defaults false, in addition to default-off SUPPLY/GENERATION/NETWORK/V2_ADMISSION flags. The scheduler is not wired into production workers or public routes. Missing budget/profile/future handlers are preparing/blocked, never fake success.
- Private runtime rows retain P2 physical owner/epoch/scope partition and maintenance purge authority. Shared profiles/accounting must not carry private material, owner/content hashes or user mappings. Existing local-user export remains bounded summaries only. Upgrade copies only still-existing authoritative settlement/actual children into anonymous facts, idempotently, without filling missing dimensions as zero or updating old ledgers. A lower known resource/cost value requires explicit strict-bool reconciliation even when an unknown row intervenes. The protected 440 request/token envelope safely rejects execution-only reservations with LEGACY_ENVELOPE_REQUIRES_REQUEST_AND_TOKEN; no synthetic request/token placeholders.

## 4. Validation & Error Matrix

| Case | Required result |
| --- | --- |
| Caller changes authoritative scope/objective/runtime/policy/owner | reject authority mismatch |
| Same root/job/reservation/settlement identity with conflicting facts | conflict, no overwrite |
| Equivalent demand/profile/restart | same root, historical usage retained |
| Missing active limit or insufficient dimension | denied; no unreserved stage success |
| Concurrent last-capacity reservation | one accepted; other denied, no overspend |
| Unknown or lost-lease usage | retained reservation, explicit reconciliation required |
| Stale generation/expired parent | no new stage effect; original-generation cost only while namespace remains valid |
| Old epoch / invalidated revision | reject new writes, retain anonymous usage and conservative reservations |
| Execution-only without request/token | safe blocked; no fake usage; future execution integration remains separate |
| Missing owner/handler, flags disabled | owner_required/preparing/disabled, no scan or provider |
| Biased/unsafe/incomplete calibration window | hold/warmup/rollback/freeze, not shrink |
| Private reset | only owner payload removed, epoch fence retained, shared/other owner unchanged |

## 5. Good / Base / Bad Cases

Good: on the dedicated fixture, trusted authority issues a canonical root; two workers compete for a claim and only one current generation reserves a fully bounded stage. Crash recovery reuses the root and skips completed checkpoints.

Base: all flags false; pure calibration and explicit repository tests are usable internally, but no provider/worker/public consumer runs.

Bad: generate a new client key to reset the budget; record unknown cost as free; complete a future stage using a placeholder handler; use shadow/success-only samples as production calibration; copy private accounting identities into a public catalog.

## 6. Tests Required

- Use `aearn_b1b_fixture_20260930` only, assert current_database, disable dotenv/LLM/pytest plugin autoload, run through API-directory `uv --offline` with `--noconftest`. Pure tests use an unreachable DSN.
- PostgreSQL/bootstrap tests are sequential across agents; explicit independent connections prove claim/reservation races, expiry/recovery and reset/revision fences. Preserve the accepted P2 49 and P1 217 baseline tests.
- Cover root authority and restart, every resource dimension, cross-root cumulative caps, exact settlement replay/conflict and overage/unknown facts, generation-bound late callbacks, shared cancellation, missing authority/handlers and starvation/deadline limits.
- Synthetic calibration covers no samples, right censoring, success-only bias, version/load drift, single-dimension canary, shadow denial, regression rollback/cooldown/freeze and unchanged in-flight snapshot.
- Bootstrap complete manifest twice; classify all 450 tables; test ordinary immutability versus authorized owner purge, bounded export and another owner/shared preservation. Run focused Ruff, whole-app Mypy, pure import guards, protected byte checks and dependency lock check.
- Record actual commands/pass counts and tested revision hashes in task-local acceptance. Unexecuted full API/provider/broker/sandbox/source/Gate tests remain explicitly unexecuted.

## 7. Wrong vs Correct

Wrong: P3 tests passed, therefore the real item bank and E are ready; a new profile gets a fresh cost root.

Correct: P3 acceptance proves the internal repository/controller boundaries only. New profiles affect future work but retain canonical accounting; real generation/review/execution/publication and E need their own evidence and authorization.
