# M4 FSRS 与复习闭环 Implementation Plan

## Implementation Checklist

- [x] Add backend tests for due queue, review start, review submit, idempotent scheduling, and run-only no-op behavior.
- [x] Add shared review scheduler service and migrate learning submit to use it.
- [x] Add review repository, request models, and `/api/reviews/*` routes.
- [x] Add worker due-count Celery task.
- [x] Update desktop review types, API client, and `ReviewPage`.
- [x] Run focused backend tests and desktop typecheck/build.
- [x] Run Trellis task validation and update docs only if implementation diverges from source-of-truth specs.

## Validation Snapshot

- `uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_worker_import.py`
- `pnpm --dir .\aearn desktop:check`
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-14-m4-fsrs-review-loop`
- `git diff --check`

## Validation Notes

- API pytest batches call `bootstrap_database()` against the same local database and should be run sequentially to avoid PostgreSQL deadlocks during schema re-bootstrap.

## Validation

- `python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py`
- `python -m pytest tests/test_onboarding_m2.py tests/test_worker_import.py`
- `pnpm --dir .\aearn desktop:check`
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-14-m4-fsrs-review-loop`

## Review Gates

- Planning gate: `prd.md`, `design.md`, and `implement.md` exist before `task.py start`.
- Code gate: No local FSRS mutation in frontend.
- Data gate: No duplicate `ReviewLog` or counter increment on repeated scheduling.
- Boundary gate: No historical tutorial runtime directories or removed draft flows are reintroduced.
