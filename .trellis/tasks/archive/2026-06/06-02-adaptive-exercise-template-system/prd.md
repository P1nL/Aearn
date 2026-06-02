# Adaptive exercise template system

## Goal

Implement the adaptive exercise template system for local-only Aearn learning. The system should generate or select exercise variants from canonical templates, validate each candidate through the matching runner before learner use, cache verified variants, and fall back to stable templates when validation fails.

This task turns the current static exercise templates and review seed materialization into a product contract for safe, versioned, runner-validated exercise variants.

## User Value

- Learners get practice variants that adapt to their weak points instead of repeatedly seeing the same static exercise.
- Invalid generated exercises do not reach the learner because every candidate must pass runner validation first.
- The product remains stable when model generation, toolchains, or validators fail because canonical fallback templates always remain available.

## Confirmed Facts

- Parent task `06-02-local-product-completion` defines Phase 2 as local user/data management, SQL L3 runner, and adaptive exercise template validation.
- Completed `02-local-user-data-boundary` owns user-scoped data reset/export/delete and must be respected by any user-specific variant cache.
- `aearn/services/api/app/services/exercise_repository.py` currently creates deterministic exercises from `_exercise_template(...)` and review seed exercises from `_exercise_template_from_review_seed(...)`.
- `aearn/services/api/app/services/review_seed_bank.py` can generate and materialize review variants, but current runtime validation is not a required pre-use gate.
- Existing runner validation paths include Python, Node/TypeScript, browser HTML/CSS, and planned SQL after `06-02-sql-query-runner`.
- Parent design requires adaptive variants to be generated from canonical templates, validated by matching runner, versioned, cached, and safely fallen back.

## Requirements

- Depend explicitly on:
  - `06-02-local-product-completion` parent product boundaries.
  - Completed `02-local-user-data-boundary` for user-scoped cache/reset/export/delete behavior.
  - Completed Python, Node/TypeScript, and browser runner contracts.
  - `06-02-sql-query-runner` for SQL variant validation if SQL templates are included.
  - Existing review seed bank safety rules and hidden-test redaction.
- Define canonical exercise templates with stable ids, versions, language/runtime identity, knowledge-point targeting, visible tests, hidden tests, solution/validator reference, and fallback template payload.
- Generate adaptive candidate variants from bounded learner context:
  - knowledge point
  - recent visible attempt facts
  - weak points
  - runtime capability
  - supported exercise type
- Use model-assisted candidate generation as the first implementation path, but constrain the model to a canonical template envelope. The model may propose learner-facing wording, variable names, data values, and scenario framing; it must not invent unsupported runtime contracts, bypass required fields, expose solutions, or change hidden-test semantics outside the allowed template knobs.
- Keep deterministic parameterization only as a fallback/test-fixture path for provider failure, invalid model output, and repeatable regression tests.
- Validate every candidate with the matching runner before materializing it for learner use.
- Cache only verified variants and include template version, generator version, runner version, validation status, and safe failure reason.
- Fall back to canonical stable templates when:
  - generation fails
  - validation fails
  - runner is unsupported or missing
  - toolchain is unavailable
  - candidate contains unsafe content
  - template version is no longer compatible
- Preserve hidden test redaction and never expose solution references, hidden expected outputs, raw prompts, provider payloads, or validator internals.
- Make variant cache local-user scoped where variants are personalized.
- Ensure reset/export/delete flows include or intentionally omit variant cache with documented behavior.
- Keep existing static exercise and review flows working while introducing adaptive selection.

## Acceptance Criteria

- [ ] Canonical templates have stable ids and versions for supported runtime families.
- [ ] Model-assisted candidate variants include generator/model/template/version metadata and are validated before becoming learner-visible.
- [ ] Runner validation passes for at least Python and one browser/Node family before those variants are used.
- [ ] SQL variants are gated on `06-02-sql-query-runner`; if SQL runner is not complete, SQL adaptive generation stays disabled or falls back.
- [ ] Invalid variants fall back to stable canonical templates without breaking the learning or review flow.
- [ ] Verified variants are cached and reused only when template version, runner identity, and user/knowledge-point scope still match.
- [ ] User reset/delete/export behavior for adaptive variants is tested or explicitly documented in code/tests.
- [ ] Hidden tests, solution references, raw prompts, provider payloads, and internal validation details are not exposed.
- [ ] Focused tests cover model-candidate success, invalid model output fallback, validation failure fallback, provider failure fallback, runner unsupported fallback, cache hit/miss, version invalidation, user isolation, and redaction.
- [ ] Existing learning, review, local user-data, runner, lint, and type-check gates keep passing when practical.

## Out of Scope

- Fully open-ended exercise generation without canonical templates.
- Learner-visible unvalidated model-generated exercises.
- Arbitrary package installation or project execution during validation.
- Global shared cloud variant cache.
- Public marketplace or authoring UI for templates.
- Rust/C++ L3 execution templates.

## Open Questions

- None blocking planning. The user decision is to implement model-assisted candidate generation first, with deterministic generation retained only as fallback/test fixture.

## Notes

- This is a complex child task. It requires `design.md`, `implement.md`, and `review.zh.md` before `task.py start`.
- Keep parent task in `planning`; do not start `06-02-local-product-completion`.
