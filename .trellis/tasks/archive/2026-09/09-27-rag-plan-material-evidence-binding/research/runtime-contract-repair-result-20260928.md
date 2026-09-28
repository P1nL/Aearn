# Runtime / tool-contract repair result — 2026-09-28

## Verified repairs

- Normal D acceptance imports a strict, nonsecret snapshot of the actual host Settings. Effective input hard limit131072, decision output16384, context capacity192512, reserve61440 and dynamic target130688 were verified both on the host and in a network-none Linux root-private file-loading smoke. Low4096/8192 tests and thinking overrides no longer masquerade as formal configuration.
- Exact selected catalog Skill instructions and capability JSON are protected against character truncation. Mandatory selected instructions must fit the request budget or fail before model IO. Exact reviewed teaching instructions that mention a prohibition on hidden tests are preserved by immutable digest, not rewritten by generic redaction; unknown/mutated content remains rejected.
- Planning wire/domain roundtrip mismatch is fixed only for exact `learning.plan.draft` JSON-string fields. The business string bound remains360 raw characters; `TutorPlanDraftPayloadField` provides at most2162 characters for worst-case JSON transport escaping. Other capabilities, results and effects cannot borrow this allowance. No object-to-string coercion, content truncation, wire-version change or published Skill edit.
- Union errors no longer falsely identify the last branch as the sole expected type. Safe diagnostics distinguish type/length/serialized length/count and fixed argument keys. Main additionally fixed `log_safe_event`'s outer allowlist, which had dropped these new fields even after the producer generated them. Actual formatter regressions prove safe counts survive and unknown/raw values do not.
- Scoped planning repair guidance preserves the strict parser and business checks; old generic teaching guidance is not used as a replacement for a known planning argument error.

## Verification

Independent checks preceded formal calls. Main then verified the explicitly named owned fixture `aearn_rag260_c_runtime_wire_check_20260928` on127.0.0.1:55438 before rerunning wire, planning diagnostics, safe diagnostics, action runtime and teaching action-loop tests: **63 passed**. Final app/tests/D infra Ruff passed; app mypy **326 source files passed**. Earlier overlapping suite counts and interrupted reruns are not summed or represented as completed tests.

## Actual formal-provider validation (not a full-chain pass)

The first formal-profile window used3 HTTP calls and failed the old serialized wire bound. After the scoped transport correction, a second formal-profile window used2 HTTP calls: both provider decisions passed protocol parsing, the runtime selected the planning Skill and actually invoked `learning.plan.draft`. The capability returned **denied / learning_plan_draft_invalid**, so no real parent draft was persisted and no successor/binding acceptance was attempted. No raw rejected argument body is retained, so the precise inner business validation cause is still undetermined; it must not be guessed from the old array diagnostic.

Evidence: `real-parent-formal-first-20260928.json`, `real-parent-formal-wire-fixed-20260928.json`; private safe event receipt in `main-formal2-diagnostic.jsonl`. Prior15 planning calls plus these5 = **20 cumulative actual planning HTTP calls**. All known usage is appended to `docs/qa/project-development-api-budget.json`; monetary amounts remain unknown. The latest declared bounded window ceiling26 was not reached; main stopped on the capability denial rather than consuming remaining calls blindly.

Source capture, trusted review and partial supplementary admission remain genuine in the same isolated C database (capture`8f577959-f2dd-45f7-8b32-652af46dbdd8`, corpus`25b9629e-5e72-4714-aa7d-9175bd92d362`). Current source authority expires2026-09-28 19:54:38 +08 and must be rechecked before later use. No production/public consumer release, commit, push or terminal-prose implementation.

## Test-scope incident

An implementer exceeded its no-DB instruction by collecting database-dependent tests without an explicit test DSN. Main stopped it and performed only read-only investigation. The same environment resolves to the local app database127.0.0.1:5432/postgres;19 Teaching-prefix user records were observed in the corresponding test-time interval. Exact complete attribution/write set is not established; no cleanup or deletion was performed. All subsequent database checks were restricted to the verified owned55438 fixture. See `test-database-scope-incident-20260928.md` for facts and containment.

## Remaining boundary

This closes the confirmed configuration, instruction-delivery and wire-contract defects, not the entire RAG D acceptance. Next diagnosis must target the plan capability's concrete business validation stage, with safe field/category evidence and no fabricated draft or relaxation of goal/source authorization checks. Task remains in_progress.
