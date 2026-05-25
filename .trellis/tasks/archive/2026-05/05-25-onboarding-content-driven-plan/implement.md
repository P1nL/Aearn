# Implementation Plan

## Phase 1: Slot Extractor Agent

- [x] 1.1 Create `aearn/services/api/app/agents/onboarding_slot_extractor.py`
  - `AgentsSDKOnboardingSlotExtractor` class with `extract(history, prior_slots) -> ExtractedSlots`
  - System prompt: instruct LLM to merge new info with prior slots, return strict JSON, suggest next question if not ready
  - Use Agents SDK `output_type` (Pydantic model) for structured output
  - Pydantic model `ExtractedSlots` with fields per design.md schema

- [x] 1.2 Deterministic fallback in same file
  - `keyword_extract_slots(history, prior_slots) -> ExtractedSlots`
  - Regex/substring matching per design.md
  - Used when `openai_compatible_configured == False` or LLM call raises

## Phase 2: Service Layer Updates

- [x] 2.1 `onboarding_conversation.py`: add `extract_slots(context, settings) -> ExtractedSlots`
  - Dispatches to LLM extractor or keyword fallback
  - Catches `LLMCallError`/`LLMConfigurationError`, returns prior slots unchanged

- [x] 2.2 `onboarding_conversation.py`: rewrite `detect_plan_proposal`
  - Check `extracted_context.plan_draft` not present (unless `revising` flag set)
  - Check `plan_ready == True`
  - Check required slots: `language`, `target_level`, `goal_text`

- [x] 2.3 `onboarding_conversation.py`: add `build_plan_draft_from_slots(slots, user_id, conn) -> PlanDraft`
  - Look up course by language; if not found raise `ValueError`
  - Construct synthetic `PlanGenerateRequest`
  - Call `plan_generator.build_plan_draft`
  - Return real `PlanDraft`

- [x] 2.4 `onboarding_conversation.py`: add `learning_route_args_from_plan_draft(draft) -> dict`
  - Project `PlanDraft` modules → `LearningRouteArgs` shape (id from `temp_id`, status="pending", mastery_score=0.0)
  - Replaces `build_deterministic_learning_route` (delete old function)

- [x] 2.5 `onboarding_conversation.py`: add `stash_plan_draft(conn, conversation_id, draft, slots)`
  - `UPDATE onboarding_conversations` writes `plan_draft`, merged slots, and `status='plan_proposed'`
  - Single SQL statement, atomic

- [x] 2.6 `onboarding_conversation.py`: add `load_stashed_plan_draft(conn, conversation_id) -> PlanDraft | None`
  - Read `extracted_context.plan_draft`, hydrate via `PlanDraft.model_validate`
  - Return None if missing

## Phase 3: Route Updates

- [x] 3.1 `routes/onboarding.py`: in `_onboarding_message_stream`, after agent text streams:
  - Call `extract_slots(refreshed_context)`
  - Persist merged slots to `extracted_context` (without `plan_draft`)
  - If `detect_plan_proposal(refreshed)` → call `build_plan_draft_from_slots` + `stash_plan_draft`
  - If course lookup fails → emit `error` event with code `LANGUAGE_NOT_SUPPORTED`, no card
  - If `has_supported_mvp_runtime` False → emit `error`, no card

- [x] 3.2 `routes/onboarding.py`: replace `build_deterministic_learning_route` call with `learning_route_args_from_plan_draft(stashed_draft)`

- [x] 3.3 `routes/onboarding.py`: add `POST /api/onboarding/{conversation_id}/confirm_plan`
  - Body: `{ user_id }`
  - Load stashed draft → 404 with `PLAN_DRAFT_NOT_READY` if missing
  - Validate user_id matches conversation owner → 403 if mismatch
  - Call `confirm_plan` repository function with hydrated draft
  - Update conversation status to `confirmed` (existing DB constraint value)
  - Return `CreatedPlanResponse`

- [x] 3.4 Drop legacy `plan_draft` SSE event emission and `build_legacy_plan_draft_payload` helper
  - Verified by user: no other consumer of `plan_draft` event remains
  - Cleans up Slice 1 dual-emit window

## Phase 4: Frontend Updates

- [x] 4.1 `api.ts`: add `confirmOnboardingPlan(conversationId, userId) -> CreatedPlanResponse`
  - POST `/api/onboarding/{id}/confirm_plan`
  - Reuses `isCreatedPlanResponse` validator

- [x] 4.2 `OnboardingPage.tsx`: rewrite `handleConfirmPlan`
  - Drop `generatePlanDraft` call entirely
  - Call `confirmOnboardingPlan(onboardingSessionId, activeUser.id)`
  - Same downstream flow (`onPlanCreated`)

- [x] 4.3 `OnboardingPage.tsx`: drop `InlinePlanCard` rendering since `plan_draft` event is gone
  - `LearningRouteCard` is the only confirm path now
  - Wire `LearningRouteCard` action handlers via `assistantToolUIs.tsx`:
    - "继续学习" / confirm → call `confirmOnboardingPlan`
    - "调整计划" → send revision message via composer

- [x] 4.4 `OnboardingPage.tsx`: drop `onboardingPlanDraft` state from store
  - Remove `setOnboardingPlanDraft`, `onboardingPlanDraft` field, related code
  - SSE handler no longer cares about `plan_draft` events

## Phase 5: Verification

- [x] 5.1 `pnpm --dir .\aearn desktop:check` passes
- [x] 5.2 `uv --directory .\aearn\services\api run ruff check app\agents\onboarding_plan_agent.py app\services\onboarding_conversation.py app\routes\onboarding.py app\agents\onboarding_slot_extractor.py tests\test_onboarding_m2.py` clean
- [x] 5.3 Browser smoke + automated acceptance coverage:
  - Browser: front-loaded user message "我想学 Python Web 后端，零基础，每天 1 小时" → 第 1 轮触发 `show_learning_route`
  - Browser: click confirm on card → plan saved, navigates to learning page
  - Automated: 4-turn drip-feed `language → level → time → focus` fills slots and triggers
  - Automated: 5 vague user turns do not trigger
- [x] 5.4 LLM-disabled / deterministic fallback coverage:
  - Keyword fallback fills slots; trigger condition still works
  - Card content reflects extracted language/level

Validation completed:
- `uv --directory .\aearn\services\api run python -m pytest tests\test_onboarding_m2.py` → 11 passed
- `uv --directory .\aearn\services\api run python -m pytest tests\test_onboarding_m2.py tests\test_llm_integration.py -k "onboarding_plan or onboarding_keyword or confirm_onboarding or onboarding_message_stream"` → 7 passed
- `pnpm --dir .\aearn desktop:check` → passed
- Browser smoke at `http://127.0.0.1:1420` with temporary API on `127.0.0.1:8001`: front-loaded Python Web message produced `show_learning_route`, clicking `继续学习` confirmed the plan and navigated to the learning page.

## Rollback Points

- After Phase 1: extractor agent self-contained; no behavior change
- After Phase 2: helpers exist but route still uses old path; can revert by reverting `routes/onboarding.py`
- After Phase 3: backend uses new path; legacy frontend `InlinePlanCard` still works
- After Phase 4: full new path; old code removed

## Dependencies

- Slice 1 SSE/store/runtime plumbing (already merged)
- `aearn/.env` with valid OpenAI-compatible endpoint
- No new npm or python packages
