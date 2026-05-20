# MVP release readiness and third-party LLM integration

## Goal

Make the completed Aearn MVP usable for a real local release-readiness pass by:

- Verifying the deterministic MVP loop end-to-end against local PostgreSQL/Redis.
- Wiring a third-party OpenAI-compatible model API into the backend through `.env`.
- Adding a small, repeatable LLM quality gate so model-backed output is judged by evidence and structure, not by subjective "looks good" checks.

This task should keep the MVP narrow. It is not a new product-expansion milestone.

## Confirmed Facts

- The formal runtime lives under `aearn/`; repository root is for Git, Trellis, docs, and agent configuration.
- The current backend config loads `aearn/.env`, but `Settings` only reads app/API, database, Redis, and Celery values. It does not yet expose `LLM_TYPE`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, or `OPENAI_MODEL`.
- `aearn/.env.example` already reserves `LLM_TYPE=openai` plus OpenAI-style API key, base URL, and model variables.
- The desktop Settings page has a `model` tab, but it is read-only explanatory UI. Only `learning` and `notifications` tabs are editable in the current implementation.
- User preferences currently reject unknown fields, so model configuration is not yet a persisted user preference.
- Existing deterministic tests cover onboarding, learning sessions, reviews, and notes, but require PostgreSQL to be available.
- Existing frontend verification command is `pnpm --dir .\aearn desktop:check`.
- The intended manual smoke path is onboarding -> confirm plan -> start learning session -> run visible tests -> explanation check / explain error -> submit -> review / notes.

## Requirements

- Add backend configuration support for third-party OpenAI-compatible model endpoints through environment variables.
- Keep secrets out of Git. Real keys must live in local `.env` only.
- Route at least one real model-backed capability through the new model client before calling the task complete.
- Use `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error` as the first real model-backed path.
- Preserve deterministic fallback/testability for existing API tests so the MVP remains testable without a live model API.
- Document exactly how to configure a third-party API key and how to verify whether the request chain is using it.
- Add or update tests for configuration loading and model-client boundary behavior without requiring a real third-party key in CI/local default runs.
- Run local release-readiness checks after implementation.

## Acceptance Criteria

- [x] `aearn/services/api/app/core/config.py` exposes validated LLM settings for `LLM_TYPE`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL`.
- [x] The backend has a single model-client boundary for OpenAI-compatible providers; feature code does not read raw env vars directly.
- [x] `explain-error` uses the model client when `LLM_TYPE=openai`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` are configured.
- [x] `explain-error` still returns the existing required contract: `error_cause`, `explanation`, `fix_suggestion`, `related_knowledge_points`, and `next_action`.
- [x] `explain-error` model output is schema-validated before database writes; invalid JSON, missing fields, unsupported enum-like values, timeout, or provider failure must fall back to the deterministic response.
- [x] `explain-error` idempotency is preserved: the same `attempt_id` plus same error context returns the stored response and does not call the model again.
- [x] `explain-error` must not leak hidden test source, reference answers, real API keys, or raw provider errors to the user.
- [x] The response or server diagnostics include a non-secret marker that makes it possible to verify whether the output came from the LLM path or deterministic fallback.
- [x] A third-party OpenAI-compatible setup can be configured with `OPENAI_BASE_URL` and `OPENAI_MODEL` without changing code.
- [x] Local tests do not require a real API key.
- [x] Documentation explains setup, smoke verification, and failure signatures for missing/invalid third-party keys.
- [x] Release-readiness verification includes backend tests, desktop build check, API health check, and one manual or scripted smoke path.

## Out Of Scope

- Non-OpenAI-compatible provider adapters unless explicitly requested.
- Persisting API keys in the desktop UI or database.
- Account system, cloud sync, hosted deployment, or production secrets management.
- Adding new course domains or broadening the MVP language scope.
- Replacing the entire deterministic runner, FSRS, or scoring system with LLM-only logic.

## Decisions

- First model-backed path: `POST /api/learning-sessions/{session_id}/attempts/{attempt_id}/explain-error`.
- Model configuration source for this task: backend `.env`, not desktop settings UI or persisted user preferences.
- Provider scope: OpenAI-compatible third-party API endpoints only.
- Default local and CI behavior: no real API key required; deterministic fallback remains valid.
- Implementation verification used mocked OpenAI-compatible responses; live third-party key verification should be run only from a local `.env` that is not committed.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
