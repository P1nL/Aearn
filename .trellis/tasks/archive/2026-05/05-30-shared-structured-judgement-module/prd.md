# Extract shared structured judgement module

## Goal

Extract the onboarding-specific structured slot judgement mechanism into a backend shared module that can be reused by onboarding, learning, review, notes, and future AI-driven pages.

The product value is to keep one consistent rule across pages: AI may judge whether a user answer is clear, ambiguous, missing, unsupported, or otherwise not actionable, but backend-owned policy decides whether a value can be persisted or whether a tool/action may run.

## Confirmed Facts

- The current onboarding fix introduced `SlotJudgement`, `slot_statuses`, and `normalize_extracted_slots(...)` to prevent ambiguous values from being written as durable slots.
- The current implementation is still coupled to onboarding files:
  - `aearn/services/api/app/agents/onboarding_slot_extractor.py`
  - `aearn/services/api/app/services/onboarding_conversation.py`
  - `aearn/services/api/app/routes/onboarding.py`
- Onboarding needs to preserve existing route-card behavior: route-ready turns emit a short assistant message plus `show_learning_route`, not a long natural-language route.
- `time_budget` remains optional for initial onboarding route generation, but ambiguous optional revisions must trigger clarification before route regeneration.
- Learning already has a concept-check flow where a structured judgement should drive the natural-language response and practice unlock behavior.
- The shared module must not own durable writes, repositories, idempotency records, or page-specific business actions.

## Requirements

- Introduce a page-agnostic backend module for structured AI judgements.
- The shared module must represent at least:
  - judgement status such as `confirmed`, `ambiguous`, `missing`, and `unsupported`
  - evidence, reason, ambiguity type, and clarification question
  - policy-owned field/action readiness rules
  - priority-based clarification question selection
- The shared module must support page-specific policy configuration rather than hardcoding onboarding slots.
- Onboarding must migrate from its local `SlotJudgement` / normalization helpers to the shared module without changing public SSE behavior.
- The shared module must be usable by learning/review/notes flows without importing onboarding-specific code.
- This task should not migrate the real learning `concept_check` flow; provide a reusable integration pattern or test example only.
- Backend code must continue to treat model output as advisory; only backend policy may decide whether to persist a field or trigger an action/tool.
- The implementation must keep SDK/LLM modules free of database writes and keep durable writes in feature services/repositories.
- The implementation must preserve model-key-free tests through fake clients and fixtures.

## Acceptance Criteria

- [ ] A shared backend module exists for structured judgement schema and normalization policy.
- [ ] Onboarding no longer defines or owns the generic judgement schema; it imports or wraps the shared module.
- [ ] Onboarding tests still prove ambiguous required slots and ambiguous optional revisions block `show_learning_route`.
- [ ] Onboarding tests still prove unsupported languages return `LANGUAGE_NOT_SUPPORTED` and do not create a route draft.
- [ ] At least one unit test directly covers the shared module independently of onboarding.
- [ ] The shared module exposes a documented integration pattern for other pages, either through docstrings or a small usage example in tests.
- [ ] No page-specific fallback questions or slot names are hardcoded in the shared module.
- [ ] Validation passes for targeted onboarding tests, relevant learning tests, backend lint/type checks, and desktop build.

## Out Of Scope

- Fully migrating learning, review, and notes pages in the same task.
- Changing public API payloads or frontend generative UI contracts.
- Adding new language support such as TypeScript/Rust/Go.
- Changing database schemas.
- Reworking the concept-check product flow beyond providing a reusable backend judgement mechanism.

## Open Questions

- Resolved: this task will migrate onboarding and add shared-module tests/examples only. Real learning `concept_check` migration is deferred to a follow-up task to avoid destabilizing the current learning flow.
