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

## 2026-10-09 private review failure observations

### 1. Scope / trigger
A real new evidenced/high candidate reached machine validation and completed blind solve, then `review_pending` without a peer bundle. The former blanket adapter/bundle exception mapping discarded failure category and usage. This addition preserves closed **private diagnostics only**; it does not prove the old failure cause, permit its replay, change model/output budgets or make a failed candidate eligible. No API, schema migration or public DTO is added.

### 2. Signatures
- `observe_review_failure(exc, *, phase, failed_role=None, usage=None, response_diagnostics=None, logical_client_invocations=None, safe_code=None) -> ReviewFailureObservation` in `review_observability.py` maps trusted types/enums, never exception prose.
- `ReviewFailureObservation.payload() -> dict[str, object]` revalidates the immutable closed projection. `AutonomousReviewError.observation_payload()` and `SharedReviewResult.observation_payload()` return this payload or `None`.
- The private pipeline retains available failure observations by the original reservation ID; this is process-local state, not a persistent DB journal or replay capability.
- Native `checkpoint_review_observation(folder, *, reservation_id, result)` exclusively saves `review-observation.json` immediately after `run_review` and **before** `settle_review`. The same payload is added to final `review.json` only when present.

### 3. Contracts
- Failure schema `item_supply_review_failure_observation_v1`: `phase`, `failed_role`, `safe_code`, nullable normalized `usage` and `response_diagnostics`, nullable `logical_client_invocations`, fixed count scope/semantics. Role is an existing `LearningItemReviewRole` or null for a non-peer stage.
- Closed phases: provider_call, output_schema, evidence_verification, review_bundle, blind_score, finite_ambiguity. Codes distinguish provider timeout/transport/configuration, incomplete/failed/missing/non-JSON/envelope responses, schema validation, evidence verification, provider binding/output limits and unknown exceptions.
- Reuse `LLMUsage` and `LLMResponseDiagnostics`: numeric token counts, allowlisted response status/incomplete reason/requested effort and output limit/visible length only. Unavailable usage remains null. Preserve usage after provider JSON parses but output schema or evidenced references fail; provider body/answers/reasoning text never enter this projection.
- A logical client invocation of 1 attests only the failed adapter operation was entered; it is NOT the actual HTTP attempt count, whole-review count, reservation count or settled money. Pre-invocation failures leave it null. Do not invent aggregate usage or convert UNKNOWN settlement to known from these diagnostics.
- Checkpoint schema `item_supply_private_review_observation_checkpoint_v1` binds the reservation ID and sets visibility=private_only, admission_eligible=false, publication_enabled=false, accounting_authority=false. It has no lease/dispatch capability and cannot overwrite a prior checkpoint.
- Preserve partial completed role reports together with the original failed role/category. Outer V2/V3 report/bundle/admission hashes and safe_reason behavior stay unchanged. Nonempty new observation payloads participate in shared result integrity; no-observation legacy result hashes and receipt shape remain exact.

### 4. Validation / error matrix
| Condition | Observation and unchanged authority outcome |
| --- | --- |
| Incomplete output with max_output_tokens and usage | response_incomplete plus the allowlisted stop reason/known tokens; still pending/UNKNOWN |
| Wrapped real transport timeout | provider_timeout by bounded trusted cause types, never message matching |
| Parsed JSON violates output schema | output_schema/schema_validation; retain available usage |
| Evidenced pointer/report verification fails | evidence_verification with actual role and available usage; no valid vote |
| Later role fails | Keep earlier completed reports and the failing role's observation, not a synthetic successful bundle |
| Unrecognized exception containing a URL/key/provider text | unknown_exception; no message, stack, raw Pydantic errors or provider content in payload |
| Shared result observation is replaced/tampered | Original result integrity rejects before commit/settlement authority |
| Settlement subsequently fails | Exclusive pre-settlement private checkpoint already exists; no second provider dispatch |
| Metadata absent in historical result | observation_payload=None; no new observation file/key and unchanged legacy hash |

### 5. Good / base / bad cases
Good: a controlled incomplete response retains output usage and max_output_tokens reason under the technical role, then stays pending. Base: an old no-observation result serializes exactly as before. Bad: assuming high caused truncation from elapsed time alone, recording reserved seven requests as seven actual calls, or changing UNKNOWN accounting because one failed response supplied tokens.

### 6. Tests required
Focused private review-observability tests cover real bounded-client response/error types, safe secret-sentinel projection, schema/evidenced rejection metadata, late-role partials, shared result tampering and legacy hashes. Operator tests assert run_review < observation checkpoint < settle_review, exclusive no-overwrite receipts and no-observation zero-file behavior. Run existing legacy/evidenced/shared/private/operator regressions, scoped Ruff and API Mypy; controlled offline errors are not a live quality or publication acceptance.

### 7. Wrong vs correct
Wrong: `str(exc)` or Pydantic raw errors are useful diagnostics, so save them with the provider body and retry until approved. Correct: classify by trusted types/closed enums, suppress raw cause propagation after copying safe metadata, retain only private normalized observations, and leave the original failed candidate/history/UNKNOWN untouched. A future new immutable bounded candidate can supply fresh diagnostic evidence; the missing old metadata cannot be reconstructed as fact.

## 2026-10-09 production peer output and single-slot probes

The peer-only marker below is retained for historical frozen plans. The later
unified-production section supersedes NEW CLI defaults; it does not upgrade these
old plans or change their8192/2048/61440 resource arithmetic.

### 1. Scope / trigger
A fresh high curriculum response actually exhausted its 2048 output budget on reasoning with zero visible output. The user explicitly selected the **formal application production output limit**, not the proposed ad-hoc8192 calibration. This config repair does not retrospectively prove other old pending causes or modify old candidates/plans, admission gates, UNKNOWN or money authorization.

### 2. Signatures
- `production_peer_output_cap() -> int` reuses `app.core.config.DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS` (currently61440). Runtime `require_production_peer_output(settings, cap)` requires configured Flash Responses and exact `settings.tutor_max_output_tokens` equality before new execution; default/legacy2048 remains compatible.
- `build_plan(target, seed=0, *, admission_policy="strict-v2", review_protocol="legacy-v2", peer_review_max_output_tokens=2048, probe_slot=None)` preserves historical default JSON/hash exactly. Production cap is an explicit **new** evidenced plan option, not a replacement of old files.
- `validate_plan(plan, *, slot_name=None)` reconstructs the complete trusted plan; `validate_campaign_state(path, plan, *, slot_name=None)` also checks stored plan/cases/accounting before IO. Imported execute and direct prepare obey the same guards.
- CLI: `--peer-review-max-output-tokens 61440 --probe-only --slot practice-2` with `--plan` is inert. Main-only `--execute` additionally requires NEW immutable campaign, current inputs and funded original limits.

### 3. Contracts
- `peer_review_output_budget` freezes schema `native_v3_peer_output_budget_v1`, limit_source, peer_max_output_tokens, blind_max_output_tokens and relation_max_output_tokens. Only six peers use the formal61440; author8192, blind2048, relation2048, high/attempt1/100s remain their distinct existing stage contracts. Do not substitute the TutorDecision16384 cap or physical model context capacity.
- Probe `execution_scope` schema `native_v3_single_slot_probe_v1` fixes one slot and false pack/anchor eligibility. Plan physically contains one allocated row/case, max8 calls, zero reserved relation calls, relation_anchor_purpose=null. Its publication status is `published_internal_single_slot_probe_not_ready_pack`; no relation anchor checkpoint. The existing pack helper rejects that status/eligibility; no full pack or consumer authority is issued.
- Default full five-slot plans retain44 calls and4 distinct relation calls. New resource arithmetic is author output + blind output +6 peer outputs, plus separate relation output only in full campaigns. A61440 probe therefore preallocates378880 output tokens, not eight times the peer cap and not the smaller legacy22528.
- Probes reuse original active canonical roots/global limits/windows; they do not initialize or replace a missing period/window. Normal owners must separately provide any later legitimate period after old ones expire. Active cap/usage/history/UNKNOWN remains immutable; no overlapping-limit workaround, invented occupied-slot files or implicit coverage reuse.

### 4. Validation / error matrix
| Condition | Outcome |
| --- | --- |
| Cap not legacy2048/formal61440, partial/extra marker, production cap with legacy protocol | Reject before external/DB/preparation IO |
| Runtime provider/model/output setting disagrees with frozen production marker | PRODUCTION_PEER_OUTPUT_SETTING_MISMATCH / PROVIDER_MISMATCH; no funded dispatch |
| Mutated limits/allocations/scope/selected slot or extra frozen case | Canonical plan/state rejection before execution |
| Old campaign relabeled as probe or given a larger cap | Immutable plan/case/accounting conflict, no old re-review |
| Active original output remaining below378880 | EXISTING_GLOBAL_REMAINING_CAP_INSUFFICIENT_NO_RESET; no author dispatch/new window |
| Missing/partial original global or root window | Probe pending, no initialization/replacement |
| Probe internally publishes one item | Item-only status/false anchor; not2/2/1 pack, no relation reserve or Gate |

### 5. Good / base / bad cases
Good: a new explicit61440/high single-slot plan with matching runtime config and sufficient original resource reservations. Base: legacy/default2048 full plan/cases hash match the accepted e6d6192 snapshots. Bad: 8192 passed off as production, current output resource remaining mistaken for CNY balance, or old limits raised to force a probe.

### 6. Tests required
`test_native_review_budget_probe.py` and existing native plan/operator regressions verify exact per-port caps and totals, physical scope cardinality, inactive/underfunded noIO guards, frozen old-plan denial and configuration mismatches. Compare24 accepted pre-change plan snapshots and81 protected artifacts; current real expense event is append-only and separate from code edits. Actual whole-role production review requires new main-owned funded receipts; a passing fake suite or blocked PG preflight does not establish model quality/publication/E.

### 7. Wrong vs correct
Wrong: raise an active120832 output resource cap to cover a new61440-per-role plan or silently reduce the peers to fit. Correct: freeze the user's formal61440 choice, preallocate the complete378880 probe output bound against all original limits, and return pending before author IO when underfunded. Existing metadata/partial checkpoints and original source/owner/lease/replay fences remain unchanged.

## 2026-10-09 bounded dispute deliberation and unified production output

### 1. Scope / trigger
The original design requires first peer-blind review, evidence-led investigation,
revision and independent recheck. `review_deliberation.py` now supplies an explicit
executable internal core; `SharedReviewPipeline.prepare_review_followup` supplies
the original-result private plan seam. Neither is a concrete native investigation,
shared revision-lineage or historical-blocker discharge issuer. Actual multi-round
provider/DB publication remains pending until those original owners are installed.
The user's later instruction sets NEW author, blind and six-peer output caps to
the formal production limit and stops further tests. Do not claim this latest cap
patch has passed runtime verification.

### 2. Signatures
- `prepare_review_deliberation(*, source, validation, bundle, lease, budget_root_id, resource_ceiling) -> ReviewDeliberationPlanV1` verifies the complete first bundle and binds immutable disputes to the original source/profile/lease/root.
- `ReviewDeliberation.execute(plan, *, owner, clock) -> ReviewDeliberationResultV1` composes investigate, revise, deterministic validate and fresh blind/six-role review through explicit `ReviewDeliberationOwner` ports; missing ports remain pending.
- `SharedReviewPipeline.prepare_review_followup(p, result) -> ReviewDeliberationPlanV1` checks original issued/result identity, source/lease/scorer and settlement, and reads original active budget caps. It performs owner DB reads/fences, but NO provider/runner calls, reservations or checkpoints. Caps are passive ceilings, not remaining allowance or a dispatch capability.
- `build_plan(..., production_output_limits=False)` keeps historical Python API reconstruction exact. New CLI defaults select production/evidenced output; `selected_author_output_cap(plan)`, `selected_blind_output_cap(plan)` and `selected_peer_output_cap(plan)` resolve each actual stage limit. `review_ports(..., blind_max_output_tokens=2048)` keeps historical reconstruction explicit; new execution supplies the selected production blind cap.

### 3. Contracts
- Private versioned deliberation plan/result always have `publication_enabled=false` and `admission_eligible=false`. Exact role/report/run/finding identities and field references are retained; original bundles are not overwritten or merged into majority votes.
- Investigation is a separate bounded-live-dispute schema, not retrospective `ReviewDiagnosticInputV1` or a new admission vote. The original owner must verify current source/lease/root, reserve, recheck and verify issued results for every operation; usage is retained conservatively UNKNOWN.
- Round ceilings come from the existing frozen discussion/revision/investigation profile and cumulative original resource limits. Parent/stage/lease deadlines are never extended. No hardcoded two-round default, unreserved retries, or caller-created budget root.
- Revisions need new candidate/version/content/source bindings AND a substantive content fingerprint that excludes identity/version-only changes. Re-run deterministic validation, blind solve and all six roles; reject old run reuse. Recheck receives only neutral test categories/field locations, not peer votes/prose or the previous blind answer. Evidence-only changes without a new verifiable review input remain pending.
- New `production_output_budget` uses schema `native_v3_production_output_budget_v1`, production limit_source, author/blind/peer caps from `DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS` (currently61440), relation cap2048. It cannot coexist with the old peer-only marker. Runtime Flash configuration and `Settings.tutor_max_output_tokens` must match before new dispatch.
- New single-slot output reservation is `8*61440=491520`; full five-slot plus four relation calls is `5*491520+4*2048=2465792`. Remaining/root calculations and actual generation/solver/reviewer parameters use the same selected caps. These are reservation ceilings, NOT consumed tokens or monetary cost. Old plans/windows/UNKNOWN are not rewritten; no production marker means no NEW author candidate in the live entry point.

### 4. Validation / error matrix
| Condition | Required boundary |
| --- | --- |
| No material dispute | Early admission-pending return, no extra operation |
| Missing native owner, zero original investigation/revision cap, expired deadline | Pending before added IO; no window reset |
| Incomplete/foreign/tampered first bundle or result | Reject private followup/plan |
| Identity-only revision, old run, wrong source/profile/policy/runtime | No valid new independent recheck |
| New evidence but no new review input | Pending, not same-input review-to-green |
| New independent bundle has no material findings | Still original admission/discharge owner pending, never automatic publication |
| Mixed output markers, wrong cap/provider/actual Settings | Reject before funded dispatch |
| Existing frozen campaign differs from new production plan | Immutable conflict; do not migrate or rerun |

### 5. Good / base / bad cases
Good: current complete bundle -> exact private dispute plan -> separately funded
original-owner investigation -> substantively new revision -> independent recheck,
with old evidence retained. Base: no native owner or no original allowance yields
pending; historical output plans reconstruct unchanged. Bad: change only item IDs,
vote away a blocker, use a plan DTO as authority, run a new round inside the old
seven-call reservation, or raise an active window cap to fit491520.

### 6. Verification boundary
Before the user's stop-testing instruction, the implementation agent ran the new
fake-owner suite (30 passed) and app Mypy (452 files); these are offline core
evidence, not live ownership/publication evidence. The later unified-output patch
and static formatting corrections receive static review ONLY: no additional
pytest/Ruff/Mypy/CLI/provider/PG runs. Existing test files are retained; no new
test matrix or real acceptance is claimed.

### 7. Wrong vs correct
Wrong: the multi-round core exists, so historical quarantine is cleared and real
production deliberation is complete. Correct: the private core/plan seam is an
implemented milestone; native investigation receipts, revision lineage, blocker
discharge and independently prepared real rounds remain separate pending owners.

## 2026-10-09 native single-investigation owner (508 staged, not installed)

### 1. Scope / trigger
The next roadmap increment implements a concrete default-off investigation owner,
not just a callback protocol. It consumes an original persisted complete public
shared review, separately reserves one bounded analysis, and writes immutable
shared-confidential audit. It does not implement shared revision lineage, historical
blocker discharge or the complete native multi-round/republication flow.

### 2. Signatures
- `NativeReviewInvestigationOwner(review: SharedReviewPipeline, *, enabled=False)` shares the original review connection, runtime and budget owners.
- `prepare(*, original, result, lease, review_receipt_id) -> PreparedNativeReviewInvestigation | None`, `run(prepared) -> NativeReviewInvestigationRun`, `settle(prepared, result) -> None`, `persist(prepared, result) -> UUID` require distinct short prepare/settlement/persist transactions; provider IO requires IDLE.
- `SharedReviewPipeline.prepare_investigation(p, result, *, owner, lease, review_receipt_id)` accepts only the concrete owner bound to that exact pipeline/connection. It is never called by default `run_review` or a public route/worker/operator.
- `NativeReviewInvestigator` uses the existing bounded client and production constant; `native_shared_review_investigation_output_v1` joins the explicit enabled/high schema allowlist only. Historical schemas/client defaults remain unchanged.

### 3. Contracts
- Validate original process-issued prepared/result identity, exact source/artifact/validation/policy/profile, already committed original blind plus six-role bundle and UNKNOWN review settlement. Reconstruct neither capability from JSON.
- Original `SharedReview.commit_review` deliberately leaves the reviewing checkpoint incomplete while coverage/final facts are pending. Investigation may run within that legal reviewing stage after full persisted review, or a legitimately reached investigating stage; never invent a completed checkpoint. Frozen discussion rounds must permit a post-first round; cap-zero/insufficient original budget remains pending.
- Any existing final admission facts/evaluation or publication history blocks a new investigation of that artifact. A historical failure cannot be revived with another key/lease/candidate label. Continuation binds the original generation artifact to the current review via the existing original-stage/continuation owner, not a false artifact-job equality.
- Preparation binds a fixed artifact/review-receipt reservation key; reserve only original cumulative root/global limits with one request, measured conservative input bytes, output61440 and investigation_rounds1. REPLAY does not mint a new prepared/dispatch capability.
- Provider projection is current review/source fields, exact leaf index and concrete disputes. Do not send complete bundle, prior blind answer/score, lease, budget ledger or reasoning. Analyses `supported|contested|insufficient_evidence` are MODEL CLAIMS, not truth or blocker discharge; require exact all-dispute coverage, unique keys and scalar-leaf field references matching the actual input. The new index is independently bounded/deterministic and leaves old review indices/hashes unchanged; an original container reference permits only actual scalar descendants, not a container or unrelated node.
- Actual timeout is narrowed immediately before IO to remaining lease/source/parent/stage deadline. Check source/lease/root/model/resources/sealed prepared before and after IO. Payload/hash/report checks retain the original `finite_review_context`, including Python scoring descriptors.
- Success and failure retain UNKNOWN usage and null cost; partial normalized usage is not aggregate attestation. Persist requires the original issued result, a separately committed matching UNKNOWN settlement, current source/lease and exact payload/hash. A failed run remains an immutable pending receipt, not a successful analysis: a post-provider fence failure clears the report and retains only safe pending observation; SQL closure/type/text/reference checks must reject missing fields under NULL semantics and require report=null for failure reasons.
- SQL508 adds only `tutor_item_supply_shared_review_investigation_preparations` and `..._receipts`: root/job/artifact/review/reservation references, receipt-to-preparation composite FK and settlement reference, generated snapshot hashes, payload bounds, current lease/source/profile/independent resource/settlement guards, unique preparations and UPDATE/DELETE immutability. Classify both as shared confidential; no learner owner/private source, export or reset hooks.

### 4. Validation / error matrix
| Condition | Required boundary |
| --- | --- |
| Disabled flags/owner, missing schema, missing original complete committed review | No valid paid dispatch |
| Old final/quarantine/publication history or foreign root/lease/source/profile | Reject, preserve history |
| Original profile permits only first round or investigation resource cap0 | Pending; no quota/window change |
| Replayed reservation/preparation or JSON copy of process-issued object | No new dispatch capability |
| DB transaction open, source/lease/deadline expires, input over bound | Reject before provider; retain conservative accounting where already reserved |
| Malformed/incomplete output, wrong keys/references/run/input identity | Pending safe observation; no valid analysis authority |
| Missing/uncommitted/wrong settlement or mutated persisted payload | Reject write/conflict, no overwrite |
| Analysis says supported or contested | Old blocker remains until separate real discharge/revision/recheck owner |

### 5. Good / base / bad cases
Good: separately committed full original review -> current same-root investigation
reserve -> one bounded high call at IDLE -> committed UNKNOWN -> immutable pending
analysis receipt. Base: old campaign profile1/cap0 or uninstalled508 stays pending.
Bad: fake reviewing completion, revive a quarantined version, consume another
user's private material, reuse old seven-call reservation, or treat model disagreement
as permission to publish.

### 6. Verification boundary
User's stop-testing instruction remains active: this increment receives static code
review only. No new/modified tests, pytest/Ruff/Mypy/compile/CLI/PG/provider/Docker
run; SQL508 is registered/staged, NOT installed or DDL/data validated. The earlier
30 fake-owner core tests do not attest this new native owner or migration. Explicit
native installation/real receipts and the remaining multi-round stages are unverified.

### 7. Wrong vs correct
Wrong: registered508 plus a concrete owner proves production investigation and
full debate passed. Correct: these are source-code/SQL contracts with default-off
explicit entry; installation and real invocation did not happen, and revision
lineage, blocker discharge, independently prepared recheck and P7/P8-P10/E remain.

## Native same-root revision/context lineage (509 staged, not installed)

### 1. Scope / trigger
The next original-roadmap increment binds a genuinely issued, committed native investigation to a new same-root child author operation. It adds concrete revision preparation, supplemental author input, original-writer generation and immutable parent-child lineage; it does NOT supply historical blocker discharge, complete independent re-review or publication authority. Stop-testing remains in force; registered SQL is not an installed/validated database.

### 2. Signatures
- `NativeRevisionOwner(investigation_owner, generation, *, enabled=False)` requires the concrete investigation and SharedGeneration owners on the same connection.
- `prepare(*, investigation, result, investigation_receipt_id) -> PreparedNativeRevision | None` verifies original process-issued/current evidence, creates and precisely claims the child through the original runtime.
- `prepare_author(p, *, provider)`, `run(p, gen)`, `settle(p, gen, result)`, `commit_generation(p, gen, result)` compose original SharedGeneration prepare/run/settle/commit; never forge original prepared state or write another owner's private registry.
- `persist_lineage(p, gen, result, *, lease) -> UUID` uses a legitimately refreshed child lease after original generation commit.
- `NativeRevisionContextV1` (`native_revision_author_context_v1`) and `NativeRevisionAuthorInputBindingV1` (`native_revision_author_input_binding_v1`) bind the supplemental context, request, actual messages/envelope/schema and measured input bytes.

### 3. Contracts
- Original issued investigation/result, already committed successful508 receipt and matching UNKNOWN settlement, current public source/root/lease/profile/model and non-terminal history are required. JSON is DATA, not a dispatch capability; one original investigation fixes at most one preparation/child, replay does not mint another.
- Child uses the original registered profile/target/coverage/runtime/scorer/purpose/risk/source contract and `enqueue(parent_job_id=...)`. Root never resets; ancestor/source/child lease/stage deadlines intersect. If claim chooses another job, raise and rollback the caller transaction, not silently retain its lease.
- Base `GenerationRequestV2`, `ProviderReceiptV2`, base author prompt/version and ordinary default bytes remain. Explicit revision authoring adds a separately versioned supplemental context containing original artifact/review/investigation identities and concrete problem list. Actual message/envelope trace is recorded; the whole extended envelope counts against the existing input-byte limit. Do not silently inject a second unbudgeted prompt through a provider proxy.
- Source-public/shared-confidential generated parent content may support repair; learner-private data and service-only hidden oracle contents are not new author inputs. Factory public-template/mandatory core rules remain intact: a requested unsupported core/spec change stays pending, not weakened to fit a model vote.
- Marked revision children cannot use the ordinary generation route without the exact frozen owner/context. Original prepare/reservation recheck/run/settle/commit all include real request1, input ceiling, output61440, candidate1 and revision_round1. Old nonrevision resource plans stay exact; known settlement cannot incorrectly refund the revision round, and missing usage stays UNKNOWN.
- Input trace, original issued result, new candidate/item/version/source/content identity and substantive fingerprint must match before original-writer storage/lineage. Changing only identity/version/title/metadata is not substantive repair. Context expiration or post-call source/lease failure cannot leave a successful usable source.
- SQL509 preparations bind root/parent-child jobs/original artifact/committed508 investigation/new candidate/request/context/deadline; lineage binds preparation/new artifact/author reservation/settlement and actual input trace. Generated snapshot hashes, size/schema/closure/type constraints and immutable guards retain old history. Static review requires the preparation parent artifact/substantive fingerprints to match the actual row, the COMPLETE resource object (not selected dimensions) to match the author ceiling, JSON numeric output61440, and public template equivalence apart from new item/version. Lineage root/parent/child/current public lease/profile and author trace closure/input_bytes numeric type must match the actual records.
- Parent-child lineage is data only: publication_enabled=false, blockers_discharged=false and no eligible authority. Until the separate discharge/independent-recheck owners exist, revision descendants fail closed at original facts and SQL admission/publication paths. Old nonrevision paths are unchanged.

### 4. Validation / error matrix
| Condition | Required boundary |
| --- | --- |
| Disabled owner, missing508/509, foreign/copied issuer data, absent committed analysis | No new author capability |
| Final/quarantined/published parent, source expiry, old profile1/cap0 | Pending/reject; no resurrection or resource-window reset |
| Claim returns a different root job | Raise rollback-required; do not steal a lease |
| Missing/mutated supplemental context or actual envelope exceeds original input bound | No valid revision author dispatch |
| Ordinary generation tries a marked revision child | Reject missing frozen owner/context |
| New generation differs only by identities/title/version | No verified repair lineage |
| Wrong root/target/runtime/scorer/profile/policy/resource/settlement or stale trace | Reject sidecar/storage, retain accounting |
| Lineage exists but no historical discharge/new full re-review | No final facts/admission/publication |

### 5. Good / base / bad cases
Good: current committed investigation -> same-root bounded child/context -> original separately funded author -> committed new real artifact -> immutable lineage, with independent validation/review still pending. Base: old profile/cap or staged-uninstalled schema prevents dispatch. Bad: generate a normal new item then label it repaired, refund revision_round1 through generic settlement, change factory core/goal to remove a blocker, or publish a latest green bundle while forgetting old findings.

### 6. Verification boundary
This increment has static review only: no new/modified test logic, pytest/Ruff/Mypy/compile/CLI/DDL/provider/PG/Docker/network runs.508/509 are registered/staged, not installed or data-path validated; earlier core test counts do not attest native revision. No successful paid repair, whole multi-round loop or P7/P8-P10/E is claimed.

### 7. Wrong vs correct
Wrong: a new item/version/hash or lineage row proves the defect is solved. Correct: real supplemental author input and substantive content change establish repair provenance only; historical blockers need separately verified discharge evidence and a new complete independent validation/blind/six-role review before the original admission owner may act.

## Native revision independent recheck and clause evidence (510 staged, not installed)

### 1. Scope / trigger
Explicit next-round recheck of a genuinely issued new revision child. Compose the original validation and public-only blind/six-peer review owners; bind historical disputes to new evidence without treating changed content or green votes as semantic discharge. This is shared-confidential DATA, not an admission/publication adapter. User stop-testing remains active.

### 2. Signatures / owner boundary
The concrete recheck owner must retain the same-connection original revision, validation and review producers, original process-issued preparation/result and committed509 lineage. Its explicit prepare/IDLE run/settle/commit stages invoke original pipelines; no JSON-restored dispatch, caller-supplied verification callback, hidden provider proxy or automatic API/worker route.510 follows509 in the existing single manifest.

- `NativeRevisionRecheckOwner(revision_owner, validation, review, *, enabled=False)` retains the concrete original owners.
- `prepare(*, revision, author, author_result, lease) -> PreparedNativeRevisionRecheck | None` binds committed lineage/current child and original history.
- `prepare_validation(..., lease, runner=None)` / `run_validation` / `settle_validation` / `commit_validation` compose the existing validation writer. After its checkpoint, caller supplies the refreshed current child lease.
- `prepare_review(..., lease)` / `run_review` / `settle_review` / `commit_review` compose new independent blind and six-role ports through the original review pipeline.
- `persist_dispute_evidence(..., lease) -> UUID` appends committed original evidence links. `NativeRevisionDisputeEvidenceV1` records `check_supported | unsupported | unresolved`, but always `historical_finding_resolved=false`.

### 3. Contracts
- Exact same canonical root/child candidate/source/content/target/purpose/runtime/scorer/risk/policy/registered frozen profile and original source grants. Deadline intersects ancestor, source retention, current child lease and frozen stage limit. Old profile1/cap0 is not upgraded.
- Validation uses actual original static or sandbox owner; independent new blind is public-only, and all six peers retain the original allowed NEW source/private-rubric/validation/scoring input contract. Parent opinions, investigation prose, old blind answer and the repair author context stay out of those provider inputs.
- Recheck creates original exact-class JSON solver/reviewer ports, not subclasses rejected by the existing entrance. Only the closed `_RecheckClient` alongside the original bounded client may narrow deadlines; it does not alter messages/schema/one-HTTP/high configuration or accept arbitrary proxy callbacks. Recompute remaining timeout at the actual HTTP boundary, and intersect ambiguity/scorer/validation runner/fence deadlines with the same original ancestor/source bound. Ordinary paths omit this extension.
- Post-IO source/lease/deadline failure removes usable validation/full review bundle, retaining partial reports/observation and conservative accounting. Original lineage reuse also denies parent/child publication-terminal history.510 requires the complete new-material-dispute projection, state/reason/typed closure and actual finite-property hash; a newly repeated blocker cannot be silently excluded to create check_supported.
- New validation/review use their own existing reservations and conservative UNKNOWN settlements. Blind and each peer use formal61440 output limits; no extra replay dispatch, old reservation borrowing, round-reset or invented money remaining.
- Historical dispute list is exact and complete, server-side only. Each entry binds original report/finding/hash/references and new candidate/source/content plus actual validation/blind/review evidence. Preserve unresolved and unsupported clauses; do not omit inconvenient findings.
- Concrete issuer verification proves the new evidence provenance, not necessarily that a historical claim is false. Any supported narrow deterministic check must state its actual semantic scope; generic rubric/curriculum/difficulty/security/adversarial discharge requires a real clause-specific adapter. A model assertion, source hash difference or unanimous new approval is insufficient.
- `finite_kc_unique_truth_v1` is a narrowly supported finite-static property check, not proof that arbitrary ambiguity/rubric prose or every previous uniqueness allegation was resolved. Its issuer evidence hash must derive from current original validation/static scoring facts; execution targets and other semantic claims remain unsupported without their own adapter.
- Process-issued previous-stage seals and committed immutable receipts remain required after a legal checkpoint advances the lease. Recheck current child/source/profile with the CURRENT lease; do not pretend the old generating/validating lease is still current, or omit original issuer verification to avoid a stale-stage error.
- Immutable510 records stay publication_enabled=false, blockers_discharged=false and admission_eligible=false.509 revision admission/publication hold remains unchanged. Full discharge, coverage, high-risk adapters/second genuinely independent bundle and original final facts/publication owner are separate future gates.

### 4. Validation / error matrix
| Condition | Required boundary |
| --- | --- |
| Missing original owner, committed lineage/schema or current source/lease | No new recheck capability |
| Copied prepared/result or stored JSON replay | Reject; no new provider/runner allowance |
| Stage advanced legally | Verify original seals/receipts plus current child lease, never revive the old lease |
| Parent/previous provider run-ID reused, or peer/old-blind payload leaked | Reject evidence independence |
| Frozen resource/deadline exhausted | Pending/deny; no budget/profile/window reset |
| Latest blind/six roles pass but old clause lacks concrete adapter | Preserve unresolved/unsupported, no historical discharge |
| Forged clause list, mismatched receipt/root/candidate/hash or wrong settlement | Reject sidecar evidence |
|510 receipt exists | Data only;509 admission/publication hold remains |

### 5. Good / base / bad cases
Good: committed original revision lineage -> actual new candidate validation -> fresh independent blind/six-role review -> complete immutable per-dispute evidence links, with missing semantic checks still pending. Base: disabled flags or uninstalled510 makes the explicit owner unavailable. Bad: drop a parent's ambiguity finding because the new bundle is green, equate recomputed hashes with correctness, resurrect a stale lease or mint final facts from a sidecar row.

### 6. Verification boundary
Implementation plus independent static source review only. No new/modified tests or pytest/Ruff/Mypy/compile/import/CLI/SQL/DDL/provider/PG/Docker/network execution;508/509/510 installation and live behavior are not established. Prior test counts are not this increment's evidence. Full multi-round discharge/admission, complete pack, P8–P10/E remain incomplete.

Future verification, only if separately authorized, must assert original issuer identity after checkpoint advancement, independently committed exact receipt closure, no ancestral run reuse, no historical prompt contamination, complete per-dispute retention, unsupported semantic claims staying unresolved, current source/deadline and exact resource/UNKNOWN bindings, and unchanged509 admission/publication denial. These are acceptance points, not tests performed or added in this increment.

### 7. Wrong vs correct
Wrong: fresh unanimous reviews prove every historical blocker was repaired. Correct: record exactly which original issue is linked to which independently issued new evidence, retain unsupported semantics as pending, and keep original admission/publication gates closed until a real clause-specific discharge owner can verify all required obligations.

## 2026-10-10 original isolated live acceptance (execution authorized)

### 1. Scope / trigger
Latest human selects the original local isolated sequence, with configured real-model count/cost unlimited and real-chain-first acceptance replacing the blanket no-real-IO interpretation. Do not add test files or replay old automated suites. Main owns real PG/provider/source/credential operations; implementation/check agents edit and statically inspect bounded harness/fixes.

### 2. Signatures / artifacts
- Main-only `research/native-multi-round-live-20261010.py` live harness: default planning is inert; explicit execute uses original same-process generation/validation/review/investigation/revision/recheck producers. It does not call the previous publishing/quarantining slot operator.
- CLI: `--plan --seed 21`; actual main invocation `--execute --seed 21 --run-name <unique-name> --main-only-ack live-chain-execution-20261010`. Max17 provider method invocations,2candidates, requests17/input4194304/output1044480, root token5238784. Parent/lease3600s, period7200s, per-request100s, discussion2/revision1/investigation1; these are frozen new-operation values, not modifications of an old profile.
- Distinguish observed original method entry/return from actual HTTP attempt counts and costs; only original receipts/settlements grant accounting authority. A once intent is retained on failure. A genuinely repaired new operation needs an explicit versioned server intent/current budget, not deleting the old intent or restoring JSON seals.
- Exact DB `aearn_b1d_sandbox_20261001`, existing original public source composition, `.runtime/native-multi-round-live-20261010/<unique-run>` private immutable receipts; safe console status/IDs/hashes only.
-508–510 now installed there: selected real DDL replay/rollback restoration/atomic installation evidence in `schema-b0ef4123985d/result.json`;292 original table rows and all old functions preserved, six empty tables added. First51042601 failure remains `schema-05bafe7bf7ed/result.json`. Future SQL repairs append new migrations, not modify installed fragments.

### 3. Contracts
- Source authorization is current per stage, not cached preflight permission. Lease/profile/model/target/policy/runtime/scorer/root and before/after IO fences use original producers; serialized files do not restore capabilities.
- New normal resource periods may initialize through original owner only when matching active periods do not already exist. Reuse all current limits and calculate genuine remaining amounts; do not replace active caps, shift the canonical obligation or clear anonymous/UNKNOWN usage. New profiles may fund bounded investigation/revision/independent recheck, old profile1/cap0 and old failures remain unchanged.
- Formal61440 author/blind/peer limits/high reasoning and separate original reservations/settlements. Unlimited currency authorization is not infinite per-operation retries/deadlines or auto-topup. Record known usage, unknown monetary cost and partial failures separately.
- Commit preparation before IDLE actual IO, independently settle and commit immutable stage data. Refresh the legal current lease after checkpoints; preserve all original issuer objects for later owners.
- Only a genuinely complete new first review with material disputes enters investigation/revision. Green, transport-failed or incomplete bundle means the branch is not exercised/pending, not a reason to manufacture findings or reroll votes. Never resurrect a terminal old quarantine or label new assertions as discharged.
- No final facts/publish/Attempt/Gate/mastery;509 hold remains and510 is partial DATA. Any code fix follows independent static review; do not regenerate/re-review an unchanged candidate merely to change a verdict.

### 4. Validation / error matrix
| Condition | Real acceptance behavior |
| --- | --- |
| Inert/default plan | Zero PG/provider/GET/credential IO |
| Different database or absent source/credential/schema | Explicit pending/reject before model dispatch |
| Existing matching current limits insufficient | Deny, not new overlapping period/root |
| No material dispute / incomplete blind or peer bundle | Retain actual evidence, do not claim revision branch passed |
| Duplicate dispatch, copied prepared or stale source/lease | Reject before new external request/effect |
| Post-IO fence or receipt insert fails | No usable success; retain actual call/usage/UNKNOWN and private failure |
| Partial clause proof / latest-green opinions | No historical discharge or509hold removal |

### 5. Good / base / bad cases
Good: real fresh KC uses current source and proper new normal periods on the original root, then original producers persist new stage evidence; a genuinely needed substantive child gets its own full validation/independent review. Base: actual first bundle green leaves the dispute branch unexercised. Bad: switch to an ordinary learner DB, remove the DB guard, forge old process-issued objects from JSON, select a different canonical scope to evade accounting, or reroll until all opinions approve.

### 6. Acceptance points, not an automated-suite requirement
Use actual private request/receipt/DB evidence and limited negative/rollback checks for duplicate/stale/ancestral-run/post-fence/unsupported-clause boundaries. Main has already established selected508–510 DDL compile/replay/rollback preservation/install and source/settings preflight; populated native data path and real model outcomes must be recorded separately. No historical test counts substitute for those results.

### 7. Wrong vs correct
Wrong: empty new tables or a responding model proves the complete multi-round/admission system. Correct: report actual reached stages and concrete receipt persistence; unexercised branches, unsupported semantic blockers and original admission/publication still remain explicit.

Actual first-sample evidence: `kc-real-20261010-1` author/validation/blind/six peers completed; blind passed, six roles high/61440 approved with0material disputes, exact PG full-bundle readback and one validation/blind/review receipt each. Eight completed provider responses observed total207881tokens; HTTP attempts and currency remainunattested/UNKNOWN, original P3 review settlement staysUNKNOWN. Four critical negative boundaries (prepare replay/copied prepared/second dispatch/genuine old expired lease) denied with0additionalprovider. Investigation/revision/recheck/510 data branch remains unexercised, not passed; no forced findings, publish or hold removal. Main expense append preserves139old events and other fields. No new test files/old suite; detailed evidence in task research/live-chain-progress-20261010.md.

### 8. Independent executable continuation and prospective wire repair
- Fixed explicit V2 targets/seeds SQL22/Python23, original pinned P6 image/runner. Inert KC V1 output must remain identical to accepted snapshot. A bounded normal campaign carries34requests/4candidates/3600execution_seconds, each original target root17/2/1800. No partial/active old period replacement; existing adequate globals may fund a missing nonoverlapping root window through the original owner. Seed/run/root changes never evade target once intents.
- Actual2026-10-10: wait original KC period natural expiry13:22:05, recheck actual DB0active windows/globals before new owner period. Both executable validation/blind succeeded; SQL15/Python9live validation terminals. Each has2approved partial roles but technical rejection, complete bundle/reviewreceipt absent. SQL phase=evidence_verification/technical/schema_validation; Python samephase/role/evidence_verification. Nonempty failure observations and known response usage coexist with original UNKNOWN review settlements; coarse safe_reason is not the fine failure code.
- Ten completed observed responses total325490tokens, actual HTTP count/CNY remainnull; append2expense events preserving140old ones/other fields. Old14table row families unchanged,4canonical roots retained. No508–510 data branch/finalfacts/evaluations/publications, no old-candidate replay or received-opinion relabeling.
- Prospective sender correction must align generated evidenced safe_code wire enum with trusted ROLE_CODES[role] and explain original required reference groups/prefixes. Never broaden role/code/ref/severity receiver gates to accept raw outputs. Wire revision and actual schema/prompt sizing must be explicit; preserve payload DTO/default/hash algorithms and frozen previous inputs/receipts. Prompt/schema correctness does not prove semantic blocker discharge or future real acceptance. See task research/live-executable-wire-repair-20261010.md and diagnosis/progress.
- Sender-only role_refs_wire_v2 correction is implemented and independently statically checked. Main actual schema/reference-catalogue DATA check succeeded with0externalIO; full frozen JSON envelope projection failed strict typed-tree framing and was stopped without compatibility loosening/capability restoration. Actual full-envelope pricing/legacy-blind runtime byte equality/supplier acceptance/new substantive candidate validation remain pending; static unchanged paths are not those live proofs.

## 2026-10-10 controlled experiment and ONE unspent setup recovery

### 1. Scope / trigger
Explicit user-approved ONE controlled KC group only, not normal item acceptance. Initial fixedseed24 private re-binding explanation is intentionally false; default API/worker/publication remainoff. Original real author/validation/blind/six/native downstream owners remain authority. Deployed508–512immutable; any subsequent SQL repair appends.

### 2. Signatures
- `SharedGenerationPipeline(..., controlled_counterexample_enabled=False)`; `prepare_controlled_counterexample(...)`, `prepare_generation(...,controlled_context=issued_preparation)`, `persist_controlled_counterexample_author(...)` use original issuer/actual source/profiles.
- CLI `native-controlled-live-20261010.py --execute --run-name <unique> --main-only-ack controlled-branch-authorization-20261010`; default `--plan` inert.
- ONE pre-author recovery: `--execute --recover-unspent-setup --run-name <unique> --main-only-ack controlled-pre-author-recovery-20261010`; `ItemSupplyRuntimeRepository.recover_controlled_unspent_setup(...,enabled=False)` uses original cancel/register/enqueue/claim under actual DB locks.
-511preparations/receipts immutable shared-confidential,512 `item_supply_internal.enforce_controlled_counterexample_insert()` root repair, `controlled_counterexample_held(jobuuid)` DENY-only ancestor query and no-admission trigger.

### 3. Contracts
Fixedclosed price6→price8 wrong initial explanation in actualSYSTEM/user/schema text and byte/trace; provider transportbaseSource schema unchanged. Returned model fields onlychecked, neverrewritten. Original senderrole_refs_wire_v2/high/61440 retained; native child does not inheritwrongconst. Hold nevermints source/receipt/grade authority. Two source materials originalsameconnection current; cloned/unissuedcontrol/prepared rejected.
Group17requests/2candidates/input4194304/output1044480/3600parent/7200period/0KCexecution (SQLplaceholder1), existingcanonicalroot. Recovery locator/once rawprior-intentSHA+prior-result-hash are DATA only: actualDB must show owned leased generating job and0reservations/artifacts/marker/trace/policy/receipt/settlement/checkpoint. Originalowner cancels onlyunspentsetup with audit; freshnewjob/profile/lease samecase/candidate/root uses exactstillunusedglobal/rootwindow with fulltime/remaining, no olddeadlines/caps/profile rewrite or sealrestore. AnyUNKNOWN/spend/receivedoutput blocks recovery.

### 4. Validation/error matrix
| Condition | Behavior |
| --- | --- |
| Feature/default or ack absent | Inert/deny,0provider |
| Initial literal absent in actual output | Fail retained, no returned-payload mutation |
| Currentsource/lease/time/profile mismatch or partial/usedperiod | Deny without replacement/reset |
| Copied issued control/prepared | Local originalissuer identity rejection; not a global replay proof |
| Blindscorefalse | Retain full actualbundle if completed, CONTROLLED_BLIND_FAILED_STOP_NO_RETRY; no508–510 |
| Accepted complete disputed bundle AND required blind condition | Native investigation/revision/recheck through sameprocess original objects only |
| Held parent/descendant requestedfacts/evaluation/pub | PersistentDENY; no latestgreen override |
| Missing root_id on physical jobcontrols | Root via actualshared_jobs join, not runtimejoin alias on%ROWTYPE |

### 5. Good/base/bad
Good: explicit intentionalcontentfault persisted beforefunding, realindependentpeers detect/record. Base: blindnegative stopsonegroup truthfully. Bad: synthesizeopinions or rehydrateJsonprepared to exercise508; relax gates/reviewuntilgreen; call experiment normalacceptance or resetrootbudget.

### 6. Acceptance points (no automated-suite mandate)
Actual:511DDL passed thenlazyinsert exposed42703 missingcontrolroot;512selectedrepair installed, originalrows/functions/triggers preserved. Exactlyoneunspentcase recovery reachedactualmarker/trace+author/machinevalidation/fullsixbundle (3majorblocking), blindfailed; native508–510positivepath unexercised.8originalowner completed-runlowerbound, HTTP/methodcountnull, knowninput/output164202/54404, otheraggregateusagepartial/UNKNOWN retained.3hold/immutability negatives0extraAPI: temporaryrollbackadmission/pub rowshapes executeactualinstalleddenyfunction23514, actualmarkerUPDATE23514/hashunchanged; not fullformaloperations or realdescendant. Currentproof_Projectionbinding/envelope/request/context/resulthashes matchesexactly; wholeouterreceipt vsprojection equality is not the comparison contract. No newtestfiles/oldmatrix orGit/publicactivation. Detailedtask controlled-branch-progress.

### 7. Wrong vs correct
Wrong: DDLcompile proveslazytriggerdatapath; control_row.root_id exists because runtimehelper joinsroot into anotherrow; 8completedowner runs means8HTTPattempts; threecritics imply508–510ran. Correct: checkphysical%ROWTYPE columns, exerciseactualinsert, append512afterdeployment; record8aslowerbound andunknown dimensionsnull; retainblindnegative andnativepositivegap. Observer-free blindresponse currently onlysolutionhash/scorereceipt, so exactsemantic/formatcause remainsunverified without rawanswer.

## 2026-10-10 prospective private blind diagnostics

### 1. Scope / trigger
Explicit internal forensic opt-in only. The old controlled answer was not retained and is not recoverable from its hash. This increment does not rerun it, revise its false score, authorize a second paid group, or complete native508–510 acceptance.

### 2. Signatures
- `SharedReviewPipeline(..., private_blind_audit_sink: PrivateBlindAuditSink | None = None)`.
- `private_blind_audit_status(original_prepared) -> dict[str, object] | None` rechecks the original issued object, returns no raw/expected answers.
- `blind_solve_candidate(..., private_audit: PrivateBlindAudit | None = None)`; finite scorer `score(..., private_audit=None)` leaves normal protocol/receipt unchanged.
- Research composition `execute_main(..., private_blind_forensics=False)` is explicit, controlled-only and not exposed as a switch in the old consumed CLI; default plan/hash/caps stay unchanged. It forwards the same private sink to parent/child original review owners.

### 3. Contracts
Private event schema `private_blind_diagnostic_event_v1`: event_kind run_started/answer_received/finite_static_evaluation/score_completed/failure; sequence, original operation locators, binding/source/request/run/solution hashes when available, bounded JSON-native details. Raw answer only `answer_received.details.raw_answer`, max48000characters, emitted after genuine run identity/input/profile/prompt/output binding verification and BEFORE original score. Unverified/malformed provider output is not captured as a verified raw answer.
Finite diagnostics retain actual original evaluation outcome/score/policy/feedback plus the current strip/casefold/split/join comparison and expected option privately. Reason is normalized_exact_match/mismatch, not a semantic root-cause claim; other scorers remain cause unavailable. Oversized normalized text is explicitly unavailable with a hash, never silently truncated. Public DTOs, prompt/wire constants, scoring algorithm, hashes and peer inputs are unchanged.
Sink is private DATA, not accounting/dispatch/admission authority. Core separates write acknowledgement/build failures from score outcome and suppresses exception prose. Disk sink max16events, full wrapper plus Journal indent/newline bounded to262144UTF8bytes before exclusive numbered write/flush/fsync; no raw data in status. Filenames are outside closed completed-run accounting routes.

### 4. Validation / error matrix
| Condition | Behavior |
| --- | --- |
| Sink absent | No new raw events/retention; original review result unchanged |
| Verified original result | Exact raw answer emitted before scoring |
| Provider/result-binding failure | Closed failure stage; no verified raw-answer claim |
| Original scoring exception after raw write | Earlier acknowledgement retained; original failure/usage semantics unchanged |
| Sink throws/build or byte limit fails | Safe independent audit gap, no score upgrade/downgrade or automatic retry |
| General scorer provides no reason | Actual score only, reason unavailable |
| Copied prepared used for status | Original issuer lookup rejects; log DATA cannot restore capability |
| Explicit research audit incomplete | Only after original settle/commit, preserve old blind-negative gate; stop experimental followup independently |

### 5. Good / base / bad
Good: original bound answer and genuine finite calculation go to private immutable journal. Base: malformed result/no reason/write failure remains unavailable. Bad: treat mismatch as semantic wrong, raw log as a scoring receipt, event count as HTTP count, or recover/review old candidate until green.

### 6. Acceptance assertions (no old-suite mandate)
Main five inert synthetic DATA checks passed: private exact roundtrip; oversized event before-write rejection; immutable filename collision with unchangedbytes; compact-inner80039bytes whose full pretty wrapper exceeds limit rejected beforecreate; Windows LF243333bytes/actualCRLF270346bytes boundary rejected beforecreate at262144cap. Full-file bound includes Journal newline=None OS conversion. They exercise the sink, not original blind/scorer/provider or actual child. Independent incremental static review and future real retention are separate labels; task progress records their current state. No testsfiles/old automatedsuite/new paid calls/SQL installation/Git cleanup from this increment.

### 7. Wrong vs correct
Wrong: bound compact inner JSON but claim full disk cap; missing old raw answer proves wrong format; leave logs in peer prompt to explain false score. Correct: match actual full Journal serialization before writing; explicitly retain historical cause gap; keep prospective raw/normalization private and preserve original score/settlement/holds.

## 2026-10-10 explicit second held counterexample group

### 1. Scope / trigger
Latest human execute approves ONE new substantive counterexample-family group, not replay of the prior diagnose/seed24 sample. Initial private rationale alone is intentionally false. User-controlled experiment remains permanently held from admission/publication even if revision/review later becomes green. Real-chain-first with independent static review; no old-suite/newtests mandate.

### 2. Signatures
- `ControlledCounterexampleContextV2()` and exact V1|V2 `checked_controlled_context`; same nine context keys and unchanged outer preparation/author receipt versions.
- `JsonBlindSolverV2(..., blind_protocol="legacy-v2")`; explicit `"single-choice-id-v3"` uses prompt_version `item-supply-blind-single-choice-id-v3` and schema name `item_supply_blind_single_choice_id_v3`.
- `blind_input(...,blind_protocol=...)`, shared review captures actual issued solver expectation/seal; native child clones its protocol and caps. Legacy defaults/DTO/seal path preserved.
- `native-controlled-v2-live-20261010.py --execute --run-name <unique> --main-only-ack controlled-v2-execution-authorization-20261010`; default --plan inert. Composition v4 mandatory privateforensics/no setup recovery, distinct fixed-scope once.
-513 modifies only closed experiment CHECK and original insert guard; deployed508–513 immutable, repairs append514+.

### 3. Contracts
V2 target python-kc-binding-v1, counterexample family, practice-1/seed0. Actual original allocator produces family-counterexample blueprint; full `source=4/saved=source/source=9/print(source,saved)` program occurs in actual option label, not assumed prompt. Same nine keys schema_version/experiment_key/rule_version/target/slot/seed/wrong_explanation/publication_enabled/admission_eligible; V2 closedkey/rule and fixed wrongtext/program specified by latest authorization, rulehash recipe unchanged. Wrongconst is initial author's real SYSTEM/user/schema only; transport baseSource schema and returned payload unchanged, child revision does not inherit const.
Single-choice sender marker/interface/schema lists ALL public option IDs only, not correctkey. Exact caller-selected protocol binds input/envelope/config hashes for preparation, run, bundle, deliberation and verified evidence; input pricing and sending share same envelope. Configseal excludes dynamic remaining-time drift; each real call still narrows timeout. No answer extraction/scorer change/peer leakage/normal admission enablement. Six peers/investigator keep existing high behavior; blind retains its prior thinking behavior, not mislabeled high.
17request/2candidate/input4194304/output1044480,61440outputs,3600parent/lease/7200normalperiod and KCexecution0 (SQLpositive placeholders1) on same original canonicalroot; no oldwindow extension/reset/UNKNOWN erase. Sources/actual period/current original grants rechecked at execution. Logs are private DATA lowerbounds, not HTTP counters or reusable seals.

### 4. Validation / errors
| Condition | Behavior |
| --- | --- |
| Legacy/default path | Old prompt/DTO/hash/seal and admission defaults unchanged |
| Unknown protocol/version or non-single-choice KC | Deny, no fallback |
| Protocol/input/envelope/config changed afterprepare | Original seal rejects before dispatch |
| Old fixedonce or V2 recovery requested | Deny without JSON capability restoration |
| Active/partial prior global/root windows | No substitute period/reset; wait for true natural expiry |
| Returned controlled explanation/key/tests incorrect | Retain failure; no output rewrite/newcandidate retry |
| Incomplete bundle/blindfalse/no actualdisputes | Stop; no fabricated investigation |
| Private forensics incomplete | Independent experimental stop after original settle/commit and oldblindfalse gates |
| Held parent/descendant | Original deny-only facts/publication guards remain |

### 5. Good / base / bad
Good: genuinely different registered family/actual allocator and full original model chain. Base: negative/partial/no-dispute outcome stays negative/partial/unexercised. Bad: only rename candidate/seed, infer correct ID from fixture letter, reuse old context/once, or script peer verdicts to populate508–510.

### 6. Acceptance assertions
Prepaid independent incremental static check passed. Main actual513 selected rehearsal/replay/rollback/install preserved300oldtables/rows and all other functions/triggers/constraints, no newtable. Pure v4plan0IO and actual registered allocation/root READONLY checks passed; canonicalroot remained7d4b85ba-a0ec-4348-ac11-3401c6bded47. Real process now owns freshcurrent prepared objects; stage-specific acceptance and populated508–510 must be recorded from actual outputs, not these preflights. No publication/Gate/Git/parentfinal claim.

### 7. Wrong vs correct
Wrong: public getter supportingcounterexample makes oldpractice1helper use it automatically; known promptversion restores authority; completedDATA count provesHTTP attempts. Correct: original allocator explicitly constructs counterexample＋practice1, newsealed solver determines expectedprotocol, and retain count/usage coverage qualifications and original holds.

### Actual bounded V2 outcome and next investigation observability seam
Original author/validation/newblind/fullsix actually completed: wrong rationale preserved withcorrectchoice-3key, blindchoice-3passed and fourprivateevents bound to original run/score, sixreports7majorblocking. Original508preparation+investigationprovidercompletedresponse+pendingreceipt reached; report=None after evidence_verification exception, originalsafe_codeunknown_exception.509/510/childnotrun.5831oldrowinstances from300tables/4roots preserved; facts/admission/nativeproof/publication0 andparentholdtrue. Main8dedup acceptedowner runs lowerbound plus1 disjointcompletedfailedadapterresponse; knowninput192579/output85102, aggregatecached/reasoning/reportedtotal/CNYunknown, oldsettlementsUNKNOWN. Oneexpenseappend143→144, oldevents/otherfields preserved. Stageproofs task controlled-v2-progress; do not call this valid investigation→revision→recheck acceptance.
Known code seam: investigator strictoutputDTO/ProviderRun then reportconstruct/verify can raise ordinaryValueError. Prospective catch now passes existing safe_code=evidence_verification ONLY forthatphase ValueError excludingValidationError; ValidationError remains schema_validation andothersoriginalclassifier. Noexceptiontextparse/prompt/receiver/DTO/usage/seal/settlementchange, independentstaticpassed, noextraAPI. Oldfailedobservationnotreclassified; prepatchprovider snapshot timing is post-run, not pre-paid sourcepin.
Remaining gap: rejected parsedoutput/exactbadkey/pointer unavailable. Senderrisk is parentrefs containingcontainers versus investigationindex scalaronly; futureexplicitversion must require everyactualdisputekeyexactlyonce andcopyexactscalarpointer/hash withoriginalfindingregion overlap. Staticriskdoesnotproveoldfailurecause; do not relaxreceiver, fabricateoutput or repeatoldcase.

## 2026-10-10 explicit investigation scalar sender and private rejection diagnostics (514 staged only)

### 1. Scope / trigger
Prospective repair after the real V2 case returned a completed investigator response but no accepted report. Do not reconstruct the missing old parsed output, reclassify its unknown_exception, replay its once, or interpret static sender risk as its proven cause. No new paid group or SQL installation in this increment; parent/full E remains incomplete.

### 2. Signatures
`NativeReviewInvestigationOwner(review, *, enabled=False, protocol="legacy-v1", private_investigation_audit_sink=None)`; `private_audit_status(original_prepared)` requires the original issued p. Adapter accepts the same closed `InvestigationProtocol=Literal["legacy-v1","scalar-evidence-v2"]`; `ReportV1.verify_input(request, *, expected_protocol="legacy-v1")` preserves the default strict legacy contract. Pure `investigation_rejection_details(request_payload, output_payload)` returns bounded private DATA only. Research `build_investigation_owner(review, *, journal=None, protocol="legacy-v1")` constructs only, never dispatches/restores JSON; explicit journal construction inspects its runtime path.
SQL514 replaces only `item_supply_internal.enforce_shared_review_investigation_insert()` with a copy of508 plus a NULL-rejecting closed prompt-version predicate. Registered/staged does not mean installed; deployed508–513 remain immutable.

### 3. Contracts
Default SYSTEM/schema/user payload, V1 DTOs and hashes remain compatible. Explicit V2 prompt `native-shared-review-investigation-v2` retains output schema name `native_shared_review_investigation_output_v1` and61440/high original adapter settings; input cap262144 unchanged. Wire schema requires analyses exact current dispute count, original key enum, and scalar evidence-index pointer enum. SYSTEM requires exact pointer/value_hash pairs, unique reference pointers and at least one original reference region overlap; statuses/analysis remain independent model claims.
Original prepare freezes full canonical `{messages, output_schema, schema_name}` hash and protocol in process-private `_sender_seals`, separately from unchanged508 preparation/receipt JSON. `_issued`/fence/run/result bind original p, adapter/protocol/envelope/settings/resources; no JSON seal restoration. V2 guard reads actual installed function definition BEFORE budget reserve and refuses old-only guard. Definition check is a compatibility preflight, not admission authority; original DB guard and receiver remain required.
Private audit is default absent. Original parsed structured response is offered before strict DTO/report verification, scalar-only allowlisted shapes only: no HTTP body, standalone or nested reasoning object, exception prose, provider keys. Events bind original preparation/reservation/job/review/request/envelope/protocol/provider and prospective run_id; no run acceptance claimed before receiver. Private event max262144UTF8 bytes/16attempts, detached sink DATA; pure comparison max128retained issues plus omitted count. Research journal bounds FULL wrapper including indent/newline/Windows CRLF, runtime subdirectory/reparse guard, exclusive creation/flush/fsync; separate filenames never enter owner-run accounting.

### 4. Validation / error matrix
| Boundary | Required result |
| --- | --- |
| Unknown protocol | Closed protocol ValueError, no implicit fallback |
| V2 with old-only installed guard | `NATIVE_INVESTIGATION_V2_INSTALLED_GUARD_REQUIRED` before reserve/provider |
| Changed issued protocol/adapter/full envelope | `NATIVE_INVESTIGATION_ORIGINAL_ENVELOPE_CHANGED` |
| Input schema growth over262144 | Existing input-limit failure before reserve; do not raise cap |
| Missing/duplicate/extra dispute key | Strict report rejection; private bounded key details only |
| Container/out-of-index pointer, wrong leaf hash, duplicate pointer or absent original-region overlap | Strict field-evidence rejection; no repair of received output |
| Evidence-phase ordinary ValueError excluding ValidationError | Existing prospective safe_code=evidence_verification; schema ValidationError retains schema_validation |
| Sink/build/oversize/unallowlisted shape failure | Separate audit gap; no result/usage/UNKNOWN/hold mutation; no raw prose in public observation |
| Synchronous private run-start retention consumes deadline | After started() returns, recompute min(previous timeout, current client/profile bound, current deadline remaining); exhausted means reject BEFORE invoked=1/provider dispatch, no-sink legacy path unchanged |

### 5. Good / base / bad
Good: new explicit campaign later freezes protocol/full envelope, current owner emits private actual parsed rejection details, strict receiver still decides. Base: legacy unchanged, no sink writes by default;514notinstalled→V2prepare refuses. Bad: set new global prompt without SQL compatibility, revive old p from JSON, infer actual HTTP count from audit events, cite parent containers as scalar leaves, treat proposed_revision/supported as blocker discharge.

### 6. Validation evidence and remaining assertions
Current increment uses independent static review and few synthetic DATA checks only, never sealed DTO/owner capability hydration. Journal detachment/full-wrapper bounds and unicode oversize rejection; grouped missing/duplicate/unexpected key and scalar pointer/hash/duplicate/region negatives; failing sink isolation and unknown/nested reasoning nonretention. Source-level comparison confirms514 guard exact508 bytes except the single wrapped prompt predicate, owner gate matches new but not old source, and legacy SYSTEM unchanged.64protected files (508–513,144-event ledger, prior real case) remain byte-identical. The first Main SQL source assertion incorrectly expected a one-line predicate; its failure is retained and formatting expectation corrected, no SQL changed or executed. Evidence `.runtime/investigation-sender-v2-repair-20261010/`.
Still required later: actual selected514DDL replay/rollback/history preservation/install, fresh substantive case with original protocol/envelope planning, actual private rejection/accepted report retention and native revision/recheck. No old suite/new test files/lint/typecheck/py_compile/provider/DB/DDL this increment; DATA assertions are not live acceptance.

### 7. Wrong vs correct
Wrong: staging514 or passing synthetic diagnostics proves the new investigation→revision branch works. Correct: staged only; original installed guard and fresh owner must be verified in a later live campaign, with prior failures/UNKNOWN/once preserved.

## 2026-10-10 controlled V3 repair/assessment V5 campaign and prospective516

### 1. Scope / trigger
Latest execute approved selected514install then ONE substantive independent experiment; earlier twofailed cases/once not replayed. V3 changes the mechanism to original two-input repair/assessment-1/seed0, not another integer-name link reroll. Initial private rationale falsely generalizes fixed10 from input3 to input8. Existing finite fixtures/truth/normaldefaults untouched; no public/Gate/facts/learner authority.

### 2. Signatures
`ControlledCounterexampleContextV3` is an independent closed DATA DTO with exact-type dispatch through the existing owner; oldV1/V2 remain unchanged. `controlled_v3_plan()` returns `native_multi_round_live_plan_v5_controlled`. Main-only CLI `native-controlled-v3-live-20261010.py --execute --run-name UNIQUE --main-only-ack investigation-v2-live-authorization-20261010`; defaultplan is inert, noseedoverride/recovery. New stable intent `operator-controlled-kc-multiscenario-repair-constant-generalization-v3-once-intent.json` never derives its key fromrun/seed/root.515adds onlyclosedthird experimentCHECK/guardbranch;516copies509enforce_native_revision_insert function with two explicit JSON-extraction parentheses.

### 3. Contracts
Exacttargetpython-kc-binding-v1/familyrepair/assessment slotindex1/seed0, blueprint `finite.python-kc-binding-v1.assessment-1.family-repair.s0`, originalallocationhash929affe6c464d9577cdaf43b7af63016ef0432db2b232730a7f1a8655119d495 andexistingcanonicalroot7d4b85ba-a0ec-4348-ac11-3401c6bded47 are independently re-derived at execution, not restoredcapabilities. Initialauthor alone receives fixedprivateconst; childoriginalrevisioncontext does not inherit it. Correctchoice2comesoriginalfactory/actualpubliclabeltruth validation, neverinjectedintoblind/review.
V5exactplan fixesblind single-choice-id-v3 +investigation scalar-evidence-v2, mandatorybothprivateforensics, max17originalrequests/2candidates/input4194304/output1044480/revision1/investigation1;61440formalcap, six/investigatorhigh, originalblindthinkingconfiguration unchanged. Root/cumulativehistory/UNKNOWN remain; newunusedperiod7200,parentlease3600,request100,actualexec/fetch0 (SQLpositiveplaceholders1not extra authorization).
Beforeoriginalinvestigationprepare/reserve, actualtypedobjects+originaladapter price/hash the completeenvelope andfsync it; afterprepare compare original_issuedadapter protocol/envelope/input/resource. V5run settlesUNKNOWN andpersistsoriginalreceipt BEFORE private retention/reportstop; callbackevents notHTTPaccounting. Parent/child completeness/blindfalse stopsremain. JSONaudit/status neverissuesowners ordischargesblockers.

### 4. Validation / error matrix
| Boundary | Required result |
| --- | --- |
| V3wrongslot/seed/privateconst | ClosedDTOvalidationrejection, not fallback |
| Changedplan/protocol/pins/oldactivewindow | Failbefore paidIO; no rootfork/windowreset/once revival |
| Actualinvestigationreport invalid or private retention missing | Preserve originalsettlement/receipt thenstop, no output editing |
| Repairpublic template comparison | First extractJSON `(payload->'public_template')`, THEN jsonb-minus identities; whole result compared by original IS DISTINCT FROM |
| Changedtemplatebody after identity removal | Stillmismatch/reject, not permissive IDs-only check |
| SQL50922P02in originalIF | Preservefailure/callback/UNKNOWN, no childauthor; append516repair, never rewrite509 |

### 5. Good / base / bad
Good: newregisteredmulti-inputmechanism, realindependent6rolesandoriginalvalidinvestigation; selectedDDL/historypreserve separately. Base: valid508reportdoesNOT imply509/510accepted; oldfullcasefailure staysimmutable. Bad: callingwholeloopgreenbecauseinvestigationaccepted, rehydrateoriginalp fromJSONafterprocessends, or retrydoomedonceafter installing516.

### 6. Current actual evidence / remaining assertions
514/515/516 selectedMainrehearsal/replay/rollbackrestore/install passed inexistinglocaldevelopmentDB,300prior tables/allpriorrows/otherfunctions/triggers/constraints preserved except515'sdeclaredclosedCHECK;0newtables. Deployed508–516immutable, futurefix517+. OneactualV3group author→machine_verified→blindchoice2passed→sixcomplete(4majorblocking)→original508validV2report+UNKNOWNcommit;4disputes/4analyses,0private structuralissues. Fourblindevents andfourinv events hash/byte/source/run/input/output/scorebindings verified; actualDBreceiptpayloadsmatch. Beforegroup6014rowinstancesin300tablespreserved/4roots; parentholdtrue, no actualdescendantexercise.509prepareIFreallyfailed22P02beforechildauthor, four509/510tables0/facts/admission/nativeproof/pub0. Originalresult remainspending_retained_no_retry.
MainPGlog+readonlysyntheticJSONSELECT identified509extraction/minusprecedence;516exactfunctionsourcecopyexcept2innerparentheses independentlystaticpassed, selectedDDLaccepted. ThisisPOSTGROUPprospective, not actualrevision/recheckacceptance.39codepins remainedthrough originalgroup; later__init__516registration not mislabelledprepaid. Onlyoneledgerappend144→145, ninecompletedacceptedownerrunslowerboundNOTHTTP, knowninput192313/output57152, aggregatecached/reasoning/reportedtotal/CNYpartialunknown; originalreview/invUNKNOWN unchanged.
Evidence `.runtime/native-investigation-v2-live-20261010/` andoriginalgroup `.runtime/native-controlled-live-20261010/controlled-kc-repair-real-20261010-1/`; operator firstencoding/readbackglob/history-idchecker mistakes documented, no paidretry. No newtestfiles/oldpytest/lint/typecheck/py_compile. Remaining: genuinelyfreshoriginalowner group exercising populated509child and510recheck/descendanthold, thennormalwholepack/E underindependentauthority.

### 7. Wrong vs correct
Wrong `(payload->'public_template' - ARRAY['item_key','version'])` lets arithmetic operator precedence target a string literal andcasts public_template asJSON. Correct `((payload->'public_template') - ARRAY['item_key','version'])` explicitly extractsfirst; preserveallothercomparisonchecks. Wrong successfulSELECT/DDLmeans509worked; correct it only validates the expression/migration, not the populatedownerbranch.

## Explicit same-case after516 continuation / no-extra-cooldown amendment (2026-10-10)

### 1. Scope
Fresh human authorization allows one continuation of the same repair/assessment-1/seed0 case after516. The original failed process is terminated, so the full author/blind/six-review/investigation front chain is rebuilt with fresh original owners. No old JSON or DB row restores in-process capabilities.

### 2. Signatures
`controlled_v3_continuation_plan()` returns the closed V6 recipe; `native-controlled-v3-continuation-after516-live-20261010.py --execute --run-name UNIQUE --main-only-ack controlled-v3-same-group-continuation-authorization-20261010` is default-inert. Its fixed continuation1 intent is distinct from the consumed V5 intent. V5 generation/hash recipe remains historical and unchanged.

### 3. Contracts
The old group/accepted four-analysis investigation/UNKNOWN/hold/failed50922P02/actual516 guard are checked as historical audit before resources or model IO. V6 retains the same mechanism, allocation, root, dual protocols/private retention, formal output limits and 17-request/2-candidate bounds. The old window end is audit-only with authority=False, not a not-before deadline. New candidate/job/profile/lease and all capability objects originate from the fresh chain.
User cancellation of extra cooldown permits current-period reuse when capacity and deadlines suffice. Original controlled owner retains 32-row/eight-resource/four-dimension closure and requires effective used+full bounded caps<=cap_amount rather than exact cap/unused0; UNKNOWN is still conservatively occupied. SQL-positive execution/fetch placeholders do not authorize execution/fetch. Original root requests/tokens, lease/source/time fences and atomic reserve checks remain. Never reset, extend, enlarge or replace old limits to manufacture capacity.

### 4. Error matrix
| Boundary | Required result |
| --- | --- |
| Active window with adequate actual capacity and time | May enter original reuse path; active existence alone is not rejection |
| Duplicate/partial dimensions, insufficient effective remaining or <3600s | Reject under actual configuration/capacity/time reason, no reset |
| Old absolute not_before or old READY after source changes | Not current authorization; rebuild frozen V6 and source pins |
| Prior failed process/once/result/UNKNOWN | Preserve; new explicit continuation cannot overwrite or revive them |
| New paid branch failure | Retain exact result/diagnostics; no automatic second continuation |

### 5. Good / base / bad
Good: readonly actual readiness, independent static review, current complete source pins, then one original CLI; sufficient existing windows may be reused. Base: a fresh-period live success does not prove the adequate-active-period reuse branch. Bad: treating unlimited fees as capacity reset, restoring sealed owners from JSON, editing outputs or repeating until green.

### 6. Current evidence / remaining assertions
Initial foreground wait stopped before any paid CLI when the side conversation cancelled cooldown. At 2026-10-10T23:39:04+08 actual root effective requests9/cap17, full new batch17, remaining time1619.7s<3600. The runtime reason is CURRENT_PERIOD_TIME_INSUFFICIENT_NO_REPLACEMENT, not active-window existence. New no-cooldown supervisor uses read-only effective accounting and rechecks source pins/STOP/elapsed before its sole child; original CLI still atomically enforces all owners. Final live outcome and populated509/510 acceptance remain pending until actual evidence; original group is not rewritten, publication/normal consumers/Git/fullE remain separate.

### 7. Wrong vs correct
Wrong: force every active window to expire despite adequate capacity, or remove all budget checks when user cancels cooldown. Correct: remove only extra fresh-unused/absolute-time restrictions and keep original effective accounting, closure and operational fences. A stopped pre-model wrapper is not a model retry; only the single new paid CLI can consume the continuation intent.

## Developer model accounting-only admission (latest authorized amendment)

### 1. Scope
Explicit user removal of artificial cumulative quotas supersedes the capacity-only amendment above for authorized developer model batches. Normal production/private budgets and source/privacy/lease/original capability/correctness/publication gates remain enforced. No automatic endless retry.

### 2. Signatures
Additive517 and default-off `DevelopmentModelAccountingOwner.prepare_batch/bind_job`; `accounting_batch_for_lease` resolves current registered ledger scope, not model capabilities. `inherit_development_model_accounting` propagates accounting only from an actual original parent to its new runtime child. Closed V7 plan/CLI use development-unlimited-model-calls-20261010 while sharing the one continuation1 intent with unexecuted V6; old failed V5 intent/result is immutable.

### 3. Contracts
Fresh accounting batch uses the existing canonical root, independent current window and job/profile/lease deadlines. Old windows/global allocations/usage/UNKNOWN stay append-only. Bound original budget selects exact batch allocations and window, does not enforce cumulative global/root request/token caps, continues replay/time/32-dimensional accounting/settlement. Positive legacy cap fields are explicitly nominal under accounting-only, not huge fake infinite numbers. Normal/private budgets exclude these tagged periods and retain cumulative admission checks. Nonzero execution/fetch does not use model-only unlimited scope. Single batch remains finite17 requests/2 candidates/one investigation+revision, output61440 and original protocol/sender/evidence checks unchanged.

### 4. Error matrix
| Boundary | Required result |
| --- | --- |
| Old cumulative usage/full old window/old short remaining period | Not developer model admission caps or new-batch deadlines |
| Disabled/unregistered/dead scope or wrong DB/root/provider/model/profile/child relation | DENY, no fallback authority |
| Current lease/source expired or original once consumed | Stop; fresh ledger row cannot restore sealed model owners |
| Missing517 for normal legacy budget | Legacy normal behavior, no account-only grant |
| Actual API/refusal/invalid evidence/failed509/510 | Retain actual failure and UNKNOWN, no editing or automatic retry |

### 5. Good / base / bad
Good: current immutable development receipt tied to fresh original job, real owner reservations with complete usage history. Base: successful accounting permission is not reviewer approval or publication. Bad: cap=huge-number masquerading as unlimited, resetting old used amounts, overriding deployed SQL, restoring JSON seals, or globally disabling production checks.

### 6. Evidence and assertions
Both old waiting wrappers stopped before paidCLI; V7 inert plan verified controlled/V3 dispatch and same fixed continuation1 key. Main budget/controlled/revision/research integration implemented; original ledger145 and old once/result preserved. Independent static/selected517 replay-rollback-history-install and ONE actual original chain remain separately pending until actual receipts. A fresh-period execution must not be described as occurring before the old window expiry; nominal legacy cap exceeded under a registered accounting-only scope provides direct real admission evidence without claiming an unobserved prior-period branch.

### 7. Wrong vs correct
Wrong: research plan says unlimited while actual original budget still checks old root/global cap or chooses ambiguous overlapping windows. Correct: bind current batch to actual new job, select its original accounting rows and skip only cumulative admission caps; original model capabilities and all correctness/security fences remain.

Actual V7 assertion update (2026-10-11): selected517 installed with300 prior tables/6197 old rows and old functions/triggers/constraints preserved; new registered accounting batch/current job binding accepted. Original controlled-marker insert then rejected legacy global UNIQUE(experiment_key), actual23505, BEFORE original author reservation/model dispatch.0models/0newexpense, continuation1 intent consumed and immutable failed result retained. Post517302tables/6197 priorrows,47sourcepins,63historicalfiles,ledger145 and oldparenthold preserved. Budget.reserve unlimited admission/realmodel/child509510 remain unexercised. Never treat staticPASS or batch preparation as paid acceptance. Future explicit case/run identity separation requires new authorized continuation issuer/DDL518+ with old duplicate defense/once/UNKNOWN/history retained; no randomizedexperimentkey or automatic second attempt.

## Explicit same-case/new-execution owner and provider-idle boundary (2026-10-11)

### 1. Scope / Trigger
One explicit user-authorized execution may retain the old controlled case identity without reusing its legacy globally unique experiment row or any consumed once. Developer cumulative accounting-only admission is independent of case-execution identity and original model-capability ownership.

### 2. Signatures
`ControlledCaseExecutionOwner(conn,enabled=False).issue(*,lease,context,candidate_id,authorization_key,original_case_job_id,prior_failed_job_id,now)` returns frozen `IssuedControlledCaseExecution`; original instance/payload/connection/current binding is required. Original `prepare_controlled_counterexample(...,execution_owner=None,execution=None)` defaults to legacy. Pure `verify_identity(...)` performs no DB/clock IO; full `verify(...)` runs from original explicit `fence()` transactions. V8 CLI is default-inert and uses distinct fixed execution authorization/once `controlled-v3-same-case-execution-20261011-1`, not random run/seed/root keys.

### 3. Contracts
518 adds immutable `shared_controlled_case_executions`, `shared_controlled_execution_preparations`, `shared_controlled_execution_receipts` (all tutor_item_supply_ prefix). New execution_id is UNIQUE; case key/ContextV3/factory/seed/slots/context/rule hashes and61440 output caps remain unchanged. Old legacy experiment UNIQUE and old rows/constraints/guard stay intact. Parallel guards copy515 closed predicates and add current original execution binding; the new generation artifact trigger copies original committed trace binding. Only old DENY ancestry hold function gains a new-marker EXISTS; no admit/publish route enabled.
The shared repository's controlled_preparation lookup collects old and new rows, still requires exactly one exact job/candidate/request match and calls the original typed owner writer_binding. A DB marker alone never restores an issuer or result.
Original-generation/issued-object lookups MUST be CPU-only outside transactions. Read-only SQL or server_clock there can open an implicit transaction, cause later explicit transaction to be a savepoint, and trip PROVIDER_IO_REQUIRES_IDLE_TRANSACTION. Keep that guard: do not fix by deleting it, extra commit, autocommit or restoring old capability JSON. Full DB/source/lease/expiry checks remain in original caller-owned transaction fences.

### 4. Validation & Error Matrix
| Boundary | Required result |
| --- | --- |
| Legacy repeated case insertion | Original UNIQUE remains, not relaxed |
| New explicitly issued case execution | Separate current authorization/prep/trace; actual original owner still mandatory |
| Copied/JSON execution or wrong connection/context/job/candidate | Exact original identity/hash/binding DENY before dispatch |
| Missing committed authorization/expired source/profile/lease | Full original transaction fence DENY |
| Identity lookup accidentally does SQL | Original IDLE guard stops before model; preserve result/once/reservation |
| Consumed execution once / finished process | No automatic redispatch or capability hydration |

### 5. Good / Base / Bad Cases
Good: new execution keyed to the unchanged case, original issuer verification, explicit committed marker/trace and DENY-only ancestry. Base: successful DB authorization or reservation is not paid-model/review/revision acceptance. Bad: deleting old global UNIQUE, changing random case keys, restoring old sealed objects, removing IDLE guard or replaying consumed authorization until green.

### 6. Required evidence / actual assertions
Independent V8/518 static gate passed; selected518 rehearsal/replay/rollback/install preserved302 prior tables/6235 row instances, all old constraints including UNIQUE and old triggers; only declared hold change/new writer trigger were installed. Actual ONE V8 execution accepted new execution authorization/parallel marker and original author reservation:32 global allocations, nominal token_cap1 but reserved192512 underaccounting-only, proving real cumulative-cap skip at reservation. New and old parent holdtrue; legacycasekey/context/rule hash intact.
Actual model IO then stopped BEFORE `_started.add` at original IDLE guard because issued lookup introduced SQL.0 new models/0 generation artifacts/review/inv/child/facts/expense events; ledger145 and74 protected historicalfiles retained;305tables/6235 oldrows/schema remained. Original failedresult/once/reservation kept, no automatic second execution. Two-file post-attempt repair now moves identity to CPU-only and retains full DB verification in fence, independently staticPASS + AST DATA shape check. This repair is prospective, NOT reverified live; future original live proof needs a fresh explicit execution authorization, not replay of this consumed once. No old suites/newtestfixtures/Git/publication/fullE claims.

### 7. Wrong vs Correct
Wrong: authorization.verify does SQL from issued()/original_generation() before provider IO, so explicit transaction becomes nested and the outer implicit transaction remains. Correct: pure original identity/hash checks there, complete original DB/current source fences within existing explicit transaction, then require connection IDLE before any model dispatch.

## 2026-10-11 explicit execution2 live chain and unsupported clause evidence

### 1. Scope / Trigger
Same controlled V3 case after execution1 was consumed before provider IO. A new explicit human authorization permits execution2, never replay/reset of consumed intent. Actual17 original-model chain is completed, not wholeE or public release.

### 2. Signatures
Immutable519 extends only `tutor_item_supply_shared_controlled_cas_authorization_key_check` plus exact518 `enforce_controlled_case_execution_insert()` and `enforce_controlled_execution_scope_insert()`. Python `ACCEPTED_AUTHORIZATIONS` is closed keys1/2; old `AUTHORIZATION` stays key1. `controlled_case_execution_followup_plan()` yields closedV9/key2, fixed `operator-controlled-v3-same-case-execution-20261011-2-once-intent.json`. Runtime operators remain default-inert and Main-only.

### 3. Contracts
Fresh in-process original typed execution/job/profile/lease/accounting batch/candidate; same root/case/factory/seed/source truth. CPU-only `verify_identity()`/controlled `issued()` must not initiate a transaction before model IO. Current DB/committed/auth/source/lease fences remain in explicit transaction `verify()`/fence. Formal61440 output caps, high configured reviewer/investigator effort and original model/IDLE guard unchanged. Actual new six-role approval does not resolve old findings:510 entries `state=unsupported`, `safe_reason=no_clause_specific_adapter`, `historical_finding_resolved=false`, evidence null until supported original clause issuer exists.

### 4. Validation & Error Matrix
Consumed key1/once -> never automatic replay. Unlisted authorization/NULL -> issuer/SQL denial. Old historical DATA -> audit only, no capability hydration. Wrong source/profile/current lease -> existing fence denial. Actual missing clause adapter -> valid unsupported receipt, not technical pipeline failure and not discharge. Old V7 unmarked23505 failure holdsfalse; original marked parent/key1 and new parent/child holdtrue. New facts/admission_evaluation/publication remain0.

### 5. Good / Base / Bad Cases
Good: real519 rehearsal/replay/rollback/commit preserves305 tables/6309 prior rows, original unique and other schema; then original17 runs generate parent and substantive child, both machine validation/blind pass, complete6+6 review, accepted4-analysis508,509lineage,5104unsupported receipts. Base: ordinary production/private budget/default flags unchanged. Bad: treating six approved new reports or changed explanation as4old disputes resolved, droppinghold, reusingonce, or clearing unknown reservation.

### 6. Verification Required / Actual Evidence
This execution used actual chain plus independent bounded static check, no old suites/newtest fixtures. Main readback verifies new original receipts/profile/source and both content hashes, all17runIDs unique, both six-role reports complete,4analyses/4recheckentries/0facts, old schema/rows/history retention. Original ledger145 unchanged and one event appended146; known input361315/output82742, aggregate cached/reasoning/reportedtotal/CNY/HTTP unknown. Evidence: research/real-chain-completion-progress-20261011.md and .runtime/real-chain-completion-20261011/main-final-real-stage-verification-private.json. Future adapter verification must assert exact original dispute pointer/hash/role/source/version binding; no broad matrix before concrete scope.

### 7. Wrong vs Correct
Wrong: `child_six_approved => blockers_discharged=True`. Correct: keep all4 original disputes unsupported until clause-specific original issuer proof is accepted; preserve509/511 ancestry hold and leave production release independent. Wrong: repeat old key1 author reservation because dispatch was0. Correct: explicit new key2 single-use authorization with fresh original owners and immutable old attempt.
