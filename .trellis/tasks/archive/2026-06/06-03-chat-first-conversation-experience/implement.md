# Chat-first conversation experience implementation plan

## Checklist

- [x] Load backend coding guidelines before editing.
- [x] Add failing focused tests for the Onboarding conversation-intent matrix:
  - advisory question
  - capability question
  - comparison question
  - direct slot answer
  - route-ready hallucination blocking
  - ambiguous slot clarification
  - unsupported language
- [x] Update Onboarding visible-message normalization so valid chat-first answers are preserved and missing-slot follow-up is appended instead of replacing non-route-ready answers.
- [x] Avoid appending a second fixed language follow-up when the generated answer already asks a semantically equivalent language-selection question.
- [x] Keep route-ready hallucination blocking behavior intact.
- [x] Update Onboarding system prompt with an explicit Claude Code / Codex-like response policy: answer latest intent first, keep workflow state private, ask at most one useful follow-up.
- [x] Add targeted language for AI Agent / agent language-advice behavior within the supported public language set.
- [x] Treat TypeScript / TS as an independent public route: do not return `LANGUAGE_NOT_SUPPORTED` and do not bridge it to JavaScript.
- [x] Keep unsupported-language errors intact for C++ and Rust.
- [x] Add learning-page duplicate-send protection for quick replies and composer sends while SSE streaming is pending.
- [x] Update support-language boundary docs so public course selection, teaching-grade runner limits, and C++/Rust unsupported route choices are not conflated.
- [x] Update Learning page composer SSE error copy to explain `MODEL_UNAVAILABLE`, `STREAM_INCOMPLETE`, and connection/SSE failures by stable `error.code` instead of using one generic incomplete-answer message.
- [x] Run focused tests:
  - `uv --directory .\aearn\services\api run python -m pytest tests\test_onboarding_m2.py -q`
  - `uv --directory .\aearn\services\api run python -m pytest tests\test_onboarding_graph.py -q`
- [x] Run quality checks:
  - `uv --directory .\aearn\services\api run ruff check .`
  - `uv --directory .\aearn\services\api run python -m mypy app`
  - `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-03-chat-first-conversation-experience`
  - `git diff --check`
- [x] Rerun quality checks after the Learning page error-copy and language-boundary follow-up edits.

## Risky Files

- `aearn/services/api/app/services/conversations/onboarding_conversation.py`: can accidentally loosen readiness safety if normalization is changed too broadly.
- `aearn/services/api/app/routes/onboarding.py`: SSE ordering and persistence must remain stable.
- `aearn/services/api/tests/test_onboarding_m2.py`: several tests require PostgreSQL; preserve existing skip behavior.

## Rollback Points

- If focused tests show route-card generation with ambiguous slots, restore the old replacement behavior and narrow the change.
- If unsupported-language behavior changes, revert only the onboarding route/error handling changes and keep prompt-only changes for review.
- If mypy or ruff failures appear outside touched files, inspect before changing unrelated code.

## Review Gate Before Start

Implementation may start after this planning set is accepted and `task.py start` moves the task to `in_progress`.
