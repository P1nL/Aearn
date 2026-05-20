# Implementation Plan

## Preconditions

- Do not start implementation until the user approves this planning artifact.
- After approval, run `python .\.trellis\scripts\task.py start 05-20-mvp-release-readiness-llm-integration`.
- Load `trellis-before-dev` before editing code.

## Ordered Checklist

1. Extend backend settings.
   - Add LLM env fields in `aearn/services/api/app/core/config.py`.
   - Add helper validation for OpenAI-compatible configuration.
   - Add focused tests for default disabled behavior and configured OpenAI-compatible values.

2. Add model client boundary.
   - Create `aearn/services/api/app/services/llm_client.py`.
   - Support OpenAI-compatible `api_key`, `base_url`, and `model`.
   - Normalize configuration/provider errors into internal exceptions.
   - Keep the client mockable and prevent raw secret exposure.

3. Add explain-error LLM wrapper.
   - Create or extend a service around `explain-error` generation.
   - Build a compact evidence prompt from sanitized exercise, error, failed tests, current code, and knowledge point summaries.
   - Require JSON-only output matching the existing explain-error contract.
   - Validate and sanitize output before returning it to repository code.

4. Integrate with repository flow.
   - In `explain_learning_attempt_error(...)`, call the LLM wrapper before deterministic fallback when settings are enabled.
   - Preserve existing idempotency lookup before any model call.
   - Preserve `attempts.error_cause` update and `idempotency_records` storage.
   - Add a non-secret observability marker through optional response metadata or structured logs.

5. Update frontend only if response metadata is returned.
   - Extend `ExplainErrorResponse` with optional metadata fields.
   - Update `isExplainErrorResponse(...)` to validate optional fields if present.
   - Avoid adding desktop API-key persistence or editable model settings.

6. Update documentation.
   - Document third-party OpenAI-compatible `.env` setup.
   - Document how to verify `explain-error` used LLM vs fallback.
   - Fix the compose path in setup docs if touched by the release-readiness instructions.

7. Add tests.
   - Mocked LLM success path returns model-generated structured output.
   - Mocked provider failure falls back to deterministic output.
   - Invalid model JSON falls back to deterministic output.
   - Idempotent replay does not call the model twice.
   - Hidden-test path does not leak hidden source or full answers.

## Verification Commands

Run backend checks sequentially because the tests share local PostgreSQL bootstrap state:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py
uv --directory .\aearn\services\api run python -m pytest tests/test_reviews_m4.py
uv --directory .\aearn\services\api run python -m pytest tests/test_notes_m5.py
```

Run desktop verification:

```powershell
pnpm --dir .\aearn desktop:check
```

Run local smoke checks when services are available:

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
uv --directory .\aearn\services\api run uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Then execute the manual path:

```text
onboarding -> confirm plan -> start learning session -> run visible tests -> trigger explain-error -> verify LLM/fallback marker -> submit
```

## Rollback Points

- If model-client integration is unstable, keep config fields and route `explain-error` to deterministic fallback.
- If response metadata causes frontend contract risk, remove public metadata and keep verification through server logs/tests.
- If provider library behavior is incompatible with third-party endpoints, switch only the `llm_client.py` implementation while preserving the feature contract.

## Validation Record

2026-05-20 release-readiness closeout:

- PostgreSQL and Redis were confirmed healthy through `docker compose -f .\aearn\infra\docker-compose.yml ps`.
- Backend tests were run sequentially against local PostgreSQL: `test_db_bootstrap.py`, `test_health.py`, `test_llm_integration.py`, `test_onboarding_m2.py`, `test_learning_sessions_m3.py`, `test_reviews_m4.py`, `test_notes_m5.py`, `test_dashboard_resume_m6.py`, and `test_worker_import.py`; all 42 tests passed.
- Quality checks passed: `uv --directory .\aearn\services\api run python -m ruff check` and targeted `mypy` for `app\core\config.py`, `app\services\llm_client.py`, and `app\services\llm_explain_error.py`.
- Desktop build passed with `pnpm --dir .\aearn desktop:check`.
- A live HTTP smoke used local API server on `127.0.0.1:18001` with LatteCode `POST /v1/responses` streaming and `OPENAI_MODEL=gpt-5.4`. The flow was `health -> create user -> generate plan -> confirm plan -> dashboard -> start learning session -> failed visible_tests run -> explain-error -> idempotent replay -> fixed visible_tests run -> check explanation -> submit -> dashboard/resume`.
- Live smoke result: `explain-error` returned `generation_source=llm`, `generation_model=gpt-5.4`, and `error_cause=state_scope_error`; replay returned `idempotency_replayed=true`; final submit returned `result=easy`, `next_action=schedule_review`, and `fsrs_rating=Easy`.
- Temporary API process and smoke logs were removed after the run. A diff scan found no real LatteCode key in tracked changes.
