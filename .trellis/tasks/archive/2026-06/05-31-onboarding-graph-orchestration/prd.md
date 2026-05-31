# Onboarding Graph Orchestration

## Goal

Make LangGraph the real orchestration layer for onboarding conversation and route generation.

## Requirements

- Graph owns onboarding flow decisions for slot collection, StructuredJudgement routing, clarification, route generation, route revision, and plan confirmation gating.
- Onboarding services still own durable writes, idempotency, route-card persistence, and public response shape.
- Ambiguous, unsupported, or missing judgement outcomes must not advance durable onboarding state.
- Existing onboarding route-card and latest-card-wins behavior must remain stable.

## Acceptance Criteria

- [ ] Onboarding message path invokes onboarding graph as primary orchestration when enabled.
- [ ] StructuredJudgement decisions are represented in graph state and transitions.
- [ ] Route generation/revision/confirmation gates are graph-owned but service-applied.
- [ ] Existing onboarding M2 tests pass with graph orchestration enabled.
- [ ] Flag-off rollback remains available during migration.
