# New Session Handoff

## Task

Task directory:

```text
.trellis/tasks/05-23-streaming-learning-conversation
```

Status: `planning`

User intent: implement the missing model-backed streaming conversation experience, but in a new session rather than the current one.

## Current Diagnosis

The MVP is runnable with backend and frontend, and the model API key can be injected into the backend process. However, the app does not yet implement true streaming conversation.

Current behavior:

- `App.tsx` composer submit appends the user message and then appends a canned local agent message.
- `LearningWorkspacePage` renders `messages` through `ThreadMessages`.
- `useSSE.ts` exists and can parse POST SSE streams.
- Backend has SSE helpers and LLM streaming primitives.
- Backend API contract already specifies `POST /api/learning-sessions/{session_id}/messages`, but the route is not wired as the learning composer path.

## Important Files To Inspect First

- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`
- `aearn/apps/desktop/src/components/ThreadMessages.tsx`
- `aearn/apps/desktop/src/hooks/useSSE.ts`
- `aearn/apps/desktop/src/api.ts`
- `aearn/services/api/app/routes/learning_sessions.py`
- `aearn/services/api/app/services/sse.py`
- `aearn/services/api/app/services/llm_client.py`
- `aearn/services/api/app/services/llm_explain_error.py`
- `aearn/services/api/app/db/schema.sql`

## Product Scope Recommendation

Implement the narrow MVP:

- active learning workspace only;
- existing bottom composer;
- streaming assistant answer from model;
- deterministic fallback when model is unavailable;
- no WebSocket;
- no global chatbot;
- no durable full chat history unless required by implementation.

Leave review-page chat for a later task unless the user explicitly expands scope.

## Model / Provider Notes

Do not write the real API key to tracked files.

The previous manual startup used:

```env
LLM_TYPE=openai
OPENAI_BASE_URL=https://api.lattecode.net
OPENAI_MODEL=gpt-5.4-mini
LLM_TIMEOUT_SECONDS=60
```

The key was read from local CCR config and injected only into the backend process. Do not print or commit it.

Provider compatibility issue to verify early:

- LatteCode Responses API requires streaming.
- Provider may reject unsupported `temperature`.
- `complete_text_stream` currently sends `temperature`; fix/test if needed.

## Recommended First Commands

```powershell
python .\.trellis\scripts\get_context.py
python .\.trellis\scripts\task.py list
Get-Content .\.trellis\tasks\05-23-streaming-learning-conversation\prd.md
Get-Content .\.trellis\tasks\05-23-streaming-learning-conversation\design.md
Get-Content .\.trellis\tasks\05-23-streaming-learning-conversation\implement.md
```

Before implementation:

```powershell
python .\.trellis\scripts\task.py start .\.trellis\tasks\05-23-streaming-learning-conversation
```

## Definition Of Done

- Backend route supports JSON and SSE.
- Frontend composer streams a real assistant answer into one incrementally updated bubble.
- Duplicate sends are blocked during streaming.
- Stream failure is visibly recoverable.
- Default tests use mocks, not a real key.
- `uv --directory .\aearn\services\api run python -m pytest` passes.
- `pnpm --dir .\aearn desktop:check` passes.
