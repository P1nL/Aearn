# Regenerate current project documentation

## Goal

Re-read current Aearn codebase and regenerate a concise current-state documentation pack for interview, architecture, flows, agent/evaluation/review, and demo/QA; avoid blindly rewriting stale source-of-truth docs before audit.

## Background

The user wants documentation regenerated from the current repository state because some existing documents may be stale. The generated package should help the project be explained as an interview project while still being accurate enough to guide future implementation and review.

Current repository facts already confirmed:

- Runtime code lives under `aearn/`; repository root is for Git, Trellis, docs, scripts, and agent configuration.
- Existing source-of-truth docs are indexed by `docs/README.md`.
- The formal app shape is backend API under `aearn/services/api/app`, desktop frontend under `aearn/apps/desktop/src`, shared frontend/backend types under `aearn/packages/shared`, and infra/scripts under `aearn/infra` and `aearn/scripts`.
- The protected visual prototype remains `docs/design/learning-agent-claude-desktop-framework.html`; it must not be deleted or replaced.
- First-version baseline is already treated as release-ready; current docs also mention post-MVP / v1.1 work such as dynamic learning route generation, provider integration, and exercise-card UI improvements.
- The current task should audit code and docs first, then generate current-state docs; it should not blindly overwrite long-form source-of-truth docs before stale areas are identified.

## Requirements

- Re-read the current repository, including backend routes/services/agents/db, frontend pages/features/hooks/stores/API client, shared package, tests, scripts, infra, and current `docs/`.
- Produce a concise current-state documentation package that is accurate to current code and clearly flags implemented, partial, planned, and stale areas.
- Keep the package useful for interview preparation: project story, architecture explanation, core flow walkthroughs, trade-offs, demo path, and expected technical questions.
- Create the first-pass documentation package additively under `docs/current/`.
- Preserve existing source-of-truth docs in this task; do not directly replace `docs/product/*`, `docs/architecture/*`, `docs/qa/*`, or `docs/setup/*`.
- Avoid duplicating stale claims from existing docs without checking current code or tests.
- Use relative paths and exact commands inside generated docs so they are easy to verify from `E:\codee\Aearn`.
- Keep generated docs readable and maintainable; prefer a small package over rewriting every existing long-form spec.
- Follow-up scope approved by the user: classify which old docs should be archived or written back, then perform safe local writebacks for clearly stale small docs.
- Follow-up scope approved by the user: fix the desktop Vite large chunk warning without changing product behavior.

## Acceptance Criteria

- [ ] A current-state audit document identifies the main stale or risky areas found during code/docs comparison.
- [ ] A project overview / interview document explains the product value, MVP loop, and strongest technical talking points.
- [ ] A current architecture document maps frontend, backend, Agent, database, runner, SSE, and test boundaries to real paths.
- [ ] A current core-flows document maps major user flows to pages, API endpoints, services, persistence, Agent nodes, and tests where applicable.
- [ ] A current Agent / evaluation / review document explains LangGraph usage, runner capability boundaries, scoring, FSRS/review behavior, and known limitations.
- [ ] A demo / QA script document gives startup commands, demo steps, verification commands, and interview Q&A prompts.
- [ ] Generated docs do not delete or replace `docs/design/learning-agent-claude-desktop-framework.html`.
- [ ] Generated docs include enough implementation references that a reviewer can trace claims back to code, tests, or authoritative docs.
- [ ] `docs/current/current-state-audit.md` includes a concrete archive/writeback decision matrix for old docs.
- [ ] Clearly stale old docs are locally written back when the fix is low-risk and traceable to current code.
- [ ] `pnpm --dir .\aearn desktop:check` completes without the Vite `chunk size is larger than 500 kB` warning.
- [ ] Relevant validation is run, at minimum markdown/file existence checks plus available targeted build/test commands when feasible.

## Out of Scope

- Rewriting every existing source-of-truth document in place during the first pass.
- Changing product behavior or runtime logic. Build configuration changes are allowed only for the approved Vite chunk warning fix.
- Deleting protected design assets.
- Deploying or modifying production data.
- Creating a commit unless the user explicitly asks after review.

## Open Questions

- None currently blocking planning. The user confirmed the first implementation pass should create an additive `docs/current/` package.

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
