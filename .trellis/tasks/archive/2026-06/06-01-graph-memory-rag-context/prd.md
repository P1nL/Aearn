# Graph memory RAG context

## Goal

Inject learner profile and retrieved teaching material into the learning graph context using typed contracts and predictable fallbacks.

## Requirements

- Add typed graph context contracts for learner memory and teaching-material RAG context.
- Keep memory/RAG assembly in the service layer; graph nodes and orchestration graphs must only consume bounded context and must not read from repositories or write durable state.
- When `LANGGRAPH_ENABLED=true`, pass bounded learner profile summary and current-knowledge-point scoped teaching chunks into both the learning graph state and orchestration graph input.
- Reuse local persisted teaching chunks through `ensure_current_knowledge_point_chunks()` and `search_chunks()`; do not add real-time web search or unallowlisted document fetching in this task.
- Keep fallback deterministic: missing profile, missing chunks, empty query, no search match, or graph failure must still complete through existing response paths.
- Preserve existing public learning API response shape and keep graph memory/RAG context internal.
- Do not inject hidden tests, reference solutions, raw prompts, provider payloads, secrets, cross-user memory, or cross-knowledge-point chunks.
- Preserve `LANGGRAPH_ENABLED=false` behavior.

## Acceptance Criteria

- [x] Typed contracts exist for graph memory snapshots and RAG context.
- [x] Learning graph state includes bounded `memory_snapshot` and `rag_context`.
- [x] Orchestration graph input receives the same bounded context when graph runtime is enabled.
- [x] RAG retrieval is scoped to `knowledge_point_id` and falls back safely when chunks are absent or search has no direct match.
- [x] Public learning message responses do not expose `rag_context`, `memory_snapshot`, graph diagnostics, hidden tests, reference solutions, raw prompts, provider payloads, or secrets.
- [x] Focused tests cover typed contract bounding/redaction, state builder wiring, orchestration wiring, route-level fake graph capture, and fallback behavior.
- [x] Existing graph/service boundary remains intact: durable writes stay in services/repositories.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
