# Evaluate OpenAI Agents SDK foundation

## Goal

Evaluate whether `openai/openai-agents-python` should become the foundation for the Aearn learning Agent product, then define the safest way to build or reshape Aearn around that framework without losing the existing product scope, source-of-truth docs, deterministic validation, and release gates.

The user clarified on 2026-05-23 that the intent is broader than a backend LLM adapter: the goal is to add functionality on top of the OpenAI Agents SDK framework, or transform that framework into the desired programming-language learning Agent.

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
- Earlier planning selected an adapter-first spike, but that decision is now superseded by the user's clarification that they are considering a framework-based product build.
- User decision on 2026-05-23: choose `application-on-SDK`.

## Requirements

- Build Aearn as an `application-on-SDK`: Aearn depends on `openai-agents` and implements learning-agent product behavior in Aearn-owned modules.
- Do not fork or vendor `openai/openai-agents-python`.
- Do not modify SDK internals for the MVP.
- Use SDK primitives such as `Agent`, `Runner`, function tools, guardrails, handoffs, tracing, and optional sessions where they serve Aearn's learning flows.
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

- [x] A written decision is available in this task: application-on-SDK.
- [x] `design.md` documents the target integration boundary, data flow, provider compatibility constraints, rollback shape, and trade-offs.
- [x] `implement.md` documents a staged implementation plan with validation commands and rollback points.
- [x] The plan identifies which existing Aearn contracts cannot be delegated to the SDK.
- [x] The plan identifies the first safe spike endpoint or service.
- [x] The plan explains how deterministic fallback and tests remain model-key-free.
- [x] The plan explains how third-party OpenAI-compatible providers are handled.
- [x] The plan does not require deleting or replacing protected product docs or frontend prototype assets.
- [x] No implementation starts until the task is explicitly moved from `planning` to `in_progress`.

## Out of Scope For Planning

- Forking or modifying upstream `openai-agents-python`.
- Replacing FastAPI, PostgreSQL, Tauri, Celery, or the deterministic runner.
- Changing Aearn's product scope from programming-language learning for AI coding.
- Replacing the current API contract before documenting the migration.
- Removing LangGraph from dependencies before a dedicated compatibility decision.
- Running real model calls or requiring production API keys.

## Superseded Decisions

- Previous strategy: adapter-first spike.
- Status: superseded by user clarification.
- Rejected strategy: upstream SDK fork.
- Rejected strategy for MVP: broad SDK-primary rewrite of all Aearn flows.

## Decision

- Chosen strategy: application-on-SDK.
- Aearn will treat `openai-agents-python` as an upstream framework dependency.
- Aearn-owned code will define the learning Agent app layer: teaching Agent, hint Agent, note assist Agent, safe tools, guardrails, and Aearn contract adapters.
- First implementation slice remains learning conversation messages, but it should be framed as the first Aearn Agent module rather than as a generic LLM adapter.
- Deferred: SDK-managed durable product state, SDK tools that directly write grading/review state, upstream fork, and full LangGraph replacement.
