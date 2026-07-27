# Container Sandbox Executor Implementation Plan

## Preconditions Before Start

- Only `.trellis/tasks/07-22-container-sandbox-executor` may enter
  `in_progress` after the user approves this final plan. The parent remains
  `planning` and is not the implementation target.
- Re-read this PRD/design, the curated manifests, the parent transition
  contract, Child 02 persistence/effect seam, and current API/executor package
  configuration immediately before editing.
- Recheck the working tree. It currently contains extensive unrelated Trellis
  upgrade/tooling/docs/output changes. Do not reset, restore, clean, broad-stage,
  or force-stage them. Limit edits to intentional Child 03 code/tests/docs and
  its own task artifacts.
- Do not read or modify `aearn/.env`. Add only non-secret defaults/comments to
  `.env.example` when configuration is required.
- Keep `TUTOR_HARNESS_ENABLED=false` and introduce a separate
  `TUTOR_EXECUTOR_ENABLED=false` default. Do not reuse
  `REAL_EXECUTION_ENABLED`, alter legacy runner paths, or wire public traffic.
- PostgreSQL/bootstrap-heavy tests must run serially. Real Docker conformance
  runs only with an explicitly enabled local conformance gate and real reviewed
  digest locks; missing Docker/locks is a fail-closed availability condition,
  never permission to use host subprocesses or tags.

## Ordered Implementation Checklist

### 1. Freeze Boundaries and Shared Pure Contracts

- Inspect existing Harness contracts, catalog descriptors, policy resolver,
  Child 02 repository/effect handler behavior, runner result shape, redaction,
  schema bootstrap, worker layout, and development script immediately before
  modifying them.
- Create the minimal Python shared package under `aearn/packages/shared/` for
  pure versioned execution contracts only: intent proof, job/claim, image lock,
  sandbox protocol, safe result, registry validation, and pure result adapter
  inputs. Configure API and executor package dependencies to use it without
  giving the API any Docker dependency.
- Define closed Pydantic/dataclass schemas with `extra="forbid"`, field bounds,
  stable identifiers, hash/digest validation, and no raw-code/image-command/
  mount/path/network fields. Search first for existing hash/redaction/payload
  validators and reuse them rather than duplicating deny lists.
- Add a Git-owned runtime catalog for the seven confirmed runtime IDs and a
  separately validated image-lock registry. A lock must be a reviewed real
  `repository@sha256:<64-hex>` value; absence means disabled, not tag or
  placeholder fallback.

**Risk / rollback:** Shared contracts are imported by two services. Keep them
pure and narrow so rollback removes only uncomposed imports; do not create a
shared Docker/DB/config abstraction or move legacy runner behavior.

### 2. Add Additive Execution Schema and API-Side Job Store

- Append an idempotent `tutor_execution_*` schema delta to
  `aearn/services/api/app/db/schema.sql` for execution intents, jobs, attempts,
  executor health, foreign keys to Child 02 effects/runs/conversations, scoped
  constraints, lifecycle indexes, and update triggers where needed.
- Extend `tests/test_db_bootstrap.py` to assert repeatable bootstrap, the new
  tables/constraints/indexes, and key uniqueness/scoping invariants. Run this
  suite serially.
- Implement a narrow API-side execution persistence module under
  `app/services/tutor/` that can issue/validate a trusted proof through an
  internal port, create/replay jobs inside the caller-owned Child 02
  transaction, read safe availability/result facts, request cancellation, and
  perform no Docker operation.
- Make job identity one-to-one with the effect record and proof. Persist only
  source/exercise references, runtime id, lock fingerprint, hashes/counters,
  safe status, and bounded result material. Do not write code, tests, Docker
  strings, command lines, paths, or container ids into any Tutor safe surface.

**Risk / rollback:** Bootstrap applies the full schema. Keep DDL additive and
idempotent; no destructive schema rollback or legacy data mutation. Do not
allow a JSONB column to bypass the existing safe-projection boundary.

### 3. Implement the Dedicated Executor Service and At-Most-Once Lifecycle

- Add `aearn/services/executor/` with its own `pyproject.toml`, standalone
  module entrypoint, executor-specific settings, PostgreSQL connection/job
  store, health loop, and the only pinned Docker SDK dependency. API and worker
  dependency manifests must remain free of Docker SDK/client dependencies.
- Implement job claim with short transactions and `FOR UPDATE SKIP LOCKED`.
  Revalidate run/intent cancellation, registry fingerprint, exact image lock,
  and health before launch reservation.
- Implement the deterministic `pending -> claimed -> launch_reserved ->
  running -> terminal` lifecycle. Allocate one launch token/name/label before
  Docker creation; replacement workers adopt/inspect only the matching
  container. On ambiguity, record `launch_uncertain` and do not relaunch.
- Implement cancellation polling, wall-clock/output watchdogs, bounded status
  transitions, cleanup in a `finally` path, internal safe attempts/audit, and
  heartbeat/quarantine behavior. Docker client errors map to safe diagnostic
  codes; raw error bodies never enter DB public/trace/export paths.
- Add a narrow trusted input resolver in the executor to load raw source and
  hidden exercise facts only from references after a valid claim. Ensure raw
  input stays transient and is never logged or persisted by the executor.

**Risk / rollback:** A Docker launch is external to PostgreSQL. Preserve
at-most-once launch behavior rather than broad automatic retries. A cleanup or
post-reservation uncertainty fails closed and can be remediated manually;
legacy runners are never a fallback.

### 4. Build the Common Docker Profile and Seven Runtime Harnesses

- Create one central immutable launch-spec builder in the executor. It must
  enforce exact digest image, fixed entrypoint/arguments, no network/mounts/
  devices/privilege, read-only root, explicit tmpfs, non-root identity,
  capability drop, no-new-privileges, CPU/memory/PID/file/output/wall-clock
  limits, and deterministic labels/name. Reject all caller overrides.
- Add Dockerfile/harness source and protocol tests for the common `SandboxInputV1`
  / `SandboxResultV1` envelope. Image builds may use local build tags only as
  build artifacts; job registry/launch lookup may never use those tags.
- Implement the seven constrained runtime harness entries in this order:
  Python; browser preview (JS and HTML/CSS); TypeScript; SQLite; Java; Go; C#.
  Reuse current exercise/test semantics through pure protocol adapters where
  possible, but do not import a host-subprocess runner into the executor.
- Enforce each runtime's prohibitions: no package/install downloads, browser
  navigation/download/extensions, SQL app-database/DDL/DML/attach access, or
  arbitrary multi-file/project toolchains. Keep Rust/C++ absent from the
  catalog/locks/protocol dispatch.

**Risk / rollback:** Do not weaken a shared isolation profile for a difficult
runtime. A runtime whose real lock/image/protocol is unavailable stays
unavailable while the other runtime definitions remain independently bounded.

### 5. Wire `runner.execute` Through Catalog, Policy, and Child 02 Effect CAS

- Add the `runner.execute` effect descriptor, its bounded proposal reference
  schema, and a reviewed exact Skill bundle/manifest/evals that explicitly
  permits it. Existing Skills remain default-deny.
- Extend catalog/policy validation so only a server-issued opaque proof can be
  referenced; derive runtime/image selection server-side from trusted exercise
  state. Reject model/learner image, tag, command, path, mount, network,
  Docker, URL, shell, SQL, or raw-code fields before the handler.
- Register the effect handler with `PostgresTutorRepository` only in a
  feature-disabled target composition. Within Child 02's transaction it must
  verify exact catalog evidence, interactive origin, user/conversation/run/
  message/exercise scope, revision, active lease, cancellation, budgets,
  executor health, and lock availability, then create/replay the one job.
- Extend safe effect/result/event vocabulary only as needed for an internal
  job receipt. Do not add a route, SSE delivery event, Desktop card, legacy
  runner call, or public status contract.

**Risk / rollback:** A registered handler alone is not authorization. Preserve
Child 02 default-deny behavior for missing/undeclared effects and test that
stale/cancelled/unhealthy paths make no job or Docker call.

### 6. Add Health and Explicit Local Development Wiring

- Add executor-specific non-secret settings/examples and a database heartbeat
  contract. API availability reads the heartbeat but never talks to Docker.
- Add an explicit, separately invoked development command/process tracking for
  the executor. If `start-dev.ps1` is extended, track an `executorPid` only
  with a strict expected command pattern and do not start it by default. Keep
  Docker daemon access out of API/worker Compose/service configuration.
- Add a narrow runtime/operations document and update the Harness transition
  contract with job ownership, intent proof, at-most-once launch, lock/health,
  redaction, Child 04 queue-policy boundary, and Child 06 public-adapter
  boundary. Update development setup only for the explicit executor workflow.

**Risk / rollback:** Development wiring must not silently grant a regular
`pnpm dev` API/worker process Docker access. Disable/remove only the separate
executor composition path when rolling back before activation.

### 7. Build the Test Matrix and Perform Independent Review

- Add pure unit tests for contracts, lock/catalog validation, policy/intent
  proof rejection, result conversion/redaction, and static Docker launch-spec
  construction.
- Add serial PostgreSQL tests for effect-to-job atomicity/replay, scope and
  proof consumption, `SKIP LOCKED` claim behavior, lease/cancellation races,
  terminal replay, safe audit/result storage, health gating, and no second
  launch after uncertain reservation.
- Add static forbidden-import/config tests proving only executor owns Docker
  client/socket/`DOCKER_HOST`, and Harness/API/worker/legacy runner paths have
  no host fallback.
- Add opt-in Docker conformance tests for common profile, cleanup, output,
  timeout, no-network behavior, and all seven runtime protocols. A missing
  daemon or real reviewed lock must exercise unavailable/disabled behavior,
  not skip the fail-closed unit assertions.
- Inspect the final diff and docs. Verify that no raw code/hidden test/container
  path/error/digest appears in learner-safe output, trace/event/export, logs,
  or staged files. Do not stage unrelated pre-existing worktree changes.

## Required Validation

Run focused tests first. Database/bootstrap-heavy commands must run one after
another, not in parallel. Exact new test module names may follow the existing
naming convention, but the coverage families below are mandatory.

```powershell
# API/shared contract and effect/job tests
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_execution_contracts.py tests/test_tutor_execution_effect.py tests/test_tutor_execution_repository.py tests/test_tutor_execution_redaction.py tests/test_tutor_executor_health.py -q

# Serial schema/bootstrap test
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py -q

# Existing Harness regression suite
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_effect_commit.py tests/test_tutor_run_repository.py tests/test_tutor_run_loop.py tests/test_tutor_skill_catalog.py tests/test_tutor_capability_gateway.py tests/test_tutor_trace_redaction.py -q

# Executor pure/unit tests
uv --directory .\aearn\services\executor run python -m pytest tests -q

# Lint and types for both Python services
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\executor run ruff check aearn_executor tests
uv --directory .\aearn\services\executor run python -m mypy aearn_executor --no-incremental

# Infrastructure and default feature-off behavior
docker compose -f .\aearn\infra\docker-compose.yml config --quiet
pnpm --dir .\aearn dev:status

# Opt-in real Docker conformance only after real immutable locks are supplied
$env:AEARN_EXECUTOR_CONFORMANCE = '1'
uv --directory .\aearn\services\executor run python -m pytest tests/test_executor_docker_conformance.py -q
Remove-Item Env:AEARN_EXECUTOR_CONFORMANCE -ErrorAction SilentlyContinue

# Task and diff integrity
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-container-sandbox-executor
git diff --check
```

If a local Docker daemon or valid lock is unavailable, record the exact blocker
and verify the corresponding disabled/unavailable path. Do not substitute a
legacy host runner, a mutable tag, or a fake production lock.

## Review Gates

Before implementation dispatch:

- Confirm this task has current `prd.md`, `design.md`, `implement.md`, and
  real curated entries in both manifests; run task validation and present this
  plan for a fresh user approval.
- Confirm Child 01/02 commits and the transition contract still expose the
  exact catalog/effect/transaction seam described here. If they changed,
  return to planning rather than guessing a compatibility adapter.
- Confirm the seven-runtime scope, Rust/C++ exclusion, no-public-traffic
  boundary, feature-off posture, and real-lock prerequisite remain unchanged.

Before the work commit:

- Confirm API/Harness/worker/legacy runner paths have no Docker package,
  socket, CLI, `DOCKER_HOST`, or fallback call; only executor has it.
- Confirm every job has a trusted interactive proof and one effect/intent
  identity, while every uncertain/duplicate/retry/cancel path cannot make a
  second container.
- Confirm runtime locks are exact reviewed digests, no job pulls images, all
  seven harnesses use the common strict launch profile, and Rust/C++ remain
  unavailable.
- Confirm raw code, hidden tests, Docker diagnostics, identifiers, paths,
  commands, and image details stay out of all safe/public projections and
  normal logs.
- Run the full validation sequence, inspect `git diff --check`, stage only
  intentional Child 03 work, and do not push/deploy without a separate user
  request.

## Rollback Summary

- **Before feature activation:** keep `TUTOR_EXECUTOR_ENABLED=false` or remove
  only the isolated executor composition/effect registration. Legacy product
  behavior is untouched.
- **Schema/data:** retain additive `tutor_execution_*` rows; do not drop state
  or alter legacy learner data as a rollback shortcut.
- **Runtime issue:** mark a runtime unavailable/quarantined via health/lock
  policy; do not use a tag, host runner, or automatic ambiguous relaunch.
- **Operational ambiguity:** terminalize `launch_uncertain` with safe evidence
  and require controlled remediation. At-most-once container launch is more
  important than automatic retry.
