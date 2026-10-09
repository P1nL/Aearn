# Finite type evidence V2 and flexible public specification V3

## 1. Scope / trigger

Applies to new explicit finite candidate specifications, pack computation and their
existing generation/review/native-read consumers. Approved 2026-10-06 inside the
existing item-bank/sandbox task. Three profiles only: single-choice Python KC,
bounded Python state code, SQLite predicate/order. No generic policy framework,
new scorer, public cutover, mastery rule or production evidence issuer is created.
Legacy V1 pack/default factory and Python spec V2 retain their old meaning/hashes.

## 2. Signatures

In `finite_candidate_factory.py`:

- `FLEXIBLE_FACTORY_VERSION = "finite-public-spec-v3"`.
- `build_finite_slot_allocation(*, target_id, family_id, slot, slot_index=1)`
  returns a bounded `FiniteSlotAllocationV2`; `build_finite_candidate_spec` and
  generation reconstruction carry the optional explicit allocation.
- `check_finite_public_spec(public, spec)` reconstructs the registered task;
  `check_finite_source_spec(source, spec)` additionally checks the exact blueprint.
- `check_finite_public_presentation(public, expected, *, public_spec_version)`
  checks allowed fields, not source authority or independent review.

In `pack_builder.py` / `selection.py`:

- `build_pack(inputs, *, now)` dispatches on explicit `PackInputsV1` / `PackInputsV2`.
- `select_pack(base, *, now, enhancement=None, mapping=None)` retains whole-pack
  selection/fallback and explicit version separation; no mixed-version laundering.
- V2 projections: `PackCandidateV2`, `FamilyMemberEvidenceV2`, `CompleteExposureV2`,
  `PackSnapshotV2`, `PackResultV2`, `PackSelectionV2`.
- `relationship_binding_hash(*, profile, request_hash, left, right)` binds stable
  content/objective context, not changing exposure receipts or watermarks.

Database schema500 adds
`item_supply_internal.shared_public_template_matches(request_payload jsonb,
source_public jsonb, target_id text) -> boolean` and changes only the exact489
template comparison in its effective491 guard. It adds no tables/rows/authority.

## 3. Contracts

- A V3 public candidate may change only title and instruction presentation. The
  complete server-rendered instruction block between
  `### finite-public-task-v3:start` and `### finite-public-task-v3:end` must occur
  exactly once with both markers once. Introductory/concluding prose may vary;
  the existing public instruction limit remains8000, with no extra2000 cap.
- All other public fields, structured code/SQL/KC content, options, datasets,
  source references, hints and identities remain exact. Supported Python state
  grammar/event semantics are unchanged; do not promise arbitrary equivalent code.
- New allocation allows compatible supported families in explicit slots. KC
  remediation remains the supported diagnose task; the family registry is a set
  of supported semantics, not a mandatory four-family inventory quota.
  Pack members must match the actual factory's bounded variant and allocation
  definition hash; arbitrary slot labels/hashes cannot stand in for this binding.
- Request-to-canonical-spec remains exact. Actual generated source/public hashes
  remain exact through immutable storage, review, materialization and current read.
  Flexible template matching is never enough to accept a post-review prose edit.
- V2 packs still select distinct2practice/2assessment/1remediation for EACH clause.
  Practice/remediation may share a family; same-family assessments require actual
  nonredundant content-specific evidence. No global six-pair/twelve-transfer gate
  and no practice-to-practice independence requirement.
- KC uses truth/options/ambiguity/misconception/independent-blind evidence without
  fake OS fields. Python/SQLite use existing real execution/scorer, reference,
  genuinely different equivalent solution and wrong/hardcoded/boundary controls.
- Exact item/content/public-task/decision/answer-leakage clones deny assessment.
  `decision_signature` is not the old coarse family hash; `answer_leakage_signature`
  is a contextual semantic fingerprint, not a bare option letter or scalar output.
- Relationship reviewers cover both actual content identities and stable request
  semantics. Independent actor/role receipts and conflict/uncertain vetoes are
  retained. One immutable batch may cover multiple exact pairs; new bindings may
  not be added to an old report. Six-role ITEM review remains separately required.
  Repeated receipt IDs/hashes must have consistent original actors, covered
  bindings, rationale and validity fields across projections; contradictory batch
  projections return relationship_receipt_identity_conflict.
- Fresh eligibility binds current complete exposure owner/epoch/receipt/watermark;
  it may reuse unchanged still-valid content reviews. Never extend old timestamps.
  Compare assessments with each other, chosen practice/remediation and actual
  exposed contents; missing comparison evidence is a gap, not implicit clearance.
  Base and enhancement must share the same resolved complete exposure observation;
  an older/emptier private ledger cannot hide exposure already known by the base.
  Mismatched observations or cross-version enhancement fall back to a freshly
  recomputed whole base (both version directions); stale base stays unavailable.

## 4. Validation and error matrix

| Condition | Required behavior |
| --- | --- |
| V1 or Python V2 prose differs from template | Preserve old strict rejection |
| V3 title/outer prose changes, canonical core intact | Preparation may pass; independent review still required |
| Core missing/changed/duplicated; structured field changes | Reject |
| Post-review public text differs from actual reviewed493 source | Native current-query rejects even if V3 template matches |
| Missing/stale/conflicting content review or exposure | Pack gap/stale; never ready by label |
| Exact clone, scorer/runtime/source/owner mismatch | Reject candidate/assessment |
| Valid same-family training and reviewed assessment relations | Compute full2/2/1 without four-family quota |
| V3 private publication with no trusted finite spec | Remain closed; no source-only version bypass |
| Unexpected489+491 trigger body at500 apply | Reject migration; never best-effort patch guards |

## 5. Good / base / bad cases

Good: a supported family produces two differently presented practice items and a
remediation item through explicit V3 allocation; assessment eligibility is based
on the actual reviewed contents and fresh exposure, not the number of family IDs.

Base: old snapshots deserialize/hash as before. Existing grants and historical
failures remain immutable; a new candidate needs its own source/hash/reviews.

Bad: invent unique semantic hashes, set caller `passed`, reuse old review on a
changed candidate, or mark a pure computed snapshot as native ready/publication.

## 6. Tests required

Focused suites: flexible_spec, flexible_native_consumers, type_evidence_pack_v2,
flexible_public_spec_schema and their directly affected legacy cases. Cover3
profiles, legacy golden hashes, actual public hash binding, same-family allocation,
fresh exposure review reuse, clone/missing-evidence rejection and fallback.

Main alone may execute schema500 on explicit `aearn_b1d_sandbox_20261001`: verify
database identity, atomic application, same-fragment and ordered replay, real SQL
helper positive/negative controls, final trigger-body identity and unchanged
preexisting row digests. SQL-shape unit tests are not actual PostgreSQL compilation.

## 7. Wrong vs correct / remaining authority

Wrong: new DTOs plus green offline fixtures mean live inventory is ready.
Correct: these are trusted-caller computations. New501/502 supply the distinct
native issuer/resolver and original495 exposure integration described in
`learning-item-supply-native-evidence.md`; live installation/populated lifecycle
and full delivery remain separate acceptance. Legacy495 family hashes are not V2 signatures.
Do not weaken the old reservation owner or mint reviewer/source/exposure receipts
to bridge missing authority. Actual-D private lifecycle, real full-pack delivery,
P8/P9/P10 and E require their own recorded acceptance. No implicit Git/public release.
