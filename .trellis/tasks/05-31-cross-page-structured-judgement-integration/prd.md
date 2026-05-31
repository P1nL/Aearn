# Cross-page Structured Judgement Integration

## Goal

Use the shared `StructuredJudgement` module beyond onboarding so Aearn has one consistent way to normalize LLM-produced field-level judgements before updating learning, review, exercise, or note state.

This child is the first runtime-integration slice because it lowers the risk of later agent write tools, learner profile updates, retrieval, routing, and LangGraph rollout. If a model judgement is ambiguous, missing, or unsupported, the product should ask for clarification or stay in the current state instead of silently writing incorrect progress.

## Confirmed Current State

- `app/agents/structured_judgement.py` defines `StructuredJudgement`, `FieldPolicy`, `JudgementPolicy`, and `normalize_judgements`.
- `app/services/onboarding_conversation.py` already uses page-specific `ONBOARDING_JUDGEMENT_POLICY`.
- `tests/test_structured_judgement.py` includes a non-onboarding learning policy example, but it is not production wiring.
- `learning_concept_agent.py` validates `result`, `confidence`, `explanation`, `next_prompt`, `actions`, and optional `repair_check`, but it does not use `StructuredJudgement` to decide whether the result is safe to apply.
- `exercise_coach_agent.py` validates explanation-check `result` and converts it into score/follow-up/next action, but ambiguous model judgement is not represented as a shared status.
- Review and notes flows have model-generated guidance or text, but their request/response gates are not normalized through shared judgement policies.

## Requirements

- Define page-specific judgement policies for each production flow that needs an LLM decision or gate. Do not reuse the onboarding policy outside onboarding.
- Apply `normalize_judgements` before any durable state transition caused by a model judgement.
- Treat `ambiguous`, `missing`, and `unsupported` as blocking for required fields unless the page-specific policy explicitly marks the field optional.
- Preserve the public response shapes and SSE event names that the desktop UI already consumes.
- Keep route/service/repository layers responsible for persistence and idempotency; agents may produce candidate judgement payloads, and services decide whether to write.
- Keep deterministic fallbacks and safe model-unavailable handling where they already exist.
- Add regression tests for each wired surface proving blocked judgements do not update state, unlock practice, score an explanation, submit review progress, or overwrite note draft content.

## Target Surfaces

| Surface | Existing Entry | Judgement Need |
|---|---|---|
| Learning concept check | `learning_conversation.py` + `learning_concept_agent.py` | Normalize answer correctness, confidence, misconception, and repair-check readiness before changing `learning_stage` |
| Practice explanation check | `learning_sessions.py` + `learning_session_repository.py` + `exercise_coach_agent.py` | Normalize explanation sufficiency before writing `Attempt.explanation_check_result` or deriving next action |
| Review warmup / repair / submit | `reviews.py`, `review_repository.py`, `review_coach_agent.py` | Normalize warmup correctness and review explanation judgement before mutating review session progress |
| Note assist | `notes.py`, `note_repository.py`, `note_assist_agent.py` | Normalize request/source/output insert-scope safety before updating `Note.agent_draft_content` |

If a surface is pure text generation with no durable decision, it should not be forced into `StructuredJudgement` unless the implementation identifies a real gate.

## Acceptance Criteria

- [ ] Learning concept-check model output includes or is adapted into `StructuredJudgement` data, and blocked judgements leave the session in the current concept stage with a clarification prompt or safe retry response.
- [ ] Practice explanation-check blocked judgements do not write a passing/partial/failed explanation result to the attempt and do not advance to the next exercise.
- [ ] Review judgement gates block unsafe or unclear warmup/explanation decisions without updating review session progress or FSRS-facing results.
- [ ] Note assist blocked judgements do not persist draft content and return a recoverable response/event the UI can show.
- [ ] Existing onboarding judgement behavior and tests remain unchanged.
- [ ] Tests cover confirmed, ambiguous, missing, unsupported, and invalid/missing judgement payload cases for the wired flows.
- [ ] `python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-cross-page-structured-judgement-integration` passes before the task is started.

## Out of Scope

- Do not wire learner profile memory, RAG retrieval, handoffs, or LangGraph in this child.
- Do not redesign the desktop UI beyond preserving/handling existing response contracts.
- Do not add new judgement status values beyond `confirmed`, `ambiguous`, `missing`, and `unsupported`.
- Do not remove deterministic fallbacks unless a test proves the structured judgement path fully replaces them safely.
