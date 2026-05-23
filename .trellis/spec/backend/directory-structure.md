# Directory Structure

> How backend code is organized in this project.

---

## Overview

The formal Aearn MVP must be implemented under `aearn/`. Historical tutorial directories `01_` through `07_` are reference material only and must not be converted into the formal app runtime.

---

## Directory Layout

```text
aearn/
  services/
    api/
    worker/
  packages/
    shared/
  infra/
```

---

## Module Organization

- `services/api/` owns FastAPI, API contracts, database access, and LangGraph orchestration entry points.
- `services/api/app/agents/` owns Aearn-specific OpenAI Agents SDK application modules. SDK code belongs here, not inside route handlers or repository modules.
- `services/worker/` owns asynchronous task execution and Celery integration.
- `packages/shared/` owns shared contracts only after they are needed by more than one runtime.
- `infra/` owns Docker Compose and local service wiring.

---

## Naming Conventions

- Keep the formal runtime under `aearn/`; do not add new MVP code to `01_` through `07_`.
- Use lowercase directory names for services and packages: `api`, `worker`, `shared`, `infra`.
- Use Python package/module names in `snake_case` when API source files are introduced in Milestone 1.
- Keep service-local dependency files inside the owning service. The current backend dependency source is `aearn/services/api/pyproject.toml`, not a repository-root `requirements.txt`.
- Keep generated caches, virtual environments, logs, and build outputs out of source conventions.

---

## Examples

- `aearn/services/api/pyproject.toml`
- `aearn/services/api/app/agents/learning_conversation_agent.py`
- `aearn/services/api/README.md`
- `aearn/infra/docker-compose.yml`

## Common Mistakes

- Running Python commands from the repository root. This repository has multiple independent projects and no root Python dependency file.
- Treating historical tutorial directories as shared packages. They are reference material only for the formal Aearn MVP.
- Adding formal API or worker code before checking the task against `docs/plans/learning-agent-implementation-plan.md`.
