# Rearchitect Aearn as a Skill-Native Tutor Agent Harness

## Goal

Rearchitect Aearn from several stage-bound LangGraph business flows and
rule-based handoff routing into one durable, skill-native Tutor Agent
Harness. The Tutor Agent must dynamically choose the next teaching action
from the learner's goal, live evidence, memory, available capabilities, and
explicit user instructions instead of following a predetermined onboarding,
learning, or review path.

The redesign must preserve Aearn's learning-domain correctness: code
execution remains runner-owned, evaluation and FSRS remain service-owned,
durable writes remain repository-owned, and learners retain control over
irreversible plan changes and long-running work.

Cross-day continuity must come from bounded external state rather than replaying
the full chat history into every model call. The Harness therefore includes an
internal Memory Curator / Context Compactor that prepares governed proposals;
it is not a second learner-facing teaching Agent.

This is an architecture-wide parent task. Its implementation will be split
into independently verifiable child tasks after planning converges.


## Requirements

- Replace the current top-level product routing model of separate onboarding,
  learning, review, resume, and note-assist graphs with a single Tutor Agent
  runtime that can load and apply relevant skills dynamically.
- Treat onboarding, concept teaching, diagnosis, practice coaching, code
  feedback, review coaching, plan revision, and note assistance as skills or
  governed capabilities rather than fixed execution paths.
- Use one user-facing Tutor Agent as the sole conversational decision-maker.
  It must dynamically load skills and capability bundles rather than delegate
  the main experience through a rule router or user-visible specialized-agent
  handoff topology.
- Keep the executable Skill catalog developer-owned, Git-versioned, reviewed,
  and testable. The Tutor Agent may dynamically select and load published
  Skills but must not create or persist new executable Skills at runtime.
- Allow the Tutor Agent to decide whether to explain, clarify, retrieve
  grounding, propose a plan change, create a practice activity, request code
  execution, suggest review, or wait for the learner. The user must be able
  to interrupt, redirect, or choose a different teaching approach at every
  turn.
- Permit the Tutor Agent to autonomously apply durable learning-plan revisions
  when policy permits. Every revision must be versioned, explain its evidence
  and expected impact in learner-safe language, expose a structured diff, and
  support a one-action rollback to the prior active revision.
- Permit the Tutor to begin with a clearly labelled provisional plan revision
  whenever it has enough evidence for a useful working hypothesis. Missing
  initial context must not block helpful teaching; later evidence may refine
  the active plan through the same version, diff, and rollback contract.
- Preserve the existing learning-domain authority boundaries: runner services
  produce execution facts; evaluation and FSRS services determine outcomes;
  repositories own transactions and idempotent durable writes; the Agent may
  propose commands but must not write durable domain state directly.
- Preserve existing public API and desktop SSE compatibility during migration,
  including `agent_message`, `tool_status`, `tool_call`, and `runner_result`.
  Any intentional contract changes need a versioned compatibility plan and
  desktop migration work.
- Introduce a capability gateway that dynamically exposes only the tools the
  current user, goal, runtime, policy, and consent state are allowed to use.
- Introduce durable Agent-run records, observable decisions, tool invocation
  records, bounded checkpoint/resume behavior, and replayable evidence for
  debugging and evaluation.
- Build each model call through a `TutorContextBuilder` with an explicit token
  budget. It selects only the active plan revision, review/FSRS snapshot,
  recent relevant messages, bounded working summary, selected learner memory,
  relevant activity/execution facts, policy, Skills, and allowed capabilities;
  it must never restore a whole conversation merely because it is retained.
- Retain new-Harness cross-session memory only as learner-inspectable,
  evidence-backed entries. Objective learning facts may be recorded from
  trusted domain services; inferred preferences or conclusions require
  evidence and confidence, remain editable/deletable/disableable by the
  learner, and never store raw prompts, hidden tests, secrets, or provider
  payloads.
- Add an internal background `Memory Curator` / `Context Compactor` that runs
  only from a durable terminal/checkpoint/evaluation/review/plan-change event
  or a context high-water mark. It consumes redacted durable outbox inputs and
  emits idempotent context-summary or memory-entry proposals; it never runs
  once per streamed token, forms a continuous self-running model loop, or
  becomes a learner-visible conversational Agent.
- Require every Curator proposal to carry source evidence, confidence,
  provenance, bounded-retention/staleness metadata, the applicable learner
  memory setting, and an idempotency key. Only the policy/service/repository
  path may validate and commit it. The Curator cannot directly change plans,
  FSRS/review state, attempts, messages, activity/inbox, or any domain table;
  trusted domain services continue to record objective facts directly.
- Run the first-release Curator through the configured primary provider/model
  only, with a lower per-job token, call, frequency, and retry budget than an
  interactive Tutor run. It may not silently select another provider/model or
  use task-based dynamic model routing when its primary provider is unavailable.
- Support policy-governed proactive Agent runs in the first implementation.
  Scheduled review preparation, grounded research, plan refinement, and other
  background work may execute without an active learner turn only when an
  explicit capability policy, cost/time budget, user consent setting, and
  audit record permit the run.
- Wake proactive work only from durable user events or policy-defined time
  signals. Each signal creates a deduplicated candidate run that must pass
  cooldown, budget, policy, and concurrency checks before the Tutor decides
  whether any action is worthwhile; wake-up signals must not encode a fixed
  teaching path or create a continuous self-running model loop.
- Restrict both interactive and proactive grounding to the developer-governed
  official/trusted source registry. The Tutor Agent must not receive an
  unrestricted open-web search or arbitrary document-fetch capability;
  registry changes remain reviewed product configuration.
- Enable the proactive Tutor Agent by default after the clean-slate cutover.
  The user may disable it, but the default product experience must allow all
  policy-permitted background capabilities to run without per-capability
  opt-in. Hard global pause, time/cost budgets, timeouts, failure circuit
  breakers, and durable audit traces remain mandatory.
- Keep DeepSeek and OpenAI-compatible models as first-class providers through
  a provider-neutral model and tool contract. The Tutor Agent Harness must not
  depend on a proprietary provider's high-level runtime APIs for core product
  behavior.
- After the configured primary model exhausts its safe retries, surface a
  stable `MODEL_UNAVAILABLE` outcome. The first Harness release must not
  silently switch providers or dynamically route across configured models.
- Retain the current safe context construction, redaction, hidden-test
  protection, provider-error protection, per-user data isolation, and
  existing code-execution sandbox constraints.
- Do not migrate legacy learner history into the new Harness. Existing
  learning sessions, messages, plans, attempts, review state, review logs,
  and legacy Agent runtime/checkpoint data are not a compatibility target.
- Gate the clean-slate cutover in the desktop product. When legacy learner
  data is detected, block entry to both legacy and new learning runtimes until
  the learner explicitly reviews the deletion/preservation summary and
  confirms the verified Harness reset; never delete it automatically during
  application startup or deployment.
- Replace the current non-container-grade code-execution boundary with a
  container-grade sandbox for Agent-initiated or learner-initiated execution.
  The sandbox must have resource limits, no default network access, scoped
  temporary storage, explicit image/runtime allowlists, and auditable
  lifecycle records.
- Permit automatic code execution without a second confirmation only inside
  an active learner interaction whose current intent explicitly requests
  running, testing, debugging, or explaining code. Proactive background work
  must never execute learner code; each permitted execution must be visible
  in the activity record and a run alone must not mutate plan or FSRS state.
- Keep internal domain services as typed commands with MCP-compatible schemas.
  Use MCP transport only for cross-process, external, or separately deployed
  capabilities; do not require MCP for every in-process domain call.
- Include the complete end-user experience: natural-language goal entry,
  free-form learning conversations, practice and real runner feedback,
  review suggestions, plan revisions, interruption, recovery, and a
  learner-facing explanation of meaningful Agent actions.
- Start a new Harness learner with guided conversation rather than a blank
  composer or a fixed multi-step form. The entry surface may offer small goal
  examples and shortcuts, but must accept free text and let the Tutor ask only
  contextually useful follow-ups.
- Keep the composer available while an interactive Tutor run is active and
  merge newly received learner messages into the active Agent loop rather
  than forcing a cancellation choice. Persist each message as an ordered
  in-run input event; at safe loop checkpoints the Tutor must refresh its
  bounded context, re-evaluate the current objective, and continue, redirect,
  or stop work autonomously while preventing stale uncommitted effects.
- Present learner-safe Agent activity in the normal learning experience:
  action timeline, plain-language reason, relevant sources, revision diffs,
  execution outcome, and rollback controls. Keep detailed but redacted run
  traces in a dedicated diagnostics surface rather than the learning flow.
- Deliver meaningful proactive outcomes to an in-app activity inbox backed by
  the activity timeline. Normal successful background work must not be
  appended to the active chat transcript or generate a desktop notification;
  the Tutor may explain the result in context when the learner opens it or
  starts a later turn.
- Produce a full implementation task tree, migration order, rollback plan,
  API/data compatibility plan, validation matrix, and documentation updates
  before implementation begins.
- Freeze documentation authority before any child starts. The freeze must
  distinguish verified current-runtime facts, legacy/current source documents,
  and the approved Harness target; it must assign each documentation delta to
  a child and prohibit silently applying a legacy Graph rule to the new runtime.


## Acceptance Criteria

- [x] Planning documents define a single autonomous Tutor Agent execution
  model, its skill catalog, capability boundary, durable state, policy
  boundary, user controls, and observability/evaluation model.
- [x] The plan identifies every current Graph/rule-router surface that will
  be migrated, retained as a domain service, deprecated, or removed.
- [x] The plan preserves the authority of runner, evaluation, FSRS,
  repository, API, and SSE layers and defines command-level contracts for all
  Agent-requested durable effects.
- [x] The plan covers onboarding, learning, review, resume, plan revision,
  and note assistance, including user-visible flows and desktop changes.
- [x] The plan has independently verifiable child tasks, ordered dependencies,
  rollback points, test/QA commands, and cross-child integration acceptance
  criteria.
- [x] The plan defines compatibility handling for current model providers and
  API/SSE consumers, plus a verified clean-slate retirement path for legacy
  sessions and LangGraph checkpoints.
- [x] Documentation authority distinguishes legacy baseline documents,
  verified repository facts, and the proposed Harness target; every child PRD
  declares its dependency and documentation responsibilities.
- [x] Parent sub-agent context manifests contain real specification and research
  entries for both implementation and checking.
- [x] The plan defines a bounded Context Builder and a non-conversational,
  proposal-only Memory Curator with explicit trigger, redaction, budget,
  commit-authority, learner-control, and no-direct-domain-write boundaries.
- [x] The existing `07-22-*` tree is compatible with Trellis `0.6.8`: the
  parent has real dispatch context, and every child has a documented
  just-in-time readiness gate before it can enter implementation.

- [x] The user approved `prd.md`, `design.md`, and `implement.md` on
  2026-07-26. The parent remains planning-only; no parent `task.py start`
  occurs, and each child still requires its own latest planning approval
  before that child can enter implementation.

## Confirmed Facts

- The backend currently pins LangChain, LangGraph, the PostgreSQL LangGraph
  checkpointer, Redis, Celery, and the OpenAI Agents SDK.
- Current model configuration supports the official DeepSeek Chat Completions
  provider and a legacy OpenAI-compatible Responses provider.
- Current top-level Agent behavior is divided across onboarding, learning,
  review, resume, and note-assist Graph specifications, plus a rule-based
  specialized-agent router.
- Current Graphs emit typed intents while service and repository layers own
  durable writes. Existing runner, evaluation, FSRS, guardrail, context,
  checkpoint, and SSE contracts must be treated as migration constraints.
- The desktop application already renders streamed agent messages, tool
  status, tool calls, and runner results, and currently derives UI behavior
  from `learning_stage` and `learning_stage_state`.
- The user does not want current learner history migrated into the new
  Harness. Existing learning sessions, messages, plans, attempts, review
  state, review logs, and related legacy Agent runtime data are not a
  compatibility target.
- The clean-slate reset must also remove the legacy learner profile and any
  Agent-derived learning preferences. It must retain local provider/model
  configuration, UI settings, and the local application identity.
- The worktree contains unrelated uncommitted changes. Planning and later
  implementation must isolate this task's paths from those changes.
- Trellis was upgraded in this worktree from `0.6.0-beta.21` to `0.6.8`.
  The existing parent/child task graph and the session-scoped active-task
  pointer resolve through the new CLI, so task directories, identifiers, and
  planning status do not need to be recreated merely for the framework upgrade.

## Trellis Upgrade Transition

The upgrade changes planning readiness rules, not the approved Harness product
scope or this parent task's planning-only role.

- The parent already has the complex-task artifacts and real context manifests
  required by the current sub-agent workflow, and it remains `planning` until
  the user reviews the final plan.
- The current CLI's `task.py validate` checks JSONL shape and referenced paths;
  it accepts seed-only manifests with zero real entries. A successful validate
  result alone therefore does not make a complex child implementation-ready.
- Before any existing child is selected for `task.py start`, its PRD must be
  refreshed against current code and its declared dependencies, then completed
  with its own `design.md`, `implement.md`, and at least one real entry in both
  `implement.jsonl` and `check.jsonl` for the current Codex `auto` dispatch
  workflow.
- **Decision confirmed on 2026-07-26:** preserve the existing task tree and
  use just-in-time readiness migration. Only the child whose upstream
  contracts are frozen and which is selected as the implementation target is
  refreshed against current code, completed with `design.md` and
  `implement.md`, and given real dual-manifest context. This prevents nine
  speculative implementation plans from becoming stale while ensuring that no
  child is marked `in_progress` or starts without the new-version gate.

## Documentation Authority

**Decision confirmed on 2026-07-24:** this parent remains planning-only. The
current documents indexed by `docs/README.md` remain the legacy/current
baseline; code, tests, schema, route registration, and configuration establish
factual current behavior; this parent `prd.md`, `design.md`, and `implement.md`
define the proposed Harness target until the user approves the final review.

- The relevant product, API, database, and LangGraph documents predate this
  July 2026 task. `docs/current/Aearn/current-state-audit.md` already records
  API/route drift, so old prose cannot override a current repository fact.
- After approval, Phase 0 must publish and link a narrow
  `docs/architecture/tutor-harness-transition.md`. It labels each surface as
  `legacy baseline`, `target contract`, `adapter window`, or `retired` before a
  child relies on a new field, route, event, migration, reset action, or UI
  behavior.
- A child records every legacy/current/target discrepancy in the documentation
  delta matrix and obtains the target contract before coding. It cannot infer
  an upstream dependency from tree order alone.
- No broad source-document rewrite or historical archival happens in planning;
  final source-of-truth consolidation remains Child 08 after proof exists.


## Out Of Scope

- Replacing the learning product with a general-purpose coding-agent product.
- Giving the Agent unrestricted filesystem, network, shell, database, or
  cross-user data access.
- Treating multi-agent delegation as the default interaction model before the
  single Tutor Agent Harness is validated.
- A continuously running, per-token, or learner-visible background Agent that
  may directly mutate memory, plans, review/FSRS, attempts, or other domain
  state without the normal policy/service/repository commit path.
- Starting implementation before the full planning artifacts are reviewed and
  approved.
- A developer learning roadmap, syllabus, labs, or learning materials as a
  Trellis deliverable. If requested later, provide it directly or in a separate
  task rather than coupling it to this rearchitecture.

## Decisions

- Developer learning roadmap: removed from this parent task on 2026-07-24. It
  is not an implementation or acceptance deliverable; provide it separately
  only when the user explicitly asks for it.
- Runtime strategy: provider-neutral. The transformed Harness must retain
  first-class support for official DeepSeek Chat Completions and
  OpenAI-compatible providers through Aearn-owned contracts.
- Autonomy boundary: include proactive background Agent runs in the first
  implementation. All such runs require policy gating, budgets, user consent
  where personal learning data is involved, durable trace records, and safe
  failure/retry behavior.
- Proactive-run consent: enabled by default. The learner can disable the
  Proactive Tutor, but policy-permitted background capabilities otherwise run
  without a per-capability opt-in. Global pause, budgets, timeout, circuit
  breaker, and audit controls are still non-optional.
- Proactive-result delivery: meaningful results are persisted in the
  learner-facing activity timeline and in-app inbox with unread state. Normal
  successful background work must not create an unsolicited chat message or
  desktop notification; opening an item or starting a later conversation lets
  the Tutor explain it in the current learning context.
- Proactive wake-up: event plus time signals. User events and policy-defined
  due/refresh signals create durable candidate runs rather than directly
  invoking a fixed teaching flow. A candidate runs only after deduplication,
  cooldown, user-level concurrency, budget, and capability-policy checks;
  the Tutor then remains free to act or intentionally do nothing.
- Grounding network boundary: allowlisted official/trusted registry only.
  Interactive and proactive runs may retrieve only sources registered in the
  developer-reviewed registry; they may not use open-web search or arbitrary
  URL fetching. The registry remains language-aware and carries source and
  domain validation metadata.
- Long-term plan mutation: autonomous versioned revision. The Agent may
  activate a policy-permitted `LearningPlanRevision` without a confirmation
  click; every change must preserve a prior version, show a learner-safe
  reason and structured diff, and support one-action rollback.
- Agent explainability: learner-safe activity timeline in the normal product
  surface, including reason, sources, action outcome, plan revision diff, and
  rollback controls. Full but redacted traces are restricted to diagnostics.
- Agent topology: single Tutor Agent with dynamically loaded skills. Retire
  rule-based specialized-agent routing and user-visible handoffs from the
  primary product runtime; background workers remain infrastructure, not
  conversational agents.
- Memory Curator: in scope as a background infrastructure worker, not a second
  Tutor. The Context Builder creates a bounded curation request only at a safe
  terminal/checkpoint or other durable trigger; Child 02 persists ordered,
  redacted requests/proposals, Child 04 supplies low-priority queue/budget/
  retry primitives, and Child 05 owns proposal semantics plus the guarded
  Curator. It can propose a scoped context summary or learner memory entry but
  cannot commit either directly or create chat, inbox, plan, review, FSRS, or
  execution effects.
- Skill ownership: developer-owned and Git-versioned. Each published Skill
  must have a stable identifier, semantic version, source/resources, tool and
  capability requirements, policy tags, and automated evaluation coverage.
  The Agent cannot persist self-generated executable Skills.
- Deployment boundary: ship a container-grade sandbox in the first
  implementation. Internal Aearn capabilities remain typed commands with
  MCP-compatible schemas; only external, cross-process, or separately
  deployed capabilities use MCP transport.
- Legacy data migration: clean-slate cutover. Do not migrate legacy learning
  sessions, messages, plans, attempts, review state, review logs, or legacy
  Agent runtime/checkpoint data into the new Harness. The implementation must
  provide an explicit, verified reset/retirement path rather than silently
  deleting data during deployment.
- Reset scope: clear all legacy learning and Agent-derived data, including the
  learner profile. Retain the local application identity, model provider
  configuration, and UI settings so the user does not need to reconfigure the
  development environment after the cutover.
- Clean-slate cutover UX: a one-time in-product reset gate. If legacy data is
  present, the desktop must block both old and new learning runtimes, show the
  exact deleted and retained categories, require confirmation, execute the
  extended reset atomically, verify that legacy data and checkpoints are gone,
  clear stale bootstrap state, and then open the new Tutor goal conversation.
  The existing local reset flow must be extended because it currently retains
  learning preferences that this cutover must remove.
- Code-execution consent: contextual interactive autonomy. When the current
  learner message explicitly asks to run, test, debug, or explain code, the
  Tutor may execute the active code or a minimal repro inside the approved
  container without another confirmation click. It may never execute learner
  code from proactive background work. Every execution produces an activity
  record and does not by itself change the learning plan or FSRS state.
- Interactive interruption: in-loop learner-message merge. The composer
  remains available during an active run, and each new message is durably
  sequenced into that run's input channel rather than presenting the learner
  with a continue/cancel choice. At safe checkpoints--before a new model or
  tool step, after a tool result, and before any durable effect--the Tutor
  refreshes its context and autonomously re-plans around the newest message.
  The UI may acknowledge that the Tutor is adjusting, but must not require an
  interrupt decision. Started work is cancelled only when safe and useful;
  stale uncommitted effects are rejected by the run input revision, while
  already committed safe facts remain visible in the activity timeline.
- First-run goal intake: guided conversation. The initial screen may offer
  concise goal examples and shortcuts but always accepts free-form input. The
  Tutor asks only questions that matter to its present decision and must not
  require the legacy language/level/goal slot sequence before it can be
  helpful.
- Initial planning: provisional-first. When the Tutor has a useful working
  hypothesis, it may activate a clearly labelled provisional plan revision or
  begin teaching without waiting for all initial context. Later language,
  level, schedule, or goal evidence refines the plan through normal
  versioning, learner-safe diffs, and one-action rollback.
- Cross-session memory: durable, evidence-backed, and learner-inspectable.
  Objective facts from runner/evaluation/review services may be recorded
  automatically. Any inferred preference or conclusion must retain its
  evidence and confidence, appear in a manageable learning-memory surface,
  and support correction, deletion, and a user-level disable control. Raw
  prompts, hidden tests, secrets, and provider payloads remain excluded.
- Curator user-control behavior: a hard background pause or memory-disable
  setting blocks new inferred-memory work; disabling an inferred-memory
  projection does not change the authoritative runner/evaluation/review facts
  that produced it. Provider failure leaves the request pending, skipped, or
  safely failed with a redacted trace under the already-defined primary-provider
  failure policy.
- Model failure behavior: fail closed after safe same-provider retries. The
  Harness must return the stable `MODEL_UNAVAILABLE` outcome and retain an
  auditable, redacted failure record; it must not silently invoke another
  provider or dynamically select a different model in the first release.


