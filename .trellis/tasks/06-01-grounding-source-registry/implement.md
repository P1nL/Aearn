# Grounding source registry implementation plan

## Steps

1. Add focused tests for registry coverage, helper behavior, allowlist validation, trust-tier alignment, and no side effects on language capabilities.
2. Implement `app/services/grounding_sources.py` with immutable source descriptors and static source entries.
3. Add registry validation helpers and keep validation pure/in-process.
4. Run the focused backend tests.
5. Run the backend quality gate if focused tests pass.

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_sources.py tests/test_language_capabilities.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Risk Notes

- Do not add network calls, background fetchers, or runtime agent tools in this task.
- Do not change public course language ids, `enabled_for_public_selection`, or runner capabilities.
- Keep C++ and SQL trust semantics explicit because they are not single official-language tutorial docs.
- Keep source URLs stable and seed-oriented; broader crawling belongs to the fetcher task.

## Completion Gate

The task is ready for archive only after focused tests and backend lint/type checks pass, and no unrelated dirty files are staged.
