# Course Material Lifetime and Exact Renewal

## P7 explicit registered-source successor (544, 2026-10-13)

### 1. Scope / Trigger
Only the newly authorized `python_reference` gen3 refresh after historical gen1/gen2 authorities expired. Not general auto-renewal, a model budget, or confirmed mapping acceptance.

### 2. Signatures
`registered_course_refresh_successor.issue(conn, *, target_key, source_permission_expires_at, retention_permission_expires_at, enabled=False) -> CourseRefreshResult`. Caller owns an active transaction; `manifest_entry()` feeds the unchanged original registered-source transport. Fixed successor UUID `fbfabcf0-f336-5b12-9824-8b0b2782b69c`; original receiver is `rag_registered_course_refresh_check`.

### 3. Contracts
Lock the canonical original attempt and require the exact two settled attempts, preceding498 authorization and capture. Preserve both historical dispatch debits; cumulative ceiling3 permits one additional dispatch. The new root remains source-access-only, with no new core budget period/reservation. New source permission is bounded by explicit access/retention limits and7days; dispatch is independently at most30minutes. Old grants/captures/expiry are immutable. PUBLIC and PRIVATE assessment proofs need distinct document handles, while original private-public provenance may bind the same current capture.

### 4. Validation and Error Matrix
Disabled/wrong target -> `COURSE_REFRESH_DEFAULT_OFF`; absent caller transaction -> `COURSE_REFRESH_CALLER_TRANSACTION_REQUIRED`; repeat issuance -> `COURSE_REFRESH_SUCCESSOR_ONCE_CONSUMED`; unexpected lineage/UNKNOWN cannot be silently normalized to zero. SQL independently verifies lineage and rights at issue and dispatch INSERT.

### 5. Good / Base / Bad Cases
Good: new owner-issued gen3 authority followed by one actual original transport capture. Base:498 historical branch behavior and source transport stay unchanged. Bad: new root as an empty wallet, old expiry update, new UUID as sufficient permission, re-GET of a consumed dispatch, or PUBLIC proof substituted for confirmed PRIVATE demand.

### 6. Tests and Actual Evidence
Four focused tests cover history/debits, manifest/no-wallet, default/target/once/transaction denials, and exact SQL branch preservation; Ruff/scoped Mypy passed. Main actual compile/replay, original issuer/duplicate denial, dispatch receiver INSERT and full rollback preceded selective installation. Installed544 changes1 original prosrc,3 CHECKs, and2 UNIQUEs to2 narrow partial UNIQUEs; old function OID/owner/ACL and all prior rows remain. One actual gen3 GET settled on2026-10-13 with retention through2026-10-20T09:26:48.121679Z. Original PUBLIC preparation confirms supported spans unchanged despite different HTML scaffolding. This does not assert signed PRIVATE proof, mapping or revision acceptance.

### 7. Wrong vs Correct
Wrong: replay498 issuance or rewrite the old source cutoff. Correct: issue the explicit successor through the original receiver, preserve historical accounting, and acquire/verify new source proof before any consuming operation.

## New course material lifetime (2026-10-06)

- New native course assessment/teaching proofs use `course_material_7d_v1` and explicit v2 signing domains. Historical v1 payload bytes and 24h bounds stay compatible. Seven days is an engineering default under the user's extension request, not an unconditional grant.
- `new_material_expiry` takes the minimum of all independently current policy, storage, delegation and period deadlines. Unknown/expired inputs deny; SQLite SELECT/expression/corefunc minima all apply. Omit an explicit old six-hour signing deadline to use the new bounded default.
- Additive497 requires the exact final488 guard body (or its exact497 transformation) before any DDL. Never replace a matching format string in an unknown/older guard. Historical rows are not updated.
- Expired roots/policies/captures require a lawful new authority/capture path; same-name periods or new roots do not magically inherit charged/unknown resources. No renewal of old seals, consumed dispatches, job leases or runtime health. 484's independent24h exception remains unchanged.
- Offline lifetime tests and isolated497 DDL are not new7d live proof acceptance. Actual new issue/persist/current consumption must be recorded separately; failure/history/unknown remain visible.

## Bounded refresh and actual-D gates (2026-10-06)

### 1. Scope / Trigger
Only B1d five-source refresh and the existing finite Python/SQLite consumers. Not general renewal, a wallet, automatic user-linked audit retention or public release.

### 2. Signatures
`registered_course_refresh.issue(conn,target_key,source_permission_expires_at,retention_permission_expires_at,enabled=False)`; schema498 `rag_registered_course_refresh_authorizations` and the same `rag_registered_course_refresh_check` at issue/supplemental/dispatch. Actual-D uses `AssessmentReceiptRepository.prepare_actual_d` and signature format `aearn.rag.actual-d-finite-source.v3`; the latter is lifecycle-gated and has no live v3 rows at this checkpoint.

### 3. Contracts
Canonical original lineage is immutable and unique under standing authorization; the physical supplemental predecessor can be the real latest terminal only through the explicit498 branch. Carry actual historical dispatch/unknown debits; a committed dispatch permanently consumes the one new allowance. Source-access-only roots are excluded by `PostgresBudgetPolicyResolver`, with no new budget periods/reservations. Material<=7d and independent dispatch<=30min; old grants/expiry/unknown remain unchanged.

Current assessment consume lookup is exact `(demand_hash,policy_id,policy_generation,budget.root_id)` plus unrevoked/current issue/expiry. Require exactly one signed candidate, then corpus-before-proof locks and full signed request equality. A historical proof with the same demand hash is neither a current candidate nor permission to select latest arbitrarily.

### 4. Validation / Error Matrix
Wrong/repeated lineage, wrong request, consumed dispatch, generic budget use of a refresh root => deny without another GET. Two exact-current signed candidates => deny, never latest-wins. Old PUBLIC or sum/filter receipt used for actual-D finite semantics => pending. Deleted user or proof expiry reached while waiting for a lock => deny. Private v3 lifecycle not classified => no live v3 issuance/ready claim.

### 5. Good / Base / Bad Cases
Good: new5 bounded captures and new actual sealed proofs, old7 debits/unknown retained, current internal source qualification. Base: all historical350/390/400/420/484 paths remain. Bad: reset a root as a new wallet, rewrite old expiry, reuse a PUBLIC terminal for D, drop user associations from a signed payload, or call user-linked data anonymous.

### 6. Tests / Evidence Required
Keep focused offline lineage/consumer-renewal cases plus main-only exact DDL, rollback-only issue and SELECT dispatch INSERT to exercise390. Compare original-column projections when adding a nullable field. Fresh proof/C consumption must be real and separate from schema green; real new5 capture/4oracle/current records exist at research/session-checkpoint-20261006.md. Actual-D safe export/reset/delete and genuine producer/freeze/confirm/mapping remain unverified.

### 7. Wrong vs Correct
Wrong: `WHERE demand_hash=... LIMIT 1 ORDER BY issued_at DESC` or reject every renewal because any historical row exists. Correct: locate unique current exact policy/generation/root authority, then revalidate the actual signed proof and original C owner without changing old receipts.

## 2026-10-14 exact same-TOP current-record reuse

- Whole-pack current-source scope is issued by the original concrete owner with an actually emitted same-TOP origin and exact object/seal/issuer/actor/epoch/selected5/digest binding. No UUID, file, prior origin or expired capability restores it.
- AssessmentReceiptRepository first executes original complete signature/terminal/prepare/provenance verification. Tail reuses only those exact signed DATA bytes, digests and the original closed-set expected row predicates; it still rereads evidence/review/admission/claim state, revocation, quality, bindings, facets/usages, applicability/execution scope and deadlines.
- Reuse retains original PUBLIC assert_current and SQL549 as well as the complete PRIVATE Python current-record fence. SQL549 alone is not the full PRIVATE state check. Service keys, provenance owner/connection, default-off PRIVATE lifecycle/schema/config and original transaction gates remain current at both ends.
- Nested duplicate work may be combined only in one closed original verifier invocation with FULL initial/final source checks. No authority cache crosses invocations/TOP. Source/repository denial clears DATA and keeps a tombstone until scope exit; catching and restoring values cannot reuse it.
- Installed SQL<=550, original 30-second exposure TTL, old deadlines/once/UNKNOWN and accounting history are immutable. This optimization grants no model, PRIVATE content, delivery or publication permission.

## 2026-10-15 current transaction front without redundant roundtrips

- AssessmentReceiptRepository.require_transaction() keeps enabled/autocommit/INTRANS checks before SQL, then performs one live SELECT of current_database() and current_setting('transaction_isolation'/'transaction_read_only') on every invocation. It never caches a successful transaction or source authorization.
- Read aliases are name, transaction_isolation, transaction_read_only. Missing row/name or wrong owned database denies SOURCE_DATABASE_DENIED first; missing/bad isolation or readonly then denies SOURCE_TRANSACTION_DENIED. Original read-committed/read-write requirements and all downstream source/epoch/clock/lock fences remain unchanged.
- Keep independent post-wait server clocks where their original owners require them; this roundtrip reduction does not move a later clock earlier or extend exposure/source deadlines. Installed SQL<=555 is frozen for the current P7 execution.
- _CurrentReceiptData.provenance is typed as the two concrete provenance compositions accepted by the repository constructor; this is DATA typing, not a new runtime authority or bypass.
- Focused regression assertions: one real query each call; a second call rereads and rejects changes; wrong database error priority; absent row/fields denial; front guard performs no SQL. Existing legacy fake-query branches remain for other original callers. C8 independent CODE, 18 directly affected offline checks, scoped Ruff and mypy passed; original Artifact acceptance is a separate Main result.
- Wrong: memoize require_transaction as passed for a connection. Correct: batch the three current values into one statement on every call, preserving fail-closed behavior.
