# Local Product Completion Implementation Plan

## Parent Task Policy

- Keep this parent task in `planning` until the user reviews `prd.md`, `design.md`, and `implement.md`.
- Do not start the parent task for normal child implementation work.
- Create child tasks incrementally when a child is about to be planned or implemented.
- Write dependency requirements inside each child artifact. Do not rely on tree position to imply dependencies.
- In inline mode, the main session performs implementation and checking directly; do not dispatch implement/check sub-agents.

## Recommended Child Creation Order

1. Create `01-local-stable-startup`.
2. Create `03-desktop-learning-experience-completion`.
3. Create `04-language-grounding-productization`.
4. Create `05-environment-doctor-and-install-guidance`.
5. Create runner children under `06-language-l3-runner-contracts` as each language family enters implementation.
6. Create `02-local-user-data-boundary` before final data-management polish.
7. Create `07-adaptive-exercise-template-system` after at least one target runner validation path is stable.
8. Create `08-agent-quality-eval-gates` after grounding, runner, and adaptive-exercise contracts are concrete.
9. Create `backend-module-organization-refactor` after enough backend modules exist to justify structural cleanup, and before final integration review.
10. Create or start `09-local-product-final-integration-review` only when selected child work is complete.

## Phase 1 Execution Checklist

- [ ] Plan and implement stable local startup/check entrypoint.
- [ ] Verify desktop learning loop gaps and close the highest-impact route/learning/exercise/review/note/settings holes.
- [ ] Plan and implement `language-grounding-productization`: persisted grounding index, reindex/fixture path, learning-agent integration, citations, and grounding evals.
- [ ] Plan and implement environment doctor/toolchain detection and allowlisted guidance templates.
- [ ] Harden Python runner behavior and result mapping.
- [ ] Implement Node/TypeScript runner contract without overclaiming TypeScript support before validation passes.
- [ ] Harden browser HTML/CSS runner behavior and preview/test boundaries.

## Phase 2 Execution Checklist

- [x] Implement local user/data management boundaries.
- [x] Implement SQL runner contract with dialect disclosure and safe local execution boundary.
- [x] Implement adaptive exercise templates, validation, versioning, caching, and fallback behavior for available runners.

## Phase 3 Execution Checklist

- [ ] Implement Java runner contract.
- [ ] Implement Go runner contract.
- [ ] Implement C# runner contract.
- [ ] Ensure compiled runner failures map to stable learner-safe categories.

## Phase 4 Execution Checklist

- [ ] Add agent eval gates for answer-seeking, repeated confusion, capability overclaims, missing citations, runner failures, grounding failures, and dynamic exercise safety.
- [ ] Reorganize backend `app/services` and `app/agents` modules into domain subpackages without behavior changes.
- [ ] Run cross-child integration checks.
- [ ] Produce final local-product readiness verdict.
- [ ] Archive completed children before archiving the parent.

## Validation Command Matrix

Each child should choose a focused subset, but the final integration review should expect these commands when practical:

```powershell
uv --directory .\aearn\services\api run python -m pytest
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
pnpm --dir .\aearn desktop:check
```

Grounding-specific children should additionally run:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_sources.py tests/test_grounding_fetcher.py tests/test_grounding_processing.py tests/test_grounding_retrieval.py tests/test_grounding_citations.py tests/test_grounding_fixtures.py tests/test_grounding_reindex.py tests/test_graph_runtime_contracts.py tests/test_teaching_chunks.py
```

Runner-specific children should add focused runtime tests for their adapter and registry behavior.

Desktop/UI children should add or update focused desktop checks and use browser/UI smoke testing when a local target is available.

## Risky Areas

- Database schema changes for grounding indexes, data export/delete, runner attempts, or adaptive exercise variants.
- Prompt and graph changes that can expose hidden tests, solution references, raw prompts, or provider payloads.
- Runner adapters that execute local toolchains and must avoid project-directory writes, unbounded output, network access, and runaway processes.
- Environment doctor code that could accidentally mutate global PATH, Docker, WSL, or system settings.
- Desktop settings and language cards that could overclaim execution support.

## Rollback Points

- Keep local startup scripts compatible with documented manual startup commands.
- Make grounding index/reindex changes additive until final review confirms no regression.
- Gate new runner support behind language capabilities and registry descriptors.
- Preserve canonical exercise templates when adaptive variants fail validation.
- Keep existing deterministic or fallback agent behavior available when model/API/grounding components fail.

## Before Starting Any Child

- [ ] Read the parent `prd.md`, `design.md`, and this file.
- [ ] Read relevant `.trellis/spec/` package/layer guidance via `trellis-before-dev`.
- [ ] Write the child `prd.md` with explicit dependencies and acceptance criteria.
- [ ] For complex children, write child `design.md` and `implement.md` before `task.py start`.
- [ ] Ask the user to review child planning artifacts before starting implementation.
