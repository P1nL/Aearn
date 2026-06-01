# Language aware retrieval implementation plan

## Steps

1. Add tests for language filtering, query/topic ranking, trust tier preference, unknown language, and fallback behavior.
2. Implement `app/services/grounding_retrieval.py`.
3. Run focused grounding tests.
4. Run backend lint and type checks.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_retrieval.py tests/test_grounding_processing.py tests/test_grounding_sources.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```
