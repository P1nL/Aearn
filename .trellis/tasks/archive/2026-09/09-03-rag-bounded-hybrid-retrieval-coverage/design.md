# Design: Bounded Hybrid Retrieval and Coverage

## 2026-09-22 后续自主治理接缝（本child仍为阶段I）

本child仍只对exact已准入corpus检索与计算资料coverage，不自行抓取。后续题库用只读RagEvidenceBinding消费Subject/version/corpus/receipt，不把相似度当coverage；新后台摄入属于另一owner。 统一增量见 `../09-03-rag-language-ecosystem-adaptive-retrieval/autonomous-corpus-extension.md`；本child原正文描述阶段I，不因新增方向自动扩大其写集、开启真实环境或跳过最终规划批准。

## Pipeline

```text
request
→ resolve exact Subject/version/corpus
→ expand required facet queries
→ FTS candidates
→ optional embedding candidates
→ database scope/hash revalidation
→ deterministic rank fusion
→ greedy facet/diversity selection under budget
→ coverage report + selected evidence
```

## Main Contracts

- `GroundingRetrievalRequest`
- `GroundingRetrievalPlan`
- `EvidenceBudgetPolicy`
- `RetrievalCandidate`
- `SelectedGroundingEvidence`
- `CoverageReport`
- `GroundingRetrievalResultV2`
- `EmbeddingRetrieverPort`

## Ranking

Use rank-based fusion rather than comparing raw FTS and vector scores. Stable ties use trust rank, facet contribution, source id and chunk id. All selected candidates are loaded from the exact corpus repository before use.

## Coverage

A deterministic greedy selector prioritizes uncovered required facets, then compliant trust and source diversity. It stops when coverage is satisfied or the server-owned estimated-token/character/chunk budget is exhausted. Embedding similarity never marks a missing facet as covered.

## Stage Profiles

The contract supports plan_preflight, lesson_authoring, tutor_focus, practice and review profiles. This child implements policy objects and fixtures; public consumers remain unwired.
