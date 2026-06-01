# Grounding reindex observability design

## Architecture

Add `aearn/services/api/app/services/grounding_reindex.py`. The service composes source registry, fetcher, and processing modules and returns structured reports plus chunks.

## Contracts

Define:

- `GroundingReindexStatus`: `completed`, `completed_with_failures`, `failed`
- `GroundingReindexSourceReport`: source id, language id, status, fetched document count, chunk count, failure count, error codes.
- `GroundingReindexReport`: status, totals, source reports, chunks.
- `run_grounding_reindex(fetcher, source_ids=None) -> GroundingReindexReport`
- `run_fixture_grounding_reindex() -> GroundingReindexReport`

## Failure Isolation

Per-source failures do not stop other sources. The top-level report status is:

- `completed` when at least one source ran and no failures occurred.
- `completed_with_failures` when successful chunks/documents exist and at least one failure occurred.
- `failed` when no source produced successful documents/chunks.

## Compatibility

No route, worker, scheduler, or startup hook is added. Future tasks can wrap the service in commands/jobs.

