# D completion attempt — 2026-09-28: not passed

## Result
D is still in progress. The existing real parent draft remains valid and completed, but no current new complete source capture was obtained, so the queued successor was not dispatched. No simulated source, expired authority, partial body or hand-written draft/binding was substituted.

## Implemented and checked
- Schema420: one explicit generation5 freshness refresh after the genuine settled generation4 capture/policy/root/grant expired; same immutable lineage, source/Subject/version/facets/URL/license/usages, no byte-cap increase, independent current policy/root/dispatch/request, at most24h authority and five cumulative registered attempts. No generation6 or auto retry.
- Fixed the historical timestamp predicate to dispatched_at <= fetched_at <= settled_at <= DB now, matching the independently observed real capture. Old rows were not edited to fit the code.
- D harness verifies the immutable parent audit under its original ceiling29 and separately admits a successor window prior28/max6/ceiling34. The new actual_cumulative_http_attempts output preserves prior counts; combined_http_attempts retains its local parent+successor meaning.
- Targeted checks: schema manifest5 passed; new freshness PostgreSQL3 passed in12.90s; budget-window bridge3 passed. All relevant Ruff checks passed. The first PG invocation skipped3 because its explicit C test DSN was absent; those skips were not counted as validation. The subsequent run explicitly targeted and verified aearn_rag260_c_d_refresh_check_20260928, bootstrapped it, and executed all3 tests without skips.
- Independent narrow review passed. No broad regression suite was run.

## Actual fresh source attempt
- Same isolated live DB: aearn_rag260_c_d_live_repair_01a0e0c7.
- Existing pinned worker image9c776f... reused; same source paths verified. Current DNS, firewall/identity checks and current signer positive/negative gates passed. Actual worker shared signer network and PID, with final UID/GID65534, exact supplementary23456, zero effective/bounding capabilities and NoNewPrivs1. Docker includes the primary GID when using --user/--group-add, so the existing setpriv bootstrap was used to establish the exact required identity; the identity check was not weakened.
- A new explicit source grant was issued under standingpolicy.sourcefreshness.20260928.main.01a0e806. Old policies/roots/expiry/attempts/auth/captures were hash-checked unchanged.
- Exactly one source worker was ARMed and executed: dispatch b474fa89-9da6-4a41-9981-b3dd3d8471ec, generation5.
- Worker ran from2026-09-28T15:03:21.633100538Z to15:04:56.396314207Z (94.763s), exited1 with BODY_DENIED at body transfer: received1507328 bytes of declared2033807 bytes, identity encoding. This was below the300-second total deadline; no evidence establishes the exact inner network error, so do not label it a proven overall timeout.
- No complete capture/provenance/report was committed. Capture count remains1, namely the expired generation4 capture. Main terminally reconciled the new dispatched row to unknown/BODY_DENIED after confirming worker exit. History hash verification again proved every preexisting source row unchanged.
- Final history: generations1/2/3 unknown, generation4 settled, generation5 unknown. No sixth attempt was issued.

## D/provider state and cleanup
- Target2831cdec-ec3f-4047-9c84-d768d0ab6cea remains queued with model_call_count0/capability_call_count0. No new semantic-review, successor or binding acceptance occurred.
- Project model HTTP remains28; this completion attempt added0 model/provider requests. Source operations are separately recorded above; unknown historical attempts were not reset.
- Parent provenance and prior failed/successful evidence remain preserved. The spent ARM was renamed inside its owned volume to arm.refresh5.spent.json. New source control/signer and temporary model containers were stopped. The owned PG, volumes and history remain intact; development5432/postgres and its19 suspicious test records were untouched.
- All new sub-agents used requested GPT-5.6 Sol. One source agent later hit its host provider quota refusal; the produced timestamp patch was independently reviewed and actually tested by main. No model substitution or top-up occurred. The project model endpoint is distinct from that failed sub-agent billing host.

## Remaining blocker
The real C-to-D positive acceptance still needs a complete, currently authorized source capture followed by automated admission, real material-feedback revision, semantic review and exact binding. The approved fifth source credit is spent. Do not reuse it, extend old expiry, promote partial bytes or label D complete. First diagnose the interrupted body transfer; any further source operation needs a separately reviewed bounded acquisition plan rather than another blind call or silent cap expansion.

Evidence: d-completion-source-refresh-result-20260928.json; d-closure-evidence-map-20260928.md; d-completion-window-20260928.md. No commit, push, public release, E acceptance or task archival.
