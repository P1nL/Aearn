# Learning Item Supply Storage (P2)

## 1. Scope / Trigger

Apply when editing the default-off item supply persistence skeleton, schema 440, storage repositories, v2 policy/evidence/observation, or local-user export/reset/cutover. P1 pure coverage remains separate. This is internal storage, not a running generator, autonomous publication, P6 sandbox, Practice/Gate integration or RAG E release.

## 2. Signatures

- Fragment: app/db/schema/440_learning_item_supply_sandbox.sql, explicitly ordered in SCHEMA_FRAGMENT_NAMES; same caller-owned bootstrap transaction, no fragment COMMIT.
- P2 exhaustive partitions: 14 tables in storage_tables.SHARED_TABLES, 22 in PRIVATE_TABLES, plus tutor_item_supply_user_epochs as a retained identity tombstone, never public catalog content. item_supply_internal.reset_permits is non-business protected capability state. Later P3 additions require their own manifest/classification update, not silently changing this P2 acceptance inventory.
- PostgresSharedSupplyStorage(conn): register_policy(policy), register_blueprint(blueprint).
- PostgresPrivateSupplyStorage(conn, user_id, expected_epoch): bind_scope(track_id, revision_id, scope), store_material/candidate/version/demand/evidence/observation/admission, get_version(scope_id, handle).
- purge_private_supply(conn, user_id, deleting=False) is called only by the existing confirmed reset/delete/cutover owner; export_private_supply returns bounded safe summaries.
- Strict types: SourceCoordinatesV2, ObservationV2, EvidenceV2, AutonomousEvidencePolicyV2, AdmissionDecisionV2.

## 3. Contracts

- Shared and user-owned storage are physically separate. Private composite identity/FKs contain user_id and epoch; scope binds current track/revision/node, lookup cannot enumerate another user's private payload. Public catalog storage cannot contain private owner mapping or content hash.
- lip:v2 private identities are opaque, separate from legacy shared handles. Snapshot contracts revalidate original typed instances before serialization; immutable payload hashes are recomputed, not caller-authorized facts.
- Source coordinates are all-null/all-present references only, NOT a current RAG authorization grant. No fake published flag or formal score authority.
- v2 policy/evidence/admission types cannot accept v1 receipts. Existing v1 policy/pilot/human approval/publication remains unchanged. P2 admission only blocked/evidence_pending, including when a flag is manually enabled.
- Observation origin is simulation, deterministic_probe or real_learner. Non-real observations have no learner authority identity. Real observations must match the exact session assignment document, Attempt, terminal result, plan revision, owner, track and knowledge node—not merely non-null collector/session/actor/terminal UUIDs; persisting this relation is still not proof of a working trusted collector.
- Immutable versions, evidence and observation events reject ordinary update/delete. Authorized private purge uses a protected permit, revoked PUBLIC execute and fixed search_path; ordinary session GUCs are not deletion authority. The schema/maintenance owner is explicitly trusted; production role provisioning is not implied.
- Reset first fences user epoch and cancels dependent jobs/bindings, then deletes child-to-root private payload in the same transaction. Retained epoch prevents old worker/request revival. Shared content and another user remain unchanged. Deleting the user removes payload and denies stale writes through identity absence.
- All new tables require explicit classification. Epoch tombstone retention is an explicit classification exception, not permission to export private data as shared. Private summaries omit material, rubric/test/answer, provider payload, content hash and lease details. External exported files/backups cannot be recalled by DB reset.
- LEARNING_ITEM_GENERATION_ENABLED, LEARNING_ITEM_NETWORK_ENABLED, LEARNING_ITEM_V2_ADMISSION_ENABLED, LEARNING_ITEM_SUPPLY_ENABLED default false. P2 never starts provider/worker/network or formal consumers. P3 claim/reserve/settle and calibration runtime remain later work.

## 4. Validation / Error Matrix

| Input or action | Required behavior |
| --- | --- |
| Cross-owner/epoch FK or lookup | Reject or non-disclosing missing result |
| Stale epoch / reset replay | gone/stale, never recreate old payload |
| Same immutable key, different payload/hash | conflict, never overwrite |
| Unknown nested fields / copied or constructed malformed model | reject before storing/hash |
| Partial source coordinates | reject, never authorize source |
| v1 evidence used as v2 / weakened policy roles | reject |
| Non-real observation with learner identity / real identity absent | reject |
| Ordinary UPDATE/DELETE or forged purge GUC | reject immutable history change |
| Confirmed owner reset then caller rollback | all payload/epoch changes roll back together |
| Flag enabled without trusted adapters | evidence_pending, not published |

## 5. Good / Base / Bad Cases

Good: on a dedicated fixture DB, store validated private content under the exact current user scope, return only opaque identity, then confirmed reset fences epoch and purges only that user's private data transactionally.

Base: all flags false; policy and evidence can be persisted internally, but admission remains blocked and no public supply route exists.

Bad: use caller hash as validation; read private payload from shared query; set a session GUC as purge permission; relabel simulated observation as real; upgrade a v1 human approval to v2; reuse old epoch after reset.

## 6. Tests Required

Use a purpose-created disposable database and explicit DATABASE_URL, never default development/learner DB. Disable dotenv/LLM/plugin autoload, run named tests with --noconftest and self-owned fixtures. Bootstrap twice, partition every new tutor table, test two-user/FK isolation and source all-or-none, immutable replay/conflict and forged models, v1/v2 separation, observations, default-off flags, full reset/export with shared/other-user unchanged, and caller rollback. Require real two-connection epoch reset-vs-bind/store/direct-SQL races and active-revision switch-vs-bind/store/direct-SQL races, each in both orderings; sequential stale-token tests alone are insufficient. Re-run P1 four pure tests separately on unreachable DSN to prove no pure-package IO regression. Ruff changed Python and Mypy all app; tests do not claim real source/scoring/collector/provider readiness.

## 7. Wrong vs Correct

Wrong: put private source payload in a shared table with an owner field and later filter it in Python. Correct: write a user/epoch-scoped physical private table with owner-composite foreign keys, filter at SQL lookup and retain only safe references outside it.

Wrong: delete private child rows before invalidating generation. Correct: fence the epoch under lock, disable/cancel bindings/jobs, then purge child-to-root in the confirmed owner's transaction. An old epoch is never accepted after reset.


## 2026-10-04 checkpoint: native exposure 495 (code checked, DDL NOT applied)

### 1. Scope / trigger
Native published-item exposure must use actual owner origins, not a caller-supplied empty snapshot.495 is staged code only at user-requested stop. Hooks apply to whichever DB installs the schema; they are not intrinsically B1d-only and Python enabled=False does not disable installed capture hooks.

### 2. Signatures
`NativeExposureOwner(conn, user_id=..., expected_epoch=..., published_query=..., source_authority=..., enabled=False)` exposes `collect`, `snapshot`, `reserve_assessment(scope_id, version_ids=(a,b), operation_key)` and `prepare_practice_delivery(scope_id, version_id, reservation_key, delivery_key)`. Concrete query/authority must share conn. SQL495 adds6private tables; `P7_NATIVE_EXPOSURE_TABLES` equals `NATIVE_EXPOSURE_PRIVATE_PURGE_ORDER`.

### 3. Contracts
Birth is captured by actual users INSERT at epoch1; immutable origin inbox comes from existing Artifact/assistance/Attempt/Gate-binding owner tables. Snapshot binds collector version/epoch/watermark. Family is exact immutable public-spec identity, not independence. Reservations precede practice; reserved assessment family cannot be exposed through practice. New AFTER epoch-update hook requires original reset permit and old+1, purges6tables child-to-parent before470 parent deletions, never creates epoch2 birth. Historical private-table slice indices stay unchanged. Safe export contains id/scope/created_at only, with NULL scope for births/inbox/events/watermarks; no origin/binding/proof JSON.

### 4. Validation / errors
No birth, unknown/unmapped origin, reset epoch, missing hooks or >4096records => pending. Stale source/runtime/publication => no reservation/delivery. NonArtifact Practice and assessment actual-display owners remain unwired; do not use practice token as assessment permission.

### 5. Good / base / bad
Expected good: genuine new participant + installed hooks + fully mapped history produces a bounded exposure snapshot, still not pack ready. Base: historical records retained and private. Bad: infer unseen from no Attempt, relabel shown as attempted, or wash exposure through new scope/version.

### 6. Tests and evidence
Worker one focused test passed; checker fixed reset hook and reran only that affected case (1passed), scoped Ruff/Mypy passed. Main one manifest case passed and narrow integration lint/type passed. Real495 DDL/birth/reset forced-rollback smoke remains unexecuted; do not infer PG behavior from fake-connection tests. Report: .trellis/tasks/09-22-multi-agent-item-bank-sandbox/research/p7b-native-exposure-check-20261004.md.

### 7. Wrong vs correct
Wrong: empty table or caller complete=True grants unseen/ready. Correct: actual birth/origin hooks and durable watermark prove only tracked history; full pack still needs real course/family/current-publication authority.


## 2026-10-11 native consumer / normal readmission classification

### 1. Scope / Trigger
Explicitly classify staged521 private consumer sidecars and staged522 shared normal-revision audit. Neither classification nor SQL comments grant admission/delivery. Selected installation/live acceptance remain Main gates.

### 2. Signatures
`P7_NATIVE_CONSUMER_TABLES=(tutor_item_supply_native_artifact_bindings,tutor_item_supply_native_consumer_receipts)` enters `PRIVATE_TABLES`; `tutor_item_supply_shared_normal_revision_readmissions` enters `P7_SHARED_PIPELINE_TABLES`/`SHARED_TABLES`. `export_private_supply(conn,user_id)` uses `artifact_id AS id` for bindings and NULL scope for both consumer tables.

### 3. Contracts
Preserve historical P2/P3/P4/P6 tuple slices. Native receipts contain exact learner/epoch/mapping/delivery linkage and are never shared content; export only opaque identity/scope/created_at, not payload/hash/answers/source/lease. Cutover derives exhaustive classification from the original tuple inventory. Original authorized epoch/reset hooks must delete binding then consumer receipts before502 deliveries/mappings; immutable denial is not bypassed by session GUC. Shared readmission audit remains outside learner purge/export and does not discharge historical findings.

### 4. Validation & Error Matrix
Unclassified new table => no final acceptance; selecting nonexistent `id` or `scope_id` => reject/fix schema-specific safe projection; ordinary update/delete => immutable denial; wrong epoch/current capability => native owner deny. Comment-only classification is insufficient.

### 5. Good / Base / Bad Cases
Good: explicit private sidecar identity-only export and original permit-owned epoch hook. Base: historical slices and old curated/current private families unchanged. Bad: putting public item-linked learner receipts into shared audit, exporting receipt JSON, or deleting502 parents before native consumers.

### 6. Tests Required
Narrow Ruff/Mypy and pure tuple identity/slice assertions passed this increment; Main selected DDL and original safe export/epoch rollback checks remain required once521/522 are independently checked. No new test files or old full suite replay authorized here.

### 7. Wrong vs Correct
Wrong: SQL COMMENT says shared/private, so runtime inventory is assumed complete. Correct: original runtime tuple inventories and per-table safe projection reflect new tables, and Main verifies SQL purge/immutable ordering and actual export after selected installation.
