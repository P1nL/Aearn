# RAG Material and Source Contracts (Package A)

## Scope and ownership

`app/services/grounding/autonomous/` contains internal, deterministic contracts and policy checks. This is not a live discovery/ingestion service. No public route, worker, migration, provider adapter, database authority or learner-state consumer is connected by package A. Existing fixture/v1 identities and trust semantics remain unchanged.

The product decision for future B/D is: reuse reviewed applicable library material; use Tavily free-tier search for gaps; on quota exhaustion use only existing qualified library materials. Do not add native model search or another provider. Preserve unmet objectives and gaps; partial material readiness does not bypass prerequisites or formal Gate. A does not implement that runtime routing.

## Interfaces and trust boundaries

- `LearningMaterialDemand`, `SourcePreference`, `SourceDiscoverySuggestion`, `SourceCandidate` describe model-proposed needs or untrusted candidates, not authority.
- `SourceDiscoveryDemand` is a server-issued projection. `issue_discovery_demand` requires trusted access and a `QueryProjectionResolver`; regex validation is not privacy redaction. Never forward raw learner dialogue as search terms.
- `AuthorityResolver` resolves actor/action, exact demand/scope, current policy generation and canonical `RagBudgetDelegation`. A delegation is a reference, NOT a balance, reservation, signed authorization or a persistent ledger.
- `SourceAuthorizationResolver` resolves exact document/version/hash, storage and usage receipts and revocation state. A source origin (including official) is not a permission grant.
- `ClaimReceiptResolver` resolves the evidence backing a particular claim, with exact scope and source/isolated-execution applicability. Resolver implementations and authenticity belong to subsequent packages; synthetic test resolvers are not production authority.

Required joins: candidates carry `demand_hash` and `scope`; access requests also carry `purpose`. `AuthoritySnapshot` includes the full trusted `LearningMaterialDemand` and matching purpose, not only a caller-supplied hash. Discovery compares the full demand in one authority resolution before requesting a reviewed query projection. Source authorization additionally binds `lineage_family`, `origin`, `reading_level` and `reviewed`; callers cannot relabel a blog or its reading level while keeping the document identity.

`ClaimEvidenceReceipt` binds demand, purpose, admission and exact primary document/claim. Independent-source verification resolves the current corroborating document/revision/hash and family, rejects shared family, stale/revoked/unauthorized material, and does not treat an independence boolean as sufficient. Isolated execution additionally requires an `ExecutionReceiptResolver`; the separate receipt must bind claim, demand, document and exact `ExecutionScope`, be verified and not revoked. An execution id inside the claim receipt alone is insufficient.

## Validation and defaults

- Frozen, strict, extra-forbid models; bounded identifiers, arrays and text. Revalidate nested data at policy boundaries, including objects made through `model_copy` or `model_construct`; a matching hash does not prove trust.
- Candidate URLs belong only in discovery/probe contracts. Evidence request/binding contracts use server handles and exact coordinates, not arbitrary URLs, SQL, database targets or commands.
- Capture metadata distinguishes no body, prefix and full body. Prefix hashes must never be reported as full-document hashes. Repository-page metadata is not a pinned repository file.
- Four settings are independent and default false: `RAG_SOURCE_DISCOVERY_ENABLED`, `RAG_AUTO_INTAKE_ENABLED`, `RAG_AUTO_ACTIVATION_ENABLED`, `RAG_EVIDENCE_CONSUMER_ENABLED`. Existing public gates cannot turn these on. These defaults do not claim to control legacy runtime entrypoints.
- `check_access` checks its action gate before calling the resolver; closed gates/missing authority deny. Clock-dependent policy takes explicit `now` rather than reading wall-clock time.

Representative denial reasons: `GATE_CLOSED`, `AUTHORITY_MISSING`, `ACTOR_ACTION_DENIED`, `POLICY_SCOPE_STALE`, `BUDGET_UNAVAILABLE`, `SOURCE_STALE`, `USAGE_DENIED`, `CLAIM_VERIFICATION_REQUIRED`, `INDEPENDENCE_UNVERIFIED`, `EXECUTION_UNVERIFIED`. Invalid objects and resolver exceptions fail closed without returning exception text. These are bounded policy outcomes, not a public API error contract.

## Source permission is not assessment verification

`check_source` is a lower-level current storage/usage check, not final consumer authorization. `authorize_binding` composes actor/demand/scope access and source binding checks for teaching use. It must not approve an assessment binding without claim verification.

`authorize_assessment_claim` is the combined assessment boundary. A third-party document may be a main textbook without becoming assessment evidence. Independent corroboration must not count mirrors as separate origins; isolated execution only proves the exact recorded environment/input/claim scope. Model-authored statements such as 'I ran it' are not execution receipts.

## Required tests and nonclaims

Use the `test_rag_material_source_contracts`, `test_rag_source_access_policy`, `test_rag_source_usage_policy`, `test_rag_assessment_claims` and `test_rag_autonomous_boundary` suites with dotenv/provider/runtime disabled and a non-business database URL. Verify malformed/nested-copy input, default-off zero resolver calls, stale actor/policy/budget, storage versus usage, exact binding, same-origin evidence, missing execution receipts, and no public runtime imports.

Preserve old grounding hashes and regression tests. Offline success does not prove DNS/egress protection, URL permission, privacy classification, actual billing, claim truth, real corpus readiness, live search, publication or course completion. Do not bootstrap a business database or enable real searches to test these pure contracts.
