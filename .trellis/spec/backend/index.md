# Backend Development Guidelines

> Current backend development rules for the Aearn Tutor Harness runtime.

---

## Overview

The formal backend lives under `aearn/services/`. Runtime facts come from current code, tests, configuration, and the documents indexed by `docs/README.md`; historical plans and archived Agent/Graph material are evidence only.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Service ownership, package boundaries, and module layout | Filled |
| [Database Guidelines](./database-guidelines.md) | PostgreSQL schema, transaction, query, and migration rules | Filled |
| [Error Handling](./error-handling.md) | Error types and safe failure mapping | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, scenarios, and validation gates | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging and redaction | Filled |
| [Tutor Context References](./tutor-context-references.md) | Typed reference, safe snapshot, history, and injection contracts | Filled |
| [Learning Agent Integration and QA](./learning-agent-integration-qa.md) | Language matrix, execution-tier truthfulness, and readiness | Filled |
| [Teaching Session Authority](./teaching-session-authority.md) | Durable teaching session, checkpoint, stimulus, and action authority | Filled |
| [Learning Artifact Authority](./learning-artifact-authority.md) | Artifact lifecycle, owner delegation, snapshot v4, SSE, routes, redaction, and governance | Filled |
| [Codex Runtime Sidecar](./codex-runtime-sidecar.md) | App Server contracts, typed tools, fencing, and worker lifecycle | Filled |

---

## How to Use These Guidelines

Before backend work:

1. Read the guide matching the touched layer.
2. Start from `docs/README.md`, then read the current architecture, API, database, setup, or QA document it designates for the surface.
3. Verify behavior against current code, route registration, schema, tests, and configuration; never restore archived runtime structure from historical plans.
4. Run commands from the owning subproject, not the repository root.

The goal is to preserve the current Tutor Harness and controlled Codex Sidecar boundaries rather than the removed tutorial, SDK-Agent, router, or LangGraph product runtime.

---

**Language**: Project specs may remain English unless a task-specific rule requires another language. Trellis task artifacts under `.trellis/tasks/**` follow the repository's Simplified Chinese rule.
