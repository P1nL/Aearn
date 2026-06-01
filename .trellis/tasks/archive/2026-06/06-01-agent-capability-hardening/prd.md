# Agent capability hardening

## Goal

Umbrella task for hardening Aearn's agent capabilities across language support, LangGraph runtime, RAG grounding, learner memory, tools, handoffs, observability, and interview/demo documentation.

## Requirements

- Establish a clear cross-language capability contract before expanding language support.
- Preserve the existing Python subprocess sandbox while extracting runtime execution behind a language runner registry.
- Harden the learning page into the primary LangGraph runtime vertical slice.
- Upgrade teaching material retrieval into language-aware knowledge grounding with allowlisted official or trusted documentation sources.
- Improve learner profile signal quality using stable learning events rather than one-off conversational guesses.
- Keep agent tools behind a typed intent boundary; services and repositories continue to own persistence, transactions, and API contracts.
- Make multi-agent handoff behavior minimally production-useful without replacing all current service orchestration.
- Add observability and regression tests that prove the hardened agent modules are actually connected to production request paths.
- Document the architecture, tradeoffs, and demo story for interview review.

## Acceptance Criteria

- [x] The task tree below exists in Trellis and each child has independently verifiable acceptance criteria before implementation starts.
- [x] The project has an explicit language capability matrix covering lesson generation, RAG grounding, exercise generation, execution, tests, static analysis, review feedback, and UX disclosure.
- [x] Runtime execution is routed through a language runner registry, with Python using the existing sandbox and unsupported languages returning explicit capability-aware responses.
- [x] Learning page LangGraph runtime responsibilities are separated from service persistence responsibilities.
- [x] RAG grounding supports mainstream language source registration and can retrieve cited material by language/topic.
- [x] Learner profile, tools, handoffs, and observability changes are covered by tests and do not regress existing onboarding, learning, or review flows.
- [x] Documentation explains what is fully supported now, what is scaffolded for later, and why those tradeoffs are intentional.

## Task Tree

```text
agent-capability-hardening
├─ 00-language-capability-contract
├─ 01-language-runtime-runner-registry
│  ├─ runner-capability-contract
│  ├─ python-sandbox-adapter
│  ├─ sandbox-security-boundary-hardening
│  ├─ browser-preview-runner-contract
│  ├─ node-typescript-runner-contract
│  ├─ sql-runner-contract
│  ├─ compiled-language-runner-contract
│  └─ runner-registry-tests
├─ 02-learning-graph-runtime-hardening
│  ├─ graph-runtime-boundary-contract
│  ├─ graph-checkpoint-thread-state
│  ├─ graph-owned-tool-loop
│  ├─ graph-memory-rag-context
│  ├─ graph-human-interrupt-checkpoints
│  ├─ graph-event-stream-adapter
│  ├─ graph-cross-page-experience-parity
│  ├─ graph-runtime-tests
│  └─ graph-demo-story
├─ 03-language-knowledge-grounding
│  ├─ grounding-source-registry
│  ├─ official-docs-fetcher
│  ├─ docs-cleaning-and-chunking
│  ├─ language-aware-retrieval
│  ├─ agent-citation-integration
│  ├─ mainstream-language-fixtures
│  └─ grounding-reindex-observability
├─ 04-learner-profile-signal-quality
├─ 05-agent-tool-boundary-cleanup
├─ 06-multi-agent-handoff-minimal
├─ 07-runtime-observability-tests
└─ 08-demo-docs-and-interview-story
```

## Scope Notes

- This task tree is intentionally one umbrella tree plus two deep subtrees: learning graph runtime and language knowledge grounding.
- Do not claim all mainstream languages have full real code execution until the language capability matrix says so.
- Do not move persistence into graph nodes. Graph runtime may decide actions, but services/repositories remain the write boundary.
- `grill-me` is not required before creating this tree because the key architecture decisions are already captured. Use it later if the execution sandbox security model or language support promises need stress testing.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
