# RAG D Internal Plan Material Consumption

## 1. Scope / Trigger
Applies to `material_contracts_v2`, `material_binding_repository`, `evidence_binding_v2`, `current_authorization`, learning `material_selection` / `material_planning_composition`, and their opt-in Tutor integration. D has no public route, no production activation, no additional source/corpus authority. Source/current evidence and paid-provider acceptance remain separately reported.

## 2. Signatures
- `PostgresMaterialBindingRepository(conn)`: `record_selection`, `get_selection`, `assign_feedback`, `get_feedback_for_target`, `freeze_binding`; caller-owned same-connection transactions, no internal commit.
- `MaterialSelectionResult`: whole-draft `DraftScope`, exact `NodeMaterialRequirement` entries and canonical selection digest. `EvidenceBindingV2`: successor selection handle/digest, exact draft/node/goal/purpose, bounded exact C evidence and binding digest.
- `CurrentMaterialAuthorizationReceipt(kind, object_digest, draft, purposes, authorization_digest, checked_at)`: strict same-operation authorization result, not a signature or independent grant. None/bool/wrong-object receipts must not authorize persistence.
- `EvidenceSelection` / `CurrentAuthorization`: current C/A resolution plus `check_current_authorization` / `assert_publication_fence`; reuse source review, grants, corpus validation and active pointer.
- `build_internal_material_planning_dispatcher(settings, server_opt_in, requirements, evidence_factory, ...)` injects into the existing dispatcher/context/capability path only under `Settings.rag_evidence_consumer_enabled` plus server opt-in and trusted dependencies. Ordinary public factories stay unchanged.
- Schema `370_rag_plan_material_bindings.sql`: `rag_material_selections`, `rag_plan_material_bindings`; explicit schema manifest order.
- `PrimaryMaterialSemanticReviewer(settings, client=None).review(MaterialReviewRequest)` returns a request-bound `MaterialReviewReceipt`. Verdicts are `consistent`, `inconsistent`, `uncertain`; this is probabilistic plan-meaning review, never source/claim authority.
- `build_internal_material_planning_dispatcher(..., semantic_reviewer=None)` injects the default configured reviewer only behind D's existing gates. `PostgresMaterialPlanningConsumer.review_decision` and `assert_review_before_append` bind the review to the exact run/revision, parent/selection and candidate.
- Schema `380_rag_material_semantic_reviews.sql`: private semantic-dispatch/result audit; `dispatched` may settle once, settled records are immutable except authorized user purge.
- `is_verified_plan_draft_receipt(value)` recognizes only the server context projection with `kind=executed_action_receipt`, `action_id=learning.plan.draft`, both lifecycle/verification statuses `verified`, and `authority_kind=plan_draft`. This is a consumed-action signal, not an independent source permission.
- `is_current_verified_plan_draft_receipt(value, input_revision=...)` additionally requires the exact current revision and a nonempty authority ID; source objects must have an `action-receipt:` identity. Older revision receipts remain history, never a reason to disable a new revision's action.
- Internal material planning explicitly selects Skill/capability `1.1.0` through `InteractiveLearningCapabilityPolicyResolver(material_plan_v110=True)` and `SkillCatalogSnapshot.capability_for_skill()`. `LearningPlanDraftCapabilityInputV110` permits raw1024/outer-escaped6146 only for profile/module JSON strings. The ordinary path remains Skill1.0.3/capability1.0.0 with raw360/escaped2162; published old instruction/eval hashes stay unchanged.

## 3. Contracts
- Default-off and missing opt-in/dependencies perform no D repository/resolver IO. Source and model suggestions never become authority. V1 fixture/hash/DTO and old active plans remain unchanged.
- `RequirementResolver` supplies server-approved exact versions, per-node facets and usage. Never hardcode every node to a whole-course facet list or guess version from the active pointer. Unsupported mapping is not ready.
- New drafting run/revision pair only; a new run may legitimately have input_revision=1. Parent selection is durable feedback, never successor authorization. Context and pre-append validation use stored target run/revision plus current parent/session CAS, not the latest selection.
- Selection snapshot/digest immutable; only the designated all-null target assignment fields may become all-full once. Re-targeting or clearing is forbidden. Freeze natural key `(draft_id,node_id,goal_hash,purpose)` rejects different evidence even under a new retry key. Replay still checks current authorization.
- Parent feedback selection is idempotent per exact target run/revision, not only per parent draft. A fresh target reselects current evidence and gets its own immutable selection; it never steals an abandoned target's assignment. Post-append successor selection retains draft-scoped idempotency.
- `apply_material_dependencies(requirements, entries)` is the shared pure dependency rule: validate full graph, reject unknown prerequisites/cycles, process independent of input ordering, block descendants unless their prerequisite main_teaching is ready. Supplementary readiness does not replace primary prerequisites. Preserve gaps and evidence without mislabelling ready.
- No duplicate evidence counted as coverage. Exact chunk IDs are text keys, corpus version ID is UUID, registry identity is its actual digest—not an invented generation.
- Provider calls stay outside DB transactions. Internal `material_transaction` may temporarily switch an IDLE autocommit connection to manual mode before a short transaction, then restore it on success/error. Do not weaken C guards or use another connection for final authorization.
- Fence uses same active short READ COMMITTED transaction, fresh DB clock after lock waits and exact authority coordinates. Preserve C version→source/review/admission→policy/grant/root→active-pointer ordering. A receipt does not guarantee future validity or replace a supply-time check.
- Missing trusted assessment claim/execution resolvers deny; two real C supplementary excerpts do not become main textbook or scoring authority. Synthetic verifier/actor/provider fixtures are never live evidence.
- User rows are private. Authorized purge terminalizes relevant runs, uses existing transaction-local user capability, removes binding→selection, breaks only that user's current-draft reference consistently, then removes drafts/session/scope/run via existing paths. Ordinary UPDATE/DELETE forbidden; other users and shared corpus untouched.
- D revisions of an existing draft require assigned target feedback; absence must not silently bypass semantic review, re-selection or binding. An initial draft with no parent is a distinct path.
- After that exact run's verified plan action, `_PlanDraftCompletionContextLoader` removes only its consumed plan capability schema, preserving the selected Skill and receipt. A stale schema cannot re-enable it: provider validation reports `plan_draft_already_verified`, and bounded repair requests `turn_completed` rather than new plan arguments. The model still supplies completion; do not force a historical failed run to completed or bypass the normal select/capability/completion protocol.
- DeepSeek's already-saved acknowledgement is a distinct non-reasoning provider phase: only a server `ACTION_RECEIPTS` item with `action-receipt:` identity, matching input revision, verified plan authority and nonempty authority ID enables `thinking_mode="disabled"`. Initial selection/drafting retain their original thinking settings and all phases retain the same output/input bounds. A 16,384-token response spent entirely on reasoning is a real failure, not a completion receipt; retain that failed attempt before a new bounded run.
- The semantic reviewer reads the complete immutable selection and parent separately from the bounded drafting-context summary. Oversized review facts fail closed; a truncated prompt summary is not evidence of full review. Draft candidate public message and public explanation are included; separate terminal completion prose is outside this draft-review guarantee.
- Review runs outside database transactions. Reserve an exact attempt before the call; same-attempt replay must not duplicate paid IO. Settle actual/unknown usage separately from current lease/authorization eligibility, then recheck current authority. A review audit is not itself permission to append.
- Primary gateway applies the optional D validator after deterministic/stream consistency checks and before accepting/completing the attempt. Definite inconsistency feeds safe closed diagnostic guidance into the existing bounded replacement loop; uncertain/invalid/unavailable review denies. Do not silently rewrite the model's plan or restrict valid planning changes to a fixed pace template.
- The reviewer uses the configured service with one HTTP attempt per client instance, bounded output, and full-message input-budget guard. Exact verdict/reason pairs must appear in the system message as well as the schema argument: JSON-mode transports may not transmit `output_schema`. `OpenAICompatibleClient(max_http_attempts=1)` is instance-scoped; product default retries remain unchanged.
- Purge semantic audits before their referenced material selections. Source/corpus shared records remain outside user deletion.

## 4. Validation / Error Matrix

Pure profile/module validation precedes paid semantic review and action execution. `_assert_plan_domain_shape` reuses `decode_compact_profile`/`decode_compact_modules`; it does not reimplement their limits or replace final server-fact/write-time checks. `plan_domain_validation_issues` maps only known local schema paths, observed type/length/count and schema bounds into existing bounded repair. Unknown extra-key names and rejected values never appear in diagnostics. A current verified save also rejects a raw repeated draft action before payload parsing, even if that repeated payload is oversized.
| Condition | Required result |
|---|---|
| Flag off, ordinary factory, missing opt-in/ports | No D IO, old behavior preserved |
| Wrong user/draft/run/node/goal/purpose/selection digest | Reject; no partial binding or successor write |
| Failed/terminal/already-drafted target or finished pending job | Reject stale feedback rather than falsely pending |
| None/boolean/mismatched current receipt | Reject persistence |
| Wrong corpus/hash/excerpt/active generation or withdrawn authority | Safe denial and whole transaction rollback |
| Expiry crossed during lock wait | Deny using current DB clock, not transaction-start time |
| Assessment lacks trusted claim/execution evidence | Deny, not inherited trust from teaching |
| New retry key attempts alternative frozen evidence | Conflict on natural key |
| Wrong-user purge / ordinary delete | DB guard rejects |
| Valid JSON but material meaning contradicts server facts | Semantic review can reject; bounded candidate replacement, not schema-only acceptance |
| Reviewer uncertain, invalid response or unavailable | Fail closed; no unreviewed successor/binding |
| Wrong run/revision/selection/candidate review binding | Deny append even if another review returned consistent |
| Repair instructions make the request exceed its input limit | Stop before next provider call with `TUTOR_CONTEXT_REQUEST_OVERFLOW` |
| Verified plan receipt but provider requests the same draft action | Completion repair, never draft regeneration or broader string limits |
| Semantic repair exceeds the selected version's raw profile/module bound | Reject: legacy360 or trusted internal1.1.0 1024; escaping allowance does not enlarge the selected business contract |
| Profile pace_summary or node description violates its unchanged domain bound | `plan_domain_invalid` repair before semantic-review IO or action writes; recheck the replacement normally |

## 5. Good / Base / Bad Cases
Good: explicit next planning run consumes its own durable parent feedback, produces a goal-preserving successor, reselects and freezes successor-bound current evidence. Base: no D injection keeps old planning path. Bad: assigning a stale parent handle to a new draft, fake ready from fixture provenance, or pretending successful helper tests prove the dispatcher ran.

## 6. Tests Required
- Strict contract/nested-copy/digest, duplicate coverage, unordered prerequisites/cycle and multi-purpose dependency cases.
- Dedicated `AEARN_RAG_D_TEST_DATABASE_URL` whose actual current_database starts `aearn_rag260_c_d_`; full manifest bootstrap twice. Pure tests with dotenv/real provider disabled.
- Assignment/replay/restart/cancel/finished-job cases; immutable table and natural-key conflicts; real reset AND delete with rollback and other-user/shared corpus invariance.
- Registered and candidate current-authorization negatives; both policy/fence orderings and expiry while waiting; mark which writer races were actually run.
- Actual dispatcher→context→provider transport→catalog/gateway→capability→plan repository→new selection/binding; at least one real C adapter composition with synthetic trusted verifier and deterministic provider. Do not replace the entire authority adapter and call that C integration.
- Existing exact import-boundary tests, metadata inventory, Ruff/Mypy/lock, old public/v1 regressions. PostgreSQL tests with committing shared fixtures need test-owned disposable databases or genuinely distinct identities; do not relax production unique indexes to avoid pollution.
- Actual primary gateway with deterministic drafting/review transports: valid-JSON wrong meaning then repair; exhausted and uncertain denial; exact attempt replay, usage settlement after lost eligibility, current receipt and purge lifecycle. These prove routing, not natural-model accuracy.
- Real reviewer negative/positive controls and full real C→D acceptance are separate tiers. Public SQL synthetic controls do not replace a freshly admitted source or a persisted real-model successor. Preserve failed controls and known usage.
- Post-save regression checks must preserve selected Skill/receipt, remove only the consumed plan schema, and turn a stale-context duplicate into a model completion repair. A legal semantic repair with outer JSON escaping over 360 must still decode intact when raw values fit 360; raw 602 is correctly denied for the legacy version. Give deterministic test runs both an explicit bounded physical window and enough dynamic capacity for the exact selected capability schema at run creation (the focused fake uses16384/12000), rather than changing only dispatcher Settings after policy freeze. Raising only the window leaves the disabled-provider default dynamic512, which can legitimately omit an atomic schema; version1.1.0 must not be inferred without that schema.
- Versioned-capacity checks cover legacy602 refusal, new-version602 acceptance, unchanged generic capability/effect bounds, and immutable old artifact hashes. `_selected_plan_draft_version` requires complete hash-valid selected1.1.0 Skill plus its exact exported capability schema; model-supplied version hints do not authorize capacity. Capability/action dispatch independently rechecks the selected version. New action input bytes are bounded at65536 (legacy16384); domain validation, full goals and semantic/current-source reviews remain mandatory.
- A profile at the new1024 limit can exceed a1200 source when bundled with duplicate title metadata. Split those two complete parent units only when needed; do not widen1200 or truncate profile/node text.

## 7. Wrong vs Correct
Wrong: fake provider selects a Skill and performs its capability in the same decision, then weaken the gate after `mixed_skill_selection_action`.
Correct: follow the existing select-only → capability → completion protocol; respect existing turn budgets.
Wrong: feed JSON-mode lists into strict Python-mode tuple contracts and loosen validation when fixtures fail.
Correct: `model_validate_json` for JSON fixtures, or retain Python tuples; production strictness stays unchanged.
Wrong: accept a wrong explanation merely because it ends with a fixed missing-material disclaimer; or remove legitimate plan editing to make semantic tests pass.
Correct: review the proposed meaning against complete server facts, retain deterministic source/goal checks, bind the reviewed candidate, and disclose the probabilistic and terminal-prose boundaries.
Wrong: keep advertising a capability after its verified success and only add stronger prose saying not to call it.
Correct: remove the consumed schema from the next decision context, preserve trusted completion evidence, and keep completion repair separate from active drafting repair.

## Implementation closeout notes (2026-09-27)
- D planning requires the immutable profile language to map to route.python or route.sql. The trusted resolver may choose approved versions/facets/purpose, not replace the course Subject or open nonpilot scopes.
- Material feedback and exact parent profile/module/node/hash parts are REQUIRED_FACTS. `context_for_run` obtains both under one outer transaction; no feedback-only projection on a missing parent. Each parent/feedback part must round-trip through the real serializer unchanged and fit the existing 1200-character source cap. Oversized feedback is split only between complete entries, with an explicit part-count header. Only the internal injected D dispatcher has 24 required-fact slots to accommodate facts plus parent plus feedback; ordinary dispatch remains at 8. Formal total input/output token limits are unchanged.
- Current-source facet narrowing is only a demand-scoped view of freshly verified same-Subject/version C authority, with the original source digest retained; no mutation/widening of A/C permission. Actual chunk coverage is intersected with the requested facets.
- Include default contract_version before hashing a newly constructed binding. Reconstruct JSON-mode DTOs with model_validate_json, and issue PG fixture timestamps from that database's clock rather than a possibly ahead host clock.
