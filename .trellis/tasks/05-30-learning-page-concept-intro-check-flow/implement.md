# Implementation Plan

## Phase 1: Contracts And Docs

- [ ] Update API/frontend docs for `show_concept_intro`, `show_concept_check_result`, and new learning stages.
- [ ] Define backend typed validation helpers for intro/check-result payloads.
- [ ] Define error envelope for `CONCEPT_INTRO_GENERATION_FAILED`.

## Phase 2: Backend Intro Generation

- [ ] Add a model-backed concept intro generator for learning-session start.
- [ ] Validate summary/example/check payloads and 2-4 option count.
- [ ] Persist intro tool call in `learning_messages.metadata.tool_calls`.
- [ ] Return intro tool data from `POST /api/learning-sessions/start`.
- [ ] Reuse persisted intro for active-session replay/resume.
- [ ] Return `CONCEPT_INTRO_GENERATION_FAILED` on invalid/unsafe generation instead of showing fallback content.

## Phase 3: Backend Concept Check Flow

- [ ] Add stage handling for `concept_check`, `concept_repair`, and `practice_offer`.
- [ ] Add a model-backed concept check judge for natural-language answers.
- [ ] Emit and persist `show_concept_check_result`.
- [ ] Implement `correct -> practice_offer`.
- [ ] Implement `incorrect -> concept_repair` with repair check.
- [ ] Implement repair limit -> another-example/guided-practice offer.
- [ ] Implement `unclear` without unlocking practice.
- [ ] Implement direct practice skip with `concept_check_skipped`.
- [ ] Implement `practice_offer -> show_code_exercise` with `concept_check_passed`.
- [ ] Implement guided practice after repair limit with `concept_check_repair_limit`.

## Phase 4: Frontend Rendering

- [ ] Extend desktop types and API validation for new tool names and args.
- [ ] Render `show_concept_intro` in the learning conversation.
- [ ] Render `show_concept_check_result` with explanation, next prompt, optional repair check, and textual quick replies.
- [ ] Add start-time loading state for intro generation.
- [ ] Add start-time error state for `CONCEPT_INTRO_GENERATION_FAILED` with retry/back actions.
- [ ] Preserve existing `show_code_exercise` behavior.

## Phase 5: Tests

- [ ] Backend test: start success persists and returns `show_concept_intro`.
- [ ] Backend test: active-session replay returns same intro, no regeneration drift.
- [ ] Backend test: invalid intro returns `CONCEPT_INTRO_GENERATION_FAILED`.
- [ ] Backend test: correct answer -> `show_concept_check_result` + `practice_offer`.
- [ ] Backend test: "开始练习" after offer -> `show_code_exercise` with `concept_check_passed`.
- [ ] Backend test: incorrect answer -> `concept_repair` and no exercise.
- [ ] Backend test: second repair failure -> guided-practice offer.
- [ ] Backend test: guided practice -> `show_code_exercise` with `concept_check_repair_limit`.
- [ ] Backend test: unclear answer asks clarification and no exercise.
- [ ] Backend test: direct practice skip -> `show_code_exercise` with `concept_check_skipped`.
- [ ] Backend test: idempotency replay preserves tool calls.
- [ ] Frontend check: intro/result tools render without buttons and composer remains available.
- [ ] Frontend check: loading and error states are visible.

## Validation Commands

Run focused checks first:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check app/services/learning_conversation.py app/services/learning_session_repository.py tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run python -m mypy app/services/learning_conversation.py app/services/learning_session_repository.py
pnpm --dir .\aearn desktop:check
```

If API docs or frontend contracts change broadly, also run:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_reviews_m4.py
git diff --check
```

## Risk And Rollback Points

- Start-time model generation changes the perceived performance of learning-session start. Keep loading/error UX explicit.
- Stage enum changes touch backend docs, service state, frontend state, and tests. Update all consumers together.
- Tool persistence must remain backward-compatible with existing sessions that only have plain `initial_agent_message`.
- Do not alter runner, hint, submit, or FSRS scheduling behavior except for unlock reasons and `learning_incomplete`.
