# Audit and Archive Stale Docs

## Goal

Audit `docs/` against the current Aearn runtime and source-of-truth structure, then archive documents that are obsolete as whole documents and update stale sections in documents that should remain active.

The output should leave `docs/README.md` as the accurate navigation entry for first-time readers and future agents.

## User Request

The user asked: "检查docs的文档有没有过期,过期的需要归档".

The user approved creating this Trellis task.

## Confirmed Facts

- Current active source-of-truth index is `docs/README.md`.
- Current formal runtime lives under `aearn/`.
- Current API service lives under `aearn/services/api/`.
- Current desktop app lives under `aearn/apps/desktop/`.
- Current worker lives under `aearn/services/worker/`.
- Current local Docker Compose file is `aearn/infra/docker-compose.yml`.
- Current database initialization is `aearn/services/api/app/db/bootstrap.py` plus `aearn/services/api/app/db/schema.sql`, not Alembic.
- There is no existing `docs/archive/` directory.
- `docs/design/learning-agent-claude-desktop-framework.html` is a protected user design asset and must not be deleted or archived unless the user explicitly asks.
- The newly added `docs/setup/newcomer-onboarding-guide.md` is an auxiliary guide and intentionally does not replace the source-of-truth specs.
- Initial stale-reference scan found old implementation assumptions in `docs/setup/development-environment.md`, including `migrations/`, `apps/api`, and Alembic commands.

## Requirements

- Audit every file under `docs/`, including markdown, HTML prototype, and design assets.
- Classify each document as one of:
  - `active`: keep in the current docs tree and index.
  - `active-with-stale-sections`: keep the document but update stale sections.
  - `archive`: move the whole document out of the active navigation because it is fully superseded or no longer useful as an active guide.
  - `protected`: keep untouched except for index wording, if needed.
- Do not archive a document merely because it says `Draft V1` or contains a future/backlog section; archive only when the whole document is superseded, misleading, duplicate, or disconnected from the current implementation.
- Preserve history by moving stale docs into an archive location rather than deleting them.
- Update `docs/README.md` so active docs, auxiliary docs, and archived docs are clearly separated.
- If an active source-of-truth document contains stale paths or commands, update the stale sections instead of archiving the whole file.
- Keep all changes scoped to documentation and Trellis task artifacts unless evidence shows a small script/check is needed.
- Do not touch `.claude/settings.local.json` or other unrelated local state.

## Acceptance Criteria

- [x] Every `docs/` file is listed in an audit table with classification and reason.
- [x] Whole-document archive candidates are moved under a clear archive path, preserving enough context to understand why they were archived. No whole-document archive candidates were found in this audit.
- [x] Active documents no longer point readers to stale runtime paths such as `aearn/infra/docker/`, root `migrations/`, or `apps/api` when current code uses different paths.
- [x] `docs/README.md` accurately lists active source-of-truth documents, auxiliary documents, protected assets, and archive location.
- [x] Current protected prototype remains at `docs/design/learning-agent-claude-desktop-framework.html`.
- [x] Documentation validation commands run and results are recorded in the final response.
- [x] `git status --short` is reviewed so unrelated local changes are not mixed into the documentation cleanup.

## Out of Scope

- Implementing product or runtime code.
- Rewriting the product direction.
- Replacing the protected desktop prototype.
- Committing changes unless the user explicitly asks.
- Archiving Trellis task directories; this task is only about `docs/`.

## Archive Layout Decision

Recommended archive layout: `docs/archive/2026-05-24/`, with an `README.md` explaining archive criteria and listing moved files.

Trade-off: a dated archive is easy to audit and reversible, but it creates one additional directory. A flat `docs/archive/` is simpler but can become messy after multiple cleanup passes.

Execution note: this audit found no whole-document archive candidates, so no archive directory was created.
