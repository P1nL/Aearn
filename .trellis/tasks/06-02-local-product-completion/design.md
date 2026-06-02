# Local Product Completion Design

## Role of This Parent Task

This parent task is an integration and sequencing contract. It does not own direct runtime implementation except final cross-child integration review. Concrete code changes should happen in independently planned child tasks.

The parent owns:

- product-level scope and non-goals
- child task tree and ownership boundaries
- dependency contracts between children
- phase ordering
- final local-product readiness criteria

## Architecture Boundaries

The local product completion work spans four existing system layers:

- Desktop app and UI flows under `aearn/apps/desktop`.
- API routes, services, repositories, graph runtime, runners, and grounding services under `aearn/services/api`.
- Worker/background process behavior under `aearn/services/worker` when needed for local jobs.
- Documentation and local setup contracts under `docs/` and repo-level scripts.

Existing ownership boundaries should be preserved:

- Graph/runtime layers decide next teaching actions.
- Services validate, execute, and orchestrate business operations.
- Repositories own persistence and database shape.
- Desktop UI displays state and invokes APIs; it should not duplicate backend capability decisions.
- Runner adapters own toolchain-specific execution, safety boundaries, and failure mapping.
- Grounding services own trusted source registry, indexing, retrieval, citation packaging, and observability.
- Backend module organization work may add domain subpackages under `app/services` and `app/agents`, but must keep the same top-level ownership boundaries and public contracts.

## Product Capability Domains

### Local Stack

The product must expose one reliable local startup/check path for API, database, Redis, worker, and desktop. Child tasks should prefer durable scripts and health checks over documentation-only instructions.

### Local Data Boundary

The product is local-only but still needs clear user/data boundaries: route/session/review/note/profile/settings isolation, reset, export, and deletion behavior.

### Learning Experience

The desktop loop must remain coherent across onboarding/route creation, learning page, exercise flow, review, notes, and settings. Child tasks must preserve the existing MVP behavior unless explicitly replacing it.

### Grounding and RAG

The project has two different grounding layers:

- Internal lesson RAG from persisted teaching chunks.
- Official/trusted language documentation grounding from allowlisted docs.

The productized design should keep those layers separate in contracts and prompts. Internal lesson chunks provide current lesson context. Official/trusted documentation chunks provide factual language grounding and citation material.

Official/trusted docs grounding must be indexed locally before use in chat. Runtime chat should not perform arbitrary live web search or dynamic crawling.

### Environment Doctor

Environment checks should be based on detected local facts: executable availability, version output, API/database/Redis/worker health, Docker/WSL status when applicable, and runner readiness.

The agent may explain detected issues but install guidance must come from allowlisted static templates.

### L3 Runners

Runner contracts target teaching exercises only. They should use temporary workspaces, timeouts, bounded output, no network by default, no writes into the project directory, stable failure categories, and hidden-test redaction.

Runner support must be capability-gated. A language should not appear executable until its runner adapter, tests, and UI/API disclosures agree.

### Adaptive Exercises

Dynamic exercise variants must be generated from canonical templates and validated by the matching runner before becoming visible to learners. Failed validation must fall back to stable canonical templates.

### Agent Quality Gates

Agent quality gates should cover the full product contract: answer-seeking behavior, repeated confusion, capability overclaims, missing citations, runner failures, grounding failures, and adaptive exercise safety.

### Backend Module Organization

Backend structure cleanup should happen after the main runner, grounding, data-boundary, and adaptive exercise modules exist. Its goal is to make final integration review and future maintenance easier, not to change behavior.

The cleanup should group flat `app/services` and `app/agents` modules into domain subpackages while preserving route, API, database, runner, graph, and Agent behavior.

## Data Flow Contracts

### Learning Grounding Flow

1. Knowledge point and exercise content are indexed into internal teaching chunks.
2. Official/trusted docs are fetched from allowlisted seed URLs through a deterministic reindex/fixture flow.
3. Cleaned docs are chunked and persisted with source metadata.
4. Learning message preparation retrieves internal chunks and optional docs grounding.
5. Tutor prompt evidence distinguishes lesson context from docs grounding.
6. Agent output metadata carries citation payloads when docs grounding is used.
7. Stream/debug observability reports retrieval status, chunk count, and fallback reason without leaking hidden data.

### Runner Flow

1. Capability matrix determines whether a language can be presented as executable.
2. Environment doctor determines whether local toolchains are available.
3. Runner registry selects the adapter or returns an unsupported/missing-toolchain result.
4. Adapter runs in a bounded temporary workspace and maps results to stable runtime categories.
5. API stores attempts and returns learner-safe output.
6. Agent and UI use only learner-safe runner summaries.

### Adaptive Exercise Flow

1. Canonical exercise template defines the knowledge point, scoring contract, expected runner, visible tests, hidden tests, and fallback exercise.
2. Candidate variant is generated from bounded context.
3. Candidate is validated by the matching runner.
4. Validated variant is versioned and cached.
5. Failed validation falls back to canonical template and records the failure for eval/debugging.

## Compatibility and Migration Notes

- Preserve existing MVP learning, review, note, graph, and FSRS tests.
- Do not break current public course language IDs: `javascript`, `python`, `java`, `cpp`, and `html_css`.
- Keep TypeScript, Go, C#, Rust, and SQL disclosures honest while their public/runtime support changes across phases.
- Existing internal teaching chunks should continue working while official docs grounding is added.
- Any new persisted grounding index must have deterministic bootstrap/reindex behavior for local development.

## Operational and Rollback Considerations

- Local startup changes must be reversible to existing manual commands.
- Environment doctor failures should not block unrelated local learning flows.
- Grounding failures should degrade to internal lesson context or no docs citations, not crash learning chat.
- Runner failures should return stable error categories, not raw subprocess internals.
- Adaptive exercise validation failures should fall back to canonical templates.
- Backend module moves should be batched and behavior-preserving; stale imports or circular imports should fail fast in focused tests before broader changes continue.
- Each child task must list rollback points for schema, scripts, runner adapters, and UI changes it owns.

## Trade-Offs

- Prefer local deterministic indexing over chat-time web fetches. This reduces freshness but improves safety, repeatability, and citation control.
- Prefer native local toolchain detection over bundling all runtimes. This keeps the product lighter but requires clearer missing-toolchain guidance.
- Prefer staged runner rollout over claiming broad language execution early. This avoids product overclaims and keeps the learning contract honest.
- Defer vector search until source persistence, citation behavior, and eval gates are stable. Current risk is product wiring and trust, not just retrieval ranking.
