# Review warmup natural conversation flow

## Goal

Make Aearn review sessions feel like a natural tutor conversation before and between exercise cards, while preserving the current state-machine guarantees for review scheduling, card persistence, and FSRS finalization.

The user-facing experience should no longer expose "skip warmup" controls or mechanical stage wording. Learners can answer the warmup in free text; the system should decide whether to advance, ask one natural follow-up, or briefly steer an off-topic answer back to the warmup question.

## Requirements

### Confirmed Facts

- Review sessions currently use backend stages such as `warmup`, `warmup_repair`, `exercise`, `exercise_feedback`, and `final_summary`.
- `POST /api/reviews/{session_id}/warmup-result` accepts free-text warmup answers and currently classifies them as `correct`, `incorrect`, or `unclear`; it also supports an explicit `skip` action.
- Current product docs still describe a skip warmup operation and a skip entry in the review page state.
- Current desktop review composer and warmup prompt still mention "跳过".
- Formal review exercises already use one generated exercise card per question, and submitted card results are persisted in the conversation flow.
- Formal exercise submissions can return `next_action=next_exercise` for an intermediate result or final scheduling data only when the batch is complete.

### Product Requirements

- Warmup should be presented as ordinary tutor dialogue, not as a separate mechanical form or stage label.
- There must be no explicit "跳过" button or public "skip" prompt in the warmup UI.
- The desktop client must not special-case typed "跳过" / "skip" into `action=skip`; those inputs are sent as ordinary free-text answers for model judgement.
- The backend may retain `action=skip` as a backwards-compatible hidden API path for older callers, but new desktop UI behavior must not expose or depend on it.
- Learners answer warmup prompts with free text. The frontend must not ask learners to self-select "remember / unsure / forgot" stages.
- Clearly relevant but wrong or incomplete answers should be classified as `incorrect` or `unclear` and receive one short, natural follow-up.
- Clearly off-topic answers should not be treated as knowledge failure on the first occurrence. The system should use the model to produce a natural, learner-facing reminder that the answer is unrelated to the current warmup and should steer the learner back to the current warmup question once.
- Off-topic steering must be model-authored. Do not use a deterministic fallback template for this reminder.
- If the learner remains off-topic or still gives no usable answer after the allowed follow-up, the session should advance into a more guided exercise rather than looping.
- If the learner explicitly says they do not know, the system should treat that as `unclear` and either ask one short follow-up or enter a guided exercise according to the existing warmup attempt limit.
- Formal practice should stay "one question, one card". Completed cards keep the learner input, run output, and feedback; the next exercise is a new card below the prior conversation.
- Wrong formal exercise answers should receive immediate lightweight feedback before the next exercise. The feedback should identify the core mistake and next focus without turning into a long lecture.
- At the end of the review batch, the system should summarize repeated mistake patterns, weak points, and next review scheduling separately from per-question feedback.

### Non-Functional Requirements

- Warmup branches must not create `Attempt`, `review_logs`, FSRS evidence, or long-term review scheduling changes.
- Intermediate formal exercise results must not update long-term `ReviewState`; final batch completion remains the only FSRS scheduling point.
- User-facing messages must not expose internal stage names, model judgement labels, raw prompts, provider errors, hidden tests, or solution references.
- Off-topic steering output must pass the same safety checks as other learner-facing review messages; unsafe or unavailable model output must not be replaced by a fixed local template.
- If off-topic steering generation fails or is blocked by existing safety guardrails, the backend should retry model generation once. If the second attempt still fails or is blocked, return a model-unavailable error instead of falling back to a template or auto-advancing.
- Do not add a separate semantic validator for whether the off-topic steering tone is natural or whether it perfectly re-focuses the learner. Natural tone and refocus behavior are enforced by the model prompt, schema contract, and review tests with controlled outputs.
- Existing persisted review sessions should remain recoverable.
- Existing API compatibility for older clients should be considered separately from removing public skip affordances.

## Acceptance Criteria

- [ ] Starting a review displays a natural tutor prompt without "跳过", "skip", "热身阶段", or self-rating choices.
- [ ] Typing "跳过" or "skip" in the desktop composer is handled as normal free text, not converted to `action=skip`.
- [ ] Submitting a correct warmup answer advances to a generated exercise card with one natural transition message.
- [ ] Submitting a relevant but wrong or incomplete warmup answer produces at most one natural follow-up before entering a guided exercise.
- [ ] Submitting an off-topic warmup answer produces one model-authored steering message that explicitly notes the answer is unrelated to the current warmup and re-focuses the learner on answering that warmup.
- [ ] Off-topic steering does not fall back to a fixed local template when model output is unavailable or unsafe.
- [ ] If off-topic steering generation is unavailable or blocked, the backend attempts one second model generation before returning `MODEL_UNAVAILABLE`.
- [ ] A second off-topic or unusable answer advances into a guided exercise instead of looping.
- [ ] Formal exercise cards remain part of the conversation flow; each next exercise creates a new card, and completed cards keep persisted results after reload.
- [ ] Wrong formal exercise submissions show immediate lightweight feedback in or directly after the completed card.
- [ ] Final review completion includes a concise batch summary that does not duplicate every per-question feedback block.
- [ ] Backend tests cover warmup `correct`, `incorrect`, `unclear`, off-topic routing, and no fixed-template fallback; they do not need an additional semantic naturalness classifier.
- [ ] Frontend tests or build verification cover removal of visible skip affordances and continued card rendering.
- [ ] API and product docs are updated to match the new warmup behavior.

## Notes

### Likely Implementation Areas

- `aearn/services/api/app/agents/review/review_coach_agent.py`
- `aearn/services/api/app/services/repositories/review_repository.py`
- `aearn/services/api/app/routes/reviews.py`
- `aearn/apps/desktop/src/pages/ReviewPage.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `docs/architecture/api-contract.md`
- `docs/product/frontend-interaction-spec.md`
- `aearn/services/api/tests/test_reviews_m4.py`
- `aearn/services/api/tests/test_llm_integration.py`

### Resolved Product Decisions

- Desktop behavior: typed "跳过" / "skip" is treated as free-text learner input and usually falls into `unclear` judgement rather than an explicit skip branch.
- Backend compatibility: keep `action=skip` as a hidden compatibility path unless implementation proves it creates significant complexity or safety risk.
- Off-topic steering: the reminder must be generated by the model in a natural tutor tone, state that the learner's answer is unrelated to the current warmup, and ask the learner to focus on the warmup question. There is no fixed-template fallback for this reminder.
- Safety scope: keep the existing teaching safety guardrail categories for hidden tests, reference answers, provider/API-key leakage, prompt/policy leakage, and complete-answer leakage. Do not add a new semantic guardrail for tone or refocus quality.
- Off-topic steering failure handling: if the first model generation fails, is unavailable, or is blocked by existing safety guardrails, retry model generation once. If the second attempt still fails or is blocked, return `MODEL_UNAVAILABLE`; do not show a fixed fallback and do not automatically advance into exercise.
