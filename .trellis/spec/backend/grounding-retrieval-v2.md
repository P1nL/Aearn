# Exact-Scope Grounding Retrieval V2

## 1. Scope / Trigger

Phase-I `retrieval_contracts.py`, `retrieval_planner.py`, `hybrid_retrieval.py`, `coverage.py`, and future internal consumers. Corpus persistence remains owned by the existing corpus repository. Public Lesson/Tutor and legacy v1 retrieval are not switched in this child.

Pure deterministic fixture identity lives in neutral `corpus_fixture_policy.py`; `corpus_fixtures.py` remains an operator compatibility re-export. Retrieval imports only the neutral policy, never an operator entrypoint. Moving this code must preserve all existing fixture content, hashes and exports.

## 2. Signatures

- `GroundingRetrievalRequest`: exact Subject/version; discriminated active/exact corpus selector; bounded query; required/optional facets; stage; named budget profile; embedding mode.
- `ActiveCorpusSelector`: optional expected generation/summary hash. `ExactCorpusSelector`: corpus UUID plus required expected summary hash.
- `resolve_plan(conn, request)` resolves one immutable published corpus and a server-owned plan or a closed unavailable reason.
- `retrieve_grounding_v2(conn, request, *, embedding=None, synthetic_config=None)` returns `GroundingRetrievalResultV2`, selected evidence and `CoverageReport`.
- `EmbeddingRetrieverPort.search(EmbeddingSearchRequest)` returns bounded candidate identities, not authoritative text or facet claims.

## 3. Contracts

- Frozen, strict, extra-forbid DTOs. Callers cannot inject source URLs/ids, SQL, paths, user identities, DB targets or scalar budget overrides.
- Stages are plan_preflight, lesson_authoring, tutor_focus, practice and review; profiles are standard/compact. Required facets must be declared for that Subject. Frameworks never silently use base-language corpus evidence.
- Current phase-I supported corpus policy is the published synthetic fixture corpus. Unsupported source/version/policy or stale identities fail closed; do not imply real-source authorization from a published label alone.
- Resolve active once to an exact identity. Exact historical published references remain distinct from the current active pointer; retired/unpublished and wrong-summary requests cannot become valid evidence.
- Subject/version/corpus/source/trust/facet constraints are SQL predicates before ranking; PostgreSQL FTS uses stored tsvector and bounded per-facet/channel limits. Never reuse v1's load-all-language-chunks Python ranking for v2.
- RRF or another exact rank-based fusion is deterministic. Greedy selection prioritizes uncovered required facets, trust and source diversity, then stable identities, under aggregate character/estimated-token/chunk caps.
- Current usage budgets count returned evidence content. Estimated tokens use a conservative UTF-8 byte upper estimate, not provider usage; a future consumer must separately budget its complete prompt including metadata/system/context overhead.
- Fixture policy verification covers the complete bounded source/document/chunk set and sealed hashes, not only rows visible through a successful join. An extra unjoined source cannot become an admitted retrieval source.
- Adapter-output faults degrade to FTS; database query failures remain database failures, not fabricated embedding-unavailable success.
- Only selected DB-authoritative facets count toward coverage. Similarity cannot fill missing facets or waive source diversity/trust. `satisfied`, `partial`, `insufficient`, `unavailable` remain separate.
- Embedding is disabled by default. The only augmentation here is a deterministic fake adapter and explicitly synthetic server-owned receipt/config bound to exact corpus/content/registry identity. There is no production embedding index receipt or pgvector rollout.
- Reload every embedding candidate from the exact PostgreSQL scope and validate model/dimension/normalization/hash/receipt against trusted expectations. Missing, throwing, malformed, stale or cross-corpus output degrades to FTS without granting coverage.
- Hashes bind request/plan/exact evidence and coverage facts using canonical data, not wall-clock timestamps or nondeterministic float serialization. Fixture provenance must remain visible in the internal result.

## 4. Validation / Error Matrix

| Condition | Outcome |
| --- | --- |
| Unknown/undeclared facet, bad stage/profile, extra authority input | Strict rejection or closed unavailable result |
| Missing/unpublished/retired corpus, wrong version/hash/generation | No selected evidence; bounded reason |
| No embedding config or invalid adapter output | FTS continues; embedding-unavailable metadata, no forged facets |
| Missing required facets / too few valid sources | Partial/insufficient, not satisfied |
| Evidence does not fit character/token/chunk budget | Stop/skip according to deterministic selector; report exhaustion truthfully |
| Exact repeated request against unchanged immutable corpus | Same plan/result/report hashes |
| Retrieval under PostgreSQL read-only transaction | Works without writes, commits, or operator calls |

## 5. Good / Base / Bad Cases

- Good: one-facet and multi-facet requests have different bounded plans; both keep exact corpus identity, and the latter cannot pass merely because four chunks were returned.
- Base: FTS-only operation requires no embedding configuration and preserves current v1 consumer behavior.
- Bad: trust an adapter's source/hash/facet labels, read another corpus for a better semantic score, or call fixture coverage real-source/learner mastery evidence.

## 6. Tests Required

- Real disposable PostgreSQL: direct FTS, cross-corpus/language/version/retirement denials, source diversity, required facets, budget exhaustion, stable hashes and fake-embedding degradation.
- Independent read-only-transaction probe and exact scope assertions; fixture publication is setup outside that transaction.
- Static no-public-consumer/provider/network/automatic-entry boundary checks, without claiming a dynamic reachability proof.
- Regression for corpus authority/operator operations and legacy retrieval. Real fetch, embeddings, learner rollout and complete lessons remain unverified.

## 7. Wrong vs Correct

Wrong: `len(chunks) == 4` or a high vector score means the framework lesson is covered.

Correct: prove all required framework facets using selected exact-scope DB evidence, compliant trust/diversity and an unexceeded named budget; otherwise report the explicit gap.
