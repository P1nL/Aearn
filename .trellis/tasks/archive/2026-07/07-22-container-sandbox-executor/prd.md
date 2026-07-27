# Container Sandbox Executor

## Goal

Deliver the feature-disabled, container-grade execution foundation that lets a
future **interactive** Tutor request run bounded learner code without granting
the API process, model, learner, legacy runner, or public request arbitrary
Docker control.

The learner value enabled by this child is trustworthy future code execution:
an explicit run, test, debug, or explain request can be represented as a
durable, scoped execution intent and eventually run in a reviewed isolated
runtime. Proactive work, host-subprocess fallback, arbitrary images or commands,
outbound network, and unbounded diagnostics remain unavailable.

## Dependencies and Authority

- **Upstream contracts:** Child 01 owns catalog/policy/gateway validation.
  Child 02 owns exact Skill/effect evidence, lease/revision/idempotency CAS,
  safe traces/events, and the in-transaction effect-handler seam. This child
  may add `runner.execute` only through those contracts.
- **Target authority:** the parent Harness artifacts and
  `docs/architecture/tutor-harness-transition.md`. Current runner modules,
  language disclosures, docs, and tests are legacy/current evidence only; they
  do not authorize Harness execution.
- **Downstream boundary:** Child 04 owns generic background queue/retry policy;
  Child 05 owns plan/memory/activity semantics; Child 06 owns public API/SSE/
  Desktop exposure. This child establishes no public route, stream, UI, or
  feature activation.
- **Documentation delta:** update the transition contract and a narrow
  executor runtime/operations contract only after the protocol and runtime
  matrix are implemented. Do not rewrite legacy runner product documentation
  prematurely.

## Confirmed Scope Decision

**Confirmed on July 27, 2026:** the first container-executor implementation
covers every runtime tier that is currently executable in the formal Aearn
product:

| Runtime ID | Current executable tier / language scope |
| --- | --- |
| `python-stdout-v1` | Python stdout/function tests |
| `browser-preview-v1` | JavaScript and HTML/CSS browser preview |
| `node-typescript-v1` | TypeScript function tests |
| `sqlite-query-v1` | SQLite teaching SQL |
| `java-managed-v1` | Java single-file managed compiled tests |
| `go-managed-v1` | Go single-package managed compiled tests |
| `dotnet-managed-v1` | C# single-file managed compiled tests |

Rust and C++ remain outside the allowlist. Their current metadata is
`compiled_sandbox_later` / non-executable, and this child must not silently
promote either language to a runnable Harness runtime.

A runtime remains disabled unless a reviewed, developer-owned exact
`repository@sha256:<64-hex>` image lock and matching executor health evidence
are present. Dockerfiles, registry schemas, protocol fixtures, and build
verification are in scope; production image publication, digest rotation, and
traffic activation are not.

## Confirmed Repository Facts

1. Python, Node/TypeScript, Java/Go/C#, SQL, and browser-preview execution
   currently use host subprocesses, local toolchains, SQLite, or browser
   checks. Their runner policy is not container grade; Python explicitly says
   `subprocess_restricted_not_container`.
2. `REAL_EXECUTION_ENABLED` defaults to true for legacy execution and
   `TUTOR_HARNESS_ENABLED` defaults to false. A separate executor gate is
   required; the legacy flag cannot authorize Harness execution.
3. Current Compose defines PostgreSQL and Redis only. The general Celery worker
   has no executor queue or Docker client, and the development script tracks
   no executor process.
4. Child 02's `PostgresTutorRepository.commit_effect_if_current()` invokes an
   allowed handler inside the same transaction only after exact Skill/effect,
   lease, revision, cancellation, and idempotency checks. Docker work cannot
   run in that transaction; the handler must persist a durable job and return.
5. Docker Desktop is available locally, but no checked-in image lock, execution
   job table, Dockerfile family, privileged executor service, or container
   conformance test currently exists.

## Requirements

### R1 — Separate Privileged Executor and Durable Submission

- The API/Tutor process, legacy runner modules, routes, and public request
  paths must have no Docker socket, daemon credential, Docker SDK/client, or
  host-container launch path. A separately deployed executor process owns the
  only container-runtime client.
- The `runner.execute` effect handler runs inside Child 02's transaction but
  only records a durable execution intent/job and safe audit evidence. It never
  starts, pulls, inspects, or cleans up a container.
- The durable PostgreSQL job table is the execution source of truth. A broker
  message, if added later, is only a wake-up optimization and cannot be the
  sole queue record.
- The executor claims committed jobs after the transaction using scoped lease
  and idempotency rules. Cancellation, lease loss, retry, duplicate delivery,
  and terminal replay cannot create a second container launch.

### R2 — Trusted Interactive Intent, Catalog, and Policy Gate

- `runner.execute` is allowed only when an exact selected Skill manifest and a
  registered effect descriptor both permit it.
- A server-issued `ExecutionIntentProof` must bind interactive origin, user,
  conversation, run, current input revision, source-message/exercise
  references, one explicit action (`run`, `test`, `debug`, or `explain`),
  policy/budget evidence, and an expiry. The model supplies no image, command,
  mount, path, network, runtime, or raw-code field.
- Proactive origin is permanently denied. Missing, stale, cross-scope,
  cancelled, expired, already-consumed, or over-budget intent proofs are denied
  before a job exists or a container is touched.
- Harness executor availability defaults deny and is independent of
  `REAL_EXECUTION_ENABLED`. A disabled or unhealthy executor/image lock returns
  a typed denial or unavailable fact; it never falls back to a legacy runner.

### R3 — Developer-Owned Images and Fixed Isolation Profile

- Runtime selection comes only from a Git-owned developer catalog plus an
  immutable reviewed image-lock registry. Each enabled lock uses an exact
  `repository@sha256:<64-hex>` reference, fixed protocol version, non-root
  user, fixed in-image entrypoint, and approved limit profile.
- Model, learner, API request, intent proof, and job payload cannot select an
  image, tag, command, shell, mount, device, host path, Docker option, or
  network mode. Jobs do not pull images or install dependencies.
- Every launch enforces no network, no host bind mount, read-only root,
  explicit writable tmpfs work areas, non-root execution, dropped Linux
  capabilities, `no-new-privileges`, bounded PID/CPU/memory/output/wall-clock
  limits, fixed command, and mandatory cleanup.
- Runtime input uses a versioned bounded stdin protocol and an in-image
  harness. Raw learner code and hidden tests remain transient trusted input;
  they must not enter trace, event, audit, export, queue, or public result
  payloads.

### R4 — Normalized Results, Cancellation, and Safe Audit

- Containers return only a bounded structured result that an API-side pure
  adapter can normalize into the existing `RuntimeExecutionResult` authority:
  success, compile/runtime failure, timeout, cancelled, unsupported, or
  unavailable plus capped learner-safe output and test feedback.
- Job/audit storage records stable job identity, reviewed lock fingerprint,
  state transitions, resource/result counters, cancellation, cleanup outcome,
  and safe diagnostic code. Public projection never exposes Docker errors,
  container IDs, image digests, commands, paths, raw code, hidden tests, or
  host details.
- The executor uses a deterministic internal launch identity so a replacement
  worker may adopt/inspect an already-created container, but must fail closed
  with an internal uncertain-launch state rather than create another one.
- Cancellation before claim, during launch, during execution, and after a
  terminal result is idempotent. Cleanup failure becomes a safe failed result
  and executor-health incident, not a leaked runtime exception.

### R5 — All Current Runtime Protocols

- Implement one common executor protocol and one constrained image/harness
  entry for each of the seven confirmed runtime IDs.
- Python, TypeScript, Java, Go, and C# remain single-submission teaching
  exercises; they may not install packages, restore dependencies, or run an
  arbitrary project.
- Browser preview remains the existing reviewed JavaScript/HTML/CSS exercise
  protocol; it may not navigate to arbitrary URLs, download content, load
  extensions, or accept user-selected browser flags.
- SQLite remains an ephemeral read-only teaching dialect; it must not connect
  to Aearn PostgreSQL, attach files/extensions, or execute DDL/DML.

### R6 — Compatibility and Feature-Off Safety

- Keep legacy subprocess runners unchanged and legacy-only during migration.
  A Harness denial/unavailable result never invokes `subprocess.run()` or a
  legacy adapter as a fallback.
- Do not add public API/SSE/Desktop wiring, proactive/background code
  execution, arbitrary shell/database/filesystem/network access, multi-file
  projects, package management, unreviewed image pulls, deployment, or legacy
  runner deletion.
- The new contract remains feature-disabled until the exact lock registry,
  executor health, catalog/policy, and later Child 06/07 integration gates all
  pass.

## Acceptance Criteria

- [ ] API/Harness/legacy runner/route code has no Docker client, socket,
  `DOCKER_HOST`, or container-launch capability; only the dedicated executor
  boundary owns it and static tests enforce the boundary.
- [ ] Exact Skill/effect policy, interactive trusted intent proof, current
  scope/revision/lease, budget, executor health, and image allowlist are all
  required before `runner.execute` can create one durable job. Proactive,
  malformed, stale, cross-scope, or unavailable requests are denied without a
  launch.
- [ ] Effect-handler retry and job replay preserve one job identity. Lease
  expiry, cancellation, duplicate wake-up, and terminal replay cannot launch a
  second container; uncertain prior launch fails closed instead.
- [ ] The image-lock registry rejects tags, local image IDs, malformed digests,
  unknown runtimes, arbitrary commands, mounts, paths, and model/user-selected
  targets. A job never pulls an image or bypasses the fixed launch profile.
- [ ] Every confirmed runtime has a reviewed protocol/harness entry and
  runtime-specific conformance coverage. Rust and C++ have no executor entry
  and remain unsupported.
- [ ] Unit/static/conformance tests cover network, mount/root/tmpfs, UID,
  capabilities, resources, output, timeout, cancellation, cleanup, audit,
  redaction, and Docker-unavailable behavior. Docker absence disables the
  capability and never triggers a host fallback.
- [ ] Safe job results can be adapted to the current runner result shape while
  preserving hidden-test/redaction behavior and excluding Docker/internal
  details from any public projection.
- [ ] No public route, SSE event delivery, Desktop behavior, proactive path,
  legacy execution behavior, or feature activation is introduced.

## In Scope

A separate executor process and privileged boundary; shared typed execution
contracts; durable intent/job/attempt/health storage; exact image-lock registry
and fixed launch profile; seven constrained Dockerfile/harness definitions;
`runner.execute` descriptor/Skill/effect integration; cancellation/cleanup/
health; normalized safe results; focused unit, PostgreSQL, static, and opt-in
Docker conformance tests; narrow transition/runtime/operations documentation.

## Out of Scope

Public API/SSE/Desktop integration; proactive execution; generic background
scheduler/retry policy; arbitrary shell, database, filesystem, network, or
project access; dependency installation; actual production image publishing or
digest rotation; feature activation; deployment; legacy-runner deletion; Rust
or C++ execution; changing `REAL_EXECUTION_ENABLED` or legacy route behavior.

## Risks and Deferred Items

- Seven runtimes multiply the image and conformance matrix. The implementation
  must share one strict core and fail closed per runtime rather than weaken
  isolation for difficult toolchains.
- Docker daemon access is a high-privilege boundary. It is intentionally
  isolated in a standalone executor service; local Docker availability is only
  a prerequisite, not proof that an image is reviewed or safe for traffic.
- A real Docker launch cannot be transactionally coupled to PostgreSQL. The
  design therefore chooses at-most-once launch over unsafe automatic relaunch:
  an uncertain post-reservation crash is recorded for safe remediation rather
  than producing a second container.
- Reviewed image locks are a release prerequisite. Until real immutable digest
  entries exist, all runtime definitions remain disabled without placeholder or
  tag-based activation.
- Child 06 still owns user-facing intent extraction/result delivery and Child
  07 owns legacy retirement. This child only provides typed internal seams.
