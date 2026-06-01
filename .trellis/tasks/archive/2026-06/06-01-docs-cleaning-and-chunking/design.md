# Docs cleaning and chunking design

## Architecture

Add `aearn/services/api/app/services/grounding_processing.py`. It consumes `GroundingFetchDocument` and `GroundingSource` metadata, and returns immutable `GroundingChunk` objects for later retrieval and citation tasks.

## Contracts

Define:

- `GroundingSection`: section path, title, text.
- `GroundingChunk`: chunk id, source id, language id, title, section path, canonical URL, source type, trust tier, fetched timestamp, content hash, text, topic tags.
- `clean_and_chunk_document(document, max_chars=1200) -> tuple[GroundingChunk, ...]`

## Cleaning

Use a small `html.parser.HTMLParser` implementation so the task does not add dependencies. It should collect headings (`h1`-`h3`), paragraphs, list items, and code/pre text, while ignoring script/style/head/nav/footer tags.

## Chunking

Create section-aware chunks. If a section exceeds `max_chars`, split on paragraph boundaries when possible and then hard-bound long text. Chunk ids are `sha256(source_id + canonical_url + section_path + chunk_index + text)[:24]`. Content hashes use full SHA-256 of chunk text.

## Compatibility

This is a pure in-memory transform. It does not modify `teaching_chunks`, routes, agents, or database schema.

