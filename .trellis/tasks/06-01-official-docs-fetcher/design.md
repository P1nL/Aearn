# Official docs fetcher design

## Architecture

Add `aearn/services/api/app/services/grounding_fetcher.py` as a pure service utility that consumes `grounding_sources.py`. The fetcher will be used by future reindex/worker flows, not by agent runtime tools.

## Contracts

Define:

- `GroundingFetchStatus`: `ok`, `blocked`, `failed`
- `GroundingFetchDocument`: source id, language id, canonical URL, final URL, content type, fetched timestamp, raw content, content hash.
- `GroundingFetchResult`: source id, URL, status, optional document, optional error code/message.
- `GroundingHttpResponse`: status code, URL, content type, text.
- `GroundingHttpClient`: protocol with `get(url, timeout_seconds)`.
- `GroundingDocsFetcher`: orchestrates allowlist checks, caching, and result normalization.

## URL Allowlist

The fetcher must resolve the source by `source_id`, then require the requested URL host to equal or be a subdomain of that source's allowlisted domains. Blocked URLs must return a `blocked` result before HTTP is called.

## Failure Isolation

The fetcher catches HTTP client exceptions and non-2xx responses and maps them to `failed` results. Error messages are bounded and secret-free.

## Caching

Cache successful and failed/blocked results by `(source_id, canonical_url)` inside the fetcher instance. The cache is intentionally in-memory and scoped to one reindex run.

## Rollout

No routes, database writes, SDK tools, or background jobs are added in this task.

