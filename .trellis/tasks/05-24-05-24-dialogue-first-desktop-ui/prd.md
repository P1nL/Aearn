# Rebuild desktop dialogue UI

## Goal

Replace the unusable prototype-shaped desktop UI with a dialogue-first frontend that starts empty, uses generated plan titles in the sidebar, supports a scrollable conversation thread, and keeps the active learning composer wired to real session SSE messages.

## Requirements

- Treat `aearn/apps/desktop/` as the runtime source. Do not implement in or depend on `docs/design/learning-agent-claude-desktop-framework.html`.
- Replace the prototype-shaped learning screen with a dialogue-first UI that is actually usable for active session conversation.
- The learning conversation area starts empty before a real session; do not inject fixed demo messages such as DOM/Python canned examples.
- The conversation thread must be vertically scrollable inside the workspace and keep the bottom composer reachable.
- The left sidebar must derive learning and note titles from the generated user plan and knowledge points, not fixed hard-coded lesson titles.
- If no plan exists, sidebar empty states must clearly say that generated route items will appear after onboarding.
- The active learning composer must stay connected to `POST /api/learning-sessions/{session_id}/messages` through the existing POST SSE hook.
- If no active learning session exists, the composer must not call the backend and must show visible guidance.
- Preserve backend-owned boundaries: no frontend scoring, FSRS scheduling, Attempt labels, or fake completion states.
- Preserve the existing onboarding, review, notes, and settings flows unless a change is needed to make the dialogue UI usable.

## Acceptance Criteria

- [x] Home dialogue area shows no fixed canned conversation before a real session.
- [x] After onboarding creates a plan, sidebar learning entries use generated knowledge point titles.
- [x] Clicking a generated learning entry opens the matching learning session.
- [x] Conversation content can scroll independently from the app shell, and new messages remain visible without using `scrollIntoView`.
- [x] Composer sends `role=user`, `content`, and a fresh `client_message_id` only when an active session exists.
- [x] Streaming `agent_message` events update one assistant bubble and `done` clears busy state.
- [x] Offline/no-session states are visible and disable duplicate or invalid sends.
- [x] `pnpm --dir .\aearn desktop:check` passes.
- [x] Existing unrelated docs-freshness changes remain outside this task's code scope.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
