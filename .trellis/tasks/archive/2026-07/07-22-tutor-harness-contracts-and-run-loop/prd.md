# Tutor Harness Contracts and Run Loop

## Goal

Deliver the first feature-disabled, finite Tutor Harness runtime seam: a typed
run lifecycle, ordered learner-input revisions, safe checkpoints, a bounded
`TutorContextBuilder`, a primary-only provider gateway, and injectable ports
for later persistence, capability, effect, and compaction work.

The child proves the new runtime can make zero, one, or multiple bounded
iterations without inheriting `learning_stage`, rule-based specialist routing,
or LangGraph checkpoints as product state. It creates no learner-facing route,
desktop entry point, SQL table, or destructive migration.

## Dependencies and Documentation Authority

- Parent task `07-22-agent-harness-rearchitecture` was approved on 2026-07-26
  and remains planning-only. Child 00 has no upstream implementation child.
- The first implementation step publishes the narrow
  `docs/architecture/tutor-harness-transition.md` target contract and links it
  from `docs/README.md`; legacy documents remain evidence until later
  reconciliation by Child 08.
- Current code, tests, configuration, and route registration establish current
  runtime facts. Legacy Graph/API documents establish retained compatibility
  obligations but must not define new Harness behavior by default.
- Child 02 owns target SQL repositories, durable run events/checkpoints, and
  the transactional compaction outbox. Child 00 defines only typed ports and
  deterministic fakes required to prove the lifecycle contract.

## Requirements

- Add `app/agents/harness/` for immutable Tutor contracts and the deterministic
  `TutorContextBuilder`, and `app/services/tutor/` for service-owned provider
  and run-loop orchestration.
- Add a default-false `TUTOR_HARNESS_ENABLED` setting. No legacy API route,
  Graph path, SSE producer, or desktop UI consumes this flag in this child.
- Define explicit types for run status, terminal outcome, policy snapshot,
  lease, input event/revision, context selection metadata, checkpoint,
  provider decision, Skill reference, capability request, effect proposal, and
  typed compaction request.
- Implement a finite loop through injected run-store, provider, capability,
  effect-commit, clock, and compaction-publisher ports. The default capability
  and effect behavior remains denied/unavailable until Child 01 and Child 02.
- Re-read the current input revision before a new model call, capability
  dispatch, after capability result, and before effect commit. A newer revision
  rejects an uncommitted effect as `stale_rejected`.
- Implement `TutorContextBuilder` with explicit deterministic item/token
  budgets. It selects sanitized scoped inputs in target priority order and
  records only source identifiers, hashes, and selection metadata in a
  checkpoint; it never injects the whole raw conversation.
- Adapt the existing `OpenAICompatibleClient` behind a primary-only Tutor
  provider gateway. Reuse its selected-provider retry behavior, validate a
  strict Harness decision envelope, reuse public-output guardrails, and map
  configuration, call, invalid-output, or guardrail failure to a redacted
  `MODEL_UNAVAILABLE` terminal outcome without cross-provider fallback.
- Extract generic value redaction from the legacy graph module into an
  `app/agents/runtime/` boundary while retaining compatibility for current
  Graph callers. Harness modules must not import the legacy `graphs` package.
- Publish a typed, idempotent compaction request only at a terminal state, safe
  checkpoint, or configured context high-water mark. Do not create a Curator,
  worker, outbox row, or per-token trigger in this child.

## Acceptance Criteria

- [ ] `TUTOR_HARNESS_ENABLED` defaults to `false`; existing legacy Graph/API
  behavior remains unchanged and no new learner-facing route is registered.
- [ ] Fake provider tests prove zero, one, and multiple bounded iterations with
  no `learning_stage` transition, router selection, or Graph checkpoint use.
- [ ] A second accepted input increments the run revision; an effect built for
  the prior revision is rejected before commit and the loop rebuilds context.
- [ ] Context selection is deterministic, scoped, bounded by explicit budget,
  redacts hidden/provider/reference data, and leaves raw prompt/full history
  out of checkpoint metadata and diagnostics.
- [ ] Provider tests cover both configured DeepSeek and OpenAI-compatible
  adapters through fakes, preserve primary-only retry, and return the stable
  `MODEL_UNAVAILABLE` terminal result with no raw provider detail.
- [ ] Compaction request tests prove terminal/safe-checkpoint/high-water
  triggering, deterministic idempotency keys, and no per-token invocation.
- [ ] Generic redaction extraction retains existing Graph contract tests while
  letting Harness code import only runtime-level helpers.
- [ ] The transition document records Child 00's legacy/target/adapter boundary
  and the development-environment documentation records the disabled flag.
- [x] The user approved this child `prd.md`, `design.md`, and `implement.md`
  on 2026-07-26 and authorized implementation. The parent remains planning-only;
  this child alone owns the subsequent `in_progress` implementation state.

## Confirmed Facts

- The current product routes learner turns through `learning_stage`, keyword
  matching, and specialized-agent handoffs in
  `aearn/services/api/app/agents/graphs/router.py`; this is legacy behavior.
- `LANGGRAPH_ENABLED` defaults to `false`. Existing learning conversation code
  retains a stable non-Graph branch and swallows Graph invocation failure rather
  than changing the public flow.
- `OpenAICompatibleClient` already supports the configured DeepSeek Chat
  Completions and legacy OpenAI-compatible Responses shapes with bounded retry
  and typed configuration/call/invalid-response errors.
- The stable public model failure family is `MODEL_UNAVAILABLE`; current model
  paths must not expose provider errors, API keys, prompts, hidden tests, or
  reference answers.
- Runtime context helpers already sanitize/bound messages, summaries, and
  direct-answer requests. Generic recursive redaction currently lives under a
  legacy Graph module and must be made runtime-owned before reuse.
- Existing `tool_status` streaming is Graph-specific and uses bounded/redacted
  fields. Child 06, not Child 00, owns Tutor endpoint, durable event replay,
  and desktop/SSE integration.
- The worktree has unrelated upgrades and documentation edits. This child may
  touch only declared runtime, docs, test, and configuration paths; it must not
  revert, stage, or rewrite unrelated changes.

## Decisions

- **Feature flag:** introduce `TUTOR_HARNESS_ENABLED=false` as a distinct
  Harness seam; do not overload `LANGGRAPH_ENABLED`.
- **Persistence boundary:** use a `TutorRunStore` protocol and test fake only;
  do not add target SQL schema, repositories, or outbox implementation.
- **Provider boundary:** use one configured primary provider/model through the
  existing Aearn LLM client; no model/provider fallback or OpenAI Agents SDK
  handoff/tool path is introduced.
- **Context budget:** use an injected conservative estimator and deterministic
  selection order rather than provider-specific tokenizers or whole-history
  replay.
- **Output boundary:** use a Harness-specific strict decision schema plus
  existing generic guardrails; do not reuse the legacy stage-specific public
  output envelope as a product contract.
- **Compatibility:** preserve legacy routes, SSE vocabulary, Graph flags, and
  Graph tests; the Harness remains unreachable from product traffic.

## Out of Scope

- Skill catalog compilation, capability policy registration, or tool exposure.
- SQL migrations, PostgreSQL repositories, durable run event/checkpoint rows,
  idempotency records, and transactional curation outbox writes.
- New Tutor API endpoints, SSE event producers/replay, desktop UI, or composer
  merge UX.
- Container execution, proactive scheduling, Curator model calls, plan/memory
  mutation, user settings, cutover/reset, or legacy Graph retirement.
- Any provider credential, live external model call, broad dependency upgrade,
  or change to current legacy endpoints.
