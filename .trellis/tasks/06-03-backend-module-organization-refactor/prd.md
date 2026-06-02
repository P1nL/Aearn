# Backend module organization/refactor

## Goal

Reorganize the backend Python modules under `aearn/services/api/app/services` and `aearn/services/api/app/agents` into clearer domain subpackages without changing runtime behavior, public API contracts, database schema, runner semantics, or desktop-visible product behavior.

## User Value

- A developer can find backend files by product/domain responsibility instead of scanning two large flat folders.
- Future work on runners, grounding, learning conversations, reviews, notes, onboarding, and local data boundaries has a stable place to add files.
- The refactor reduces navigation friction before final local-product integration review, without introducing product-risky behavior changes.

## Confirmed Facts

- `aearn/services/api/app/services` currently has 45 non-`__init__.py` Python files in one flat package.
- `aearn/services/api/app/agents` currently has 22 non-`__init__.py` Python files in one flat package.
- Backend spec says `services/api/app/agents/` owns Aearn-specific OpenAI Agents SDK modules and SDK code should not live in routes or repositories.
- Existing imports heavily use direct paths such as `app.services.runner_registry` and `app.agents.learning_graph`, so implementation must update app and test imports deliberately.
- The parent task `06-02-local-product-completion` is still a planning parent; this child must be reviewed before `task.py start`.

## Dependencies

- Depends on completed local-product runner and data-boundary work being committed, because this refactor will move modules added by those children.
- Depends on the current backend specs under `.trellis/spec/backend/`, especially `directory-structure.md` and `quality-guidelines.md`.
- Depends on API, database, runner, graph, and LLM contracts staying unchanged in `docs/architecture/`.
- Before implementation, use `trellis-before-dev` for backend specs and inspect current import paths with repository evidence, not memory.

## Requirements

- Create a target backend package map for `app/services` and `app/agents` that groups modules by domain responsibility.
- Move modules into subpackages using a low-risk sequence that keeps each batch verifiable.
- Update all first-party imports in `app/` and `tests/` to the new paths.
- Keep FastAPI route paths, request/response envelopes, database schema, runtime statuses, language capability disclosures, and model/error behavior unchanged.
- Keep the refactor behavior-preserving: no feature additions, no product copy changes, no schema migrations, no package upgrades, and no runner/agent contract changes.
- Update backend directory-structure documentation after the final package layout is chosen.
- Do not move generated files such as `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache`, or virtualenv content.
- Prefer direct import migration over duplicate long-lived compatibility wrappers unless implementation evidence shows a wrapper is needed to control risk.

## Acceptance Criteria

- [ ] `app/services` has domain subpackages for runner/runtime, grounding, repositories/persistence, conversations, curriculum/exercises, LLM utilities, environment/toolchain checks, and streaming/event helpers.
- [ ] `app/agents` has domain subpackages for runtime/shared helpers, graph orchestration, learning, onboarding, review, notes, and agent tooling.
- [ ] Root-level non-`__init__.py` files in `app/services` and `app/agents` are reduced by at least 70%, with any remaining root files documented as intentional.
- [ ] All first-party imports in `aearn/services/api/app` and `aearn/services/api/tests` point to the new package paths.
- [ ] Public API responses and persisted data behavior are unchanged by the refactor.
- [ ] Runner result categories, hidden-test redaction, language capability disclosures, and environment doctor behavior remain unchanged.
- [ ] Backend directory-structure docs describe the new package map and ownership boundaries.
- [ ] Focused import/behavior tests pass, plus `ruff`, `mypy`, and backend pytest verification chosen in `implement.md`.

## Out of Scope

- Changing FastAPI route URLs, desktop API contracts, or database schema.
- Rewriting business logic inside runners, agents, repositories, grounding, or review scheduling.
- Renaming public language ids, runtime tiers, runtime statuses, or API fields.
- Reorganizing frontend files.
- Introducing dependency injection frameworks, new packages, or packaging/build-system changes.
- Preserving old root import paths forever through compatibility shim files if they keep the folders cluttered.

## Resolved Decisions

- Directly update all internal imports to new subpackage paths.
- Do not keep long-lived root-level compatibility shims.
- Temporary wrappers are allowed only as short-lived implementation scaffolding for a failing batch, and must be removed before closeout unless a documented blocker remains.

## Notes

- This is a complex structural task; keep `design.md`, `implement.md`, and `review.zh.md` current before implementation starts.
