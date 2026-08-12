# Container Sandbox Executor Operations Contract

**Status:** Current operational boundary, 2026-08-12.
**Authority:** `aearn/services/executor/`, `aearn/infra/executor/`,
`tutor_execution_*` schema, executor tests, and
[Tutor Harness Runtime](../architecture/tutor-harness-runtime.md).

The executor is an explicit, standalone container process. It is not a public
HTTP API, SSE producer, Desktop dependency, normal Celery runtime client, or
fallback for the removed legacy runner. The default product posture remains
safe unavailable until an operator intentionally supplies all reviewed
preconditions.

## 1. Process ownership and commands

The normal development process set is PostgreSQL, Redis, API, general Celery
worker, and Desktop. It does **not** start the executor. Start it separately:

```powershell
# Refresh safe health and process at most one durable job.
pnpm --dir .\aearn executor:once

# Long-running isolated process in a dedicated terminal.
pnpm --dir .\aearn executor:dev
```

The executor reads the environment of its own terminal. Its settings module
does not load or modify `aearn/.env`; pass any required `DATABASE_URL` and
`TUTOR_EXECUTOR_ENABLED` explicitly to that process. API, Desktop, Harness,
and the normal worker do not receive a Docker runtime client dependency.

## 2. Default-deny posture

```text
TUTOR_EXECUTOR_ENABLED=false
```

With the default setting, the service records safe feature-disabled/health
facts and does not claim jobs, start containers, use a host subprocess, pull
an image, or open a network path. Setting the flag to `true` alone is still
insufficient: the reviewed image-lock registry is intentionally empty until
real immutable locks are approved, so no runtime is available by default.

No caller may substitute an image tag, local image ID, arbitrary Docker command,
host executable, browser runner, or fallback network request for a missing
reviewed lock.

## 3. Enablement preconditions

A job may reach a container only when every condition is true:

1. The standalone executor is explicitly enabled and can reach PostgreSQL.
2. The Git-owned runtime catalog contains the requested supported runtime.
3. `aearn/infra/executor/image-locks.json` contains the reviewed exact
   `repository@sha256:<64-hex>` lock for that runtime.
4. Catalog protocol, lock fingerprint, fixed non-root identity, image entrypoint
   and resource limits agree.
5. A current interactive run has server-issued execution proof, exact selected
   Skill/effect evidence, current input revision, valid lease, remaining
   budget, and is not cancelled.
6. The executor has a compatible safe health heartbeat and can verify the
   existing local image without implicitly pulling it.

Proactive work can never satisfy item 5 for `runner.execute`: background
composition permanently denies learner-code execution even when the executor
is otherwise enabled.

## 4. Immutable launch profile

`build_launch_spec()` derives every runtime setting from the reviewed lock.
Neither learner input, model output, API payload nor queue row can choose an
image, command, mount, network mode, device, privilege flag or resource limit.

The fixed profile includes:

- exact digest image and reviewed in-image entrypoint;
- `network_mode="none"`, no host network escape;
- read-only root filesystem; tmpfs only for `/work` and `/tmp`;
- reviewed non-root UID/GID, `cap_drop=("ALL",)`,
  `no-new-privileges:true`, never privileged;
- bounded PID, CPU, memory, file descriptor, output and wall-clock limits;
- bounded daemon-side local log buffer;
- labels binding job ID, launch token, lock fingerprint and runtime ID.

The supported catalog protocol entries are Python stdout, browser preview,
TypeScript, SQLite, Java, Go and C#. Rust and C++ are absent. Dockerfiles are
build definitions only; they do not themselves authorize runtime execution.

## 5. Durable lifecycle and recovery

`tutor_execution_jobs` is the source of truth. The normal effect transaction
creates/replays at most one job for a proof identity; broker delivery is only a
wake-up mechanism.

1. The executor claims `pending` work using short transactional locking.
2. It records a launch token before any external side effect.
3. A replacement executor may adopt only a container with exactly matching
   labels/token/lock; unknown prior state becomes `launch_uncertain`.
4. `launch_uncertain` is terminal/safe. It is never a reason to start a second
   container.
5. Cancellation is idempotent before claim, before launch, while waiting and
   after terminalization. Cleanup runs in `finally`; cleanup failure is a safe
   failure and quarantines health rather than exposing raw engine output.

## 6. Public-data and observability boundary

Durable executor rows and safe health facts may contain opaque IDs, fingerprints,
states, counters, timestamps, stable codes and capped learner-safe result text.
They must not expose learner submission code, hidden tests, image digest,
container ID, command, mount, filesystem path, raw Docker error, provider data
or credentials through Tutor API/SSE/Desktop.

No HTTP endpoint turns arbitrary caller data into a job. The public current
runtime only reads safe executor availability/result facts when an approved
interactive effect is composed; it never imports the Docker client.

## 7. Verification

```powershell
# API-side execution/effect boundary.
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_execution_contracts.py -q

# Standalone executor contract tests.
uv --directory .\aearn\services\executor run python -m pytest
```

Real Docker conformance is explicitly opt-in and remains skipped/fail-closed
until the project carries seven reviewed immutable image locks and matching
fixtures. A passing unit suite does not justify enabling a production image
fleet; record the actual result and residual risk in the
[Release Readiness Ledger](../qa/tutor-harness-release-readiness.md).

## 8. Current reviewed-lock status

As of 2026-08-12, `aearn/infra/executor/image-locks.json` contains zero locks. The runtime catalog lists Python, browser preview, TypeScript, SQLite, Java, Go, and C# build/runtime contracts, but catalog presence and Dockerfiles are not execution approval. Public composition therefore cannot produce `container_verified` for any language.

Local Python/browser/TypeScript/SQL/Java/Go/C# runner tests are development evidence only and must be labeled `teaching_local`. Java and HTML/CSS are extension validation; Go and C# remain partial and toolchain-dependent; Rust and C++ do not have current executable container runtimes. No command may convert a successful local runner result into public executor health or a reviewed image lock.
