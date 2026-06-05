# Verification: learning-doc-panel-flow

## Implementation Status

- Review-approved implementation continued in Phase 2/3 without committing.
- Remaining issues fixed after review:
  - Documentation panel collapse now updates the parent grid column from 420px to a narrow collapsed column.
  - `trigger-concept-check` no longer resets later learning stages back to `concept_check`.
  - `documentation_reading` and `concept_qna` can first-trigger concept checks; `concept_check` replays idempotently.
  - Recent user questions in the same learning session are passed into concept intro generation.
  - Knowledge point documentation uses a user-scoped Redis 24h best-effort cache.
  - Documentation references now prefill the assistant-ui composer via composer runtime, not a brittle DOM value mutation.
  - Learning graph/router/tool transition sets and architecture docs include `documentation_reading`.

## Browser Smoke

- Target: `http://127.0.0.1:1420`
- Verified:
  - Learning session enters documentation reading with right-side document panel.
  - Document panel shows table of contents, expanded first sections, collapsed later sections.
  - Sidebar review item with future `due_at` is disabled and displays `未到期 · 下次 ...`.
  - Code-block reference fills the composer with `引用文档：... 我的问题是：`.
  - `✓ 开始概念检验` returns and renders `show_concept_intro`.
  - Collapsing documentation panel leaves only the `展开文档` tab visible.

## Spec Update

- Added code-spec coverage for the backend documentation-reading flow, user-scoped documentation cache, concept-check trigger, and review-state preview contract in `.trellis/spec/backend/quality-guidelines.md`.
- Added code-spec coverage for the desktop documentation panel, assistant-ui composer prefill, concept trigger card, and disabled future review sidebar behavior in `.trellis/spec/frontend/quality-guidelines.md`.

## Automated Checks

- `uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py -q` -> `70 passed`
- `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_reviews_m4.py -q` -> `45 passed`
- `uv --directory .\aearn\services\api run ruff check app tests/test_learning_sessions_m3.py` -> passed
- `uv --directory .\aearn\services\api run python -m mypy app` -> passed
- `pnpm --dir .\aearn desktop:check` -> passed, with existing Vite large chunk warning
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-04-learning-doc-panel-flow` -> passed
- `git diff --check` -> passed, with expected CRLF conversion warnings only

## Notes

- Documentation content generation remains deterministic from persisted outline/sources/chunks for this MVP path; Redis caches the generated payload for 24 hours when available.
- No commit, archive, deploy, or production data change was performed.
