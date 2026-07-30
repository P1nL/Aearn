# Tutor Integration QA and Documentation

## Goal

Prove the completed Tutor Harness slices work as one learner-facing system,
then make the repository documentation and dependency surface describe that
proven system accurately. This child owns the final integration evidence,
physical retirement of legacy Graph/SDK implementation only when replacement
proof is complete, and a release record that states the clean-slate boundary
truthfully.

## Dependencies and Execution Mode

- This child depends on the archived Children 00 through 07:
  `tutor-harness-contracts-and-run-loop`,
  `tutor-skill-catalog-and-capability-gateway`,
  `tutor-state-traces-and-evals`, `container-sandbox-executor`,
  `tutor-proactive-scheduler`, `tutor-plans-memory-and-activity`,
  `tutor-api-sse-and-desktop`, and
  `harness-cutover-and-legacy-retirement`.
- The archived Child 07 implementation deliberately left Graph/router/tool
  code and related packages in place. It requires Child 08 to collect
  replacement proof before any physical retirement. Completion of Child 07 is
  therefore not evidence that legacy imports, routes, tests, or packages have
  already been removed.
- `docs/README.md` remains the documentation index. Current code, tests,
  schema, route registration, and configuration establish factual behavior;
  `docs/architecture/tutor-harness-transition.md` is the approved transition
  contract until this child publishes the final current-runtime documentation.
- This Codex session is **inline**. The seed-only `implement.jsonl` and
  `check.jsonl` files are not a readiness gate and must not be curated merely
  to satisfy the old sub-agent workflow. Before any implementation edit, load
  `trellis-before-dev` for the affected layer and use the completed planning
  artifacts plus repository specs directly.
- This is a complex child. `prd.md`, `design.md`, and `implement.md` must be
  reviewed and approved before `task.py start` changes the task to
  `in_progress`.

## Confirmed Repository Facts (2026-07-29)

- The working tree is clean on `main`; all eight upstream delivery children
  are archived under `.trellis/tasks/archive/2026-07/`.
- The target Tutor surface, durable state, public `/api/tutor` adapter,
  server-authoritative cutover gate, and Desktop cutover experience were added
  by the archived child work. The transition contract records their
  feature/cutover semantics.
- The source tree still contains legacy Graph imports in
  `app/agents/graphs/{learning,onboarding,review}_graph.py`, keeps the
  `LANGGRAPH_ENABLED` setting, and still has OpenAI Agents SDK imports in
  legacy agent/runtime/tool modules.
- `aearn/services/api/pyproject.toml` still pins `langchain`,
  `langchain-openai`, `langgraph`, `langgraph-checkpoint-postgres`, and
  `openai-agents`. Their removal must be based on a post-replacement caller
  audit, not on the feature flag alone.
- Several current source-of-truth documents still present the Graph/SDK
  baseline as current, including the documentation index, the LangGraph state
  machine, product/desktop specifications, API material, setup guidance, and
  SDK release-readiness report. These documents cannot be rewritten or
  archived until their replacement behavior is verified.

## Requirements

### 1. Establish an auditable integration evidence ledger

- Create a release-readiness record that ties every matrix row to the exact
  command or smoke procedure, revision, result, warnings, and residual risk.
- Use deterministic fixtures/test users. Integration validation must not call
  a real provider, run arbitrary learner code, or allow a proactive worker to
  create production-like learner activity.
- Run bootstrap-heavy backend tests sequentially while they share PostgreSQL
  bootstrap state; failures remain failures and cannot be concealed by
  documentation updates.

### 2. Verify the end-to-end Harness boundary

- Prove provider primary-only failure handling, bounded run-loop budgets and
  lease recovery, selected-Skill/capability validation, durable input merge,
  stale-effect rejection, grounding registration/citations, repository-owned
  effects, redaction, and trace/event ordering.
- Prove sandbox default-deny network behavior, image/limit/allowlist checks,
  cleanup, and the rule that proactive work cannot execute learner code.
- Prove proactive scheduling and Memory Curator gates: deduplication,
  cooldown/pause/budget/circuit limits, inbox-only output, redacted ordered
  outbox, proposal-only curation, and normal policy/service/repository
  validation before durable effects.
- Prove cutover, API/SSE, and Desktop behavior together: server-only
  confirmation, clean-slate deletion verification, Tutor-only entry after a
  verified receipt, cursor replay/error/terminal ordering, guided entry,
  activity/inbox visibility, diagnostics separation, and narrow viewport
  behavior.

### 3. Retire legacy implementation only after replacement proof

- First run the focused replacement suite, feature-enabled cutover tests,
  default Desktop routing smoke, worker-gating proof, and a scoped source/test
  caller audit.
- If any retained production caller, compatibility consumer, or essential
  test still depends on Graph/router/tool/SDK code, stop retirement, repair
  the replacement path, and return to the relevant implementation/check step.
- Once the caller audit is clean, remove obsolete Graph/router/tool modules,
  endpoints, tests, configuration, package pins/lock entries, and only the
  documentation made obsolete by that exact removal. Keep historical records
  as archived, clearly labelled material rather than silently deleting
  evidence.

### 4. Publish one coherent documentation and operational contract

- Add a current Tutor Harness runtime architecture document without erasing
  the transition/cutover record; update `docs/README.md` to route readers to
  current contracts.
- Reconcile the product, Desktop, API/SSE, database, sandbox, provider,
  worker, evaluation/acceptance, environment, and operational documents with
  verified behavior. Preserve first-release constraints that remain valid
  (`Attempt`, FSRS, hidden-test protection, model-failure mapping, and source
  attribution) unless replacement tests prove a deliberate change.
- Move Graph/SDK-specific material to a dated archive only after no current
  index or production code presents it as the active runtime.
- Record that code/configuration rollback before a confirmed cutover is
  possible, but rollback after a confirmed clean-slate deletion never restores
  intentionally deleted learner history.

## Acceptance Criteria

- [ ] A release-readiness ledger records all provider, loop, grounding,
  effects, plan/memory, sandbox, scheduler, API/SSE, Desktop, cutover, and
  retirement gates with reproducible evidence and explicit residual risks.
- [ ] The full backend suite, lint, type check, Desktop build, targeted
  Docker/executor health checks, designated browser/Desktop smoke, task
  validation, and `git diff --check` have recorded outcomes. Shared-bootstrap
  suites run sequentially.
- [ ] A feature-enabled fixture-user path proves verified cutover reaches only
  a fresh Tutor entry and that legacy runtime access cannot resume, recreate,
  or silently restore old learner data.
- [ ] A scoped caller/dependency audit is empty for production legacy
  Graph/router/tool/SDK runtime paths before their physical removal. Any
  intentionally retained historical mention is archived or explicitly labelled
  non-current and is not a product caller.
- [ ] `docs/README.md` and every retained source-of-truth document agree on
  the current Tutor runtime, public API/SSE behavior, Desktop entry, sandbox
  and scheduler safety boundaries, and clean-slate rollback limits.
- [ ] Graph/SDK documentation is archived rather than silently discarded, and
  no active documentation index labels it as the current orchestration model.
- [ ] Release documentation never claims that code rollback restores deleted
  history, never hides a failed integration gate, and contains no secrets,
  raw learner content, hidden tests, provider diagnostics, or checkpoint
  payloads.

## Out of Scope

- Reintroducing a compatibility mode that silently migrates or reconstructs
  legacy learner history after a confirmed clean-slate cutover.
- Treating a green documentation build, feature flag, task manifest, or static
  search alone as proof of cutover/data safety.
- Broad refactors outside the proven legacy retirement surface, arbitrary
  provider/executor changes, production deployment, or operation on a real
  learner account.
- Starting the parent task; the parent remains a coordination-only planning
  task and this child is the implementation target after approval.

## Open Questions and Planning Gate

No unresolved product decision remains: the parent plan already assigns final
integration proof, physical retirement after proof, and documentation
consolidation to this child. The remaining gate is the user's review of this
child's `prd.md`, `design.md`, and `implement.md`. If execution discovers a
new retained caller or an incompatible public consumer, return to Phase 1 and
record the resulting scope/risk decision before continuing.