# Child 00 Implementation Plan: Tutor Harness Contracts and Run Loop

## Preconditions

- Parent planning was approved on 2026-07-26; the parent remains
  planning-only and is never started as an implementation task.
- This child is still `planning`. Do not run this child's `task.py start` or
  edit product runtime code until the user approves the latest child summary.
- Work only in `aearn/services/api/`, the declared transition/setup documents,
  Child 00 artifacts, and focused tests. Preserve all unrelated dirty changes.
- No live model calls, secrets, database migrations, routes, or desktop builds
  are required for this child.

## Ordered Work

### 1. Publish the narrow transition contract

1. Add `docs/architecture/tutor-harness-transition.md` with authority labels
   (`legacy baseline`, `target contract`, `adapter window`, `retired`).
2. Add a narrow index row in `docs/README.md` without changing its existing
   user-edited historical-visual-reference row.
3. Document `TUTOR_HARNESS_ENABLED=false` in
   `docs/setup/development-environment.md`, including that it exposes no route
   or UI in Child 00.

**Gate:** Child 00's run/input/context/provider/checkpoint/terminal contract is
written before implementation code depends on it.

### 2. Extract shared redaction safely

1. Add `app/agents/runtime/redaction.py` with the generic recursive redaction
   primitives currently embedded in `graph_runtime_contracts.py`.
2. Convert the legacy Graph module to import/re-export those helpers without
   changing public contract behavior.
3. Preserve existing Graph stream and Graph contract tests.

**Rollback point:** Restore the prior in-module implementation; no data or API
behavior has changed.

### 3. Add feature-off contracts and ports

1. Extend `app/core/config.py` with `tutor_harness_enabled`, default false.
2. Create `app/agents/harness/__init__.py`, `contracts.py`, and
   `context_builder.py`.
3. Create `app/services/tutor/__init__.py` and `ports.py` with protocols and
   deterministic fakes/default-deny implementations.
4. Keep all run, decision, policy, context, checkpoint, compaction, provider,
   capability, and effect payloads typed, bounded, and redacted.

**Gate:** No Harness module imports routes, repositories, Graph modules, or
LangGraph APIs.

### 4. Implement context and provider boundaries

1. Implement deterministic budget selection, source metadata hashing, safe
   message sanitization, and high-water compaction-request candidates.
2. Implement `PrimaryTutorProviderGateway` over `OpenAICompatibleClient`.
3. Validate strict decision output and use existing output guardrails.
4. Map all selected-provider configuration/call/invalid-output failures to a
   redacted `MODEL_UNAVAILABLE` terminal result; do not add fallback routing.

### 5. Implement finite loop behavior

1. Add `run_loop.py` with lease acquisition, fixed budgets, revision reload,
   safe checkpoints, default-deny capability/effect ports, terminal handling,
   and compaction publisher calls.
2. Verify stale effects are rejected before a committer is invoked.
3. Verify no operation uses `learning_stage`, `route_message`, Graph checkpoint
   types, or persisted legacy session state.

### 6. Add focused tests

- `tests/test_tutor_context_builder.py`
  - deterministic selection/order/budget;
  - message and evidence redaction;
  - no full-history/checkpoint raw content;
  - high-water compaction candidate behavior.
- `tests/test_tutor_provider_gateway.py`
  - DeepSeek and OpenAI-compatible fake client paths;
  - strict envelope and guardrail rejection;
  - primary-only error behavior and redaction;
  - no live provider requirement.
- `tests/test_tutor_run_loop.py`
  - zero/one/multiple bounded iterations;
  - lease/budget/cancellation terminal outcomes;
  - revision reload and stale effect rejection;
  - safe checkpoint/compaction trigger behavior;
  - feature-disabled service behavior.
- Update the existing Graph contract test only for the shared redaction
  extraction compatibility regression.

## Validation Commands

Run from `E:\codee\Aearn`:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_graph_runtime_contracts.py tests/test_llm_integration.py -q
uv --directory .\aearn\services\api run ruff check app tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py tests/test_graph_runtime_contracts.py
uv --directory .\aearn\services\api run mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-harness-contracts-and-run-loop
```

No database bootstrap, live provider call, desktop build, deployment, reset, or
parent `task.py start` belongs to the initial Child 00 implementation loop.

## Risk and Rollback Boundaries

| Risk | Prevention | Rollback |
| --- | --- | --- |
| Legacy Graph dependency leaks into Harness | Import-boundary test and runtime-level redaction extraction | Revert isolated Child 00 modules; legacy path remains unchanged. |
| Hidden/provider data appears in context/diagnostics | Reuse sanitization/redaction, source-only checkpoint metadata, fake leakage tests | Remove feature-off code; no durable Harness records exist. |
| Provider fallback or raw error leak | Single settings-selected gateway, typed error mapping, fake transport tests | Revert adapter only; existing LLM client continues unchanged. |
| Concurrent input commits stale effect | Revision reload before every unsafe boundary, fake compare/reject tests | No database state is written by Child 00. |
| Scope expands into persistence/API/UI | Explicit protocol-only boundary and path allowlist | Stop before Child 02/06 work; no migration required. |

## Ready-to-Start Checklist

- [ ] Child PRD has passed final convergence and has no blocking open question.
- [ ] `design.md` and this file have been reviewed against parent target and
  current repository evidence.
- [ ] `implement.jsonl` and `check.jsonl` contain real, validated entries.
- [ ] The user has explicitly approved the latest Child 00 planning summary.
- [ ] No parent task is started; the child, not the parent, will own the later
  implementation state.
