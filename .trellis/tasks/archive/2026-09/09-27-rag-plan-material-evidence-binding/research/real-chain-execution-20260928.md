# Real-chain execution checkpoint — 2026-09-28

## Outcome

**Source capture and trusted automatic admission passed. Complete C-to-D real-provider chain did not pass.** No commit, push, production release, fixture-draft substitution, or terminal-prose feature work.

At DB clock 2026-09-28T08:01:54Z, the same isolated database `aearn_rag260_c_d_live_repair_01a0e0c7` contained 4 registered attempts (the original three unknown rows unchanged; generation 4 settled), 1 capture, 1 trusted review, 1 admission, 1 active partial corpus, and ZERO plan drafts, material selections, material bindings, or material semantic reviews. See `real-chain-status-20260928.json`.

## Source path actually executed

- Reviewed schema410 reuses existing allowance/auth tables and appends one generation-4 correction grant; no old permission was revived or reset. Current source bounds were retained. The original three attempts, authorizations, allowance, policy and root rows were compared by fingerprints.
- Immutable source image `sha256:9c776f7682c1993f869b14a1ada0eaf2dd76babeb20060e595654891844c0d38`; all16 current source hashes matched. Actual staged signer negative/positive checks passed, with the source worker sharing both the controlled network and PID namespaces. Main independently repeated the positive signed check before allowance/ARM. Worker runtime remained UID/GID65534, supplementary23456, zero effective/bounding capabilities, NoNewPrivs1.
- Main corrected the operator's read-only script syntax and compared timezone-aware datetimes instead of serialized timezone strings. Initial allowance insertion used a nonmatching approval-reference prefix and was rolled back; main then used the schema-required standing-policy prefix. Neither mistake created a source dispatch.
- Exactly one generation-4 worker invocation returned exit0 / `WORKER_ONE_SHOT_SETTLED`; dispatch `fccb47a8-1f27-4318-b6e1-fabb3e3b9da2`, capture `8f577959-f2dd-45f7-8b32-652af46dbdd8`, 2,033,807 complete bytes, SHA256 `a6d38ca170dff62177e74e63297b44e567f673e7d2111de923e33b481560c140`.
- Trusted SQLite review used the original separately pinned private service identity in an internal-only one-shot process. Initial admission launch lacked the entrypoint in the source image; it did not execute. The subsequent root-owned output-directory check denied mode0755; after correcting only the directory to0700, actual automatic review/admission returned `partial_queries_activated_isolated_db` for corpus `25b9629e-5e72-4714-aa7d-9175bd92d362`, run `c-auto-gen4-20260928-01a0e0c7`.
- Only exact supported supplementary excerpts were admitted; schema/main/scoring gaps and no public-consumer release remain. Current source expiry is 2026-09-28T11:54:38.657105Z (19:54:38 +08), not perpetual permission. The spent ARM was renamed to an audit copy, not reused.

## Real model path actually executed

- Real owner runtime cutover service performed dry-run/prepare/enable with durable preparing/preflight/enabled audit, generation1, in the same isolated DB. This was not source publication or production activation.
- D model container had narrow read-only source mounts, private DSN/config, and ONLY the new receipt plus PUBLIC reviewer key. The signing private key was never mounted there. Provider configuration was streamed into root0600 tmpfs through stdin, not Docker Env/arguments/image.
- Five bounded real-parent invocations used 4 + 3 + 2 + 3 + 3 = **15 actual model HTTP calls**, 89,570 known total tokens, unknown monetary cost. All attempts are recorded in `docs/qa/project-development-api-budget.json`; no failed request was treated as free. The initial16 total technical call bound was explicitly revised to20 before the last3-call window, with no usage reset; main stopped after its first parent failure rather than consuming the unused5 calls blindly.
- Observed issues and implemented corrections: harness dynamic context target512 omitted capability schemas; now2048. Generic1200/1600 character clipping corrupted server capability JSON; schemas now remain intact subject to existing safety/token checks. Synthetic one-module request contradicted the production tool's required module_1/module_2; now it requests an optional independent schema refresher plus core queries. Added selected-capability wire guidance; no model output was coerced. One actual response consumed all4096 output tokens as reasoning and ended incomplete; isolated acceptance CountedClient now disables optional thinking using the existing client option, without changing product defaults or HTTP caps.
- The actual later DB checkpoint confirms capability schema selected_count1/skipped_count0. Nevertheless the real provider still emitted invalid argument/payload values; one final attempt also omitted conversation_title, and bounded repair reached the per-invocation cap. Safe diagnostics do not retain raw invalid values, so a union diagnostic saying expected array must not be promoted to proof of the exact original Python value type.
- No valid parent draft persisted. Thus no successor dispatch, material semantic review, or final material binding was executed. This is not a RAG semantic-review pass or a full-chain success.

## Checks and remaining work

- Source410/deployment independent review:34 focused PG tests,40 runtime unit tests, functional offline signing positive/negative checks; actual live positive gate separately executed.
- Main final focused gateway/context/D harness suite:177 passed,3 fixture/platform-dependent skips (not counted as live acceptance). Full app/tests/infra Ruff passed; app mypy326 files passed. Counts overlap prior reports and must not be summed as unique tests.
- Remaining critical work is real-provider structured-protocol reliability at the parent boundary. Diagnose the exact safe output shape and repair guidance before another paid window; do not keep changing prompts and spending calls without discriminating evidence. Recheck source current-use expiry before later D consumption. End-prose constraints remain deferred; task stays in_progress.
