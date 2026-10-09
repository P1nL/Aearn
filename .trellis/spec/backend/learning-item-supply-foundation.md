# Learning Item Supply Foundation (P0/P1, offline)

For the separately approved new V2 pack computation (not a silent change to these
V1 contracts), see [finite type evidence](./learning-item-supply-type-evidence.md).

## 1. Scope / trigger

Applies to `app/services/learning/item_supply/{contracts,coverage,matrix,exposure}.py` and their pure tests. This package is an internal declaration and exact-fact validation layer only. No database/schema/job/provider/network/runner, public route or existing Gate/Practice consumer is wired to it. Source, publication, scorer, Attempt and progress remain their existing owners.

## 2. Interfaces

- `build_support_matrix() -> SupportMatrixSnapshot`: immutable snapshot/hash of actual language-capability declarations, public-course language groups and existing Item Kind/Purpose/Interaction enums. M01/M02/M03 are bounded first-batch target metadata; execution-type Gate adapters are still planned. Runtime/source/inventory readiness is explicitly `not_evaluated`.
- `SupplyScopeV1`: exact course/version, node, canonical language and Subject/version/facets, dialect, runtime/profile digest, item kind/purpose/interaction, capabilities, assessment/scorer/assistance policy, visibility and private owner.
- `CoverageBlueprintV1`, `AssessmentSupplyDemandV1`: exact objective/clause identities, validated acyclic prerequisites, scope, matrix/policy and canonical hashes. `MinimumCoverageV1` requires at least 2 practice variants, 2 independent assessment candidates and 1 remediation path per clause; these are coverage redundancy, never compulsory learner counts or mastery rules.
- `ObjectiveCoverageProofV1`, `CandidateAuthorityV1`, `SourceAuthorizationFactsV1`: exact immutable item/content, objective/clause, family/slot, source/evidence/current authorization, runtime/scorer/assistance/matrix/policy coordinates and aware validity intervals. The facts come from a trusted caller in a future owner composition; P1 does not issue signatures or resolve production receipts.
- `ExposureRecordV1`, `ExposureSnapshotV1`, `check_exposure(snapshot, *, learner_ref, scope_hash, item_handle, candidate_family_id, independent)`: pure eligibility over exact learner/scope facts. Wrong/forged snapshots deny, independent checks exclude previously exposed item/family; ordinary practice can reuse exposure without changing formal independence.
- `evaluate_supply(demand, blueprint, candidates, exposure, *, now) -> AssessmentSupplyResultV1`: bounded pure evaluation; no implicit clock or IO. It returns safe gap/stale or complete `ready_exact`. Pending/failed type variants are reserved, not evidence of actual background work.

## 3. Contracts and trust boundary

- Reuse actual `LANGUAGE_CAPABILITIES`, `PUBLIC_COURSE_LANGUAGE_MAP`, `LearningItemKind/Purpose/Interaction`, `FrozenContract` and canonical JSON/hash helpers. No parallel language registry or Item publication authority.
- Strict/frozen/extra-forbid data, bounded identifiers/arrays/hash/time and nested revalidation at decision and hash boundaries, including `model_copy`/`model_construct` payloads. Revalidate the original model instance before serialization: base-annotated serialization can otherwise drop forbidden nested subclass fields. All four scope/blueprint/demand/proof hash properties validate first. Validate structure before graph/set traversal; malformed inputs must not leak raw input or framework exceptions through decision APIs.
- Public content carries no private owner; private content matches both its scope owner and demand learner. A caller's independent/exposure flags never authorize cross-user access.
- `visibility="public"` means shared content visibility, not Subject release or public-consumer enablement. Do not bypass shadow/fixture-only/source-use release policies with this field.
- Compare the demand and blueprint identity and the current `build_support_matrix().matrix_hash` first, then proof versus actual item/content/clauses/scope/profile/matrix/policy/scorer/assistance/source facts. A matching hash alone is not trust. Source facts must be active and current at explicit `now`; assessment slots require assessment evidence, not supplementary or main-teaching permission.
- Published, required materialization, `available_capabilities` containing the requested capabilities, runtime readiness and current authorization must all agree. Absent booleans/receipts deny by default. Replays/same handles/content/families cannot inflate independent coverage; per-clause/slot content-to-family matching is bounded and deterministic, avoiding greedy under-count when a complete independent combination exists. Conflicting immutable identities, including source coordinates, invalidate all copies of that handle; fresh dynamic authorization/proof observations are not content conflicts. Unknown/cyclic/unmet predecessors do not become covered just because a child has candidates.
- DEMO or DEMONSTRATION assessment candidates return `assessment_unsupported`, even with synthetic scorer strings and all boolean facts true. Their lawful practice/remediation portion cannot imply a complete formal assessment package. Planned/unsupported language declarations return `language_unsupported` and cannot be upgraded by caller runtime booleans; partial declaration is not silently treated as planned or full physical readiness.
- Complete required slots for every clause yield `ready_exact`; partial counts remain gaps. Old/expired evidence is discarded and reported safely. A synthetic caller-fact positive validates the algorithm only: it is NOT real publication, current source truth, runtime proof, formal assessment or publicly usable inventory.
- This package is not connected to default/public/runtime paths. Later P2/P4/P5/P7 must persist exact facts, use trusted source/claim/execution resolvers and publication fence on the owner's transaction, then revalidate again at supply time. No model payload may bypass those later authorities by constructing P1 facts.

## 4. Validation / errors

| Condition | Required result |
| --- | --- |
| Nested forged copy/construct, extra fields, bool as integer, invalid time/graph | Reject with bounded input error; no IO |
| Same title/key but different objective/clause/scope/version | Safe mismatch; no coverage |
| Source missing/inactive/expired/mismatched or wrong assessment purpose | Deny candidate; no trust expansion |
| Not published/materialized, missing capabilities/runtime/proof | Safe gap; never false ready |
| Cross-private owner or wrong exposure learner/scope | Deny; no private payload projection |
| Replayed candidates / same family or content | No extra independent count |
| Greedy content/family collision with a valid independent combination | Find the bounded matching; no artificial gap |
| Same handle with conflicting immutable source coordinates | Exclude every conflicting copy |
| Demo assessment or planned/unsupported declaration | Explicit unsupported denial; no fake formal ready |
| Complete exact synthetic facts | Algorithm-only ready result; never production evidence |

## 5. Good / Base / Bad cases

- Good: exact synthetic scope/proofs/current-source facts plus a full independent combination return an algorithm-only ready result; expired or wrong-purpose alternatives do not count.
- Base: no candidate authority facts returns explicit gaps, with no IO, job creation or Gate mutation. Matrix snapshots remain declaration-only even for nominally full languages.
- Bad: permit nested subclass `raw_answer` by serializing it away; sign/hash a malformed constructed model; allow a demonstration to count formal assessment; or claim a stored synthetic ready result proves current published inventory.

## 6. Tests required and nonclaims

Run only `test_item_supply_contracts.py`, `test_item_supply_coverage.py`, `test_item_supply_matrix.py`, `test_item_supply_exposure.py` with dotenv disabled, LLM disabled, an explicit unreachable sentinel DATABASE_URL, plugin autoload disabled and `pytest --noconftest`. Root `tests/conftest.py` imports Tutor/worker/route and offers DB fixtures; disabling dotenv alone is insufficient. Do not widen this whitelist to DB/Tutor suites.

Record focused pytest/Ruff/Mypy/lock and AST/transitive import boundary separately from source/provider/DB/browser acceptance. Imports of the five frozen P1 API modules (`__init__`, `contracts`, `coverage`, `matrix`, `exposure`) may use pure contracts/registries, never repository, config/env-reader, route, worker, provider or executable runner. P2 storage modules are separately scoped by `learning-item-supply-storage.md` and must not be imported transitively by these pure APIs; later module additions do not broaden the P1 no-IO whitelist. No real data reset/cleanup, source-use renewal, production release or auto-commit is implied.

Assertions must include: nested subtype extras and hash-boundary copy/construct rejection; all-side non-assessment source-use denial; current matrix identity; missing capabilities/authorization/runtime; same-handle source conflict versus legitimate dynamic authorization refresh; content/family augmenting-path coverage and ordering invariance; unmatched prerequisites; private/exposure isolation; intrinsic demo/planned denials and default no-IO behavior.

## 7. Wrong vs correct

```python
# Wrong: projection can discard nested subclass fields before validation.
cleaned = CoverageBlueprintV1.model_validate(untrusted.model_dump(mode="python"))

# Correct: validate the original strict instance before any serialization/hash.
checked = revalidate_contract(untrusted, CoverageBlueprintV1)
digest = checked.blueprint_hash
```

Wrong selection: greedily keep `(content1,family1)` and report a gap after rejecting both collisions. Correct selection: bounded deterministic matching can instead choose `(content1,family2)` plus `(content2,family1)`, after each has passed all actual-fact checks. This algorithm correction does not authenticate the caller facts.
