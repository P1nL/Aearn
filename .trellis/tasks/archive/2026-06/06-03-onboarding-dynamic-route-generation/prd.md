# Onboarding dynamic route generation

## Goal

Onboarding must generate the in-chat learning route card from the dynamic plan generation path instead of deterministic course templates, so supported languages produce sufficiently rich, grounded, model-generated learning routes.

## User Value

- Users should not see short template routes for Java, TypeScript, SQL, Go, or C# after the onboarding model has already collected their learning goal.
- Developers should immediately see configuration or model-generation failures instead of silently shipping a template fallback.
- Generated routes should meet a measurable depth bar, reducing the chance that the model returns the smallest acceptable structure.

## Confirmed Facts

- `POST /api/onboarding/messages` generates route cards through `build_plan_draft_from_slots(...)` and emits `tool_call(name="show_learning_route")`.
- `build_plan_draft_from_slots(...)` currently delegates to `build_plan_draft(...)`.
- `build_plan_draft(...)` currently uses `COURSE_TEMPLATES[language]`, so onboarding route card modules are deterministic templates.
- `POST /api/plans/generate` already calls `build_sdk_plan_generation_response(...)`, but it first builds a deterministic draft and currently allows fallback semantics.
- Dynamic plan generation requires OpenAI-compatible model configuration, `PLAN_GENERATION_ENABLED`, and `EXA_API_KEY`.
- `AUTHORITATIVE_DOCS` currently maps `python`, `javascript`, `html_css`, `typescript`, `rust`, `go`, `java`, and `cpp`; supported onboarding languages `sql` and `csharp` are missing from that mapping.
- Current dynamic output validation enforces `4-8` modules and `2-4` knowledge points per module, but the desired product bar should not be a fixed count threshold.
- `docs/architecture/api-contract.md` still documents `/api/plans/generate` fallback to templates, which conflicts with the new no-fallback requirement.

## Requirements

- Onboarding route card generation for every supported public language must use dynamic plan generation rather than `COURSE_TEMPLATES`.
- The implementation must not provide a template fallback for supported public languages when dynamic generation is disabled, misconfigured, unavailable, or returns invalid output.
- Configuration must remain complete and explicit: missing OpenAI-compatible model config, disabled `PLAN_GENERATION_ENABLED`, missing `EXA_API_KEY`, missing authoritative docs, or invalid model output must surface as an error/no-route condition rather than silently producing a template route.
- All supported public onboarding languages must have authoritative documentation mappings used by dynamic generation: `python`, `javascript`, `typescript`, `html_css`, `java`, `go`, `csharp`, and `sql`.
- Dynamic route generation must include a quality gate that rejects routes that do not cover the user's stated needs or do not cite authoritative sources before the route card is shown or stashed.
- `/api/plans/generate` and onboarding must share the same dynamic route-generation contract so future changes do not reintroduce divergent template behavior.
- API contract documentation must be updated to remove stale fallback language and describe no-fallback failure behavior.
- Tests must prove dynamic generation is invoked for onboarding route cards, supported-language docs mappings are complete, and shallow/invalid dynamic results do not generate a route card.

## Acceptance Criteria

- [x] For a complete onboarding slot set, `POST /api/onboarding/messages` builds the route card from dynamic generation output and the emitted `show_learning_route` arguments contain dynamic modules/source attribution.
- [x] If dynamic generation is unavailable or invalid for a supported language, onboarding does not call `COURSE_TEMPLATES`, does not stash a draft, and returns a clear error/no-route SSE outcome.
- [x] `AUTHORITATIVE_DOCS` covers every public supported onboarding language, including `sql` and `csharp`.
- [x] A test fails if any public supported onboarding language lacks authoritative docs.
- [x] A quality-gate test rejects outputs that omit the user's goal, target level, requested direction, time constraints when provided, or authoritative source coverage.
- [x] `/api/plans/generate` no longer documents or depends on template fallback behavior for dynamic generation failure.
- [x] Existing unsupported language behavior for C++ and Rust remains unchanged.
- [x] Focused backend tests pass for onboarding, dynamic plan generation, and plan generation validation.

## Out Of Scope

- Adding new public supported languages beyond the current onboarding language set.
- Building real compiler/runtime support beyond the current runtime boundaries.
- Changing the desktop UI layout for route cards unless required by an API contract change.
- Committing or deploying changes in this planning step.

## Quality Gate Decision

- Do not enforce a fixed module or knowledge-point count beyond the structural validity needed to render a route.
- Require the generated route to cover the user's stated learning goal, target level, requested direction or profession when provided, and time budget/deadline when provided.
- Require `source_urls` to include authoritative documentation for the selected language.
- Require `generation_notes` or equivalent metadata to explain how the route covers the user's needs and which authoritative sources informed it.
