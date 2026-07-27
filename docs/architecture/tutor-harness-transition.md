# Tutor Harness Transition Contract

## Status and Authority

This transition contract records the feature-disabled, in-process Tutor
Harness seam from Child 00/01 and the target-only durable foundation delivered
by Child 02. Child 02 adds no learner-facing API, SSE stream, desktop entry
point, worker, Curator, feature activation, or legacy-data migration.

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
| Child 05 | Curator generation, semantic proposal validation, and all plan/memory/activity/domain projections. |
| Child 06 | Tutor API/SSE `Last-Event-ID` adaptation, delivery acknowledgement, feature exposure, and desktop deduplication. |
| Child 07/08 | Cutover, legacy retirement, and source-of-truth reconciliation. |

This document does not authorize product traffic to enter the Harness.
