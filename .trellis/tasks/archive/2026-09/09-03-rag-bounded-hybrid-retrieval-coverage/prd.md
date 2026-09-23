# Bounded Hybrid Retrieval and Coverage

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍只对exact已准入corpus检索与计算资料coverage，不自行抓取。后续题库用只读RagEvidenceBinding消费Subject/version/corpus/receipt，不把相似度当coverage；新后台摄入属于另一owner。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Goal

Replace fixed-count, language-only retrieval with exact Subject/version/facet-scoped PostgreSQL FTS, optional embedding augmentation, deterministic fusion, bounded evidence planning and server-owned coverage decisions.

## Dependencies

- Child 01 owns Subject, facet and capability contracts.
- Child 02 owns exact corpus/chunk persistence.
- Child 03 may provide fixture-published corpus for integration tests but does not own ranking.

## Requirements

- Build strict retrieval request, plan, candidate, evidence, budget and coverage contracts.
- Filter exact Subject/version/corpus/source/trust/facet before ranking.
- Query PostgreSQL FTS directly; do not load every language chunk and rank all content in Python.
- Add a versioned optional embedding port with disabled and deterministic fake adapters; no mandatory pgvector/provider dependency.
- Revalidate all embedding candidates against PostgreSQL scope and hash lineage.
- Fuse ranks deterministically and select evidence by uncovered required facets, trust, source diversity and total token/character/chunk budget.
- Return stable `satisfied|partial|insufficient|unavailable` coverage and bounded reason codes.
- Forbid framework-to-base-language fallback unless explicitly declared auxiliary scope still leaves framework facets independently covered.

## Acceptance Criteria

- [x] FTS-only retrieval is deterministic and works without embedding configuration.
- [x] Fake embedding can add/reorder candidates only inside the same exact corpus scope.
- [x] Missing/stale/wrong-dimension/wrong-corpus embedding output falls back to FTS without changing coverage correctness.
- [x] Simple and complex fixtures produce different bounded plans; `top_k=4` is not treated as coverage.
- [x] Required facet, source diversity, wrong version, stale corpus, budget exhaustion and fallback-denial tests pass.
- [x] Result and report hashes are stable under replay.
- [x] Focused tests, Ruff and Mypy pass.

## Out of Scope

- Production embedding provider or pgvector rollout.
- Learner-visible Lesson/Tutor cutover.
- Model-owned coverage decisions.
