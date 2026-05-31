# Cross-page Structured Judgement Integration Implementation Plan

## Checklist

- [x] Inventory exact production judgement points in learning, explanation-check, review, and notes routes/services.
- [x] Add or co-locate page-specific `JudgementPolicy` definitions and small adapter functions for each target surface.
- [x] Update model prompts/output schemas for target LLM JSON flows to include `judgements` where the model makes a durable decision.
- [x] Apply `normalize_judgements` before learning-stage transitions, attempt explanation-check writes, review progress writes, and note draft persistence.
- [x] Return clarification/retry-safe responses for blocked judgements without leaking provider details.
- [x] Keep onboarding policy and behavior unchanged.
- [x] Add regression tests for confirmed, ambiguous, missing, unsupported, and invalid judgement payloads.
- [x] Run focused backend verification, lint, type-check, and Trellis validation.

## Suggested File Order

1. `aearn/services/api/app/agents/learning_concept_agent.py`
2. `aearn/services/api/app/services/learning_conversation.py`
3. `aearn/services/api/app/agents/exercise_coach_agent.py`
4. `aearn/services/api/app/services/learning_session_repository.py`
5. `aearn/services/api/app/agents/review_coach_agent.py`
6. `aearn/services/api/app/services/review_repository.py`
7. `aearn/services/api/app/agents/note_assist_agent.py`
8. `aearn/services/api/app/services/note_repository.py`
9. Relevant tests under `aearn/services/api/tests/`

Adjust the file list after the inventory step if code evidence shows a surface has no durable judgement gate.

## Verification Commands

Run from repository root:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_structured_judgement.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py tests/test_reviews_m4.py tests/test_notes_m5.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run mypy app
python .\.trellis\scripts\task.py validate .\.trellis\tasks\05-31-cross-page-structured-judgement-integration
```

If frontend response handling changes become necessary, also run:

```powershell
pnpm --dir .\aearn desktop:check
```

## Review Gate Before `task.py start`

- [ ] PRD acceptance criteria are still accurate after inventory.
- [ ] No target surface requires a public API contract migration.
- [ ] Blocked judgement behavior is specified for each target surface.
- [ ] Verification commands are practical in the local environment.
- [ ] User has approved moving from planning to implementation.

## Rollback Points

- Revert prompt/output-schema changes first if live model behavior becomes unstable.
- Keep deterministic fallback paths intact until structured judgement tests and real route tests pass.
- Preserve current API/SSE shapes so rollback does not require desktop UI changes.
