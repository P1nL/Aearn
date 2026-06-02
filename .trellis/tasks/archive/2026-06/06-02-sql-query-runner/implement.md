# SQL Query Runner Implementation Plan

## Pre-Start Checklist

- [ ] User reviews `prd.md`, `design.md`, `implement.md`, and `review.zh.md`.
- [ ] Do not start parent tasks.
- [ ] Run `trellis-before-dev` for backend specs before code changes.

## Ordered Implementation

1. Add focused tests first:
   - SQL registry selection
   - SQL capability disclosure
   - SQL success with visible and hidden tests
   - visible result mismatch
   - hidden redaction
   - syntax/runtime error mapping
   - timeout/progress abort
   - unsafe query rejection
   - disabled/missing SQLite fallback if practical
2. Add `sql_query_runner.py` with typed result dataclasses and learner-safe public result conversion.
3. Add SQLite setup/query execution:
   - create per-run connection
   - apply trusted setup SQL
   - enable query restrictions
   - execute one read-only learner query
   - compare result rows
   - close connection
4. Integrate SQL runner into `runner_registry.py` and `runtime_runner.py`.
5. Update `language_capabilities.py`:
   - add `sql_query_test`
   - mark SQL execution support only after runner tests pass
   - keep public selection disabled unless SQL course content is intentionally added
6. Update `schema.sql` and `seeds.py` for SQL runtime profile compatibility.
7. Update environment doctor/settings disclosure if existing capability payloads do not already reflect SQL correctly.
8. Run focused verification.

## Focused Validation

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_sql_query_runner.py tests/test_runner_registry.py tests/test_language_capabilities.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .trellis\tasks\06-02-sql-query-runner
git diff --check
```

If UI/settings payloads change:

```powershell
pnpm --dir .\aearn desktop:check
```

## Risky Files

- `aearn/services/api/app/services/language_capabilities.py`
- `aearn/services/api/app/services/runner_registry.py`
- `aearn/services/api/app/services/runtime_runner.py`
- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/db/seeds.py`
- new SQL runner tests

## Rollback Points

- Revert SQL capability to `sql_later` and `supports_execution=False`.
- Keep `SQL_RUNNER` unsupported fallback if the adapter has to be disabled.
- Remove or archive SQL runtime profile seed if bootstrap compatibility fails.
- Leave public SQL route disabled unless separately proven.

## Completion Criteria

- Focused tests pass.
- SQL hidden test redaction is covered.
- SQL cannot mutate Aearn app DB or any shared DB.
- `task.py validate` passes.
- User-approved implementation can be committed separately from local unrelated dirty files.
