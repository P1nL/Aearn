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
| [Grounding Corpus Operations](./grounding-corpus-operations.md) | Local fixture-only operator CLI, replay, validation, safe output and runtime isolation | Filled |
| [Grounding Retrieval V2](./grounding-retrieval-v2.md) | Exact-scope FTS, fake embedding, facet coverage, bounded evidence and no public cutover | Filled |
| [Plan Preflight and Migration](./plan-preflight-migration.md) | Default-off server-fact preflight, immutable repair projections and no history mutation | Filled |
| [Grounding Shadow Integration](./grounding-shadow-integration.md) | Internal legacy-shape adapters, disposable fixture demo and no public release authority | Filled |
| [Grounding Material Contracts](./grounding-material-contracts.md) | Package A strict material/source contracts and default-deny authority ports; B is documented separately | Filled |
| [Grounding Controlled Discovery](./grounding-controlled-discovery.md) | B1 durable search/budget and B2 candidate-specific lease, safe fetch, quarantine, egress and default-off worker contracts | Filled |
| [Grounding Source Admission](./grounding-source-admission.md) | C default-off registered-source, Unix bridge, review, retention and corpus governance contracts; live acceptance remains separate | Filled |
| [Grounding Plan Material Consumption](./grounding-plan-material-consumption.md) | D internal default-off material feedback, successor bindings, same-transaction authorization and private receipt lifecycle | Filled |
| [Error Handling](./error-handling.md) | Error types and safe failure mapping | Filled |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, scenarios, and validation gates | Filled |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging and redaction | Filled |
| [Tutor Context References](./tutor-context-references.md) | Typed reference, safe snapshot, history, and injection contracts | Filled |
| [Learning Agent Integration and QA](./learning-agent-integration-qa.md) | Language matrix, execution-tier truthfulness, and readiness | Filled |
| [Teaching Session Authority](./teaching-session-authority.md) | Durable teaching session, checkpoint, stimulus, and action authority | Filled |
| [Learning Artifact Authority](./learning-artifact-authority.md) | Artifact lifecycle, owner delegation, snapshot v4, SSE, routes, redaction, and governance | Filled |
| [Learning Item Bank Governance](./learning-item-bank-governance.md) | Git source compilation, deterministic validation, independent review, pilot, risk gates, and publication | Filled |
| [Teaching Artifact Orchestration](./teaching-artifact-orchestration.md) | Candidate authority, atomic teaching commits, depth-one branches, and deterministic continuation scheduling | Filled |
| [Knowledge Check Artifacts](./knowledge-check-artifacts.md) | Structured scoring, assistance receipts, remediation/transfer selection, and evaluation continuation | Filled |
| [Model Review Artifacts](./model-review-artifacts.md) | Stable code/diff identity, deterministic findings, immutable receipts, remediation, and evaluation continuation | Filled |
| [Authoritative Execution Result Artifacts](./execution-result-artifacts.md) | Safe result v2, terminal projection, evaluation continuation, fallback, and cross-layer response identity | Filled |
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
