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

- [x] Create task-local coverage matrix under `.trellis/tasks/06-03-exercise-generation-knowledge-alignment/research/` or equivalent.
- [x] Enumerate all public executable languages: `python`, `javascript`, `html_css`, `typescript`, `sql`, `java`, `go`, `csharp`.
- [x] Include `cpp` as static placeholder only.
- [x] Extract route knowledge points and `skill_tags` from `COURSE_TEMPLATES`.
- [x] Map each language to runtime tier and runner.
- [x] Mark current internal seed/harness-template coverage and known gaps.
- [x] Pick the first semantic validator batch.

Recommended first batch:

- Python: `list_comprehension`
- SQL: `filtering`, `joins`, `aggregation`
- JavaScript/TypeScript: `functions`, `dom_events`, `types`

## Phase 1: Enhanced Model Context

- [x] Add `required_skill_tags` to `_model_context()`.
- [x] Add bounded lesson/module context where available.
- [x] Add safe source/taxonomy hints where available.
- [x] Increase description context only with a bounded cap; do not pass unlimited raw lesson text.
- [x] Update `_model_messages()` system/user instructions to require alignment with `required_skill_tags`.
- [x] Bump `ADAPTIVE_TEMPLATE_PROMPT_VERSION` or related version constants if appropriate.
- [x] Add tests proving fake candidate generators receive `required_skill_tags` and lesson context.
- [x] Add tests proving generic candidate output can be rejected and converted into safe regeneration feedback once semantic validators exist.

## Phase 2: Model-First Bounded Freeform Generation

- [x] Update prompt language so canonical templates are internal seed/harness and boundary metadata, not required skeletons or user-visible fallback content.
- [x] Confirm current candidate schema already permits rewritten `starter_code`, `solution_reference`, `prompt_markdown`, and `code_blanks`.
- [x] Decide whether to add allowlisted fields such as `exercise_intent`, `target_skill_tags`, `alignment_claims`, and `requested_exercise_type`.
- [x] If adding fields, reject arbitrary unsupported fields and keep safe metadata only.
- [x] Do not allow model candidates to change `language`, `runtime_tier`, or `runner`.
- [x] Do not allow model candidates to own final `test_cases` in the first implementation.
- [x] Preserve current runner validation with `run_exercise()`.
- [x] Add tests where a model-generated candidate uses a completely different code shape from the deterministic seed but still passes validation.
- [x] Add a bounded retry loop for invalid freeform candidates.
- [x] Add tests proving invalid freeform candidates trigger safe regeneration feedback.
- [x] Add tests proving retry-cap exhaustion returns an honest unavailable/error result and does not present a deterministic exercise.

## Phase 3: Semantic and Syntax Validators

- [x] Add a validator package, likely `aearn/services/api/app/services/exercises/syntax_validators/`.
- [x] Define a small `SemanticValidationReport` or equivalent.
- [x] Add a dispatcher that selects validator by `language` / `runtime_tier`.
- [x] Run semantic validation before cache persistence.
- [x] Add safe regeneration feedback for semantic validation failures.
- [x] Implement Python AST validator first.
- [x] Add Python tests for a required skill such as `list_comprehension`.
- [x] Add SQL lightweight validator tests for `filtering`, `joins`, and/or `aggregation`.
- [x] Add JavaScript/TypeScript lightweight validator tests for one or two high-value tags.
- [x] Add lightweight Java/Go/C#/HTML/CSS validators after the first batch; keep strict parser-grade validators deferred.

## Validation Commands

Focused backend tests:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_adaptive_exercise_templates.py tests/test_exercise_semantic_validators.py tests/test_sql_query_runner.py tests/test_runner_registry.py tests/test_learning_sessions_m3.py -q
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

This task was started after user approval and is now implemented. Keep it unarchived until the user asks for commit/archive closeout.

## Verification Results

- `uv --directory .\aearn\services\api run python -m pytest tests/test_adaptive_exercise_templates.py tests/test_exercise_semantic_validators.py tests/test_sql_query_runner.py tests/test_runner_registry.py tests/test_learning_sessions_m3.py -q` -> `113 passed`
- `uv --directory .\aearn\services\api run python -m ruff check app tests` -> passed
- `uv --directory .\aearn\services\api run python -m mypy app` -> passed
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-03-exercise-generation-knowledge-alignment` -> passed
- `pnpm --dir .\aearn desktop:check` -> passed with Vite chunk size warning only
- `git diff --check` -> passed with CRLF warnings only
