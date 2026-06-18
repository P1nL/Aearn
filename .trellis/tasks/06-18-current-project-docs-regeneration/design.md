# Regenerate Current Project Documentation Design

## Scope Decision

Generate an additive documentation package under `docs/current/`. The first pass does not replace the existing source-of-truth docs in `docs/product/`, `docs/architecture/`, `docs/qa/`, or `docs/setup/`.

The package is a current-state readout for interview preparation and repo handoff. It may point out stale source-of-truth areas; broad source-of-truth rewrites or whole-document archival should remain a later task after review.

Follow-up scope approved by the user on 2026-06-18:

- Add an old-doc archive/writeback decision matrix without adding a seventh `docs/current/` file.
- Perform low-risk local writebacks for clearly stale small docs.
- Fix the desktop Vite large chunk warning via build chunking only, without changing product UI/runtime behavior.

## Deliverables

Create exactly these six markdown files:

1. `docs/current/current-state-audit.md`
2. `docs/current/project-overview-interview.md`
3. `docs/current/architecture-current.md`
4. `docs/current/core-flows-current.md`
5. `docs/current/agent-evaluation-review-current.md`
6. `docs/current/demo-qa-script.md`

`current-state-audit.md` should serve as the package entry point and include links to the other five files, so no extra `README.md` is required for this first pass.

## Evidence Model

Every high-level claim should be grounded in one of these evidence classes:

- Current code: `aearn/services/api/app/**`, `aearn/apps/desktop/src/**`, `aearn/packages/shared/**`, `aearn/scripts/**`, `aearn/infra/**`.
- Tests: `aearn/services/api/tests/**`.
- Current docs: `docs/README.md` plus existing product, architecture, QA, setup, and design files.
- Project configuration: `aearn/package.json`, `aearn/services/api/pyproject.toml`, workspace and docker compose files.

When code and old docs disagree, the generated package should say so explicitly instead of silently picking one.

## Current Module Boundaries To Audit

Backend:

- API routes: `courses`, `dashboard`, `environment`, `health`, `learning_sessions`, `notes`, `onboarding`, `plans`, `reviews`, `users`.
- Services: conversations, curriculum, environment, exercises, grounding, LLM, repositories, runners, streaming.
- Agent runtime: graphs, learning, notes, onboarding, review, runtime, tooling.
- Persistence: `app/db/schema.sql`, bootstrap, connection, seeds.

Frontend:

- Pages: `LearningWorkspacePage`, `NotesPage`, `OnboardingPage`, `ReviewPage`, `SettingsPage`.
- Learning/onboarding feature components.
- Hooks: assistant runtime, auto-save, SSE.
- Stores: app, notes, settings.
- API client and shared types.

Verification and operations:

- Backend tests under `aearn/services/api/tests`.
- `aearn/scripts/start-dev.ps1`.
- `aearn/infra/docker-compose.yml`.
- Desktop scripts in `aearn/package.json`.

## Staleness Classification

Use the following terms consistently:

- `Implemented`: current code and tests support the claim.
- `Partially implemented`: code exists but coverage, UX, or contract is incomplete.
- `Documented / planned`: docs describe it but code evidence is absent or incomplete.
- `Stale risk`: existing docs appear older than current code or contain claims that require follow-up.
- `Out of scope`: outside this documentation package or outside the current product boundary.

## Documentation Style

- Write in Simplified Chinese for interview and handoff readability.
- Keep code identifiers, paths, commands, API endpoints, environment variables, and model/provider names in English.
- Prefer tables for traceability maps.
- Include exact relative paths from repository root.
- Avoid presenting aspirational features as implemented.
- Preserve the protected prototype boundary: `docs/design/learning-agent-claude-desktop-framework.html` is reference material, not runtime code.

## Compatibility And Rollback

Rollback is deleting `docs/current/` and reverting the Trellis planning files, local doc writebacks, and `aearn/apps/desktop/vite.config.ts` if needed. No database, product runtime logic, production data, or deployment state should change.
