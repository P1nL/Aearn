# Backend Module Organization Design

## Architecture Intent

This child is a behavior-preserving structure refactor. It should make the backend easier to navigate without changing the product contract.

The current backend already has good high-level package boundaries:

- `app/routes` owns FastAPI HTTP/SSE route wiring.
- `app/models` owns Pydantic request/response/domain models.
- `app/db` owns schema bootstrap and seed data.
- `app/services` owns business orchestration, repositories, runner adapters, grounding, environment checks, and utility services.
- `app/agents` owns Aearn-specific OpenAI Agents SDK, graph orchestration, guardrails, and tool definitions.

The refactor should keep those top-level boundaries and only add one meaningful level below `services` and `agents`.

## Target `app/services` Package Map

Recommended target:

```text
app/services/
  __init__.py
  conversations/
    learning_conversation.py
    onboarding_conversation.py
    review_conversation.py
  curriculum/
    catalog.py
    plan_generator.py
    teaching_chunks.py
  environment/
    environment_doctor.py
  exercises/
    adaptive_exercise_service.py
    evaluation.py
    exercise_guidance.py
    exercise_repository.py
    exercise_templates.py
  grounding/
    grounding_citations.py
    grounding_fetcher.py
    grounding_fixtures.py
    grounding_index_repository.py
    grounding_processing.py
    grounding_reindex.py
    grounding_retrieval.py
    grounding_sources.py
  llm/
    llm_client.py
    llm_explain_error.py
    llm_urls.py
  repositories/
    dashboard_repository.py
    learner_profile.py
    learning_session_repository.py
    local_user_data_repository.py
    note_repository.py
    plan_repository.py
    review_repository.py
    review_scheduler.py
    review_seed_bank.py
    user_repository.py
  runners/
    browser_preview_runner.py
    language_capabilities.py
    managed_compiled_runner.py
    node_typescript_runner.py
    runner_registry.py
    runtime_contracts.py
    runtime_runner.py
    sandbox.py
    sandbox_runner.py
    sql_query_runner.py
  streaming/
    graph_event_stream.py
    sse.py
```

Notes:

- `language_capabilities.py` stays with `runners` because it gates runtime presentation, runner registry selection, and language execution disclosure.
- `environment_doctor.py` gets its own package because it crosses local process/toolchain checks and should not be hidden inside runner execution.
- `grounding_index_repository.py` stays with grounding because it owns grounding persistence and retrieval orchestration rather than general product repositories.
- `learner_profile.py` is grouped with repositories because it owns persisted learner-profile state assembly and updates.

## Target `app/agents` Package Map

Recommended target:

```text
app/agents/
  __init__.py
  graphs/
    graph_runtime_contracts.py
    learning_graph.py
    onboarding_graph.py
    review_graph.py
    router.py
  learning/
    exercise_coach_agent.py
    learning_concept_agent.py
    learning_conversation_agent.py
  notes/
    note_assist_agent.py
  onboarding/
    onboarding_conversation_agent.py
    onboarding_plan_agent.py
    onboarding_slot_extractor.py
    plan_generation_agent.py
  review/
    review_coach_agent.py
    review_conversation_agent.py
  runtime/
    agent_domain_contexts.py
    agent_runtime_context.py
    guardrails.py
    sdk_runtime.py
    structured_judgement.py
  tooling/
    tools.py
    tools_web.py
```

Notes:

- `graphs` separates deterministic orchestration contracts from SDK call adapters.
- `runtime` contains shared guardrails, SDK runtime, JSON/context helpers, and structured judgement helpers.
- `tooling` avoids a package named `tools` that would conflict with the existing `tools.py` module name during migration.

## Import Strategy

Accepted strategy:

1. Create subpackages with `__init__.py`.
2. Move files with history-preserving Git moves where practical.
3. Update first-party imports directly to the new paths.
4. Avoid long-lived compatibility wrappers unless a staged batch needs a short temporary adapter.
5. Remove any temporary adapters before closing the child unless the final review documents a concrete blocker.

Example:

```python
from app.services.runners.runner_registry import get_runner_registry
from app.agents.graphs.graph_runtime_contracts import GraphRunResult
```

## Compatibility Contract

The following must not change:

- FastAPI route paths and response envelopes.
- Database schema and seed data semantics.
- Public course ids and runtime profile disclosure.
- Runner status mapping and hidden redaction.
- Agent SSE event order and tool-call payload shape.
- Idempotency behavior for plan, learning, review, notes, and local user APIs.

This task may update import paths, module docstrings, `__init__.py` package markers, and backend directory documentation.

## Risk Areas

- Circular imports can appear when files move into subpackages but keep existing cross-domain dependencies.
- Tests and monkeypatch targets may still point to old module paths.
- `mypy` may reveal missing `__init__.py` package markers or stale imports.
- Agent SDK tests are sensitive to exact helper locations and monkeypatch paths.
- Root compatibility wrappers can hide stale imports and make the cleanup look done when it is not, so they are not part of the accepted final design.

## Rollback Strategy

- Keep the refactor in small move/update batches, so a failed batch can be reverted without touching behavior changes.
- If a subpackage creates circular imports, move the smallest shared helper into `agents/runtime`, `services/llm`, or a clearly documented shared package rather than introducing broad cross-imports.
- If a temporary compatibility wrapper is needed, track it explicitly in `implement.md` and remove it before final acceptance unless a concrete blocker is documented.
