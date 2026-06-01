# Implementation Plan

## Steps

1. Add page-specific allowed graph intent maps for onboarding and review routes.
2. Centralize onboarding graph output conversion/validation before route generation and confirm gating.
3. Centralize review graph output conversion/validation before start/warmup/submit/message routing.
4. Add regression tests for invalid graph output fallback and public response non-leakage.
5. Run focused onboarding/review graph tests plus backend lint/type checks.

## Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_reviews_m4.py -k "graph or langgraph"
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

## Review Gates

- Onboarding/review do not gain learning-runtime graph SSE frames.
- Invalid graph intent targets do not block stable service behavior.
- Public responses do not expose graph diagnostics or sensitive payloads.
- Durable writes remain in existing service/repository functions.
