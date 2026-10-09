# Learning Item Supply P6 Internal Sandbox

## Scope

For the approved new V3 presentation and V2 pack policy, see
[finite type evidence](./learning-item-supply-type-evidence.md). It changes no
container/scorer/terminal ownership or historical V1 witness meaning.

P6 composes strict terminal observations, internal executor ports, and the P3/P4 private persistence boundary. It is not a public runtime, normal worker, formal learner collector, Attempt, Gate, mastery/progress, pilot or publication owner. The runtime/database/API source-of-truth documents remain authoritative.

## Isolation and provenance

- Repository and DB triggers accept only `aearn_b1d_sandbox_20261001` for sandbox execution intents/runs/observations. Private actors have a dedicated `sandbox.p6.<user UUID>` namespace; actual execution actors differ from fixture owner IDs. Do not clone real user/track/assignment/document data. Keep the control sentinel unchanged.
- A fixed runtime image is selected by immutable repository digest, never caller command/tag/mount/network/privilege. Reuse executor `build_launch_spec` and `DockerContainerRuntimeClient`; Docker imports stay in standalone executor composition, not API imports. Containers use non-root, read-only root, network none, no host mounts, dropped capabilities, no-new-privileges and fixed bounded PID/memory/CPU/output/wall limits.
- P6 has its own entrypoint and runner adapter. Both protect trusted parent process facts; the entrypoint rejects nonzero adapter exits before parsing output. The first unsafe digest is revoked by its SHA256 across all repository aliases. Fixed local logging is 16k, one file, compression false; no daemon-wide or old public launch changes.
- A typed live/isolation label or a digest alone is not execution trust. Verify actual runner-issued sealed input/result/lock/run/probe receipts; synthetic clients cannot become machine-verified. Keep reference answers/rubrics out of candidate-child input; use the existing API scorer on actual raw terminal facts. Approved internal candidate images do not populate the formal empty image-lock registry or publish executor health.
- Fixed scenarios cover correct/error/partial/equivalent/boundary/hint/answer-request/remediation/replay/stale/failure. `ObservationV2` is unique by `(source_run,scenario,attempt)` and immutable in origin and context. Counts are derived from independently resolved and verified terminal receipts, never model-supplied counters or expected scenario labels. Reads re-resolve and verify too. Simulation/probe remain distinct ledgers; real learner observations require the existing formal collector/session/actor/terminal authority and otherwise fail closed before resolver IO.

## Execution-only accounting and transactions

- `470_learning_item_supply_sandbox_execution.sql` adds three private tables: execution intents, sandbox runs, sandbox observations. Do not edit original 440/450/460 fragments or widen shared headers. A private zero request/token header is valid only with an exact current execution intent; all non-execution dimensions are zero and `execution_seconds` is positive.
- `reserve_execution` reuses the original 450 root/global/user/window cumulative caps, locks, reservations, settlement and retained anonymous usage. Ordinary `reserve` retains the legacy execution-only refusal. No fake HTTP/token usage, second wallet, new resettable cost root or unknown-as-free accounting.
- Prepare reserves under current owner/epoch/scope/generation/state/profile/source and commits before IO. Run verifies the committed intent/header under a short read transaction that closes before any container call. Settle verified actual elapsed units separately and commit before the final source/lease fence and 460 typed validation. Missing/partial usage remains unknown and conservatively reserved.
- Frozen control JSON is `item_supply_job_snapshot_v1.profile.values`; physical control state `leased` is not the logical checkpoint next stage `validating`. Fix decoding mistakes, never loosen state gates. Parameterized psycopg SQL uses `%%` for literal modulo in the `xmin` committed-settlement guard.
- Missing independent equivalent/wrong/boundary/semantic plans remains pending/blocked, even after reference/starter runner smoke. Genuine machine-verified code/SQL V2 validation enters the typed P5 path directly; it has no legacy V1 receipt and none may be forged. This is not whole-job completion or publisher authority.
- Private tables participate in existing opaque bounded export, cutover inventory and authorized children-first reset; no new PUBLIC purge grant. P4 synthetic allowlist adds only the exact disposable P6 DB while business DBs still deny it. Curated/fixed fixture sources never become live RAG assessment claims.

## Focused verification and non-claims

Use new pure tests and only affected existing tests; opt into three PG tests on the precise disposable DB with dotenv, LLM and plugin autoload disabled. Check one independent review, scoped Ruff, whole API Mypy and current file hashes. Verify fixed Python and existing curated SQLite reference/starter containers plus one parent-stdout regression, and a committed prepare/run/settle/final lifecycle. Preserve failures and their actual costs. Do not repeat old 503/54 suites or add defensive matrices.

The finite first-batch Python/SQLite independent live profiles and direct typed P5 compatibility have real component evidence. Full M01/M02/M03 qualification, real learner observations, live RAG assessment/claim authorization, full admission profile/coverage, final publisher/Practice, formal public locks, P7-P10 and E remain separately evidenced. A reference smoke or green fixture does not establish them.

## 2026-10-02 finite independent execution/scoring contract

### 1. Scope / trigger
Only the public fixed-list Python stdout task and SQLite learner-track filtering/order task have server-owned complete plans. New task semantics need a separate supported plan, not relabeling a reference run.
### 2. Signatures
`build_candidate_probe_plan(source, profile_id=None)` binds source hash and server fixture bytes. `SandboxCandidateExecutionPort(..., probe_plan=plan, parent_deadline_at=...)` issues/verifies terminal-derived evidence and exposes resource plan/usage/receipts/scorer counts. `SandboxBlindAnswerScorer(runner, binding=..., parent_deadline_at=...).score(source, answer=...)` executes one sealed answer, not the entire profile.
### 3. Contracts
Python has 16 terminal calls/160-second bound; SQLite has 23/230, independent boundary inputs, SQL positive/negative semantic pairs and protocol/resource probes. Candidate SQL expected outputs are checked by the fixed declarative filter/order oracle on legal typed datasets, never by executing its reference as truth. Python expected stdout uses existing newline normalization only, not whitespace stripping. All candidate expected data stays API-private. Blind scoring reserves ten execution seconds within the funded review plan; no fabricated HTTP call is charged as its actual usage.
### 4. Validation / errors
Unsupported task/schema/oracle -> unavailable before reservation/IO; duplicate wire disguised by a name -> reject; missing terminal/invalid seal -> unknown or pending; synthetic runner -> no machine verification; expired frozen deadline -> no new run. FP/FN/pending counts come from actual positive and negative facts; scorer counterexample is not a renamed wrong probe.
### 5. Good/base/bad
Good: actual candidate SQL on new independent boundary data, separately declared truth and sealed terminal; base: no independent plan remains pending; bad: identical query/data with only case names changed, computing truth from candidate/reference, or treating the fixed Python runtime/scorer boundary as parameterized candidate behavior.
### 6. Tests required
Use the focused probe/old execution tests and a single real committed lifecycle. Record exact measured execution units, false-positive/false-negative counts and stage fences; preserve failed/unknown attempts. Only main runs Docker/PG.
### 7. Wrong vs correct
Wrong: eight fixtures green means real OS/live source admission. Correct: sealed real execution may be machine verified while source/coverage/role veto still independently blocks admission.

## 2026-10-02 versioned Python assignment goal

- `python-assignment-sum-print-v1` is a new D1 task, not a relabel of the legacy stdout/D2 item. Exact public instruction plus the frozen `PYTHON_GOAL_SCORER_VERSION` blueprint permits server-owned `compile_goal_tests`; omitted author metadata is compiled, contradictory/foreign declarations are rejected. The full scorer hash enters source/binding and actual scope identities, while runtime hash is the actual runner-lock fingerprint.
- Protected Linux parent computes whole-program AST facts from the actual submission. Only fixed `numbers` assignment followed by direct sum/print or one `total` intermediate is supported. Children receive code only, never cases/expected outputs. The image recipe must COPY `python_goal.py` alongside the adapter.
- After seal/request verification, candidate/reference/equivalent/negative/blind/ambiguity share `score_python_case`: successful `python_terminal`, exact goal ID, strictly Boolean goal fact AND existing normalized stdout must agree. Missing/malformed facts and infrastructure failures cannot establish intentional negative evidence.
- The new goal profile has 12 terminal calls/120-second conservative bound; the legacy Python profile remains 16/160 and SQLite is unchanged. Ambiguity is two actual same-stdout calls with opposite goal facts, funded by the original seven-HTTP review aggregate and 30 execution seconds (blind 10 plus ambiguity 20). Preserve UNKNOWN provider usage, never add another wallet or pretend zero cost.
- Full 481 issue/verify retains same-connection current source, frozen scope/demand/node/blueprint, lease, exact payload and in-memory owners. For the new Python goal only, all candidate/ambiguity/blind receipts must belong to the SAME exact live `ItemSupplyRunnerBridge` with an actual `DockerContainerRuntimeClient`. Reinvoke the concrete bridge class verifier on original receipt/request pairs; an injected port's `verify=True`, typed coverage mapping or bare digest is not an actual issuer. Missing issuer/seal makes admission pending. API only inspects already-loaded classes, never imports or launches Docker.
- Focused checking uses seven goal cases, four affected legacy cases, two protected-harness cases and one image recipe case. Scoped API checks and Linux-platform harness typing suffice for this increment; only main performs real source/model/PG/Docker acceptance. Harness facts alone do not establish candidate admission or P7/P8/E.

## Effective Python goal review context

- The server derives the reviewer scoring descriptor from the exact public goal and frozen blueprint; it is not author-provided metadata. `ReviewInputV2.input_hash` binds the effective payload, and the resource plan prices exactly the payload submitted to the provider. Goal-only prompt v2.3 explains the sealed Boolean goal AND stdout rule, finite supported forms, and pending infrastructure facts without instructing approval. Legacy review v2.2 and blind inputs remain unchanged.
- Do not infer mandatory blank-marker grammar from `code_completion` alone. Review vetoes remain independent; a descriptor fix neither changes old votes nor establishes the cause of a model veto. Preserve quarantine and perform only a bounded necessary new attempt, never a retry-to-green loop.

## Private retrospective review diagnostics

- `ReviewDiagnosticInputV1` and `ReviewDiagnosticReceiptV1` are separate private protocol types, not enriched admission votes. The request explicitly marks historical source authority as not asserted current or expired; the receipt has `admission_eligible=false` and cannot enter `ReviewBundleV2`.
- A diagnostic claim carries a bounded problem, expected behavior, and exact JSON-pointer/value-hash references into the effective reviewer payload. These references authenticate location, not the truth of the model explanation. Verify the claim against the actual source/scorer contract before editing content.
- Hash the complete transmitted input, diagnostic version and complete output. Resource planning and the actual call use the same envelope. Do not expose diagnostic prose, private tests or rubric through learner projections or blind inputs.
- A historical explanation request does not renew any source, terminal seal, vote, job or lease. Reserve bounded calls under the existing canonical budget owner and a newly frozen current diagnostic job, commit before provider IO, retain actual usage/unknown settlement, and preserve all original artifacts.

## 2026-10-03 native finite public validation

### 1. Scope / Trigger
The closed `python-state-update-v1`, `sqlite-predicate-order-v1` and static
`python-kc-binding-v1` targets have a separate native public specification path.
They do not broaden the old fixed sum/filter-track task authorities.

### 2. Signatures
`build_finite_candidate_spec(...) -> FiniteCandidateSpecV1` freezes the public
template, allocation/family declaration, seed, typed goal and coverage declaration.
`prepare_finite_candidate_validation(source, spec=..., materials=...)` reconstructs
that specification and independently checks proposed scoring expectations.
`SandboxCandidateExecutionPort(runner, probe_plan=..., finite_spec=..., parent_deadline_at=...)`
and `validate_candidate(source, execution_port=..., finite_spec=...)` use the same
reconstructed finite profile. KC consumes `inputs.static_facts.validation` instead.

### 3. Contracts
The provider receives no private oracle, hidden case catalog or accepted-answer
identity. Python author tests may use `{}`; a separate compiler view injects the
exact public goal without changing generated content. Recognition reconstructs
factory allocation/seed/instruction/content, not arbitrary JSON or a claimed goal.
KC option IDs may rotate; compare complete propositions and unique truth through
the existing static scorer. A static check has no Docker/OS receipt.

### 4. Validation / Errors
The Python fixed-task boundary is an actual same-goal/same-stdout semantic-negative
control, not candidate behavior on another parameter set. Unsupported/failed
runtime facts cannot prove a negative. SQL runs the unchanged candidate on new
independent datasets; native semantic negatives and read-only/single-statement/
bounded-setup controls are real requests. Native requirements are derived from the
exact source/spec/plan; no arbitrary required-name list or fake `joins` pass.
No-spec legacy profile requirements remain unchanged. Missing seals, current
source, runtime identity, budget or original deadline remains blocked/pending.

### 5. Good / Base / Bad
Good: strict proposed expectations, independently derived finite truth and sealed
actual submissions. Base: valid public specification with no candidate/execution
is only a declaration. Bad: fixture `CURATED_FIXTURE` becomes generated admission,
a renamed option/family creates independence, or another task is called a boundary.

### 6. Minimal Verification / Actual Evidence
Only new/directly affected shape cases plus scoped lint/type were run. One actual
provider candidate per target has committed native validation: Python state 9
sealed terminals, SQLite predicate 15, KC 0. These are the first practice-family
instances, not all families/slots or course acceptance. See the task's
`research/p7b-native-generation-validation-live-20261003.md`. No rerun of the old
503/54 matrices is required by this slice.

### 7. Wrong vs Correct
Wrong: restore serialized runner seals or infer admission from machine verification.
Correct: persist immutable validation audit, retain original issuer boundaries,
and separately establish current blind/review/ambiguity/final facts, family,
exposure, publication and formal Practice/Gate authority.
