# Implementation Plan: Review Graph Session State

## Scope Guard

Implement only batch session state initialization/recovery and `current_node` responses. Do not change the formal exercise submit scheduler boundary in this child.

## Ordered Checklist

1. Load `trellis-before-dev` and read applicable backend/test/docs specs.
2. Inspect current tests in `tests/test_reviews_m4.py` for start/reuse/warmup/cross-user expectations.
3. Update `schema.sql` review stage constraints to include batch stages while keeping `variant_practice`.
4. Add pure helpers in `review_repository.py` for:
   - `review_batch_v1` initialization
   - legacy state upgrade
   - stage derivation
   - current node serialization
   - warmup result -> recall-level diagnosis
5. Update `start_review_session(...)` to persist/return `review_batch_v1` and `current_node`.
6. Update `record_review_warmup_result(...)` to update batch diagnosis/stage and return `current_node`.
7. Update `review_graph.py` action names only where useful for batch-aware decisions; keep persistence in repository code.
8. Update `routes/reviews.py` warmup messages if needed so user-facing copy says formal review instead of a single variant when stage becomes `exercise`.
9. Extend tests for:
   - new start response `current_node`
   - active session reuse with same current exercise
   - warmup clear/fuzzy/wrong/skipped branches
   - no Attempt/ReviewLog/ReviewState writes from warmup
   - cross-user session protection
10. Update narrow docs only if this child changes API/schema wording.
11. Run validation commands and Trellis validation.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -k "review_start or warmup or session or current_node" -q
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py -q
uv --directory .\aearn\services\api run ruff check app\agents\graphs\review_graph.py app\routes\reviews.py app\services\repositories\review_repository.py tests\test_reviews_m4.py
.\.venv\Scripts\python.exe -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-08-review-graph-session-state
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-08-review-graph-adaptive-flow
git diff --check
```

Run `mypy` from `aearn/services/api`. If `uv run mypy app` hits the known uv trampoline path issue, use the direct venv Python command.

## Risky Files

- `aearn/services/api/app/services/repositories/review_repository.py`
- `aearn/services/api/app/routes/reviews.py`
- `aearn/services/api/app/agents/graphs/review_graph.py`
- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/tests/test_reviews_m4.py`
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/langgraph-state-machine.md`

## Rollback Points

- Keep `variant_practice` accepted in DB and state derivation.
- Keep `review_exercise` response compatibility field.
- Do not modify `submit_review_exercise_result(...)` scheduling behavior here.
- If batch state causes recovery issues, legacy state upgrade can return old `variant`-derived exercise node without data deletion.
