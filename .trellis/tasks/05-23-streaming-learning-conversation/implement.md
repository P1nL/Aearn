# Implementation Plan

## Preconditions

- Keep the task in `planning` until the new session explicitly starts it.
- Before code edits, read:
  - `.trellis/spec/backend/index.md`
  - `.trellis/spec/frontend/index.md`
  - `docs/architecture/api-contract.md`
  - `docs/product/frontend-interaction-spec.md`
  - `docs/setup/development-environment.md`
  - `docs/qa/acceptance-test-plan.md`

## Backend Checklist

1. Inspect existing route patterns in `aearn/services/api/app/routes/learning_sessions.py`, especially JSON/SSE split logic for `run` and `submit`.
2. Inspect `aearn/services/api/app/services/sse.py` and reuse the existing frame helpers.
3. Inspect `aearn/services/api/app/services/llm_client.py`; update `complete_text_stream` so provider-unsupported `temperature` is not sent by default.
4. Add request/response models for learning-session messages.
5. Add a service that:
   - validates the learning session exists;
   - builds safe prompt context from current session/exercise/attempt data;
   - streams deltas from `OpenAICompatibleClient.complete_text_stream`;
   - returns deterministic fallback on disabled/incomplete/failed LLM configuration;
   - never includes secrets or hidden test details.
6. Add `POST /api/learning-sessions/{session_id}/messages` with JSON and SSE behavior.
7. Add focused backend tests for JSON, SSE, validation error, fallback, and provider payload compatibility.

## Frontend Checklist

1. Inspect `aearn/apps/desktop/src/App.tsx` composer handling. Replace canned local agent message for `home` route active sessions with real streaming behavior.
2. Inspect `aearn/apps/desktop/src/hooks/useSSE.ts`; reuse it where practical, or wrap it with a feature-specific hook if component state becomes clearer.
3. Add typed API constants/helpers in `aearn/apps/desktop/src/api.ts`.
4. Extend `ConversationMessage` if needed to represent streaming/error status.
5. Update `ThreadMessages` or adjacent component code to render progressive assistant text and incomplete/error states.
6. Preserve review-route current local behavior unless explicitly brought into scope.
7. Ensure duplicate send is disabled while stream is active.
8. Ensure no active session case is explicit and does not call the backend.

## Verification Commands

Run these before claiming the task is complete:

```powershell
uv --directory .\aearn\services\api run python -m pytest
pnpm --dir .\aearn desktop:check
```

If running a focused subset first:

```powershell
uv --directory .\aearn\services\api run python -m pytest .\aearn\services\api\tests -k "llm or stream or message or learning_session"
```

Manual smoke after tests:

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
uv --directory .\aearn\services\api run python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
pnpm --dir .\aearn desktop:dev
```

Then verify in browser:

- onboarding creates/loads user and plan;
- learning session starts;
- composer sends a follow-up question;
- assistant bubble updates incrementally;
- stream ends cleanly;
- run, explain-error, and submit still work.

## Rollback Points

- Backend route/service additions should be isolated to learning-session message files and `llm_client.py`.
- Frontend changes should be isolated to `App.tsx`, `api.ts`, conversation message types/components, and optional stream hook wrapper.
- If streaming UI destabilizes the main workspace, revert frontend wiring and keep backend tests as the first completed slice.
