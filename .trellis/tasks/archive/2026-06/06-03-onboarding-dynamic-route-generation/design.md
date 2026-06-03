# Design: Onboarding dynamic route generation

## Architecture Boundary

Onboarding and `/api/plans/generate` should share an application-level dynamic plan generation service instead of making an intra-process HTTP call. This keeps the FastAPI route handlers thin, avoids recursive HTTP failure modes, and still satisfies the product requirement that onboarding uses the same dynamic generation capability as the existing dynamic generation endpoint.

## Current Flow

1. `POST /api/onboarding/messages` updates onboarding slots.
2. When `language`, `target_level`, and `goal_text` are ready, `routes/onboarding.py` calls `build_plan_draft_from_slots(...)`.
3. `build_plan_draft_from_slots(...)` delegates to `build_plan_draft(...)`.
4. `build_plan_draft(...)` selects `COURSE_TEMPLATES[language]`.
5. The route serializes the draft into `show_learning_route` tool arguments and stashes the draft.

## Target Flow

1. `POST /api/onboarding/messages` still owns slot extraction, route-readiness checks, draft stashing, and SSE event emission.
2. When route generation is allowed, onboarding converts slots into a `PlanGenerateRequest`-compatible generation context.
3. A shared dynamic generation service validates configuration, authoritative docs coverage, and model output quality.
4. Only a passing dynamic result may be merged into a `PlanDraft`, stashed, and emitted as `show_learning_route`.
5. Missing configuration, missing docs, unavailable model/tooling, or failed quality gate returns a clear no-route error outcome.

## Contracts

- Supported public onboarding languages: `python`, `javascript`, `typescript`, `html_css`, `java`, `go`, `csharp`, `sql`.
- Unsupported onboarding languages: `cpp`, `rust`; current `LANGUAGE_NOT_SUPPORTED` behavior must remain intact.
- Dynamic generation configuration is required for public supported languages:
  - OpenAI-compatible model configuration
  - `PLAN_GENERATION_ENABLED=true`
  - `EXA_API_KEY`
  - language present in `AUTHORITATIVE_DOCS`
- Dynamic route output must satisfy the final quality threshold selected during planning.
- Template modules must not be used as a hidden fallback for public supported languages.

## Error Behavior

Dynamic generation failure must be externally visible and testable. The exact error code can follow existing onboarding error conventions, but the behavior must guarantee:

- no `show_learning_route` tool call,
- no stashed `plan_draft`,
- no template module substitution,
- enough error detail for frontend/developer diagnosis without exposing secrets.

Likely codes to evaluate during implementation:

- `MODEL_UNAVAILABLE` for missing model config or model call failure.
- `PLAN_GENERATION_UNAVAILABLE` for missing `PLAN_GENERATION_ENABLED`, `EXA_API_KEY`, missing docs mapping, or rejected dynamic output.

## Quality Gate Shape

The existing dynamic validator already checks:

- module count range,
- knowledge point count range,
- temp id language prefixes,
- safe teaching output,
- source URL presence.

This task should not add a fixed richness threshold such as "at least 6 modules". The product quality gate should be coverage-based:

- the route covers the user's stated `goal_text`,
- the route fits `target_level`,
- the route reflects requested direction or `profession` when provided,
- the route reflects `time_budget` or deadline when provided,
- `source_urls` includes authoritative documentation for the selected language,
- `generation_notes` explains how user needs and authoritative sources shaped the route,
- every module includes non-empty Chinese title and description,
- module order indexes are sequential.

Structural lower/upper bounds may remain only as renderer safety checks; they must not be treated as the product definition of "good enough".

## Documentation Updates

`docs/architecture/api-contract.md` must remove the old `/api/plans/generate` fallback statement and document that dynamic route generation failure is not hidden by templates. Onboarding route card behavior must also mention dynamic generation and no-route failure behavior.

## Compatibility Notes

Existing tests that monkeypatch `build_sdk_plan_generation_response` to `None` may need adjustment because `None` should no longer mean "fallback template" in dynamic route paths. Tests for unrelated learning/review flows may continue using deterministic drafts only if they do not exercise dynamic route generation behavior.

## Rollback Points

- Route-level integration in `aearn/services/api/app/routes/onboarding.py`.
- Shared dynamic plan generation service extraction or refactor.
- `AUTHORITATIVE_DOCS` and quality validation changes in `aearn/services/api/app/agents/onboarding/plan_generation_agent.py`.
- API contract text in `docs/architecture/api-contract.md`.
