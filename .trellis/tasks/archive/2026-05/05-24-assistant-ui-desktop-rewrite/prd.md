# Assistant UI desktop rewrite

## Goal

Rewrite the Aearn desktop frontend shell and conversation layer around assistant-ui, then reattach Aearn-specific learning route, exercise workbench, run/submit/hint/explain actions, notes drawer, review entry, and existing FastAPI/SSE contracts without reintroducing prototype fallback content.

## Requirements

- Rewrite the desktop UI shell and conversation layer around `assistant-ui` or an assistant-ui-compatible architecture.
- Keep Aearn's backend API, FastAPI SSE endpoints, Zustand state ownership, and learning business contracts as the source of truth.
- Do not migrate scoring, FSRS scheduling, Attempt persistence, runner results, or learning plan state into frontend-only logic.
- Preserve or reattach Aearn-specific components:
  - generated learning route tree
  - active learning thread
  - generated exercise card / `ExerciseWorkbench`
  - run preview / visible tests / submit
  - hint / explain error / check explanation
  - note drawer and notes entry
  - review entry and review page
  - settings diagnostics
- Replace the current custom `ThreadMessages` + composer implementation with a mature assistant-style thread/composer layer.
- Support `POST /api/learning-sessions/{session_id}/messages` streaming through the existing Aearn SSE contract.
- Streaming deltas must update one assistant message, not create one bubble per chunk.
- Cold start must show an empty state and generated-route guidance, not hard-coded prototype lessons or canned chat.
- Sidebar titles must come from generated plan modules/knowledge points.
- The UI must remain usable at desktop and narrow widths.
- Do not delete or archive `docs/design/learning-agent-claude-desktop-framework.html`; it is no longer the runtime direction but remains a protected design asset.

## Acceptance Criteria

- [ ] A new assistant-style thread/composer layer is integrated or implemented.
- [ ] Home conversation starts empty before a real user/session event.
- [ ] Active session composer sends `{ role: "user", content, client_message_id }` to the Aearn SSE message endpoint.
- [ ] `agent_message.delta` appends and `agent_message.content` replaces the current assistant bubble.
- [ ] Duplicate sends are disabled while streaming.
- [ ] No active session -> composer disabled with visible guidance and no backend call.
- [ ] Learning route/sidebar uses generated plan data and has explicit empty states.
- [ ] Exercise workbench still runs preview, visible tests, submit, hint, explain-error, and check-explanation through existing API wrappers.
- [ ] Notes drawer remains attached to the current knowledge point.
- [ ] Review and settings routes remain accessible.
- [ ] No prototype fallback messages, fixed route examples, or fake draft modules exist in runtime code.
- [ ] `pnpm --dir .\aearn desktop:check` passes.
- [ ] Browser smoke verifies cold start, active session thread, composer disabled/enabled states, and sidebar route generation.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
