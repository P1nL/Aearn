# Grounding Corpus Operator Contracts

## 1. Scope / Trigger

Local phase-I `corpus_service.py`, `corpus_cli.py`, and `corpus_fixtures.py` changes. Read the existing database-guidelines corpus section for immutable storage/CAS; operator setup belongs in `docs/setup/development-environment.md`. These modules are not learner routes or worker entrypoints.

## 2. Signatures

Entry: `python -m app.services.grounding.corpus_cli`.

- `status --subject`
- `reindex --subject --subject-version --mode fixture|fetch --idempotency-key`
- `validate --corpus-id --expected-generation --idempotency-key`
- `diff --candidate-id --idempotency-key`
- `activate --candidate-id --expected-generation --summary-hash --idempotency-key`
- `rollback --subject --target-corpus-id --expected-generation --idempotency-key`
- `retire --corpus-id --idempotency-key`

`CorpusService` owns the operation transaction; `CorpusRepository` remains the only lifecycle/pointer writer. The CLI parses arguments, calls one operation, prints bounded single-line JSON and returns an exit code. It never bootstraps a database.

## 3. Contracts

- The only admitted version is `fixture-v1`. Fixture identity, source/facet mapping and canonical content hashes come from the server registry. Material uses `fixtures.aearn.invalid`, is synthetic, and must not be represented as fetched documentation.
- Four routes retain shadow posture and six ecosystems retain fixture-only posture. A fixture active pointer does not grant public admission or real-source authorization.
- `fetch` is reserved and fails with `FETCH_NOT_READY`, exit 2, without fetching or silently falling back to fixtures. Real ingestion governance is later work, not an implied capability of this command.
- Reindex creates an isolated candidate, preserves per-source failures, and never activates. Validate checks frozen scope/version/source identity, document/chunk hashes, required facets, bounds and FTS; it does not accept caller-supplied `passed` facts. Invalid/all-failed corpora cannot validate successfully.
- Validate and diff never move the active pointer. Diff binds its exact active baseline and replays the recorded baseline, not the latest pointer.
- Mutations require explicit idempotency keys. Same request replays the immutable receipt after later pointer/state changes; changed request conflicts. Retry does not insert snapshots again or allocate a different candidate for the same request.
- Activation requires the exact validated summary hash and expected active generation. Rollback selects a previous published version and advances generation; retirement refuses the current active target.
- Output contains safe ids, hashes, closed codes and bounded counts/projections only: no source body, DSN, password, raw SQL error or arbitrary exception text.

## 4. Validation / Error Matrix

| Situation | Expected behavior |
| --- | --- |
| Successful operation / valid replay | Exit 0; `ok=true`, safe JSON receipt |
| Invalid arguments, unsupported version/fetch, absent corpus or failed validation | Exit 2; safe closed error code |
| Stale CAS, conflicting idempotency, wrong activation hash, active retirement | Exit 3; `CORPUS_CONFLICT` and no partial mutation |
| Unexpected connection/runtime failure | Exit 4; `INTERNAL_ERROR`, no exception/credential echo |
| New operator import in route/learner/startup/beat path | Operator boundary gate fails |

Argparse help remains ordinary local help output, not an operation receipt. Standard output for operation results is one JSON line; diagnostics must not add a traceback to stderr.

## 5. Good / Base / Bad Cases

- Good: fixture reindex → validate → diff → explicit activate; second version activation → rollback to first; replay old operations returns their old receipts.
- Base: status on an empty, already bootstrapped test database returns no active pointer without creating content.
- Bad: activate during validation, treat rendered fixture text as external provenance, change a replay's diff baseline, or bootstrap the default learner database from CLI startup.

## 6. Tests Required

- Service and CLI tests for each operation, replay/conflict, malformed input, per-source/all-source failure, missing facet, tampered scope/hash, rollback and active-retire denial.
- Offline AST/registration audit for FastAPI routes, runtime imports, worker task/beat maps and dev startup. This is static wiring evidence, not a formal proof of every dynamic path.
- Actual CLI subprocess fixture sequence on an explicitly named disposable PostgreSQL database, including fresh-process persistence, old replay after pointer changes and safe connection errors. Guard the DB name before bootstrap/tests, run serially and drop only owned temporary databases.
- Re-run corpus authority tests after changing storage-facing orchestration. No browser, provider or real fetch is necessary for phase-I acceptance.

## 7. Wrong vs Correct

Wrong: catch a failed validation, return success, and advance active because a fixture exists.

Correct: persist a bounded failure receipt, leave the active pointer unchanged, and require a separately successful validation plus explicit hash/CAS activation.
