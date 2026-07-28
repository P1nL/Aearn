# Tutor Plans, Memory, Activity, and User Controls Implementation Plan

## Preconditions

1. Child 01, Child 02, and Child 04 are archived and their target contracts
   are present in `docs/architecture/tutor-harness-transition.md`.
2. Load `trellis-before-dev`, backend/database/shared guides, and read existing
   `tutor` catalog, persistence, scheduler, safe-projection, and test fixtures.
3. Keep the worktree scoped to this child. Do not add API/SSE/Desktop routes,
   modify legacy Graph behavior, enable scheduler/cutover flags, use real model
   credentials in tests, or alter legacy plan/profile/review/FSRS tables.
4. This is Codex inline execution: no implementation/check sub-agent is
   dispatched. Existing seed-only JSONL manifests remain non-authoritative;
   source work is grounded through the task artifacts and specs.

## Ordered Implementation Checklist

### 1. Publish Typed Learner-State Effect Contracts

- Add bounded Pydantic proposal models and reviewed effect descriptors for plan
  activation/rollback, objective memory recording, and learner-safe activity
  recording.
- Add a reviewed Tutor Skill bundle that declares only those exact effects;
  preserve catalog exact-version/hash compilation and update strict fixture
  identity rather than weakening its assertions.
- Keep default policy composition deny-by-default. Extend proactive composition
  only for explicitly allowed reviewed plan/activity effects and retain the
  permanent `runner.execute` denial.

### 2. Add Repeatable Target Domain Schema

- Add target-only plan-revision, active-pointer/action, memory-preference/entry,
  context-summary, activity/inbox, and curation-projection-receipt tables,
  indexes, FKs, lifecycle checks, and `updated_at` triggers.
- Ensure plan revisions and activity are append-only where required; mutable
  pointers/preferences/inbox state have narrow guarded updates.
- Prove all run/outbox/proposal/user references have same-scope constraints;
  no schema statement reads or alters legacy learner domain tables.

### 3. Implement Target Repositories and Effect Handlers

- Add a focused Child 05 repository/service module for immutable plan revision
  activation/rollback, memory preferences/correction/delete, trusted objective
  fact recording, context summaries, activity/inbox records, and safe list/read
  projections for future Child 06.
- Register explicit in-transaction handlers through
  `PostgresTutorRepository.commit_effect_if_current()`; decode descriptor
  payloads once, preserve input-revision/lease/idempotency enforcement, and
  emit only safe effect receipts/events.
- Assert plan effects never write legacy plan, review, FSRS, attempt, or learner
  profile state. Activity/inbox rows must never retain raw trace/provider
  reasoning/prompt/code/hidden-test data.

### 4. Implement Curator Proposal and Projection Pipeline

- Add an injected primary-only Curator gateway around the existing configured
  `OpenAICompatibleClient`, with a separate max-output-token configuration that
  defaults to zero/fail-closed.
- Add a curation processor that reads only the redacted Child 02 outbox, checks
  current source/policy/memory-setting/retention facts and learner memory
  preference before any provider call, validates one typed proposal, records
  its generic envelope, and commits a context-summary or memory projection via
  the repository.
- Compose this processor only inside the Child 04 curation wrapper when the
  feature flags already permit it; unavailable/disabled composition must return
  bounded no-action without a provider call.

### 5. Add Focused Tests and Static Boundaries

- Add plan tests for immutable predecessor/diff/evidence, activation,
  one-action rollback, idempotency, and proof no legacy FSRS/review mutation
  occurs.
- Add memory tests for objective vs inference evidence, preference versioning,
  correction/delete/disable, retention/staleness, no raw payload leakage, and
  no Curator provider call after denial.
- Add Curator tests with fake primary gateway for exact input bounds, no
  fallback, invalid output, retry/no-action outcomes, outbox idempotency, and
  one projection receipt per proposal.
- Add activity tests for user scope, inbox state, safe evidence fields, effect
  CAS/idempotency, and proactive `runner.execute` denial.
- Update existing catalog/proactive/eval/worker tests only where the new
  reviewed contracts intentionally change strict identities or deferred
  composition behavior.

### 6. Record Verified Documentation and Code-Spec Delta

- Extend `docs/architecture/tutor-harness-transition.md` with Child 05
  ownership, user controls, Curator protocol, target data boundaries, and
  feature-off compatibility.
- Add the mandatory cross-layer executable scenario to
  `.trellis/spec/backend/quality-guidelines.md`: exact signatures, contracts,
  validation/error matrix, good/base/bad cases, tests, and wrong/correct
  example.
- Do not claim public API/Desktop availability, cutover completion, legacy data
  retirement, or product activation.

## Required Validation

Run PostgreSQL/bootstrap-heavy tests sequentially:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_plan_revisions.py tests/test_tutor_memory.py tests/test_tutor_memory_curator.py tests/test_tutor_activity.py tests/test_tutor_effect_commit.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_skill_catalog.py tests/test_tutor_capability_gateway.py tests/test_tutor_proactive_candidates.py tests/test_tutor_proactive_policy.py tests/test_tutor_memory_curation_scheduler.py tests/test_worker_import.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-plans-memory-and-activity
git diff --check
```

## Review Gates and Rollback

- Confirm every path from provider or Tutor effect to a domain table crosses
  descriptor validation, policy, run/lease/input CAS, repository transaction,
  and safe projection exactly once.
- Confirm a Curator cannot use canonical messages, raw traces, provider
  payloads/reasoning, chat, activity/inbox, plan revisions, review/FSRS,
  attempts, executor, or a fallback provider/model.
- Confirm defaults leave all feature paths unavailable/denied with no model
  call. Use deterministic fakes and disposable fixture users only.
- Roll back by disabling target composition/flags; retain target evidence for
  diagnostics. Never claim code rollback reconstructs an explicit future
  cutover deletion.