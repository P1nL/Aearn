# Research: current-runner-executor-baseline

- Query: Establish the current execution, worker, Docker, persistence, and capability boundaries before planning the Child 03 container-grade executor.
- Scope: internal
- Date: 2026-07-27

## Confirmed Current Facts

### 1. Current execution is host-process based, not container grade

- `app/services/runners/sandbox.py` launches `sandbox_runner.py` through
  `subprocess.run()` in a host temporary directory. It constrains Python
  imports/builtins but does not provide OS-container isolation.
- Node/TypeScript and managed compiled runners also invoke host subprocesses
  and write temporary workspaces. `runner_registry.py` explicitly labels the
  Python, Node, SQL, and compiled runner policies
  `is_container_grade=False`.
- Existing language disclosures acknowledge this explicitly. Python is
  `subprocess_restricted_not_container`; Java/Go/C# are local teaching-grade
  toolchain runners; SQL uses a local SQLite teaching database; browser preview
  is not a Docker runtime. See
  `app/services/runners/language_capabilities.py:65-279`,
  `runner_registry.py:105-236`, and `sandbox.py:43-148`.

### 2. Current configuration and operations cannot be reused as Harness enablement

- `Settings.real_execution_enabled` defaults to true and governs legacy
  execution. `Settings.tutor_harness_enabled` defaults to false.
  `app/core/config.py:58-65`.
- The current compose file contains PostgreSQL and Redis only; it defines no
  executor service, Docker socket boundary, image registry, or executor health
  check. `aearn/infra/docker-compose.yml:3-38`.
- `start-dev.ps1` starts one general Celery worker through the API environment;
  it tracks only API, worker, and desktop processes. No isolated executor queue
  or PID is present. `aearn/scripts/start-dev.ps1:119-121,318-331`.
- Local Docker is running in this checkout: Docker Engine `29.3.0`, Linux
  engine, cgroup v2, with Docker Desktop already serving PostgreSQL/Redis.
  This proves a local prerequisite, not production executor readiness.

### 3. Current worker and package boundaries

- `aearn/services/worker/aearn_worker/worker_app.py` owns a Celery application
  with Redis broker/backend and only health/review tasks. It has no executor
  queue, Docker client, image policy, task claim, or cancellation contract.
- API currently depends on the editable worker package. Putting Docker control
  inside API runtime code would violate the parent boundary; a separate executor
  process/package or a separately launched, queue-isolated worker is required.
- Existing formal directory guidance places async execution in `services/worker/`
  and local service wiring in `infra/`; a new executor package is justified only
  if the Docker privilege/operations boundary cannot remain isolated within the
  worker process.

### 4. Child 01/02 contracts impose a durable-submit boundary

- Child 01 registered only `grounding.retrieve`; no execution capability or
  effect is currently catalog-enabled.
- Child 02's `PostgresTutorRepository.commit_effect_if_current()` invokes an
  effect handler inside the same database transaction, only after exact selected
  Skill/effect authorization, active lease, current input revision, and
  idempotency checks. `app/services/tutor/persistence.py:191-204,808-938`.
- A Docker launch must not run inside that database transaction. The Child 03
  effect handler therefore needs to create a durable execution job/audit record
  in the transaction; a separate executor service claims and runs the job only
  after commit. The job queue is the durable source of truth, not an API call or
  an in-memory Celery message alone.
- Raw learner code, hidden tests, Docker errors, paths, and command lines cannot
  be copied into Child 02 safe trace/event/outbox projections. The executor must
  use trusted message/exercise references and return bounded runner facts only.

### 5. Parent target and verified gaps

- The parent assigns Child 03 a separate executor queue/service, immutable image
  digests, no-network launch, read-only root, scoped temporary storage, resource
  limits, cancellation, cleanup, audit, and bounded result projection.
  `.trellis/tasks/07-22-agent-harness-rearchitecture/design.md:531-551`.
- The parent defines `runner.execute` as an interactive explicit-intent effect;
  no proactive run may execute learner code.
  `.trellis/tasks/07-22-agent-harness-rearchitecture/design.md:291-300`.
- The target transition contract currently does not authorize public product
  traffic. Child 06 owns API/SSE/Desktop exposure after this child proves the
  internal executor contract.

## Planning Implications

1. Add a dedicated Harness executor gate distinct from `REAL_EXECUTION_ENABLED`;
   it defaults false and cannot enable legacy subprocess execution.
2. Use a developer-owned image registry with exact `sha256:` digests. The API,
   model, learner, capability payload, and job payload may never select an image,
   Docker command, mount, network mode, or host path.
3. Design execution as two phases: a transactionally persisted intent/job from
   the Tutor effect handler, followed by a separately privileged executor claim
   and container lifecycle. API processes do not receive Docker credentials or
   socket access.
4. Require no network, no host bind mount, non-root user, read-only root,
   explicit writable tmpfs workspace, cap drop/no-new-privileges, PID/CPU/memory
   caps, wall-clock/output limits, cancellation, cleanup, and safe audit/result
   projection.
5. Existing runner/evaluation services remain the learner-facing authority. The
   new executor returns normalized bounded facts; it must not expose Docker
   diagnostic text or silently fall back to `subprocess.run()`.

## Product-Scope Decision Still Needed

The repository does not state which real runtime images should be present in
Child 03's first production allowlist. That choice changes the reviewed digest
registry, runner adapter matrix, image build/release process, conformance tests,
and what Child 06 may eventually expose. The existing public legacy languages
cannot be silently treated as container-ready merely because they have a local
runner.

## Not Found

- No Docker SDK/Engine client dependency or container execution service.
- No immutable image digest registry, image build pipeline, or Dockerfile for
  learner execution.
- No `runner.execute` descriptor, executable Skill bundle, or in-transaction
  job-creation effect handler.
- No durable execution-job/audit table or executor queue lease/cancellation
  protocol.
- No existing `Last-Event-ID`/Desktop integration relevance; those remain Child
  06 concerns.