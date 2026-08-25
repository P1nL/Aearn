# Directory Structure

> How backend code is organized in the current Aearn Tutor Harness runtime.

---

## Overview

Formal product code lives under `aearn/`. The repository root owns Git, Trellis, documentation, and agent configuration. Historical tutorial directories and the removed SDK-Agent/LangGraph product runtime are not implementation sources.

---

## Service Layout

```text
aearn/
  services/
    api/
      app/
        agents/
        core/
        db/
        models/
        routes/
        services/
      tests/
    worker/
    executor/
  packages/
    shared/
  infra/
    executor/
  scripts/
```

- `services/api/` owns the FastAPI public boundary, Tutor Harness composition, PostgreSQL access, current learning services, and the controlled Codex Sidecar adapter.
- `services/worker/` owns Celery wakeup delivery and reconciliation. PostgreSQL remains the durable queue/lease authority.
- `services/executor/` owns the standalone container executor service and protocol implementation.
- `packages/shared/` owns pure versioned contracts used by more than one runtime. It must not acquire database, environment-reader, subprocess, or container-client dependencies.
- `infra/` owns Docker Compose and reviewed executor runtime image definitions/locks.
- `scripts/` owns product-workspace orchestration such as `start-dev.ps1`.

---

## API Application Packages

### `app/routes/`

HTTP/SSE transport only: request validation, ownership lookup, service invocation, safe error mapping, and response serialization. Route handlers do not own provider orchestration or durable business rules.

### `app/services/`

Domain package root. New modules go into the narrowest current package:

- `tutor/`: Tutor run lifecycle, interaction authority, queueing, public projection, provider gateway, persistence, proactive delivery, curation, and cutover.
- `learning/`: tracks, plans, lessons, teaching sessions, context references, mastery, practice, review sessions, and related repositories/policies.
- `exercises/`: adaptive exercise templates, validation, deterministic evaluation, and exercise persistence.
- `grounding/`: trusted sources, fetch/process/retrieve/citation contracts, fixtures, and indexing.
- `runners/`: language/runtime contracts and controlled runner registry.
- `llm/`: provider-neutral clients and safe provider error normalization.
- `environment/`: local capability and environment diagnostics.
- `curriculum/`: course catalog and curriculum/grounding support that is not owned by the current learning package.
- `repositories/`: product repositories not already owned by a narrower domain package.
- `streaming/`: shared SSE utilities only.

Do not recreate removed `services/conversations/` behavior for onboarding/legacy learning/review flows. Empty local directories retained only by caches are not runtime packages.

### `app/agents/`

Controlled model/runtime boundaries, not a generic Agent tree:

- `harness/`: Tutor Harness context, contracts, policy, skill selection, provider request, and run-loop support.
- `runtime/`: controlled Codex App Server adapter/supervisor contracts.
- `skills/`: versioned Tutor Skill bundles and catalog resources.
- `codex_spike/`: bounded compatibility/preflight research retained only where current code still imports it.

Do not recreate removed `graphs/`, `learning/`, `notes/`, `onboarding/`, `review/`, or `tooling/` product packages. Archived documents that mention them are historical evidence.

### `app/db/`

Connection, bootstrap, seeds, and the current PostgreSQL schema source. `app/db/schema/__init__.py` owns the explicit fragment manifest; `app/db/schema/*.sql` owns the ordered SQL. Directory traversal is not execution authority, and loaders do not commit transactions owned by callers.

---

## Modularity Rules

- Root-level `app/services/*.py` and `app/agents/*.py` modules remain exceptional.
- Split modules by cohesive authority boundary, not by arbitrary line count alone.
- A file that owns multiple independent domains, mappings, queues, or projections should become a package/facade before additional responsibilities are added.
- Persistence extraction must preserve one caller-owned connection, transaction atomicity, idempotency, lease fencing, and stale checks.
- Public import paths should remain stable through package `__init__.py` exports during structural migrations.
- Tests should mirror domain ownership and keep shared helpers under an explicit support package.

---

## Source of Truth

Start from `docs/README.md`. In particular:

- runtime/security: `docs/architecture/tutor-harness-runtime.md`
- HTTP/SSE: `docs/architecture/api-contract.md`
- PostgreSQL: `docs/architecture/database-schema.md`
- development: `docs/setup/development-environment.md`
- validation: `docs/qa/acceptance-test-plan.md`

Historical plans and `docs/archive/` never override current code, tests, configuration, or the current documentation index.

---

## Common Mistakes

- Running Python tooling from the repository root and creating root-level caches or dependency state.
- Reintroducing old tutorial, onboarding, top-level review, notes, SDK-Agent, router, or LangGraph product directories.
- Putting durable writes in routes, provider adapters, Skills, or model-authored payload handling.
- Splitting repositories in a way that introduces independent connections or partial commits.
- Treating an archived implementation plan as current runtime authority.
