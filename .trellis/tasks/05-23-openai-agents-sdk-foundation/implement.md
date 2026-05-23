# Implementation Plan

## Status

This task is in `in_progress`. The user selected `application-on-SDK`: build the Aearn learning Agent application on top of OpenAI Agents SDK as an upstream dependency, without forking SDK internals. The task was started before implementation.

## Preconditions

Before implementation:

1. Confirm the task is still current and status remains `planning` until implementation is explicitly approved.
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
3. Use the chosen foundation mode: application-on-SDK.
4. Use learning conversation messages as the first slice.
5. Document provider compatibility:
   - OpenAI Responses;
   - Responses-compatible proxy;
   - Chat-Completions-only OpenAI-compatible provider;
   - structured-output gaps.
6. Keep note assist as a follow-up candidate, not part of the first spike.

## Phase 2: Application-On-SDK First Slice

Chosen first implementation:

1. Add `openai-agents` to `aearn/services/api/pyproject.toml`.
2. Re-lock with `uv --directory .\aearn\services\api lock`.
3. Add Aearn-owned SDK modules, for example `app/agents/sdk_runtime.py` and `app/agents/learning_conversation_agent.py`.
4. Implement a learning conversation Agent using SDK `Agent` / `Runner` while satisfying the existing `TextCompletionClient`-style boundary.
5. Normalize SDK exceptions into existing Aearn LLM exceptions.
6. Keep deterministic fallback behavior in the caller.
7. Add unit tests with fake SDK runner/model behavior, not real network calls.
8. Wire the SDK-backed Agent only into learning conversation message generation.
9. Leave note assist, final evaluation, review, and FSRS paths on the current implementation.
10. If this first slice is stable, create follow-up tasks for note assist Agent and tool-backed context loading.

## Phase 3: Optional Tool Integration

Only after the simple adapter works:

1. Wrap safe read-only Aearn functions as SDK tools:
   - load learning context;
   - load latest visible attempt summary;
   - load note context.
2. Keep write operations outside SDK tools unless explicitly designed.
3. Add guardrails for hidden-test leakage and direct-answer behavior.

## Implementation Notes

2026-05-23 first slice:

1. Added `openai-agents==0.17.3` to `aearn/services/api/pyproject.toml` and refreshed `uv.lock`.
2. Added Aearn-owned SDK modules under `aearn/services/api/app/agents/`.
3. Wired `POST /api/learning-sessions/{session_id}/messages` through `AgentsSDKLearningConversationClient` when model settings are configured.
4. Kept deterministic fallback, idempotency storage, SSE event framing, Aearn DB ownership, and current route contracts in `app/services/learning_conversation.py` and `app/routes/learning_sessions.py`.
5. Left final evaluation, review state, FSRS scheduling, note assist, and runner semantics outside SDK ownership.
6. Added model-key-free tests using a fake SDK runner; no real model call is required for local verification.

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

- User approves starting implementation from these updated planning artifacts.
- Existing `05-23-streaming-learning-conversation` overlap is resolved or explicitly sequenced.
- `task.py start` has been run for this task.
