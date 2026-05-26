# Implementation Plan

## Checklist

- [x] Add or update backend tests reproducing the screenshot-like multi-turn path where route text currently appears without `show_learning_route`.
- [x] Extend deterministic slot extraction for "学过一点", "看过基础语法", and similar beginner-plus phrases.
- [x] Refactor onboarding message streaming so slot extraction/readiness can happen before the model writes a long route body.
- [x] Ensure ready route turns emit short assistant text plus `show_learning_route` tool-call events.
- [x] Ensure the short route-generation text tells users they can revise by typing a normal reply.
- [x] Add coverage that missing time budget does not block route-card generation.
- [x] Persist completed tool-call metadata on the assistant message.
- [x] Update the route card to expose only `开始学习` and remove the card-level `调整计划` action.
- [x] Ensure natural-language revision after a generated card can produce a revised `show_learning_route` card.
- [x] Ensure a later time-budget message can regenerate the route card and make the previous card stale.
- [x] Track the latest `show_learning_route` tool call in onboarding UI state so older route cards keep a disabled `开始学习` button even when a regenerated draft has the same `plan_id`.
- [x] Add a frontend or integration check that a revised route makes the earlier card stale.
- [x] Keep non-ready turns guided and question-oriented.
- [x] Sync the onboarding behavior contract in the relevant source-of-truth product/frontend/API docs.
- [x] Run focused backend onboarding tests.
- [x] Run `pnpm --dir .\aearn desktop:check` if frontend code changes.
- [x] Browser-smoke onboarding if backend/frontend behavior changes are both involved.

## Likely Files

- `aearn/services/api/app/routes/onboarding.py`
- `aearn/services/api/app/services/onboarding_conversation.py`
- `aearn/services/api/app/agents/onboarding_slot_extractor.py`
- `aearn/services/api/tests/test_onboarding_m2.py`
- `aearn/apps/desktop/src/components/generative-ui/LearningRouteCard.tsx`
- `aearn/apps/desktop/src/pages/OnboardingPage.tsx`

## Validation Commands

```powershell
uv --directory .\aearn\services\api run python -m pytest tests\test_onboarding_m2.py -q
pnpm --dir .\aearn desktop:check
```

## Risk Points

- Running slot extraction before generation may change the conversational feel if the ready/not-ready branch is too blunt.
- Existing stashed `plan_draft` handling must avoid duplicate or stale route cards.
- The LLM route preface must not leak a full route before tool-call emission.
- Backend tests that bootstrap PostgreSQL should be run sequentially with other DB-heavy tests.
