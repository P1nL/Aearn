# Course Material Lifetime and Exact Renewal

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
