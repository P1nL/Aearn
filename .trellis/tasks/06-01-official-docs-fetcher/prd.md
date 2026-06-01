# Official docs fetcher

## Goal

Fetch allowlisted official documentation pages from lesson sources or configured seeds with caching, failure isolation, and no runtime web search.

## Confirmed Facts

- `grounding_sources.py` now owns canonical source ids, allowlisted domains, seed URLs, trust tiers, and language metadata.
- This task must fetch only URLs that match a registered source allowlist.
- Fetching is a service utility for offline/reindex flows. It must not add an agent runtime web-search tool.
- Cleaning, chunking, retrieval, citation formatting, fixtures, and reindex reporting are separate child tasks.

## Requirements

- Add a backend fetcher service that can fetch configured seed URLs for a source or all sources for a language.
- Fetching arbitrary lesson/source URLs is allowed only when the URL matches a registered source's allowlisted domain.
- Fetch results must use a typed result object instead of throwing for normal blocked/network/status failures.
- Successful fetches must capture source id, language id, canonical URL, final URL, content type, fetched timestamp, raw content, and content hash.
- Add in-memory caching by source id + URL so repeated fetches in one reindex run do not repeat HTTP calls.
- HTTP behavior must be injectable for tests and future worker integration.
- The fetcher must enforce timeout/status failure isolation and never expose raw provider stack traces through public result fields.

## Acceptance Criteria

- [ ] Registered source seed URLs can be fetched through a test fake client.
- [ ] URLs outside a source allowlist return a blocked result without calling HTTP.
- [ ] HTTP failures and non-2xx status codes return failed results without raising.
- [ ] Repeated fetches use cache and avoid duplicate client calls.
- [ ] Language-level seed fetching returns one result per configured seed URL.
- [ ] No route, SDK tool, or runtime agent web-search entry point is added.

## Out of Scope

- HTML cleaning and chunking.
- Persistent storage or database migrations.
- Retrieval ranking and agent citations.
- Background reindex orchestration.
