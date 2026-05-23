# Implementation Plan

## Status

This task is in `planning`. Do not implement until the user approves the chosen foundation strategy and the task is started with `task.py start`.

## Preconditions

Before implementation:

1. Finish the open product/architecture decision in `prd.md`.
2. Re-check current worktree because `05-23-streaming-learning-conversation` has in-progress changes touching the same route and LLM files.
3. Read the relevant specs:
   - `.trellis/spec/backend/index.md`
   - `.trellis/spec/frontend/index.md`
   - `docs/architecture/api-contract.md`
   - `docs/architecture/langgraph-state-machine.md`
   - `docs/architecture/code-completion-evaluation-spec.md`
   - `docs/qa/acceptance-test-plan.md`
   - `docs/setup/development-environment.md`
4. Verify upstream SDK package metadata and docs again if dependency versions or provider assumptions matter.

## Phase 1: Research And Decision

1. Confirm package install impact with a non-mutating resolver method, or document why current `uv` cannot dry-run `add`.
2. Compare current `OpenAICompatibleClient` behavior with SDK model provider options.
3. Decide whether the first slice is:
   - learning conversation messages only;
   - note assist only;
   - both behind one shared adapter.
4. Document provider compatibility:
   - OpenAI Responses;
   - Responses-compatible proxy;
   - Chat-Completions-only OpenAI-compatible provider;
   - structured-output gaps.
5. Update `design.md` with the final decision.

## Phase 2: Adapter-First Spike

Recommended first implementation:

1. Add `openai-agents` to `aearn/services/api/pyproject.toml`.
2. Re-lock with `uv --directory .\aearn\services\api lock`.
3. Add `app/services/agents_sdk_client.py`.
4. Implement a SDK-backed class that satisfies `TextCompletionClient`.
5. Normalize SDK exceptions into existing Aearn LLM exceptions.
6. Keep deterministic fallback behavior in the caller.
7. Add unit tests with fake SDK runner/model behavior, not real network calls.
8. Wire the adapter only into the selected spike path.

## Phase 3: Optional Tool Integration

Only after the simple adapter works:

1. Wrap safe read-only Aearn functions as SDK tools:
   - load learning context;
   - load latest visible attempt summary;
   - load note context.
2. Keep write operations outside SDK tools unless explicitly designed.
3. Add guardrails for hidden-test leakage and direct-answer behavior.

## Validation Commands

Backend focused checks:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
```

Full backend gate when ready:

```powershell
uv --directory .\aearn\services\api run python -m pytest
```

Frontend gate if the spike touches desktop UI:

```powershell
pnpm --dir .\aearn desktop:check
```

Dependency verification:

```powershell
uv --directory .\aearn\services\api lock --check
```

Manual smoke, if the endpoint is wired through desktop:

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
uv --directory .\aearn\services\api run python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
pnpm --dir .\aearn desktop:dev
```

Smoke path:

- onboarding;
- start learning session;
- send composer message;
- verify streaming assistant response;
- run visible tests;
- explain error;
- submit.

## Risky Files And Rollback Points

- `aearn/services/api/pyproject.toml` and `uv.lock`: dependency changes.
- `aearn/services/api/app/services/llm_client.py`: preserve current OpenAI-compatible behavior.
- `aearn/services/api/app/services/learning_conversation.py`: likely first adapter injection point.
- `aearn/services/api/app/routes/learning_sessions.py`: overlaps with current in-progress streaming task.
- `aearn/apps/desktop/src/*`: avoid frontend work unless this task explicitly includes UI wiring.

Rollback:

- Remove `agents_sdk_client.py`.
- Revert dependency addition.
- Keep route/service behavior using current `OpenAICompatibleClient`.
- Retain tests for provider fallback if they remain useful.

## Do Not Start Until

- User confirms the foundation strategy.
- Existing `05-23-streaming-learning-conversation` overlap is resolved or explicitly sequenced.
- `task.py start` has been run for this task.
