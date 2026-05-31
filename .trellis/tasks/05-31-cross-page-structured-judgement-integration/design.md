# Cross-page Structured Judgement Integration Design

## Architecture

Keep `app/agents/structured_judgement.py` as the single generic judgement primitive. Domain code owns the policies and adapters:

- Learning policies live near `learning_concept_agent.py` or `learning_conversation.py`.
- Exercise explanation-check policies live near `exercise_coach_agent.py` and are applied by `learning_session_repository.py` before `Attempt` writes.
- Review policies live near `review_coach_agent.py` / review service code and are applied before review progress or FSRS-facing mutations.
- Note-assist policies live near `note_assist_agent.py` / `note_repository.py` and are applied before `agent_draft_content` writes.

Do not move persistence into agent modules. Agents produce candidate content plus judgement evidence; services normalize and decide whether the candidate can be written.

## Data Flow

General flow:

```text
Route request
  -> service/repository loads safe context
  -> agent builds JSON/text candidate with field-level judgements where needed
  -> domain adapter parses `StructuredJudgement` values
  -> `normalize_judgements(policy=page_specific_policy)`
  -> service either writes durable result or returns clarification/retry response
```

The normalization boundary sits after model validation and before durable state changes. This keeps model-specific parsing out of repositories while still preventing unsafe writes.

## Policy Shape

Each policy should name only fields that matter for the page gate:

- Learning concept check: `answer_correctness`, `confidence`, optional `misconception`, optional `repair_check`.
- Practice explanation check: `explanation_sufficiency`, optional `feedback_grounding`, optional `next_action`.
- Review: `warmup_correctness` or `review_explanation_sufficiency`, optional `weak_point_signal`, optional `repair_needed`.
- Note assist: `insert_scope`, `source_grounding`, `content_safety`, optional `focus_clarity`.

Policies must set required/optional status according to the page contract, not according to what the model happened to return.

## Compatibility

- Existing response envelope and SSE event names must remain stable.
- Existing deterministic fallbacks may continue returning current shapes.
- If a model path returns a blocked judgement, services should map it to a recoverable response rather than a provider failure.
- If a model path is unavailable, existing `MODEL_UNAVAILABLE` or deterministic fallback behavior remains the rollback path.

## Validation Strategy

Use focused unit tests for adapters and route/service tests for production wiring:

- Adapter tests assert policy normalization and field clearing.
- Learning session tests assert stage/state does not advance on blocked concept judgements.
- Attempt tests assert explanation-check writes happen only after confirmed sufficiency.
- Review tests assert review state and review logs do not mutate on blocked review judgements.
- Notes tests assert draft content is not persisted when note-assist judgement blocks output.

## Trade-offs

- Requiring explicit `judgements` in every model response is stricter but safer; it may require updating fake clients and prompts.
- Deriving confirmed judgements from existing enum results is lower risk for rollout, but weaker as a guardrail. Use it only as an adapter for deterministic or legacy fallback paths, not as the primary LLM contract.
- Centralizing all policies in one file would make discovery easy, but it would mix domain semantics. Prefer co-located policies unless duplicate logic appears in three or more places.
