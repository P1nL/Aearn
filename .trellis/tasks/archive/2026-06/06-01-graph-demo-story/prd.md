# Graph demo story

## Goal

Document the learning graph runtime vertical slice and explain why onboarding/review remain graph orchestration plus service persistence.

## Requirements

- Add a concise demo/readiness document for the `02-learning-graph-runtime-hardening` slice.
- Explain the learning page graph runtime path end to end:
  - service-owned context loading
  - graph memory/RAG context injection
  - checkpoint thread config
  - graph-owned stage/tool intent decisions
  - service boundary validation and durable writes
  - SSE event mapping to the existing public contract
- Explain why onboarding and review remain graph-assisted orchestration paths, not full graph runtime migrations.
- Include a demo script with local commands, expected evidence, and known fallback cases.
- Keep the document honest about current language runtime boundaries: TypeScript/Go/C#/Rust/SQL are not executable yet, and Java/C++ still use unsupported/planned runner fallbacks.
- Do not add new product promises, routes, UI surfaces, live web browsing, or runtime execution capabilities.

## Acceptance Criteria

- [x] A source-of-truth linked document describes the learning graph runtime vertical slice and cross-page boundary.
- [x] The document contains a demo script that can be followed from local checkout using existing commands/tests.
- [x] The document explicitly distinguishes graph decisions from service/repository/API/SSE ownership.
- [x] The document lists fallback and safety evidence for flag-off, graph failure, invalid intents, idempotency replay, and redaction.
- [x] Docs index points readers to the new demo story without replacing architecture/API/QA source-of-truth documents.

## Notes

- This is a documentation/demo closeout task for the `02` graph hardening subtree.
