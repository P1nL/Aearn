# Grounding C Source Admission (default off)

## 1. Scope / Trigger

Use for `autonomous/registered_source_*`, source review/claim verification, `corpus_governance`, schema 320/330, and C Unix bridge/deployment code. C is not a public route or D/E consumer. The current operator lane is limited to an explicitly disposable `aearn_rag260_c_*` database. Offline tests, synthetic captures and a validated partial corpus are not real-source or production acceptance.

## 2. Signatures

### Provider-native Tavily acquisition (schema 430)
- `HttpxTavilyExtractTransport(enabled=False).extract(url)` uses the fixed Tavily API, one bounded request, no implicit retry/direct-fetch fallback. Query trimming is omitted. Exact returned Markdown/text, response hash, request ID and nullable usage are distinct from original HTML or origin transport proof.
- `TavilyCaptureRepository(conn)` dispatches before HTTP, settles once in a later caller-owned transaction, and resolves current provider provenance. `rag_provider_extraction_attempts` is not another corpus authority. Registered captures have exactly one of `fetch_attempt_id` and `provider_attempt_id`; provider captures are `provider_extracted`, never `live_egress_attested`, and cannot carry direct-worker proof/image fields.
- Inject `SourceReviewRepository(..., registered_provider_captures=repository)` explicitly. Without injection, legacy direct/candidate paths do not query provider tables. Policy/root/retention/revocation and exact uses still apply.
- `TavilySQLiteReviewVerifier` has its own Markdown profile/signature domain and verifies exact raw byte excerpts plus the existing SQLite oracle. It is a narrow SQLite quality adapter, not a universal correctness claim. It cannot use a text-format capture as Markdown or accept a legacy HTML receipt.
- `rag-d-live/tavily_acquire.py` is separate from DB-only `tavily_admission.py`; the acquirer/model never receives the service signing key. D CLI defaults to Tavily; explicit legacy direct mode is retained without automatic fallback. Probe output is not retrospectively admitted as a pre-dispatched capture. Old direct attempts, including failed/expired ones, remain unchanged.

### Legacy direct capture interfaces

- `PostgresRegisteredSourceRepository.take_dispatch(scope, operation_key=..., request_hash=..., now=...)`: durable first insert before network I/O; creates two process-local permissions in the same instance. `resolve(scope, now=...)` consumes one per pre-DNS/pre-dial check. A restarted instance cannot recover permissions from a dispatched row.
- `make_host_callbacks(dsn=..., verifier=..., decision_type=..., capture_record_type=..., worker_uid=..., worker_gid=..., dispatch_owner=..., worker_image_sha256=...)`: exact owner type and matching DSN required. Only a verified disposable database is accepted.
- Bridge `capture_store(scope, body, content_type, sha256, proof, now, peer_socket)`: seventh argument is the actual accepted Unix socket. Direct calls without the socket fail closed. The production callback returns a capture ID only after its transaction commits.
- `SourceReviewRepository(conn, verifier=...)`: caller-owned transaction; rechecks complete bytes and trusted quality findings. Missing verifier cannot project a current source authorization.
- `TrustedOperatorSQLiteSelectQualityVerifier(review=..., reviewer_key_id=..., reviewer_public_key=..., provenance=..., enabled=False)`: optional human intervention, not a required normal-flow gate. Checks a pinned Ed25519 operator judgment; its signature authenticates human judgment, not factual truth.
- `SQLiteSelectAutomatedReviewVerifier(review=..., service_key_id=..., service_public_key=..., provenance=..., enabled=False)`: normal opt-in trusted-service reviewer. Verifies an externally pinned service signature, current full capture/provenance, UTC expiry and finite SQLite-executed claims, and returns only exact reviewed excerpts and `supplementary_explanation`. Source workers and page text cannot sign this receipt; no key material is generated in the adapter. Current DB grants remain independently enforced.
- `PostgresCurrentCaptureProvenanceResolver(conn, verifier=..., worker_image_sha256=...)`: resolves a persisted exact transport-proof digest using externally approved pins; nullable fixture proofs fail closed. Check historical signed proof at settlement time while current policy/retention remains independently required.
- `CorpusGovernance(conn, authority=..., source_reviews=..., isolated_operator_enabled=False)`: same connection for review/corpus; existing `CorpusRepository` remains the lifecycle/pointer writer.
- `clear_registered_captures(conn, limit=100, operator_approved=False)`: caller-owned transaction, bounded cleanup; reports cleared capture bodies separately from preserved authorized history or blocked formal history.

## 3. Contracts

Registered scopes bind policy/generation/source/Subject/version/facets/exact HTTPS URL/host/path/root/dispatch UUID/byte cap. Registered fetches require full GET, redirects=0 and independently enforced compressed/expanded hard caps <=8 MiB (8,388,608 bytes), as approved on 2026-09-25. A source policy may impose a smaller cap. Base64 IPC framing has a separate bounded allowance for encoding and metadata; it does not enlarge the body grant. Do not forge B search/candidate receipts for operator registrations.

Default dispatch remains one exact URL across policies/generations. Schema 350 adds a separately operator-provisioned, immutable supplemental authorization for one new dispatch, bound to a terminal original attempt, exact new policy/root/URL/request hash/dispatch UUID and expiry. It cannot chain from another supplemental attempt or revive the original row. The root-only ARM explicitly carries its UUID; without it default denial remains. Disabling an enabled registered policy permanently revokes that generation.

Schema 390 permits at most one unused-authorization correction; a consumed supplemental dispatch remains spent even if its result is unknown. Schema 400 adds a distinct, explicitly operator-approved final credit only when the original and latest supplemental attempt are both terminal unknown: a new generation-3 policy/root and exact dispatch/request/URL, an immutable allowance and matching authorization, at most three total attempts under schema 400 alone, with no replacement/revocation of the spent final credit. Schema 410 separately permits one explicit generation-4 deployment-correction allowance in the same existing table after exactly three terminal unknown attempts, tracing the latest attempt to the same original generation-3 allowance. It requires a new exact current policy/root/dispatch/request and immutable approval reference; existing rows stay unchanged, original+generation is unique, issuance and dispatch serialize on the original attempt, and under schema 410 alone total attempts stop at four with no fifth or automatic issuance. Do not reset history, treat failed fetch as unused, or apply this quota extension automatically. For a large registered full GET only, the worker may choose a deadline up to 300 seconds; B FetchLimits stays <=30 seconds and the B pre-dial signed grant TTL stays 4 seconds. The C bridge completion nonce lasts 360 seconds from issue, and completion-frame send/settlement response gets a separate 30-second IPC timeout after the 2-second connect/peer check; report delivery is checked within 60 seconds of completion. These independent clocks must not be conflated with an age limit on the full body fetch. A bridge failure after dispatch is unknown, never an implicit retry.

Schema 420 adds one explicit operator freshness-refresh credit, not a retry: generation 5 requires the same four-attempt lineage, a complete settled generation-4 capture with `dispatched_at <= fetched_at <= settled_at <= DB now`, and expired but non-revoked generation-4 policy/root/capture/grant. New policy/root/dispatch/request and `standingpolicy.sourcefreshness.` approval bind the unchanged source, Subject/version/facets, exact URL, license, usages and history policy; byte cap cannot increase, and the new authority lasts at most 24 hours. Existing rows and clocks remain immutable. The original attempt serializes issuance/dispatch; only five total attempts are possible and generation 6 is denied. Replaying 410 fails closed for 5 until 420 is restored. A truncated response is not a capture; terminal failure consumes the fifth credit and must be reconciled to unknown, not replayed. Focused coverage: `tests/grounding/test_rag_c_expired_source_refresh.py` (success/old-history preservation, expiry/cleared/missing-grant denial, bootstrap/replay behavior).

Capture `transport_proof` contains bounded canonical bytes of the signed B pre-dial envelope and a separate authenticated worker report. The hash must match `transport_proof_sha256`; `attestor_key_sha256` and `worker_image_sha256` are operator pins. All four may be absent only on legacy/synthetic fixtures; their presence does not itself authenticate a production reviewer. Never write body text into logs/task artifacts.

Only namespace/firewall facts are signed by B's attestor. TLS, peer, response status and body information remain a report from the reviewed worker image over authenticated IPC. Do not call these independently signed HTTPS bytes. Bind the report to exact dispatch/request hash/URL/IP/B nonce/body hash/size and timestamps.

C link admission requires both the immutable review and registered policy to authorize permanent formal history. Temporary capture retention and immutable corpus-history permission are distinct. Clear `captured_body` on expiry/revocation; do not mutate sealed 260 chunks or historical citations. Current-use expiry does not authorize continued use, and read denial is not physical erasure of backups/WAL.

The automatic SQLite SELECT profile reads only an already authorized complete capture. It recognizes complete, exact visible HTML assertions from a fixed finite profile and checks those limited claims with actual in-memory SQLite execution; keyword presence, partial sentences, ambiguous markup and unsupported statements do not confer quality. Its domain-separated receipt binds service identity/profile, full-body hash and current provenance, exact byte offsets/hashes, oracle result, usage and expiry. The repository's paired `reviewed_usages`/`approved_excerpts` hooks fence admission and current read; `CorpusGovernance` accepts chunks only if they equal an approved excerpt, rechecking on candidate creation, validation, activation and qualification. No excerpt grants whole-page correctness, `main_teaching`, `assessment_evidence`, schema coverage or public consumer cutover. Human full-document review remains a separately trusted optional adapter.

## 4. Validation & Error Matrix

| Condition | Outcome |
| --- | --- |
| New owner after restart, third grant, different URL/policy scope | No grant; never another GET |
| Bare B envelope, no peer socket, wrong mapped UID/GID or signer pins | No capture |
| C bridge sees cross-PID peer PID=0 with exact trusted UID/GID | C bridge identity representation only; still require path/signature/deployment checks |
| B signer sees peer PID=0 or cannot verify `/proc/<pid>/ns/net` | Reject; source worker must share the controlled signer network AND PID namespaces, retain nonroot/zero capabilities, and pass current-signer negative/positive probes before ARM |
| Generation-4 correction requested with wrong chain, stale current authority, or four attempts already spent | Deny atomically; no old-row reset or fifth attempt |
| Model/page supplies `QUALIFIED`, no trusted verifier | No reviewed authorization |
| Self-hashed invented chunk absent from captured body | `CHUNK_INVALID` |
| Current source revoked, policy/root mismatch, missing retention/history | Deny validation/activation/qualification |
| `queries` only, full SQL asks for `schema` | Partial corpus may exist only in disposable DB; full demand stays gap |
| Missing independent exact assessment claim evidence | Assessment remains blocked |

## 5. Good / Base / Bad Cases

Good: a new operator policy and once-only dispatch, two current bridge grants, concrete pinned TLS fetch, peer-authenticated report, host atomic settlement, independent reviewer facts, exact retained chunks and CAS in a disposable DB.

Base: all modules imported with defaults; no network, dispatch or activation occurs.

Bad: reuse a dispatched row after a process crash; change policy ID to re-fetch the same URL; turn a signature over worker claims into asserted independent response proof; claim a test fake or domain name establishes technical correctness.

## 6. Tests Required

Run relevant `test_rag_c_*` suites, schema manifest/inventory tests, and adjacent A/B regressions. PostgreSQL tests must explicitly set `AEARN_RAG_C_TEST_DATABASE_URL`, check `current_database()`, and roll back fixtures. Include cross-policy URL uniqueness, two grants then denial, restart denial, exact proof/pin/body binding, missing real Unix peer, retention clearing, revoked source, wrong history grant, partial coverage and invented chunk denial.

Windows skips cannot prove Linux SO_PEERCRED. Exercise the host callback using a non-root Linux process and a real Unix socket plus disposable PG; synthetic signed fixtures still do not prove live egress. C bridge and offline-harness unit suites are separate from actual namespace/firewall proof.

Bootstrap capabilities must match required syscalls: control socket provisioning needs CHOWN; the egress diagnostic bootstrap needs NET_ADMIN and SETUID/SETGID/SETPCAP for setpriv. The worker must end with CapEff=0, CapBnd=0, NoNewPrivs=1. Confirm in the kernel, not merely Compose text.

## 7. Wrong vs Correct

Wrong: keep `cap_drop: ALL` and assume UID 0 can still chown a socket or switch worker identity. Correct: explicitly permit only the bootstrap operations, then prove zero worker capabilities.

Wrong: accept only peer PID>0 across containers. Correct: cross-PID-namespace peers can appear as PID=0; verify exact mapped UID/GID, root-owned immutable paths, pinned keys and separate network namespaces.

Wrong: call all tests passing a live C result. Correct: separately report unit tests, synthetic PG/Unix integration, actual Docker network proof, real GET, quality admission, isolated activation and production non-execution.
Runtime failure output must retain a bounded stage and an explicit allowlisted reason,
never arbitrary exception strings or cause chains. TLS certificate rejection and
TLS handshake failure remain distinct (`TLS_CERTIFICATE_DENIED` versus
`TLS_HANDSHAKE_DENIED`); neither permits disabling verification or retrying the
one-shot attempt. Diagnostic code changes do not retroactively establish a cause
for a historical generic failure, and require a newly pinned image before deployment.

## B full-capture admission lane (schema 360)

`PostgresCandidateGrantResolver` requires an explicit `rag_candidate_use_grants`
row for the exact capture hash, B policy/generation/root, Subject/version/facets,
license, usages and retention. Rows default off and are immutable except terminal
revocation. B's temporary store rule is necessary but never a formal-history grant.
The resolver rechecks completed discovery/intake and settled search accounting,
current access rules/root and complete body. `CorpusGovernance` audits either
registered or candidate capture via `SourceReviewRepository` and checks chunks
against its exact bytes; the existing corpus repository remains the only writer.
Synthetic B fixtures establish the code path, not a real provider/candidate review.

`review_operator.py` only prepares a root-private unsigned review draft after
current provenance verification. All quality judgments remain unknown, no key or
signature is produced, and no review/admission/activation is written. A draft or
local SQL execution check is not a substitute for the configured trusted reviewer.

## Automated service review execution contract (2026-09-25)

### 1. Scope / trigger
Use `sqlite_select_automated_review.py`, optional excerpt hooks, and
`automated_admission.py` for automated existing-capture review. Human signatures
are optional; they are not the normal-flow gate. This profile is limited to the
exact SQLite WHERE paragraph and LIMIT statement, not whole-page quality.

### 2. Signatures
- `evaluate(capture) -> AutomatedReviewEvaluation`: unsigned support probe only.
- `sign_service_review(capture, provenance, private_key, service_key_id, now, expires_at, enabled=False)` produces a domain-separated automated-service receipt.
- `SQLiteSelectAutomatedReviewVerifier(review, service_key_id, service_public_key, provenance, enabled=False)` exposes `verify`, `reviewed_usages` and `approved_excerpts`.
- `SourceReviewRepository.reviewed_excerpts(capture) -> tuple[str,...] | None`: `None` only for a legacy verifier with neither optional method. Paired methods are mandatory if either is present.
- `automated_admission.py --execute --config --capture-id --corpus-id --run-id --expected-active-generation --service-private-key --service-public-key --service-public-sha256 --receipt-output`: root-only, isolated C DB, no GET/provider call.

### 3. Contracts
Two complete exact source units and both `where_true`/`limit` claims are required.
The reviewer runs fixed SQLite queries, never SQL or instructions from the page.
The signed receipt binds full capture/provenance, service/profile identity,
SQLite oracle digest, exact byte spans/hashes, supplementary usage and UTC expiry
of at most 24h. Scope finding is not proof of the entire page/latest SQLite release.
The verifier recomputes these facts with a separately pinned public key; verification
requires no signing private key. Quality evidence hash is SHA256 of
`canonical_signed_review`, not of an unsigned payload.

All corpus chunks must exactly equal an approved excerpt, not simply occur in the
full body. Admission and dynamic resolution are limited to supplementary_explanation;
main_teaching and assessment_evidence remain denied. Current review and admission
rows are share-locked through verification. Full SQL still has a schema gap.

### 4. Validation / errors
| Case | Outcome |
| --- | --- |
| Missing/ambiguous supported units, altered statement or failed oracle | QUARANTINED, no admission |
| Partial/malformed optional hooks or exception | REVIEW_DENIED/current read unavailable |
| Unapproved but source-present chunk | CHUNK_INVALID |
| Broader main/assessment purpose | admission/current corpus denied |
| Expired/tampered receipt, key/body/provenance mismatch | no verified finding |
| Same completed run ID/corpus/receipt and current audit valid | already_completed_isolated_db, no pointer increment |
| Matching provisional receipt after DB rollback | reverify and reuse, never overwrite/re-sign it blindly |

### 5. Good/base/bad
Good: an existing authorized capture yields a service-signed two-excerpt
supplementary corpus, committed atomically and dynamically revalidated.
Base: no --execute / reviewer disabled, no changes. Bad: label a model answer or
a service signature as human judgment, approve the entire captured page from two
passing claims, or turn a failed DB transaction's provisional file into a commit claim.

### 6. Tests required
Cover altered/negated/quoted statements, supported optional HTML endings without
unsafe selected units, body/signature/expiry mismatch, paired hooks, exact chunk
membership, purpose narrowing, transaction rollback, CAS and completed-run replay.
Use explicit disposable PG identity and savepoints around negative fixture seeds.
Runtime evidence must distinguish synthetic PG tests from actual persisted capture.

### 7. Wrong vs correct
Wrong: force well-formed XHTML for an HTML document or extract arbitrary keyword
substrings to get a pass. Correct: tolerate irrelevant HTML structure while only
accepting complete finite supported units and validating their exact raw-byte spans.
Wrong: normal automated processing waits for a human signature. Correct: the trusted
service independently verifies supported evidence and signs as a service; unsupported
material stays isolated and optional human intervention never masquerades as automation.
