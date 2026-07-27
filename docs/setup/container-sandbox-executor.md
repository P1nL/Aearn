# Container Sandbox Executor Operations Contract

## Status and Scope

This is a feature-disabled internal service for the Tutor Harness target. It
has no HTTP route, public SSE frame, Desktop consumer, or legacy-runner
fallback. The normal `pnpm --dir .\aearn dev` process set remains PostgreSQL,
Redis, API, general worker, and Desktop only; it does not start the executor.

The executor is the sole Aearn service package permitted to own a container
runtime client. API/Harness code only persists a proof/job and reads safe health
and result facts. The worker remains a general Celery process without runtime
client dependencies.

## Explicit Local Commands

```powershell
# One health/queue poll. Default setting records feature-disabled availability.
pnpm --dir .\aearn executor:once

# Long-running isolated process, started intentionally in a separate terminal.
pnpm --dir .\aearn executor:dev
```

The process reads environment supplied to that terminal. It does not load or
modify `aearn/.env`. `TUTOR_EXECUTOR_ENABLED` defaults to `false`; setting it
true does not authorize execution by itself.

## Enablement Preconditions

An individual runtime is available only when all of these are true:

1. `TUTOR_EXECUTOR_ENABLED=true` for the explicit executor process and the
   feature remains independently composed by a later Harness integration task.
2. The Git-owned catalog contains the approved runtime protocol entry.
3. `aearn/infra/executor/image-locks.json` contains a reviewed exact
   `repository@sha256:<64-hex>` lock that matches the catalog protocol,
   non-root identity, entrypoint, and limits.
4. The standalone executor has a recent compatible health heartbeat and has
   verified the pre-existing local image without pulling it.
5. A server-issued interactive execution proof, exact selected Skill/effect,
   current revision/lease, uncancelled run, and budget all pass inside the
   Child 02 effect transaction.

The checked-in lock registry is intentionally empty until real reviewed images
are published. This is the expected fail-closed condition: every runtime is
unavailable, no image tag/local id is substituted, and no host subprocess path
is used.

## Isolation Profile

The executor derives every launch from the reviewed lock. The job, proof, API
request, learner, and model cannot select images, commands, mounts, paths,
network settings, devices, or runtime flags. The profile requires an exact
image digest, fixed in-image entrypoint, no network, read-only root, explicit
`/work` and `/tmp` tmpfs, non-root UID/GID, dropped capabilities,
`no-new-privileges`, PID/CPU/memory/file/output/wall-clock limits, and cleanup.

The seven catalog entries are Python stdout, browser preview, TypeScript,
SQLite, Java, Go, and C#. Rust and C++ remain unsupported. Runtime Dockerfiles
are build definitions only and accept an explicit prebuilt toolchain base; they
are not production locks and do not enable execution.

## Lifecycle and Recovery

`tutor_execution_jobs` is the durable queue. The effect transaction creates one
job per effect/proof identity, then the executor claims `pending` work (or
safely reclaims an expired `claimed` lease that has no launch token) using a
short `FOR UPDATE SKIP LOCKED` transaction. It writes a launch token before the
external side effect. A replacement executor may adopt only an exact matching
labeled runtime. If it cannot prove the prior launch state, it records
`launch_uncertain` and never creates another runtime.

Cancellation is idempotent before claim, before launch, while waiting, and
after terminalization. Cleanup is in a finally path. A cleanup failure becomes
a safe failed result and quarantines executor health; it is not exposed as raw
runtime diagnostics.

## Observability and Safety

Internal durable job/audit facts contain only opaque IDs, runtime IDs, hashes,
state, counters, timestamps, safe codes, and capped learner-safe result text.
Any future learner/public projection excludes runtime IDs as well as submission
code, hidden tests, image reference/digest, command, mount, path, container
identifier, raw runtime error, and credentials.

For the transition boundary, see
[`../architecture/tutor-harness-transition.md`](../architecture/tutor-harness-transition.md).
