# Implementation Checklist

- [ ] Extract static content and pure helper functions from `App.tsx` into dedicated support modules.
- [ ] Extract shared shell/support components (`SidebarNav`, `SideContext`, `ThreadMessages`, `ApiHealthChip`, and related helpers).
- [ ] Extract `OnboardingPage` and `PlanDraftPanel`, keeping plan generation/confirmation behavior unchanged.
- [ ] Extract `LearningWorkspacePage` and the M3 workbench subtree.
- [ ] Extract M3 result/assist subcomponents (`RuntimeFeedback`, `HintHistoryCard`, `ErrorFeedbackPane`, `ExplanationCheckPanel`, `SubmissionSummary`).
- [ ] Extract `ReviewPage`, `NotesPage`, and `SettingsPage`.
- [ ] Reduce `App.tsx` to app shell / bootstrap / route orchestration only.
- [ ] Run desktop validation and perform an additional smoke pass if the refactor touches run/submit/hint/explain behavior.

## Validation

- `pnpm --dir .\aearn desktop:check`

Optional but recommended if route/workbench logic moves significantly:

- run local desktop app and smoke the existing M3 path

## Review Gates

- Before `task.py start`: confirm the task remains a structure refactor, not a router/store rewrite.
- Before coding: confirm page/feature ownership is clear enough that `App.tsx` will not keep all page-local state by inertia.
- Before finish: verify `App.tsx` no longer contains inline page/workbench component definitions and `desktop:check` is green.

## Rollback Notes

- Keep extraction steps incremental so broken wiring can be reverted cleanly.
- Avoid mixing refactor with unrelated visual or backend edits; that keeps rollback to a single frontend commit.
