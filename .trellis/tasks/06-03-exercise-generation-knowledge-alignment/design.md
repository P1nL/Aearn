# Design: Exercise Generation Knowledge Alignment

## Architecture Boundary

This task changes the backend exercise-generation boundary only.

- Route and course taxonomy remain owned by `aearn/services/api/app/services/curriculum/plan_generator.py`.
- Internal canonical seed and runner-harness materialization remains owned by `aearn/services/api/app/services/exercises/exercise_repository.py`.
- Adaptive generation, validation, metadata, and cache behavior remain owned by `aearn/services/api/app/services/exercises/adaptive_exercise_service.py`.
- Runtime execution remains owned by `aearn/services/api/app/services/runners/`.
- New semantic validation should live under `aearn/services/api/app/services/exercises/syntax_validators/` or an equivalent exercise-validation package.

The core rule is: the model may generate the exercise, but the application owns language/runtime boundaries, safety checks, semantic alignment checks, runner validation, caching, retry policy, and honest failure behavior. Hard-coded deterministic templates may support internal seeding and validation, but they must not be presented as normal adaptive output after generation failure.

## Current Legacy Data Flow

1. Learning route creates `knowledge_points` with `title`, `description`, `skill_tags_json`, and exercise refs.
2. Learning session unlocks or materializes an exercise for the current knowledge point.
3. `exercise_repository._exercise_template()` currently selects a deterministic fallback based on language/runtime.
4. `adaptive_exercise_service.build_adaptive_exercise_template()` selects a canonical envelope and builds bounded model context.
5. The model candidate may replace learner-facing fields and solution code.
6. `_candidate_payload_from_generated()` schema-validates and safety-checks the candidate.
7. `_validate_candidate()` runs the candidate solution through the selected runner.
8. A validated candidate is cached; failures currently use the old deterministic fallback path. The target design replaces this user-visible fallback behavior with regeneration and honest failure.

## Target Data Flow

1. Load the current knowledge point with `skill_tags_json`, route/module context, lesson outline, weak points, and runtime profile.
2. Build a canonical seed envelope containing language, runtime, runner, exercise type support, internal harness summary, and hard safety boundaries.
3. Send a model-first generation request with required skill tags and lesson context.
4. Parse the candidate through a bounded candidate schema.
5. Run safety checks:
   - no forbidden learner-facing text
   - no hidden test leakage
   - no provider payload or secret leakage
   - no unsupported fields
   - no language/runtime/runner override
6. Run semantic alignment validation:
   - candidate claims target skill tags
   - language-specific validator checks required syntax/semantic markers
   - validation result is safe metadata only
7. Run existing runner validation through `run_exercise()`.
8. Cache only if schema, safety, semantic alignment, and runner validation all pass.
9. If validation fails, create safe validation feedback and ask the model to regenerate within the same request.
10. If the configured retry cap is exhausted, return an honest unavailable/error result instead of a hard-coded exercise.

## Model Context Contract

Add bounded structured fields to `_model_context()`:

- `required_skill_tags`: normalized list from `knowledge_points.skill_tags_json`
- `knowledge_point_title`
- `knowledge_point_description`: increase the limit only within a bounded cap
- `lesson_outline`: compact structured summary when available
- `module_title` / `module_description` when available
- `source_attribution` / taxonomy hints when available
- `weak_points`
- `language_id`
- `runtime_tier`
- `runner_key`
- `allowed_exercise_types`
- `generation_policy`: model may redesign exercise shape, but may not change language/runtime/runner or own grading authority

Do not pass unlimited raw lesson text. If long lesson content is needed, summarize or select the most relevant teaching chunks before prompt construction.

## Candidate Schema

Keep model output bounded. Initial allowed fields should remain close to the existing schema:

- `title`
- `prompt_markdown`
- `starter_code`
- `solution_reference`
- `metadata_json`
- `code_blanks`
- `difficulty`
- `estimated_minutes`
- `requires_explanation`

If Phase 2 needs richer freeform behavior, add allowlisted fields rather than accepting arbitrary objects:

- `exercise_intent`
- `target_skill_tags`
- `alignment_claims`
- `visible_examples`
- `requested_exercise_type`

`requested_exercise_type` should only be accepted if it maps to an existing UI/runtime-supported type. It must not alter `language`, `runtime_tier`, or `runner`.

The model must not produce authoritative `test_cases` in the first implementation. It may describe validation intent in safe metadata, but final grading must come from system-owned runner tests and semantic validators.

## Regeneration Feedback Contract

When a candidate fails validation, build a safe feedback object for the next model attempt. The feedback may include:

- `failure_stage`: `schema`, `safety`, `semantic`, `runner`, or `provider`
- `failure_code`: stable safe code such as `missing_required_skill`, `runner_validation_failed`, or `invalid_candidate_schema`
- `missing_skill_tags`: safe tag ids only
- `runner_status`: safe public runtime status only
- `public_test_summary`: bounded visible-test summary only
- `attempt_index` and `max_attempts`

The feedback must not include raw provider output, hidden tests, hidden expected values, full prompts, full submitted/generated code beyond bounded snippets, API keys, stack traces, or internal temp paths.

## Semantic Validator Interface

Create a small interface that can reject candidates after schema/safety validation and before cache persistence.

Example shape:

```python
@dataclass(frozen=True, slots=True)
class SemanticValidationReport:
    passed: bool
    failure_code: str | None
    matched_tags: list[str]
    missing_tags: list[str]
    validator_key: str
    validator_version: str
```

Example function:

```python
def validate_exercise_semantics(
    *,
    candidate_payload: Mapping[str, object],
    knowledge_point: Mapping[str, object],
    runtime_profile: Mapping[str, object],
) -> SemanticValidationReport:
    ...
```

The validator should inspect `starter_code`, `solution_reference`, `code_blanks`, and safe metadata. It should not execute code or access provider payloads.

## Language Strategy

- Python: use standard library `ast` first. Example: `list_comprehension` requires an `ast.ListComp` node in `solution_reference` or the filled solution.
- JavaScript/TypeScript: start with lightweight checks for selected tags; consider Acorn/Esprima only after dependency review.
- SQL: start with normalized token/regex checks for `SELECT`, `WHERE`, `JOIN`, `GROUP BY`, `ORDER BY`, and aggregation tags.
- Java/Go/C#: start with lightweight language-specific markers for functions, types, conditionals, loops, and tests; defer strict parsing unless needed.
- HTML/CSS: prefer structural/selectors/output checks over AST. For example, semantic HTML tags, accessible controls, flex/grid, media queries, and selector specificity.

## Coverage Matrix

Phase 0 should produce a matrix with columns:

- `language`
- `runtime_tier`
- `runner`
- `course/module`
- `knowledge_point_id`
- `knowledge_point_title`
- `skill_tags`
- `current_internal_seed_template`
- `model_context_coverage`
- `semantic_validator`
- `runner_validation`
- `known_gap`
- `priority`

This matrix should be committed as a Trellis research artifact or a task-local markdown file before implementation begins.

## Cache and Versioning

The current cache key includes `template_id`, `template_version`, `ADAPTIVE_TEMPLATE_GENERATOR_VERSION`, runner, and runtime tier.

This task should bump generator or prompt versions when:

- model context fields change
- prompt behavior changes from template rewrite to model-first freeform
- semantic validation becomes required
- candidate schema changes

If semantic validators have independent versions, include the validator key/version in adaptive metadata and consider it in cache invalidation.

## Retry And Honest Failure Strategy

Deterministic templates become internal seeds and harness references only. User-visible adaptive exercises must come from validated model candidates.

- model unavailable before any candidate -> `MODEL_UNAVAILABLE` or `EXERCISE_GENERATION_UNAVAILABLE`
- invalid model schema -> retry with safe `invalid_candidate_schema` feedback
- unsupported field -> retry with safe `unsupported_candidate_field` feedback
- safety failure -> retry with safe `candidate_safety_failed` feedback, without echoing unsafe text
- semantic validation failure -> retry with safe missing-tag feedback
- runner validation failure -> retry with safe runtime/test summary
- unsupported runner -> honest unavailable/unsupported runtime result, not a generic exercise
- retry cap exhausted -> honest unavailable/error result with recoverable retry guidance

All failure reasons must be safe to expose in metadata and logs. Do not include raw provider output, hidden tests, or solution references.

## Compatibility

- Existing deterministic exercise creation may remain available for internal seed/harness construction, tests, and explicit developer fallback modes, but it must not be the normal learner-visible response for failed adaptive generation.
- Existing tests for validation, hidden-output redaction, cache export/reset, and SQL runner behavior must remain valid.
- C++ remains static-only and must not enter executable validation.
- This work should not require a frontend redesign. If metadata display changes are needed, keep them minimal and behind existing exercise card contracts.

## Rollback

- Revert `_model_context()` to the previous compact fields.
- Disable semantic validators behind a feature/config guard if needed.
- Revert prompt/generator version changes and disable model-first generation if needed.
- Keep deterministic seed templates intact for internal harness construction and tests, but product rollback should still clearly disclose if adaptive generation is unavailable.

## Key Trade-Off

More model freedom improves personalization and knowledge-point fit, but it increases the chance of plausible wrong exercises. The system must compensate with deterministic boundaries, semantic validation, runner validation, bounded regeneration, and honest failure rather than by reducing the model back to simple wording rewrites or showing a hard-coded generic exercise.
