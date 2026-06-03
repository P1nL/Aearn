# Exercise generation knowledge alignment

## Goal

Make generated practice align with the learner's route knowledge point, especially `skill_tags`, while preserving Aearn's local-only runtime boundaries.

The desired product direction is model-first bounded freeform generation: the model should be allowed to redesign the exercise prompt, code shape, `starter_code`, `solution_reference`, and blanks so the practice really targets the current knowledge point. Deterministic templates remain only as internal canonical seeds, safety envelopes, and runner harness references. They must not become the normal user-visible fallback when model generation fails.

## User Value

- Learners should not see generic language drills when the route says they are practicing a specific concept such as Python list comprehensions, SQL joins, DOM events, or TypeScript type contracts.
- Practice cards should feel adaptive and varied instead of repeating one hard-coded template per language.
- The system should still be able to prove that generated exercises are executable, safe to show, and aligned with the target skill before caching or presenting them.
- When the system cannot generate a qualified exercise, it should honestly say generation is unavailable or ask the learner to retry, instead of showing a hard-coded generic exercise as if it were adaptive.

## Confirmed Facts

- Public executable route languages are `python`, `javascript`, `html_css`, `typescript`, `sql`, `java`, `go`, and `csharp`.
- `cpp` is a placeholder/static-template language only and must not be presented as executable.
- `docs/architecture/api-contract.md` defines public language/runtime boundaries, including `python_stdout_test`, `browser_preview`, `node_typescript_test`, `sql_query_test`, and `managed_compiled_test`.
- `aearn/services/api/app/services/curriculum/plan_generator.py` stores route knowledge points with `skill_tags`.
- `aearn/services/api/app/services/exercises/exercise_repository.py::_exercise_template()` currently provides deterministic templates used as fallbacks. It now has explicit branches for `python`, `html_css`, `java`, and `sql`; JavaScript still relies on the browser fallback; `typescript`, `go`, and `csharp` need internal seed/harness coverage or a model-first path that is proven safe.
- `aearn/services/api/app/services/exercises/adaptive_exercise_service.py::_model_context()` currently sends `knowledge_point_title`, a 500-character `knowledge_point_description`, `weak_points`, and runtime metadata, but does not pass full `skill_tags` or route lesson context to the model.
- `adaptive_exercise_service.py` already lets a model candidate replace `title`, `prompt_markdown`, `starter_code`, `solution_reference`, `metadata_json`, and `code_blanks`.
- Model candidates are runner-validated through `_validate_candidate()` and `run_exercise()` before caching.
- Model candidates cannot currently own `test_cases`; unsupported fields currently force deterministic fallback.
- Validated variants are cached per user, knowledge point, template id/version, generator version, runner, and runtime tier.

## Requirements

- Add a coverage audit phase before implementation that maps every public language and route knowledge point to its runtime tier, current internal seed/harness template, `skill_tags`, and validation coverage.
- Enhance model context with structured `skill_tags`, route/module lesson context, source/taxonomy hints, weak points, and runtime constraints.
- Replace the current "generic template rewrite" prompt stance with model-first bounded freeform instructions.
- Allow the model to redesign learner-facing exercise shape within an allowlisted candidate schema.
- Keep `language`, `runtime_tier`, `runner`, provider payloads, hidden tests, and final grading authority outside model control.
- Keep deterministic canonical templates as internal seed/harness only; do not require generated exercises to preserve the original hard-coded code skeleton.
- Add semantic alignment validation so a generated candidate must prove it practices required `skill_tags`, not only that its `solution_reference` passes runner execution.
- Introduce a syntax/semantic validator interface that can be implemented per language and can fail candidates before cache/presentation.
- Start with lightweight validators where AST coverage is expensive, but make Python AST validation the preferred first strict implementation.
- Replace user-visible hard-coded fallback with a bounded retry loop: if model generation, schema validation, runtime validation, or semantic validation fails, feed safe validation feedback into another model attempt up to a configured cap.
- If all generation attempts fail, return an honest unavailable result such as `EXERCISE_GENERATION_UNAVAILABLE` or the existing `MODEL_UNAVAILABLE` family, without presenting a deterministic generic exercise as adaptive practice.
- Version generator/prompt/semantic validation changes so stale cached variants are not reused after alignment rules change.
- Keep this task scoped to backend exercise generation and validation; do not redesign the learning-session UI, onboarding UI, deployment, or runtime sandbox architecture.
- Do not make hard-coded deterministic exercises the normal learner-visible fallback for adaptive generation failure.

## Acceptance Criteria

- [ ] A coverage matrix exists for all 8 executable languages and `cpp` static placeholder, showing route knowledge points, `skill_tags`, internal seed/harness coverage, runner tier, and validator coverage.
- [ ] `_model_context()` includes bounded structured `skill_tags` and route/lesson context, with tests proving these fields reach the candidate generator.
- [ ] The model prompt explicitly asks candidates to align exercise intent with required `skill_tags` and to avoid generic language drills when a specific concept is present.
- [ ] Model candidates can freely change `starter_code`, `solution_reference`, prompt, and blanks without preserving the deterministic seed skeleton.
- [ ] Model candidates cannot change `language`, `runtime_tier`, `runner`, or own final grading/runtime authority.
- [ ] A generated candidate that passes runtime tests but misses required syntax/semantic alignment is rejected, then retried with safe feedback.
- [ ] When the retry cap is exhausted, the API returns an honest unavailable/error result and does not show a deterministic template as a generated exercise.
- [ ] At least Python has a strict validator for one high-value skill such as `list_comprehension` using `ast`.
- [ ] At least JavaScript/TypeScript and SQL have initial lightweight validators for selected high-value skill tags.
- [ ] Existing runner validation, hidden-output redaction, safe metadata handling, and user-scoped cache behavior remain intact.
- [ ] Focused backend tests cover model context enrichment, model-first candidate shape, semantic validation failure, bounded retry, honest unavailable failure, and cache invalidation/versioning.
- [ ] `ruff`, `mypy`, focused pytest, Trellis task validation, and `pnpm --dir .\aearn desktop:check` pass or exact blockers are documented.

## Phased Scope

### Phase 0: Coverage audit

- Build the language/knowledge-point/internal-seed/validator coverage matrix.
- Identify missing explicit coverage for `javascript`, `typescript`, `go`, and `csharp`.
- Identify high-value skill tags per language for the first validator batch.

### Phase 1: Enhanced model context

- Pass `skill_tags`, lesson/module context, route source attribution, and weak points into model context.
- Use bounded structured context rather than unlimited raw lesson text.
- Update prompt and tests.

### Phase 2: Model-first bounded freeform generation

- Let the model redesign the exercise shape within a safe candidate schema.
- Treat canonical templates as internal seed/harness and boundary metadata, not as required skeletons or user-visible fallback content.
- Add a bounded regeneration loop that passes safe validation feedback to the model after failed schema, semantic, or runner validation.
- Add an honest failure result when all attempts are invalid.
- Keep tests and final grading authority system-owned.

### Phase 3: Semantic and syntax validation

- Add a per-language validator interface.
- Implement Python strict AST validation first.
- Add lightweight JavaScript/TypeScript and SQL validators next.
- Add Java, Go, C#, and HTML/CSS validators in smaller follow-up slices.

## Out of Scope

- Arbitrary project execution, package manager execution, dependency installation, or container sandbox expansion.
- Making `cpp` or Rust publicly executable.
- Replacing route generation or onboarding product flow.
- Frontend redesign beyond any minimal metadata display required by the backend contract.
- Changing provider configuration or DeepSeek/OpenAI compatibility behavior.
- Committing or starting this planning task before explicit user approval.

## Risks

- Model freedom can generate exercises that run successfully but do not teach the target skill; semantic validation is required to control this.
- Removing user-visible hard-coded fallback means some learners may wait longer or receive a retry/unavailable message; this is accepted as more honest than showing a generic exercise.
- Per-language validators can become expensive; implementation should start with the highest-value tags and expand iteratively.
- Long lesson context can introduce prompt injection or noise; context must stay structured and bounded.
- Cache reuse can hide prompt/validator improvements; generator or validator versioning must invalidate stale variants.
- Managed compiled languages may be harder to semantically validate without full parser dependencies; start with lightweight rules and focused skill tags.

## Open Questions

- No blocker for planning. Before implementation starts, pick the first validator batch and retry cap. Recommended default: max 3 model attempts per exercise request, then return an honest unavailable result.
