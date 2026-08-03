# Implementation Plan: Conversation TurnRun、公开历史与 Desktop 导航

## Start Gate and Scope Discipline

- 仅在 `08-02-deepseek-responses-decision-contract` 已 review/archived、其 `conversation_title` 与 `continuation_kind` typed contract 可用后启动本 child。
- 开始前逐个检查现有未提交修改，特别是 `persistence.py`、`public_api.py`、`TutorWorkspacePage.tsx`、`useTutorSSE.ts`、`styles.css` 和相关 tests/docs；保留已正确的诊断或局部实现，不 reset、不覆盖用户修改。
- 加载 `trellis-before-dev`，并阅读 backend/frontend index 列出的相关规范与 source-of-truth docs。

## Ordered Implementation

1. **Freeze the child-1 contract boundary**
   - Import/use typed `conversation_title` and `continuation_kind`; do not add free-form JSON fields or duplicate canonical decision parsing.
   - Update focused existing tests that construct `TutorDecision`/provider result fixtures.

2. **Additive schema and repository primitives**
   - Add conversation title/last public activity, run supersede/continuation fields, foreground index, public-process and process-step tables/checks/indexes.
   - Add shared repository helpers for foreground predicate, title normalization/write-once, safe process step mapping, server elapsed calculation and cursor encode/decode.
   - Verify bootstrap remains repeatable and test cleanup follows child-to-root foreign-key order.

3. **Atomic first turn and normal turn mutation**
   - Add first-turn API/model/public service/repository transaction and idempotency response.
   - Replace normal conversation-input merge behavior with fresh-run creation and foreground supersede in one transaction.
   - Leave old empty-conversation endpoint only as intentionally bounded compatibility behavior; Desktop must not call it for a draft.
   - Limit run-input to an explicit persisted continuation; normal chat submits always use conversation turn.

4. **Run-loop and lifecycle race guards**
   - Add cancellation/supersede refresh after provider return and before decision/capability/effect/public terminal boundaries.
   - Make terminal persistence recheck locked foreground state before Tutor message/title/process completion.
   - On supersede, preserve only safe cancellation/process projection and prevent all stale public/effect/capability writes.

5. **Safe projections, history and list reads**
   - Implement repository/public API serializers for recent conversation summaries, full list cursor pages, history cursor pages and active safe run/process state.
   - Ensure title/process/tool categories use fixed server allowlists, not raw events or front-end derivation.
   - Preserve legacy message-only history without synthesized process records.

6. **Routes and external contract**
   - Add/adjust Pydantic request models and route endpoints for first-turn, normal turn, list and history.
   - Keep all response bodies learner-safe; reject malformed/cross-scope cursors with stable public errors.
   - Ensure dispatch occurs only after the atomic mutation commits and only for the new foreground run.

7. **Desktop navigation and timeline**
   - Add route-level selected-conversation state, recent sidebar, new draft, full-list panel and cursor pagination.
   - Change first submit to first-turn and subsequent normal submit to conversation-turn; only show/use continuation interaction when server grants it.
   - Hydrate server history on selection, close old SSE before switching, subscribe only to returned active run and keep `useTutorSSE` transport-only.
   - Replace temporary large process panel with compact persistent disclosure cards using server process projections; retain local disclosure state only.
   - Preserve timeline-only scrolling and visible Composer, including reduced-motion and keyboard behavior.

8. **Documentation and final integration**
   - Update API, database, runtime and frontend interaction source-of-truth documents.
   - Reconcile any existing uncommitted documentation changes rather than overwriting them.

## Required Focused Tests

### Backend lifecycle and persistence

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_run_loop.py tests/test_tutor_run_repository.py tests/test_tutor_input_merge.py tests/test_tutor_sse.py tests/test_tutor_routes.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_provider_gateway.py -q
```

Add focused cases for:

- ten ordinary turns → same conversation, ten distinct run IDs and fresh budgets;
- first-turn success, forced intermediate failure rollback and idempotency replay;
- foreground partial-unique/concurrent normal input behavior;
- post-provider supersede race, plus capability/effect/public-message/title suppression;
- normal run-input rejection and valid explicit continuation acceptance;
- title validation/write-once/placeholder behavior and absence of rename route;
- public-process key allowlist, duration bounding, superseded display and redaction;
- history/list pagination order, opaque cursor integrity, user/conversation scope and legacy message compatibility.

### Quality and Desktop

```powershell
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
git diff --check
```

Where existing frontend test infrastructure permits, cover draft no-write behavior, endpoint selection, SSE teardown on switch, history prepend ordering, disclosure keyboard state and no raw process text rendering. Do not make a real provider call in any test.

## High-Risk Files

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/models/tutor.py`
- `aearn/services/api/app/routes/tutor.py`
- `aearn/services/api/app/agents/harness/contracts.py`
- `aearn/services/api/app/services/tutor/run_loop.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/public_api.py`
- `aearn/services/api/tests/test_tutor_run_loop.py`
- `aearn/services/api/tests/test_tutor_run_repository.py`
- `aearn/services/api/tests/test_tutor_input_merge.py`
- `aearn/services/api/tests/test_tutor_sse.py`
- `aearn/services/api/tests/test_tutor_routes.py`
- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/hooks/useTutorSSE.ts`
- `aearn/apps/desktop/src/pages/TutorWorkspacePage.tsx`
- `aearn/apps/desktop/src/styles.css`
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/product/frontend-interaction-spec.md`

## Rollback Points

1. **Schema:** all additions are additive; do not delete existing Tutor data. If a new index/check prevents safe startup, roll back the new code/feature gate after examining migration/bootstrap evidence, not by broad table deletion.
2. **Backend route/UI adoption:** retain a safe disabled/read-only behavior for the new UI path instead of silently returning to old merged normal runs.
3. **Race protection:** if a cancellation check is uncertain, fail closed to `cancelled`/safe process display before a public write or effect, rather than attempting to recover a stale provider result.
4. **History:** on invalid cursor/projection state return a stable recoverable error; do not query raw trace/events as a fallback timeline.

## Completion Gate

- All child acceptance criteria have tests or direct type/lint evidence.
- No raw CoT/reasoning/provider body/trace/tool argument/diagnostic enters any new table, serializer, title, process card or UI text.
- No ordinary message reuses a run; no stale run can publish/dispatch/commit.
- No manual title rename capability is present.
- Parent integration checklist is updated with test outputs before asking to archive this child.
