# Grounding reindex observability implementation plan

## Steps

1. Add tests for successful reindex, mixed failures, unknown source, and fixture smoke reindex.
2. Implement `app/services/grounding_reindex.py`.
3. Run focused grounding tests.
4. Run full backend quality gate and desktop check for final 03 closure.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_reindex.py tests/test_grounding_fixtures.py tests/test_grounding_citations.py tests/test_grounding_retrieval.py tests/test_grounding_processing.py tests/test_grounding_fetcher.py tests/test_grounding_sources.py
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
```
