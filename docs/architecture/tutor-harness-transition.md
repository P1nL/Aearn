# Tutor Harness Transition Contract

## Status and Authority

This Child 00 contract creates only a feature-disabled, in-process Tutor
Harness seam. It adds no learner-facing API, SSE stream, desktop entry point,
database table, migration, worker, or outbox.

| Authority | Meaning |
| --- | --- |
| **Legacy baseline** | Current routes, Graph routing, `learning_stage`, Graph checkpoints, SSE vocabulary, persistence, and desktop flows remain the compatibility baseline. |
| **Target contract** | The immutable Harness contracts, bounded context builder, primary-only provider gateway, finite loop, input revision protocol, and typed compaction request introduced by Child 00. |
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
- Existing persistence remains the legacy schema/repository boundary; Child 00
  stores no Tutor run, event, checkpoint, or outbox data.

`TUTOR_HARNESS_ENABLED=false` is a separate future-integration seam. No
current product route, Graph path, SSE producer, or UI reads it in Child 00.

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
| Child 02 | Target SQL repos, durable events/checkpoints, transactional commit, compaction outbox. |
| Child 06 | Tutor API/SSE replay, feature exposure, desktop adaptation. |
| Child 07/08 | Cutover, legacy retirement, and source-of-truth reconciliation. |

This document does not authorize product traffic to enter the Harness.
