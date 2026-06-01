# Docs cleaning and chunking implementation plan

## Steps

1. Add tests for HTML cleaning, metadata propagation, deterministic ids/hashes, empty content, and chunk splitting.
2. Implement `app/services/grounding_processing.py`.
3. Run focused grounding processing/fetcher/source tests.
4. Run backend lint and type checks.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_processing.py tests/test_grounding_fetcher.py tests/test_grounding_sources.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Risk Notes

- Keep this deterministic and dependency-free.
- Do not persist chunks yet.
- Do not let raw HTML/script/style noise leak into grounded teaching chunks.
