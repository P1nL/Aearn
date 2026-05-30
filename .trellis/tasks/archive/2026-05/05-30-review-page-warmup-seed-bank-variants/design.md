# Design

## Current State

- `aearn/services/api/app/services/review_repository.py` owns `GET /api/reviews/today`, `POST /api/reviews/start`, and review exercise submit.
- `POST /api/reviews/start` currently loads a due review context, creates or reuses an active `learning_sessions` row with `session_type='review'`, picks or creates an `Exercise`, and returns `review_exercise`, `variant_reason`, and `initial_agent_message`.
- `aearn/services/api/app/services/review_conversation.py` stores `review_messages` and streams short review coach text.
- `aearn/services/api/app/services/review_scheduler.py` updates `review_states` and `review_logs` from `Attempt.fsrs_rating`.
- `docs/architecture/fsrs-scheduling-spec.md` already states that only `Attempt(attempt_type=submit)` and `Attempt(attempt_type=review_submit)` can update `ReviewState`.
- `aearn/apps/desktop/src/pages/ReviewPage.tsx` loads due items, starts a review, renders a single review exercise, streams review chat, and submits the exercise result.

## Target Flow

```text
GET /api/reviews/today
POST /api/reviews/start
  ensure due ReviewState
  ensure review_seed_bank
  select seed
  materialize/reuse review exercise
  persist review session stage state
  return warmup + selected exercise shell
learner answers warmup or skips
  persist warmup result
  move to variant_practice or warmup_repair
learner completes variant exercise
POST /api/reviews/{session_id}/exercise-result
  run/reuse runner evidence when applicable
  evaluate Attempt(review_submit)
  update ReviewState + review_logs
  return feedback + due_at + forget_risk
```

## Review Session State

Add review-specific state on `learning_sessions` rather than overloading learning-only stage fields:

```text
review_stage: warmup | warmup_repair | variant_practice | submitted
review_stage_state_json: jsonb
```

`review_stage_state_json` stores the replayable state for one review session:

```json
{
  "knowledge_point_id": "uuid",
  "seed_bank_id": "uuid",
  "seed_id": "seed_state_scope_review_patch_01",
  "warmup": {
    "question": "short recall or judgment prompt",
    "expected_focus": "state shared outside callback",
    "result": "pending",
    "repair_count": 0,
    "last_answer": null
  },
  "variant": {
    "exercise_id": "uuid",
    "exercise_type": "review_ai_patch",
    "guided": false,
    "selection_reason": "last weak point was state_scope_error"
  }
}
```

Rules:

- `review_stage` is only used when `session_type='review'`.
- Warmup updates change only `review_stage_state_json` and optional `review_messages`; they do not create `Attempt` rows.
- The selected seed and materialized exercise id are persisted before the first response is returned.
- Active-session replay returns the same seed, warmup, and exercise unless an explicit regenerate action is added later.

## Seed Bank Persistence

Use one persisted bank per user/knowledge point/generator version:

```text
review_seed_banks
  id uuid primary key
  user_id uuid not null
  plan_id uuid not null
  knowledge_point_id uuid not null
  generator_version text not null
  status text check in ('generating', 'ready', 'failed')
  seed_count integer not null default 0
  seeds_json jsonb not null default '[]'
  quality_report_json jsonb not null default '{}'
  failure_code text null
  failure_message text null
  generated_at timestamptz null
  created_at timestamptz not null default now()
  updated_at timestamptz not null default now()
```

Recommended unique key:

```text
UNIQUE(user_id, knowledge_point_id, generator_version)
```

The MVP keeps seeds inside `seeds_json` to avoid premature per-seed query complexity. If later analytics need seed-level history, split to `review_seed_bank_items`.

## Seed Schema

Each seed must be safe to materialize into an `Exercise` or review-specific exercise payload:

```json
{
  "id": "seed_state_scope_patch_01",
  "exercise_type": "review_ai_patch",
  "difficulty": 3,
  "target_misconception": "state_scope_error",
  "knowledge_point_id": "uuid",
  "runtime_tier": "browser_preview",
  "prompt_markdown": "Review the AI change against the requirement.",
  "starter_code": "",
  "visible_tests_summary": ["clicking twice should show 2"],
  "hidden_tests_summary": "hidden tests exist but are not disclosed",
  "metadata": {
    "requirement": "Counter must persist across clicks.",
    "original_code": "...",
    "ai_diff": "...",
    "review_focus": "state placement and test evidence",
    "expected_risk": "count reset on every click"
  },
  "rubric": {
    "verdict_correctness": "0-2",
    "evidence_grounding": "0-2",
    "knowledge_point_alignment": "0-2",
    "actionability": "0-2"
  }
}
```

For `code_blank`, `fix_bug`, `explain_code`, and `implement_function`, keep compatibility with existing `Exercise` fields and use `metadata_json` for seed id, misconception, and review focus.

## Seed Generation Inputs

Use safe, bounded context only:

- Official taxonomy/module placement.
- `KnowledgePoint.title`, `description`, `lesson_outline_json`, and `lesson_sources_json`.
- Runtime capability and supported exercise types.
- Common misconceptions from course templates and `weak_points_json`.
- Aggregated prior attempts: result, score, weak point tags, hint count, and high-level error cause.
- No hidden tests, full solution references, raw prompts, provider errors, secrets, or SDK internals.

## Generation Timing

Normal path:

- After plan confirmation or knowledge point creation, enqueue seed-bank generation for each knowledge point.
- Worker calls the generator, validates the full bank, persists `status='ready'`, and records quality report.
- Failure persists `status='failed'`, `failure_code`, and retry metadata.

Rescue path:

- `POST /api/reviews/start` checks for a ready seed bank.
- If missing or stale, it calls the same generator synchronously.
- The generated full bank must be persisted as `ready` before selecting a seed.
- If generation or validation fails, return `REVIEW_SEED_BANK_GENERATION_FAILED`.
- Do not fallback to a deterministic low-quality review exercise.

## Validation Rules

Reject the full bank if any rule fails:

- Normal knowledge point has fewer than 8 or more than 12 seeds.
- Core/high-risk knowledge point has fewer than 12 or more than 16 seeds.
- Required type coverage is missing.
- `review_ai_patch` coverage is missing when the knowledge point/runtime can support it.
- Any seed is not tied to the current knowledge point.
- Any seed is a duplicate by type, misconception, prompt, and code fingerprint.
- Any code block exceeds configured length limits.
- Any seed exposes hidden test code, full reference answer, raw prompt, provider error, API key, or secret.
- Single-choice warmup/check options, if generated, are outside 2-4.
- `review_ai_patch` lacks requirement, original code, AI diff, review focus, expected risk, or rubric.
- Difficulty is inconsistent with `ReviewState`, history, or knowledge point level.

## Exercise Type Selection

Selection is model-assisted or deterministic-scored, but it must use the same inputs:

- Current knowledge point and runtime capability.
- `ReviewState.card_state`, `lapses`, `last_fsrs_rating`, and `forget_risk`.
- `weak_points_json` and last review submit breakdown.
- Seed bank coverage and recently used seed ids.

The selector must not use a fixed ratio. It chooses the best next evidence task.

## `review_ai_patch`

Add `review_ai_patch` to exercise type validation across docs, backend schemas, frontend types, API contracts, and tests.

Learner output must include:

```json
{
  "verdict": "pass | fail | uncertain",
  "evidence": "diff/test/requirement grounded evidence",
  "knowledge_point_risk": "risk tied to the current concept",
  "next_action": "accept | reject | request_change | run_more_tests"
}
```

The frontend may render this as a structured form or a guided text area, but the submitted API payload must be structured enough for scoring.

Scoring dimensions:

- `verdict_correctness`
- `evidence_grounding`
- `knowledge_point_alignment`
- `actionability`

The result is stored in `Attempt.code_completion_result`:

```json
{
  "result": "partial",
  "score": 5,
  "score_breakdown": {
    "verdict_correctness": 2,
    "evidence_grounding": 1,
    "knowledge_point_alignment": 1,
    "actionability": 1
  },
  "review_ai_patch_result": {
    "verdict": "fail",
    "evidence_quality": "weak",
    "expected_risk": "state resets on every click",
    "learner_next_action": "request_change"
  },
  "weak_points": ["insufficient_test_evidence"],
  "feedback": "Conclusion is right, but evidence needs to cite the diff and requirement.",
  "next_action": "review_variant",
  "fsrs_rating": "Hard"
}
```

FSRS mapping constraints:

- Major verdict error maps to `Again`.
- Correct verdict with weak or ungrounded evidence maps to at most `Hard`.
- Correct verdict, grounded evidence, aligned risk, and actionable next step maps to `Good`.
- `Easy` requires strong scores across all four dimensions and no major uncertainty.

## API Changes

Add or extend endpoints:

- `POST /api/reviews/start`: returns warmup state, selected seed id, review stage, and review exercise.
- `POST /api/reviews/{session_id}/warmup-result`: persists warmup answer/skip and returns next stage.
- `POST /api/reviews/{session_id}/exercise-result`: accepts current exercise types plus `review_ai_patch` structured answer.
- Optional internal endpoint or worker task: `generate_review_seed_bank(user_id, knowledge_point_id, generator_version)`.

New error:

```json
{
  "error": {
    "code": "REVIEW_SEED_BANK_GENERATION_FAILED",
    "message": "Unable to generate safe review material for this knowledge point."
  }
}
```

Keep existing errors for due-state, validation, idempotency, model unavailable, runner unavailable, and evaluation conflict.

## Frontend Rendering

Review page should show:

- Due queue and metrics as today.
- Warmup card with answer/skip actions.
- Warmup result card with one correction max.
- Variant exercise card selected from the seed bank.
- Dedicated `review_ai_patch` UI with requirement, original code, AI diff, review focus, learner verdict/evidence/risk/action input, and submit validation.
- Loading state for start/rescue generation.
- Retry/back state for `REVIEW_SEED_BANK_GENERATION_FAILED`.
- Metrics refresh after successful review submit.

Frontend must not compute final score, FSRS rating, `due_at`, or `forget_risk`.

## Compatibility And Migration

- Existing review sessions can continue without `review_stage`; treat them as legacy `variant_practice`.
- Existing `Exercise.exercise_type` values remain valid.
- Existing review submit behavior remains valid for `code_blank` style exercises.
- Additive schema changes should be safe for local dev bootstrap and tests.
- If `review_seed_banks` is empty, rescue generation is the intended path.

## Operational Notes

- Async seed generation belongs in worker/background execution, but review start must not require the worker to have already succeeded.
- Rescue generation can be slower, so frontend must show a bounded loading state and retry.
- Generation must be idempotent by `user_id + knowledge_point_id + generator_version`.
- Generated seed bank quality failures should be observable without exposing raw provider details to the user.
