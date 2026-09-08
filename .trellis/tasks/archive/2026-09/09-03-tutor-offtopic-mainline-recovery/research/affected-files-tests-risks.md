# Research: affected files, tests, specifications, and implementation risks

- Query: List the exact implementation/test/spec surface for the smallest bounded server-authoritative direction decision, and identify compatibility and regression risks.
- Scope: internal
- Date: 2026-09-04

## Findings

### Files found and proposed implementation ownership

#### Required runtime/domain changes

| File | Smallest required change | Why |
| --- | --- | --- |
| `aearn/services/api/app/services/learning/plan_tools.py` | Add required internal `direction_action` closed enum to model-visible `PlanningContextReadInput`; remove/replace separate `clarification_required` and `confirmed_switch` booleans; validate allowed combination with `planning_intent_hint`; return stable accepted/invalid result codes. | Existing tool schema is the only Codex model-to-server planning decision boundary (`plan_tools.py:90-109`, `327-466`). |
| `aearn/services/api/app/agents/runtime/learning_plan_tools.py` | Track one accepted direction candidate/result, enforce one direction-resolution call per turn, expose accepted action/result to dispatcher, and apply a smaller intake tool budget. | Current registry tracks only two transient booleans and allows 6 calls/300 seconds (`learning_plan_tools.py:43-64`, `84-89`, `201-266`). |
| `aearn/services/api/app/services/tutor/codex_dispatcher.py` | Require accepted direction before typed-request fallthrough; remove “missing fact alone means pending” behavior; map all four actions to server postconditions; use conservative clarification on omission/timeout; emit durable success receipt after commit; choose bounded intake turn profile from primed status. | Current stale-question fallback and transient mapping live here (`codex_dispatcher.py:193-200`, `349-466`, `635-674`). |
| `aearn/services/api/app/agents/runtime/contracts.py` | Add optional internal turn effort/profile field, bounded and default-compatible. | `RuntimeTurnRequest` currently has only thread/input/tools (`contracts.py:122-127`). |
| `aearn/services/api/app/agents/runtime/codex_adapter.py` | Pass optional `effort` to `turn/start`; preserve omission when unset; keep all existing turn fences and notification handling. | Current request sends only `threadId` and `input` (`codex_adapter.py:148-159`). |
| `aearn/services/api/app/services/tutor/persistence/run.py` | Add a public repository method that appends one idempotent `planning_direction_resolved` event after postconditions succeed; do not call `_append_event_locked` ad hoc from unrelated layers. | Existing append-only event mechanism is safe and migration-free (`run.py:884-935`). |
| `aearn/services/api/app/services/tutor/persistence/_dependencies.py` | Add `planning_direction_resolved` to the closed durable event vocabulary. | `_DURABLE_EVENT_KINDS` currently excludes it (`_dependencies.py:120-133`). |
| `aearn/services/api/app/services/tutor/safe_projection.py` | Allowlist only receipt keys/closed values (`direction_action`, `result_kind`, `source`, hashes, policy/schema version); continue dropping learner/model prose. | Existing projection rejects unknown fields and validates bounded safe metadata (`safe_projection.py:40-92`, `136-186`). |

`persistence/contracts.py` needs a new receipt dataclass only if callers/tests benefit from a typed return value. It is optional; the durable `TutorDurableEvent` can be returned directly for the smallest patch.

#### Required tests

| Test file | New/changed cases |
| --- | --- |
| `aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools.py` | Generated schema requires exactly one `direction_action`; every enum value accepted; old booleans rejected; hint compatibility enforced; omission/duplicate resolution/second resolution call fail closed; no learner text/rationale enters tool result or receipt candidate. |
| `aearn/services/api/tests/codex_sidecar/test_codex_plan_drafting_cutover.py` | Parameterized four-way mapping; screenshot-like ambiguous input with omitted signal must not ask old question; malformed/timeout path creates fixed clarification or stable failure; answer/refocus requires exact-ending one-question postcondition; confirmed switch reopens exactly four direction facts; continue with complete facts can draft; exactly one durable direction receipt per run. |
| `aearn/services/api/tests/codex_sidecar/test_codex_runtime_adapter.py` | `turn/start` includes allowed `effort` when set and omits it otherwise; fake server rejects invalid values; timeout/interrupt remains terminal and no second turn contamination occurs. |
| `aearn/services/api/tests/tutor/test_tutor_run_repository.py` or a focused new persistence test beside it | Durable event kind is accepted, idempotent replay returns the same event, conflicting payload fails, safe projection contains only closed metadata, export/diagnostics do not include learner/model prose. |
| `aearn/services/api/tests/tutor/test_tutor_conversation_runtime.py` | Public snapshot/SSE remain unchanged by the internal direction receipt; receipt never becomes a new public item/event/field. |

#### Existing tests that should remain unchanged and green

- `tests/tutor/test_tutor_provider_gateway.py` — shared Harness policy and non-keyword scenario matrix (`:202-286`).
- `tests/tutor/test_tutor_skill_catalog.py` — immutable LearningPlan `1.0.3` and LessonTeaching `1.2.1` hashes/instructions.
- `tests/tutor/test_tutor_teaching_context.py` and `test_tutor_teaching_action_loop.py` — lesson-teaching authority.
- `tests/tutor/test_tutor_branch_continuation.py` — unique Artifact branch dispositions/offer-confirm rules.
- `tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py` — server facts/question descriptors/fences.
- Planning-fact and typed-request tests — exact question catalog and append-only fact lineage.

#### Specifications/source-of-truth to update after implementation

| File | Required spec change |
| --- | --- |
| `.trellis/spec/backend/codex-runtime-sidecar.md` | Define required internal four-way direction candidate, server gate/postconditions, intake deadline/effort, omission fallback, receipt schema, and no-public-enum/no-keyword boundary. |
| `docs/architecture/tutor-harness-runtime.md` | Update Codex plan-drafting data flow from transient booleans/fallback to candidate -> gate -> request/draft/reopen -> receipt. Keep Harness/LessonTeaching policy text. |
| `docs/qa/acceptance-test-plan.md` | Add P0 cases for missing candidate, old-question suppression, four accepted actions, deadline, idempotent receipt, no public contract change, and explicit no-real-provider limitation. |
| `docs/product/user-flows.md` | Optional one-sentence clarification that ambiguous planning direction produces a server-owned single clarification and cannot silently continue the stale question. No public enum should be documented. |

Do **not** edit published Skill `1.0.3`/`1.2.1`; if future Harness wording changes are necessary, publish new immutable versions. This bounded Codex implementation does not currently require a new Skill because Codex plan drafting uses `_BASE_INSTRUCTIONS` and dynamic tools, not the Harness LearningPlan Skill (`design.md:55-63`; `plan_policy.py:21-27`).

### Files explicitly not required for the bounded direction implementation

- `aearn/services/api/app/services/tutor/runtime_projection.py`
- `aearn/services/api/app/services/tutor/conversation_contracts.py`
- `aearn/services/api/app/services/tutor/persistence/conversation.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- Desktop contracts/API/hooks/reducers/components/tests
- Database schema/migration files
- Artifact branch contracts/tables
- `provider_request.py`, `decision_protocol.py`, `decision_gate.py` unless the task is deliberately expanded beyond Codex plan drafting

Those files belong either to the mistaken privacy patch, an already-sufficient shared semantic policy, or a separate product authority.

### Proposed focused validation

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/codex_sidecar/test_codex_learning_plan_tools.py `
  tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py `
  tests/codex_sidecar/test_codex_plan_drafting_cutover.py `
  tests/codex_sidecar/test_codex_runtime_adapter.py `
  tests/tutor/test_tutor_run_repository.py `
  tests/tutor/test_tutor_conversation_runtime.py -q

uv --directory .\aearn\services\api run ruff check `
  app/agents/runtime/contracts.py `
  app/agents/runtime/codex_adapter.py `
  app/agents/runtime/learning_plan_tools.py `
  app/services/learning/plan_tools.py `
  app/services/tutor/codex_dispatcher.py `
  app/services/tutor/persistence `
  tests/codex_sidecar `
  tests/tutor/test_tutor_run_repository.py `
  tests/tutor/test_tutor_conversation_runtime.py

uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .trellis/tasks/09-03-tutor-offtopic-mainline-recovery
```

A real-provider latency/semantic smoke remains excluded unless separately authorized. The fake App Server should include an artificial pre-tool delay to prove the server deadline rather than relying only on instant fake calls.

### Risk matrix

| Risk | Severity | Why | Mitigation/test |
| --- | --- | --- | --- |
| Low effort harms full plan quality | P1 | One turn can include both direction decision and draft when facts are complete. | Apply low effort only when primed status is `AWAITING_USER`; complete-fact drafting keeps normal profile. |
| Model omits required enum | P0 | Current production failure mode. | Schema requires it; server refuses old-question fallback; fixed clarification or stable failure; regression with fake host omission. |
| Model chooses wrong enum semantically | P1 | No keyword classifier or second semantic judge exists. | Server restricts effects; ambiguity-safe fallback; scenario evals; optional later real-provider statistical eval. Do not overclaim semantic certainty. |
| `answer_and_refocus` text bypasses exact question | P0 | Could create mismatch between message and generated UI. | One-question + exact-ending + safety check; atomic request/message/receipt; otherwise clarify/fail. |
| Confirmed switch reopens too much or too little | P0 | Stale facts could still draft or stable preferences could be lost. | Keep exact existing four-field constant (`planning_facts.py:44-49`); assert weekly minutes/preferences/pace remain. |
| Direction receipt becomes model authority | P0 | Persisting raw model enum/rationale directly would violate authority. | Server computes closed accepted action/status/hashes after commit; no rationale/text; safe projection; idempotency conflict test. |
| Receipt leaks into public API/SSE/Desktop | P1 | Internal decision evidence could accidentally become a public item. | Keep it in run durable events only; public contract regression proves no new snapshot/SSE key/item. |
| New event kind breaks replay/export | P1 | Application vocabulary is closed even though DB column is generic. | Update `_DURABLE_EVENT_KINDS`, mapping, diagnostics/export tests; no migration. |
| Deadline interrupts valid slow environments | P1 | Local model/network variance may exceed a too-small constant. | Setting-backed default, measured fake delay boundaries, stable timeout code, no partial request/fact write. |
| Persistent thread still biases candidate | P1 | Typed enum does not remove old context. | Candidate required every turn; current facts/input in prompt; server fallback prevents omission; later real-provider eval may tune prompt or thread reset policy. |
| Parallel dirty changes are reverted accidentally | P0 | Privacy and direction changes share task/docs/spec files. | Revert by named semantic hunks only; narrow stage; compare current hunk ownership before write/commit. |
| Immutable Skill byte hashes are damaged | P0 | Published bundles are raw-byte authority. | No edits to existing Skill versions; run catalog hash/LF checks. |
| Artifact branch authority is duplicated | P0 | General direction flow could conflict with active blocking Artifact. | Codex plan-drafting scope only; do not reuse branch tables or public dispositions. |

### External references

- Official OpenAI Codex App Server docs (`developers.openai.com/codex/app-server`, accessed 2026-09-04) for `turn/start effort`, `dynamicTools`, and explicit tool-call responses.
- Local exact Runtime version remains `0.142.0-cometix`; verify the fake/allowed-version contract before depending on an effort override (`.trellis/spec/backend/codex-runtime-sidecar.md:43-49`).

### Related specs

- `.trellis/spec/backend/codex-runtime-sidecar.md`
- `.trellis/spec/backend/teaching-artifact-orchestration.md`
- `.trellis/spec/backend/database-guidelines.md` for append-only event/idempotency rules
- `.trellis/spec/backend/quality-guidelines.md` for serial PostgreSQL and public-absence tests
- `.trellis/spec/guides/cross-layer-thinking-guide.md:156-176` for provisional event versus business authority

## Caveats / Not Found

- The exact effort enum accepted by the local forked Codex `0.142.0-cometix` was not live-probed because real Runtime/model execution was out of scope. Treat effort as transport optimization; required typed action, server postconditions, timeout, and receipt are the authority fix.
- A production-quality semantic accuracy claim still requires separately authorized real-provider evaluation over the scenario matrix. Fake tests can prove omission/fallback/receipt behavior deterministically.
- The task planning files currently still contain the retracted privacy requirements. The main session should revise them before implementation approval so implement/check agents do not receive conflicting scope.
