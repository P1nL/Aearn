# Optimize Learning Prompt And Context Implementation Plan

## Preconditions

- Stay in planning until the user reviews/approves PRD and design.
- Do not touch `.claude/settings.local.json` or `docs/.obsidian/`.
- Before editing runtime code, load relevant backend specs via `trellis-before-dev`.

## Implementation Steps

1. Inspect existing backend specs and tests related to learning conversation and LLM integration.
2. Add or extend tests for prompt/context behavior:
   - Diagnosis-first reply policy.
   - Direct-answer request redirects to partial guidance.
   - Safe summary construction excludes hidden/reference/provider/API-key/direct-answer content.
   - LLM summary failure falls back without breaking the main learning response.
   - Summary refresh uses threshold/staleness rules, not every-turn refresh.
3. Add a learning context summary module or helper near `learning_conversation.py`.
4. Implement safe message selection and sanitization from `learning_messages`.
   - Keep up to 4 recent safe messages by default.
   - Optionally merge adjacent very short learner messages before counting.
5. Implement LLM-generated safe summary with:
   - dedicated prompt,
   - sanitized inputs,
   - output guardrail,
   - deterministic fallback.
6. Persist validated summary state under `learning_sessions.learning_stage_state_json.conversation_summary`.
7. Implement threshold/staleness refresh logic using persisted summary metadata and recent `learning_messages`.
8. Extend `_build_messages` to include:
   - `conversation_context.safe_summary`,
   - `conversation_context.recent_safe_messages`,
   - `response_policy`,
   - diagnosis-first style rules.
9. Refine prompt text for all learning stages:
   - `concept_intro`,
   - `concept_qna`,
   - `readiness_check`,
   - `practice_support`.
10. Run targeted backend tests and fix regressions.
11. Consider whether docs need a small update to API/architecture behavior.

## Validation Commands

Preferred targeted checks:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_llm_integration.py tests/test_learning_sessions_m3.py
```

If `uv` shim fails on this machine, use the service-local Python fallback:

```powershell
.\aearn\services\api\.venv\Scripts\python.exe -m pytest .\aearn\services\api\tests\test_llm_integration.py .\aearn\services\api\tests\test_learning_sessions_m3.py
```

Run formatting/static checks only if discoverable and scoped to touched backend files.

## Rollback Points

- If summary persistence becomes too invasive, keep summary ephemeral and recomputed from recent messages.
- If `learning_stage_state_json` becomes too crowded, isolate summary fields under one versioned `conversation_summary` key before considering a new table.
- If LLM summary introduces instability, keep the interface but temporarily force deterministic fallback.
- If prompt changes break existing concept-first behavior, keep summary plumbing and revert only response policy wording.

## Review Gate

Implementation can start only after the user accepts:

- LLM-generated summary with threshold/staleness refresh.
- Diagnosis-first tutor behavior.
- Direct-answer requests becoming concrete partial guidance, not full refusal or full answer.
