# Adaptive Exercise Template System Implementation Plan

## Pre-Start Checklist

- [ ] User reviews `prd.md`, `design.md`, `implement.md`, and `review.zh.md`.
- [ ] Do not start parent task.
- [ ] Run `trellis-before-dev` for backend/frontend specs before code changes.
- [ ] Confirm whether `06-02-sql-query-runner` is complete before enabling SQL adaptive templates.

## Ordered Implementation

1. Add focused tests first:
   - canonical template selection
   - model candidate generation success
   - invalid model payload fallback
   - provider failure fallback
   - deterministic fallback/test fixture generation
   - runner validation success
   - validation failure fallback
   - unsupported/missing runner fallback
   - cache hit and cache miss
   - template version invalidation
   - user isolation/reset/delete/export behavior
   - hidden redaction
2. Add canonical template catalog module.
3. Add adaptive exercise service:
   - build bounded learner context
   - select template
   - request a model-assisted candidate inside the canonical template envelope
   - parse and validate the model candidate shape
   - use deterministic fallback when model generation fails or is unavailable
   - validate via runner
   - choose verified candidate or fallback
4. Add additive schema/cache support if needed:
   - `exercise_variant_cache`
   - indexes by user, knowledge point, template, version, status
5. Integrate materialization with `exercise_repository.py` and review seed flow without breaking existing behavior.
6. Update local user-data reset/export/delete handling for variant cache.
7. Add safe metadata to exercises and learner-safe API output where needed.
8. Run focused verification.

## Focused Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_adaptive_exercise_templates.py tests/test_runner_registry.py tests/test_local_user_data_boundary.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .trellis\tasks\06-02-adaptive-exercise-template-system
git diff --check
```

If desktop exercise payloads or settings views change:

```powershell
pnpm --dir .\aearn desktop:check
```

## Risky Files

- `aearn/services/api/app/services/exercise_repository.py`
- `aearn/services/api/app/services/review_seed_bank.py`
- `aearn/services/api/app/services/runtime_runner.py`
- `aearn/services/api/app/db/schema.sql`
- local user data boundary services and routes
- new adaptive exercise service/tests

## Rollback Points

- Feature-gate adaptive generation and return to existing `_exercise_template(...)` behavior.
- Feature-gate model-assisted generation and fall back to deterministic/template behavior.
- Treat variant cache rows as ignored or archived.
- Preserve canonical fallback templates.
- Disable SQL adaptive variants until SQL runner validation is green.

## Completion Criteria

- Every learner-visible adaptive variant is runner-validated before use.
- Model-assisted variants are the primary generation path and are runner-validated before use.
- Invalid variants fall back to canonical templates.
- Cache reuse is version-safe and user-scoped.
- Hidden data and solution references remain private.
- Focused tests and `task.py validate` pass.
- Implementation is committed without local unrelated dirty files.
