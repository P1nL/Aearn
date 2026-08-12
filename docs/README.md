# Aearn Documentation Index

## Current runtime status

**Updated: 2026-08-12.** Aearn's active product runtime is the **Tutor Harness**.
The desktop starts from a local learner identity, asks the server for a
cutover decision, and admits a learner to the Tutor workspace only after a
server-authoritative `verified` receipt. The current learning runtime also includes
server-authored, prepublication-validated `model_code_review` Lesson Gates with
deterministic structured-finding scoring. The former graph/router/SDK product
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
| Learner flow | [`product/user-flows.md`](./product/user-flows.md) | Local identity, controlled cutover, LearningTrack home, immutable LessonDocument reading, server-authoritative exercise Gate, and explicit module-diagnostic skip confirmation. |
| Desktop interaction | [`product/frontend-interaction-spec.md`](./product/frontend-interaction-spec.md) | Bootstrap state machine, server authority, responsive Tutor UI, Lesson Gate/diagnostic interaction, SSE handling, and local storage boundary. |
| HTTP and SSE API | [`architecture/api-contract.md`](./architecture/api-contract.md) | Current public routes, idempotency, cursor replay, errors, and privacy rules. |
| Database | [`architecture/database-schema.md`](./architecture/database-schema.md) | `tutor_*`, `harness_cutovers`, scoped persistence, deletion/preservation, and historical legacy tables. |
| Local development | [`setup/development-environment.md`](./setup/development-environment.md) | Required tooling, local services, dependency commands, worker/executor posture, and safe verification commands. |
| Executor operations | [`setup/container-sandbox-executor.md`](./setup/container-sandbox-executor.md) | Explicit-only container executor enablement and isolation rules. |
| Acceptance matrix | [`qa/acceptance-test-plan.md`](./qa/acceptance-test-plan.md) | Required automated and fixture-only manual checks. |
| Release evidence | [`qa/tutor-harness-release-readiness.md`](./qa/tutor-harness-release-readiness.md) | Exact command results, audits, smoke evidence, non-claims, and residual risks. |

## Historical material

The following files are dated evidence, not an active runtime contract:

- [`archive/2026-07-29/langgraph-state-machine.md`](./archive/2026-07-29/langgraph-state-machine.md)
- [`archive/2026-07-29/sdk-agent-release-readiness.md`](./archive/2026-07-29/sdk-agent-release-readiness.md)
- [`archive/2026-07-29/learning-graph-runtime-demo-story.md`](./archive/2026-07-29/learning-graph-runtime-demo-story.md)
- [`archive/2026-07-29/agent-capability-hardening-demo-story.md`](./archive/2026-07-29/agent-capability-hardening-demo-story.md)
- [`architecture/tutor-harness-transition.md`](./architecture/tutor-harness-transition.md), which remains migration evidence only.

Pre-cutover `Attempt`, FSRS, hidden-test, legacy plan, review, and note material
may appear in historical records and in the server's clean-slate inventory. It
is not reconstructed, served, or mutated by the active Tutor API. The target
runtime continues to protect hidden tests, source attribution, provider failure
mapping, and learner content redaction.

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
