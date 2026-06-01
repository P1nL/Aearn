# Mainstream language fixtures design

## Architecture

Add `aearn/services/api/app/services/grounding_fixtures.py` for compact offline fixtures. The fixtures are service-level test fixtures because future reindex/retrieval tests can reuse them without live network access.

## Contracts

Expose:

- `mainstream_grounding_fixture_documents(fetched_at=None) -> tuple[GroundingFetchDocument, ...]`
- `fixture_documents_for_language(language_id_or_alias, fetched_at=None) -> tuple[GroundingFetchDocument, ...]`

Each fixture uses the first registered source for the language and its first seed URL.

## Fixture Shape

Each document is short HTML with one heading and one paragraph containing the language display name and source topic tags. Content hash is deterministic from the raw fixture HTML.

## Compatibility

Fixtures do not imply runtime execution or public selection for planned languages.

