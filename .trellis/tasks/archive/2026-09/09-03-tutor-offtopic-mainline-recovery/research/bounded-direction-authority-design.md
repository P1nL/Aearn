# Research: smallest server-authoritative bounded direction decision

- Query: Design the smallest implementation that bounds Codex direction resolution and emits a machine-verifiable success marker without keyword matching or model-written persisted authority.
- Scope: mixed
- Date: 2026-09-04

## Findings

### Design objective

Keep the existing semantic policy and server-owned planning facts/questions. Add one internal typed **candidate -> server gate -> server receipt** path for Codex plan drafting. Do not add a public API enum, Desktop classifier, keyword list, database migration, second Artifact branch state machine, or model-authored fact write.

### Files found

- `aearn/services/api/app/services/learning/plan_tools.py` — existing model-visible planning context schema is the smallest place to add a closed direction candidate.
- `aearn/services/api/app/agents/runtime/learning_plan_tools.py` — existing registry already tracks per-turn planning signals and budgets.
- `aearn/services/api/app/services/tutor/codex_dispatcher.py` — already maps transient signals into server prompts, fact reopen, typed request persistence, and terminalization.
- `aearn/services/api/app/agents/runtime/contracts.py` and `codex_adapter.py` — smallest internal path for an optional App Server turn `effort` override.
- `aearn/services/api/app/services/tutor/persistence/run.py`, `_dependencies.py`, and `safe_projection.py` — existing append-only `tutor_run_events` can carry a server-issued receipt without a schema migration.
- `aearn/services/api/app/services/tutor/persistence/interaction.py` — existing atomic message + typed request boundary supplies postcondition evidence.

### Proposed internal contract

#### 1. Replace two booleans with one closed candidate

Add an internal enum/type in `plan_tools.py`:

```python
PlanningDirectionAction = Literal[
    "continue_mainline",
    "answer_and_refocus",
    "clarify_direction",
    "confirmed_switch",
]
```

Model-visible `PlanningContextReadInput` becomes conceptually:

```python
class PlanningContextReadInput(_ToolModel):
    schema_version: Literal["aearn-learning-plan-tools-v1"]
    direction_action: PlanningDirectionAction
    planning_intent_hint: PlanningContextIntentHintV2 | None = None
```

Rules:

- `direction_action` is required on the model’s first `aearn_planning_context_read` call for every Codex plan-drafting turn.
- `planning_intent_hint` is allowed only with `continue_mainline` and only when `language_id` is the next missing fact.
- Remove the ambiguous default-empty model call. Internal `prime_context()` remains a direct server method and is not subject to the model schema.
- The model supplies a **candidate**, not persisted authority. No rationale, evidence prose, learner text, fact value, or replacement objective is accepted.

This closes the current omission state: every turn has exactly one candidate or fails closed.

#### 2. Gate the candidate against server state

The service/registry accepts the candidate only under server-owned conditions:

| Candidate | Server postcondition |
| --- | --- |
| `continue_mainline` | Current facts/session remain authoritative. If a fact is missing, result must be the existing first `next_missing_fact`; if facts are complete, the model may proceed to the existing typed draft tool. |
| `answer_and_refocus` | A first missing fact must exist. The eventual public text must be learner-safe, contain exactly one question, and end with the exact server `planning_question_prompt(field)`. The server-generated typed request remains `planning_input`. |
| `clarify_direction` | No fact mutation or draft. Server creates one `clarification` request using a fixed/bounded server prompt; model wording may be ignored. |
| `confirmed_switch` | Server executes existing append-only reopen of `language_id`, `goal_text`, `target_level`, `experience_level`; then selects the next server question/clarification. Model cannot provide replacement values. |

A structurally valid candidate is not yet “success.” Success occurs only after the mapped server action and all postconditions commit.

#### 3. Remove the stale-question omission fallback

Change `_codex_typed_request_pending`/terminalization so “primed missing fact exists” is not sufficient by itself. Require an accepted `direction_action`.

If the model omits/invalidates the action or exceeds the direction bound:

- do **not** fall back to the old first missing fact;
- interrupt/terminalize the model attempt safely;
- create one server-owned generic direction clarification such as the existing `_direction_clarification_prompt` fallback;
- record `source=server_fallback_missing_direction` in the internal receipt.

This conservative fallback resolves ambiguity without keyword matching and guarantees the screenshot path cannot silently ask the stale website question.

#### 4. Bound intake deliberation

Use existing knowledge from `prime_context()` to distinguish intake from full drafting:

- If primed status is `AWAITING_USER`, this turn cannot legitimately submit a draft until learner input arrives. Set an internal turn profile:
  - `effort="low"` on App Server `turn/start`;
  - direction deadline 30-45 seconds (exact value should be a setting with a tested default);
  - at most one accepted direction-context call; no learning-plan draft call;
  - at most one bounded final answer/refocus text.
- If primed status is `COMPLETED`, keep normal draft timeout/effort, but still require the first context call to carry one direction candidate. A second call may be the existing draft tool.

`RuntimeTurnRequest` currently has no effort field (`runtime/contracts.py:122-127`), and the adapter currently omits it (`codex_adapter.py:148-159`). Official App Server docs expose an optional `turn/start effort`, so this can remain an internal transport change.

The deadline must be enforced by the host/dispatcher, not merely written into the prompt. A tool-call budget alone cannot stop a model that reasons too long before its first call.

#### 5. Emit a server-issued success receipt without a migration

Reuse append-only `tutor_run_events`; its database `kind` is bounded text, while application code keeps a closed allowlist (`persistence/run.py:884-935`; `_dependencies.py:120-133`). Add a new durable kind such as `planning_direction_resolved` and a repository method that emits exactly once after the transaction commits the mapped action.

Recommended safe payload:

```json
{
  "schema_version": "planning-direction-resolution-receipt-v1",
  "kind": "planning_direction_resolved",
  "status": "accepted",
  "direction_action": "clarify_direction",
  "result_kind": "clarification",
  "question_key": null,
  "input_revision": 3,
  "facts_fingerprint": "<sha256>",
  "public_message_hash": "<sha256>",
  "policy_version": "planning-direction-policy-v1",
  "source": "model_candidate"
}
```

For a server fallback, `direction_action=clarify_direction`, `source=server_fallback_missing_direction`. For a confirmed switch, include the resulting first reopened `question_key` but never fact values or learner text.

The receipt is authoritative because:

- the server chooses the stored action from a closed enum after validation;
- the server computes the facts/message hashes;
- the server writes it only after the typed request/draft/fact reopen postconditions succeed;
- the payload is projected through the existing safe allowlist;
- the model cannot supply IDs, hashes, status, result kind, source, or policy version.

No new table or column is required. Add the new keys/enum values to `TutorSafeProjection` rather than allowing arbitrary payload fields (`safe_projection.py:40-92`, `136-186`).

### Exact success postconditions

| Accepted action | Machine-verifiable success condition |
| --- | --- |
| `continue_mainline` + missing fact | Persisted request kind `planning_input`; exact server `question_key`; descriptor prompt equals `planning_question_prompt`; receipt action/result/hash matches. |
| `continue_mainline` + complete facts | Existing valid learning-plan draft receipt/append succeeds; direction receipt references the current facts fingerprint and `result_kind=plan_draft`. |
| `answer_and_refocus` | Formal message is learner-safe; exactly one question; ends exact server question; matching `planning_input` request and direction receipt commit atomically. |
| `clarify_direction` | Exactly one durable `clarification` request; no `question_key`; no fact/draft mutation; server prompt and direction receipt commit atomically. |
| `confirmed_switch` | Append-only reopen events exist for the four direction fields; no draft committed from stale facts; one next request exists; direction receipt records `confirmed_switch`. |
| missing/invalid/timeout | No old-fact planning request; one server fallback clarification or stable failed outcome; receipt marks server fallback or failure code. |

### Why this is the smallest credible design

- Reuses the existing planning context tool rather than adding a classifier provider, Desktop route, or second Runtime.
- Reuses existing fact reopen and typed request authority.
- Reuses existing append-only run event storage; no migration.
- Changes only internal Codex contracts; public snapshot/SSE/Desktop contracts do not need a direction enum.
- Does not change immutable Skill resources: Codex planning does not consume the Harness LearningPlan Skill, and the current Skill direction policy remains valid.
- Makes all four behaviors explicit and testable while preserving server ownership of the actual action.

### Rejected alternatives

1. **Keyword/regex classifier in API or Desktop:** violates the semantic requirement and fails related-extension cases.
2. **Persist the model enum directly in planning facts:** makes model output authority and pollutes fact lineage.
3. **Only strengthen `_BASE_INSTRUCTIONS`:** repeats the current prompt-only failure and provides no receipt.
4. **Only shorten the UI reasoning display:** changes observability, not latency or final action.
5. **Reuse Artifact branch tables:** scope violation; those rows require an active blocking Artifact and explicit offer/confirm controls.
6. **Add only `continue_mainline`/`answer_and_refocus` booleans:** preserves mutually ambiguous booleans and omission; one required closed enum is smaller and safer.
7. **Accept arbitrary model clarification text as success:** cannot prove it resolved direction or stayed within one question/exact typed-request authority.

### External references

- Official OpenAI Codex App Server docs (`developers.openai.com/codex/app-server`, accessed 2026-09-04): `thread/start` supports `baseInstructions` and `dynamicTools`; `turn/start` supports an optional `effort`; dynamic tool calls have explicit client responses. These primitives support an internal bounded candidate/gate flow.
- Local Runtime compatibility target: Codex `0.142.0-cometix` (`.trellis/spec/backend/codex-runtime-sidecar.md:43-49`). The implementation must verify that this exact allowed build accepts the chosen `effort` value in fake/contract tests before relying on it.

### Related specs

- `.trellis/spec/backend/codex-runtime-sidecar.md` — add the required direction candidate, bound, server postconditions, and durable receipt.
- `.trellis/spec/backend/teaching-artifact-orchestration.md` — preserve its statement that general direction semantics do not create a second Artifact authority.
- `docs/architecture/tutor-harness-runtime.md:222-244` — replace the current “not prompt-only” claim with the explicit candidate/gate/receipt contract.
- `docs/qa/acceptance-test-plan.md:428-437` — add omission, timeout, fallback, receipt, and no-stale-question cases.

## Caveats / Not Found

- A one-turn low-effort intake profile is safe only when primed context is `AWAITING_USER`; full plan drafting may need the existing normal effort/timeout. Tests must prove the branch selection is server-derived from primed status.
- If the exact allowed Codex build does not accept `turn/start effort`, retain the same server deadline/required typed action and treat effort as an optional optimization, not the authority mechanism.
- The server cannot prove the model’s semantic judgment is philosophically correct without another semantic model. It can prove that one closed candidate was supplied, only an allowed server action occurred, required postconditions held, omission/timeout did not fall through, and a durable server receipt was written. That is the requested machine-verifiable success boundary.
