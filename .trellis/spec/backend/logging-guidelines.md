# Logging Guidelines

> How logging is done in this project.

---

## Overview

The formal Aearn backend currently has only dependency scaffolding in `aearn/services/api/pyproject.toml`. When FastAPI and worker code are introduced, logging must support local debugging of API, runner, LangGraph, database, and Celery flows without exposing code submissions, LLM keys, or user secrets.

Historical tutorial projects write logs under `logfile/app.log`, but the formal runtime must define its own service-local logging setup when the API service is created.

---

## Log Levels

- `debug`: local-only details for runner inputs, state transitions, and retry decisions. Keep disabled by default in normal runs.
- `info`: service startup, health checks, successful milestone operations, task registration, and high-level API lifecycle events.
- `warning`: recoverable problems such as stale client state, retryable runner timeout, unsupported runtime tier, or idempotency replay.
- `error`: failed durable writes, unexpected exceptions, invalid evaluator JSON after retry, worker task failure, or broken external dependency.

---

## Structured Logging

- Include `request_id` whenever an HTTP request, SSE stream, runner call, or LangGraph node execution is involved.
- Include stable IDs when safe: `user_id`, `plan_id`, `session_id`, `exercise_id`, `attempt_id`, `knowledge_point_id`.
- Include `idempotency_key` for write operations when available.
- Include `runtime_tier`, `runner`, and `runtime_status` for run/submit paths.
- Prefer structured fields over concatenated prose so future tests and support scripts can filter logs reliably.

---

## What to Log

- API startup and `/health` readiness.
- Migration start/end and migration version.
- Plan generation, plan confirmation, learning session start/resume, run, submit, review update, and note save outcomes.
- Runner status transitions: `success`, `runtime_error`, `timeout`, `unsupported`.
- LangGraph node failures and retries, including evaluator JSON validation failures.
- Celery worker startup, task registration, task retries, and final task status.

---

## What NOT to Log

- Do not log LLM API keys, `.env` contents, database passwords, Redis URLs with credentials, or auth tokens.
- Do not log full code submissions, full note bodies, or raw user background text by default.
- Do not log complete LLM prompts/responses unless a local debug mode explicitly redacts secrets and user content.
- Do not log raw stack traces into user-facing responses. Keep traces in logs and map API responses to stable error codes.
