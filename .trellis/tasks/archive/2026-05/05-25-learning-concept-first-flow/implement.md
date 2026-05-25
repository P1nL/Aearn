# Implementation Plan: Concept-first learning workspace

## Preconditions

- Obtain user approval for `prd.md` and `design.md`, then run `task.py start` before editing runtime code.
- In Phase 2, load `trellis-before-dev` and read the backend, frontend, and cross-layer specs for touched files.
- Keep existing unrelated dirty changes in `App.tsx`, `LearningWorkspacePage.tsx`, `styles.css`, `sdk_runtime.py`, and `test_llm_integration.py` isolated and preserved.

## Ordered Implementation Checklist

1. Update source-of-truth docs for the approved concept-first flow, stage names, practice unlock trigger, history-reference boundary, and API/state-machine contract.
2. Add focused backend failing tests for concept-stage start, nullable exercise contract, stage resume, early practice, Feynman unlock/failure, and learning-history filtering.
3. Extend database/bootstrap schema with curated lesson outline fields, compact learn-session stage state, and `learning_messages` persistence plus indexes.
4. Update backend models and repository/service behavior so new learning sessions begin with a persisted concept introduction and do not expose an exercise before unlock.
5. Refactor learning conversation generation to use lesson outline plus compact progress, persist AI/user turns, keep concept-stage prompts free of exercise content, and transition stages deterministically.
6. Add the learn-only history read API and tool-call/session-patch output required for `show_learning_history` and `show_code_exercise`.
7. Update desktop TypeScript contracts/API validators for nullable exercise, learning stage state, history payloads, and learning tool calls.
8. Reuse/generalize assistant-ui tool plumbing, add exercise/history tool UIs, and make `LearningWorkspacePage` render practice from unlock tool/state rather than entry-time `session.exercise`.
9. Preserve existing run/submit/hint/explain-error/check-explanation behavior inside the generated exercise card and verify early-practice notice content.
10. Run targeted backend and desktop checks, perform browser smoke on the local learning flow, and review changed paths against the task scope before closeout.

## Expected Touch Points

- Backend: `aearn/services/api/app/db/schema.sql`, bootstrap/fixture data, `app/models/learning_sessions.py`, `app/routes/learning_sessions.py`, `app/services/learning_session_repository.py`, `app/services/learning_conversation.py`, and targeted tests.
- Desktop: `aearn/apps/desktop/src/types.ts`, `api.ts`, assistant-ui tool components/hooks/store plumbing, and `pages/LearningWorkspacePage.tsx`.
- Docs: `docs/product/user-flows.md`, `docs/product/frontend-interaction-spec.md`, `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md`, and `docs/architecture/langgraph-state-machine.md`.

## Verification Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests\test_learning_sessions_m3.py tests\test_llm_integration.py tests\test_dashboard_resume_m6.py
pnpm --dir .\aearn desktop:check
pnpm --dir .\aearn desktop:dev
```

- Backend pytest requires the configured local PostgreSQL prerequisites when tests hit persistence.
- Browser smoke should verify fresh concept entry, no initial practice card, normal unlock, early-practice notice, and history card filtering/grouping.

## Review Gates And Rollback Points

- Gate 1: Do not activate the task until the user approves the planning artifacts.
- Gate 2: Do not merge the frontend rendering switch until backend start/resume tests establish the nullable exercise and legacy-session fallback contract.
- Gate 3: Do not claim completion until backend tests, `desktop:check`, and browser smoke pass or exact blockers are recorded.
- Rollback: the generated exercise rendering switch can be reverted independently if backend stage/history persistence is valid but tool UI integration fails.
