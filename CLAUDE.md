# CLAUDE.md

This repository is the Aearn MVP workspace for an AI programming language learning agent.

## Project Structure

- `aearn/` is the formal runtime workspace.
- `aearn/services/api/` contains the FastAPI service.
- `aearn/services/worker/` contains worker-side scheduling and async task code.
- `aearn/apps/desktop/` contains the React + Tauri desktop app.
- `aearn/packages/` contains shared project packages.
- `aearn/infra/` contains local infrastructure configuration.
- `docs/` contains the product, architecture, API, database, interaction, and acceptance source documents.
- `docs/design/learning-agent-claude-desktop-framework.html` is the user-designed protected frontend prototype and must not be deleted without explicit user confirmation.

Legacy tutorial project files have been removed from the current working tree. Do not recreate or depend on them for new Aearn work.

## General Guidelines

- Run project commands from `aearn/` unless a task explicitly targets repo-level docs or Trellis files.
- Use `docs/README.md` to find the current source document before changing behavior.
- Keep secrets, local environment files, build outputs, dependency folders, and tool worktrees out of Git.
- Prefer the smallest relevant verification command before claiming work is complete.
