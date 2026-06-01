# Learning graph runtime hardening

## Goal

Turn the learning page LangGraph path into the primary runtime orchestration slice with clear graph/service boundaries, state, tools, streaming, interrupts, and tests.

## Requirements

- Make the learning page the complete LangGraph runtime vertical slice.
- Keep onboarding and review as graph orchestration plus service persistence unless a later requirement explicitly changes that boundary.
- Define graph/service/API/SSE responsibilities before moving behavior into graph nodes.
- Route memory, RAG context, tool-loop decisions, human interrupts, and event streaming through typed graph contracts.
- Preserve existing user-facing learning behavior while reducing hard-coded orchestration in the learning conversation service.

## Acceptance Criteria

- [ ] Graph runtime boundary is documented and accepted before implementation starts.
- [ ] Checkpoint/thread state strategy is explicit and does not move durable service persistence into graph nodes.
- [ ] Tool-loop ownership is graph-driven where appropriate and still emits typed service actions for writes.
- [ ] Learner profile and teaching material retrieval can be injected into graph context with safe fallbacks.
- [ ] Human interrupt points are modeled for ambiguous stage transitions or unsafe actions.
- [ ] Graph events adapt to the existing learning page streaming/API contract.
- [ ] Onboarding and review remain behaviorally consistent without being forced into full runtime migration.
- [ ] Runtime branches, fallbacks, event mapping, and graph/service action execution are covered by focused tests.

## Task Tree

```text
learning-graph-runtime-hardening
├─ graph-runtime-boundary-contract
├─ graph-checkpoint-thread-state
├─ graph-owned-tool-loop
├─ graph-memory-rag-context
├─ graph-human-interrupt-checkpoints
├─ graph-event-stream-adapter
├─ graph-cross-page-experience-parity
├─ graph-runtime-tests
└─ graph-demo-story
```

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
