# Review Warmup Natural Conversation Flow Design

## Scope

This task updates the review-session warmup and exercise conversation flow across backend agent judgement, review-session state, API contracts, desktop rendering, and tests.

The implementation keeps the existing review batch state machine and FSRS boundary. It changes how warmup answers are classified and how the desktop exposes warmup and exercise feedback.

## Architecture

### Current Data Flow

```text
ReviewPage composer
  -> POST /api/reviews/{session_id}/warmup-result
  -> record_review_warmup_result
  -> build_sdk_review_warmup_judgement_response
  -> ReviewPage renders warmup result or exercise card
```

Formal exercise flow remains:

```text
ReviewExerciseWorkbench
  -> runLearningExercise / submitReviewExerciseResult
  -> submit_review_exercise_result
  -> completed card snapshot + next exercise card or final summary
```

### Target Warmup Judgement Contract

Extend the warmup judgement result set:

```text
correct | incorrect | unclear | off_topic
```

`off_topic` means the learner's answer is clearly unrelated to the current warmup prompt. It is not a knowledge failure and must not update FSRS, create attempts, or write review logs.

The model response remains a safe JSON object:

```json
{
  "result": "off_topic",
  "confidence": "high",
  "feedback": "这句和当前热身点关系不大。先回到这个问题：看到这段代码时，你会先怀疑状态放在哪里会出问题？"
}
```

The `feedback` field is used as the user-facing steering message. It must be model-authored and pass the existing teaching safety guardrails.

### Off-Topic Failure Handling

When the model classifies a warmup answer as `off_topic`, the backend should return the model-authored `feedback` on the first off-topic answer and keep the session on the warmup turn.

If model generation fails, is unavailable, returns invalid JSON, returns an invalid result, or its output is blocked by the existing teaching safety guardrails:

1. Retry model generation once.
2. If the second attempt still fails or is blocked, return `MODEL_UNAVAILABLE`.
3. Do not use a fixed local template.
4. Do not auto-advance into exercise on model failure.

The retry applies to model-authored warmup judgement/steering for this flow. Existing hidden `action=skip` compatibility does not need model retry.

### Warmup State

Persist enough warmup state to make off-topic behavior deterministic across reloads:

```json
{
  "result": "off_topic",
  "last_answer": "...",
  "feedback": "...",
  "off_topic_count": 1,
  "judgement_source": "llm",
  "judgement_model": "configured-model"
}
```

Rules:

- First `off_topic`: persist `off_topic_count=1`, keep `review_stage` as the current warmup stage, return `next_action=retry_same`.
- Second `off_topic` or unusable answer after the allowed follow-up: mark the current exercise plan as guided and advance to `exercise`.
- `off_topic` should not consume the same semantic meaning as `incorrect`; it exists to keep product messaging honest.
- Explicit "I don't know" remains `unclear` and follows the existing one-follow-up/guided-exercise limit.

### Skip Compatibility

The desktop client must stop converting typed `跳过` / `skip` into `action=skip`.

The backend may keep `action=skip` as a hidden compatibility path for older callers, but the product docs and desktop UI should not expose it.

### Desktop Behavior

Warmup is ordinary conversation:

- No skip button.
- No public skip prompt.
- No self-rating choices.
- Composer placeholder should ask for a short free-text answer without mentioning skip.
- Typed `跳过` / `skip` goes through the same `action=answer` path as any other text.

Formal exercise remains one card per question:

- Active exercise is rendered as a conversation attachment card.
- Completed cards retain submitted code, blanks, patch answer, explanation, run output, and feedback after reload.
- Intermediate wrong answers show immediate lightweight feedback in the completed card or adjacent transition area.
- Batch completion shows a concise final summary separate from per-card feedback.

### Error Contract

Use existing backend error envelope rules. `MODEL_UNAVAILABLE` should be recoverable and should not leak provider details.

For warmup-result failures after two model attempts:

```json
{
  "error": {
    "code": "MODEL_UNAVAILABLE",
    "message": "模型暂时不可用，请稍后重试。",
    "recoverable": true,
    "next_action": "retry_same"
  }
}
```

Exact Chinese wording can follow existing route error helpers.

## Compatibility And Migration

- Existing persisted review sessions without `off_topic_count` default to `0`.
- Existing `skipped` warmup states remain readable.
- The hidden `action=skip` path remains available unless implementation proves it creates complexity or safety risk.
- API docs should describe the public desktop behavior separately from hidden compatibility.

## Trade-Offs

- Returning `MODEL_UNAVAILABLE` instead of a local fallback can block review during model outages, but it respects the product decision that off-topic steering must be model-authored.
- Not adding semantic naturalness validation avoids over-engineering and false positives; quality is controlled through prompts and tests with representative model outputs.
- Keeping backend `skip` compatibility reduces break risk while allowing the desktop experience to remove skip affordances.

## Validation Strategy

- Backend tests for warmup `correct`, `incorrect`, `unclear`, and `off_topic`.
- Backend tests for first off-topic retry-same behavior and persisted `off_topic_count`.
- Backend tests for second off-topic advancing to guided exercise.
- Backend tests for model output blocked once then succeeding on second generation.
- Backend tests for model output blocked twice returning `MODEL_UNAVAILABLE`.
- Frontend build/typecheck for updated response types and no special skip conversion.
- Documentation updates in API and frontend interaction specs.
