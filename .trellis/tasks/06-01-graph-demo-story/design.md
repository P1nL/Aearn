# Design

## Document Placement

Add a QA/demo document under `docs/qa/` and link it from `docs/README.md` as an auxiliary handoff document. The architecture source of truth remains `docs/architecture/langgraph-state-machine.md`; the new document is a demo narrative and evidence checklist, not a replacement specification.

## Story Shape

The document should answer three questions:

- What exactly is the learning graph runtime vertical slice?
- Why do onboarding and review use graph decision validation but keep service/repository persistence?
- How can a reviewer verify the slice locally without live model or web dependencies?

## Required Boundaries

The story must preserve the current architecture:

- Graph owns routing decisions, stage transitions, and typed intent production.
- Service owns graph invocation, boundary validation, intent execution, idempotency replay, and durable write orchestration.
- Repository owns SQL and persistence invariants.
- API owns request/response envelopes.
- SSE owns public event vocabulary and frame order.

## Compatibility

The document must not claim new runtime support or public language support. It may reference existing tests and commands as evidence, but should not require external documentation fetches or live LLM calls.

## Rollback

Rollback is removing the new doc and the README link. No runtime behavior changes are expected.
