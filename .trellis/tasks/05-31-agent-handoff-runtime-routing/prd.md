# Agent Handoff Runtime Routing

## Goal

Use `router.py` and SDK handoff target construction in production conversation routing so agent selection is no longer only test-covered plumbing.

## Requirements

- Call router logic from the real learning conversation path using session stage and learner message evidence.
- Build handoff targets only from safe, current-session agents.
- Preserve existing endpoint contracts when routing has no match.
- Keep the default teaching agent path as fallback.
- Avoid exposing SDK handoff internals in public JSON/SSE.

## Acceptance Criteria

- [x] Real learning message handling invokes route selection.
- [x] Matched routes pass handoff targets into SDK agent construction.
- [x] No-match routes preserve current behavior.
- [x] Tests prove routing/handoff plumbing is connected to production code.
- [x] Focused backend tests, lint, mypy, and task validation pass.
