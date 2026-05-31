# Learning Graph Real Orchestration

## Goal

Make LangGraph the real orchestration layer for the learning page flow.

## Requirements

- Graph owns decisions for `concept_intro`, `concept_check`, `concept_repair`, `practice_offer`, and `practice_support`.
- `learning_conversation.py` remains responsible for API response adaptation, SSE framing, idempotency, model error mapping, and durable writes.
- Graph output must represent tool calls and stage transitions as intents that services apply safely.
- Existing JSON/SSE contracts for `/api/learning-sessions/{session_id}/messages` remain stable.
- Feature flag rollback remains available until parity tests prove the graph path is stable.

## Acceptance Criteria

- [ ] Learning message route invokes the graph as the primary orchestration path when enabled.
- [ ] Graph output replaces `_determine_transition()` and related ad-hoc stage decision branches.
- [ ] Stage updates and tool calls are applied through existing service/repository functions.
- [ ] Existing M3 learning tests pass with graph orchestration enabled.
- [ ] Flag-off fallback remains available during migration.
