# Tutor Plans Memory and Activity

## Goal

Deliver immutable plan revisions/rollback, evidence-backed learner memory,
activity timeline/inbox, and user controls while preserving FSRS/review service
authority.

## Dependencies and Documentation Authority

- Depends on Child 01 capability/effect policy, Child 02 durable state,
  compare-and-set, redaction, trace/outbox contracts, and Child 04 generic
  low-priority curation queue/budget/retry infrastructure.
- Before code, the transition contract must distinguish legacy plans/profiles
  from new revisions/memory/activity and document user-visible evidence,
  rollback, correction, deletion, disable, Curator provenance, retention, and
  proposal/commit behavior.
- Product, database, API, and frontend docs are legacy/current evidence. This
  child freezes semantics for Child 06 UI and Child 07 cutover; it cannot alter
  FSRS authority.
- This is a complex child: add `design.md`, `implement.md`, and real manifests
  before `task.py start`.

### Readiness Refresh (2026-07-28)

- Child 01 (catalog/policy), Child 02 (durable run, redaction, curation outbox),
  and Child 04 (low-priority curation lease/budget/retry queue) are archived as
  completed. `docs/architecture/tutor-harness-transition.md` is the narrow
  target authority for their feature-disabled seams.
- The current catalog validates exact effect descriptors and selected-Skill
  authorization before `PostgresTutorRepository.commit_effect_if_current()`
  invokes an in-transaction domain handler. The only published effect is still
  `runner.execute`; Child 05 must add typed plan, learner-memory, and
  activity/inbox effects without weakening the catalog/policy/CAS gate.
- Child 02 already persists a redacted `tutor_memory_curation_outbox` and one
  proposal envelope per outbox identity. Child 04 creates one leaseable
  `tutor_curation_jobs` row and provides a default-deny processor only. Child
  05 owns semantic proposal validation and the committed target projections;
  it may not turn either store into raw prompt, trace, or provider-payload
  storage.
- No `tutor_*` target plan, learner-memory, context-summary, activity, inbox,
  or memory-preference projection exists yet. Existing `learning_plans`,
  learner-profile, review, FSRS, and note records are legacy baseline data and
  are not a Child 05 dependency or write target.
- The user approved continuing the existing Harness plan after Child 04
  closeout. This checkout runs Codex inline, so source work loads relevant
  specs through `trellis-before-dev`; no implementation/check sub-agent is
  dispatched.

## Requirements

- Add immutable plan revision lineage, structured diffs, evidence references,
  policy-permitted activation, and one-action rollback.
- Replace opaque profile writes with objective facts and evidence/confidence
  inferences that learners can inspect, correct, delete, or globally disable.
- Implement the internal Memory Curator / Context Compactor using only Child
  02's redacted outbox and Child 04's queue. It uses the configured primary
  provider/model under lower curation budgets and can emit only a typed bounded
  context-summary or learner-memory proposal; policy/service/repository code
  validates and commits every projection.
- Add user-scoped activity timeline/inbox records and API contracts that exclude
  raw traces/provider reasoning.
- Use input-revision CAS and user idempotency for plan, memory, and note effects;
  a plan revision never directly updates FSRS.

## Acceptance Criteria

- [ ] Every activated revision records predecessor, learner-safe reason, diff,
  source run/evidence, and tested rollback.
- [ ] Plan actions do not change FSRS; review/FSRS services retain authority.
- [ ] Memory separates objective facts from inferences and supports all learner
  correction, deletion, and disable controls.
- [ ] Curator proposals retain source evidence, confidence, provenance,
  retention/staleness, setting/policy version, and idempotency; they cannot
  directly alter activity/inbox/chat, plan, review/FSRS, attempts, or provider
  selection.
- [ ] Activity/inbox is user-scoped and never exposes trace/provider reasoning.

## Out of Scope

- Desktop rendering, legacy deletion, generic scheduler queue policy, and raw
  long-term prompt/provider payload storage.
