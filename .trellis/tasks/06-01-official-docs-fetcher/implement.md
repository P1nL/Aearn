# Official docs fetcher implementation plan

## Steps

1. Add unit tests with a fake HTTP client for success, blocked URL, HTTP error, cache hit, and language seed fetching.
2. Implement `app/services/grounding_fetcher.py` with typed result objects and injectable HTTP client.
3. Extend source-registry helper surface only if needed for public allowlist checks.
4. Run focused tests plus grounding source tests.
5. Run backend lint/type checks.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_fetcher.py tests/test_grounding_sources.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Risk Notes

- Do not call live documentation sites in tests.
- Do not add runtime agent web-search/browse behavior.
- Do not persist raw fetched content yet; chunking and storage are later tasks.
