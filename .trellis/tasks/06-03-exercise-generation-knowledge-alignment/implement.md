# Implementation Plan

## Before Editing

- Keep `.trellis/tasks/06-03-learning-session-deepseek-compat` separate from this task's implementation scope.
- Do not run `task.py start` for this task until the user approves the planning package.
- Read backend specs before code changes:
  - `.trellis/spec/backend/directory-structure.md`
  - `.trellis/spec/backend/error-handling.md`
  - `.trellis/spec/backend/quality-guidelines.md`
  - `.trellis/spec/backend/logging-guidelines.md`
- Inspect current exercise generation files:
  - `aearn/services/api/app/services/exercises/exercise_repository.py`
  - `aearn/services/api/app/services/exercises/adaptive_exercise_service.py`
  - `aearn/services/api/app/services/exercises/exercise_templates.py`
  - `aearn/services/api/app/services/curriculum/plan_generator.py`
  - `aearn/services/api/app/services/runners/runtime_runner.py`
  - `aearn/services/api/app/services/runners/runner_registry.py`
- Inspect current tests:
  - `aearn/services/api/tests/test_adaptive_exercise_templates.py`
  - `aearn/services/api/tests/test_learning_sessions_m3.py`
  - `aearn/services/api/tests/test_sql_query_runner.py`
  - `aearn/services/api/tests/test_runner_registry.py`

## Phase 0: Coverage Audit

- [ ] Create task-local coverage matrix under `.trellis/tasks/06-03-exercise-generation-knowledge-alignment/research/` or equivalent.
- [ ] Enumerate all public executable languages: `python`, `javascript`, `html_css`, `typescript`, `sql`, `java`, `go`, `csharp`.
- [ ] Include `cpp` as static placeholder only.
- [ ] Extract route knowledge points and `skill_tags` from `COURSE_TEMPLATES`.
- [ ] Map each language to runtime tier and runner.
- [ ] Mark current internal seed/harness-template coverage and known gaps.
- [ ] Pick the first semantic validator batch.

Recommended first batch:

- Python: `list_comprehension`
- SQL: `filtering`, `joins`, `aggregation`
- JavaScript/TypeScript: `functions`, `dom_events`, `types`

## Phase 1: Enhanced Model Context

- [ ] Add `required_skill_tags` to `_model_context()`.
- [ ] Add bounded lesson/module context where available.
- [ ] Add safe source/taxonomy hints where available.
- [ ] Increase description context only with a bounded cap; do not pass unlimited raw lesson text.
- [ ] Update `_model_messages()` system/user instructions to require alignment with `required_skill_tags`.
- [ ] Bump `ADAPTIVE_TEMPLATE_PROMPT_VERSION` or related version constants if appropriate.
- [ ] Add tests proving fake candidate generators receive `required_skill_tags` and lesson context.
- [ ] Add tests proving generic candidate output can be rejected and converted into safe regeneration feedback once semantic validators exist.

## Phase 2: Model-First Bounded Freeform Generation

- [ ] Update prompt language so canonical templates are internal seed/harness and boundary metadata, not required skeletons or user-visible fallback content.
- [ ] Confirm current candidate schema already permits rewritten `starter_code`, `solution_reference`, `prompt_markdown`, and `code_blanks`.
- [ ] Decide whether to add allowlisted fields such as `exercise_intent`, `target_skill_tags`, `alignment_claims`, and `requested_exercise_type`.
- [ ] If adding fields, reject arbitrary unsupported fields and keep safe metadata only.
- [ ] Do not allow model candidates to change `language`, `runtime_tier`, or `runner`.
- [ ] Do not allow model candidates to own final `test_cases` in the first implementation.
- [ ] Preserve current runner validation with `run_exercise()`.
- [ ] Add tests where a model-generated candidate uses a completely different code shape from the deterministic seed but still passes validation.
- [ ] Add a bounded retry loop for invalid freeform candidates.
- [ ] Add tests proving invalid freeform candidates trigger safe regeneration feedback.
- [ ] Add tests proving retry-cap exhaustion returns an honest unavailable/error result and does not present a deterministic exercise.

## Phase 3: Semantic and Syntax Validators

- [ ] Add a validator package, likely `aearn/services/api/app/services/exercises/syntax_validators/`.
- [ ] Define a small `SemanticValidationReport` or equivalent.
- [ ] Add a dispatcher that selects validator by `language` / `runtime_tier`.
- [ ] Run semantic validation before cache persistence.
- [ ] Add safe regeneration feedback for semantic validation failures.
- [ ] Implement Python AST validator first.
- [ ] Add Python tests for a required skill such as `list_comprehension`.
- [ ] Add SQL lightweight validator tests for `filtering`, `joins`, and/or `aggregation`.
- [ ] Add JavaScript/TypeScript lightweight validator tests for one or two high-value tags.
- [ ] Defer Java/Go/C#/HTML/CSS strict validators unless the coverage audit marks them as release-blocking.

## Validation Commands

Focused backend tests:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_adaptive_exercise_templates.py tests/test_sql_query_runner.py tests/test_runner_registry.py -q
```

Learning-session integration tests if exercise materialization behavior changes:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_sessions_m3.py -q
```

Quality checks:

```powershell
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-03-exercise-generation-knowledge-alignment
git diff --check
```

## Risky Files and Rollback Points

- `adaptive_exercise_service.py`: rollback if prompt/context/schema changes break retry, validation, or honest failure behavior.
- `exercise_templates.py`: rollback if template/generator versioning invalidates cache incorrectly.
- `exercise_repository.py`: rollback if internal seed/harness language/runtime routing regresses.
- `syntax_validators/`: can be disabled or removed if semantic checks become too strict.
- Tests that rely on live model calls should stay fake/offline by default.

## Start Gate

This task is currently planning-only. Do not start implementation until the user approves the PRD/design/implementation plan or explicitly says to enter implementation.
