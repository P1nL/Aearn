# Add SDK exercise coach endpoints

## Goal

Move the learning exercise coaching endpoints behind Aearn-owned OpenAI Agents SDK modules while preserving the existing API contracts, Attempt writes, idempotency behavior, deterministic fallbacks, and Aearn-owned scoring state.

This is a follow-up after `05-23-sdk-teaching-tools-guardrails`. The SDK should improve coaching quality for hints, error explanation, and explanation checking, but it must not take over runner execution, final evaluation, FSRS scheduling, or durable product writes.

## Requirements

- Add an Aearn-owned SDK Exercise Coach module under `aearn/services/api/app/agents/`, likely `exercise_coach_agent.py`.
- Cover these existing endpoint paths without changing their public contracts:
  - `POST /api/learning-sessions/{session_id}/exercises/{exercise_id}/hint`;
  - `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`;
  - `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/check-explanation`.
- Keep `learning_session_repository.py` responsible for:
  - loading session, exercise, attempt, and visible result context;
  - incrementing `Attempt.hint_usage_count`;
  - writing `Attempt.error_cause`, `Attempt.explanation_text`, and `Attempt.explanation_check_result`;
  - idempotency lookup and storage.
- SDK inputs must be safe summaries, not raw full submissions or hidden test payloads.
- SDK outputs must be normalized to the existing response shapes from `exercise_guidance.py` and `llm_explain_error.py`.
- Guardrails from the teaching-agent task must apply to coaching outputs:
  - no direct full-answer leakage;
  - no hidden test IDs, hidden case text, or reference answers;
  - no provider raw errors or SDK event names in API responses.
- Preserve deterministic fallback when model config is missing, SDK execution fails, output validation fails, or guardrails block before a useful response.
- Keep all tests model-key-free using fake SDK runners or fake client adapters.

## Acceptance Criteria

- [x] Exercise Coach SDK module exists under `app/agents/` and is used by hint, explain-error, and check-explanation generation.
- [x] Public JSON response fields and error codes for the three endpoints are unchanged.
- [x] `Attempt` writes remain in `learning_session_repository.py`, not inside SDK tools or agent code.
- [x] Hint responses stay incremental in level: `nudge`, `concept`, and `code_shape` must not become complete answers by default.
- [x] Explain-error output is grounded in provided runtime/stderr/visible test facts and does not invent runner results.
- [x] Explanation-check output preserves the max-two-round rule and schema expected by submit/evaluate.
- [x] SDK failure or blocked output falls back to existing deterministic guidance.
- [x] Existing `tests/test_learning_sessions_m3.py` still passes.
- [x] Focused LLM/SDK integration tests cover fake SDK success, invalid output, blocked leakage, and deterministic fallback.

## Out Of Scope

- Moving `/run` or `/submit` execution/evaluation into the SDK.
- Changing `build_code_completion_result`, FSRS mapping, or `ReviewState` writes.
- Review-page coaching.
- Note assist generation.
- Frontend UI redesign.

## Dependencies

- `05-23-sdk-teaching-tools-guardrails` should finish first so this task can reuse safe tools, guardrail helpers, and SDK runtime wiring.
- Current SDK foundation remains the base: `app/agents/sdk_runtime.py` and the `TextCompletionClient`-style boundary.
