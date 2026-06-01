# Grounding source registry design

## Architecture

Add `aearn/services/api/app/services/grounding_sources.py` as the backend contract for official/trusted documentation grounding sources. Keep it adjacent to `language_capabilities.py` because the registry depends on canonical language ids and `source_trust_policy`.

The registry is a static service-layer module. It does not fetch network content at import time and does not expose a runtime agent web-search path. Downstream tasks will consume the registry for fetcher, chunking, retrieval, and citation work.

## Contracts

Define narrow literal types:

- `SourceTrustTier`: `official`, `trusted_de_facto`, `internal`
- `SourceSeedPolicy`: `seed_urls_only`
- `SourceContentType`: tutorial/reference/spec/platform-docs/vendor-docs

Define an immutable `GroundingSource` dataclass with:

- `source_id`
- `language_id`
- `display_name`
- `provider`
- `trust_tier`
- `seed_policy`
- `content_type`
- `allowlisted_domains`
- `seed_urls`
- `topic_tags`
- `notes`

Expose helper functions:

- `all_grounding_sources() -> tuple[GroundingSource, ...]`
- `sources_for_language(language_id_or_alias: str) -> tuple[GroundingSource, ...]`
- `get_grounding_source(source_id: str) -> GroundingSource | None`
- `allowlisted_domains_for_source(source_id: str) -> tuple[str, ...]`
- `seed_urls_for_language(language_id_or_alias: str) -> tuple[str, ...]`
- `validate_grounding_source_registry() -> tuple[str, ...]`

## Source Selection

Initial sources should be stable, documentation-oriented seeds:

- Python: Python Tutorial and library docs on `docs.python.org`
- JavaScript: MDN JavaScript guide/reference on `developer.mozilla.org`
- TypeScript: TypeScript Handbook on `www.typescriptlang.org`
- Java: `dev.java` learning docs and Oracle Java API docs
- Go: `go.dev/doc` and Go Tour
- C#: Microsoft Learn C# docs
- Rust: The Rust Book and standard library docs
- C++: `en.cppreference.com/w/cpp` as trusted/de facto documentation
- SQL: PostgreSQL tutorial/reference docs as trusted dialect documentation
- HTML: MDN HTML docs and WHATWG HTML spec
- CSS: MDN CSS docs

## Compatibility

The registry must not mutate `LANGUAGE_CAPABILITIES` or public course mappings. Planned languages may have documentation sources while remaining unavailable for public selection and execution. This keeps grounding readiness separate from runtime readiness.

## Validation

`validate_grounding_source_registry()` should perform deterministic in-process checks:

- Source ids are unique.
- Source language ids exist in `LANGUAGE_CAPABILITIES`.
- Every language capability has at least one source.
- Every source has non-empty seed URLs and allowlisted domains.
- Every seed URL has `http` or `https` scheme and its host equals or is a subdomain of one allowlisted domain.
- At least one source for each language is compatible with that language's `source_trust_policy`.

Validation should return error strings instead of raising, so tests and future startup checks can choose how strict to be.

## Rollout

This task only adds the registry and tests. No migrations, background jobs, external calls, or runtime behavior changes are required.

