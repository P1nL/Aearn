# RAG Shadow Compatibility and Demo

## Ownership and phase

- `grounding/fixtures_v2.py` organizes deterministic scenario metadata around the existing immutable fixture policy; it does not replace its material or publish a real corpus.
- `learning/grounding_adapters.py` is an explicit internal-only seam. No public route, worker, startup, Lesson authoring or Tutor consumer calls it. It is the one exact non-grounding path allowed to import the v2 planner for server-owned plan revalidation; a separate inverse-reference audit forbids runtime consumers of this adapter. Do not generalize this exception to other learning modules.
- `aearn/scripts/rag_v2_demo.py` is an operator demonstration, not an app entrypoint. Its CLI writes only to an explicitly confirmed, separately provisioned disposable database.

## Compatibility is not authority

- Disabled adapter/status calls must perform zero database reads and return no citation/source material.
- Enabled conversion requires an exact request/result/plan/report hash chain, the currently active published fixture identity, and full sealed source/document/chunk verification. Candidate, retired, wrong version/hash/scope, partial/insufficient and malformed results fail closed.
- Legacy Lesson/Tutor shapes must remain inside a wrapper carrying synthetic provenance and public-blocked status. Public availability stays unavailable, including when a fixture corpus is active.
- Never insert v2 compatibility shapes as v1 `grounding_chunks` authority or valid HTTP ingestion provenance. Existing public Lesson/source-inspector validation stays unchanged.
- Reload all authoritative text, URLs, source/version/trust and hashes. Do not truncate content while retaining the old hash, invent metadata, use wall-clock timestamps, or let similarity substitute for required facets.
- Caller owns a coherent read-only transaction. The adapter must not commit, rollback, lock, mutate or invoke an external provider/retriever.

## Demo guards

- No implicit DB creation/bootstrap/cleanup. Require explicit opt-in and exact disposable database name before app imports, subprocesses or connection.
- Validate the resolved DB connection, not merely a URL prefix: remote hosts and DSN query overrides of host/database/service must fail closed. Never echo credentials, DSNs, raw stderr, provider data or source text on failure.
- Require .env disabled, provider disabled and public/runtime gates closed. Fake embedding is explicit synthetic interface validation only.
- Accept only an empty corpus state or the exact demo's own repeatable published identities; reject partial/foreign state without repairing or deleting it.
- Stable idempotency keys support replay. No learner-table writes, original database access, reset, retirement, public activation or deployment.

## Required evidence

- Unit tests: four route/six ecosystem scenarios; strict denial/fallback; default-off zero reads; safe status and exact legacy shape conversion.
- Disposable PostgreSQL: actual CLI subprocess reindex/validate/diff/activate, deterministic replay, FTS, valid fake and invalid/failing fake fallback, LangChain core blocked preflight.
- Main independent adapter probe: all ten Subjects, both Lesson/Tutor stages and named budget profiles, exact row content/hash checks, default-off and forged result denial, unchanged table fingerprints in the same READ ONLY REPEATABLE READ transaction.
- Public Lesson/Tutor/citation/plan/source-inspector and DB manifest regressions; full backend Ruff/Mypy/lock; Desktop typed/build; no-route/no-schedule scan; local documentation link and hygiene checks.
- Static scans do not prove every transitive import path; local Desktop build is not live UI acceptance. No-network fixture success is not real corpus, real embedding, sandbox health, public release or complete learning acceptance.
