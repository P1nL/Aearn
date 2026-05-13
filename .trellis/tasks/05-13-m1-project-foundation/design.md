# Technical Design

## Scope Boundary

This task implements Milestone 1 only. It builds the runtime foundation that Milestone 2 will consume, but it does not implement onboarding, `plan_draft`, or confirmed plan APIs.

Target paths:

- `aearn/services/api/`
- `aearn/services/worker/`
- `aearn/apps/desktop/`
- `aearn/infra/`

Historical tutorial directories must remain untouched.

## Backend Structure

Create a small importable API package:

```text
aearn/services/api/
  app/
    __init__.py
    main.py
    core/
      config.py
      errors.py
    db/
      connection.py
      bootstrap.py
      schema.sql
      seeds.py
    routes/
      health.py
  tests/
```

`app.main:app` is the ASGI entry point for uvicorn and tests.

## API Health

`GET /health` returns a small JSON object:

```json
{
  "status": "ok",
  "service": "aearn-api"
}
```

If DB/Redis dependency checks are added, they should be optional or separate so the service can still start while local services are unavailable.

## Database Bootstrap

Use `psycopg` and SQL for M1. The bootstrap command should:

1. Ensure `pgcrypto`.
2. Create `set_updated_at()`.
3. Create M1 tables with compatible names and key fields.
4. Create indexes and constraints needed by smoke tests.
5. Upsert seed runtime profiles and language courses.

Recommended command:

```powershell
uv --directory .\aearn\services\api run python -m app.db.bootstrap
```

The SQL must be repeatable with `CREATE TABLE IF NOT EXISTS` and seed upserts.

## M1 Tables

Minimum required tables:

- `users`
- `runtime_profiles`
- `language_courses`
- `learning_plans`
- `plan_modules`
- `knowledge_points`
- `exercises`
- `attempts`
- `review_states`

Keep fields compatible with `docs/architecture/database-schema.md` but narrow to M1 needs where safe. Use UUID PKs, `timestamptz`, text enum checks, JSONB, and FK constraints.

## Seed Catalog

Seed entries:

- `rt_browser_js`
- `rt_browser_html_css`
- `rt_python_stdout`
- `rt_compiled_later_java`
- `rt_compiled_later_cpp`
- JavaScript DOM beginner course
- HTML/CSS interaction beginner course
- Python basic beginner course
- Java basic placeholder
- C++ basic placeholder

Java/C++ placeholder entries should have `compiled_sandbox_later` capability and must not imply execution support.

## Worker Skeleton

Create an importable Celery app under `aearn/services/worker/`, for example:

```text
aearn/services/worker/
  aearn_worker/
    __init__.py
    worker_app.py
```

It should read `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND`, register a `health.ping` task, and be importable without requiring the API app to run.

## Desktop Health Integration

The desktop shell should:

- Call `GET /health` at startup or on retry.
- Show API online when successful.
- Show API offline and a retry button when unavailable.
- Keep the Milestone 0 readiness panel visible.
- Avoid adding router/state libraries for this small check.

## Test Strategy

Backend tests:

- FastAPI `/health` with `TestClient`.
- SQL bootstrap can execute.
- Smoke insert/query relationships for user -> plan -> module -> knowledge point -> exercise -> attempt -> review state.
- Worker module imports and exposes the smoke task.

Frontend checks:

- TypeScript build passes.
- Health UI is resilient when API is offline. Automated browser testing is optional for M1, but build must pass.

## Rollback

- Local DB rollback can drop M1 tables in reverse dependency order, or recreate Docker volume if no user data matters.
- Desktop rollback is reverting `src/` health integration.
- Worker rollback is removing the skeleton module.
