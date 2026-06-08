# Technical Design: Review Candidate Pool Generation

## Summary

This child upgrades the current review seed bank into a batch-ready candidate pool while keeping the existing review start API compatible.

Current implementation facts:

- `aearn/services/worker/aearn_worker/review_seed_bank_core.py` owns the shared `GENERATOR_VERSION`, count/type/safety validation, and ready/failed persistence helpers.
- `aearn/services/api/app/services/repositories/review_seed_bank.py` builds model context and prompt, validates generated seeds, selects one seed for the current compatibility flow, and materializes it into `exercises`.
- `review_seed_banks.seeds_json` already stores the generated list and is keyed by `(user_id, knowledge_point_id, generator_version)`.

Target for this child:

- Introduce `review_candidate_pool_v1` as the baseline pool contract.
- Store candidate-pool content in the existing `review_seed_banks.seeds_json`.
- Add schema and validation for selection metadata needed by later graph/session-state children.
- Preserve no-fallback behavior and existing `/api/reviews/start` compatibility.

## Versioning

Recommended constants:

```python
GENERATOR_VERSION = "review_candidate_pool_v1"
_REVIEW_CANDIDATE_POOL_PROMPT_VERSION = "review_candidate_pool_prompt_v1"
```

Use `generator_version` to separate old `review_seed_bank_model_v2` rows from the new candidate pool. No data migration is required for this child because the unique index already includes `generator_version`; old rows can remain unused by the new generator.

## Persistence

Baseline pool remains in `review_seed_banks`:

- `seeds_json`: full candidate list.
- `seed_count`: candidate count.
- `quality_report_json`: coverage, safety, model, prompt and adaptation metadata.
- `status`: `ready` or `failed` based on validation.

Do not create a new global candidate-pool table in this child.

Adaptive supplements are not persisted to `review_seed_banks`. Later graph/session-state work should store them under `LearningSession.review_stage_state_json.pool.adaptive_supplements`.

## Candidate Schema

Candidate object:

```json
{
  "id": "candidate_001",
  "knowledge_point_id": "uuid",
  "exercise_type": "code_blank",
  "difficulty": 2,
  "capability": "basic_application",
  "target_misconception": "state_scope_error",
  "focus_tags": ["state", "event_callback", "scope"],
  "recommended_for": {
    "recall_levels": ["fuzzy", "wrong", "skipped"],
    "weak_points": ["state_scope_error"],
    "after_result": ["failed", "partial"]
  },
  "avoid_if": {
    "already_passed_focus_tags": ["state_scope_error"],
    "recent_candidate_ids": ["candidate_001"],
    "unsupported_runtime_tiers": []
  },
  "title": "State scope review",
  "prompt_markdown": "Complete the focused review task.",
  "starter_code": "let count = 0;",
  "code_blanks": [],
  "test_cases": [],
  "metadata": {
    "selection_reason": "Confirm state persistence across event callbacks.",
    "is_core": true
  }
}
```

Allowed capabilities:

- `basic_application`: normally `code_blank` or `implement_function`.
- `concept_explanation`: normally `explain_code`.
- `debugging`: normally `fix_bug`.
- `transfer_or_review`: normally `implement_function` in a changed context or `review_ai_patch`.

Allowed exercise types remain the existing review types:

- `code_blank`
- `fix_bug`
- `explain_code`
- `implement_function`
- `review_ai_patch`

## Validation

Shared worker validation should reject:

- candidate count outside normal/high-risk ranges.
- unsupported `exercise_type` for the runtime tier.
- wrong `knowledge_point_id`.
- difficulty outside `1..5`.
- missing or invalid `capability`.
- missing or empty `focus_tags`.
- missing `recommended_for` / `avoid_if` object.
- missing `metadata.selection_reason` or non-boolean `metadata.is_core`.
- duplicate prompt/starter-code fingerprint.
- hidden answer, hidden test body, raw prompt, provider error, API key or secret leakage.
- invalid `review_ai_patch` metadata or rubric.

Coverage rules:

- Normal pool: 10-12 candidates.
- High-risk pool: 12-16 candidates.
- Hard cap: 18 candidates.
- Include at least three capabilities when runtime supports enough exercise types.
- Include at least one `basic_application` candidate and one `concept_explanation` candidate.
- Include `transfer_or_review` when `review_ai_patch` or `implement_function` is supported.
- Preserve existing `review_ai_patch` requirement when runtime supports it.

## Quality Report

`quality_report_json` should include at minimum:

```json
{
  "candidate_count": 12,
  "exercise_types": ["code_blank", "fix_bug", "explain_code", "implement_function", "review_ai_patch"],
  "capabilities": ["basic_application", "concept_explanation", "debugging", "transfer_or_review"],
  "core_candidate_count": 5,
  "focus_tag_count": 9,
  "high_risk": false,
  "generator_version": "review_candidate_pool_v1",
  "prompt_version": "review_candidate_pool_prompt_v1",
  "generation_source": "llm",
  "generation_model": "fake-review-seed-model",
  "adaptation_inputs": {
    "weak_point_count": 2,
    "mastery_score": 0.31,
    "last_fsrs_rating": "Again",
    "review_count": 4,
    "lapse_count": 2,
    "has_latest_attempt": true,
    "runtime_language": "javascript",
    "runtime_tier": "browser_preview"
  },
  "safety": "validated"
}
```

## Model Prompt

Prompt policy:

- Generate candidates, not a fixed display order.
- Cover multiple capabilities and weak points.
- Adapt to learner state and runtime support.
- Do not decide FSRS, due date, minimum review count, final rating, session completion, or persistence.
- Do not include `solution_reference`, hidden tests, raw prompts, provider errors or secrets.

Response shape:

```json
{
  "candidate_pool": {
    "candidates": [],
    "quality_notes": []
  }
}
```

For compatibility, `_seeds_from_generated(...)` may temporarily accept the old `seed_bank.seeds` shape, but new tests should assert the `candidate_pool.candidates` shape.

## API Compatibility

This child should not force the frontend to understand batch graph nodes yet.

`POST /api/reviews/start` may continue to return:

- `seed_bank`
- `selected_seed_id`
- `review_exercise`
- `warmup`
- `review_stage`

But the selected exercise metadata must preserve candidate-pool provenance:

```json
{
  "review_seed": {
    "seed_bank_id": "uuid",
    "candidate_id": "candidate_001",
    "capability": "basic_application",
    "focus_tags": ["state_scope_error"],
    "selection_reason": "Confirm state persistence across event callbacks.",
    "is_core": true
  }
}
```

Later graph/session-state work can use the same metadata to build `exercise_plan`.

## Selection Boundary

This child can keep a compatibility `select_review_seed(...)` path for the old one-exercise review flow.

Minimum upgrade:

- Prefer candidates matching weak points, `last_fsrs_rating=Again`, and supported runtime types.
- Avoid candidates whose `avoid_if.recent_candidate_ids` or already-passed focus tags apply when that context is present.
- Return a selected candidate with a stable `selection_reason`.

Do not implement full batch selection, minimum-count planning, adaptive supplements, or finalization in this child. Those belong to later child tasks.

## Failure Handling

On invalid model output:

- Reject the pool.
- Persist a failed row through the existing failed seed bank path.
- Return the existing stable review seed bank error path.
- Do not return `review_exercise`.
- Do not synthesize fallback questions.

Failure messages must remain bounded and must not store raw provider output, secrets, or prompts.

