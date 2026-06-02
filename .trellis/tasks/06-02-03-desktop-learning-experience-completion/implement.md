# 03 Desktop Learning Experience Completion Implementation Plan

## Pre-Implementation Checks

- [ ] Read `docs/product/frontend-interaction-spec.md`.
- [ ] Read `docs/qa/acceptance-test-plan.md`.
- [ ] Read frontend Trellis spec via `trellis-before-dev` before editing.
- [ ] Confirm unrelated dirty files remain excluded from this child.

## Implementation Steps

1. Audit current desktop loop against the acceptance plan.
   - Onboarding route card and plan confirmation.
   - Dashboard/resume banner and bootstrap route selection.
   - Learning workspace concept-first sessions, generated exercise cards, and post-action feedback.
   - Review queue/warmup/variant/submission states.
   - Notes drawer/page save failure behavior.
   - Settings category/diagnostic disclosure.

2. Patch the smallest set of desktop files needed.
   - Prefer `App.tsx`, page components, stores, `appContent.ts`, `desktopLabels.ts`, and learning feature components.
   - Avoid adding new dependencies unless a strong existing-project reason appears.
   - Keep copy in Simplified Chinese for learner-facing UI.

3. Patch API guards or backend tests only if visible desktop behavior depends on contract accuracy.
   - Keep changes additive.
   - Do not introduce new runner, grounding, environment doctor, export/delete/reset, or adaptive exercise behavior.

4. Update docs/spec only for durable rules discovered during implementation.
   - If a recurring UI contract is learned, update `.trellis/spec/frontend/*` or the closest existing spec file.
   - Avoid duplicating the product spec.

5. Run focused verification.
   - `pnpm --dir .\aearn desktop:check`
   - Focused backend tests if touched, expected candidates:
     - `uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py tests/test_dashboard_resume_m6.py tests/test_reviews_m4.py tests/test_notes_m5.py tests/test_learner_profile.py -q`
   - `python .\.trellis\scripts\task.py validate`
   - `git diff --check`

6. Finish the child.
   - Run `task.py archive` only after implementation, verification, and task-specific commit are complete.
   - Keep parent task in planning.
   - Continue to next child in parent order after archiving this child.

## Risky Files

- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/stores/useAppStore.ts`
- `aearn/apps/desktop/src/stores/useNotesStore.ts`
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`
- `aearn/apps/desktop/src/pages/ReviewPage.tsx`
- `aearn/apps/desktop/src/pages/SettingsPage.tsx`
- `aearn/apps/desktop/src/features/learning/ExerciseWorkbench.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`

## Review Gate

The user has requested direct sequential execution of the remaining children. Treat that as approval to proceed after this planning set validates, while still keeping the parent task itself in planning.

## Rollback Points

- Desktop UI patches can be reverted independently from backend API changes.
- If API guard tightening breaks build due to an existing backend mismatch, either adjust the backend payload/test or revert the guard and document the mismatch.
- If a note-save change risks data loss, stop and preserve the draft before continuing.
