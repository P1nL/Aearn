# Design

## Current State

- `aearn/services/api/app/services/learning_session_repository.py` owns `POST /api/learning-sessions/start`, creates `learning_sessions`, writes the first `learning_messages` row, and currently returns a plain `initial_agent_message`.
- `aearn/services/api/app/services/learning_conversation.py` owns learning-page message generation, stage transition, tool-call construction, and persistence of agent `tool_calls` into `learning_messages.metadata`.
- The current tool-call model already supports generated UI cards such as `show_code_exercise` and `show_learning_history`.
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx` prepends `initial_agent_message` as the first conversation message and renders tool calls through `AssistantUIThread`.

## Target Stages

Use learning-page stages that match the new flow:

- `concept_intro`: internal start-time generation of the intro tool.
- `concept_check`: session is waiting for the learner's natural-language answer to the active judgment question.
- `concept_repair`: learner answered incorrectly and is working through a narrower follow-up check.
- `practice_offer`: learner answered correctly; agent has restated the key concept and is asking whether to start practice.
- `practice_support`: real exercise/help flow, unchanged except for new unlock reasons.

Implementation may initialize a new session directly into `concept_check` after the `show_concept_intro` tool is persisted, as long as persisted state records that the intro was generated.

## Tool Contracts

### `show_concept_intro`

Purpose: render the stable opening card for one knowledge point.

Required args:

```json
{
  "session_id": "uuid",
  "knowledge_point_id": "uuid",
  "summary": "1-2 sentence concept summary",
  "example": {
    "title": "short title",
    "body": "easy example or tiny code-like example",
    "takeaway": "what the learner should notice"
  },
  "check": {
    "type": "single_choice",
    "question": "natural-language judgment question",
    "options": [
      {"id": "A", "text": "option text"}
    ],
    "expected_focus": "the core cause/effect relationship being tested"
  }
}
```

Validation:

- `summary`, `example.title`, `example.body`, `example.takeaway`, `check.question`, and `check.expected_focus` are required non-empty strings.
- `check.options` length must be 2-4.
- Option ids must be unique and stable within the intro.
- Output must pass teaching safety checks.
- Invalid output returns `CONCEPT_INTRO_GENERATION_FAILED`; do not silently fallback to a deterministic card.

### `show_concept_check_result`

Purpose: render the model's structured judgment and next action.

Required args:

```json
{
  "session_id": "uuid",
  "knowledge_point_id": "uuid",
  "result": "correct | incorrect | unclear | skipped",
  "confidence": "high | medium | low",
  "explanation": "short learner-facing explanation",
  "next_prompt": "what the learner should answer next",
  "actions": [
    {"id": "start_practice", "label": "开始练习"},
    {"id": "show_another_example", "label": "再看一个例子"}
  ],
  "repair_check": {
    "type": "single_choice",
    "question": "optional narrower follow-up check",
    "options": [
      {"id": "A", "text": "option text"}
    ],
    "expected_focus": "optional focus"
  }
}
```

Rules:

- `correct` should set actions to at least `start_practice` and `show_another_example`.
- `incorrect` should include a short misconception explanation and, before the repair limit, a valid `repair_check`.
- `unclear` should ask for a more specific answer or ask the learner to use the option labels.
- `skipped` is used when the learner asks to practice without completing the check.
- `repair_check`, when present, follows the same 2-4 option validation.

## Persistence

- Persist `show_concept_intro` as the first agent message's `metadata.tool_calls`.
- Persist `show_concept_check_result` on the agent reply that judges the learner answer.
- Continue using `idempotency_records` for message-response replay.
- Store active concept state in `learning_sessions.learning_stage_state_json`, including:
  - `active_concept_intro`
  - `active_concept_check`
  - `concept_check_attempts`
  - `concept_check_result`
  - `previous_misconceptions`
  - `practice_unlock_reason`
  - `learning_incomplete`
  - `conversation_summary`
- Reused sessions must read existing persisted intro/check tools instead of regenerating them.

## Backend Flow

1. Start session loads knowledge point, lesson outline, sources, and runtime profile.
2. For a new learning session, call a model-backed concept intro generator.
3. Validate the structured result and teaching safety.
4. Insert the session and first agent message with `show_concept_intro` in metadata in one transaction.
5. Return session state plus intro tool data to the frontend.
6. On learner message in `concept_check` or `concept_repair`, call a model-backed concept check judge with minimal safe context.
7. Convert model result into `show_concept_check_result`, persist it, and update `learning_stage`.
8. On "开始练习" in `practice_offer`, emit existing `show_code_exercise` using unlock reason `concept_check_passed`.
9. On direct practice before passing check, emit existing `show_code_exercise` using unlock reason `concept_check_skipped`.
10. On guided practice after repair limit, emit existing `show_code_exercise` using unlock reason `concept_check_repair_limit`.

## Frontend Flow

- Learning page start should show a loading state while intro generation is pending.
- If start returns `CONCEPT_INTRO_GENERATION_FAILED`, show a recoverable error card with "重试生成" and "返回路线".
- Render `show_concept_intro` as a concept card with summary, example, and text-style answer options.
- Keep the composer as the only answer input. Do not require option buttons.
- Render `show_concept_check_result` with explanation, next prompt, optional repair check, and textual quick reply hints.
- Continue rendering `show_code_exercise` only from tool calls or recovered `practice_support` state.

## Compatibility

- Existing sessions that already have a plain `initial_agent_message` must remain readable.
- The frontend should tolerate sessions without `show_concept_intro` during the migration window.
- API docs must be updated if `LearningSession.learning_stage` enum examples change from `readiness_check` to the new concept-check stages.

## Error Handling

- `CONCEPT_INTRO_GENERATION_FAILED`: start-time intro generation failed validation, safety, timeout, or model call.
- Existing model/provider raw errors must be hidden from the user.
- A failed concept-check judgment should return a safe error or retryable response without corrupting stage state.

## Trade-Offs

- Model-generated intro keeps the examples adaptive, but requires structured validation and explicit failure handling.
- Natural-language-only answers keep the interaction chat-like, but require `unclear` handling because answers are ambiguous.
- Persisting tools prevents refresh drift, but introduces a new compatibility requirement for legacy sessions.
