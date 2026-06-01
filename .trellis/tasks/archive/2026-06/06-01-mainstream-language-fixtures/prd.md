# Mainstream language fixtures

## Goal

Add smoke fixtures and tests for Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS source handling.

## Confirmed Facts

- Source registry, fetch document shape, cleaning/chunking, retrieval, and citation adapters now exist.
- Tests should be offline and must not call live documentation sites.
- Fixtures must cover all `LANGUAGE_CAPABILITIES` ids, including planned/non-executable languages.

## Requirements

- Add deterministic fixture documents for every mainstream language id.
- Fixture documents must be built from registered grounding sources and seed URLs.
- Fixture documents must be compatible with `clean_and_chunk_document()`, `retrieve_grounding_chunks()`, and `grounding_results_for_agent()`.
- Fixture helpers must support all fixtures and per-language lookup.
- Tests must smoke the end-to-end in-memory grounding path across all target language ids.

## Acceptance Criteria

- [ ] Fixtures cover Python, JavaScript, TypeScript, Java, Go, C#, Rust, C++, SQL, HTML, and CSS.
- [ ] Every fixture references a registered source id and seed URL.
- [ ] Every fixture produces at least one chunk.
- [ ] Every language can retrieve and cite at least one fixture chunk.
- [ ] Planned languages remain non-executable and not public selectable.
- [ ] No network calls are made.

## Out of Scope

- Large real documentation snapshots.
- Golden embedding datasets.
- Live provider/API smoke tests.
