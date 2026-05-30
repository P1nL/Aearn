# Learning Page Concept Intro And Check Flow

## Goal

Replace the current learning-page opening with a model-generated concept intro flow that gives the learner a concise summary, an easy example, and a low-friction natural-language judgment question before practice.

The flow must stay specific to the learning page. Review-page warmups and "audit AI-written code" exercises are out of scope for this task.

## Background

Current learning sessions start with a plain `initial_agent_message` and then move through `concept_intro`, `concept_qna`, `readiness_check`, and `practice_support`. The current opening can leave the learner unsure how to respond. The desired learning-page flow is shorter and more guided:

`start -> show_concept_intro -> learner natural-language judgment -> show_concept_check_result -> practice_offer -> show_code_exercise`

## Requirements

- `POST /api/learning-sessions/start` must generate the learning-page opening at session start, not wait for the learner to send a first message.
- The opening must be model-generated and returned as a `show_concept_intro` tool, not only as a long plain-text agent message.
- `show_concept_intro` must include a concise concept summary, an easy-to-understand example, and a single-choice judgment question.
- The judgment question option count is chosen by the model, but valid output must have 2 to 4 options.
- The UI should show options as text the learner can naturally answer, not as mandatory buttons. The learner can reply with `A`, `B`, or their own wording.
- If intro generation fails validation or safety checks, do not show a broken fallback card. Return a clear `CONCEPT_INTRO_GENERATION_FAILED` error so the frontend can show retry/back actions.
- The learner's natural-language answer must be judged by the model, and the result must be emitted as a structured `show_concept_check_result` tool.
- The check result must support `correct`, `incorrect`, and `unclear`. Direct "start practice" requests before a valid check must be handled as `skipped`.
- On `correct`, the agent must briefly restate the key concept relationship, then ask whether to start practice. The state becomes `practice_offer`.
- From `practice_offer`, a learner reply such as "开始练习" must unlock `show_code_exercise` with `learning_incomplete=false` and `practice_unlock_reason=concept_check_passed`.
- On first `incorrect`, the agent must point out one misconception, give a simpler counterexample, and ask a narrower follow-up judgment. The state becomes `concept_repair`.
- After two incorrect/repair attempts, the agent must stop looping and offer either another example or a guided practice path.
- If the learner chooses guided practice after the repair limit, unlock `show_code_exercise` with `learning_incomplete=true` and `practice_unlock_reason=concept_check_repair_limit`.
- On `unclear`, the agent must not mark the learner wrong or unlock practice. It should ask a more concrete question or ask the learner to answer using the shown options.
- If the learner directly asks to practice before passing the concept check, allow it, but mark `concept_check_result=skipped`, `learning_incomplete=true`, and `practice_unlock_reason=concept_check_skipped`.
- `show_concept_intro` and `show_concept_check_result` tool calls must be persisted and replayed on refresh/resume/idempotency replay. Do not regenerate intro content for the same session unless a later explicit regenerate action is added.
- Model input for concept checking must include only safe minimal context: knowledge point, lesson outline/sources, active intro/check, learner answer, attempt count, previous misconceptions, and safe conversation summary.
- Model input/output must not expose hidden tests, `solution_reference`, full exercise answers, raw provider errors, raw prompts, secrets, or SDK internals.
- Existing sessions created before this task must keep working. They may use the legacy plain initial message path or a compatible migration path, but must not break learning session start/resume.

## Acceptance Criteria

- [ ] New learning session start returns or rehydrates a persisted `show_concept_intro` tool with summary, example, and 2-4 check options.
- [ ] Invalid/unsafe intro generation returns `CONCEPT_INTRO_GENERATION_FAILED` and does not persist a malformed intro tool.
- [ ] Refreshing or starting the same active session replays the same persisted intro; the example and check do not drift.
- [ ] A natural-language learner answer is judged by the model and persisted as `show_concept_check_result`.
- [ ] `correct` result enters `practice_offer`; the agent restates the key relationship and asks whether to start practice.
- [ ] From `practice_offer`, "开始练习" emits `show_code_exercise` with `practice_unlock_reason=concept_check_passed` and `learning_incomplete=false`.
- [ ] First `incorrect` result enters `concept_repair`, gives misconception feedback, and provides a simpler follow-up judgment without unlocking practice.
- [ ] Second failed repair stops the judgment loop and offers another example or guided practice.
- [ ] Guided practice after the repair limit emits `show_code_exercise` with `practice_unlock_reason=concept_check_repair_limit` and `learning_incomplete=true`.
- [ ] `unclear` asks for clarification and does not unlock practice.
- [ ] Direct practice request before check emits `show_code_exercise` with `practice_unlock_reason=concept_check_skipped` and `learning_incomplete=true`.
- [ ] Frontend renders concept intro/check result tools and shows loading, retry, and back states for start-time generation failure.
- [ ] Backend tests cover start success/failure, persisted replay, correct/incorrect/unclear/skipped branches, repair limit, and idempotency replay.
- [ ] Frontend checks cover rendering intro/check result tools and the learning-page loading/error path.

## Out Of Scope

- Review-page warmup flow.
- AI patch/code-review exercise type.
- Button-based answer submission for concept checks.
- Replacing the existing exercise runner, hint, submit, or FSRS scheduling logic.
- A user-facing "regenerate intro" feature beyond retrying failed generation.

## Open Questions

- None currently blocking planning. The user confirmed: learning-page scope, model-generated intro, AI-chosen 2-4 options, natural-language answers only, model judging with structured tool status, no fallback on invalid generation, and persisted tool replay.
