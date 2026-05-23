# Evaluate OpenAI Agents SDK foundation

## Goal

Evaluate whether `openai/openai-agents-python` should become Aearn's Agent runtime foundation, then define a safe migration path that preserves the existing Aearn product, API, database, deterministic runner, SSE streaming, idempotency, tests, and release gates.

The first user value is architectural clarity: decide whether Aearn should keep its current LangGraph-first implementation and add OpenAI Agents SDK as an adapter, or pivot more aggressively toward the SDK as the primary Agent loop.

## Confirmed Facts

- Aearn's runtime is under `aearn/`, not the repository root.
- `aearn/services/api` is the main FastAPI backend; `aearn/services/worker` is the Celery worker; `aearn/infra/docker-compose.yml` starts local PostgreSQL and Redis.
- Current backend dependencies already include `langchain==1.2.0`, `langchain-openai==1.1.6`, `langgraph==1.0.5`, and `langgraph-checkpoint-postgres==3.0.2`.
- Current `uv.lock` already contains `openai==2.36.0`.
- The OpenAI Agents SDK package is `openai-agents`; current upstream metadata requires `openai>=2.26.0,<3`, so it is likely dependency-compatible with the current lock.
- Aearn already has a narrow LLM/provider boundary in `app/services/llm_client.py`.
- Aearn's learning conversation worktree changes already introduce a `TextCompletionClient` protocol and streaming message route shape that can be adapted without replacing the whole backend.
- Source-of-truth docs already define the product/API/state-machine/QA boundaries, especially `docs/architecture/api-contract.md`, `docs/architecture/langgraph-state-machine.md`, `docs/architecture/code-completion-evaluation-spec.md`, and `docs/qa/acceptance-test-plan.md`.
- Official SDK docs position the Agents SDK as a higher-level runtime around Responses API model calls, with Agents, tools, handoffs, guardrails, sessions, tracing, and streaming.
- Official SDK docs state that many non-OpenAI providers still do not support Responses API or structured outputs reliably; third-party or Chat Completions paths may be needed for provider compatibility.

## Requirements

- Decide whether OpenAI Agents SDK should be used as:
  - a focused adapter under Aearn's existing architecture;
  - the primary Agent runtime for selected backend flows;
  - or a broader replacement for the current LangGraph-oriented design.
- Preserve Aearn's existing product source of truth and API contracts unless the task explicitly updates docs first.
- Do not fork or vendor `openai/openai-agents-python` as the default approach.
- Keep Aearn's database ownership in the backend repositories and existing schema, not in SDK session abstractions by default.
- Preserve deterministic fallback paths so tests and local MVP smoke do not require a real model API key.
- Preserve existing SSE event contracts and frontend rendering expectations.
- Preserve existing `Attempt`, `ReviewState`, FSRS, runner, and code-completion evaluation semantics.
- Evaluate whether SDK features add enough value for Aearn:
  - function tools;
  - guardrails;
  - handoffs / multi-agent orchestration;
  - sessions;
  - tracing;
  - streaming result surfaces.
- Identify the smallest safe spike slice before any broad migration.
- Keep current in-progress streaming-learning-conversation changes separate from this new task's scope and commits.

## Acceptance Criteria

- [ ] A written decision is available in this task: adapter-first, SDK-primary, or no migration.
- [ ] `design.md` documents the target integration boundary, data flow, provider compatibility constraints, rollback shape, and trade-offs.
- [ ] `implement.md` documents a staged implementation plan with validation commands and rollback points.
- [ ] The plan identifies which existing Aearn contracts cannot be delegated to the SDK.
- [ ] The plan identifies the first safe spike endpoint or service.
- [ ] The plan explains how deterministic fallback and tests remain model-key-free.
- [ ] The plan explains how third-party OpenAI-compatible providers are handled.
- [ ] The plan does not require deleting or replacing protected product docs or frontend prototype assets.
- [ ] No implementation starts until the task is explicitly moved from `planning` to `in_progress`.

## Out of Scope For Planning

- Forking or modifying upstream `openai-agents-python`.
- Replacing FastAPI, PostgreSQL, Tauri, Celery, or the deterministic runner.
- Changing Aearn's product scope from programming-language learning for AI coding.
- Replacing the current API contract before documenting the migration.
- Removing LangGraph from dependencies before a dedicated compatibility decision.
- Running real model calls or requiring production API keys.

## Open Question

- Which foundation strategy should this task optimize for first?
  - Recommended: adapter-first spike. Keep Aearn's current state machine and contracts, and introduce the SDK behind the existing LLM/client protocols for one endpoint first.
  - Alternative: SDK-primary runtime. Move selected flows to `Agent` + `Runner` + tools as the main orchestration layer, while keeping Aearn DB writes outside SDK state.
  - High-risk alternative: broad replacement. Redesign the backend around Agents SDK sessions/tools/handoffs. This is not recommended for the current MVP because it would destabilize contracts and tests.
