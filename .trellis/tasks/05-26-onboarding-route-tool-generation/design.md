# Design: Onboarding Route Tool Generation

## Problem

The current onboarding flow can produce a natural-language learning route without producing the structured `show_learning_route` tool call. This breaks the generative-ui contract: the user sees route-like text, but the frontend cannot render a route card and the backend may not have a stashed `PlanDraft`.

## Desired Boundary

- The model or extractor may decide route readiness.
- Backend code remains the authority for validation, plan draft construction, stash, and SSE tool-call emission.
- The frontend remains a renderer of structured tool-call state; it should not parse natural-language route text into a card.

## Proposed Flow

1. Persist the user message.
2. Load refreshed onboarding context.
3. Extract or update slots from the full conversation.
4. Decide whether route generation is ready.
5. If not ready, generate a concise guided assistant reply that asks the highest-value next question.
6. If ready, build and stash `PlanDraft`, stream a short assistant preface, then emit `show_learning_route` as a tool call.
7. Persist the assistant message with `metadata.tool_calls` when a tool call was emitted.
8. If the user later asks to change the route in normal chat, mark the turn as revision-capable and emit a revised `show_learning_route` card after validation.

## Readiness Contract

Route readiness should be structural, not keyword-only:

- Required: `language`, `target_level`, `goal_text`.
- Optional but useful: `time_budget`, `focus`.
- Missing `time_budget` must not block route-card generation; plan generation should use existing default schedule behavior.
- The latest user message may include confirmation intent, but confirmation intent is not required if the required slots are already ready.
- Existing stashed drafts should not be overwritten unless the latest extraction indicates revision or the user materially changed core slots.

## Route Card Actions

The route card should expose one action only:

- `开始学习`: confirm the latest stashed `PlanDraft` and enter the first learning session.

The card must not expose `调整计划`. Users should revise a route by sending natural-language chat messages such as "我想改成数据分析方向" or "每周只有 2 小时". This keeps the interaction conversational and avoids teaching users that route editing is a separate card mode.

Only the latest generated route card is startable. Older cards can remain as conversation history, but their `开始学习` button must be disabled after a newer route card exists. This avoids a mismatch where an old card visually describes route A while `confirm_onboarding_plan` confirms the currently stashed route B.

Implementation should enforce this in the desktop by deriving the latest `show_learning_route` `tool_call_id` from onboarding messages and passing a disabled/stale state into route-card rendering, while backend confirmation continues to use the latest stashed `PlanDraft` as the source of truth. Comparing only `plan_id` is insufficient because revisions such as time-budget changes may generate a new card without changing all draft identity inputs.

Time budget changes after a route card exists are normal route revisions. The new user turn should update slots, rebuild/stash a new `PlanDraft`, emit a new `show_learning_route` card, and make the earlier card non-startable.

## Prompting / Generation Constraints

The onboarding assistant should not write the complete route in plain text. When readiness is reached, the assistant should produce only a short transition that also teaches the revision path, for example:

`信息够了，我生成一份路线卡片。想改方向、时间或难度，直接回复我就行。`

## Deterministic Fallback

Extend keyword extraction so common beginner-plus phrases map to a valid target level:

- "学过一点"
- "看过基础语法"
- "会一点"
- "接触过"
- "写过一点"

These should usually map to `beginner_to_intermediate` unless a stronger level signal is present.

## Frontend Impact

`LearningRouteToolUI` is already registered in `AssistantUIThread`. Frontend work is expected for the route card CTA shape:

- Change the primary button label from `继续学习` to `开始学习`.
- Remove the `调整计划` button.
- Remove or ignore `adjust_plan` route-card event handling if it becomes unreachable.
- Disable `开始学习` on stale route cards when a newer `show_learning_route` card has been generated.
- Do not add a separate stale label such as "已被新路线替换".

## Compatibility

- Extend `show_learning_route` compatibly with optional `time_budget`; existing cards without it still render.
- Keep stored `metadata.tool_calls` shape.
- Keep `confirm_onboarding_plan` using the stashed draft.
- Do not require users to type a fixed phrase.

## Rollback

The change should be isolated to onboarding route generation. Rollback means restoring previous onboarding stream order and extractor patterns. Existing persisted plans and confirmed learning sessions should not require migration.
