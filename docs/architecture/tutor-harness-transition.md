# Tutor Harness Transition Contract

## Status and Authority

This transition contract records the feature-disabled, in-process Tutor
Harness seam from Children 00/01, the target-only durable foundation from Child 02,
the scheduling/queue seam from Child 04, and the Child 05 learner-state projections.
None of these target layers adds a learner-facing API, SSE stream, Desktop entry
point, legacy-data migration, cutover, or product activation.

| Authority | Meaning |
| --- | --- |
| **Legacy baseline** | Current routes, Graph routing, `learning_stage`, Graph checkpoints, SSE vocabulary, persistence, and desktop flows remain the compatibility baseline. |
| **Target contract** | The immutable Harness contracts, bounded context builder, primary-only provider gateway, finite loop, catalog policy boundary, and Child 02 target-only durable state/replay/redaction contracts. |
| **Adapter window** | Until Child 06, the Harness is unreachable from product traffic. Existing API/SSE/Desktop flows preserve legacy contracts while future adapters translate at the boundary. |
| **Retired** | Nothing is retired by Child 00. Later cutover work owns explicit retirement and migration decisions. |

Current code/tests establish legacy facts. This document only defines the new
internal target contract.

## Legacy Baseline: Explicit Non-Changes

- `LANGGRAPH_ENABLED` remains the legacy Graph flag and is not reused.
- Legacy `learning_stage` routing, specialist handoffs, Graph checkpoints,
  routes, SSE events, and desktop flows continue to own product traffic.
- Existing provider configuration and selected-provider retry remain owned by
  `OpenAICompatibleClient`.
- Existing product persistence remains the legacy schema/repository boundary.
  Child 02's additive `tutor_*` records are isolated, feature-off target state;
  they do not migrate, delete, or alter legacy learner records.

`TUTOR_HARNESS_ENABLED=false` remains a separate future-integration seam. No
current product route, Graph path, SSE producer, worker, or UI reads it after
Child 02.

## Target Run and Input Contract

`TutorRunSnapshot` is immutable and contains opaque run/conversation/user ids,
a monotonic `input_revision`, and fixed policy/lease/counter data.
`TutorCheckpoint` retains only redacted source/budget metadata, while terminal
results expose only learner-safe public text and stable diagnostic codes. None
of those contracts contains raw provider payloads, prompts, full history,
hidden tests, reference answers, submitted code, or secrets.

```text
queued -> leased -> running
running -> waiting_for_input | waiting_for_capability | awaiting_effect_commit
running -> completed | model_unavailable | blocked_policy | budget_exhausted | cancelled | failed
```

Each accepted `TutorInputEvent` has an opaque message id and monotonic
revision. `TutorRunStore.current_input_revision(run_id)` is authoritative. The
loop reloads it before every model call, before capability dispatch, after a
capability result, and before effect commit. A different expected revision makes
an effect `stale_rejected`; its committer is never called.

The fixed policy bounds iterations, model/capability/effect calls, deadline,
and context tokens. Child 00 supplies ports plus deterministic fakes/default
denials only; later persistence makes the same protocol durable.

## Target Context, Checkpoint, and Compaction Contract

`TutorContextBuilder` accepts only pre-scoped facts and selects them in this
stable order: system/selected-Skill/policy descriptors; active plan revision;
review/FSRS snapshot; recent sanitized messages; working summary; learner-
visible memory; activity/execution facts; allowed capability schemas.

Each section has explicit item/token budgets. The default estimator is
deterministic and conservative (UTF-8 byte count). Sanitization/runtime
redaction happens before selection. Checkpoints retain only section counts,
source ids/hashes, and consumed-budget metadata—never composed prompts or raw
source content.

High-water output is an idempotent typed compaction *request*, not a Curator
call. It is emitted only on a terminal state, safe checkpoint, or configured
context high-water condition, never per streamed token.

## Target Provider and Decision Contract

`PrimaryTutorProviderGateway` is the only Child 00 model boundary. It wraps
the configured `OpenAICompatibleClient`, retaining the selected provider/model
and bounded retry behavior for DeepSeek Chat Completions and legacy
OpenAI-compatible Responses. It never changes settings or attempts a cross-
provider/model fallback.

The strict Harness decision envelope permits bounded learner-safe public text,
Skill refs, capability requests, effect proposals, optional safe-checkpoint
reason, and terminal intent. It rejects unknown/malformed/duplicate fields,
reasoning/diagnostic fields, and unsafe text. Generic teaching-output
guardrails remain the text safety boundary.

Configuration, selected-provider call, response/schema, or guardrail failures
become redacted `MODEL_UNAVAILABLE`; raw provider errors, prompts, keys, and
payloads never cross this contract.

## Child 01 Target: Skill Catalog, Policy, and Registry Grounding

Child 01 adds an isolated internal catalog/gateway composition only. It does
not make the Harness reachable from product traffic or change the default
`TUTOR_HARNESS_ENABLED=false` posture.

### Published Skill Catalog

- Reviewed bundles live under
  `aearn/services/api/app/agents/skills/<skill_id>/<semantic_version>/` and
  contain `manifest.json`, a UTF-8 reviewed instruction, and a non-empty JSON
  evaluation suite in the same Git-owned tree.
- The compiler accepts exact SemVer 2 references only, verifies bundle-relative
  resource names and content hashes, checks reviewed registry references,
  declared descriptors/effects, and compiles the complete set into an ordered,
  immutable snapshot with a canonical SHA-256 digest. An invalid bundle rejects
  the whole snapshot; there is no partial or `current` fallback.
- `tutor.registry-grounding@1.0.0` is the initial published Skill. It requires
  only `grounding.retrieve`, declares the reviewed
  `registry:grounding_sources` resource, and declares no allowed effect type.
  Skills remain instruction/resource data, not model-authored or executable
  code.

### Catalog Context and Decision Boundary

- A catalog context loader decorates the existing bounded context input. Before
  selection it supplies only policy-eligible exact-version Skill summaries and
  MCP-compatible JSON schemas. After a validated selection it supplies that
  exact reviewed instruction plus id/version/hash facts. It never exposes a
  legacy tool registry or arbitrary catalog file body.
- The Child 01 selection store remains run-local for its isolated composition.
  Child 02 persists the resolved exact catalog digest plus Skill id/version and
  manifest/instruction/evaluation hashes by `(run_id, input_revision)`. A
  mutable `current`, range, wildcard, or instruction body is never durable
  replay evidence. A newly selected Skill still causes a context rebuild and
  cannot dispatch a capability or propose an effect in the same model decision.
- The catalog decision gate runs after strict provider-envelope parsing and
  before checkpoint/capability/effect work. It rejects unversioned, unknown,
  policy-ineligible, malformed, or mixed selection/action decisions without
  fallback. The default uncomposed gate denies model-selected Skills,
  capabilities, and effects.

### Capability Policy and Effect Boundary

- `CapabilityPolicyContext` binds run/user scope, origin, current input
  revision, catalog digest, consent, runtime availability, remaining budget,
  policy tags, eligible exact Skill references, and registered source scope.
  The default resolver publishes no Skill, capability, effect, or source.
- Only descriptor-declared fields are decoded from the bounded provider
  envelope. Unknown field names, URLs, paths, images, SQL fragments, shell
  commands, arbitrary user identifiers, and function-like targets are denied
  before a lookup is attempted.
- Effects remain typed `TutorEffectProposal` values carrying
  `expected_input_revision`. The initial catalog has no effect descriptor or
  allowed effect type, so effect proposals are denied before the default-deny
  committer and no domain mutation path is reached.

### Registry-Only Grounding

- The sole executable Child 01 capability is `grounding.retrieve@1.0.0`. It
  accepts only bounded language/query/topic/count fields, derives eligible
  source ids from `grounding_sources.py`, and returns capped snippets with
  citation/source metadata.
- The gateway receives an injected `GroundingLookup` adapter. Its in-memory
  implementation reuses pure retrieval over supplied indexed chunks; the
  catalog, Harness, and gateway do not directly import a database connection,
  persisted index repository, HTTP fetcher, crawler, shell, runner, or legacy
  teaching tool.
- Child 02 persists only bounded capability invocation/effect evidence:
  resolved catalog/policy/revision/lease facts, safe status codes, and hashes.
  It never serializes arbitrary targets, lookup bodies, provider payloads,
  prompts, or full snippets. No route, SSE frame, Desktop component, worker,
  provider-routing change, or legacy Graph/tool removal is authorized here.

## Child 02 Target: Durable State, Replay, and Safe Curation Envelope

### Additive Schema and Scoped Lifecycle

Child 02 extends the repeatable API bootstrap schema with the additive,
feature-off `tutor_*` family: target conversations/messages, immutable catalog
snapshots, runs, exact Skill selections, accepted inputs, metadata-only
checkpoints, ordered run events, capability/effect receipts, redacted traces,
and curation outbox/proposal envelopes. It introduces no Alembic runner or
parallel migration mechanism. All records are user/run/conversation scoped;
legacy learner sessions, messages, attempts, plans, reviews, FSRS state, and
notes remain untouched.

A learner input is accepted in one transaction: scope and terminal checks,
run-scoped idempotency-key/body-hash replay or conflict, canonical learner text
write to `tutor_messages` only, monotonic input-revision allocation, reference
input event, and one safe `input_accepted` event. Diagnostics, events,
checkpoints, traces, outbox rows, proposal rows, and exports are not raw
conversation storage.

### Durable Ordering, Lease, and Effect CAS

`tutor_runs.next_event_sequence` is allocated under the locked run row in the
same transaction that writes a `tutor_run_events` record. The internal replay
cursor is the monotonically increasing, run-local integer `event_sequence`.
Reads return only the ordered suffix where `event_sequence > after_sequence`.
This is an internal repository contract, not an SSE `id`, `Last-Event-ID`,
delivery acknowledgement, or public reconnect promise.

Checkpoint/high-water/terminal lifecycle writes atomically include their safe
ordered event, redacted trace, and deduplicated curation outbox row. A failed
transaction exposes none of its partial checkpoint/result/event/trace/outbox
rows. Terminal updates use a guarded state transition, so a losing writer gets
a stable final/lease receipt rather than a second terminal sequence.

Effect commit checks the target user scope, active lease owner/generation and
expiry, non-terminal state, and expected current input revision in the same
transaction. Stale or invalid-lease proposals persist only
`stale_rejected` safe evidence and an event; no domain committer is invoked.
Actual domain effects remain default-deny until an owning child supplies an
explicit in-transaction handler.

### Redaction, Export, and Curation Boundaries

Child 02 uses a shared allowlisted safe projection at diagnostic write time and
again on export/read. Raw prompts/history, provider payloads/errors/reasoning,
keys/tokens, hidden tests, solution/reference material, full code, stack
traces, host/container paths, shell or SQL targets, and credential-bearing URLs
are removed even when nested or disguised under an allowed-looking field.
Canonical raw learner text remains only in `tutor_messages`.

The curation outbox stores a redacted typed compaction request with a closed
source event range, source ids/hashes, policy and memory-setting versions,
retention/staleness, priority, and deterministic idempotency identity. At most
one `context_summary` or `memory_entry` proposal envelope exists per outbox
identity. Child 02 does not lease a queue, retry jobs, call a model, semantically
validate a proposal, or project it into learner memory, plans, reviews, FSRS,
attempts, activity, or chat.

### Deterministic Evaluation Boundary

Source-controlled `tests/fixtures/tutor_evals/` cases use only fixed clocks,
fake providers/gateways/stores/committers, and exact catalog/Skill digest/hash
identity. They cover policy denial, strict provider-envelope rejection, bounded
loop exit, stale revision/effect behavior, primary-only `MODEL_UNAVAILABLE`,
and redaction leakage without a live model, network, worker, or wall clock.

## Child 03 Target: Isolated Container Executor

Child 03 adds a feature-disabled, durable execution foundation. It does not
make the Harness reachable from product traffic and does not change the legacy
runner, route, Graph, SSE, Desktop, or general Celery-worker boundary.

- `runner.execute` is an exact catalog effect that accepts only a server-issued
  opaque `ExecutionIntentProofV1` reference. The proof binds an interactive
  user/conversation/run/revision/message/exercise scope, explicit action,
  catalog/policy/budget evidence, and expiry. Proactive origin, stale scope,
  cancellation, missing evidence, or extra model fields create no job.
- The Child 02 in-transaction handler only records or replays one
  `tutor_execution_jobs` row and consumes the proof. It does not contact an
  image registry, runtime daemon, or legacy runner. The durable PostgreSQL job
  table is the execution source of truth; later broker delivery can only be a
  wake-up optimization.
- Only `aearn/services/executor/` owns the runtime client. It claims jobs after
  commit, reserves one immutable launch token before an external action, and
  either adopts a matching labeled runtime or records `launch_uncertain`.
  Uncertainty is terminal rather than a reason to launch a second runtime.
- The Git-owned catalog names the seven reviewed protocol entries: Python,
  browser preview, TypeScript, SQLite, Java, Go, and C#. Rust and C++ remain
  absent. `image-locks.json` contains only reviewed
  `repository@sha256:<64-hex>` locks; an omitted lock is unavailable, never a
  tag, local image, pull, or host-process fallback.
- `TUTOR_EXECUTOR_ENABLED=false` is independent from both
  `TUTOR_HARNESS_ENABLED` and `REAL_EXECUTION_ENABLED`. API availability reads
  only a compatible executor heartbeat and lock fingerprint. It never contacts
  the runtime daemon.
- Intent/job/audit/event/export projections retain opaque ids, fingerprints,
  enums, counters, and capped learner-safe result facts only. They exclude
  source code, hidden tests, image details, runtime identifiers, commands,
  mounts, paths, container identifiers, and raw runtime errors.

The standalone process and its operator workflow are documented in
[`../setup/container-sandbox-executor.md`](../setup/container-sandbox-executor.md).

## Child 04 Target: Proactive Scheduler and Curation Queue

Child 04 adds only feature-disabled durable scheduling mechanics. It does not
expose a route, SSE frame, desktop state, notification, chat message, legacy
review-worker behavior, or product-domain projection.

- A committed domain fact or bounded time scan records a typed signal with a
  stable producer identity, source hash, dedupe key/window, safe reference
  fields, and an auditable disposition. Candidate creation records every allow,
  no-action, or duplicate-window decision; PostgreSQL is authoritative for
  dedupe, leases, retries, and broker redelivery recovery.
- Scheduler policy is fail-closed: global enable, hard pause, verified cutover,
  per-user preference/pause, separate daily budget, concurrency, cooldown, and
  circuit-breaker limits are checked before a run or Curator processor can be
  invoked. Defaults keep the scheduler disabled and background work hard-paused.
- A proactive candidate reserves one internal `tutor_conversations` record
  (`visibility=internal`, `kind=proactive`) and one `tutor_runs` record with
  `origin=proactive` before the existing finite `TutorRunLoop` can run. The
  background composition permanently rejects `runner.execute` and
  `tutor.memory.record`. It may receive only explicitly policy-composed
  `tutor.plan.activate`, `tutor.plan.rollback`, or `tutor.activity.record`
  authority with a positive effect budget; the default composition remains empty
  and has no normal-success chat/desktop delivery path.
- The curation queue seeds exactly one low-priority job per Child 02 pending
  outbox identity. It preserves the outbox as the redacted semantic envelope and
  rechecks source revision/policy/memory-setting/retention facts before work.
  Child 04's injected default remains no-action; Child 05 may compose a
  primary-only Curator only when all scheduler gates pass and
  `TUTOR_CURATION_MAX_OUTPUT_TOKENS > 0`. It cannot directly write chat, plan,
  review, FSRS, attempt, filesystem, or an arbitrary provider/model target.
- The worker exposes bounded target task names
  `tutor.proactive.scan_due_signals`, `tutor.proactive.drain_candidates`, and
  `tutor.curation.drain`. They delegate to API-side policy/repository services;
  their default feature-off behavior makes no model, capability, or domain call.

## Child 05 Target: Learner State, Curator Projection, and User Controls

Child 05 adds feature-disabled target-domain state without changing the legacy
`learning_plans`, learner-profile, review, FSRS, attempt, route, SSE, Desktop,
or Graph boundaries.

- The reviewed catalog adds exact descriptors for `tutor.plan.activate`,
  `tutor.plan.rollback`, `tutor.memory.record`, and `tutor.activity.record`.
  The reviewed `tutor.learner-state@1.0.0` Skill declares only those effects.
  The default policy still grants none. `PostgresTutorRepository.commit_effect_if_current()`
  now revalidates the descriptor payload as well as the selected Skill evidence
  before invoking an in-transaction handler.
- `tutor_plan_revisions` is immutable, `tutor_active_plans` is the sole mutable
  pointer, and `tutor_plan_revision_actions` is append-only. An activation adds
  a revision plus evidence and predecessor; rollback can move only to the active
  revision's recorded predecessor. Neither path writes legacy plans, review,
  FSRS, attempts, or learner profiles.
- `tutor_memory_entries` distinguishes `objective_fact` from `inference`.
  Objective facts can be evidence-backed effects or trusted/user-control
  records. Inferences require Curator provenance, confidence, policy and
  memory-setting versions, retention/staleness, and a redacted outbox/proposal
  scope. Corrections append a linked replacement; deletion is a guarded state
  transition, not a raw-data rewrite. `tutor_memory_preferences` versioning
  invalidates stale queued work.
- `tutor_activity_records` is append-only learner-safe evidence and
  `tutor_inbox_items` is its optional, user-scoped read/dismiss projection.
  Neither table stores prompt, trace, provider reasoning, code, path, command,
  SQL, hidden-test, or secret data.
- `PrimaryCurationGateway` sees only the Child 02 redacted envelope and calls
  the configured primary `OpenAICompatibleClient` once with no provider/model
  fallback. `TUTOR_CURATION_MAX_OUTPUT_TOKENS=0` is the default no-call mode.
  A typed result can create exactly one context summary or inference projection;
  `tutor_curation_projection_receipts` records `committed`, `no_action`,
  `stale`, or `failed` without turning generic proposal rows into a raw provider
  payload store.
- Child 05 remains unreachable from product traffic. Child 06 owns public API,
  SSE, and Desktop adaptation; Child 07 owns cutover and legacy retirement.

## Child 06 Target: Public API, Cursor SSE, and Pre-Cutover Desktop

Child 06 may expose a versioned `/api/tutor` adapter over the durable target
records. It does not make the Harness the normal product path: with
`TUTOR_HARNESS_ENABLED=false`, every target route returns the stable
`CUTOVER_REQUIRED` envelope before a target-domain read or write. Setting that
route-composition flag is not a cutover confirmation, does not delete legacy
data, and does not authorize Graph retirement; Child 07 owns those gates.

| Surface | Child 06 status | Compatibility rule | Removal gate |
| --- | --- | --- | --- |
| Existing learning/onboarding/review/notes routes and Graph SSE streams | legacy | Preserve current request, event, and desktop behavior. No implicit reroute. | Child 07 and Child 08 replacement proof. |
| `POST /api/tutor/conversations`, input/run/activity/memory/plan/preference routes | new | Use only user-scoped `tutor_*` target records and stable envelopes. | Retained target surface. |
| `GET /api/tutor/runs/{run_id}/events` | new | Adapt ordered durable events to SSE ids and `Last-Event-ID`; never call a provider while streaming. | Retained target surface. |
| Legacy endpoint to Tutor translation | adapter | Explicit, versioned, and tested only; Child 06 adds no automatic adapter. | Remove only after replacement consumers pass. |
| Harness desktop components | new, cutover-gated | Compile typed UI/contracts without changing the default legacy app entry. | Child 07 server cutover state. |

All target mutations require a client idempotency key. The adapter persists only
the operation/key/body hash and a learner-safe response projection; a replay
returns the original projection and a different body is
`IDEMPOTENCY_CONFLICT`. Conversation input creates one interactive run only
when no non-terminal compatible run exists; otherwise it calls the durable
input-acceptance transaction and returns its monotonic input revision. It never
cancels a run or starts a competing legacy stream for a second learner message.

The public SSE cursor is a non-negative decimal `Last-Event-ID` scoped to one
run. The adapter reads the ordered durable suffix where
`event_sequence > cursor`, frames each sequence as the public SSE `id`, and
maps only learner-safe event facts. Existing compatible event names remain
available where applicable; `input_accepted`, `run_state`, and `activity` are
new optional event types. A route or replay error raised before it can be tied
to one durable event is terminal but has no SSE `id`; desktop code must model
that frame as `id: null`, retain its last numeric cursor, and never use an
error frame as `Last-Event-ID`. Raw learner messages, traces, Curator
prompts/source segments/rationale, provider payloads/errors, code, paths,
hidden tests, Attempt, and FSRS details are never API/SSE/Desktop fields.

Learner controls read immutable plan lineage/diffs, learner-safe memory
provenance/retention facts, and activity/inbox state. User plan rollback can
move only to the active revision's recorded predecessor and appends an audited
user-control action; it cannot choose a target revision or mutate legacy plan,
review, FSRS, attempt, or profile data. User memory corrections append a linked
replacement and deletion remains a guarded state transition. Preference routes
may expose inferred-memory enablement and a user's proactive pause, but never
enable background work, relax hard pause/budgets, or expose provider settings.

## Child 07 Target: Verified Clean-Slate Cutover Gate

Child 07 owns the one-time transition from the legacy learning runtime to the
public Tutor surface. It does not migrate legacy learner history and it does
not physically remove Graph, route, tool, dependency, or documentation code in
the first cutover change.

- `TUTOR_HARNESS_ENABLED=false` preserves the legacy product path and keeps
  `/api/tutor/*` feature-off. The flag is only rollout composition; it never
  proves that a local learner has cut over.
- With the flag enabled, both user-scoped legacy runtime routes and Tutor
  routes consult the same `harness_cutovers(user_id, cutover_version)` receipt.
  Only `verified` permits Tutor traffic. `summary_ready`, `required`,
  `verification_failed`, `blocked_target_state`, and
  `blocked_checkpoint_scope` deny both runtime families; the narrow cutover
  status and confirmation endpoints remain available. A legacy route without a
  recognizable UUID user scope fails closed rather than falling through to a
  session/path-only legacy read. A `verified` receipt authorizes only the
  Tutor family; it never reopens a legacy route.
- `GET /api/harness/cutover?user_id=...` is server-authoritative. It computes a
  canonical safe summary/hash and issues a preview nonce only for legacy data
  that needs destructive confirmation. The Desktop may display that summary but
  cannot choose table names, counts, checkpoint threads, or deletion scope.
- `POST /api/harness/cutover/confirm` requires the exact version, summary
  version, nonce, hash, `confirm=true`, and a stable client idempotency key.
  A stale summary, cross-user request, changed-body replay, target-state row,
  or unresolved checkpoint scope deletes nothing.
- The transaction locks the active user row, derives only
  `aearn:learning:<learning_session_id>` checkpoint threads before deleting
  sessions, deletes exact `idempotency_records.user_id` rows rather than JSON
  or text matches, clears the five legacy learner preference fields, verifies
  the same scope, and commits `verified` atomically. Identity, display name,
  time slots, reminder preference, shared `tutor_catalog_snapshots`, and
  `checkpoint_migrations` stay outside deletion scope.
- Any pre-cutover user-scoped `tutor_*` row or
  `tutor_api_idempotency_records` row is target-state contamination. It is
  blocked, never deleted or migrated. Missing checkpointer tables are safe
  zero; an unknown schema, namespace, `NULL` thread id, or unprovable thread
  mapping blocks instead of issuing a broad delete.
- The ordinary `POST /api/users/{user_id}/reset-data` operation remains a
  legacy reset while the rollout is disabled. Once rollout is active, it first
  requires the same verified receipt; a pending summary can never use reset to
  delete legacy rows and then become an implicit empty-state cutover.
- If deletion or verification raises an error, the destructive transaction is
  rolled back and a separate safe `CUTOVER_VERIFICATION_FAILED` receipt keeps
  both runtime families blocked. Rolling back code after a confirmed cutover is
  never a claim of learner-data recovery.

Desktop bootstrap reads the local user identity, asks the cutover endpoint
before restoring `aearn.bootstrap.planId` or issuing dashboard/resume/legacy
requests, then mounts only the blocking confirmation screen or a fresh
`TutorWorkspacePage`. Verified success preserves `userId`, writes `planId=null`,
clears legacy in-memory and settings-form state, and does not clear unrelated
local UI storage.

Physical legacy retirement is a later proof gate. It requires feature-enabled
cutover and fresh Tutor-entry coverage, a verified Desktop default route with
no legacy bootstrap calls, gated legacy worker writes, an empty scoped caller
search, and Child 08 source-of-truth reconciliation before Graph/runtime code
or dependencies may be removed.

## Target Loop and Future Ownership

The finite loop leases, loads, checks fixed budgets/cancellation, builds bounded
context, asks the primary provider for one decision, and rechecks revision and
policy before every unsafe boundary. Default capability/effect ports deny or
report unavailable; they execute no tools and write no product state.

Safe checkpoints and compaction candidates are emitted through injected ports
only for terminal, safe-checkpoint, or high-water reasons. Child 00 does not
create a Curator, worker, transactional outbox, background loop, or direct
mutation of memory, plans, reviews, FSRS, attempts, messages, or activity.

| Future child | Ownership after Child 00 |
| --- | --- |
| Child 01 | Skill catalog, capability policy, registered capability implementations. |
| Child 02 | Additive target SQL repositories, exact catalog replay evidence, durable internal events/checkpoints, lifecycle transaction, redacted trace/export, curation envelope, and fake-only evals. |
| Child 04 | Queue leasing/retry/circuit-breaker ownership for persisted outbox work; Child 02 does not run jobs. |
| Child 05 | Delivered target learner-state effects, immutable plan revisions/rollback, memory/activity/inbox projections, and primary-only Curator validation under feature-off gates. |
| Child 06 | Tutor API/SSE `Last-Event-ID` adaptation, delivery acknowledgement, feature exposure, and desktop deduplication. |
| Child 07/08 | Cutover, legacy retirement, and source-of-truth reconciliation. |

This document does not authorize product traffic to enter the Harness.
