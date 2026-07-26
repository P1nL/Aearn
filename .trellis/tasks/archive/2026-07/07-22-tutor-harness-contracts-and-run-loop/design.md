# Child 00 Design: Tutor Harness Contracts and Run Loop

## Status and Scope

This is a child-level planning artifact for the approved Harness parent. Child
00 is the first implementation child, but remains `planning` until the user
reviews this design and its implementation plan. The parent task itself is not
an implementation target.

Child 00 creates a feature-disabled, testable runtime seam. It does not create
the target database model, API, SSE replay stream, desktop workflow, or any
learner-visible behavior.

## Authority and Compatibility Boundary

| Authority | Role for this child |
| --- | --- |
| Current repository code/tests/configuration | Establish actual legacy provider, context, Graph, error, and stream behavior. |
| `docs/architecture/api-contract.md` | Preserves `MODEL_UNAVAILABLE` and existing SSE vocabulary; target routes are not added here. |
| Parent target artifacts | Define the new finite loop, provider, context, effect, and compaction boundaries. |
| Child 00 target transition section | Defines the first approved target contract for run/input/context/provider/checkpoint/terminal behavior. |

The Phase 0 transition document is created before Child 00 code. It labels
legacy Graph routing/checkpoints as `legacy baseline`, the new types and loop as
`target contract`, and the untouched endpoints as `adapter window` until Child
06 exposes the Harness.

## Module Boundaries

| Path | Ownership | Responsibility |
| --- | --- | --- |
| `app/agents/runtime/redaction.py` | shared runtime | Generic bounded recursive sensitive-value redaction extracted from Graph-only ownership. |
| `app/agents/graphs/graph_runtime_contracts.py` | legacy compatibility | Imports/re-exports the shared redaction helper without changing existing Graph API. |
| `app/agents/harness/contracts.py` | Harness contract | Immutable typed values, enums, strict decision envelope, status/terminal vocabulary. |
| `app/agents/harness/context_builder.py` | Harness contract | Deterministic scoped context selection, token/item budgets, source fingerprints, compaction trigger calculation. |
| `app/services/tutor/ports.py` | service boundary | `TutorRunStore`, provider, capability, effect, compaction, clock, and token-estimator protocols plus test-safe defaults. |
| `app/services/tutor/provider_gateway.py` | service boundary | Primary-only adapter over `OpenAICompatibleClient`; strict output/guardrail/error mapping. |
| `app/services/tutor/run_loop.py` | service boundary | Lease acquisition, finite iteration, revision reload, safe checkpoints, terminal transition. |
| `app/core/config.py` | configuration | Default-false `TUTOR_HARNESS_ENABLED` property. |

Harness modules may import `app.agents.runtime` helpers and `app.services.llm`
clients. They must not import `app.agents.graphs`, Graph router functions,
LangGraph checkpoint APIs, route handlers, database connections, or worker
implementations.

## Core Contracts

### Run State

`TutorRunStatus` is limited to:

```text
queued -> leased -> running
running -> waiting_for_input | waiting_for_capability | awaiting_effect_commit
running -> completed | model_unavailable | blocked_policy | budget_exhausted | cancelled | failed
```

A run snapshot contains opaque run/conversation/user identifiers, the current
monotonic input revision, a policy snapshot, lease owner/expiry, iteration and
model-call counters, and redacted terminal/checkpoint metadata. It never stores
raw provider payloads or raw composed prompts.

### Input and Effect Revision Protocol

Each `TutorInputEvent` has a monotonic revision and stable message identity.
`TutorRunStore.current_input_revision(run_id)` is authoritative. Before each
new model call, capability dispatch, post-capability continuation, and effect
commit, `TutorRunLoop` reloads it. Any effect whose `expected_input_revision`
does not equal the current revision transitions to `stale_rejected` without
calling the effect committer.

Child 00's in-memory store proves compare/reload behavior in tests. Child 02
will make the same protocol transactional and durable.

### Policy and Lease

`TutorPolicySnapshot` fixes `max_iterations`, `max_model_calls`,
`max_capability_calls`, `max_effects`, `deadline`, and `context_token_budget`
for one run. The loop cannot mutate those values. `TutorRunStore.acquire_lease`
and heartbeat operations provide a single-worker ownership contract; fake
implementations make expiry, contention, and budget outcomes testable without a
database or worker process.

## TutorContextBuilder

`TutorContextBuilder` receives only already scoped facts through a typed input
object. It selects in this fixed order:

1. system/selected-Skill/policy descriptors;
2. active plan revision;
3. review/FSRS snapshot;
4. bounded recent sanitized messages;
5. bounded working summary;
6. selected learner-visible memory;
7. relevant activity/execution facts;
8. allowed capability schemas.

Every section has a maximum item count and consumes an explicit budget. The
default `TokenEstimator` conservatively estimates tokens from UTF-8 byte count;
providers may later supply a more exact estimator without changing selection
order. Inputs are sanitized through runtime helpers and generic redaction before
selection. The resulting checkpoint metadata contains section counts, source
ids, hashes, and consumed budget only, never raw hidden/context/prompt text.

If the builder reaches its configured high-water threshold, it returns a typed
`CompactionRequest` candidate. This is a request contract only; the publisher
is injected and Child 02 later writes it to a transactional outbox.

## Provider Gateway

`PrimaryTutorProviderGateway` is the only Child 00 model boundary. It wraps the
already configured `OpenAICompatibleClient`, so the active `Settings` provider
selects DeepSeek Chat Completions or the OpenAI-compatible Responses path.

The gateway sends a strict JSON decision request and validates a
Harness-specific Pydantic envelope. The envelope permits a learner-safe
`public_message`, selected Skill references, capability requests, effect
proposals, an optional checkpoint reason, and a terminal intent. It rejects
unknown fields, duplicate/malformed content, unsafe public output, and raw
reasoning/diagnostic fields. Child 00 executes neither real capabilities nor
effects by default.

Configuration, transport, invalid-response, envelope, or guardrail failures
are converted to the redacted terminal code `MODEL_UNAVAILABLE`. The gateway
never changes `Settings.llm_provider_type`, model, or client after failure; the
existing selected-provider retry remains the only retry path.

## Finite Run Loop

1. Acquire a lease and load the latest snapshot.
2. Stop as `blocked_policy`, `budget_exhausted`, or `cancelled` when a fixed
   precondition fails.
3. Build bounded context from the latest current input revision.
4. Ask only the primary provider for one decision and validate it.
5. Before dispatching a requested capability/effect, reload input revision and
   re-check policy. Default ports reject unregistered requests.
6. Record a redacted checkpoint through the store port; emit a compaction
   candidate only at terminal/safe/high-water reasons.
7. Repeat only within the fixed iteration/model-call/lease/deadline budget.
8. Produce a typed terminal result; no route, SSE writer, or desktop consumer
   observes it in this child.

A zero-iteration run is valid when the initial policy/lease check stops it. A
one-iteration run can wait for learner input. A multiple-iteration run is
possible only through fake/injected safe results and remains finite.

## Compatibility, Rollback, and Observability

- `TUTOR_HARNESS_ENABLED` defaults to false; no legacy code path reads it.
- No existing `LANGGRAPH_ENABLED` branch, Graph router, checkpoint usage,
  endpoint, SSE event ordering, or desktop behavior changes.
- The shared redaction extraction preserves the existing Graph import surface
  and is covered by existing Graph contract tests.
- No raw prompt, provider error, secret, submitted code, hidden test, or
  reference answer is logged or kept in Harness diagnostics.
- Rollback before later integration is deletion/revert of isolated feature-off
  modules and documentation reference; there is no migration or learner data to
  undo.

## Documentation Delta

Before code, add `docs/architecture/tutor-harness-transition.md` and link it
from `docs/README.md`. The Child 00 section records the target run/input/context
provider/checkpoint/terminal contract, explicit legacy non-changes, and future
owners for persistence (02), capabilities (01), API/SSE (06), and retirement
(07/08). Update `docs/setup/development-environment.md` with the disabled flag
and explicitly state that it does not enable a user-facing Tutor route.
