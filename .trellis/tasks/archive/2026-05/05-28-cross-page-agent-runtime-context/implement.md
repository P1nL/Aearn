# Reusable Agent Runtime Context Layer Implementation Plan

## Preconditions

- Task remains `planning` until the user reviews and approves these planning artifacts.
- Before runtime edits, load `trellis-before-dev` and relevant backend specs.
- Do not touch unrelated local files:
  - `.claude/settings.local.json`
  - `docs/.obsidian/`
- Keep public API/SSE contracts unchanged.

## Phase 1: Planning Review

1. First-phase domain scope is confirmed:
   - learning page
   - onboarding/build-plan page
   - review page
2. Note Assist is confirmed as follow-up, not first-phase scope.
3. Confirm no schema migration unless implementation proves it is required.
4. Review `prd.md` and `design.md` before `task.py start`.

## Phase 2: Shared Context Primitives

1. Inspect current backend specs:
   - `.trellis/spec/backend/index.md`
   - `.trellis/spec/backend/quality-guidelines.md`
   - `.trellis/spec/backend/directory-structure.md`
   - `docs/architecture/api-contract.md`
   - `docs/qa/sdk-agent-release-readiness.md`
2. Add model-key-free tests for the intended shared primitives before broad refactor.
3. Introduce small shared context abstractions under `aearn/services/api/app/agents/`.
4. Extract reusable helpers from learning page only when tests lock current behavior:
   - safe message shape
   - forbidden-token sanitization
   - summary refresh decision
   - LLM summary invocation
   - deterministic fallback summary
   - JSON summary normalization

## Phase 3: Learning Page Migration

1. Keep `learning_conversation.py` public behavior stable.
2. Move current learning summary plumbing behind shared helper functions.
3. Preserve:
   - `conversation_summary` persistence under `learning_stage_state_json`
   - `recent_safe_messages` limit
   - concept-first / diagnosis-first prompt policy
   - direct-answer request redirection to partial guidance
   - no hidden/reference/provider/API-key leakage
4. Run targeted learning tests.

## Phase 4: Onboarding Context Reuse

1. Identify where onboarding messages, slot state, route cards, and plan drafts are loaded.
2. Add onboarding domain adapter for safe context:
   - goal text
   - language
   - target level
   - time budget
   - missing slots
   - rejected/unsupported directions
   - current `PlanDraft` status
3. Preserve server-owned course template validation in `plan_generator.py` / plan services.
4. Ensure model failure or invalid candidate still maps to `MODEL_UNAVAILABLE`.
5. Run onboarding tests.

## Phase 5: Review Context Reuse

1. Identify where due review facts and latest visible attempt facts are loaded.
2. Add review domain adapter for safe context:
   - due reason
   - weak points
   - latest visible attempt facts
   - variant rationale
   - recommended review strategy
3. Keep FSRS, `ReviewState`, `ReviewLog`, and `Attempt(review_submit)` writes outside SDK code.
4. Ensure model failure or unsafe text still maps to `MODEL_UNAVAILABLE`.
5. Run review tests.

## Validation Commands

Focused backend checks:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py tests/test_onboarding_m2.py tests/test_reviews_m4.py
```

If `uv` shim fails on this machine:

```powershell
.\aearn\services\api\.venv\Scripts\python.exe -m pytest .\aearn\services\api\tests\test_llm_integration.py .\aearn\services\api\tests\test_learning_sessions_m3.py .\aearn\services\api\tests\test_onboarding_m2.py .\aearn\services\api\tests\test_reviews_m4.py
```

Static checks when runtime edits are ready:

```powershell
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api lock --check
```

Run desktop check only if API contract or frontend-facing SSE payloads change:

```powershell
pnpm --dir .\aearn desktop:check
```

## Risky Files

- `aearn/services/api/app/services/learning_conversation.py`
- `aearn/services/api/app/services/plan_generator.py`
- `aearn/services/api/app/services/review_repository.py`
- `aearn/services/api/app/agents/sdk_runtime.py`
- `aearn/services/api/app/agents/guardrails.py`
- `aearn/services/api/app/agents/learning_conversation_agent.py`
- `aearn/services/api/app/agents/onboarding_plan_agent.py`
- `aearn/services/api/app/agents/review_coach_agent.py`
- `aearn/services/api/tests/test_llm_integration.py`
- `aearn/services/api/tests/test_learning_sessions_m3.py`
- `aearn/services/api/tests/test_onboarding_m2.py`
- `aearn/services/api/tests/test_reviews_m4.py`

## Rollback Points

- If shared abstraction becomes too broad, keep only extracted sanitization/summary helpers and leave domain clients explicit.
- If onboarding/review persistence is unclear, keep summaries ephemeral for those domains and continue only with safe recent context.
- If learning page regresses, revert learning migration while leaving shared primitives unused.
- If model-key-free tests become brittle, split shared primitive tests from route-level contract tests.

## Review Gate Before Start

Implementation should start only after the user confirms:

- Shared layer must preserve domain-specific summary schemas instead of one global summary schema.
- No database migration unless implementation evidence shows current state fields are insufficient.
