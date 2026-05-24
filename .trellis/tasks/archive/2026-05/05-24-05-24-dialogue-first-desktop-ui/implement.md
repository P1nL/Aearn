# Implementation Plan

## Checklist

1. Confirm frontend specs and active task boundary.
2. Remove fixed home/review canned messages from the runtime conversation feed.
3. Replace sidebar fallback lesson titles with generated-plan entries and useful empty states.
4. Wire sidebar knowledge point clicks to `openLearningSession`.
5. Rework `LearningWorkspacePage` empty state and scroll behavior.
6. Update CSS so the thread scrolls independently and composer stays usable.
7. Run `pnpm --dir .\aearn desktop:check`.
8. If practical, run a local browser smoke against `http://127.0.0.1:1420`.
9. Review `git status --short` and report frontend task files separately from unrelated docs changes.

## Validation Commands

```powershell
pnpm --dir .\aearn desktop:check
```

```powershell
git status --short
```

## Files In Scope

- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/components/SidebarNav.tsx`
- `aearn/apps/desktop/src/components/SideContext.tsx`
- `aearn/apps/desktop/src/lib/appContent.ts`
- `aearn/apps/desktop/src/lib/learningHelpers.ts`
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`
- `aearn/apps/desktop/src/styles.css`

## Stop Conditions

- If the backend SSE contract has changed, stop and reconcile with `docs/architecture/api-contract.md`.
- If a change requires archiving or deleting the protected design prototype, stop and ask the user.
- If validation fails due to unrelated existing docs changes, keep frontend fixes scoped and report the unrelated blocker separately.
