# Child 00 Current Runtime Baseline

**Recorded:** 2026-07-26  
**Scope:** Planning evidence for `07-22-tutor-harness-contracts-and-run-loop`.
This file records current behavior and target constraints; it changes no runtime
code, database data, route behavior, or feature flags.

## Confirmed Current Behavior

| Concern | Evidence | Child 00 consequence |
| --- | --- | --- |
| Legacy product orchestration | `app/agents/graphs/router.py:21-65` routes by `learning_stage`, keywords, and specialist handoffs. | The new loop must not import or reproduce stage routing or user-visible handoffs. |
| Legacy graph feature path | `app/core/config.py:61-62` exposes `LANGGRAPH_ENABLED`; `services/conversations/learning_conversation.py:387-391` and `520-544` preserve the non-graph fallback when disabled or graph invocation fails. | Harness work must use a separate default-false feature flag and must not alter existing legacy route selection. |
| Existing provider boundary | `app/services/llm/llm_client.py:20-55` provides typed provider errors and `OpenAICompatibleClient`; its DeepSeek branch uses Chat Completions while the other branch uses Responses. | Build an Aearn-owned Tutor provider adapter on top of this tested client; do not introduce a second raw HTTP client or an automatic fallback provider. |
| Retry and public model failure | `app/services/llm/llm_client.py:336-399` retries transient failures; `app/core/errors.py:37-50` maps public failure to `MODEL_UNAVAILABLE`. | The Tutor adapter catches configuration, call, and invalid-output errors, records only redacted diagnostics, and terminates as `model_unavailable` after the selected primary provider exhausts its own retries. |
| Safe context primitives | `app/agents/runtime/agent_runtime_context.py:106-195` sanitizes messages and builds bounded safe context; existing tests cover hidden/provider/reference redaction. | `TutorContextBuilder` reuses runtime-level sanitization and deterministic limits, never restores the entire raw conversation. |
| Legacy graph redaction | `app/agents/graphs/graph_runtime_contracts.py:646-685` owns reusable value redaction today. | Extract or relocate generic redaction behind an `agents/runtime` import boundary before Harness code uses it; Harness must not depend on a legacy graph module. |
| Public output safety | `app/agents/runtime/guardrails.py:98-129` provides input/output leak checks; `agents/learning/learning_public_output.py` has a legacy stage-specific envelope. | Reuse generic guardrails, but define a Harness-specific decision schema rather than importing the legacy learning envelope or its stage semantics. |
| Current SSE compatibility | `app/services/streaming/graph_event_stream.py:25-54` emits bounded `tool_status`; `docs/architecture/api-contract.md:452-465` keeps existing SSE vocabulary during migration. | Child 00 defines internal event/checkpoint contracts only. It does not add routes or SSE frames; Child 06 owns durable event replay and desktop/API adaptation. |
| No new target persistence yet | Parent design assigns target run/event/outbox SQL to Child 02; the existing data model is legacy learning/session state. | Child 00 defines store, lease, effect, and compaction publisher protocols plus test fakes. It adds no SQL migration, repository implementation, or durable outbox. |

## Child 00 Design Decisions Derived From Evidence

1. **Feature-disabled seam.** Add `TUTOR_HARNESS_ENABLED=false` as a new Settings
   flag. No existing route reads it in this child; the flag protects later
   integration and tests prove the legacy behavior remains untouched.
2. **Service-owned orchestration.** Put immutable Harness contracts and the
   deterministic context builder under `app/agents/harness/`; put the provider
   gateway, run-loop service, and injected persistence/capability/effect ports
   under `app/services/tutor/`.
3. **No new product persistence.** The loop operates through an abstract
   `TutorRunStore`/lease port and a deterministic in-memory fake used only by
   unit tests. Child 02 later supplies SQL repositories, run events,
   checkpoints, and the transactional curation outbox.
4. **Bounded context only.** Context selection uses explicit item and token
   budgets with a deterministic, conservative estimator. It selects sanitized
   scoped facts in parent-design priority order and stores only source ids,
   hashes, and budget metadata in checkpoint records.
5. **Primary-only provider.** A `TutorProviderGateway` adapts the existing
   `OpenAICompatibleClient` and validates a strict Harness decision envelope.
   It never chooses a second provider/model; invalid output, guardrail failure,
   configuration failure, or retry exhaustion becomes a redacted
   `MODEL_UNAVAILABLE` terminal outcome.
6. **Safe checkpoint and input revision.** Every loop boundary reloads the
   run's current input revision. Effects carry an expected revision and are
   rejected as stale before commit when a newer input exists. Child 00 provides
   the contract and fake proof; Child 02 supplies durable transaction support.
7. **Compaction contract only.** Child 00 may publish one typed, idempotent
   compaction request at a terminal/safe checkpoint or context high-water mark.
   It never publishes per streamed token and never calls a Curator model.

## Explicitly Deferred to Later Children

- Skill catalog compilation and capability policy/gateway: Child 01.
- SQL tables, durable run events, checkpoints, trace persistence, and curation
  outbox: Child 02.
- Container execution: Child 03.
- Proactive scheduling and queue leases: Child 04.
- Curator behavior, learner memory, plans, activity, and user controls: Child 05.
- Tutor API, SSE replay, desktop composer merge UX, and feature exposure: Child 06.
- Clean-slate migration and legacy retirement: Child 07.

## Validation Direction

The first child-level test suite is model-key-free and uses fake provider,
clock, store, capability, effect, and compaction ports. It must cover zero/one/
multiple bounded iterations; input revision reload and stale effect rejection;
context budget and redaction; primary-only provider errors; safe compaction
triggers; lease/budget terminal outcomes; and legacy Graph regression coverage.
