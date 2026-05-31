# Implementation Plan

## Ordered Steps

1. Read current onboarding judgement code:
   - `aearn/services/api/app/agents/onboarding_slot_extractor.py`
   - `aearn/services/api/app/services/onboarding_conversation.py`
   - `aearn/services/api/app/routes/onboarding.py`
   - `aearn/services/api/tests/test_onboarding_m2.py`

2. Read likely future consumers enough to avoid a one-page abstraction:
   - `aearn/services/api/app/services/learning_conversation.py`
   - `aearn/services/api/app/agents/learning_concept_agent.py`
   - review/note agent or service entry points if present

3. Add shared structured judgement module:
   - schema types
   - field/action normalization helper
   - priority-based clarification selection
   - no DB/repository/route imports

4. Add focused shared-module unit tests:
   - required ambiguous field blocks readiness and clears value
   - missing optional field does not block readiness when policy says so
   - ambiguous optional field blocks readiness when policy says so
   - fallback question remains policy-owned

5. Migrate onboarding:
   - replace local `SlotJudgement` with shared type or an alias
   - replace local normalization helpers with shared policy invocation
   - keep onboarding fallback questions and route-ready protection in onboarding service

6. Preserve unsupported-language behavior:
   - `unsupported_language` still yields `LANGUAGE_NOT_SUPPORTED`
   - no `plan_draft` is stashed for unsupported language turns

7. Add reusable integration evidence for future pages:
   - add a shared-module unit test or small test helper showing a non-onboarding policy shape
   - do not migrate the real learning `concept_check` runtime in this task
   - leave learning/review/notes adoption as follow-up work after the onboarding migration is stable

## Validation Commands

Run from repository root:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py
uv --directory .\aearn\services\api run ruff check app/agents app/services app/routes tests/test_onboarding_m2.py
uv --directory .\aearn\services\api run python -m mypy --follow-imports=skip app/agents app/services app/routes
pnpm --dir .\aearn desktop:check
git diff --check -- aearn/services/api/app/agents aearn/services/api/app/services aearn/services/api/app/routes aearn/services/api/tests
```

If the final touched scope is narrower, the implementer may narrow ruff/mypy path arguments, but must include the new shared module, onboarding files, and affected tests.

## Review Gates

- Verify the shared module has no onboarding-specific field names or fallback copy.
- Verify services, not agents, still own persistence and public response decisions.
- Verify model output cannot force readiness when policy says a field is ambiguous/missing/unsupported.
- Verify existing onboarding route-card replay behavior remains intact.

## Rollback Points

- If the abstraction becomes too broad, keep only the shared schema and a small normalization helper, then defer learning/review/notes adoption.
- Learning integration is intentionally deferred; keep only a test/example integration pattern in this task.
