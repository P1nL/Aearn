# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | Filled |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | Filled |
| [Error Handling](./error-handling.md) | Error types, handling strategies | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | Filled |
| [Tutor Context References](./tutor-context-references.md) | Cross-layer typed reference, safe snapshot, history, and context-injection contract | Filled |
| [Learning Agent Integration and QA](./learning-agent-integration-qa.md) | Final language matrix, execution-tier truthfulness, cutover schema inventory, and readiness contract | Filled |
| [Codex Runtime Sidecar](./codex-runtime-sidecar.md) | Aearn-owned App Server contracts, ownership, typed LearningPlan tools, bounded repair/fencing, and dedicated worker lifecycle | Filled |

---

## How to Use These Guidelines

Before backend work:

1. Read the guide that matches the touched layer.
2. Cross-check the task against `docs/architecture/api-contract.md`, `docs/architecture/database-schema.md`, and the current milestone in `docs/plans/learning-agent-implementation-plan.md`.
3. Run commands from the owning subproject, not the repository root.

The goal is to help AI assistants and new team members follow the current Aearn runtime conventions instead of the historical tutorial projects.

---

**Language**: All documentation should be written in **English**.
