# Research: trace redaction replay eval baseline

- Query: Investigate the current Harness run/context/provider/capability/effect contracts, redaction helpers, SSE/event conventions, worker/outbox evidence, evaluation fixtures/runners, and tests needed to plan Child 02 (`tutor-state-traces-and-evals`). Identify exact anchors, reusable seams, gaps, leakage boundaries, and validation scenarios for durable ordered replay, diagnostic trace/export redaction, curation outbox/proposals, and deterministic Harness evals.
- Scope: internal
- Date: 2026-07-27

## Findings

### Scope boundary and source authority

**Current verified facts**

- This child is planning-only and currently has no `design.md` or `implement.md`. Its PRD requires additive persistence, ordered replayable events, redacted traces, expected-revision CAS, and deterministic fixtures; it explicitly excludes Curator model behavior, learner UI, container isolation, proactive scheduling, and legacy-data deletion. `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:1-50`
- The transition contract labels the existing API/SSE/Graph/database behavior as the legacy baseline and the Harness run/context/provider contracts as the feature-disabled target seam. It explicitly assigns durable events/checkpoints/transactional outbox to Child 02, while product exposure remains a later child. `docs/architecture/tutor-harness-transition.md:1-18`, `docs/architecture/tutor-harness-transition.md:121-143`
- This report does **not** propose a public route, SSE endpoint shape, client/UI integration, or Desktop change. It only records persistence, trace, replay, outbox, and evaluation constraints for the Child 02 planning artifacts.

**Proposed Child 02 work, not present in current code**

- Add the durable, additive persistence/repository layer that the current in-memory ports intentionally omit: run/input/checkpoint/event/catalog-selection/capability/effect evidence; transactional curation outbox; redacted trace/export projections; and deterministic Harness evaluation fixtures/running.
- Keep the feature flag off and preserve legacy traffic. Child 02 should not introduce a Curator model worker, semantic learner-memory commit path, public traffic adapter, or legacy schema deletion. `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:20-32`, `docs/architecture/tutor-harness-transition.md:129-143`

### Files found

| File | Current role / evidence value |
| --- | --- |
| `docs/architecture/tutor-harness-transition.md` | Child 00/01 target contract and explicit future-child ownership boundaries. |
| `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md` | Child 02 stated goal, acceptance criteria, dependencies, and exclusions. |
| `.trellis/tasks/07-22-agent-harness-rearchitecture/design.md` | Parent target data invariants, trace/memory separation, and eval coverage matrix. |
| `aearn/services/api/app/agents/harness/contracts.py` | Immutable run/context/checkpoint/decision/effect/compaction value contracts. |
| `aearn/services/api/app/agents/harness/context_builder.py` | Deterministic bounded context selection, high-water request creation, and Harness-specific redaction. |
| `aearn/services/api/app/agents/runtime/redaction.py` | Shared recursive redaction helper. |
| `aearn/services/api/app/agents/runtime/agent_runtime_context.py` | Message/summary sanitization and metadata-only safe-context helper behavior. |
| `aearn/services/api/app/agents/runtime/guardrails.py` | Public-output rejection for hidden tests, provider data, prompts, keys, references, and direct answers. |
| `aearn/services/api/app/services/tutor/run_loop.py` | Finite loop, lease/revision checks, typed compaction publication, and feature-disabled service seam. |
| `aearn/services/api/app/services/tutor/ports.py` | Protocols plus non-durable deterministic fakes for store/provider/capability/effect/compaction. |
| `aearn/services/api/app/services/tutor/provider_gateway.py` | Primary-only strict structured-decision provider boundary. |
| `aearn/services/api/app/services/tutor/capability_policy.py` | Revision-bound, default-deny policy context. |
| `aearn/services/api/app/services/tutor/decision_gate.py` | Exact catalog selection and capability/effect authorization gate. |
| `aearn/services/api/app/services/tutor/capability_gateway.py` | Registry-only grounding dispatch and bounded safe result shaping. |
| `aearn/services/api/app/services/tutor/skill_selection.py` | Explicitly non-durable selected Skill/version/hash store. |
| `aearn/services/api/app/services/streaming/sse.py` | Current request-scoped SSE framing and local event IDs. |
| `aearn/services/api/app/routes/learning_sessions.py` | Legacy streaming order, aggregate response replay, and disconnect handling. |
| `aearn/services/api/app/db/schema.sql` | Current bootstrap schema: legacy message tables and generic idempotency record; no Tutor/outbox schema. |
| `aearn/services/worker/aearn_worker/worker_app.py` | Current Celery task registration; no Curator/outbox worker. |
| `aearn/services/api/app/agents/harness/skill_catalog.py` | Skill eval JSON is loaded/validated/hashed but not executed. |
| `aearn/services/api/app/services/exercises/evaluation.py` and `app/services/runners/runtime_runner.py` | Existing deterministic domain evaluation and runner evidence, distinct from Harness evals. |
| `aearn/services/api/tests/test_tutor_*.py` | Existing focused Harness fakes and unit tests that Child 02 can extend. |

### Current Harness contracts and reusable seams

#### Run, input revision, checkpoint, and compaction

- The current run state is an immutable value contract: queued/leased/running/waiting/terminal statuses, bounded policy counters, a lease, and a monotonic `input_revision`. `TutorInputEvent` accepts learner-only messages and requires a positive revision; `TutorRunSnapshot` has counters but no durable fields or repository implementation. `aearn/services/api/app/agents/harness/contracts.py:22-43`, `aearn/services/api/app/agents/harness/contracts.py:107-160`, `aearn/services/api/app/agents/harness/contracts.py:483-538`
- Context section order is fixed: system, active plan, review, recent messages, working summary, learner memory, activity, capability schemas. This is an existing deterministic ordering contract and should remain the source for trace/checkpoint metadata and eval fixture assertions. `aearn/services/api/app/agents/harness/contracts.py:46-66`, `aearn/services/api/app/agents/harness/contracts.py:173-213`
- Checkpoints already carry only token budget, consumed token count, source IDs, and source hashes. The compaction request has an idempotency key, run/conversation/revision, trigger, source IDs/hashes, and budget data—not composed prompt text. `aearn/services/api/app/agents/harness/contracts.py:238-325`, `aearn/services/api/app/agents/harness/contracts.py:541-574`
- `TutorRunLoop` acquires a lease before terminal persistence, reloads `current_input_revision` before model calls and unsafe boundaries, creates a high-water compaction request, and produces typed safe checkpoints at safe-progress/terminal transitions. `aearn/services/api/app/services/tutor/run_loop.py:70-245`, `aearn/services/api/app/services/tutor/run_loop.py:272-480`
- The source deliberately states it runs “without routes, Graphs, persistence, or workers.” The store/publisher are injected protocols. `aearn/services/api/app/services/tutor/run_loop.py:44-68`, `aearn/services/api/app/services/tutor/ports.py:32-103`
- The only available store/publisher implementations are non-durable test fakes: `InMemoryTutorRunStore` stores snapshots/checkpoints/results in dictionaries/lists; `InMemoryTutorCompactionPublisher` deduplicates only inside process memory and never calls a worker or Curator. `aearn/services/api/app/services/tutor/ports.py:122-221`, `aearn/services/api/app/services/tutor/ports.py:331-347`

**Child 02 implication:** preserve the value contracts and convert the store/publisher invariants into one transactional persistence boundary. Do not treat the existing in-memory lists as an event log or a restart/replay implementation.

#### Provider, catalog, capability, and effect boundaries

- `PrimaryTutorProviderGateway` uses the configured `OpenAICompatibleClient` and catches configuration, transport, schema, and guardrail failures as safe `MODEL_UNAVAILABLE`; it does not fall back to another provider/model. `aearn/services/api/app/services/tutor/provider_gateway.py:145-190`, `aearn/services/api/app/agents/harness/contracts.py:459-480`
- The strict provider envelope forbids extra keys and rejects nested reasoning/diagnostic/reference/prompt/provider/key/secret/traceback fields before building capability/effect values. `aearn/services/api/app/services/tutor/provider_gateway.py:49-88`, `aearn/services/api/app/services/tutor/provider_gateway.py:91-135`, `aearn/services/api/app/services/tutor/provider_gateway.py:193-271`
- Capability policy is bound to run/user/revision/catalog digest and is default-deny. The policy resolver cannot infer permission from model output. `aearn/services/api/app/services/tutor/capability_policy.py:16-103`, `aearn/services/api/app/services/tutor/capability_policy.py:106-146`
- Exact semantic-version catalog selection precedes capability/effect dispatch. Selection plus an action in the same decision is denied; capability argument keys must be descriptor declared; effect types must be catalog/Skill/policy authorized. `aearn/services/api/app/services/tutor/decision_gate.py:29-72`, `aearn/services/api/app/services/tutor/decision_gate.py:74-159`
- The current selected Skill evidence store is intentionally in memory and keyed by `(run_id, input_revision)`, with manifest/instruction hashes. Child 02 is explicitly the durable replay owner for these facts. `aearn/services/api/app/services/tutor/skill_selection.py:1-53`, `docs/architecture/tutor-harness-transition.md:82-92`
- The published initial Skill only requires `grounding.retrieve` and authorizes no effect types. The production-safe default effect committer denies all commits. `aearn/services/api/app/agents/skills/tutor.registry-grounding/1.0.0/manifest.json:16-25`, `aearn/services/api/app/services/tutor/ports.py:313-328`
- Effects are typed proposals with `expected_input_revision`; the loop checks the revision before calling the committer and records `stale_rejected` in memory. This is a logical CAS seam, not yet a database compare-and-set transaction. `aearn/services/api/app/agents/harness/contracts.py:390-414`, `aearn/services/api/app/services/tutor/run_loop.py:319-364`

**Child 02 implication:** durable effect state must retain selected exact catalog/version/hash evidence, policy decision/fingerprint, expected revision, idempotency identity, and result reference. A database commit must make the expected revision condition authoritative; rechecking only in Python is insufficient under competing workers.

### Redaction and diagnostic/export boundary

#### Current protections to reuse

- Shared recursive redaction replaces exact sensitive field names: `solution_reference`, hidden-test fields, raw/system prompt, provider payload, API key/secret/auth token, stack trace, and traceback. It also redacts content markers such as hidden tests, provider errors, raw prompts, and secret keys. `aearn/services/api/app/agents/runtime/redaction.py:8-76`
- Harness context redaction strengthens that helper by normalizing field names and additionally rejecting `reference_answer`, provider error, raw/full/conversation history variants, and any key beginning with `hiddentest`. It bounds mappings/lists and hashes selected sanitized source content. `aearn/services/api/app/agents/harness/context_builder.py:38-57`, `aearn/services/api/app/agents/harness/context_builder.py:193-263`
- Message and summary sanitizers convert blocked content to learner-safe generic text; output guardrails reject hidden case identifiers, reference answers, provider/key data, prompts/internal context markers, and direct-answer output. `aearn/services/api/app/agents/runtime/agent_runtime_context.py:94-194`, `aearn/services/api/app/agents/runtime/guardrails.py:22-132`, `aearn/services/api/app/agents/runtime/guardrails.py:166-191`
- Existing context tests prove that provider payload/error, reference answers, raw history, hidden cases, and solution references do not appear in prompt context or checkpoint metadata. `aearn/services/api/tests/test_tutor_context_builder.py:68-114`

#### Current gaps that matter for durable traces

- The generic `SSEWriter` merely JSON-encodes the supplied data. It has no redaction/allowlist layer, so Child 02 must redact before persistence and before replay/export rather than relying on the framing utility. `aearn/services/api/app/services/streaming/sse.py:32-119`
- `TutorInputEvent.content` is a bounded/sanitized value but the current seam has no persistence separation. The parent design requires raw learner text to live only in conversation history, while checkpoints/traces retain only redacted references/hashes. `aearn/services/api/app/agents/harness/contracts.py:140-160`, `.trellis/tasks/07-22-agent-harness-rearchitecture/design.md:354-381`
- Current helper sets do not explicitly name executor host/container path fields. The Child 02 trace/export policy must add an explicit normalized field/value ban for executor paths (including path-like diagnostics), in addition to the existing prompt/provider/secret/stack rules. Child 02 already requires this protected category. `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:40-43`

#### Protected categories for the Child 02 trace/export contract

The durable trace/outbox/proposal/export projection must never contain, directly or nested:

1. raw or system/developer prompts; raw/full conversation/history; raw learner message body outside the visible conversation store;
2. provider request/response payloads, raw provider error bodies, reasoning/diagnostics, model credentials, API keys, secrets, tokens, and authorization values;
3. hidden-test IDs/source/body, solution/reference answers, test oracle values, and full submitted code where not explicitly learner-visible;
4. stack traces, traceback text, internal exception detail, host/container/executor paths, shell commands, SQL fragments, URLs with credentials, and arbitrary target identifiers;
5. raw trace body inside a curation request/proposal, or a curation proposal copied into a learner-memory/domain-effect record without its owning validation path.

This is stricter than a UI-only redaction rule: redact/omit before insert, store only safe hashes/counts/stable codes where possible, and re-run a defensive projection on export.

### Current SSE/event behavior and replay gap

**Current facts**

- Current SSE frames are single-line JSON, with a local `SSEWriter` counter that emits `evt_000001`, `evt_000002`, and so on per writer instance. `aearn/services/api/app/services/streaming/sse.py:32-39`, `aearn/services/api/tests/test_sse_utils.py:6-22`
- Legacy event vocabulary includes `agent_message`, `tool_status`, `tool_call`, `runner_result`, `evaluation_result`, `done`, and `error`. The legacy learning stream emits progressive public text, tool-call deltas, and a final `done`; run and submit streams use `tool_status -> runner_result -> done`, with submit adding `evaluation_result`. `aearn/services/api/app/routes/learning_sessions.py:746-922`, `aearn/services/api/app/routes/learning_sessions.py:944-1000`, `aearn/services/api/app/routes/learning_sessions.py:1008-1192`
- A stored legacy conversation response is replayed as a newly framed aggregate agent message/tool-call sequence; it is not a replay of previously persisted frames or event IDs. `aearn/services/api/app/routes/learning_sessions.py:787-818`
- A client disconnect causes the current generator to return at the chunk iterator boundary. There is no current `Last-Event-ID`, `event_sequence`, or replay-cursor implementation under API, tests, or desktop source (read-only search returned no matches on 2026-07-27). `aearn/services/api/app/routes/learning_sessions.py:934-941`, `aearn/services/api/app/services/streaming/sse.py:32-39`
- Graph observability has a separate redacted `tool_status` adapter, but that does not make SSE durable. `aearn/services/api/app/services/streaming/graph_event_stream.py:25-54`, `aearn/services/api/tests/test_graph_event_stream.py:11-68`

**Child 02 implication:** retain the existing event names as data values where useful, but create a durable run-local event ordering/replay source. A request-scoped counter cannot serve as a reconnect cursor.

### Schema, idempotency, worker, and outbox evidence

- The current database bootstrap is a single `schema.sql`; repository discovery found no migration directory/framework. The schema contains generic `idempotency_records` with a global key, request hash, full `response_json`, optional user, and invalidation timestamp. `aearn/services/api/app/db/schema.sql:333-345`
- Existing idempotency behavior is reusable as a semantic pattern: same key plus different body hash is a conflict; same key/hash replays a stored result. It is not a durable run-event, trace, or outbox implementation, and its full JSON response must not become a trace/export storage format. `aearn/services/api/app/services/repositories/plan_repository.py:34-58`, `aearn/services/api/app/services/repositories/plan_repository.py:167-175`
- Current legacy message tables are content-bearing rows ordered only by `created_at`, with unique client IDs. They lack Harness run/revision/event sequence/cursor data and are not a substitute for ordered replay state. `aearn/services/api/app/db/schema.sql:621-667`
- Current worker registration contains only `health.ping`, review due-count refresh, and review seed-bank generation. There is no Tutor compaction outbox lease/dispatch/Curator task. `aearn/services/worker/aearn_worker/worker_app.py:17-31`, `aearn/services/worker/aearn_worker/worker_app.py:61-146`
- A direct source search found no current application/worker `outbox`, `tutor_run_events`, `tutor_traces`, `memory_proposal`, or persisted curation contract. The only `context_summary` hit is legacy Graph runtime state, not a Harness outbox.

**Child 02 implication:** migration delivery is an unresolved planning prerequisite. The repository has an idempotent bootstrap schema but no established additive migration mechanism; choose and document one before coding rather than silently treating `schema.sql` edits as safe production migration history.

### Evaluation fixtures, runners, and current test baseline

- Existing code-completion evaluation is deterministic, server-owned domain logic based on runtime results, hard gates, score breakdown, and FSRS mapping. It is not a Harness trace/eval runner. `aearn/services/api/app/services/exercises/evaluation.py:7-69`, `aearn/services/api/app/services/exercises/evaluation.py:238-302`
- The legacy runtime runner is also mostly deterministic fallback/registry logic and redacts hidden-case output to generic messages. It should remain a domain fact source rather than be reused as a model-evaluation framework. `aearn/services/api/app/services/runners/runtime_runner.py:64-178`, `aearn/services/api/app/services/runners/runtime_runner.py:186-217`, `aearn/services/api/app/services/runners/runtime_runner.py:268-275`
- The published Skill has one JSON evaluation fixture, but the catalog compiler only checks non-empty valid JSON, stable case IDs, and content hashes. No code executes the fixture as an eval suite today. `aearn/services/api/app/agents/skills/tutor.registry-grounding/1.0.0/evals.json:1-10`, `aearn/services/api/app/agents/harness/skill_catalog.py:303-343`, `aearn/services/api/app/agents/harness/skill_catalog.py:421-429`
- The Harness already supplies deterministic fakes suitable for an eval runner: `FixedClock`, `InMemoryTutorRunStore`, `InMemoryTutorContextLoader`, `SequenceTutorProvider`, `SequenceCapabilityGateway`, `RecordingEffectCommitter`, and `InMemoryTutorCompactionPublisher`. `aearn/services/api/app/services/tutor/ports.py:109-347`
- Current focused tests cover deterministic context selection/redaction, bounded loop behavior, stale effect rejection before the committer, typed compaction requests, feature-off behavior, provider schema/guardrail failure, exact skill selection, capability policy denial, and registry grounding filtering. `aearn/services/api/tests/test_tutor_context_builder.py:49-143`, `aearn/services/api/tests/test_tutor_run_loop.py:118-346`, `aearn/services/api/tests/test_tutor_provider_gateway.py:159-244`, `aearn/services/api/tests/test_tutor_capability_gateway.py:150-315`, `aearn/services/api/tests/test_tutor_grounding_policy.py:120-317`
- Test configuration already replaces selected live model generators with fakes, but no Harness eval fixture runner or persistence/replay concurrency test exists. `aearn/services/api/tests/conftest.py:13-17`, `aearn/services/api/app/agents/harness/skill_catalog.py:421-429`

### Concrete validation scenarios required before Child 02 can pass

The following are repository-derived acceptance scenarios for a later implementation/check plan. They are not public-route or Desktop work.

#### 1. Durable ordered event replay

1. **Per-run append ordering:** two competing writers append different safe events for one run. Assert a unique, monotonic, gap-free `event_sequence` per run and deterministic read order.
2. **Idempotent append:** retry the same logical event with the same run-scoped idempotency identity. Assert it returns the original sequence/payload fingerprint and creates no duplicate event.
3. **Terminal uniqueness/order:** attempt competing terminal writes. Assert exactly one terminal transition/event becomes authoritative, no non-terminal event is committed after that terminal boundary, and losing work gets a stable stale/conflict result.
4. **Cursor replay:** persist N events, simulate delivery through K, then reload after cursor K. Assert returned events are exactly K+1..N in order; reusing the same cursor never duplicates K; a cursor past terminal returns an empty ordered suffix.
5. **Input/effect causality:** accept a new input revision between provider decision and effect commit. Assert the effect is stored as `stale_rejected`, no domain committer is invoked, and any emitted effect/event record has the current revision relationship.
6. **Transaction failure:** force failure after a domain/effect result but before event/outbox commit. Assert no partially visible event, no orphan replay row, and no later duplicate after retry.

#### 2. Redacted trace and export

1. **Nested forbidden-field corpus:** persist a diagnostic candidate containing snake/camel/compact variants of every protected key, plus value markers. Assert database projection, event projection, outbox projection, and export projection omit/replace all raw values.
2. **Checkpoint metadata-only:** seed context with raw prompt/history/provider/error/reference/hidden-case values. Assert stored checkpoint/trace has source IDs/hashes/counts/budget only and never source content.
3. **Value-based leaks:** inject a provider-like error, bearer token, hidden identifier, solution text, stack trace, credential-bearing URL, host/container path, and shell/SQL-like target in allowed-looking keys. Assert export has no raw substring and retains only stable safe codes/hashes where needed.
4. **Separation of stores:** write visible learner message content and a trace for the same run. Assert trace/outbox/proposal tables do not contain the message body; trace export cannot rehydrate it.
5. **Dual defense:** test redaction at write time and at export time independently, so a historical malformed row cannot leak through a future exporter.

#### 3. Curation outbox and proposal persistence

1. **Transactional trigger:** terminal, safe-checkpoint, and high-water trigger records are persisted with a closed source range, source hashes, policy/memory-setting version, safe trace reference, and deterministic dedupe key in the same transaction as their owning lifecycle result.
2. **Duplicate delivery:** insert/retry the same outbox request and emulate repeated worker delivery. Assert one outbox identity and at most one proposal identity; replay returns the existing record, not a second proposal.
3. **Stale policy/revision:** create a request, advance input revision or policy/memory-setting version, then attempt a proposal transition. Assert it becomes safe no-action/stale/failed according to the frozen contract and cannot overwrite newer state.
4. **No direct domain write:** attempt to use an outbox/proposal path to mutate plan, review/FSRS, attempt, visible message, activity, or learner memory. Assert the repository boundary rejects it; Child 02 only persists redacted request/proposal state.
5. **Export redaction:** outbox/proposal exports contain no raw prompt, provider payload/error, trace body, hidden tests, secret, or executor path. The Child 02 PRD makes this an explicit acceptance condition. `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:24-30`, `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:40-45`

#### 4. Deterministic Harness eval runner

1. **Fixture identity and catalog reproducibility:** evaluate a fixture against a fixed catalog digest/Skill version/hashes; changing a fixture, manifest, or selected version fails deterministically rather than silently resolving `current`.
2. **Policy denial:** fake provider proposes a non-eligible Skill/capability/effect; assert no gateway/committer invocation and stable denied diagnostic.
3. **Schema rejection:** fake provider returns unknown envelope fields or forbidden nested payload data; assert `MODEL_UNAVAILABLE` and no trace leak.
4. **Finite bounded loop:** use `FixedClock` and `SequenceTutorProvider` for zero budget, model-call budget, capability budget, deadline, cancellation, and successful bounded continuation cases.
5. **Revision conflict/CAS:** use an in-memory deterministic race fixture plus persistence-level concurrent transaction test; assert one input revision advance and no double effect commit.
6. **Model failure/no fallback:** fake the configured primary provider error; assert safe `MODEL_UNAVAILABLE`, selected provider fingerprint only, and no second provider/call.
7. **Leakage regression fixture:** run the redaction corpus through provider result, capability result, checkpoint, event, trace, outbox, proposal, and export paths. Assert no forbidden substrings in any safe projection.

## Reusable Code Patterns

- **Bounded redaction/sanitization:** extend `redact_value`, Harness normalized-field redaction, and guardrails rather than copy individual deny lists. `aearn/services/api/app/agents/runtime/redaction.py:43-76`, `aearn/services/api/app/agents/harness/context_builder.py:207-263`, `aearn/services/api/app/agents/runtime/guardrails.py:98-132`
- **Stable metadata-only checkpoint shape:** reuse `TutorCheckpointMetadata`, `TutorContextSectionMetadata`, and `build_compaction_request`; durable storage must not invent a second checkpoint redaction shape. `aearn/services/api/app/agents/harness/contracts.py:238-325`, `aearn/services/api/app/agents/harness/contracts.py:541-574`
- **Expected-revision effect protocol:** reuse `TutorEffectProposal.expected_input_revision`, `TutorEffectStatus.STALE_REJECTED`, and the loop’s unsafe-boundary order; move authority into a transactional repository CAS. `aearn/services/api/app/agents/harness/contracts.py:390-414`, `aearn/services/api/app/services/tutor/run_loop.py:319-394`
- **Primary-only model failure contract:** preserve `TutorProviderResult.model_unavailable()` and strict-envelope tests; do not add a fallback provider in Child 02 eval infrastructure. `aearn/services/api/app/agents/harness/contracts.py:459-480`, `aearn/services/api/app/services/tutor/provider_gateway.py:163-190`
- **Legacy idempotency collision semantics:** reuse same-key/same-hash replay versus same-key/different-hash conflict semantics, but build a separate run-scoped/event-safe representation rather than serializing `response_json` into traces. `aearn/services/api/app/services/repositories/plan_repository.py:34-58`, `aearn/services/api/app/services/repositories/plan_repository.py:167-175`
- **Deterministic fakes:** reuse the Tutor ports/fakes as the base fixture harness, with no live provider, network, worker, database, or wall-clock dependency in ordinary evals. `aearn/services/api/app/services/tutor/ports.py:109-347`
- **SSE payload framing only:** reuse `sse_event` for single-line encoding if a later integration child needs it; do not mistake local `evt_*` IDs for durable replay IDs. `aearn/services/api/app/services/streaming/sse.py:32-119`

## External References and Versions

- No external website/documentation was consulted; this report is based on the current checkout and task artifacts.
- Local source-of-truth references: `docs/README.md`, `docs/architecture/tutor-harness-transition.md`, `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md`, and the active Child 02 PRD.
- Installed/pinned API-service dependency evidence: FastAPI `0.128.0`, LangGraph `1.0.5`, LangGraph PostgreSQL checkpointer `3.0.2`, Celery `5.5.3`, and OpenAI Agents SDK `0.17.3`. `aearn/services/api/pyproject.toml:1-38`

## Related Specs

- `.trellis/spec/backend/database-guidelines.md` — PostgreSQL is the persisted source of truth; explicit schema/migration contracts, UUID/timestamptz, and idempotency behavior are required.
- `.trellis/spec/backend/error-handling.md` — stable error envelope and SSE error-then-terminal convention; no raw framework/provider details.
- `.trellis/spec/backend/logging-guidelines.md` — never log API keys, provider payloads, full submitted code, raw prompts/responses, or stack traces to user-visible output.
- `.trellis/spec/backend/quality-guidelines.md:1598-1699` — feature-disabled Harness seam explicitly forbids a database migration/repository/worker/outbox before the owning child and requires metadata-only checkpoints plus deterministic focused tests.

## Caveats / Not Found

- **Critical planning conflict to freeze:** the Child 02 PRD calls for persisted typed context-summary/memory-entry proposals, while the parent design says Child 05 owns guarded Curator/proposal semantics. Resolve this as: Child 02 owns redacted proposal/outbox record schemas, idempotency, retention/export, and repository invariants; it must not generate, semantically validate, apply, or direct-write a proposal. `.trellis/tasks/07-22-tutor-state-traces-and-evals/prd.md:24-27`, `.trellis/tasks/07-22-agent-harness-rearchitecture/design.md:383-407`
- **Migration mechanism is not established:** only `aearn/services/api/app/db/schema.sql` was found; no migration directory/framework was found in the API project. Child 02 planning needs an explicit additive migration delivery/rollback decision before implementation.
- **No durable replay implementation found:** no `Last-Event-ID`, `event_sequence`, or replay cursor implementation was found under current API/tests/client source on 2026-07-27. Current `SSEWriter` IDs reset per request.
- **No current Harness outbox/Curator worker found:** the only compaction publisher is in-memory and current Celery tasks are review-related.
- **No Harness evaluation runner found:** Skill `evals.json` is validated and hashed, but it is not executed by current runtime code.
- **Tests were not run:** this was a research-only pass. Avoided executing pytest because it can write test/cache artifacts outside the one permitted research-report path.
