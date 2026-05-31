# Teaching Chunks Indexing Runtime Implementation Plan

## Checklist

- [ ] Inspect plan/exercise persistence points and `teaching_chunks.py`.
- [ ] Add synchronous idempotent indexing at the narrowest durable-content boundary.
- [ ] Ensure search is scoped to current knowledge point.
- [ ] Add regression tests for indexed search, re-index idempotency, and cross-knowledge-point isolation.
- [ ] Run focused tests, ruff, mypy, and task validation.

## Verification

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_teaching_chunks.py tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-teaching-chunks-indexing-runtime
```

