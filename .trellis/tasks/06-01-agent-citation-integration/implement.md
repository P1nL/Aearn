# Agent citation integration implementation plan

## Steps

1. Add tests for citation metadata, deterministic citation ids, content bounding, score/reason preservation, and empty input.
2. Implement `app/services/grounding_citations.py`.
3. Run focused grounding tests.
4. Run backend lint and type checks.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_citations.py tests/test_grounding_retrieval.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```
