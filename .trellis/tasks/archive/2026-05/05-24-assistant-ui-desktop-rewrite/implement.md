# Implementation Plan

## Phase 1: Dependency and Adapter Decision

1. Inspect assistant-ui install requirements and runtime APIs.
2. Decide whether to add `@assistant-ui/react` directly or implement a compatible internal adapter first.
3. If adding a dependency, update only the desktop workspace package files and run install/check commands.

## Phase 2: Thread and Composer Rewrite

1. Extract a dedicated `AssistantLearningPage`.
2. Replace `ThreadMessages` and current composer with assistant-style components.
3. Map Aearn `ConversationMessage` to assistant thread messages.
4. Keep SSE send flow on `POST /api/learning-sessions/{session_id}/messages`.
5. Ensure deltas update one assistant bubble.

## Phase 3: Reattach Aearn Components

1. Reattach generated learning route tree.
2. Reattach `ExerciseWorkbench` as a session card/message area.
3. Reattach note drawer entry and current knowledge point context.
4. Keep review, notes, and settings routes reachable.

## Phase 4: Remove Prototype Residue

1. Search runtime code for hard-coded lesson/demo strings.
2. Remove canned messages, fixed sidebar route examples, and fake draft modules.
3. Preserve explicit empty states.

## Phase 5: Verification

Run:

```powershell
pnpm --dir .\aearn desktop:check
```

Run browser smoke:

```text
http://127.0.0.1:1420
```

Smoke assertions:

- cold start has no fake message article
- sidebar route empty state appears before plan
- generated plan titles appear after onboarding or bootstrap restore
- active session composer is enabled
- no active session composer is disabled
- stream updates one assistant bubble
- exercise workbench actions remain available

## Files Expected In Scope

- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/pages/LearningWorkspacePage.tsx`
- `aearn/apps/desktop/src/components/ThreadMessages.tsx`
- `aearn/apps/desktop/src/components/SidebarNav.tsx`
- `aearn/apps/desktop/src/components/SideContext.tsx`
- `aearn/apps/desktop/src/features/learning/*`
- `aearn/apps/desktop/src/stores/useAppStore.ts`
- `aearn/apps/desktop/src/hooks/useSSE.ts`
- `aearn/apps/desktop/src/styles.css`

## Stop Conditions

- Stop if assistant-ui requires a full Tailwind/shadcn migration that would exceed the MVP rewrite scope.
- Stop if backend API or SSE shape no longer matches `docs/architecture/api-contract.md`.
- Stop if protected prototype assets would need deletion.
