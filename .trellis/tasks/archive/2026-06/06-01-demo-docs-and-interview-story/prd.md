# Demo docs and interview story

## Goal

Document the agent architecture story, capability boundaries, demo flows, and interview-ready tradeoffs.

## Confirmed Facts

- `docs/qa/learning-graph-runtime-demo-story.md` already documents the graph runtime vertical slice.
- `docs/README.md` is the source-of-truth docs index.
- Parent task requires documentation explaining what is fully supported now, what is scaffolded for later, and why the tradeoffs are intentional.

## Requirements

- Add an interview-ready agent capability hardening demo story covering architecture, boundaries, demo flow, and tradeoffs.
- Clearly state current supported boundaries: Python execution is real; other mainstream languages are grounded/scaffolded but not executable until runners exist.
- Explain graph/service/repository responsibility split, tool intent boundary, learner profile memory signals, RAG grounding, routing/handoff, and observability.
- Link the new document from `docs/README.md`.
- Keep the protected HTML prototype untouched.

## Acceptance Criteria

- [ ] New or updated docs provide a concise demo path for review/interview use.
- [ ] Docs distinguish fully supported behavior from scaffolded/future runner support.
- [ ] Docs name the key validation commands and regression proof points.
- [ ] `docs/README.md` links the demo/interview story.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
