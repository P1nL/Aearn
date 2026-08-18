# Codex Runtime Sidecar

## Scenario: Aearn-owned Codex App Server runtime boundary

### 1. Scope / Trigger

Apply this contract when changing the Codex App Server connection, runtime adapter, supervisor, worker ownership, lifecycle configuration, dynamic tool callbacks, or local `tutor-codex` worker startup.

The runtime process and plan-drafting admission are enabled by default, but remain separate controls. Runtime availability alone never routes a Tutor run to Codex; the server-side policy must verify exact fresh readiness and freeze `runtime_kind`.

### 2. Signatures

Aearn code above the adapter depends only on these contracts:

~~~python
class AgentRuntimePort(Protocol):
    async def start(self) -> RuntimeHealthSnapshot: ...
    async def health(self) -> RuntimeHealthSnapshot: ...
    async def start_thread(self, request: RuntimeThreadRequest) -> RuntimeThreadHandle: ...
    async def resume_thread(self, thread_id: str) -> RuntimeThreadHandle: ...
    async def run_turn(self, request: RuntimeTurnRequest) -> RuntimeTurnResult: ...
    async def steer(self, thread: RuntimeThreadHandle, turn_id: str, input: tuple[RuntimeInput, ...]) -> None: ...
    async def interrupt(self, thread: RuntimeThreadHandle, turn_id: str) -> None: ...
    async def shutdown(self) -> None: ...
~~~

Dedicated worker command:

~~~text
python -m celery -A aearn_worker.worker_app:celery_app worker --pool=solo --concurrency=1 -Q tutor-codex -n tutor-codex@%h
~~~

Lifecycle tasks are `tutor.codex.runtime_health` and `tutor.codex.runtime_shutdown`. Controlled plan-drafting cutover additionally owns `tutor.codex.dispatch` and `tutor.codex.reconcile`; both stay on the dedicated `tutor-codex` queue.

### 3. Contracts

Environment keys:

~~~text
CODEX_RUNTIME_ENABLED=true
CODEX_RUNTIME_BINARY_PATH=
CODEX_RUNTIME_HOME=
CODEX_RUNTIME_ALLOWED_VERSIONS=0.142.0-cometix
CODEX_RUNTIME_STARTUP_TIMEOUT_SECONDS=15
CODEX_RUNTIME_REQUEST_TIMEOUT_SECONDS=15
CODEX_RUNTIME_TURN_TIMEOUT_SECONDS=300
CODEX_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS=5
CODEX_RUNTIME_NOTIFICATION_QUEUE_SIZE=256
TUTOR_CODEX_PLAN_DRAFTING_ENABLED=true
TUTOR_CODEX_RUNTIME_HEALTH_MAX_AGE_SECONDS=90
~~~

Required behavior:

- Use exact model `deepseek-v4-flash`, provider `aearn_deepseek`, and `wire_api = "responses"`.
- Use an isolated Aearn Codex Home; never read or write the user's global `~/.codex` state.
- Keep Codex JSON-RPC methods and wire item/status shapes inside the adapter.
- Preserve a monotonic connection generation. Old thread handles cannot write after restart.
- Hold both a process-local owner registry and an OS-level file lock for one Runtime Home.
- Pre-register the tool registry by thread before sending `turn/start`; bind it to the turn after receiving the response.
- Ignore reasoning items. Do not put tool arguments into normal Runtime events.
- Bound notification and Runtime event queues. Queue exhaustion fails closed.
- Logs and health payloads may include method, version, generation, safe code, hashes, and duration only; exclude prompts, model bodies, reasoning, tool arguments, credentials, and full temporary paths.
- `pnpm --dir .\aearn dev` starts the dedicated worker by default. `pnpm --dir .\aearn dev:no-codex` is the explicit local opt-out.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Runtime explicitly disabled | `unavailable / runtime_disabled`; no child process |
| Binary missing or version not allowlisted | `codex_missing` or `unsupported_codex_version` |
| Provider credential missing | `provider_credential_missing` |
| Initialize/account preflight fails | `runtime_preflight_failed` |
| Returned Codex Home differs from isolated Home | `isolated_home_mismatch` |
| Second owner targets the same Runtime Home | `ownership_conflict` |
| Old handle uses a replaced generation | `RuntimeGenerationError("stale_runtime_generation")` |
| Second concurrent writer starts a turn | `RuntimeBusyError("runtime_writer_busy")` |
| Tool callback arrives immediately after turn response | thread-prepared registry handles it |
| Unknown server request or invalid JSON | current generation fails closed |
| Child exits with pending work | pending operations receive a connection error |
| Runtime event queue is full | `runtime_event_backpressure_exhausted` |
| Worker shuts down | interrupt, close stdio, terminate if needed, release ownership |

### 5. Good / Base / Bad Cases

- Good: one worker preflights the exact version and isolated Home, then one adapter owns the active turn and receives an immediate typed tool callback through the thread-prepared registry.
- Base: Runtime infrastructure and the dedicated worker are enabled, but no Tutor Codex dispatch task exists; Tutor runs continue through Harness.
- Bad: two worker processes write the same Runtime Home without a file lock.
- Bad: code waits for `turn/start` to return before registering any tool registry, causing intermittent callback failure.
- Bad: reasoning or tool arguments enter Runtime events, logs, health responses, snapshots, or public DTOs.

### 6. Tests Required

- Validate Aearn-owned input, tool, thread, turn, event, terminal, and health DTOs.
- Cover disabled, missing credential, unsupported version, initialize/account failure, and isolated-Home mismatch.
- Cover start, resume, steer, interrupt, shutdown, generation restart, and stale handles.
- Repeat the immediate callback regression enough to expose scheduler races.
- Assert single active writer and second process/file-lock rejection.
- Assert child crash fails pending work and leaves no reader/process.
- Assert reasoning omission and stderr secret/path redaction.
- Assert event backpressure returns a stable safe code instead of hanging.
- Assert Celery lifecycle tasks use `tutor-codex` and business dispatch is absent.
- Assert PowerShell default startup and `dev:no-codex` opt-out.
- Run Harness, health, environment doctor, and Desktop regressions.
- Real App Server startup/shutdown smoke may run initialize/account preflight without starting a model turn.

### 7. Wrong vs Correct

#### Wrong

~~~python
turn = await connection.request("turn/start", params)
turn_id = turn["turn"]["id"]
tool_dispatcher.register(turn_id, registry)
~~~

The reader can receive `item/tool/call` after decoding the response but before the waiting coroutine resumes.

#### Correct

~~~python
tool_dispatcher.prepare(thread_id, registry)
try:
    turn = await connection.request("turn/start", params)
    turn_id = turn["turn"]["id"]
    tool_dispatcher.register(turn_id, registry)
    return await consume_turn(turn_id)
finally:
    tool_dispatcher.unregister(thread_id, turn_id)
~~~

Thread-level preparation closes the response/callback scheduling race; final cleanup prevents stale callbacks from crossing turn or generation boundaries.


## Scenario: Server-authoritative LearningPlan dynamic tools

### 1. Scope / Trigger

Apply this contract when adding or changing Codex dynamic tools for `plan_drafting`, planning-fact projection, LearningPlan draft validation, tool repair/rebuild budgets, or tool-call fencing. This facade is test-only until a later cutover task admits Tutor runs to the Codex runtime.

### 2. Signatures

Registered tools:

~~~text
aearn_planning_context_read({schema_version?})
aearn_learning_plan_draft({schema_version?, modules[2..8]})
~~~

Each module has `stable_key`, `title`, bounded optional `description`, `is_core`, `is_skippable`, and `nodes[1..8]`. Each node has `stable_key`, `title`, bounded optional `description`, `is_core`, `prerequisites[]`, and `required_capabilities[]`.

The draft schema must not contain `profile_json`, `module_1..8`, user/session/run/database IDs, source selection, runtime selection, or confirmation fields.

### 3. Contracts

- Build `CompactPlanProfile` only from current confirmed `PlanningFact` leaves. Map `pace_constraints` to `pace_summary`; derive the draft title on the server.
- Reuse the same LearningPlan artifact builder, language/source policy, graph validation, quality checks, and append-only repository as the Harness capability.
- Freeze run ID, conversation/user scope, input revision, Tutor lease owner/generation, Runtime connection generation, and planning-facts fingerprint/revision when the registry is created.
- Refresh the fence before every tool call and again immediately before `append_draft`.
- Tool-visible status is exactly `completed | repairable_invalid | awaiting_user | conflict | policy_blocked | unavailable | fatal`.
- `repairable_invalid`, `awaiting_user`, and the first bounded `conflict` are normal tool outputs. Policy, unavailable, fatal, deadline, and exhausted repair/conflict budgets fail the tool call.
- Default registry budgets are 6 tool calls, 2 repairs, 1 conflict rebuild, 32,000 input bytes, 30 seconds wall time, and 8,000 output bytes.
- Safe issues contain allowlisted `path`, `code`, and generic `hint` only. Never echo the invalid value, Pydantic input, internal exception, profile object, prompt, reasoning, credential, or full path.
- Durable duplicate replay is owned by the existing `(source_run_id, source_input_revision)` draft identity. When rebuilding a replay candidate, reuse the stored `change_reason`; deriving a replacement reason from the now-updated session would change the content hash and incorrectly convert an identical replay into a conflict.
- Success returns only draft ID, version, content hash, bounded counts, and a deterministic safe receipt hash. Confirmation and LearningTrack creation remain HTTP/domain authority outside the tool.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Unknown field, malformed type, module/node bound, duplicate stable key, missing/self/cyclic prerequisite | `repairable_invalid` with safe issue path/code |
| Confirmed planning facts are incomplete | `awaiting_user / planning_facts_missing` |
| Input revision, lease, Runtime generation, or facts revision/fingerprint changed | `conflict` |
| More than one conflict rebuild | `fatal / tool_conflict_budget_exhausted` |
| Repair count exceeded | `fatal / tool_repair_budget_exhausted` |
| Tool call/wall/output budget exceeded | stable `fatal` budget code |
| Language is not selectable or policy callback denies | `policy_blocked` |
| Active planning session or approved source set is unavailable | `unavailable` |
| Corrupt server-owned facts or unexpected service failure | `fatal` without raw exception text |
| Same valid draft is replayed after commit | original draft/receipt, `replayed=true`, no second row |
| Same source identity carries a different candidate | `conflict`, no second row |

### 5. Good / Base / Bad Cases

- Good: Codex reads bounded confirmed facts, submits one invalid prerequisite graph, receives a safe repair issue, submits a corrected typed graph in the same turn, and receives one durable draft receipt.
- Base: facts are incomplete; the context tool returns `awaiting_user` and missing stable fact keys so Codex can create a typed planning request later.
- Good replay: the App Server disconnects after commit and repeats the same tool call; the repository returns the original draft and safe receipt.
- Bad: accepting a model-authored user ID, profile, source list, facts revision, or confirm action.
- Bad: mapping a stale lease or policy denial to `repairable_invalid`, allowing the model to bypass server authority.
- Bad: rebuilding replay content with a new `change_reason`, producing a false content-hash conflict.

### 6. Tests Required

- Assert generated JSON Schema contains typed `modules[]`/`stable_key` and excludes every authority/profile/confirmation field.
- Cover unknown fields, item bounds, duplicate keys, unknown/self/cyclic prerequisites, payload/output/call/repair/conflict/wall budgets, and raw invalid-value redaction.
- Fake App Server loop: `repairable_invalid -> completed` in one turn; separately cover awaiting-user, conflict, policy, unavailable, fatal, timeout, and duplicate replay terminal mapping.
- PostgreSQL integration: construct profile from confirmed facts, append exactly one draft, replay the same safe result, detect facts and Runtime generation staleness, and preserve policy denial.
- Keep the legacy Harness capability decode/persistence tests passing through the shared artifact builder.
- Run the full API suite, Ruff, Mypy, lock check, compileall, and database bootstrap twice.

### 7. Wrong vs Correct

#### Wrong

~~~python
payload = LearningPlanDraftCapabilityInput(
    profile_json=model_args["profile_json"],
    module_1=model_args["module_1"],
    module_2=model_args["module_2"],
)
handler.generate(run=run, capability_input=payload)
~~~

This lets the model repeat server facts and preserves the double-encoded JSON boundary.

#### Correct

~~~python
registry = LearningPlanRuntimeToolRegistry.from_postgres(
    conn,
    run=leased_run,
    runtime_generation=connection_generation,
    runtime_generation_reader=current_connection_generation,
)
thread = await runtime.start_thread(
    RuntimeThreadRequest(cwd=workspace, tools=registry.definitions)
)
~~~

The registry exposes typed module input only; the service refreshes authority, builds the profile from confirmed facts, and reuses the existing domain/repository path.

## Scenario: Durable Tutor projection for Codex Runtime events

### 1. Scope / Trigger

Apply this contract when changing `tutor_runs.runtime_kind`, Runtime binding/receipt tables, normalized Runtime event fields, final-message persistence, or the mapping from Codex lifecycle events into Tutor turn/process/message/error items.

Runtime projection is persistence and public-contract work, not business admission. A run reaches this path only after a caller has already created it with `runtime_kind = "codex_sidecar_v1"` and acquired the authoritative Tutor lease.

### 2. Signatures

~~~python
@dataclass(frozen=True, slots=True)
class TutorRuntimeProjectionFence:
    input_revision: int
    lease_owner_id: str
    lease_generation: int
    connection_generation: int

class PostgresTutorRuntimeProjectionRepository:
    def bind_run(
        self, *, user_id: str, run_id: str,
        fence: TutorRuntimeProjectionFence,
        runtime_version: str, protocol_version: str,
        external_thread_id: str, occurred_at: datetime,
    ) -> TutorRuntimeBinding: ...

    def project(
        self, *, binding_id: str,
        fence: TutorRuntimeProjectionFence,
        event: TutorRuntimeProjectionEvent,
    ) -> TutorRuntimeProjectionReceipt: ...
~~~

Database signatures:

~~~text
tutor_runs.runtime_kind = harness_v1 | codex_sidecar_v1, default harness_v1, immutable
tutor_run_runtime_bindings(run/user/conversation scope, runtime/protocol version, external thread/turn, connection generation, state)
tutor_runtime_item_receipts(binding scope, semantic event key, unique sequence, allowlisted hashes/status, projection status)
tutor_runtime_public_errors(binding scope, Aearn-safe public code, recoverable, created_at)
~~~

### 3. Contracts

- `runtime_kind` is chosen when the run is inserted, copied to retries, and cannot be updated in place.
- Binding requires an interactive `thread_turn_v2` run with an active matching Tutor lease, current input revision, and the exact Runtime connection generation.
- External thread/turn/item IDs stay in private binding state or one-way hashes. They never enter public URLs, Tutor public DTOs, conversation events, SSE payloads, or Desktop types.
- Runtime receipts contain only allowlisted kind/status/tool name, input/result/content hashes, safe code, sequence, timestamps, and an optional Aearn public item reference. They never contain raw prompt, reasoning, commentary, tool arguments/results, command/path, credentials, or provider bodies.
- Only `agentMessage` items with `phase = "final_answer"` become `MESSAGE_COMPLETED`. Commentary and reasoning stay non-public.
- A final message is inserted only after content-hash verification, teaching-output safety, run ownership, input revision, lease owner/generation, Runtime generation, and non-terminal checks all pass.
- Exact semantic replay returns the original receipt even if the transport repeats the event. A reused sequence with different safe facts is an idempotency conflict. A late revision/generation/turn callback writes one `ignored_stale` receipt and performs no public mutation.
- A safe message and a domain tool commit are independent durable facts. Later Runtime failure may mark the process failed but must not delete an already accepted safe message or an existing domain receipt. Unsafe output must not roll back an earlier domain commit.
- Public lifecycle mapping remains Aearn-owned: turn started -> running/process; tool activity -> bounded process steps; completed -> completed; interrupted -> cancelled/interrupted; unavailable -> model_unavailable/unavailable plus `TUTOR_RUNTIME_UNAVAILABLE`; failed or blocked final -> failed plus an Aearn-safe Runtime error code.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Historical or ordinary run omits `runtime_kind` | Persist `harness_v1` |
| Caller tries to update `runtime_kind` | PostgreSQL check violation from immutable trigger |
| Run is not Codex, interactive, or `thread_turn_v2` | Reject binding |
| Lease owner/generation, input revision, expiry, or Runtime generation differs | Reject binding or receipt `ignored_stale`; no public write |
| Event thread/turn differs from binding | Receipt `ignored_stale`; no public write |
| Duplicate semantic event | Return existing receipt with `replayed=true` |
| Same binding sequence carries different safe facts | `TutorIdempotencyConflict` |
| Tool name is outside `[A-Za-z0-9_-]{1,64}` | Omit at adapter boundary or reject normalized projection DTO |
| Commentary/reasoning/command/path item | No final-message event and no public payload |
| Final text is missing, hash-mismatched, oversized, or teaching-unsafe | `blocked_unsafe`; completed terminal is converted to failed |
| Runtime completed without an accepted final message | Failed with `TUTOR_RUNTIME_OUTPUT_MISSING` |
| Runtime interrupted | Tutor outcome `cancelled`, process `interrupted`, no invented message |
| Runtime unavailable | Tutor outcome `model_unavailable`, process `unavailable`, public `TUTOR_RUNTIME_UNAVAILABLE` |
| Runtime failed | Tutor outcome/process `failed`, public `TUTOR_RUNTIME_FAILED` or bounded output-blocked code |

### 5. Good / Base / Bad Cases

- Good: a current leased Codex run binds one private thread, records tool input/result hashes, accepts one safe `final_answer`, and publishes the existing Tutor message/process/turn events.
- Good replay: reconnect repeats the same five normalized events; message, process, error, and receipt counts do not increase.
- Base: Harness-created runs keep `runtime_kind = "harness_v1"` and never create Runtime bindings or receipts.
- Bad: persist the App Server item JSON in a generic JSONB receipt column.
- Bad: accept every completed `agentMessage` as final; commentary may then win before the real final answer.
- Bad: treat a stale callback as a failed current run instead of an ignored audited receipt.

### 6. Tests Required

- Bootstrap twice and assert the Runtime tables, indexes, constraints, immutable triggers, and `harness_v1` default.
- Assert `runtime_kind`, binding identity, terminal binding state, receipts, and public errors cannot be mutated after their allowed lifecycle point.
- PostgreSQL integration must cover completed, interrupted, failed, unavailable, unsafe/missing final, duplicate replay, conflicting sequence, and stale connection generation.
- Assert a successful projection produces only existing Tutor public turn/process/message/error records and conversation events.
- Serialize public history/events and assert external thread/turn/item IDs, reasoning, commentary, tool arguments/results, provider diagnostics, and credentials are absent.
- Adapter tests must prove tool names and argument/result hashes are present while raw arguments/results are absent, and only `phase = "final_answer"` becomes a final-message event.
- Keep the full non-real-provider API suite, Ruff, Mypy, database bootstrap, Harness routes/SSE, and Desktop build green.

### 7. Wrong vs Correct

#### Wrong

~~~python
if item["type"] == "agentMessage":
    repository.save_tutor_message(item["text"])
~~~

This trusts wire DTOs, ignores phase/safety/fences, and can expose commentary or a stale generation.

#### Correct

~~~python
runtime_event = adapter.normalize(item)  # final_answer only; IDs/arguments stay private
receipt = projector.project(
    binding_id=binding.id,
    fence=TutorRuntimeProjectionFence(
        input_revision=run.input_revision,
        lease_owner_id=lease.owner_id,
        lease_generation=lease.generation,
        connection_generation=thread.generation,
    ),
    event=runtime_event,
)
~~~

The adapter removes wire-private data; the projector rechecks database authority and writes only safe Aearn-owned public state plus an append-only receipt.


## Scenario: Controlled plan-drafting Runtime cutover

### 1. Scope / Trigger

Apply this contract when changing Codex plan-drafting admission, worker readiness persistence, Runtime routing, Queue/Steer/Interrupt control, or same-runtime Retry behavior.

### 2. Signatures

~~~text
TUTOR_CODEX_PLAN_DRAFTING_ENABLED=true
TUTOR_CODEX_RUNTIME_HEALTH_MAX_AGE_SECONDS=90

tutor_codex_runtime_health(worker_id, status, generation, runtime_version,
  model, model_provider, protocol, safe_error_code, observed_at)

TutorRuntimeSelectionPolicy.select(scope_kind, inherited_runtime_kind,
  conversation_runtime_kind) -> harness_v1 | codex_sidecar_v1
~~~

### 3. Contracts

- Only a brand-new `plan_drafting` conversation without a frozen Runtime may enter `codex_sidecar_v1`.
- Exact admission requires feature enabled, `CODEX_RUNTIME_ENABLED=true`, a fresh `ready` row, generation >= 1, an allowlisted Runtime version, model `deepseek-v4-flash`, provider `aearn_deepseek`, and protocol `responses`.
- Feature disabled routes new plan-drafting work to Harness. Feature enabled with missing, stale, unhealthy, or mismatched readiness fails closed with `TUTOR_RUNTIME_UNAVAILABLE`; general/track/proactive scopes remain Harness and unaffected.
- The first interactive Runtime kind in a conversation is inherited by later fresh turns. Retry always copies the failed root Runtime kind. Clients, models, queued metadata, and public DTOs cannot select or mutate it.
- Harness and Codex workers claim the same durable job table with an exact Runtime filter. `TutorRuntimeDispatchRouter` reads only the immutable run snapshot; it never re-evaluates feature or health.
- `CodexTutorRunDispatcher` never composes `TutorRunLoop`. It acquires the Tutor lease, registers only the typed LearningPlan tools, binds the private Runtime thread, projects normalized events, and returns the existing Aearn run result.
- During an active Codex turn, a higher durable input revision becomes `turn/steer`; cancellation, supersede, lease loss, or control failure becomes `turn/interrupt`. Control failure terminates unavailable rather than leaving an orphan task.
- A recovered dispatch with an existing private binding does not start another external turn. It terminalizes the same run as unavailable so a learner Retry can create a fresh same-Runtime run without duplicating model or tool side effects.
- Codex may append a draft through the typed tool but cannot confirm it. LearningPlan confirm and LearningTrack creation remain existing HTTP/domain authority.
- Readiness, logs, receipts, errors, history, SSE, and Desktop payloads remain Aearn-owned and redacted; Runtime thread/turn IDs and tool arguments never become public.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Feature off | New plan-drafting run uses `harness_v1` |
| General, learning-track, proactive, or historical conversation | Preserve `harness_v1` or the conversation's frozen Runtime |
| Missing/stale/unhealthy/mismatched readiness | `503 TUTOR_RUNTIME_UNAVAILABLE`; no conversation/run is created |
| Harness worker sees Codex job or Codex worker sees Harness job | No claim/no action |
| New input revision while Codex turn is active | One ordered `turn/steer` with the accepted input text |
| Cancel, supersede, or lease loss | `turn/interrupt`; late Runtime projection is stale/no public overwrite |
| Retry of failed Codex run | Fresh run with `codex_sidecar_v1`; no cross-Runtime fallback |
| Existing binding recovered after dispatch failure | Same run becomes unavailable; no second external turn |

### 5. Good / Base / Bad Cases

- Good: a fresh plan-drafting conversation sees one current exact readiness row, freezes Codex, runs through the dedicated worker, steers one later accepted revision, projects one final answer, and leaves confirmation to Aearn.
- Base: admission is disabled; the same public request creates a normal Harness run without starting or depending on the Codex worker.
- Good recovery: a failed Codex run creates a fresh Retry with `codex_sidecar_v1`; committed draft/message receipts remain and no Harness fallback occurs.
- Bad: route from current health instead of persisted `runtime_kind`, let the client set Runtime, let both workers claim the same job, or start a second external turn for a run that already has a binding.

### 6. Tests Required

- Default-enabled configuration plus explicit feature-off behavior.
- Exact readiness matrix for version, model, provider, protocol, generation, freshness, and status.
- Public acceptance proving only a new plan-drafting run freezes Codex and no Runtime control field enters the DTO.
- Runtime-filtered durable claims, frozen-kind router, Codex dispatcher projection without Harness composition, revision-to-steer, cancel-to-interrupt, and same-Runtime retry.
- Full non-real-provider API suite, Ruff, Mypy, database bootstrap/cutover inventory, Desktop check, Trellis validation, and `git diff --check`.

### 7. Wrong vs Correct

#### Wrong

~~~python
runtime_kind = "codex_sidecar_v1" if health.ready else "harness_v1"
dispatcher = codex if health.ready else harness
~~~

This silently crosses Runtime after admission and lets a transient health change alter an existing run.

#### Correct

~~~python
selection = runtime_policy.select(scope_kind=scope.scope_kind)
run = repository.create_run(runtime_kind=selection.runtime_kind, ...)
result = TutorRuntimeDispatchRouter(harness=harness, codex=codex).dispatch(
    user_id=run.user_id,
    run_id=run.run_id,
)
~~~

Selection happens once at the server-owned creation boundary; dispatch reads only the immutable persisted Runtime.
