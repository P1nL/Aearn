# Design: Versioned RAG Corpus Authority

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍拥有不可变corpus及active generation CAS。后续v2新增service principal/policy/真实provenance receipt与撤权检查，不能伪造operator receipt；手工/自动并发都走同一active指针，不建第二corpus。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Schema Fragment

Add the next manifest-ordered additive schema fragment, provisionally `260_rag_subject_corpus.sql`.

Tables:

1. `grounding_corpus_versions`
   - Subject/version/registry digest, lifecycle state, generation, source/content hashes, policy versions and bounded validation/coverage summaries.
2. `grounding_active_corpora`
   - one row per Subject, published corpus pointer, generation, activation event and timestamp.
3. `grounding_corpus_source_snapshots`
   - frozen registry/source scope, trust, allowlist, version and facets.
4. `grounding_corpus_documents`
   - frozen document identity, canonical/final URL metadata, content type, fetched time, document hash and parse outcome.
5. `grounding_corpus_chunks`
   - exact corpus/document/source/Subject/version identity, bounded text, section path, facets/tags, hashes and generated FTS vector.
6. `grounding_corpus_events`
   - append-only reindex/validate/diff/activate/rollback/retire receipts.

## Repository

`corpus_repository.py` owns typed mapping, candidate writes, validation finalization, publication, active-pointer CAS, rollback selection, history reads and safe projections.

Published history remains immutable. Rollback advances the pointer generation to a prior published corpus; it does not reverse event history.

## Compatibility

Do not add foreign keys from existing Lesson or plan tables in this child. A later adapter can project selected v2 chunks into existing `LessonSourceSnapshot`. Existing v1 tables remain readable and are not backfilled automatically.
