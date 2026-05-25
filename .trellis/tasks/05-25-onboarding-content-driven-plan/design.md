# Design

## Boundary

This task lives entirely inside the onboarding flow:

**Backend** (`aearn/services/api/app/`):
- New extractor agent (LLM structured output) reads conversation history and returns slot JSON
- `onboarding_conversation.py`: replace `detect_plan_proposal` heuristic, build PlanDraft from extracted slots, stash to `extracted_context.plan_draft`
- `routes/onboarding.py`: drive new extractor call, emit `show_learning_route` from real PlanDraft, new confirm endpoint
- `routes/plans.py`: optionally accept `onboarding_session_id` to read stashed draft

**Frontend** (`aearn/apps/desktop/src/`):
- `OnboardingPage.tsx`: `handleConfirmPlan` switches to the new endpoint, drops `generatePlanDraft` call
- `api.ts`: add `confirmOnboardingPlan(sessionId, userId)` wrapper

Must not change:
- FSRS scheduling, exercise generation, learning/review pages
- `plan_generator.build_plan_draft` internals (course templates stay)
- assistant-ui Slice 1 plumbing (tool_call SSE protocol, partial-json, runtime adapter)

## Slot Extraction

Extractor agent runs **after** the chat agent finishes streaming text, on the refreshed conversation history. Separate agent so the chat reply stays free-form and the extractor can use a strict JSON-schema response.

**Slot schema**:

```ts
type ExtractedSlots = {
  language: "javascript" | "python" | "java" | "cpp" | "html_css" | null;
  target_level: "beginner" | "intermediate" | "advanced" | "beginner_to_intermediate" | null;
  goal_text: string | null;       // ≥10 chars when set
  time_budget: { minutes_per_day: number; days_per_week: number } | null;
  focus: string | null;            // free text, e.g. "Web 开发"
  plan_ready: boolean;             // agent's own judgment
  missing_slot_question: string | null;  // suggested next question if !plan_ready
  revising: boolean;               // latest user turn asks to adjust/rebuild the draft
};
```

**Cumulative merge**: each turn's extraction merges over the prior `extracted_context` — null/missing fields don't clobber earlier values. The agent prompt explicitly instructs "if a field was set previously and the new turn doesn't change it, repeat the prior value".

**LLM unavailable fallback** (`openai_compatible_configured == False`):
- Keyword scan over user-message history:
  - language: substring match on `python|js|javascript|java|c\+\+|cpp|html|css`
  - target_level: substring match on `零基础|入门|进阶|高级|有经验|有基础`
- time_budget: regex `(\d+)\s*(分钟|小时|min|h)` + `每[天日周]`
- focus: a fixed list of keywords (`web|后端|前端|数据|算法|爬虫|游戏`)
- `plan_ready` = required slots (`language`, `target_level`, `goal_text`) filled; `time_budget` and `focus` are extracted when present but do not block draft generation
- `missing_slot_question` = templated string per missing slot

## Trigger

`detect_plan_proposal(context)` becomes:

```python
def detect_plan_proposal(context: OnboardingConversationContext) -> bool:
    extracted = context.extracted_context
    if extracted.get("plan_draft"):  # already stashed; don't re-trigger
        return False
    if not extracted.get("plan_ready"):
        return False
    return all(extracted.get(slot) for slot in ("language", "target_level", "goal_text"))
```

`time_budget` and `focus` are nice-to-have, not gating — agent can fill defaults.

## PlanDraft Stashing

When `detect_plan_proposal` returns True, the route:

1. Loads the user and the course matching `extracted.language`
2. Builds a synthetic `PlanGenerateRequest` from extracted slots:
   ```python
   PlanGenerateRequest(
       user_id=user_id,
       mode="goal_based",
       goal_text=extracted["goal_text"],
       course_id=course["id"],
       language=extracted["language"],
       target_level=extracted["target_level"],
       time_budget=TimeBudget(**extracted["time_budget"]) if extracted.get("time_budget") else None,
   )
   ```
3. Calls `build_plan_draft(payload, user, course)` → real `PlanDraft`
4. Validates `has_supported_mvp_runtime` — if False, log and emit error event (no card)
5. Serializes draft via `model_dump(mode="json")`, writes to `extracted_context.plan_draft`, and moves the conversation to `status='plan_proposed'`
6. Projects `LearningRouteArgs` from the draft (modules + knowledge points), emits `show_learning_route` tool call

The projection lives in a new helper `learning_route_args_from_plan_draft(draft: PlanDraft) -> dict`. Replaces `build_deterministic_learning_route`.

## Confirm Path

**New endpoint**: `POST /api/onboarding/{conversation_id}/confirm_plan`

Request body:
```json
{ "user_id": "..." }
```

Response: same shape as `POST /api/plans` (`CreatedPlanResponse`).

Behavior:
1. Load `onboarding_conversations.extracted_context.plan_draft`; 404 if missing
2. Validate user_id matches conversation
3. Hydrate `PlanDraft` from stashed JSON (Pydantic validation)
4. Reuse existing `confirm_plan` repository function (idempotency key = `default_confirm_key(user_id, draft_id)`)
5. Update conversation status to `confirmed` (matches the existing database check constraint)

**Frontend** drops `generatePlanDraft` from `handleConfirmPlan` and calls `confirmOnboardingPlan(sessionId, userId)`.

**Backward compat**: `POST /api/plans` with full `PlanDraft` body keeps working; only the onboarding flow uses the new endpoint.

## Revise Plan

When user clicks "调整计划" or sends a free-form revision:
- Frontend just sends the revision text as a normal user message
- Extractor reruns on next turn with new context, may update slots and rebuild plan_draft
- Stashed `plan_draft` is **overwritten** when `detect_plan_proposal` triggers again — this requires us to drop the "already stashed" guard during a "revise pending" state

Simplest implementation: a separate flag `extracted_context.revising = True` toggled when the user message contains revision intent (LLM extracts this as a 6th boolean slot, or a heuristic match on "调整|改|不对|换"). When `revising`, ignore the `plan_draft` short-circuit so the next plan_ready turn overwrites the draft.

## Risks

- **Extractor latency**: a second LLM call per turn doubles backend cost and adds ~1–2s. Current implementation keeps time-to-first-token on the chat stream, then runs extraction before any trailing tool_call emission.
- **Schema drift**: if the extractor emits malformed JSON, slots stay stale. Mitigation: tolerant parser (re-use partial-json on backend, or `json.loads` with try/except → keep prior context).
- **Course mismatch**: extracted language might not be in `language_courses` table. Surface as agent prompt: "我们目前主要支持 Python/JavaScript/HTML+CSS，你倾向哪个？" — clear `language` slot, do not trigger.
- **Stashed draft becomes stale**: extracted slots change but plan_draft isn't regenerated. Mitigation: every successful extraction during `revising` rebuilds the draft.
