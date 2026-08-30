# Aearn API Service

`aearn/services/api` owns the FastAPI public boundary and the current Tutor Harness runtime. It is not a Milestone-0 placeholder and must not recreate the removed onboarding/learning-session/top-level-review/notes SDK-Agent runtime.

## Responsibilities

- HTTP and SSE routes under `app/routes/`
- Tutor Harness, controlled Codex Sidecar selection, run lifecycle, queueing, persistence, projection, proactive delivery, and curation
- learning tracks, planning, lessons, teaching sessions, practice, model review, and review sessions
- PostgreSQL bootstrap/schema/seeds and scoped repositories
- provider-neutral LLM boundary and controlled runner registry
- deterministic tests, eval fixtures, redaction, idempotency, lease, and stale-fence enforcement

PostgreSQL owns durable state, queue/lease lifecycle, and effect authority. Redis/Celery deliver wakeups; model output never owns durable writes directly.

## Layout

```text
app/
  agents/       controlled Harness, runtime adapter, and versioned Skills
  core/         settings and cross-cutting safety helpers
  db/           connection, manifest-ordered schema fragments, bootstrap, and seeds
  models/       public request/response models
  routes/       HTTP/SSE transport boundaries
  services/     Tutor, learning, runner, grounding, LLM, and repository domains
tests/          domain folders for Tutor, learning, Codex, runners, grounding, DB, integration, and smoke
```

See [`../../../docs/README.md`](../../../docs/README.md) for the current source-of-truth index and [`../../../docs/architecture/tutor-harness-runtime.md`](../../../docs/architecture/tutor-harness-runtime.md) for runtime/security ownership.

## Dependency ownership

`pyproject.toml` and `uv.lock` are the API environment authority. The API environment uses editable local sources for `aearn-worker` and `aearn-shared`; do not add a repository-root Python environment or `requirements.txt`.

## Development and validation

From the repository root:

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
```

Schema execution order is declared by `app/db/schema/__init__.py`; SQL fragments never commit independently. PostgreSQL bootstrap-heavy tests run serially. Real-provider tests are explicit opt-in and must never record credentials, prompts, provider bodies, learner content, hidden tests, or raw diagnostics.
