# Codex Runtime Sidecar

## Scenario: Aearn-owned Codex App Server runtime boundary

### 1. Scope / Trigger

Apply this contract when changing the Codex App Server connection, runtime adapter, supervisor, worker ownership, lifecycle configuration, dynamic tool callbacks, or local `tutor-codex` worker startup.

The runtime process is enabled by default, but Tutor business admission is separate. Runtime availability must never imply that a Tutor run is routed to Codex.

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

Lifecycle tasks are `tutor.codex.runtime_health` and `tutor.codex.runtime_shutdown`. There must be no `tutor.codex.dispatch` task until controlled cutover explicitly adds business admission.

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
