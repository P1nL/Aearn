# SQL query runner

## Goal

Implement the SQL L3 teaching runner for local-only query exercises. The first supported dialect is SQLite, disclosed as the "SQLite teaching dialect" everywhere learner-facing SQL execution appears.

This task moves SQL from `sql_later` planned metadata to a safe, capability-gated local runner only after the adapter, registry behavior, tests, API behavior, and disclosures agree.

## User Value

- Learners can practice SQL queries locally without installing or connecting to a shared database server.
- SQL exercises can validate visible and hidden query expectations while keeping hidden rows, expected outputs, and internal fixture setup private.
- Aearn can honestly explain that SQL runs in an isolated SQLite teaching database, not against the app database or a production database.

## Confirmed Facts

- Parent task `06-02-local-product-completion` defines Phase 2 as local user/data management, SQL L3 runner, and adaptive exercise validation.
- Runner parent `06-02-06-language-l3-runner-contracts` keeps concrete runner work in child tasks and must remain in `planning`.
- `aearn/services/api/app/services/language_capabilities.py` currently marks SQL as `execution="sql_later"`, `runner_key="sql"`, `supports_execution=False`, and not public-selectable.
- `aearn/services/api/app/services/runner_registry.py` currently has `SQL_RUNNER` as unsupported/planned metadata only.
- `aearn/services/api/app/db/schema.sql` currently restricts `runtime_profiles.runtime_tier` and `runtime_profiles.language` to the earlier MVP set; SQL runtime profile support needs an additive compatibility update.
- Existing PostgreSQL is Aearn's application database and must not be used as the learner SQL execution target.
- Previous archived task `06-01-sql-runner-contract` required fixture setup, teardown, query restrictions, timeout, deterministic comparison, and product-safe unsupported fallback.

## Requirements

- Depend explicitly on:
  - `06-02-local-product-completion` parent product boundaries.
  - `06-02-06-language-l3-runner-contracts` runner disclosure contract.
  - Completed Python, Node/TypeScript, and browser runner redaction patterns.
  - Completed `02-local-user-data-boundary` for attempt ownership and learner-safe result persistence.
- Implement a SQL adapter that executes only teaching query exercises in an isolated SQLite database created per run.
- Disclose dialect as SQLite teaching dialect in capability metadata, runtime profile metadata, API payloads, and desktop/settings surfaces touched by this task.
- Do not execute learner SQL against PostgreSQL, Aearn application tables, local files, network databases, or any shared database.
- Allow fixture-owned setup and seed SQL, then apply learner query restrictions before running learner SQL.
- Restrict learner SQL to a single read-only query shape for the initial implementation: `SELECT` or `WITH ... SELECT`.
- Reject multi-statement learner input, DDL, DML, `ATTACH`, `PRAGMA`, transaction control, extension loading, and file/database attachment attempts.
- Support deterministic result comparison from exercise metadata:
  - visible expected rows and columns
  - hidden expected rows and columns
  - ordered and unordered comparison modes
  - bounded row count and bounded cell serialization
- Return stable learner-safe statuses:
  - `success`
  - `runtime_error` for SQL parse/execution/comparison errors
  - `timeout`
  - `unsupported`
  - `missing_toolchain` only if the local Python `sqlite3` module is unavailable or disabled
- Redact hidden test case ids, hidden expected rows, seed data marked hidden, assertion internals, solution references, raw prompts, and internal runner exceptions.
- Update capability matrix, runner registry, runtime contract tests, environment/settings disclosure, and bootstrap/runtime profile compatibility together.
- Keep SQL public course selection disabled unless this task also adds reviewed SQL course content; runner executability alone is not enough to expose SQL as a public route.

## Acceptance Criteria

- [ ] SQL capability no longer overclaims or underclaims: it is executable only through the SQLite teaching dialect runner and remains non-public-selectable unless SQL course content exists.
- [ ] Runner registry selects a SQL runner for `sql_query_test` or equivalent SQL runtime profile and returns unsupported only for truly unsupported SQL modes.
- [ ] SQL runner runs a valid learner `SELECT` query against per-run fixture data and returns success with visible/hidden test summaries.
- [ ] SQL syntax or execution errors map to learner-safe `runtime_error` without leaking internal traceback or hidden fixture data.
- [ ] Long-running or runaway SQL maps to `timeout`.
- [ ] Missing/disabled SQLite support maps to learner-safe `missing_toolchain` or unsupported behavior according to the shared runtime contract.
- [ ] DDL, DML, multi-statement input, `ATTACH`, `PRAGMA`, transaction control, and file/database attachment attempts are rejected before execution.
- [ ] Hidden SQL test ids, hidden expected rows, hidden seed data, assertion SQL, and solution references are redacted in public runner output.
- [ ] Aearn's PostgreSQL application database is never passed to or mutated by the SQL runner.
- [ ] Focused backend tests cover success, visible failure, hidden redaction, query restriction, timeout, missing toolchain, registry selection, capability disclosure, and bootstrap compatibility.
- [ ] Existing runner, learning session, review, local user-data, lint, and type-check gates keep passing when practical.

## Out of Scope

- PostgreSQL/MySQL/DuckDB teaching dialect execution.
- Arbitrary learner database projects, migrations, stored procedures, triggers, extensions, or package installation.
- Running learner SQL against Aearn application database tables.
- Public SQL course exposure unless separately planned with content and route UX.
- Automatic installation or mutation of local database tooling.

## Open Questions

- None blocking planning. The recommended implementation dialect is SQLite. If product direction changes to PostgreSQL or DuckDB, update this task before `task.py start`.

## Notes

- This is a complex child task. It requires `design.md`, `implement.md`, and `review.zh.md` before `task.py start`.
- Keep parent tasks in `planning`; do not start `06-02-local-product-completion` or `06-02-06-language-l3-runner-contracts`.
