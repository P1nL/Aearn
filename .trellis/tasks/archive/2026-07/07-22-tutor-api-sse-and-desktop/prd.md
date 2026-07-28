# Tutor API SSE and Desktop

## Goal

Deliver durable Tutor endpoints, cursor-based SSE replay, in-loop input-merge
composer, guided entry, activity/settings UI, and a bounded legacy-adapter
window.

## Dependencies and Documentation Authority

- Depends on frozen implementation contracts from Children 00 through 05,
  especially Child 02 events/replay/outbox and Child 05 plans/memory/activity/
  Curator proposal semantics.
- Before routes or UI work, publish the endpoint/event compatibility matrix with
  `legacy`, `adapter`, `new`, or `removed` status, consumer coverage, errors,
  and removal gate.
- Current product/frontend/API/SSE documents are legacy/current evidence. The
  approved transition contract and this matrix decide target behavior. UI work
  starts from the current `aearn/apps/desktop/src/` implementation plus approved
  product interaction contracts; the historical HTML design reference is
  non-authoritative and may be changed, replaced, or removed when needed.
- This is a complex child: add `design.md`, `implement.md`, and real manifests
  before `task.py start`.

### Readiness Refresh (2026-07-28)

- Children 00 through 05 are now archived and their required contracts are
  present in the current checkout: durable target conversations/runs/events,
  reviewed catalog evidence and effect CAS, feature-disabled execution and
  scheduler seams, and learner-safe plan/memory/activity/inbox projections.
- `PostgresTutorRepository` already owns run-scoped input idempotency,
  monotonic revisions, ordered `events_after()` replay, lease/CAS checks, and
  guarded terminal persistence. `TutorLearnerStateRepository` already owns
  learner-safe target read models and governed memory/inbox mutations. No
  existing product route or desktop page currently exposes either target layer.
- Existing `learning-sessions`, Graph SSE, and desktop flows remain the legacy
  baseline. This child publishes a versioned boundary adapter; it must not
  silently route legacy traffic into the Harness, remove Graph paths, enable
  `TUTOR_HARNESS_ENABLED`, or claim that a cutover has occurred.
- The user explicitly approved continuing the existing Harness implementation
  plan without re-opening product requirements. This checkout uses Codex inline
  execution; no implement/check sub-agent is dispatched.

## Requirements

- Add conversation/input/run/event endpoints and versioned errors; retain legacy
  adapters only for an explicitly tested migration window.
- Extend SSE with replay cursor, input acknowledgement, run state, activity,
  and compatible current event types.
- Keep composer enabled during active runs and use durable input events instead
  of competing stream calls, frontend aborts, or choice modals.
- Implement guided goal entry, activity, plan rollback, memory settings,
  provenance/retention state, proactive pause, and diagnostics access without
  exposing trace, Curator prompts/source segments/rationale, provider,
  Attempt/FSRS, or hidden-test internals.

## Acceptance Criteria

- [ ] A second message during an active run is acknowledged and merged without
  destructive cancellation.
- [ ] Cursor reconnect produces one timeline without duplicate events; stale
  partial output cannot commit plan/effect.
- [ ] UI shows permitted action/evidence/controls and hides protected internals.
- [ ] Learners can distinguish trusted-domain facts from Curator inferences,
  inspect learner-safe evidence/confidence/provenance/retention, correct/delete
  an entry, and disable future inferred memory.
- [ ] Legacy rendering remains compatible only while its adapter is enabled;
  Harness UI stays cutover-gated.

## Out of Scope

- Legacy Graph removal, destructive reset, arbitrary diagnostics exposure, and
  standalone historical-reference churn that is unrelated to actual frontend work.
