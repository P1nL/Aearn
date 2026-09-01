# Aearn Documentation Index

## Current runtime status

**Updated: 2026-09-01.** Aearn's active product runtime is the **Tutor Harness** with a controlled Codex Sidecar path for eligible new `plan_drafting` turns.
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
The backend now also persists knowledge-scoped TeachingSession/checkpoint authority and exact learner-message, teaching-control, or domain-event Turn stimuli while keeping one long-lived track conversation. Artifact-aware teaching uses exact `tutor.lesson-teaching@1.2.0` and decision v3, server-built published Learning Item handles, impossible-instruction gating, and an atomic message/checkpoint/receipt/Artifact/event/Turn commit while both Artifact flags remain default-off. Blocking Artifacts can anchor durable depth-one clarification branches, and a fixed-priority continuation arbiter orders learner messages ahead of explicit Artifact actions, expected events, timers, and background work; reconnect uses additive snapshot v5 only when branch history exists. Immutable `tutor.lesson-teaching@1.0.0` and `1.1.0` remain catalog history and are not rewritten.
Learner messages may carry validated append-only `lesson_selection`,
`exercise_feedback`, `execution_result`, and `review_feedback` references;
these are injected as separate learner-safe structured context rather than
being concatenated into learner text. The Codex path uses exact `deepseek-v4-flash` Responses readiness, immutable server-side Runtime selection, and Aearn-owned public projection; general, track, proactive, historical, and feature-off traffic remains Harness. The former graph/router/SDK product
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
