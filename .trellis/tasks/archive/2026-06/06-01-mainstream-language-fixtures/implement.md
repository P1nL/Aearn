# Mainstream language fixtures implementation plan

## Steps

1. Add fixture coverage tests for all mainstream languages.
2. Implement `app/services/grounding_fixtures.py`.
3. Run focused grounding fixture and pipeline tests.
4. Run backend lint and type checks.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_fixtures.py tests/test_grounding_citations.py tests/test_grounding_retrieval.py tests/test_grounding_processing.py tests/test_grounding_sources.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```
