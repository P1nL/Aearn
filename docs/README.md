# Aearn Documentation Index

## Current runtime status

**Updated: 2026-09-03.** Aearn's active product runtime is the **Tutor Harness** with a controlled Codex Sidecar path for eligible new `plan_drafting` turns.
The desktop starts from a local learner identity, asks the server for a
cutover decision, and admits a learner to the Tutor workspace only after a
server-authoritative `verified` receipt. The current learning runtime also includes
server-authored, prepublication-validated `model_code_review` Lesson Gates whose
provider authors only learner-facing scenario copy and candidate code while
server-owned templates construct tests/rubrics, a
track-scoped spaced-review authority with finite `ReviewSession` batches,
server-projected critical-prerequisite Gates, exactly-once mastery/schedule
finalization, and a responsive track learning workspace that combines the
server roadmap, Lesson/Practice, Review, and a scoped Tutor conversation.
The backend now also persists knowledge-scoped TeachingSession/checkpoint authority and exact learner-message, teaching-control, or domain-event Turn stimuli while keeping one long-lived track conversation. Artifact-aware teaching uses exact `tutor.lesson-teaching@1.2.0` and decision v3, server-built published Learning Item handles, impossible-instruction gating, and an atomic message/checkpoint/receipt/Artifact/event/Turn commit while both Artifact flags remain default-off. Blocking Artifacts can anchor durable depth-one clarification branches, and a fixed-priority continuation arbiter orders learner messages ahead of explicit Artifact actions, expected events, timers, and background work; reconnect uses additive snapshot v5 only when branch history exists. Explicit Artifact Runs now persist strict `safe-execution-result-v2`, project one immutable result Artifact per terminal Attempt, schedule one mainline evaluation Turn only after terminal authority, and preserve the result with a deterministic safe evaluation message when the model is unavailable. The Desktop exact-parses Attempt v1/v2, renders concise failure-first results with bounded output/table detail, and can return focus to the exact source Artifact without deriving score or execution state. It also exact-parses snapshot v4/v5 into one conversation-native Artifact shell, uses an inert internal Markdown AST with controlled size/color/link rules, preserves process-local Artifact UI state across version refresh, and renders exact active/resolved clarification branches without scroll or focus theft. Immutable `tutor.lesson-teaching@1.0.0` and `1.1.0` remain catalog history and are not rewritten.
Single-file exercise Artifacts now lazy-load Monaco, preserve process-local drafts and view state, send code only on explicit Run, and use an app-owned Tauri custom-protocol child webview with exact capability isolation, sandbox/CSP, a nonce-bound bridge, and Preview-only hang recreation. Web-mode unavailability never falls back to main-DOM code execution. Published teaching demonstrations now materialize only from server-approved handles, remain read-only, complete through exact isolated-Preview evidence or visible-time authority, and never create Attempt, mastery, or progress evidence. Structured knowledge checks use immutable server-scored responses, receipt-backed H1-H3/direct-answer assistance, capability-scoped remediation or transfer successors, and one exact evaluation continuation; Desktop renders the closed response controls and a portal-based Hint overlay without deriving answer, mastery, or successor authority. Conversation-native AI code reviews now use additive `model_code_review_v2`: the server builds stable code/diff hashes and hunk/line maps, scores closed structured findings deterministically, stores the full submission only in an immutable private receipt, and schedules one receipt-backed evaluation continuation with an exact smaller/lower published remediation on failure; Desktop provides only the read-only Monaco review surface and local draft controls. Structured `sql_workspace_v2` Learning Items publish only exact SQLite table/column/PK/FK metadata and a bounded public dataset; explicit Run admits one Learning Item-owned Attempt, executes independent public/hidden datasets only after commit, exposes only the public grid plus generic hidden-test summaries, and completes through the existing authoritative result/evaluation flow. Desktop lazy-loads Monaco, keeps Editor/Schema 50:50 or stacked at narrow widths, copies names without editor mutation, and never auto-runs or connects to the Aearn application database.
The current Tutor Conversation Learning Artifact platform also includes exact frozen Lesson source resolution: Lesson citations, persisted lesson-selection references, and source-inspector Artifacts open one right-side document drawer without remounting Tutor, Lesson, Monaco, or Preview state. The drawer uses server-owned document/version/block/hash identity, isolated scrolling, a non-reflow highlight, historical-version disclosure, 88vw narrow behavior, and exact trigger focus restoration. Artifact write admission, Artifact-aware teaching, and Learning Item agent review remain separate default-off gates; existing learner-safe history stays readable. The complete local engineering matrix is reproducible from the acceptance plan and release-readiness ledger, but it is not a release approval.
Plan drafting now uses `planning-language-intent-v2`: only explicit active language evidence can auto-confirm `language_id`; bounded server-built language candidates allow a strict semantic hint to create a 1..3 option learner-confirmed shortlist, while insufficient evidence creates one targeted clarification. Enabled ambiguity no longer expands to the full catalog; `TUTOR_PLANNING_INTENT_ENABLED=false` is the explicit legacy rollback. Harness carries the hint in its strict provider decision, while Codex submits the same hint through a second validated planning-context tool call. Existing persisted requests and Skill versions `1.0.0`/`1.0.1` remain immutable; new planning runs select `tutor.learning-plan-draft@1.0.2`.

Learner messages may carry validated append-only `lesson_selection`,
`exercise_feedback`, `execution_result`, and `review_feedback` references;
these are injected as separate learner-safe structured context rather than
being concatenated into learner text. The Codex path uses exact `deepseek-flash` Responses readiness, immutable server-side Runtime selection, and Aearn-owned public projection; general, track, proactive, historical, and feature-off traffic remains Harness. The former graph/router/SDK product
runtime has been physically removed from the active source tree and its
runtime-specific documents are preserved under
[`archive/2026-07-29/`](./archive/2026-07-29/).

This is not a release approval. The verified code, dependency, database, and
web-browser checks are recorded in
[`qa/tutor-harness-release-readiness.md`](./qa/tutor-harness-release-readiness.md).
That ledger records the controlled verified-only proactive-delivery proof and its residual risk; it is not a release approval.

## Current source-of-truth documents

| Surface | Current document | Authority |
| --- | --- | --- |
| Runtime architecture and security boundary | [`architecture/tutor-harness-runtime.md`](./architecture/tutor-harness-runtime.md) | Tutor loop, Skills, controlled Action Runtime, safe persistence, exercise execution reuse, provider, executor, scheduler, cutover, and rollback rules. |
| Learner flow | [`product/user-flows.md`](./product/user-flows.md) | Local identity, controlled cutover, LearningTrack home, immutable LessonDocument reading, exercise Gate, module diagnostics, and track-scoped ReviewSession behavior. |
| Desktop interaction | [`product/frontend-interaction-spec.md`](./product/frontend-interaction-spec.md) | Bootstrap state machine, server authority, responsive Tutor UI, Lesson Gate/diagnostic interaction, SSE handling, and local storage boundary. |
| HTTP and SSE API | [`architecture/api-contract.md`](./architecture/api-contract.md) | Current public routes, idempotency, cursor replay, errors, and privacy rules. |
| Database | [`architecture/database-schema.md`](./architecture/database-schema.md) | `tutor_*`, `harness_cutovers`, scoped persistence, deletion/preservation, and historical legacy tables. |
| Local development | [`setup/development-environment.md`](./setup/development-environment.md) | Required tooling, local services, dependency commands, worker/executor posture, and safe verification commands. |
| Codex Sidecar operations | [`setup/codex-sidecar-runtime.md`](./setup/codex-sidecar-runtime.md) | Exact version/provider/protocol, isolated Home, readiness, worker lifecycle, observability, rollback, and real-smoke approval boundary. |
| Executor operations | [`setup/container-sandbox-executor.md`](./setup/container-sandbox-executor.md) | Explicit-only container executor enablement and isolation rules. |
| Tutor v2 protocol cutover | [`setup/tutor-thread-turn-v2-cutover.md`](./setup/tutor-thread-turn-v2-cutover.md) | Global preflight, generation/CAS, enable, blocked recovery, rollback, and non-production boundary. |
| Acceptance matrix | [`qa/acceptance-test-plan.md`](./qa/acceptance-test-plan.md) | Required automated and fixture-only manual checks. |
| Release evidence | [`qa/tutor-harness-release-readiness.md`](./qa/tutor-harness-release-readiness.md) | Exact command results, audits, smoke evidence, non-claims, and residual risks. |
| Codex Sidecar integration evidence | [`qa/codex-sidecar-integration-readiness.md`](./qa/codex-sidecar-integration-readiness.md) | Protocol-to-product failure matrix, approved real smoke reuse, rollback proof, safety scan, and non-claims. |

## Historical material

The following files are dated evidence, not an active runtime contract:

- [`archive/2026-07-29/langgraph-state-machine.md`](./archive/2026-07-29/langgraph-state-machine.md)
- [`archive/2026-07-29/sdk-agent-release-readiness.md`](./archive/2026-07-29/sdk-agent-release-readiness.md)
- [`archive/2026-07-29/learning-graph-runtime-demo-story.md`](./archive/2026-07-29/learning-graph-runtime-demo-story.md)
- [`archive/2026-07-29/agent-capability-hardening-demo-story.md`](./archive/2026-07-29/agent-capability-hardening-demo-story.md)
- [`architecture/tutor-harness-transition.md`](./architecture/tutor-harness-transition.md), which remains migration evidence only.
- [`architecture/fsrs-scheduling-spec.md`](./architecture/fsrs-scheduling-spec.md), the pre-cutover `review_states` / `/api/reviews` design.
- [`archive/2026-06-18/current-state-audit/`](./archive/2026-06-18/current-state-audit/), the complete 2026-06-18 pre-Tutor runtime audit bundle formerly stored under the misleading `docs/current/Aearn/` path.
- [`setup/newcomer-onboarding-guide.md`](./setup/newcomer-onboarding-guide.md), a pre-cutover implementation guide retained as historical onboarding evidence.

Pre-cutover `Attempt`, FSRS, hidden-test, legacy plan, review, and note material
may appear in historical records and in the server's clean-slate inventory. Old
`review_states`, `review_logs`, `review_seed_banks`, and top-level `/api/reviews`
are not reconstructed, served, or mutated by the active Tutor API. The active
review authority instead uses `tutor_review_*` tables and track-scoped
`/api/learning-tracks/{track_id}/reviews...` routes. The target runtime continues
to protect hidden tests, source attribution, provider failure mapping, and
learner content redaction.

## 2026-09-08 local repair boundary

New managed lessons require verified HTTP-ingestion provenance rather than fixture/unknown metadata. Knowledge-bound teaching input requires prepared session authority before admission. Failed Harness turns now have deterministic safe error history, and runtime diagnostics are message-rendered structured records. Planning intake separates message/reasoning budgets and confirms underlying stop rather than treating an interrupt ACK as completion. See the updated API, local setup, runtime and acceptance documents above.

These changes do not constitute full real-model artifact acceptance: the retained Python test-course authoring attempts still returned incomplete provider responses at their bounded output limit. The ineffective model-output-policy experiment was reverted; no output cap, publication gate or retry count was relaxed. Offline pass counts and the two reproduced pre-existing eval-baseline failures are recorded in the release-readiness ledger.

## Documentation maintenance rules

1. Treat route registration, current code, schema, tests, and configuration as
   factual authority; update the documents above from verified behavior only.
2. Do not describe a feature flag, a green build, or a static search as proof
   that learner data was safely cut over or retired.
3. Do not put learner messages, learner code, hidden tests, prompts, provider
   payloads, checkpoint payloads, credentials, or raw diagnostics in release
   evidence.
4. Code/configuration rollback before confirmation can restore code only while
   legacy rows still exist. After a confirmed clean-slate deletion, rollback
   never restores intentionally deleted learner history.
5. Move a whole obsolete runtime document to a dated archive and add a visible
   redirect instead of silently deleting the evidence.

## 2026-08-12 final integration status

The programming-language learning-agent task tree is integrated locally. A deterministic PostgreSQL matrix covers the complete plan-to-review evidence path for Python, JavaScript, TypeScript, and SQL. Java and HTML/CSS are extension validation only; Go and C# remain partial local managed-compiled capabilities; Rust is unavailable and C++ is static-only. The reviewed image-lock registry is empty, so no public language is `container_verified`.

Cutover inventory is schema-reconciled: every `tutor_*` table is explicitly classified as user-owned target state or shared immutable/catalog infrastructure. Legacy learning state is not silently converted. The final command results and remaining non-claims are recorded in the release-readiness ledger; local completion still does not authorize provider rollout, image approval, push, deployment, or production migration.


## 2026-09-02 Tutor Conversation Learning Artifact platform integration status

All twelve approved Trellis children completed local implementation, verification, commit, and archive, followed by the parent final acceptance reconciliation. The closed public Artifact contract, snapshot v4/v5 recovery, branch/continuation authority, Learning Item governance, HTML editor/isolated Preview, result evaluation, demonstrations, knowledge checks/Hints/remediation, model review v2, SQL workspace, and exact source drawer share one Artifact/Attempt/Result/Markdown/Branch boundary. The final acceptance mapping lives in [the Tutor Conversation Learning Artifact platform matrix](./qa/acceptance-test-plan.md#2026-09-02-tutor-conversation-learning-artifact-platform-final-matrix).

Local deterministic tests, disposable PostgreSQL/browser fixtures, Rust checks, and safe import/static audits do not authorize a real provider run, Docker conformance, reviewed image build/sign/publish, production migration, push, deploy, or release. Those remain separately approved operations.
