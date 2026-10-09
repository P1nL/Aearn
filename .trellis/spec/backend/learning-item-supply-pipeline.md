# Learning Item Supply P4/P5 Internal Pipeline

Explicit finite public spec V3 and its version-aware native consumers are described
in [type evidence and flexible specs](./learning-item-supply-type-evidence.md).
Legacy strict checks below remain the default; do not remove them globally.

The user-approved explicit diagnostic-blind V3 branch is specified in
[diagnostic blind admission](./learning-item-supply-diagnostic-blind.md). It changes
only completed blind correctness from an unconditional veto to a warning when
independent hard evidence and all required reviews pass. Legacy V2 stays strict.

> Native public staging/validation added 2026-10-03 is described below; existing
> private P4/P5 and final admission/publication boundaries remain independent.

## Scope and source of truth

The internal `learning/item_supply` generation, deterministic-validation and autonomous-review adapters compose P2 private candidate/version storage and P3 lease/budget/checkpoint contracts. See the architecture, database and API documents indexed by `docs/README.md`. This is not an API, production worker, publisher, Attempt, scoring, progress or Gate integration.

## Contracts and authority

- Keep `LearningItemSourceV1` as the exact content shape, not an authorization upgrade. Existing v1 review/pilot/high-risk human rules and P2 admission decisions stay unchanged.
- `GenerationRequestV2` accepts bounded, approved-public materials with exact assessment-purpose authorization and claim coordinates. Live storage requires the concrete RAG authorizer on the same PostgreSQL connection; persist the strict request and source receipts, and recheck active generation/use/claims before storage, validation and review submission. Item agents cannot fetch, self-authorize or synthesize live claim receipts.
- Live producer/reviewer configuration must match the immutable root provider and registered frozen profile. `trusted_model_bindings` is an internal server mapping from `(provider, profile model-version key)` to the actual configured model, not a caller-selected alias. Missing mappings or unsupported cross-provider/role profile plans remain pending. Freeze and recheck actual provider/model bindings before IO and before commit; a mismatched generation receipt cannot release a reservation as known usage.
- Revalidate original model trees before serialization. Extra fields introduced by constructed/copied nested models must not disappear through base-type dumping.
- `candidate_validation_v2` carries eleven ordered checks plus source/content binding. Deterministic KC uses the existing pure compiler/validator. Code/SQL needs verified live approved-OS-boundary execution evidence; synthetic execution or an absent port is blocked. `short_text` without independent scoring is blocked. The pipeline does not invoke an unbudgeted P6 executor while a database transaction is open.
- KC with no OS execution profile binds review to the actual deterministic `static-exact-v1` path; do not stringify `None` or manufacture an execution profile. Code/SQL without a concrete runtime binding remains pending.
- Independent blind solve sees only public problem/starter/interface, never private answers, hidden tests, rubric or peer reports. The six fixed review roles are peer-blind and author-separated. Actual provider/model/prompt/run facts, not role labels, describe independence and correlation.
- Hard security, uniqueness, rubric, leakage, deterministic and adversarial blockers veto even an approved/minor vote. Stale or missing content/policy/profile/runtime/role receipts cannot be overridden by consensus.
- Medium risk needs real execution/scoring/probe receipts. High risk also needs each declared versioned risk adapter and a genuinely independent second bundle. Missing/contested evidence is pending/quarantine, never fabricated human approval.
- `eligible_internal` is an internal evaluation only, still `publication_enabled=false`. A missing final publisher remains pending. Synthetic fixtures forcibly fail live source-current admission.

## Transactions and accounting

1. Prepare under a current owner/epoch/scope/lease; reserve the immutable P3 root and frozen profile limits. The caller commits this short transaction.
2. Provider IO requires the connection to be IDLE. Refresh the lease in a separate short transaction that ends before IO. Generation and review retry bounds are fixed before reservation and rechecked at invocation.
3. Generation uses bounded transport attempts (default one). Review uses `BoundedOpenAIReviewClient` with one HTTP attempt and the minimum frozen request/stage/parent deadline; the unbounded raw core client is rejected. Reserve the sum of the actual seven port bounds, not an assumed three-attempt multiplier. Token resource plans remain explicit trusted server inputs.
4. Settle separately before committing stage artifacts. Complete attested generation usage may be known; missing/per-attempt-unattested review usage stays unknown and conservatively retains reservations. Null monetary cost is not zero. Lost authorization cannot resurrect stage effects.
5. Recheck the current namespace and source fence and append typed immutable receipts, then checkpoint only the completed stage. Do not manufacture missing P6/P7 checkpoints or mark the entire job completed.

## Storage and maintenance

`460_learning_item_supply_pipeline.sql` adds only `tutor_item_supply_private_generation_artifacts` and `tutor_item_supply_private_pipeline_receipts`. Do not hide v2 metadata in strict v1 `private_staging` payloads. Both tables have composite owner/epoch/scope/job/version references, live lease insertion fences, immutable replay hashes and false publication checks. Their classification feeds the existing bounded private export and cutover owner. The existing reset capability deletes these children before their parents and retains epoch tombstones and anonymous usage facts. Original 440/450 bytes are protected.

Synthetic repository mode is allowed only on `aearn_b1b_fixture_20260930` and the explicitly owned `aearn_b1d_sandbox_20261001`, not on a business database. The B1d DB requires the exact `sandbox.p6.<user UUID>` actor label; fix fixture identity, never loosen its artifact guard. All SUPPLY/GENERATION/NETWORK/V2_ADMISSION/SCHEDULER flags stay default off; no public consumer imports this package.

## Focused verification

Use only the dedicated fixture after asserting `current_database()`, or an unreachable DSN for pure tests. Disable dotenv, LLM and pytest plugin autoload; run `uv --offline pytest --noconftest` from the API package. Cover typed generation/evidence, bounded provider configuration, eleven-check validation, blind/six-role review and admission blockers, plus the short prepare/IO/settle/commit persistence path, immutable replay and owner/lease/reset boundary. Run scoped Ruff and whole-app Mypy. One independent checker plus its affected regressions is sufficient; do not rerun the accepted B1b 503 matrix without a concrete affected contract.

Real assessment sources/claims, provider-run admission, approved execution, public publication and RAG E are separate acceptance facts. Mark missing or unexecuted slices explicitly, never infer them from synthetic test success.

## 2026-10-02 executable V2 generation/review closure

### 1. Scope / trigger
Finite code/SQLite candidates now enter P5 directly with genuine machine-verified `CandidateValidationV2`; no synthetic V1 completion receipt. This does not change old V1 review, human/pilot or publication rules.
### 2. Signatures
`GenerationRequestV2.public_template: LearningItemPublicV1 | None` is optional server-owned public task input. `review_candidate(..., validation_receipt=V1|CandidateValidationV2)` and `evaluate_admission_v2(...)` accept the actual typed validation. `review_resource_plan(...)` measures the actual seven portable prompts and configured output bounds. `receipt_digest(v2)` is the complete V2 evidence hash; `execution_receipt_digest(v2)` is its complete OS execution-evidence hash, not an unrelated terminal ID.
### 3. Contracts
Template identity/version/kind/purpose/difficulty/source refs/interactions must match the frozen request/blueprint; the resulting `source.public` must exactly equal it. Excerpts remain untrusted source data, never a channel for template instructions or hidden answers. JSON-object transports do not enforce out-of-band schemas: generation/solver/reviewer carry their program-owned schema in the system message and count the whole input envelope. Generation and bounded review explicitly disable thinking for this JSON protocol, use one HTTP attempt and retain actual model/usage. Role labels do not turn the same model into independent models.
### 4. Validation / error matrix
Bad template -> `blocked/invalid_request` before source/provider IO; altered provider public output -> `failed/candidate_mismatch`; absent/nonlive/stale V2 execution -> no review admission; reasoning/output exhaustion -> retained failed/unknown, never a success vote; frozen deadline exhausted -> no new HTTP. Explicit bounded recovery needs a new funded reservation/current dispatch, not reusing an exhausted bound or changing an old profile expiry.
### 5. Good/base/bad
Good: exact server public template, real OS receipt and public-only solver; base: no template keeps the previous path/default-off behavior; bad: pass hidden fixture truths in an excerpt, flatten V2 to fake V1, ignore a material difficulty veto or reuse one model as a second independent bundle.
### 6. Tests required
Use the focused generation/V2-review tests and one independent scoped check; assert zero IO on bad template, unchanged source/execution binding, portable schema, public-only solve and same-model correlation. Do not repeat the whole-app or accepted old matrix without a changed dependency.
### 7. Wrong vs correct
Wrong: all model calls and containers returned, therefore admission/publication passed. Correct: Python's real difficulty objection quarantines that exact candidate; SQLite's six approvals still remain pending when current source, coverage or the full admission profile is missing.

## 2026-10-02 actual SQL pre-admission closure

### 1. Scope / Trigger
Fresh current-source private SQL filter/order candidate, explicit isolated engineering fixture; not natural learner Journey, public publish or Attempt/Gate.

### 2. Signatures
TaskAmbiguityOwner runs two sealed calls, resource_plan execution20; prepare_review reserves original7HTTP+blind10+ambiguity20. AdmissionFactsOwner.issue/verify and commit_review(facts_owner=..., facts_receipt=...) use same-connection actual source/goal/lease and concrete execution/blind issuers.

### 3. Contracts
Registered CoverageBlueprint binds actual current node/objective/target clauses and unique demand, not random hash or P7 inventory. Low profile has7 real outcomes, ambiguity under independent duplicate/order cases. New actor source oracle/sign/current precede new generation; never recycle old candidate/votes.481 is immutable private facts, publicationfalse; actual model correlation remains declared.

### 4. Validation / Error Matrix
Explicit live SQL review allocation29 rejects before reserve/providerIO;30 is full bound. Naked AdmissionEvidence DTO/expired current source/missing concrete issuer stays pending. Failed infrastructure is not intended wrong-answer proof. Actual eligible_internal with publication_port_pending is not publish/Gate completion.

### 5. Good / Base / Bad Cases
Good: new current-source generation,9 positive/8 negative FP/FN/pending0, blind pass,6 approved roles, two sealed ambiguity controls,481 issue/verify/finalfence. Base: legacy/synthetic paths remain distinct. Bad: stdout-only Python proof asserted to establish assignment, changing old D2 votes, classifying target coverage as inventory or unknown usage as0.

### 6. Focused Tests / Evidence
Facts scoped9 cases plus only affected1 repair recheck; no wholeapp/accepted matrix replay. Actual result real-current-sql-chain-20261002.json and persisted live facts final PG evidence prove this SQL scope only.8 bounded model invocation telemetry enters the original project register; aggregate review remains conservativeUNKNOWN and money null.

### 7. Wrong vs Correct
Wrong: infer all first-batch/P7 readiness from this one candidate. Correct: record SQL eligible_internal, preserve Python assignment/scorer gap, and close remaining scope prerequisites before reporting whole-stage acceptance. No implicit commit/push/public release.

## Native Public Staging and Validation (2026-10-03)

### 1. Scope / Trigger
Closed finite public course candidates use P3 public canonical roots, not a fake
learner or private scope. The implementation is default-off and restricted to the
existing `aearn_b1d_sandbox_20261001` internal database.

### 2. Signatures
`SharedGenerationPipeline.prepare_generation / run_generation / settle_generation /
commit_generation` stages immutable request+source+receipt through489.
`SharedValidationPipeline.prepare_validation(lease=..., artifact_id=..., spec=...,
source_authority=..., runner=None)` returns an in-process prepared capability;
`run_validation / settle_validation / commit_validation` compose490 and the native
finite validator. See the sandbox code-spec for exact finite scorer/probe rules.

### 3. Contracts
Only native `PublicCourseEvidenceBindingV1` materials enter this path;
`GenerationRequestV2.demand_binding=None`. Full request, actual provider model,
frozen profile, exact coverage declaration, source claims and runtime/scorer
identities must match. No bank version is imported at generation/validation.
Prepare and current fences use a same-connection concrete C authority; mixed
Python corpus needs both assessment and teaching verifiers. Compose that authority
inside its required caller transaction, not while the connection is IDLE.

### 4. Validation / Error Matrix
External provider/runner IO requires IDLE after committed reservation. Settlement
commits separately before final source/lease checks. Reservation replay is not a
new HTTP/run permission. Unknown execution use retains reservation; lost current
authorization prevents stage effects but not truthful usage settlement. Static
KC has no runner/reservation/terminal. An invalid source/spec, stale lease,
uncommitted settlement or restored prepared JSON is rejected; only genuine
`machine_verified` advances validating.

### 5. Good / Base / Bad
Good: the same original generated data reaches current authorized deterministic
validation. Base: staged or blocked evidence remains unpublished. Bad: copy a
private item into shared, create a fake learner for public generation, rewrite an
expired parent deadline or restore runner seals from a file.

### 6. Minimum Checks
New focused cases and scoped checks; main-only actual three-target generation /
validation and one necessary new-row bootstrap replay. Preserve original errors
and rerun only the failed operation, not the entire source/provider/runner chain.
Shared tables stay outside user private export/reset and historical P3 inventory
slice stays twelve tables.

### 7. Wrong vs Correct
Wrong: three machine-verified first-family candidates mean full-course ready/E.
Correct: retain their committed identities and actual usage while separately
closing blind/six-role/ambiguity/final facts, publication, family allocation,
exposure, whole packs and formal learner/E gates.


## 2026-10-04 checkpoint: explicit Python public-spec revision and family plans

### 1. Scope / trigger
Actual native Python six-role review quarantined the original candidate. Static diagnosis found real public/matcher and blank-metadata mismatches, not evidence that all model votes were mistaken. Original votes/candidate/source remain immutable.

### 2. Signatures
`build_finite_candidate_spec(..., public_spec_version=PYTHON_FACTORY_VERSION_V2)` explicitly selects Python `finite-public-spec-v2`; FACTORY_VERSION/default remain v1. Version lives in existing blueprint.version, with no new DTO default field. Request/validation/probe reconstruct exact original version. SQL/KC reject this Python V2. `build_finite_family_transfer_plan(target_id, specs=four_exact_specs, materials=...)` and `finite_family_transfer_work(plan, materials=...)` create only private declaration plans/resource bounds.

### 3. Contracts
V2 public constraints state actual finite initialization/update/output shapes; do not change matcher/scorer/target/family identities. Completion regex counts only a necessary minimum assignment-symbol count and is explicitly NOT a goal predicate; comments can satisfy it, while actual scoring still requires sealed goal+stdout. Program-owned descriptor exposes compiler hashes/case bindings/terminal rules privately to reviewers, not a verdict or blind/public answer. Family plans bind exact public spec version/hash and original/target reference checks; no terminal, seal, reservation, independent verdict or course mapping is issued.

### 4. Validation / errors
V1 public relabeled as V2 fails exact reconstruction. Mixed-version family plans fail. Legal successful semantic mismatch is required for an eventual witness; syntax/missing-column/dimension-padding/arbitrary wrong-option failures do not count. Current seed0 plans: Python12directions pending actual execution/review; SQL7planned/5unresolved; KC0planned/12unresolved. Do not turn these gaps into independent families.

### 5. Good / base / bad
Good future path: valid new source/operation + explicit V2 + NEW candidate and full actual review. Base: old V1 bytes/hash and quarantine preserved. Bad: edit the old review, renew old proof, change source public template in place, or silently weaken family count/witness requirements.

### 6. Tests and evidence
V2 worker one case passed,7pre-change V1 specs retained exact bytes/hash, scoped lint/type passed; real V2 generation/review and independent check remain pending. Family worker one focused deterministic case and scoped lint/type passed, no actual runner or model evidence. All source/runtime/grant checks are still separate. Refer to research/p7b-native-python-public-spec-v2.md and p7b-finite-family-transfer-worker-20261003.md in the active task.

### 7. Wrong vs correct
Wrong: count four task labels or planned counterexamples as 2/2/1. Correct: preserve unresolved pair directions, establish lawful finite witnesses and exact course-clause mappings with actual review, then compute full supply. User-requested stopping is not P7/P10/E acceptance.

## 2026-10-09 explicit review thinking transport

Fresh evidenced-role review calls may explicitly select DeepSeek `thinking_mode="enabled"` and `reasoning_effort="high"`. `OpenAICompatibleClient.complete_json` has an additive optional effort argument; omission preserves historical/default requests. Only the documented exact `deepseek-flash`/`deepseek-v4-pro` models accept the new explicit argument. Unsupported provider/model, unsupported effort, or disabled/unspecified thinking plus an explicit effort rejects before IO.

Responses carries `reasoning.effort`; Chat carries `thinking.type` plus `reasoning_effort`. Keep the caller's frozen token/output bounds, one-attempt review client, and independent settlement/UNKNOWN rules. Do not raise old root/profile caps or switch providers to support thinking. Disable provider-body capture and expose no reasoning text; the review consumes final structured output only. Chat `finish_reason=length|content_filter` is incomplete even if its visible content happens to parse as JSON; retain safe usage and stay pending. Existing Responses terminal validation still applies.

The dated 2026-10-02 non-thinking generation/review statement is historical and remains true for legacy calls; this addition does not change generation, Tutor or old completed receipts. Official parameter verification: active task research/deepseek-review-thinking-official-20261009.md. Real reviewer-quality measurement is separate from fake-transport serialization checks.

## 2026-10-09 evidenced six-role review protocol

### 1. Scope / trigger
Fresh native six-role review uses `evidenced-v1`. This is a private code/protocol repair, not source authorization, publication, learner scoring or reviewer-accuracy acceptance. Old DTO/history and outer V2/V3 admission policies remain exact.

### 2. Signatures
- `make_review_request(source, *, binding, validation_receipt, role, protocol="legacy-v2") -> ReviewRequest` and `verify_review_report(report, request) -> ReviewReport` are the central dispatch/verification boundary in `review_protocol.py`.
- Native operator fresh CLI defaults to `--review-protocol evidenced-v1`; `--plan` remains zero-IO. Explicit `--review-protocol legacy-v2` retains compatibility. `--execute` is main-only and requires a new immutable campaign and actual current owner/source/budget prerequisites.
- `OpenAICompatibleClient.complete_json(..., thinking_mode="enabled", reasoning_effort="high")` maps Flash Responses to `reasoning.effort` and V4-Pro Chat to `thinking.type` plus `reasoning_effort`. Unsupported explicit provider/model/effort rejects before HTTP.

### 3. Contracts
- `EvidencedReviewInputV1` wraps the exact typed subject plus private evidence index. `EvidencedReviewFindingV1` requires problem, expected behavior, exact pointer/value_hash references and an applicable counterexample. `EvidencedReviewOutputV1`/`EvidencedReviewReportV1` retain the actual new schema/output_hash; never compress to a legacy vote and counterfeit a provider hash.
- The exact `evidenced_protocol_marker()` freezes protocol/prompt/input/output/report versions, enabled/high thinking and null temperature. Marker-absent stored plans and old port/build_plan defaults remain legacy, not silently upgraded.
- Outer ReviewBundleV2/V3 policies/hash semantics and old JSON stay unchanged. Prepare/run/commit must use the same protocol; admission/history use the report-aware verifier. Same-model correlation and high-risk independent second bundle remain mandatory.
- Six domain rubrics share hard codes and finite boundaries. Specialization must not suppress a genuine cross-role hard defect. Hard codes require major/critical blocking findings; info/minor are advice, and minor_issue cannot be material. approved means no material findings; changes_required means major without critical; rejected requires critical.
- Field references authenticate actual relevant input fields/binding, not semantic truth. Keep problem/expected/counterexample private and hidden from repr/public DTOs; no chain of thought, peer votes, blind answers or provider-body capture.
- Frozen output/input/token/request bounds and UNKNOWN remain unchanged. Late-role errors retain private completed reports without a successful bundle; native `partial-review-reports.json` is an exclusive no-admission checkpoint before settlement. Non-native private state is exception/instance retention, not a DB journal or replay capability.

### 4. Validation / error matrix
- Unknown/mixed protocol, marker tampering or stored-plan mismatch: reject before reservation/DB/provider access, including imported execution/direct preparation.
- Empty/contradictory denial, wrong severity/hard-code pairing, unrelated or hash-tampered refs: no valid vote/success bundle; pending, never automatic approval.
- Reservation `REPLAY`: no new prepared review/dispatch permission; no re-review or budget reset.
- Thinking output truncated/filtered, including valid-looking Chat JSON with length/content_filter: incomplete/pending, preserve safe usage and UNKNOWN.
- Major material defect with valid field evidence: original hard veto still applies; six votes cannot override deterministic/source/risk/coverage/runtime failure.

### 5. Good / base / bad cases
Good: new frozen evidenced campaign, concrete relevant private evidence, actual high wire fields and original owners. Base: explicit legacy/marker-absent history retains original bytes and interpretation. Bad: upgrade an old campaign, ban cross-role safety findings, treat equal numeric answer components as two complete correct answers, or count matching pointers as proof a model claim is true.

### 6. Tests required
Focused `test_item_supply_evidenced_review.py`, `test_native_evidenced_review_plan.py`, legacy/autonomous/private/shared regressions and `test_llm_responses_diagnostics.py` cover exact hashes, failed-role retention, finite descriptors, scale consistency, same-model risk, pre-reservation/replay fences and Chat/Responses high. Use explicit zero-IO tests first; PG tests require a named disposable fixture database and rollback, not default business DSN. Labeled doubles are not a real precision/recall benchmark. Actual high-thinking calibration and populated publication/readback require separate receipts.

### 7. Wrong vs correct
Wrong: all six model calls returned JSON, therefore the pack/review quality/publication passed. Correct: verify actual field-bound reports and unchanged budget/source/owner gates, retain pending/denial as facts, then independently validate native persistence and real supply. Do not replay old quarantine until green or declare P7b/E complete from protocol tests.
