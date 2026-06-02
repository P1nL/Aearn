# Backend Module Organization Implementation Plan

## Start Conditions

- Do not start this child until the user reviews `prd.md`, `design.md`, `implement.md`, and `review.zh.md`.
- User review is complete for the import strategy: implementation should directly migrate internal imports and avoid long-lived root-level compatibility shims.
- Keep parent `06-02-local-product-completion` in `planning`.
- Before implementation, run `trellis-before-dev` for backend specs.
- Keep unrelated local dirty paths excluded: `.codex/config.toml`, `.trellis/tasks/.obsidian/workspace.json`, and `.claude/skills/grill-me/`.

## Ordered Checklist

1. Reconfirm current state.
   - Run `python .\.trellis\scripts\get_context.py --mode record`.
   - Run `git status --short`.
   - Confirm this child is the active implementation target after `task.py start`.

2. Build the real import inventory.
   - Use `Select-String` over `aearn/services/api/app/**/*.py` and `aearn/services/api/tests/*.py`.
   - Record old import prefixes for `app.services.*` and `app.agents.*`.
   - Identify monkeypatch paths in tests before moving files.

3. Create target packages.
   - Add `__init__.py` files for the selected `services` subpackages.
   - Add `__init__.py` files for the selected `agents` subpackages.
   - Keep package files minimal; no business logic should move into `__init__.py`.

4. Move `app/services` in cohesive batches.
   - Batch A: `grounding/*`.
   - Batch B: `runners/*` plus environment package.
   - Batch C: repositories and learner-profile persistence helpers.
   - Batch D: conversations, curriculum/exercises, LLM, streaming.
   - After each batch, update imports and run a focused import/test check when practical.

5. Move `app/agents` in cohesive batches.
   - Batch A: runtime/shared helpers.
   - Batch B: graph contracts and graph modules.
   - Batch C: learning, onboarding, review, notes, and tooling modules.
   - Update service imports and tests after each batch.

6. Remove stale root imports.
   - Search for `from app.services.` and `from app.agents.` paths pointing to old root modules.
   - Remove temporary wrappers unless a concrete blocker is explicitly documented.
   - Confirm root-level non-`__init__.py` files meet the acceptance threshold.

7. Update documentation.
   - Update `.trellis/spec/backend/directory-structure.md` with the new backend package map.
   - If needed, add a short note to relevant architecture docs, but avoid duplicate broad documentation.

8. Final verification.
   - Run the full backend test suite sequentially if practical.
   - Run lint and type checks.
   - Run desktop check if backend API contracts or generated desktop-facing types are touched.

## Validation Commands

Focused import smoke after early batches:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_worker_import.py tests/test_llm_integration.py -q
```

Domain-focused regression after move batches:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_runner_registry.py tests/test_managed_compiled_runner.py tests/test_node_typescript_runner.py tests/test_sql_query_runner.py tests/test_browser_preview_runner.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_sources.py tests/test_grounding_fetcher.py tests/test_grounding_processing.py tests/test_grounding_retrieval.py tests/test_grounding_citations.py tests/test_grounding_fixtures.py tests/test_grounding_reindex.py tests/test_grounding_index_repository.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py tests/test_reviews_m4.py tests/test_notes_m5.py tests/test_local_user_data_boundary.py -q
```

Final quality gate:

```powershell
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-03-backend-module-organization-refactor
git diff --check
```

## Risky Files And Checks

- `aearn/services/api/app/routes/*.py`: route imports must change without route behavior changes.
- `aearn/services/api/app/services/learning_conversation.py`: imports both agents and services and is likely to reveal circular dependency risk.
- `aearn/services/api/app/agents/tools.py`: calls service-layer helpers and may need careful import updates.
- `aearn/services/api/tests/test_llm_integration.py`: imports many agent helpers directly.
- `aearn/services/api/tests/conftest.py`: may contain path assumptions for app imports and database bootstrap.

## Rollback Points

- If grounding moves fail, restore only the `services/grounding` batch and retry after import graph review.
- If runner moves fail, restore `services/runners` before changing registry/runtime behavior.
- If agent moves create circular imports, keep shared helpers in `agents/runtime` and update only the domain import that caused the cycle.
- If broad import migration becomes too risky, keep a short-lived compatibility wrapper only for the failing domain and document a follow-up removal.

## Before Closeout

- Confirm no generated `__pycache__` or cache directories were staged.
- Confirm no unrelated local dirty paths were staged.
- Confirm parent remains `planning`.
- Confirm this child can be archived independently after implementation and verification.
