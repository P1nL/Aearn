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

## PRIVATE development accounting-only scope (SQL551 isolated acceptance installation, 2026-10-15)

- This isolated default-off original owner is model-resource accounting, not source, dispatch, quality or delivery authority. PrivateDevelopmentModelAccountingOwner prepares fresh atomic locator-only batches on the existing same-user/epoch/scope canonical enhancement root, binds an actual unspent first-claim job before any model reservation, and rereads original controls and clocks after locks. PUBLIC517 remains separate.
- Tagged batch selects exactly its own one PRIVATE window,32 global and8 user nominal-positive cap1 rows; only freshly validated accounting_only mode skips cumulative root/global/user comparisons. Execution/fetch denial, original per-operation profiles/lease/breaker/once and all allocation/UNKNOWN settlement remain. Ordinary PRIVATE/PUBLIC limits and funding exclude development nominal rows but retain normal cumulative gates. Finite64 is never called unlimited.
- Anonymous SHARED global-limit classification contains no user/epoch/scope/root/job/batch/content mapping and survives PRIVATE purge; otherwise cap1 would become ordinary after deletion of private mappings. New PRIVATE batches/maps have original composite ownership FKs and safe export-compatible id/scope_id/created_at; ordinary mutation denies. Only original permitted epoch+1 maintenance deletes new job maps then batches before original450 targets; no second purger or oldSQL edit.
- Original private task anchors use the exact immutable task.demand_id ANDscope_id. Equal practice/assessment scope alone is insufficient: unique stored/pack entries plus full demand.scope/blueprint/objective/policy must equal genuine assessment contract; remediation/different/ambiguous anchor denies. Preserve actual task identity and original ensure_private_root verification.
- New phase/profile parent and stage bounds fit both genuine current SOURCE expiry and accounting deadline; formal request and bounded preparation/claim allowance stay unchanged. Insufficient remaining lifetime denies before enqueue/IO; actual claimed lease/profile deadlines are checked again. Never extend source, historical profile/window, UNKNOWN or consumed once.
- Main actual selected551 compile/replay and populated original root/firstclaim/reserve2>nominal1/export/permitted purge were proven only in full rollback with0HTTP; these are not installation or fullP7 acceptance. Original privacy/source/quality/enhancement/Artifact acceptance remains separate.

- Subsequent Main selected551-554 compile/replay/full rollback and complete original author preparation/late current fence PASS were followed by isolated installation at2026-10-15 11:48 Beijing. This does not rewrite prior rollback evidence, change ordinary/private cumulative caps, enable public flags or prove actual model/quality/Artifact acceptance. Ordinary funding supplies legacy resource_cap=caps.candidates=5 and preserves disabled execution/fetch caps0; SQL553 allows0 only for those two non-model kinds, keeping all model/candidate/round caps positive.


## C18 fixed durable-output persistence phase (2026-10-16; implementation, live acceptance separate)

### 1. Scope / trigger
An expired author lease does not invalidate a real committed SQL560 output, and does not authorize reauthoring it. C18 is explicitly approved for exactly one new original-owner persistence/quality phase for output f4519c66-4130-4e34-b053-64dba6214dcb. Installed <=561 remains immutable; SQL562 is a selected forward slice. This section does not assert installation or P7 completion; Main's task evidence controls actual status.

### 2. Signatures
PrivateEnhancementService.generation_persistence_phase_owner() returns the separate PrivateGenerationPersistencePhaseOwner. Its issue(task_ref, output_id) prepares A; persist(cap) writes B; executor.adopt_persisted_phase(cap) and prepare_persistence_phase_review(handoff) prepare C. Original run_initial_recovery_review runs only after C commit and IDLE.
SQL public-to-Python surface is item_supply_internal.private_generation_persistence_phase_{ready(),first_claim(uuid,uuid,uuid,uuid),bound(uuid,uuid),complete(uuid,uuid,uuid),committed(uuid,uuid)}. Internal completed_data(uuid) proves historical facts, not live work authority. The two new trigger functions enforce closed insert facts and A/B deferred atomicity. Exact signatures, keys and payloads remain in the C18 task wire contract and SQL562.

### 3. Contracts
Original request/result/profile/source/receipt/known settlement and original558 consume remain unchanged. The new writer profile, lease, accounting batch and slot phase are a distinct authority domain. A has deterministic output binding and caller-owned TOP; B preserves original request.profile while storing the new writer job, then original generating checkpoint and completion. A/B server xid8 markers must differ; released savepoints are not commits. C requires actual committed B and a separate concrete quality cap. No author, author reservation, resettlement, old capability restoration, or automatic second phase/restart API.

### 4. Validation and error matrix
- Wrong output/ref, copied or nested-mutated cap, changed generation DATA: deny; no new phase rights.
- Same TOP A/B or B/C: deny with prior-TOP binding/completion requirement.
- A missing accounting/slot phase or B missing artifact/checkpoint/completion: deferred rejection, whole caller transaction rolls back.
- Expired/reclaimed/renewed writer or stale source: deny; no extending historical/current deadlines to pass.
- Historical completed publication/review_failed: exact immutable provenance and full quality predicates remain readable without claiming the writer is current.
- Original accounting_batch_for_lease returns a projection with batch_id, not a raw table row with id.

### 5. Good / base / bad cases
Good: committed560 output -> new exact first claim/accounting/phase A commit -> B commit -> C prepare commit -> original quality once. Base: ordinary/C17 profile equality and original expiry denials remain. Bad: substituting a new profile into the historical request, using a local JSON file as an issuer, or relabeling artifact persistence as quality/publication.

### 6. Required focused evidence
Use C18 Python and schema tests, directly affected C17/C16/C14 regressions, selected migration compile/replay/catalog/history rollback, original A rollback and actual separate B/C gates. These scopes are distinct. A fixture must mirror the real accounting projection; A batch/enqueue test asserts caller transaction depth1 and complete rollback. Clock regressions assert actual frozen-profile clock order and server-owned binding time. Native quality readback joins the exact review preparation/artifact/reservation to the matching native blind payload, not generic pipeline receipt kinds.

### 7. Wrong vs correct: original transaction and clock domains
Wrong: adding a nested SAVEPOINT around SQL551 prepare_batch. Its installed fresh-global-row receiver checks the original TOP transaction identity. Correct: A preparation remains in the caller's atomic TOP; keep B's intentional savepoint and server complete-TOP proof separately.
Wrong: compare job.created_at (DEFAULT now()) or control.updated_at (450 trigger forces now()) to a later clock_timestamp() as equal/ordered generation evidence. Correct: compare original server-clock batch.started_at with frozen profile.bound_at; SQL562's binding BEFORE trigger validates the incoming current bounds and writes its own final clock_timestamp(). Never modify450/551, extend a deadline, or use raw xmin as new commit proof.
PostgreSQL's current date/time documentation was checked for the distinct now()/clock_timestamp() meanings: `https://www.postgresql.org/docs/current/functions-datetime.html#FUNCTIONS-DATETIME-CURRENT`.
