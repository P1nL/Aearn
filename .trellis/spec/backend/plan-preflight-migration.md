# Plan Preflight and Migration Projections

## Scope

- Phase I only: internal, default-off shadow evaluation. No public route, plan-confirm, worker, startup or Desktop integration.
- `app/services/learning/plan_coverage.py` owns strict node requirements, server facts and deterministic reports. `plan_migration.py` owns repair and existing-track proposal projections.
- A proposal is a frozen, non-persisted projection, not a created successor revision, confirmation, activation or mastery receipt.

## Authority

- Requirements cover every node of the exact plan and bind Subject/version, facets, assessment capabilities and expected corpus generation/hash.
- Resolve canonical registry identities; unknown or incompatible scope fails closed. Framework facts cannot be replaced with base-language facts.
- The internal PostgreSQL fact reader receives an explicitly injected retrieval function. It must not import corpus operator modules or wire retrieval into public services.
- Corpus coverage is the exact request-bound v2 report. Published Learning Item handles come from current publication facts, not arbitrary free-text knowledge keys.
- Registry capability declarations do not prove a healthy live sandbox. Synthetic corpus coverage does not grant public release or lesson completion.
- `lc-overview` preserves its LangChain requirement. An unsupported core goal waits for release; it cannot be deleted, downgraded or rebound to ordinary Python to manufacture success.

## Deterministic Projection

- Keep supported, partial, insufficient and unavailable distinct. An uncovered required core blocks the target; optional repair requires explicit future confirmation. Preserve prerequisite targets and nonempty modules; the sole node of a required/non-skippable module cannot be treated as freely optional.
- Repair actions are server-owned and bounded. An enum value is not permission to fabricate a replacement: no verified compatible target means no replacement offer.
- Exact node diffs, reasons, target handles, source/capability facts, predecessor plan identity and policy version are bound into canonical hashes.
- Duplicate unchanged requests yield identical projections. Stale plan/source identities fail closed, rather than silently evaluating a different active version.
- Revalidate strict DTOs at authority boundaries; Pydantic `model_copy(update=...)` can bypass constructor validation. A self-reported hash is not an authorization signature.

## Transaction and History Rules

- Existing-track migration reads the immutable active revision with user/track ownership predicates and expected revision/content hash.
- Do not invoke existing `propose_revision` or `activate_revision`: those mutate track authority. Existing `read_active_plan` also acquires a row lock indirectly and is unsuitable for PostgreSQL READ ONLY probes.
- Use caller-owned coherent read-only/repeatable-read transactions for multi-read projections. No commits, rollbacks, locks, mutations or external IO inside the sidecar.
- Preserve active pointer, node progress, assignments, Lesson documents/failures, publication events and all other authority. A new proposal does not repair an old failure record.

## Verification

- Offline functional tests: all statuses under explicitly synthetic facts, core/optional differences, exact coverage, stale/replay behavior, no LangChain fallback, strict invalid input and forged report denial.
- Static boundary tests: no public/worker/startup references; no obvious mutation SQL, operator/provider/network imports or automatic entrypoints. Static scans are not transitive call-graph proofs.
- Real disposable PostgreSQL: actual published synthetic corpora, immutable tracks and preserved failed Lesson runs; execute projection under READ ONLY + REPEATABLE READ, compare full table content hashes and transaction identity before/after.
- Run existing plan-confirm/session and learning-track regressions with disabled provider and isolated database. Never bootstrap the user's business database for verification.
- Keep real-source ingestion, real embedding, public migration UI/activation and learner end-to-end acceptance explicitly out of scope.
