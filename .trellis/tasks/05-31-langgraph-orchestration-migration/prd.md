# LangGraph Orchestration Migration

## Goal

Fully migrate Aearn's three main agent-orchestrated flows to LangGraph-owned orchestration while preserving existing public API/SSE contracts, idempotency, transaction boundaries, and feature-flag rollback.

This is a full migration program, not a partial experiment. The parent task must not be archived until Learning, Onboarding, and Review orchestration have all moved from imperative service-level branching to graph-owned flow decisions.

## Scope

- Learning page / learning session flow.
- Onboarding conversation and route generation flow.
- Review page / FSRS review flow.
- Shared graph state, result, error, and persistence-boundary contracts needed by those flows.

## Requirements

- Each main flow must have a graph entrypoint invoked from a real production route or service path.
- Graphs own orchestration decisions: stage transitions, next node selection, tool-intent emission, and recovery routing.
- Services and repositories continue to own durable writes, transactions, idempotency replay, public response envelopes, and SSE framing.
- Each graph migration must support rollback through feature flags until the migrated flow is release-safe.
- The final parent acceptance requires no remaining main-page orchestration logic hidden in ad-hoc service if/else branches, except API validation, idempotency, persistence, and response adaptation.
- Public JSON/SSE response shapes remain stable unless a child PRD explicitly documents a contract migration.
- Raw graph errors, provider payloads, prompts, hidden tests, `solution_reference`, submitted code, and secrets must not reach public responses or logs.

## Child Workflow

| Order | Child | Responsibility |
|---|---|---|
| 1 | `graph-shared-runtime-contracts` | Shared graph state/result/error contracts and adapters. |
| 2 | `learning-graph-real-orchestration` | Learning page orchestration migration. |
| 3 | `onboarding-graph-orchestration` | Onboarding flow orchestration migration. |
| 4 | `review-graph-orchestration` | Review flow orchestration migration. |

## Cross-Child Acceptance Criteria

- [ ] Shared graph contracts are used by all migrated flows.
- [ ] Learning page orchestration is graph-owned for concept intro, concept check, repair, practice offer, and practice support.
- [ ] Onboarding orchestration is graph-owned for slot collection, structured judgement, route generation, route revision, and plan confirmation gating.
- [ ] Review orchestration is graph-owned for review start, review exercise result, FSRS update coordination, and review feedback.
- [ ] Feature flags allow rollback while each child is being migrated.
- [ ] Final state has no major page left on old ad-hoc orchestration as the primary path.
- [ ] Full backend tests, lint, type-check, and relevant desktop checks pass before parent archival.

## Out of Scope

- Rewriting repository persistence into graph nodes.
- Introducing new public languages or new exercise types.
- Replacing deterministic API validation, idempotency storage, or SSE framing with graph logic.
