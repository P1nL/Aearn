# Technical Design

## Architecture

Add a shared pure-Python backend module for structured judgement primitives. The likely location is:

`aearn/services/api/app/agents/structured_judgement.py`

This location matches existing shared agent-context helpers and keeps the schema close to SDK/LLM structured output types. The module must stay pure: no database imports, no route imports, no repository calls, and no feature-specific side effects.

Feature services remain responsible for applying the normalized result to durable state and public responses.

## Core Types

The shared module should define generic types similar to:

- `JudgementStatus = Literal["confirmed", "ambiguous", "missing", "unsupported"]`
- `StructuredJudgement`
- `JudgementFieldPolicy`
- `JudgementPolicy`
- `NormalizedJudgementResult`

The exact names may change during implementation, but the contract should be page-agnostic.

## Normalization Contract

Inputs:

- a mapping of field name to current value
- a mapping of field name to model-produced judgement
- a page-specific policy that defines required fields, optional clarification fields, priority order, fallback questions, and which non-confirmed statuses block action readiness

Outputs:

- sanitized field values where non-confirmed judged fields are cleared
- recomputed `ready` boolean
- selected clarification question
- list or mapping of blocking fields for diagnostics/tests

The shared module must not know about onboarding terms such as `language`, `goal_text`, `target_level`, `time_budget`, `show_learning_route`, or `LANGUAGE_NOT_SUPPORTED`.

## Onboarding Migration

Onboarding should keep its page-specific policy near `onboarding_conversation.py` or a small onboarding adapter module. That policy supplies:

- required fields: `language`, `goal_text`, `target_level`
- optional clarification fields: `time_budget`, `focus`
- clarification priority: `language`, `goal_text`, `target_level`, `time_budget`, `focus`
- onboarding fallback questions
- rule that missing optional `time_budget` does not block initial route generation, but ambiguous or unsupported optional revisions do block regeneration

`onboarding_slot_extractor.py` should reuse the shared judgement schema, while `ExtractedSlots` remains onboarding-specific.

## Future Page Integration

Learning/review/notes should be able to define their own policies:

- learning concept check: fields may include answer correctness, confidence, missing explanation, misconception, or direct-answer request
- review: fields may include answer quality, recall confidence, unsupported state, or needs clarification
- notes: fields may include user intent, source material clarity, rewrite/summarize action readiness

Those pages should not import onboarding policy or onboarding models.

The real learning `concept_check` runtime is not migrated in this task. The implementation should instead include a shared-module unit test or example policy that proves the abstraction can represent a non-onboarding judgement shape without changing learning-page behavior.

## Compatibility

- Existing onboarding `extracted_context.slot_statuses` blobs must still hydrate after migration.
- Public SSE event order and payload shape must not change.
- Existing tests that construct `ExtractedSlots(slot_statuses={...})` should keep working or require minimal fixture-only updates.
- No DB migration is expected.
- Existing learning `concept_check` behavior must remain unchanged.

## Risks

- Over-abstracting too early could make page policies harder to read. Keep the shared module small and policy-driven.
- If the shared module owns page fallback text, it will recreate coupling under a different name. Keep fallback text in page adapters.
- If onboarding and learning both need subtly different semantics for `missing`, the policy must express that explicitly instead of branching on page name.
