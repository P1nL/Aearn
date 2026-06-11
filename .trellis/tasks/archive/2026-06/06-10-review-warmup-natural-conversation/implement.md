# Review Warmup Natural Conversation Flow Implementation Plan

## Preconditions

- User has reviewed and approved `prd.md` and `design.md`.
- Task is started with `python ./.trellis/scripts/task.py start 06-10-review-warmup-natural-conversation`.
- Inline implementation reads relevant backend/frontend specs before editing code.

## Implementation Checklist

### 1. Backend Warmup Judgement Contract

- Extend review warmup judgement result constants to include `off_topic`.
- Update the warmup judge prompt schema and rules so unrelated answers produce `off_topic`, not `unclear`.
- Keep `feedback` short, learner-facing, and safe.
- Add one model retry for warmup judgement/steering failures when the model response is unavailable, invalid, or blocked by existing teaching safety guardrails.
- Preserve hidden `action=skip` compatibility.

### 2. Backend Review State Handling

- Add `off_topic_count` handling in `record_review_warmup_result`.
- Persist first off-topic response and return `next_action=retry_same` without creating an `Attempt`, review log, FSRS evidence, or schedule update.
- On second off-topic or unusable follow-up, mark current exercise as guided and advance to exercise.
- Ensure old sessions without `off_topic_count` default safely to zero.
- Ensure `MODEL_UNAVAILABLE` is returned after two blocked/unavailable model attempts and uses the standard error envelope.

### 3. API Types And Runtime Validation

- Update backend response examples/docs for `off_topic`.
- Update desktop API response type guards to accept `off_topic`.
- Remove desktop warmup skip intent conversion from typed `跳过` / `skip`.
- Keep frontend handling for legacy `skipped` values if returned by hidden backend compatibility.

### 4. Desktop Conversation UI

- Remove public skip wording from warmup prompts and composer placeholders.
- Ensure warmup remains ordinary dialogue with no self-rating choices.
- Keep exercise cards as conversation attachments.
- Ensure wrong formal exercise feedback stays immediate and lightweight.
- Ensure final summary remains separate from per-question feedback.

### 5. Tests

- Add/update `tests/test_reviews_m4.py` coverage:
  - correct warmup advances to exercise.
  - incorrect/unclear warmup follows the one-follow-up limit.
  - first `off_topic` persists steering feedback and returns retry-same.
  - second off-topic advances to guided exercise.
  - one blocked model output is retried.
  - two blocked/unavailable outputs return `MODEL_UNAVAILABLE`.
  - hidden `action=skip` remains compatible if kept.
- Add/update `tests/test_llm_integration.py` coverage for the warmup judge prompt/client contract.
- Update frontend type/build coverage through `desktop:check`.

### 6. Documentation

- Update `docs/architecture/api-contract.md`:
  - public warmup behavior.
  - `off_topic` judgement.
  - hidden skip compatibility, if retained.
  - retry-once then `MODEL_UNAVAILABLE` failure mode.
- Update `docs/product/frontend-interaction-spec.md`:
  - no skip button/prompt.
  - free-text warmup.
  - one-topic steering behavior.
  - one card per formal exercise.
  - immediate lightweight feedback plus final batch summary.

## Validation Commands

Run backend tests sequentially because Aearn API tests share bootstrap database state:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py -q
uv --directory .\aearn\services\api run ruff check app/agents/review/review_coach_agent.py app/services/repositories/review_repository.py app/routes/reviews.py tests/test_reviews_m4.py tests/test_llm_integration.py
pnpm --dir .\aearn desktop:check
git diff --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-10-review-warmup-natural-conversation
```

If `test_llm_integration.py` is too broad for the final local pass, run the added/changed tests by node first, then run the full file if time permits.

## Risk Points

- Do not let off-topic warmup paths create `Attempt`, `review_logs`, FSRS updates, or long-term review scheduling changes.
- Do not reintroduce fixed skip prompts through frontend placeholders or docs.
- Do not use model/provider error text as a user-facing message.
- Do not add a second semantic guardrail for naturalness; keep safety guardrails limited to existing protected categories.
- Do not split completed exercise card state from the conversation flow.

## Rollback

- Revert this task's code and docs as one unit if warmup submissions regress.
- Existing hidden `action=skip` compatibility should allow older clients to keep working during rollback.
- Persisted review sessions with `off_topic_count` should remain safe if ignored by older code because it is an additive warmup-state field.
