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
    async def compact_thread(self, thread: RuntimeThreadHandle) -> None: ...
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
- Normalize `item/reasoning/textDelta` and `item/reasoning/summaryTextDelta` separately; only raw reasoning text delta enters the owner-scoped Tutor Runtime text projection. Reasoning summary and commentary remain nonpublic.
- Codex `item/completed` for a reasoning item may omit `text`. Preserve `visible_text=None/content_sha256=None` through the adapter so the projector finalizes the already accumulated delta text instead of overwriting it with `""`.
- `item/tool/requestUserInput` is a known but prohibited client-side elicitation request. Return a schema-valid empty answer map without accepting model-owned questions/options and without killing the sidecar; every other unknown server request remains fatal.
- Live Runtime event delivery must use a turn-scoped subscription created before `run_turn` is scheduled and closed in the controlled-turn `finally` block. Never retain one process-global event queue across turns: an observer may legitimately finish with undrained events, and those events must be dropped with that subscription rather than replayed into the next turn.
- Runtime event `sequence` is turn-local. A synthetic control/recovery terminal uses `max(observed_or_persisted_sequence) + 1`; it must never restart at `1` and collide with an existing receipt.
- Do not put tool arguments, tool results, prompts, provider bodies, or credentials into normal Runtime events.
- Bound notification and Runtime event queues. Runtime event publication must apply bounded async backpressure so an active consumer can drain burst traffic; only a subscriber that remains full through the bounded wait fails closed.
- Logs and health payloads may include method, version, generation, safe code, hashes, and duration only; exclude prompts, model bodies, reasoning, tool arguments, credentials, and full temporary paths.
- `pnpm --dir .\aearn dev` starts a normal `tutor-main` worker for `celery,tutor-interactive,tutor-proactive,tutor-curation` plus the dedicated `tutor-codex` worker. `pnpm --dir .\aearn dev:no-codex` is the explicit local Codex opt-out; it must not disable Harness queue consumption.

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
| `item/tool/requestUserInput` arrives | reply with `{answers:{question_id:{answers:[]}}}`; connection stays healthy; no Aearn request is created from model payload |
| Prior turn finishes before its observer drains every live event | closing that turn's subscription drops the undrained backlog; the next turn observes only its own thread/turn events and starts sequence at `1` |
| Synthetic control/recovery terminal follows persisted receipts | allocate the next sequence after the maximum persisted/observed sequence; terminalize once without idempotency conflict |
| Active turn-scoped subscriber queue is temporarily full while its observer is draining | publisher awaits bounded capacity and preserves every event in order |
| Active turn-scoped subscriber remains full through the bounded wait | current turn fails closed with `runtime_event_backpressure_exhausted`; no event is carried into a later turn |
| Other unknown server request or invalid JSON | current generation fails closed |
| Child exits with pending work | pending operations receive a connection error |
| Runtime event queue is full | `runtime_event_backpressure_exhausted` |
| Worker shuts down | interrupt, close stdio, terminate if needed, release ownership |

### 5. Good / Base / Bad Cases

- Good: one worker preflights the exact version and isolated Home, then one adapter owns the active turn, receives an immediate typed tool callback, streams raw reasoning text through a turn-scoped subscription, finalizes a text-less reasoning completion from accumulated deltas, closes the subscription, and starts the next turn without replaying any undrained event.
- Base: Runtime infrastructure and the dedicated worker are enabled, but no Tutor Codex dispatch task exists; Tutor runs continue through Harness.
- Bad: two worker processes write the same Runtime Home without a file lock.
- Bad: code waits for `turn/start` to return before registering any tool registry, causing intermittent callback failure.
- Bad: one process-global live event queue survives turn completion. Undrained events from an earlier turn or conversation can then consume the next binding's sequence numbers, trigger idempotency conflicts, interrupt valid reasoning, and leave the Runtime binding falsely `running`.
- Bad: converting a missing completed-item `text` to `""`, which clears the current UI and destroys historical reasoning.
- Bad: accepting Codex `request_user_input` questions as Aearn authority, or exposing reasoning through logs/receipts instead of the dedicated owner-scoped text projection.

### 6. Tests Required

- Validate Aearn-owned input, tool, thread, turn, event, terminal, and health DTOs.
- Cover disabled, missing credential, unsupported version, initialize/account failure, and isolated-Home mismatch.
- Cover start, resume, steer, interrupt, shutdown, generation restart, and stale handles.
- Repeat the immediate callback regression enough to expose scheduler races.
- Assert single active writer and second process/file-lock rejection.
- Assert child crash fails pending work and leaves no reader/process.
- Assert raw reasoning delta mapping, text-less reasoning completion, summary/commentary separation, and stderr secret/path redaction.
- Assert `item/tool/requestUserInput` receives empty answers without a fatal connection, while an unrelated unknown server request remains fail-closed.
- Run two burst turns on one resumed thread and then a turn on another conversation; assert each controlled-turn observer sees only its own turn IDs and unique turn-local sequences even when the prior observer intentionally leaves backlog.
- Assert control/recovery terminal projection continues after the maximum observed/persisted receipt sequence instead of colliding at sequence `1`.
- Assert a slow active subscriber drains a burst larger than its queue without event loss, while an undrained subscriber returns the stable `runtime_event_backpressure_exhausted` safe code instead of hanging.
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

#### Wrong: process-global live event backlog

~~~python
self._events = asyncio.Queue(maxsize=256)
# Every turn publishes here; the next turn consumes anything the prior observer left behind.
~~~

#### Correct: turn-scoped live event subscription

~~~python
event_iterator = runtime.events().__aiter__()  # registers a fresh subscription synchronously
turn_task = asyncio.create_task(runtime.run_turn(request))
try:
    ...  # consume only this turn's live events
finally:
    await event_iterator.aclose()
~~~

The durable `RuntimeTurnResult.events` remains the final replay authority. The live subscription is only a bounded low-latency channel and must not persist beyond its controlled turn.


## Scenario: Server-authoritative LearningPlan dynamic tools

### 1. Scope / Trigger

Apply this contract when adding or changing Codex dynamic tools for `plan_drafting`, planning-fact projection, LearningPlan draft validation, tool repair/rebuild budgets, or tool-call fencing. This facade is test-only until a later cutover task admits Tutor runs to the Codex runtime.

### 2. Signatures

Registered tools:

~~~text
aearn_planning_context_read({schema_version?})
aearn_learning_plan_draft({schema_version?, modules[2..8]})
~~~

When planning facts are incomplete, `aearn_planning_context_read` returns:

~~~json
{
  "status": "awaiting_user",
  "data": {
    "missing_facts": ["..."],
    "next_missing_fact": {
      "field_key": "language_id",
      "meaning": "server-owned field semantics",
      "exact_question": "你想学习哪门编程语言？",
      "wording_policy": "use exact_question as the only question",
      "response_authority": "aearn_typed_request"
    }
  }
}
~~~

Each module has `stable_key`, `title`, bounded optional `description`, `is_core`, `is_skippable`, and `nodes[1..8]`. Each node has `stable_key`, `title`, bounded optional `description`, `is_core`, `prerequisites[]`, and `required_capabilities[]`.

The draft schema must not contain `profile_json`, `module_1..8`, user/session/run/database IDs, source selection, runtime selection, or confirmation fields.

### 3. Contracts

- Build `CompactPlanProfile` only from current confirmed `PlanningFact` leaves. Map `pace_constraints` to `pace_summary`; derive the draft title on the server.
- Reuse the same LearningPlan artifact builder, language/source policy, graph validation, quality checks, and append-only repository as the Harness capability.
- Freeze run ID, conversation/user scope, input revision, Tutor lease owner/generation, Runtime connection generation, and planning-facts fingerprint/revision when the registry is created.
- Before starting the model Turn, call `registry.prime_context()` once to read the same server-authoritative planning context without consuming a model tool-call budget. This guarantees the dispatcher knows the first missing field even if the model omits or misuses the context tool.
- When facts are incomplete, both the primed result and the model-visible tool result must expose one `next_missing_fact` descriptor derived from the server question catalog: exact `field_key`, explicit semantic `meaning`, server-owned `exact_question`, bounded `wording_policy`, and `response_authority=aearn_typed_request`.
- `language_id` always means the programming language or published course the learner wants to study. It never means the natural language used by lesson copy or the interface. The model may briefly acknowledge confirmed facts, but it must copy `exact_question` verbatim as the only question and must not invent parenthetical examples, options, or a second question.
- The dispatcher-created durable Tutor message and generated UI prompt must reuse the same `planning_question_prompt(...)` source of truth as `next_missing_fact.exact_question`; do not maintain a second prompt mapping in Runtime code.
- Refresh the fence before every model tool call and again immediately before `append_draft`.
- Tool-visible status is exactly `completed | repairable_invalid | awaiting_user | conflict | policy_blocked | unavailable | fatal`.
- `repairable_invalid`, `awaiting_user`, and the first bounded `conflict` are normal tool outputs. Policy, unavailable, fatal, deadline, and exhausted repair/conflict budgets fail the tool call.
- Default registry budgets are 6 tool calls, 2 repairs, 1 conflict rebuild, 32,000 input bytes, 300 seconds wall time, and 8,000 output bytes.
- Safe issues contain allowlisted `path`, `code`, and generic `hint` only. Never echo the invalid value, Pydantic input, internal exception, profile object, prompt, reasoning, credential, or full path.
- Durable duplicate replay is owned by the existing `(source_run_id, source_input_revision)` draft identity. When rebuilding a replay candidate, reuse the stored `change_reason`; deriving a replacement reason from the now-updated session would change the content hash and incorrectly convert an identical replay into a conflict.
- Success returns only draft ID, version, content hash, bounded counts, and a deterministic safe receipt hash. Confirmation and LearningTrack creation remain HTTP/domain authority outside the tool.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Unknown field, malformed type, module/node bound, duplicate stable key, missing/self/cyclic prerequisite | `repairable_invalid` with safe issue path/code |
| Confirmed planning facts are incomplete | `awaiting_user / planning_facts_missing` plus one first-missing `next_missing_fact` descriptor |
| `next_missing_fact` is absent, semantically ambiguous, or its `exact_question` differs from the durable prompt | contract regression; do not let the model infer wording from the raw field key |
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
- Base: facts are incomplete; primed context and the model-visible context tool both return `awaiting_user`, while Aearn—not Codex—selects exactly the first missing stable field, supplies its semantic descriptor and exact question, and creates one typed planning request.
- Good: `language_id` is missing after experience and goal are confirmed; the model may acknowledge those facts, then asks exactly `你想学习哪门编程语言？`, while the generated UI independently renders the server catalog options from the same field key.
- Bad: exposing only `missing_facts=["language_id"]` and asking the model to infer its meaning. The model can misread it as lesson/interface language and produce a natural-language question that contradicts the programming-course generated UI.
- Good replay: the App Server disconnects after commit and repeats the same tool call; the repository returns the original draft and safe receipt.
- Bad: accepting a model-authored user ID, profile, source list, facts revision, or confirm action.
- Bad: mapping a stale lease or policy denial to `repairable_invalid`, allowing the model to bypass server authority.
- Bad: rebuilding replay content with a new `change_reason`, producing a false content-hash conflict.

### 6. Tests Required

- Assert generated JSON Schema contains typed `modules[]`/`stable_key` and excludes every authority/profile/confirmation field.
- Cover unknown fields, item bounds, duplicate keys, unknown/self/cyclic prerequisites, payload/output/call/repair/conflict/wall budgets, and raw invalid-value redaction.
- Fake App Server loop: `repairable_invalid -> completed` in one turn; separately cover awaiting-user, conflict, policy, unavailable, fatal, timeout, duplicate replay, prohibited `request_user_input`, and empty-answer continuation.
- Integration must prove a typed response creates a fresh TutorRun/new Codex turn on the same persistent conversation thread and deterministically creates the next server-owned question when facts remain missing, even if the fake model omits the context tool call.
- Assert every `awaiting_user` context contains `next_missing_fact` for the first entry in `missing_facts`; `language_id` must be described as a programming language/course, its exact question must be `你想学习哪门编程语言？`, and the model-visible descriptor/instructions must not contain natural-language option examples.
- Assert the Runtime instructions require verbatim `exact_question`, and the persisted Tutor interaction prompt equals `planning_question_prompt(field)` so raw final-answer wording and generated UI cannot drift across separate prompt maps.
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

For elicitation, do not infer learner-facing semantics from a raw stable key:

~~~python
# Wrong: model invents the meaning and examples for "language_id".
missing = result.data["missing_facts"][0]
ask_model_to_phrase_question(missing)

# Correct: server catalog owns semantics and exact wording.
next_fact = result.data["next_missing_fact"]
assert next_fact["field_key"] == result.data["missing_facts"][0]
final_question = next_fact["exact_question"]
~~~

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
tutor_conversation_runtime_threads(one active persistent Codex thread per user/conversation)
tutor_run_runtime_bindings(run/user/conversation scope, persistent thread binding, external turn, connection generation, state)
tutor_runtime_text_items(binding scope, hashed external item identity, reasoning/final_answer channel, cumulative text, streaming/completed/discarded/blocked state, owner scope)
tutor_runtime_item_receipts(binding scope, semantic event key, unique sequence, allowlisted hashes/status, projection status; no raw text)
tutor_runtime_public_errors(binding scope, Aearn-safe public code, recoverable, created_at)
~~~

### 3. Contracts

- `runtime_kind` is chosen when the run is inserted, copied to retries, and cannot be updated in place.
- Binding requires an interactive `thread_turn_v2` run with an active matching Tutor lease, current input revision, and the exact Runtime connection generation.
- External thread/turn/item IDs stay in private binding state or one-way hashes. They never enter public URLs, Tutor DTOs, conversation events, SSE payloads, or Desktop types; clients receive only Aearn-owned text-item IDs.
- Runtime receipts contain only allowlisted kind/status/tool name, input/result/content hashes, safe code, sequence, timestamps, and an optional Aearn public item reference. Raw text is stored only in owner-scoped `tutor_runtime_text_items`, never in receipts/logs/health.
- Raw reasoning and raw `final_answer` deltas are separate text channels. Reasoning summary and `agentMessage.phase=commentary` are ignored. Only `agentMessage.phase=final_answer` may become the formal Tutor message. If a provisional stream was classified as `final_answer` but its completed item is authoritatively `commentary`, zero and mark that text item `discarded` and emit a text-free `discard` event.
- A text-less completed reasoning item finalizes the stored cumulative text/hash. It never replaces non-empty text with empty; explicit `discard` is the only removal authority. Every terminal turn also zeroes and marks any remaining `streaming` text item `discarded`, then emits text-free discard events before the terminal projection.
- Completed text items link to the accepted Tutor message, so owner-scoped history/reconnect/refresh returns `runtime_output {reasoning_items[], final_answer_item}`. Current items may be streaming; historical items are completed.
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
| Reasoning summary, commentary, command, or path item | `ignored_nonpublic`; no runtime text/public message |
| Completed item corrects a provisional `final_answer` stream to `commentary` | zero the provisional text, mark it `discarded`, emit a text-free discard event, and create no Tutor message |
| Any terminal event finds remaining `streaming` runtime text | zero and mark every remaining item `discarded`; terminal snapshot/history contains no stuck stream |
| Raw reasoning delta | append to owner-scoped reasoning text item and emit exact `tutor_runtime_item_stream_v1` event |
| Reasoning completion omits `text` | mark existing cumulative item completed and emit its full stored text; never clear it |
| Final text is missing with no accumulated answer, hash-mismatched, oversized, or teaching-unsafe | `blocked_unsafe`; completed terminal is converted to failed |
| Runtime completed without an accepted final message | Failed with `TUTOR_RUNTIME_OUTPUT_MISSING` |
| Runtime interrupted | Tutor outcome `cancelled`, process `interrupted`, no invented message |
| Runtime unavailable | Tutor outcome `model_unavailable`, process `unavailable`, public `TUTOR_RUNTIME_UNAVAILABLE` |
| Runtime failed | Tutor outcome/process `failed`, public `TUTOR_RUNTIME_FAILED` or bounded output-blocked code |

### 5. Good / Base / Bad Cases

- Good: a current leased Codex run binds the conversation's persistent thread, appends multiple reasoning deltas, drains a burst larger than the live subscriber queue under bounded backpressure, discards any phase-corrected commentary stream, finalizes a text-less reasoning completion without loss, accepts one safe `final_answer`, and links only completed public channels to the historical Tutor message.
- Good replay: reconnect repeats the same normalized events; message, text item, process, error, and receipt counts do not increase.
- Base: a terminal answer has no reasoning items; history renders the answer without an empty `think` row.
- Base: Harness-created runs keep `runtime_kind = "harness_v1"` and never create Runtime bindings or receipts.
- Bad: persist the App Server item JSON in a generic JSONB receipt column or copy raw reasoning into audit receipts/logs.
- Bad: accept every completed `agentMessage` as final, or leave a provisional answer/reasoning row in `streaming` after commentary correction or turn terminal; commentary may then flash, persist, or leave the UI stuck before the real final answer.
- Bad: treat a stale callback as a failed current run instead of an ignored audited receipt.

### 6. Tests Required

- Bootstrap twice and assert the Runtime tables, indexes, constraints, immutable triggers, and `harness_v1` default.
- Assert `runtime_kind`, binding identity, terminal binding state, receipts, and public errors cannot be mutated after their allowed lifecycle point.
- PostgreSQL integration must cover multi-delta reasoning plus text-less completion, provisional-final-to-commentary discard, terminal cleanup of unfinished text, completed/interrupted/failed/unavailable, unsafe/missing final, duplicate replay, conflicting sequence, and stale connection generation.
- Assert current snapshot, reconnect, refresh, and historical message return owner-scoped raw reasoning/final answer from `tutor_runtime_text_items`; terminal no-reasoning output has no empty row.
- Serialize receipts/log-safe evidence and assert raw reasoning/final text, commentary, tool arguments/results, provider diagnostics, credentials, and external thread/turn/item IDs are absent. Serialize owner history and assert only Aearn text-item IDs plus the allowed runtime text channels appear.
- Adapter tests must prove tool names and argument/result hashes are present while raw arguments/results are absent, reasoning summary/commentary are separated, only `phase = "final_answer"` becomes a final-message event, a slow observer drains burst traffic beyond queue capacity, and an abandoned subscriber still fails closed.
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
runtime_event = adapter.normalize(item)  # typed reasoning/final_answer; external IDs/arguments stay private
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
- One `TutorConversation` owns one persistent Codex App Server thread. Every fresh `TutorRun`—including a typed-request response—starts a new turn inside that same thread. The first interactive Runtime kind is inherited; Retry copies the failed root Runtime kind. Clients, models, queued metadata, and public DTOs cannot select or mutate it.
- Harness and Codex workers claim the same durable job table with an exact Runtime filter. `TutorRuntimeDispatchRouter` reads only the immutable run snapshot; it never re-evaluates feature or health.
- `CodexTutorRunDispatcher` never composes `TutorRunLoop`. It acquires the Tutor lease, registers only the typed LearningPlan tools, binds the private Runtime thread, projects normalized events, and returns the existing Aearn run result.
- During an active Codex turn, a higher durable input revision becomes `turn/steer`; cancellation, supersede, lease loss, or control failure becomes `turn/interrupt`. Control failure terminates unavailable rather than leaving an orphan task.
- A recovered dispatch with an existing private binding does not start another external turn. It terminalizes the same run as unavailable so a learner Retry can create a fresh same-Runtime run without duplicating model or tool side effects.
- The dispatcher primes planning context before each model turn. When facts are incomplete it selects only the first missing field and creates one server-catalog typed request after the turn; a learner response creates a fresh run/turn and repeats until complete. Codex built-in `request_user_input` never creates Aearn state.
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
| Model calls Codex `request_user_input` | empty client response, sidecar stays alive, Aearn creates at most one server-owned typed request from primed facts |
| Typed response leaves more missing facts | fresh run/new turn on same thread, next first-missing catalog request appears without ordinary composer input |

### 5. Good / Base / Bad Cases

- Good: a fresh plan-drafting conversation sees one current exact readiness row, freezes Codex, runs through the dedicated worker, steers one later accepted revision, projects one final answer, and leaves confirmation to Aearn.
- Base: admission is disabled; the same public request creates a normal Harness run without starting or depending on the Codex worker.
- Good recovery: a failed Codex run creates a fresh Retry with `codex_sidecar_v1`; committed draft/message receipts remain and no Harness fallback occurs.
- Bad: route from current health instead of persisted `runtime_kind`, let the client set Runtime, let both workers claim the same job, or start a second external turn for a run that already has a binding.

### 6. Tests Required

- Default-enabled configuration plus explicit feature-off behavior.
- Exact readiness matrix for version, model, provider, protocol, generation, freshness, and status.
- Public acceptance proving only a new plan-drafting run freezes Codex and no Runtime control field enters the DTO.
- Runtime-filtered durable claims, frozen-kind router, one persistent conversation thread with fresh run turns, deterministic next typed request, prohibited client elicitation, Codex dispatcher projection without Harness composition, revision-to-steer, cancel-to-interrupt, and same-Runtime retry.
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

## Scenario: Semantic planning language resolution and narrow durable requests (2026-09-03)

- `PlanningIntentResolver` reads only exact current learner input, current confirmed facts, active PostgreSQL courses/capabilities, deterministic intent tags, and an optional validated hint. It never reads Tutor output, provider reasoning, course description, or Runtime item text.
- One explicit active language is the only auto-confirm path and writes `policy_version=planning-language-intent-v2`. Multiple, unsupported, conflicting, deterministic-direction, or semantic evidence never auto-confirms.
- Model context receives at most 24 server-built candidates with canonical language, course title, level, capability state, and execution family. It receives no course UUID, URL, command, path, runtime configuration, or secret.
- `planning-intent-hint-v2` is extra-forbid and allows only 1..3 unique current canonical language values, `high|medium`, and one closed reason code. It is legal only on `planning_input + language_id`; low/insufficient evidence uses `clarification` without a hint.
- Harness carries the hint through strict provider output and `TutorDecision`. Codex first reads candidates and then calls `aearn_planning_context_read` again with the same hint or `clarification_required=true`; the dispatcher converts only validated tool state into an existing typed request.
- Decision gate and persistence re-resolve current input revision/catalog. Unknown, duplicate, inactive, stale, extra, or oversized candidates fail closed and never widen. Enabled no-signal becomes clarification; feature-off alone may use `full_catalog` with `feature_off_rollback`.
- A durable semantic request persists 1..3 exact options, `recommended=null`, `selection_scope=intent_shortlist`, safe semantic reason, and v2 policy. Public snapshot/SSE/history omit confidence, rationale, candidate evidence, and course UUIDs; historical v1/full-catalog requests replay unchanged.
- New runs select immutable `tutor.learning-plan-draft@1.0.2`; versions 1.0.0/1.0.1 remain untouched. Default tests use fake provider/App Server and local PostgreSQL only.

## Scenario: Bounded Runtime delta coalescing and semantic budgets (2026-08-21)

### 1. Scope / Trigger

Apply when changing Codex reasoning/final-answer delta mapping, Runtime turn budgets, source/projection sequence, PostgreSQL Runtime receipts, or conversation `turn_output` projection. This does not authorize provider/model fallback, public source telemetry, or live-provider tests.

### 2. Signatures

```python
RuntimeDeltaCoalescer.push(event, now) -> tuple[RuntimeEvent, ...]
RuntimeEvent(source_sequence_start, source_sequence_end, source_delta_count,
             source_content_sha256, projection_sequence)
```

DB receipt fields are `projection_sequence`, `source_sequence_start/end`, `source_delta_count`, and `source_content_hash`. Environment keys are `CODEX_RUNTIME_DELTA_COALESCING_ENABLED`, `CODEX_RUNTIME_DELTA_FLUSH_{DELAY_MS,CHARS,BYTES}`, `CODEX_RUNTIME_MAX_{PENDING_BYTES,RAW_NOTIFICATIONS,ITEMS,TOOLS,VISIBLE_TEXT_CHARS}`.

### 3. Contracts

- Each turn owns one coalescer. Only consecutive equal `thread/turn/item/kind/channel/index/phase` reasoning or final-answer deltas merge.
- Default flush is 25ms, 1,024 characters, or 4KB; item/phase/summary/tool/compaction/completed/terminal/error boundaries flush first and pending bytes never exceed 16,000.
- PostgreSQL/SSE/Desktop consume projection sequence. Receipt source evidence contains only continuous range/count/SHA-256, never raw text/body/external identity.
- `item/completed` remains final calibration authority; commentary, reasoning summary, terminal discard, subscriber backpressure, and snapshot recovery stay unchanged.
- Feature-off restores per-delta projection under the new semantic budgets and never restores the retired 2,000-event failure.

### 4. Validation & Error Matrix

| Condition | Stable result |
| --- | --- |
| Normal 5,000 tiny deltas | completed; bounded projection chunks |
| Raw notifications exceed runaway guard | `runtime_raw_notification_runaway` |
| Item/tool/text/time budget exceeded | matching `runtime_*_budget_exhausted` / `runtime_turn_time_exhausted` |
| One pending delta exceeds byte bound | `runtime_pending_bytes_exhausted` |
| Projection gap at Desktop | fresh snapshot; model turn unchanged |
| Incomplete source receipt range | PostgreSQL CHECK rejection |

### 5. Good / Base / Bad Cases

- Good: 5,000 one-character reasoning deltas become a small number of exact chunks and completed text matches source byte-for-byte.
- Base: coalescing disabled; 5,000 projection events still complete because source count is not a normal business budget.
- Bad: increasing 2,000 to another fixed number, merging across item/tool/phase, or exposing source range in public SSE.

### 6. Tests Required

- Adapter: 5,000 deltas, sparse timer flush, Unicode/whitespace, item/phase boundaries, long LearningPlan repair, feature-off, independent semantic safe codes.
- PostgreSQL: bootstrap twice, source-range CHECK, projection uniqueness, replay/conflict, completed calibration, commentary correction, terminal discard, receipt redaction.
- Desktop/browser: existing exact DTO and gap/snapshot tests, three viewport overflow/console smoke. Default tests use fake App Server/local PostgreSQL only.

### 7. Wrong vs Correct

#### Wrong

```python
if len(collected) >= 2_000:
    raise RuntimeUnavailableError("runtime_event_budget_exhausted")
```

#### Correct

```python
for projected in coalescer.push(source_event, now=clock()):
    await publish(projected)
# raw runaway, item, tool, text, time, and pending-byte budgets remain independent.
```
