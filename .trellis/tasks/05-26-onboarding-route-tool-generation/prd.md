# Fix onboarding learning route tool generation

## Goal

Make onboarding generate learning route cards through structured tool calls instead of long plain-text route replies, while preserving guided conversation.

## Background / Confirmed Facts

- The desktop thread already registers `LearningRouteToolUI` in `aearn/apps/desktop/src/components/AssistantUIThread.tsx`.
- The onboarding stream emits `show_learning_route` only after backend `detect_plan_proposal(...)` returns true.
- `detect_plan_proposal(...)` currently requires `plan_ready=True` plus `language`, `target_level`, and `goal_text`.
- Recent local onboarding sessions showed long plain-text route replies with no `metadata.tool_calls`, because `target_level` stayed `None` and `plan_ready` stayed `False`.
- The current model prompt allows the assistant to say "信息够了，我帮你生成一份学习路线", but it does not prevent the model from writing the full route as plain text.
- The desired UX is not a keyword command. The model may judge readiness, but the system must convert readiness into a structured backend contract and a `show_learning_route` tool call.
- The current route card has both `继续学习` and `调整计划`; the desired card action model is a single `开始学习` button.
- `confirm_onboarding_plan` confirms the currently stashed draft for the onboarding conversation; if old cards remain clickable, the visible old card could accidentally confirm the newer stashed draft.

## Requirements

- Preserve guided onboarding: each normal turn should respond naturally and push at most one missing decision point, so the user knows what to answer next.
- Do not require a fixed user phrase such as "确定学习路线" before generating a route card.
- Let the model or slot extractor judge when enough context exists, but require backend validation before any plan draft is stashed.
- Time budget is optional for initial route-card generation.
- When route context is ready, the assistant text must stay short and the route content must be delivered through the `show_learning_route` tool call.
- The short route-generation message should tell users they can revise the route by typing a normal reply.
- The route card must be backed by a stashed `PlanDraft` that `confirm_plan` can persist.
- Improve deterministic fallback behavior for common level expressions such as "学过一点", "看过基础语法", "会一点", and "写过一点".
- Keep user-visible route content out of plain assistant text when a route card is generated.
- Preserve resume behavior: stored onboarding messages with `metadata.tool_calls` must still rehydrate the route card.
- The route card must only expose one primary action: `开始学习`.
- Users revise the route by typing a normal chat message to the agent, not by clicking an `调整计划` button.
- A route revision request after a card has been generated must be handled as a normal onboarding turn that can produce a revised `show_learning_route` card.
- If a user adds or changes time budget after a route card exists, the agent should treat it as a route revision and generate a new latest route card.
- Only the latest generated route card can start learning. Older route cards may stay visible in chat history, but their `开始学习` button must be disabled.
- Avoid touching unrelated local files such as `.claude/settings.local.json` and `docs/.obsidian/`.

## Acceptance Criteria

- [x] A multi-turn onboarding flow like `Python` -> `自动化脚本` -> `看过基础语法` -> route readiness emits a `tool_call` with `name="show_learning_route"`.
- [x] The same flow does not stream a long plain-text route body in the assistant text for the route-generating turn.
- [x] The route-generating assistant text includes a short revision hint such as "想改方向、时间或难度，直接回复我就行。"
- [x] The route-generating turn stores `metadata.tool_calls` with completed `show_learning_route` args.
- [x] `confirm_onboarding_plan` succeeds after the generated route card.
- [x] Missing time budget does not block route-card generation once `language`, `target_level`, and `goal_text` are ready.
- [x] The route card renders a single `开始学习` action and no `调整计划` action.
- [x] After a route card is generated, a user message such as "我想改成数据分析方向" can trigger a revised route card through normal chat.
- [x] After a revised route card is generated, old route cards keep their `开始学习` button visible but disabled.
- [x] Starting learning confirms the latest stashed route draft, not an older card's stale visual content.
- [x] A non-ready flow still asks a clear next question instead of producing a route card.
- [x] Existing first-complete-turn route generation still works.
- [x] Focused backend onboarding tests pass.
- [x] `pnpm --dir .\aearn desktop:check` passes if frontend code changes are made.

## Out of Scope

- Redesigning the route card visuals.
- Replacing assistant-ui or rebuilding the chat shell.
- Changing learning-session exercise generation flow.
- Supporting unsupported languages beyond the current catalog/runtime boundary.

## Decisions

- Route-card generation can happen automatically when required slots are ready.
- The card keeps only `开始学习`; route changes are requested through normal chat input.
- Only the latest route card can start learning.
- Time budget is optional; users can provide it later to revise the route.
- Stale route cards use a disabled `开始学习` button only; no extra stale/replaced label is required.
- Route-generation short replies should explicitly tell users they can revise by typing a normal chat reply.

## Open Question

- None. The user approved implementation on 2026-05-26.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
