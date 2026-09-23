# Versioned RAG Corpus Authority

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍拥有不可变corpus及active generation CAS。后续v2新增service principal/policy/真实provenance receipt与撤权检查，不能伪造operator receipt；手工/自动并发都走同一active指针，不建第二corpus。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Goal

Add an additive PostgreSQL authority for immutable candidate/published corpus versions, one active pointer per Subject, frozen source/document/chunk snapshots and auditable lifecycle events while keeping legacy grounding reads unchanged.

## Dependencies

- Child `09-03-rag-subject-capability-taxonomy` owns Subject ids, version and release-state contracts.

## Requirements

- Add new schema rather than changing legacy `grounding_chunks` semantics in place.
- Persist corpus versions, active Subject pointers, source snapshots, document snapshots, chunks and append-only lifecycle events.
- Candidate content may be built and replaced only inside its own lifecycle; validated/published content is immutable.
- Activation and rollback update a generation-fenced pointer and never rewrite a published corpus.
- Enforce one active corpus per Subject, hash lineage, source/Subject/version scope and bounded JSON.
- Classify the new state as shared infrastructure in schema, reset/export/cutover inventories.
- Preserve existing Lesson source snapshots and legacy grounding tables.

## Acceptance Criteria

- [x] Bootstrap creates the new tables/indexes/triggers and succeeds twice.
- [x] Candidate → validated → published/retired and failure transitions are enforced.
- [x] Active pointer activation/rollback requires expected generation and references only published corpus rows.
- [x] Published source/document/chunk identity and hashes cannot be updated or deleted through ordinary paths.
- [x] Two concurrent activations produce one winner.
- [x] Legacy `grounding_chunks` and current Lesson/Tutor reads behave unchanged.
- [x] Schema manifest and data classification tests pass.

## Out of Scope

- CLI orchestration.
- Real network fetching.
- Retrieval ranking and coverage.
- Public consumer cutover.
