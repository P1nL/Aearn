# RAG B controlled discovery and candidate quarantine

This code-spec records executable B1/B2 boundaries. Product authority and acceptance remain in `docs/README.md` and its linked RAG design; this is not a new product spec. Package C owns formal admission and purpose/claim verification. No B candidate is an active corpus document.

## 1. Scope / Trigger

When editing `app/services/grounding/autonomous/` B modules, schema fragments `270`–`310`, `aearn_worker/worker_app.py`, or `aearn/infra/rag-b-egress/`, preserve **default-off** cost/network/storage authority. Campaign and private actor issuance share the B1 job/ledger, but both reconstruct the full current demand and actor rather than trusting a queue UUID or a hash. `QualifiedCorpusAdapter` must return unknown when C's current qualification authority is absent; an existing fixture, search snippet, or staged candidate cannot satisfy it.

## 2. Signatures and persisted identities

- `run_rag_worker_operation(*, operation, job_id=None, candidate_id=None, limit=None) -> dict`: queue inputs are canonical UUID selectors or a bounded retention limit, never grants. `dispatch`, `intake`, and `retention` are distinct routes on `rag-controlled`, with no B beat or public API route.
- `PostgresDiscoveryWork.claim_or_reuse(demand, projection, operation_id)` precedes `prepare_attempt` and durable `take_dispatch`. Provider I/O occurs **after** the one-shot dispatch CAS commits. `record_outcome` settles only with same-attempt observed usage evidence; unknown usage holds the reservation.
- `PostgresIntakeLeaseRepository.claim(candidate_id, candidate, probe, store, demand, gates, authority_resolver, capture_kind, planned_bytes, owner_id)` returns candidate-specific `IntakeLease(candidate_id, job_id, owner_id, generation, expires_at)`. `require_live_intake_lease` fences staging; `finish(success=True)` needs a persisted capture. `reconcile_captured(candidate_id)` marks an already-captured stale/idle lease done without refetching. The completed B1 discovery lease is **never** reopened for B2.
- `IntakeService.intake(...)` checks current probe/store grant, settled receipt, canonical root, candidate lease, each hop, and staging commit separately; never hold a DB transaction over network I/O. `CandidateStagingRepository.stage(...)` locks candidate then intake lease, refreshes DB clock after waits and before insertion, and rechecks exact storage policy.
- Schema manifest order is `260 -> 270 -> 280 -> 290 -> 300 -> 310`. `rag_candidate_intake_leases` is in 280; shared audit/ledger and private actor refs are separate. Schema/bootstrap is idempotent on an explicitly disposable `aearn_rag260_*` database; no root, campaign, candidate policy, or service principal is seeded enabled.

## 3. Contracts and environment

Four independent gates default false: `RAG_SOURCE_DISCOVERY_ENABLED`, `RAG_AUTO_INTAKE_ENABLED`, `RAG_AUTO_ACTIVATION_ENABLED`, `RAG_EVIDENCE_CONSUMER_ENABLED`. They are only brakes: `_load_operator_config()` remains `None` until a separately reviewed deployment injects current cost, network, storage, actor, qualification, key, and attestor authorities. `rag_campaign_definitions.intake_approved` defaults false; campaign `probe`/`store` require it in addition to current principal/campaign/period/cost/root and exact candidate policy. Retention cleanup has **independent operator approval** even while discovery/intake gates are off.

B1 Tavily responses create untrusted landing candidates and exact attempt usage observations, not document content. Only authoritative account-exhaustion evidence can return `existing_only`; 401, 429, timeout, unknown usage, and generic provider errors do not. B2 capture kinds: `none` uses HEAD and hashes the empty *response body*, not the remote document; `prefix` requires an exact 206 `Content-Range` and hashes only that range; `full` streams a bounded GET and may hash/parse the complete body. Never fetch full then truncate for a narrower grant. `offline_protocol_only` is not a live receipt; a live stage consumes a one-use receipt from the same concrete pinned TLS/fresh policy/signed egress fetcher. Page attribution cannot override the operator's current license grant.

The portable egress artifact in `aearn/infra/rag-b-egress/` is default-off and requires reviewed config/image, root-owned pins, a dedicated namespace, IPv4/IPv6 OUTPUT DROP, exact DNS/public-IP exceptions, a non-root worker with no capabilities, and a per-hop signed attestation. It is **not** evidence of production deployment isolation; the ignored one-off lab proof is scoped only to its own ephemeral container. Never include provider keys, query bodies, or fetched content in queue payloads, logs, task docs, or Git.

## 4. Validation and error matrix

| Condition | Safe outcome |
| --- | --- |
| Missing gate, operator approval, full actor context, qualification, root or exact candidate policy | `blocked_policy` / denial before provider or DNS; no implicit `.env` approval |
| Replayed/dispatched attempt, lost lease, unknown provider usage | No second Tavily dispatch; reserve remains held until authoritative reconciliation |
| Confirmed account quota exhausted | `existing_only` signal, not a new provider or permission to teach from unqualified material |
| Private/metadata IP, DNS rebinding, wrong peer/SNI, redirect outside current policy, absent signed egress | `SafeFetchDenied` before body retention; application check never substitutes for deployed firewall |
| HEAD with no body, strict 206 prefix, full bounded fetch | Distinct provenance/hash scopes; 200 to Range fails before reading full body |
| B1 job completed but no candidate-specific lease; stale generation, revoked policy, missing settled receipt | No B2 staging; no B1 lease reuse or ledger refund |
| Capture staged then process crashes before `finish` | Reconcile existing capture after lease expiry; never refetch/repopulate a scrubbed row |
| Expired/revoked retained body | Clear body and fragment text together; preserve only allowed non-secret audit facts and other actors' shared candidate facts |

## 5. Good / base / bad cases

- **Good:** current qualified corpus gap + full server-issued context + enabled root/campaign/actor + exact quota and candidate policy → one reserved/dispatched search, settled receipt, then a separately claimed B2 candidate lease and licensed bounded capture. C still reviews before any formal use.
- **Base:** existing qualified material sufficient or all gates off → no search/fetch. Retention may still clear expired bytes under separate approval.
- **Bad:** search snippet used as fetched text, a `completed` B1 lease forged into B2, a prefix `200` body truncated locally, a root grant inferred from a URL, or a test attestor presented as production proof → deny, not best-effort fallback.

## 6. Tests required and assertion points

- Run `tests/grounding/test_rag_b_*`, `tests/database/test_schema_manifest.py`, and `services/worker/tests/test_rag_b_worker_routes.py`; assert budget/dispatch CAS replay, unknown usage, campaign/private revocation, lease generation, receipt settlement, per-hop DNS/peer/redirect limits, exact range/HEAD/full provenance, retention and two-user export/reset/delete isolation. Test default-off routes separately from configured fake ports.
- Explicit disposable PostgreSQL: verify `current_database()`, bootstrap twice, and run B1/B2 PG tests; use rollback for test-owned rows. Run corpus repository/CLI/retrieval regressions in their own required disposable name prefixes. Run Ruff, Mypy app, offline lock check and `git diff --check`.
- Offline fake DNS/TLS/socket tests prove protocol behavior only. A bounded real transport smoke and an isolated namespace proof are separate evidence, and neither proves the production image, firewall backend, operator approval, C admission, or source-content retention rights.

## 7. Wrong vs correct

**Wrong:** `if gates.intake: stage(candidate_id, old_discovery_job_lease, fetched_body[:prefix_limit])` — a boolean gate, completed B1 lease and post-hoc truncation provide no authority.

**Correct:** resolve full current actor/campaign demand and exact policy; claim a settled candidate-specific `IntakeLease`; enforce HEAD or exact Range/full per grant through pinned TLS plus signed egress; recheck same candidate lease/root/license in the staging transaction; call `finish` or reconcile an already persisted capture without refetching.
