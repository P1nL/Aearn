# Grounding reindex observability

## Goal

Provide reindex commands, job status, metrics/logging, and regression checks for source fetch, chunking, and retrieval quality.

## Confirmed Facts

- Source registry, fetcher, processing, retrieval, citation, and fixtures exist.
- This task should expose a service-level reindex report path, not a production scheduler or CLI command yet.
- External fetch failures must be isolated from normal lesson/session startup.

## Requirements

- Add a reindex service that fetches configured sources, chunks successful documents, and returns a structured report.
- Report must include status, totals for sources/documents/chunks/failures, per-source status, and bounded error metadata.
- Partial failures must produce a completed-with-failures status rather than raising.
- Unknown source ids must be reported as failures.
- The service path must be testable with fake HTTP clients and must not call live documentation sites in tests.
- Fixtures should be usable as a no-network smoke path.

## Acceptance Criteria

- [ ] Successful reindex returns completed status and chunk counts.
- [ ] Mixed success/failure returns completed-with-failures and preserves successful chunks.
- [ ] Unknown source ids are reported as failures, not exceptions.
- [ ] Per-source reports expose fetched document count, chunk count, failure count, and error codes.
- [ ] Fixture smoke reindex covers all mainstream languages without network calls.
- [ ] No route, worker schedule, or production startup hook is added.

## Out of Scope

- Persistent job tables.
- CLI command wiring.
- Worker scheduling.
- Production metrics export.
