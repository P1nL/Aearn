# Tutor Proactive Scheduler

## Goal

Deliver durable user-event/time-signal candidate runs with deduplication,
budget/cooldown/circuit-breaker policy, safe worker recovery, and inbox-only
proactive outcomes.

## Dependencies and Documentation Authority

- Depends on Child 00 run lifecycle, Child 01 policy/capability gateway, and
  Child 02 durable persistence/traces, including its curation outbox contract.
- The transition contract must define signal sources, consent/defaults, pause,
  budget, no-action, audit, and delivery semantics before worker enablement.
- Existing review worker behavior is legacy/current evidence; it cannot become
  autonomous Tutor behavior without the new policy contract.
- This is a complex child: add `design.md` and `implement.md` before
  `task.py start`. This checkout uses Codex inline execution, so source work
  loads layer specs through `trellis-before-dev` rather than curating JSONL
  dispatch manifests.

### Readiness Refresh (2026-07-28)

- Child 00, Child 01, and Child 02 are archived as completed. Their current
  contracts are present in `docs/architecture/tutor-harness-transition.md`:
  finite leased runs, catalog/policy decisions, durable replay/trace evidence,
  and the redacted curation outbox. The transition contract is linked from
  `docs/README.md` and remains the target authority while legacy product flows
  stay feature-disabled.
- The current PostgreSQL schema already stores `tutor_runs.origin` with
  `interactive` and `proactive` values, and `PostgresTutorRepository.create_run`
  accepts either. `TutorRunSnapshot` does not currently expose that persisted
  origin, so Child 04 must add the typed propagation needed for a policy resolver
  to distinguish background work from an interactive turn.
- `tutor_memory_curation_outbox` is durable and idempotent but has no queue
  lease/retry owner. `aearn/services/worker/aearn_worker/worker_app.py` only
  registers legacy review tasks, so it supplies no reusable Harness scheduler.
- The Harness eval suite currently has one unrelated regression: the fixture
  pins the complete published catalog digest from before Child 03 added
  `tutor.runner-execution@1.0.0`. Repair and re-run that fixture as a pre-start
  baseline gate; do not weaken catalog-identity validation or treat the failure
  as a scheduler behavior change.
- This child may add only target-only, feature-disabled scheduler seams. It must
  not expose a route, SSE frame, desktop state, legacy worker replacement, or
  user-visible activity/inbox projection owned by Child 05/06.
- **Planning review recorded on 2026-07-28:** the user approved this refreshed
  Child 04 plan. This session remains planning-only by workflow state, so it
  records approval without invoking `task.py start`; the next execution-enabled
  session must start this child before changing source code.

## Requirements

- Ingest durable user events and policy-defined time signals, deduplicate
  candidates, and apply cooldown, user concurrency, time/cost budgets, circuit
  breakers, and audit records.
- Lease candidates through the same finite Tutor runtime and allow a documented
  no-action outcome.
- Provide a low-priority `curation` queue/lease class for Child 05 to consume
  Child 02 outbox rows. Enforce independent curation budget, cooldown,
  concurrency, retry, and circuit-breaker controls; it is not a proactive Tutor
  candidate and cannot create teaching output by itself.
- Provide global proactive enable/pause, default-enabled state only after
  cutover, and no normal-success chat injection or desktop notification.
- Limit proactive capabilities to approved read/plan/activity operations and
  explicitly exclude learner code execution.
- Carry the persisted run origin through the Harness snapshot/policy boundary;
  a missing or unknown origin must deny capability dispatch rather than default
  to an interactive permission set.

## Acceptance Criteria

- [ ] Repeated signals create at most one eligible candidate per dedupe window;
  ineligible candidates persist a no-action reason.
- [ ] A paused or budget-exhausted learner causes no provider/tool request.
- [ ] Successful work creates only user-scoped activity/inbox state.
- [ ] Scheduler decisions are traceable and recover safely after worker retry.
- [ ] Hard background pause, inferred-memory disable, or curation-budget denial
  makes no Curator provider call; retry/re-delivery remains idempotent per
  outbox key.

## Out of Scope

- Continuous self-running model loops, proactive code execution, and replacing
  existing learning/review behavior before cutover; Curator summary/memory
  semantics or direct domain writes, which belong to Child 05.
