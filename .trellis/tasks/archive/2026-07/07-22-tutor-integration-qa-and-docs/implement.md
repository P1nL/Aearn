# Tutor Integration QA and Documentation Implementation Plan

## Preconditions and Safety Gate

Do not run `task.py start` until the user reviews and approves this file,
`design.md`, and `prd.md`. The parent remains planning-only; start only this
child after approval.

Before editing any implementation surface:

1. Run `python .\.trellis\scripts\get_context.py` and confirm this child is
   still the selected task and the working tree changes are understood.
2. Load `trellis-before-dev` and the relevant backend/frontend specs before
   touching that layer.
3. Use a disposable fixture user and deterministic provider/executor seams.
   Do not enable a real provider, proactive worker, or production-like learner
   data just to create release evidence.
4. Record the starting commit, dependency inventory, source/test caller audit,
   flag values, and test environment in the new release-readiness ledger.

## Ordered Execution

### 1. Freeze the integration baseline and target inventory

- Read the archived Children 00--07 artifacts, current transition contract,
  code, tests, schema, route registration, package manifests, and documentation
  index.
- Build a concrete matrix of each target contract, its test/smoke proof, its
  owning implementation file, and its final documentation owner.
- Snapshot all active legacy callers and package references before changing
  them. Start with:

  ```powershell
  rg -n --glob '*.py' 'app\.agents\.graphs|from langgraph|langgraph-checkpoint|graph_event_stream|from agents|import agents' aearn\services\api\app aearn\services\api\tests
  rg -n 'LANGGRAPH_ENABLED|langchain|langgraph|openai-agents' aearn\services\api\pyproject.toml aearn\services\api\uv.lock docs
  ```

- Do not infer that an import is removable until the source/test caller and
  public behavior it protects have been replaced and verified.

### 2. Close target-contract test gaps before any retirement

- Run existing focused test modules for provider gateway, run loop, durable
  replay/input merge, trace redaction, executor job store, scheduler,
  learner-state/memory/curation, public Tutor API/SSE, worker import, and
  harness cutover. Add narrowly scoped regression tests for any missing row
  from the design matrix.
- Use fake provider/clock/executor/worker seams. Assert unsafe behavior is
  rejected: cross-provider fallback, unbounded loop, stale input/effect,
  direct curation write, unregistered grounding, public trace leakage,
  sandbox-network fallback, proactive execution, and client-only cutover
  routing.
- Keep the PostgreSQL/bootstrap-sensitive suite sequential. If local database
  infrastructure is unavailable, record the precise blocker and leave the
  affected release gate unresolved; do not report a pass based on mocks alone.

### 3. Perform the cross-layer fixture-user integration proof

- Exercise the feature-enabled cutover flow with a disposable user: obtain a
  server summary, submit an exact confirmation, verify the deletion and
  preservation matrix, and confirm a verified receipt permits only fresh Tutor
  entry.
- Exercise the public Tutor route/API contract, durable input merge, ordered
  SSE cursor replay, error envelope, terminal ordering, activity/inbox,
  memory/plan controls, and diagnostics separation without a real model call.
- Verify the default Desktop bootstrap path reads the server cutover decision,
  cannot restore a legacy plan/session from local state, and renders the guided
  Tutor experience at the normal and narrow viewport sizes.
- Run the documented executor/worker health checks only in their disabled or
  controlled test posture; verify proactive execution cannot become a side
  channel to the learner-code executor.

### 4. Retire legacy runtime in small verified edits

This step begins only when Steps 2 and 3 are green.

- Re-run the source/test caller audit. Resolve every active production or
  test-only Graph/router/tool/SDK caller by migrating to the proven Tutor
  contract or deleting it with its obsolete test.
- Remove old Graph routes, Graph event streaming, specialist router/tools,
  legacy flags, obsolete fixtures, and package pins/lock entries only after
  their callers are gone. Keep deletion commits logically grouped so a failed
  removal has a narrow rollback point.
- Rerun import/build checks after each removal group. A dependency may be
  removed only when its package audit is clean; retain unrelated libraries if
  the target implementation still owns a legitimate use.
- Keep historical docs/tasks outside production/runtime search scope and label
  them explicitly. An empty current-runtime caller audit is the goal, not the
  deletion of migration evidence.

### 5. Consolidate source-of-truth documents from verified behavior

- Add `docs/architecture/tutor-harness-runtime.md` and update the README index
  to make it the current architecture entry point. Preserve the transition
  contract as a migration/cutover record.
- Update product flows, desktop interaction, API/SSE, database, environment,
  sandbox, worker/scheduler, acceptance, and release-readiness documents using
  the evidence ledger. Preserve still-valid first-release invariants.
- Move the LangGraph state-machine and SDK release-readiness documents to a
  dated archive only after matching code/package retirement is proven. Add
  redirect/status wording that makes their historical nature unambiguous.
- Validate every retained documentation link and ensure no active index says
  the Graph/SDK runtime is current.

### 6. Run the final sequential verification matrix

At minimum, run and record the results of:

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
pnpm --dir .\aearn dev:status
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-integration-qa-and-docs
git diff --check
```

Then run the designated fixture-user browser/Desktop smoke and the relevant
Docker/executor health commands documented by the current setup guide. Do not
substitute a Desktop build for backend, cutover, worker, container, or SSE
proof. Record exact command output summaries, failures, skipped checks, and
residual risk in `docs/qa/tutor-harness-release-readiness.md`.

### 7. Review before archive

- Compare the completed release ledger against every acceptance criterion in
  `prd.md` and every cross-child gate in the parent implementation plan.
- Verify physical retirement and documentation archive claims with a final
  scoped search plus a clean dependency manifest/lock diff.
- If any release gate is unresolved, leave the task `in_progress`, document
  the blocker, and return to the owning implementation boundary. Do not
  archive it as a documentation-only success.
- After all gates pass, perform the normal Trellis finish flow: source/spec
  review, final verification, intentional commit, and archive this child
  before considering parent closure.

## Planned Files and Risk Points

| Area | Likely files | Risk and rollback boundary |
| --- | --- | --- |
| Final runtime docs | `docs/README.md`, new `docs/architecture/tutor-harness-runtime.md`, transition/Graph documents | Never make an unproven target look current; archive rather than erase historical evidence. |
| Public contracts | `docs/product/user-flows.md`, `docs/product/frontend-interaction-spec.md`, `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md` | API/SSE/desktop docs must follow route/schema tests, not assumptions. |
| Operations and QA | `docs/setup/development-environment.md`, sandbox guide, acceptance plan, new release-readiness record | Do not publish real credentials, provider diagnostics, raw learner data, or false health claims. |
| Legacy retirement | `app/agents/graphs/`, legacy routes/streaming/runtime/tool files, tests, `pyproject.toml`, `uv.lock` | Delete only after source/test consumer audit and replacement proof; code rollback never restores deleted learner history. |
| Desktop verification | `aearn/apps/desktop/src/` only if a smoke exposes a real regression | Server decision remains authoritative; avoid restoring legacy bootstrap state. |

## Completion Evidence

The task is ready to archive only when the release-readiness document points to
reproducible proof for every required matrix row, the final caller/dependency
audit supports every physical removal, retained docs consistently name Tutor
as the current runtime, and the final verification commands are recorded with
their actual pass/fail/skipped state.