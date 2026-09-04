# Research: current semantic direction-recovery data flow and typed evidence

- Query: Map the current direction-recovery mechanism across provider/Harness, LearningPlan, Codex planning, LessonTeaching, and Artifact branches; determine which actions or receipts machine-verify `continue_mainline`, `answer_and_refocus`, `clarify_direction`, and `confirmed_switch`.
- Scope: internal
- Date: 2026-09-04

## Findings

### Files found

- `aearn/services/api/app/agents/harness/provider_request.py` — shared natural-language provider policy for latest-input precedence and the four direction behaviors.
- `aearn/services/api/app/services/tutor/decision_protocol.py` — strict Harness provider output schema; typed actions are general continuations/teaching actions, not general direction dispositions.
- `aearn/services/api/app/services/tutor/decision_gate.py` — validates catalog, capability, effect, teaching action/focus/interaction authority; it does not validate a general direction-disposition field.
- `aearn/services/api/app/services/learning/plan_policy.py` — selects immutable LearningPlan `1.0.3` and LessonTeaching `1.2.1`.
- `aearn/services/api/app/agents/skills/tutor.learning-plan-draft/1.0.3/**` — instruction/eval-only direction policy for Harness LearningPlan.
- `aearn/services/api/app/agents/skills/tutor.lesson-teaching/1.2.1/**` — instruction/eval-only direction policy for lesson teaching.
- `aearn/services/api/app/services/learning/plan_tools.py` — Codex planning-context input schema and server result codes for clarification/switch.
- `aearn/services/api/app/agents/runtime/learning_plan_tools.py` — Codex dynamic-tool registry and transient per-turn direction flags.
- `aearn/services/api/app/services/tutor/codex_dispatcher.py` — persistent-thread dispatch, flag-to-server-action mapping, typed request creation, and fact reopen.
- `aearn/services/api/app/services/learning/planning_facts.py` — append-only planning fact/question lineage and direction-switch reopen set.
- `aearn/services/api/app/services/tutor/persistence/interaction.py` — durable typed request/message persistence.
- `aearn/services/api/app/services/tutor/persistence/effects.py` — lesson-teaching action receipt persistence; no general direction field.
- `aearn/services/api/app/services/tutor/branch_contracts.py` and `branching.py` — the one place where answer/refocus/switch are true typed durable branch dispositions.

### 1. Shared provider/Harness policy

`TUTOR_TEACHING_POLICY` states latest learner input/explicit control/current server authority precedence and names all four semantic behaviors (`provider_request.py:23-34`). The same policy is appended to the normal provider request and the replacement retry (`provider_request.py:47-79`; `decision_protocol.py:744-780`).

The strict provider action schema does **not** have a general direction field. Its relevant typed forms are:

- `wait_for_input { continuation_kind, question_key?, planning_intent_hint? }` (`decision_protocol.py:235-250`);
- `teaching_step { action, objective_id, focus_id, focus_resolution, interaction... }` (`decision_protocol.py:367-475`);
- direct terminal/capability/effect actions.

`parse_tutor_provider_items` maps those closed actions into `TutorDecision` but cannot preserve `continue_mainline` or `answer_and_refocus` as an explicit typed disposition (`decision_protocol.py:639-734`). `CatalogTutorDecisionGate` validates catalog/capability/effect authority, not direction semantics (`decision_gate.py:39-100`). `TeachingTutorDecisionGate` validates exact objective/focus/interaction/moves and recent-unit non-repetition, but not a direction classification (`decision_gate.py:263-402`).

**Result:** in ordinary Harness and non-blocking LessonTeaching, all four names are prompt/Skill guidance. The final action may be valid while the intended direction behavior is wrong.

### 2. Immutable Skill coverage

`plan_policy.py:21-27` makes `tutor.learning-plan-draft@1.0.3` and `tutor.lesson-teaching@1.2.1` current. Their instructions explicitly define semantic, non-keyword direction behavior:

- LearningPlan: `instructions.md:10-13`.
- LessonTeaching: `instructions.md:5-10`.

The eval JSON files provide scenario text but are static catalog fixtures, not runtime receipts. `test_tutor_skill_catalog.py:120-174` proves instruction/eval presence and version selection; it does not prove a real model selected the intended behavior.

### 3. Codex planning tool path

#### Server-side priming

Before starting the Codex turn, the dispatcher constructs a `LearningPlanRuntimeToolRegistry` and calls `registry.prime_context()` (`codex_dispatcher.py:193-200`). Priming reads current confirmed facts, missing facts, first server-owned question, current draft, and constraints (`plan_tools.py:327-371`) without consuming a model tool-call budget (`learning_plan_tools.py:160-167`).

#### Model-visible direction inputs

`PlanningContextReadInput` currently contains:

- `planning_intent_hint` for semantic language shortlist;
- `clarification_required: bool`;
- `confirmed_switch: bool`.

They are mutually exclusive (`plan_tools.py:90-109`). There is no typed field for `continue_mainline` or `answer_and_refocus`.

The registry records only transient in-memory flags when the model voluntarily calls `aearn_planning_context_read` with one of those values (`learning_plan_tools.py:201-246`). The service returns:

- `planning_direction_clarification_required` plus `direction_clarification_required=true` (`plan_tools.py:417-428`, `452-457`);
- `planning_direction_switch_pending` plus `confirmed_switch_pending=true` (`plan_tools.py:419-428`, `459-464`).

These are tool results inside the current turn, not durable accepted business receipts.

#### Dispatcher mapping

After Codex finishes, the dispatcher enters typed-request handling whenever **either** the primed/tool context has a missing field **or** one of the two transient flags is set (`codex_dispatcher.py:635-640`). It maps:

- `planning_confirmed_switch` -> append-only reopen of `language_id`, `goal_text`, `target_level`, `experience_level`, then server-generated planning/clarification prompt (`codex_dispatcher.py:369-408`; reopen set `planning_facts.py:44-49`; event writes `planning_facts.py:232-244`).
- `planning_clarification_required` -> durable general `clarification` request using one model question when shape-valid, otherwise a fixed server fallback (`codex_dispatcher.py:409-411`, `651-655`).
- no direction flag + missing fact -> ordinary `planning_input`; `_planning_input_prompt` keeps model text only when it has exactly one question and ends with the exact server question, otherwise it returns only the exact server question (`codex_dispatcher.py:412-435`, `643-648`).

`record_interaction_request` persists a formal Tutor message plus a durable request whose kind is only `clarification`, `planning_input`, `approval`, `capability_result`, or `external_result` (`interaction.py:756-876`, `931-1015`). The descriptor records request kind/question/catalog/prompt but has no general direction-disposition field.

### 4. LessonTeaching path

The selected Skill tells the model how to answer/refocus or clarify (`tutor.lesson-teaching/1.2.1/instructions.md:5-10`), but the machine contract remains a `TeachingStepDecision` with action, objective/focus, focus resolution, pause, moves, and interaction. The gate verifies those fields (`decision_gate.py:306-402`). The teaching receipt persists those same fields (`effects.py:878-915`) and has no direction action/disposition.

Therefore a receipt can prove “a valid `explain_concept`/`check_understanding` unit on focus X was committed,” but not “the model correctly recognized and resolved a direction drift.”

### 5. Blocking Artifact branch exception

The Artifact clarification branch is different and already authoritative:

- `BranchResponseDisposition` is a closed enum with `answer_and_refocus`, `offer_switch`, `confirmed_switch` (`branch_contracts.py:22-25`).
- Branch message classification is derived from explicit typed control, never free text (`branch_contracts.py:46-53`).
- The policy requires offer-before-confirm and produces a typed disposition (`branch_contracts.py:56-95`).
- PostgreSQL stores the disposition in append-only branch events and tests assert it (`test_tutor_branch_continuation.py:1033-1037`, `1325-1368`).

This authority must not be copied or weakened.

### Typed signal/action/receipt matrix

| Semantic behavior | Ordinary Harness | Codex plan tool | Codex durable result | LessonTeaching | Blocking Artifact branch |
| --- | --- | --- | --- | --- | --- |
| `continue_mainline` | Prompt-only. Usually indistinguishable from direct reply, normal planning input, or teaching step. | No field/signal. Absence of other flags is overloaded. | No direction marker. May persist a normal planning request or draft receipt. | Prompt-only; receipt proves teaching action, not direction. | Not a branch disposition; branch is not entered for normal mainline. |
| `answer_and_refocus` | Prompt-only; public text and general action may happen to embody it. | No field/signal. | Only content-shape heuristic: one question, final text ends exact server question (`codex_dispatcher.py:643-648`). No direction receipt. | Prompt-only; action receipt has no direction field. | **Typed and durable** as `answer_and_refocus`. |
| `clarify_direction` | Usually encoded as generic `continuation_kind=clarification`, but reason is not typed as direction. | **Typed transient candidate** via `clarification_required=true`; tool code `planning_direction_clarification_required`. | Durable request kind is only `clarification`; no direction-success receipt. | Can use composer/text-answer, but no direction field. | Topic-switch flow uses typed controls/dispositions, not this label. |
| `confirmed_switch` | Prompt-only unless another product-specific typed control exists. | **Typed transient candidate** via `confirmed_switch=true`; tool code `planning_direction_switch_pending`. | Server reopens facts and persists a planning/clarification request, but no durable direction-resolution receipt. | Skill says not to invent authority; action receipt has no direction field. | **Typed and durable** after prior `offer_switch`. |

### Conclusion

The current implementation has partial execution for Codex clarification and confirmed switch, but there is no complete typed direction contract across the general flow. In particular:

1. `continue_mainline` and `answer_and_refocus` are never explicit machine values outside the Artifact branch.
2. Codex `clarification_required` and `confirmed_switch` are transient model tool-call flags; durable rows record their resulting generic request/fact effects, not an accepted direction-resolution receipt.
3. The server can prove a typed request/action was valid, but cannot prove semantic direction correction succeeded.
4. The only fully machine-verifiable direction-like dispositions are inside the existing blocking Artifact branch.

### External references

- Official OpenAI Codex App Server documentation (`developers.openai.com/codex/app-server`, accessed 2026-09-04) documents `dynamicTools`, `dynamicToolCall`, `thread/start baseInstructions`, and `turn/start`; these are transport/tool primitives. Aearn remains responsible for validating tool results and defining business authority.

### Related specs

- `.trellis/spec/backend/teaching-artifact-orchestration.md:62-78` — shared semantic policy and unique durable Artifact branch authority.
- `.trellis/spec/backend/codex-runtime-sidecar.md:171-263` — server-authoritative LearningPlan dynamic tools.
- `docs/architecture/tutor-harness-runtime.md:222-244` — current direction implementation statement.
- `docs/qa/acceptance-test-plan.md:428-437` — direction scenario matrix.

## Caveats / Not Found

- No general `direction_disposition`, `direction_action`, or `direction_resolution_receipt` exists in the inspected provider DTOs, Codex tool schemas, teaching action receipt, typed request schema, or run durable event vocabulary.
- Static Skill evals and fake-host tests prove contracts and deterministic server mapping, not real-model semantic accuracy or latency.
- The Artifact branch’s durable dispositions are deliberately scoped to an active blocking Artifact and cannot serve as a general planning/teaching direction authority without violating the existing scope model.
