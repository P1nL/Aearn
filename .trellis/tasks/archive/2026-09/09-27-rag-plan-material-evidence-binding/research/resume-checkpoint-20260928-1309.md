# Resume checkpoint — 2026-09-28 13:09 Asia/Shanghai

User requested continuing the real end-to-end run. The two GPT-6 Sol implementation agents previously terminated with explicit insufficient-balance HTTP 403 responses from their host model channel. No paid retry was sent to that known-exhausted channel; this is not evidence that the separately configured Aearn DeepSeek provider or the cumulative CNY project budget is exhausted. No provider switch or top-up was performed.

## Work actually performed

- Preserved all existing dirty-tree changes. Resumed only the owned WSL PostgreSQL fixture cluster (port 55438) and existing isolated Docker live PostgreSQL container. The source-control and egress containers remain stopped after the host interruption; their old namespace/image pins must not be reused blindly.
- Inspected partial final-followup and C-only long-deadline implementation left by interrupted agents. Fixed an unused snapshot in the final-followup regression by asserting the two historical attempt rows remain byte-for-byte logically unchanged after the third synthetic attempt settles unknown.
- Applied the current full schema manifest to a new synthetic fixture database `aearn_rag260_c_resume_20260928`; this is ONLY for tests, not replacement of the live evidence database.
- Final-followup and supplemental-recovery PostgreSQL tests: **19 passed**.
- Safe-fetch/connector and live-worker/bridge offline run: **155 passed, 14 skipped, 55 subtests passed**. Missing PostgreSQL-specific configuration in that first run was not counted as success.
- Subsequent explicit-PostgreSQL registered-source policy/inventory/schema/final-followup/recovery plus worker/bridge run: **127 passed, 3 skipped, 55 subtests passed**. Counts overlap; do not add them into a unique test total. Remaining platform/deployment skips are not live acceptance.
- Ruff app/tests/C-live/C-control/D-live: passed. Mypy app: **326 source files passed**.

## Fresh live read-only evidence

At `2026-09-28T05:09:10.939939Z`, a read-only, cap-drop-ALL, no-new-privileges helper on the existing internal Docker network verified exact database identity `aearn_rag260_c_d_live_repair_01a0e0c7` and transaction_read_only=on:

- registered attempts: 2, both `unknown / DEADLINE_EXCEEDED`;
- original `0ffc109e-136b-4b99-b270-2896f8d92edd` preserved;
- second `9ab67b2d-4d62-47be-8ae0-4df576b099e9` preserved;
- captures, reviews, admissions, active corpora: all 0.

No third GET, no new live allowance, no schema400 live application, and no Aearn model call occurred in this resume. Full-chain acceptance remains **NOT PASSED**. Ending-prose constraints remain deferred.

## Remaining gate

The new schema400 and long-deadline changes still need the planned independent GPT-6 Sol review after the model channel is available. Passing main-session tests is not an independent-agent GO. Then rebuild/re-pin/re-probe isolated source deployment, issue the single final allowance in the SAME live database under existing scope, and invoke exactly one long-deadline worker. Successful source capture must be followed by genuine trusted review/admission and real parent/successor model flow. No fourth attempt or history reset is authorized by this checkpoint. Re-evaluate current grant expiry at actual execution time.
