# SQL Query Runner Design

## Scope

This child implements a local SQL teaching runner using SQLite. The runner is for single-exercise query validation, not for arbitrary database development.

The design keeps SQL separate from Aearn's PostgreSQL application database. PostgreSQL remains only the product persistence layer.

## Architecture

### New Runner Adapter

Add a SQL runner adapter under `aearn/services/api/app/services/`, for example `sql_query_runner.py`.

The adapter should expose a small typed result boundary similar to the existing Python, Node/TypeScript, and browser adapters:

- `SqlExecutionResult`
- `SqlTestResult`
- `execute_sql_query_with_tests(...)`

The adapter owns:

- creating an in-memory or temporary SQLite database per run
- applying trusted fixture setup
- applying learner query restrictions
- executing the learner query under timeout and authorizer controls
- comparing results to visible and hidden expectations
- returning bounded stdout/stderr/error data

### Runtime Contract Integration

Update `language_capabilities.py` and `runner_registry.py` together.

Recommended runtime identity:

- execution mode: `sql_query_test`
- runner key: `sql`
- runtime tier: `sql_query_test`
- dialect metadata: `sqlite`
- presentation: `stdout` or `static_feedback` depending on existing UI contract, but the learner-facing text must disclose SQLite.

`LanguageCapability.supports_execution` must include SQL only when the SQL runner is implemented and validated.

### Database and Bootstrap Compatibility

`schema.sql` currently restricts runtime tiers and language ids to the earlier MVP set. This task should add an idempotent compatibility update for:

- `runtime_profiles.runtime_tier` including `sql_query_test`
- `runtime_profiles.language` including `sql`
- `runtime_profiles.runner` including `sql`

Add a SQL runtime profile seed in `seeds.py`, but do not necessarily add a public SQL course seed unless SQL route content is intentionally included.

If no SQL course is added, backend runner tests can still exercise SQL through in-memory exercise payloads.

### Exercise Metadata Contract

SQL exercises should keep fixture and comparison data in exercise metadata and test case rows.

Recommended metadata shape:

```json
{
  "sql": {
    "dialect": "sqlite",
    "setup_sql": ["CREATE TABLE ...", "INSERT INTO ..."],
    "max_rows": 50,
    "comparison": "ordered"
  }
}
```

Test cases use existing `test_cases` records:

- `input_json` may identify query scenario metadata.
- `expected_output_json` stores expected visible rows for visible cases.
- hidden cases use the same structure but must be redacted in public results.
- `assertion_code` should not be required for initial SQL comparison.

### Query Safety Boundary

The adapter should reject unsafe input before execution:

- multiple statements
- non-read-only statements
- DDL or DML
- `ATTACH`
- `DETACH`
- `PRAGMA`
- transaction control
- extension loading
- file-backed database access

Recommended controls:

- parse/shape checks for one statement starting with `SELECT` or `WITH`
- SQLite authorizer during learner query execution
- SQLite progress handler or equivalent timeout guard
- bounded fetched rows and bounded serialized cell values
- per-run connection that is closed and discarded after execution

Trusted setup SQL runs before learner query restrictions are enabled. Setup SQL is authored by Aearn templates, not by the learner or the model at runtime.

### Result Mapping

Map SQL runner statuses into the existing `RuntimeExecutionResult` shape:

- valid query and all tests pass: `runtime_status="success"`
- visible or hidden expected result mismatch: `runtime_status="success"` with lower pass rate and learner-safe failure messages
- SQLite parse/execution error: `runtime_status="runtime_error"`
- timeout/progress abort: `runtime_status="timeout"`
- disabled SQLite module or unavailable adapter dependency: `runtime_status="unsupported"` or explicit missing-toolchain branch if the shared contract adds it
- unsafe query rejection: `runtime_status="runtime_error"` with an actionable learner-safe message

Hidden cases must use generic public ids such as `hidden_case_2` and generic messages.

### UI and Environment Disclosure

The environment doctor and settings surfaces already expose capability/toolchain state. SQL should show:

- dialect: SQLite teaching dialect
- execution boundary: isolated per-run local database
- unsupported scope: PostgreSQL/MySQL/project databases are not run by this task
- missing-toolchain state only if `sqlite3` is unavailable

### Compatibility

- Existing Python, Node/TypeScript, browser, compiled-later, onboarding, learning, review, notes, and local user-data flows must continue to pass focused tests.
- SQL public route selection remains disabled unless content work is included.
- A failed SQL runner should not break non-SQL learning flows.

## Rollback

- Revert SQL capability from executable to `sql_later`.
- Remove SQL runtime profile seed or mark it archived.
- Keep unsupported SQL fallback behavior in `runner_registry.py`.
- Disable SQL exercise generation until runner tests are restored.
