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

- [x] Plan and implement stable local startup/check entrypoint.
- [x] Verify desktop learning loop gaps and close the highest-impact route/learning/exercise/review/note/settings holes.
- [x] Plan and implement `language-grounding-productization`: persisted grounding index, reindex/fixture path, learning-agent integration, citations, and grounding evals.
- [x] Plan and implement environment doctor/toolchain detection and allowlisted guidance templates.
- [x] Harden Python runner behavior and result mapping.
- [x] Implement Node/TypeScript runner contract without overclaiming TypeScript support before validation passes.
- [x] Harden browser HTML/CSS runner behavior and preview/test boundaries.

## Phase 2 Execution Checklist

- [x] Implement local user/data management boundaries.
- [x] Implement SQL runner contract with dialect disclosure and safe local execution boundary.
- [x] Implement adaptive exercise templates, validation, versioning, caching, and fallback behavior for available runners.

## Phase 3 Execution Checklist

- [x] Implement Java runner contract.
- [x] Implement Go runner contract.
- [x] Implement C# runner contract.
- [x] Ensure compiled runner failures map to stable learner-safe categories.

## Phase 4 Execution Checklist

- [x] Add agent eval gates for answer-seeking, repeated confusion, capability overclaims, missing citations, runner failures, grounding failures, and dynamic exercise safety.
- [x] Reorganize backend `app/services` and `app/agents` modules into domain subpackages without behavior changes.
- [x] Run cross-child integration checks.
- [x] Produce final local-product readiness verdict.
- [x] Archive completed children before archiving the parent.

## Phase 4 Evidence Notes

- Agent eval gates are covered by existing deterministic regression tests instead of a separate `08-agent-quality-eval-gates` child: direct-answer guardrails and provider leak handling in `tests/test_learning_sessions_m3.py`, repeated-confusion routing in `tests/test_agent_router.py`, capability overclaim rejection in `tests/test_llm_integration.py`, citation metadata/fallback behavior in grounding tests, runner failure/redaction contracts in runner and learning-session tests, and dynamic exercise validation/fallback in `tests/test_adaptive_exercise_templates.py`.
- Backend module organization is complete via `06-03-backend-module-organization-refactor`, implementation commit `85a5934`, and archive commit `c914f7e`.
- Cross-child integration checks passed on 2026-06-03 with `uv --directory .\aearn\services\api run python -m pytest -q` (`472 passed`), `uv --directory .\aearn\services\api run ruff check .`, `uv --directory .\aearn\services\api run python -m mypy app`, and `pnpm --dir .\aearn desktop:check`. The desktop build still reports the existing Vite chunk-size warning.
- Final local-product readiness verdict: ready for parent archive/closeout once the user explicitly approves the archive/commit step. All created child tasks are already archived; no new `08-agent-quality-eval-gates` child was created because equivalent deterministic coverage is present and verified.

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
