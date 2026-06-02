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

### API Service Subpackages

Keep `services/api/app/services/` and `services/api/app/agents/` as domain package roots. New backend modules should go into the narrowest existing subpackage instead of returning these roots to a large flat layout.

`services/api/app/services/` is organized as:

- `conversations/`: learning, onboarding, and review conversation orchestration services.
- `curriculum/`: course catalog, plan draft generation, and teaching chunk indexing/search.
- `environment/`: local toolchain and environment doctor checks.
- `exercises/`: exercise templates, adaptive exercise generation, exercise persistence, and deterministic evaluation helpers.
- `grounding/`: trusted documentation source registries, fetching, processing, retrieval, citations, fixtures, reindexing, and grounding persistence.
- `llm/`: OpenAI-compatible client helpers, model error types, URL normalization, and LLM-backed explanation helpers.
- `repositories/`: persistence-oriented product repositories and schedulers for dashboard, users, plans, sessions, notes, reviews, learner profiles, and local data boundaries.
- `runners/`: runtime contracts, runner registry, browser preview, Python sandbox, Node/TypeScript, SQL, managed compiled, and language capability modules.
- `streaming/`: SSE utilities and graph event stream adapters.

`services/api/app/agents/` is organized as:

- `graphs/`: graph runtime contracts, graph orchestration modules, and routing.
- `learning/`: learning conversation, concept, and exercise-coach SDK agents.
- `notes/`: note-assist SDK agents.
- `onboarding/`: onboarding conversation, slot extraction, plan generation, and onboarding plan SDK agents.
- `review/`: review coach and review conversation SDK agents.
- `runtime/`: shared SDK runtime, guardrails, structured judgement, runtime context, and domain context helpers.
- `tooling/`: agent tool definitions and web-tool adapters.

Root-level `services/api/app/services/*.py` and `services/api/app/agents/*.py` modules should remain exceptional. If a root module is unavoidable, document why it is shared across all subpackages before adding it.

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
