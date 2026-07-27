# Current Skill and Capability Baseline

## Purpose

This research records the verified implementation boundary for Child 01 before
introducing a versioned Skill catalog or a catalog-aware capability gateway.
It distinguishes the feature-disabled Tutor Harness target from legacy
LangGraph/SDK agent tooling so this child does not silently reintroduce a
stage router, direct domain write, arbitrary web request, or database coupling.

## Child 00 Harness Seam

- `app/agents/harness/contracts.py:167-206` already reserves bounded
  `TutorContextInput.capability_schemas` context, and
  `app/agents/harness/context_builder.py:108-190` deterministically bounds and
  redacts that section with the rest of the Tutor context.
- `TutorSkillReference` is currently only an opaque identifier plus a default
  `"current"` version (`contracts.py:338-345`). Child 01 must replace the
  unpinned default with resolution to a published semantic version before a
  reference becomes executable.
- `TutorCapabilityRequest` and `TutorEffectProposal` are already bounded
  envelope values (`contracts.py:358-393`); effects already carry
  `expected_input_revision`. The run loop reloads the authoritative input
  revision before dispatch and before commit (`services/tutor/run_loop.py:255-347`).
- The existing `TutorCapabilityGateway` is an injected port, and the only
  production-safe default is `DefaultDenyCapabilityGateway`
  (`services/tutor/ports.py:71-77`, `247-254`). There is no catalog resolver,
  policy evaluator, grounded implementation, database repository, route, SSE
  producer, worker, or desktop consumer in the Harness seam.
- The provider parser currently accepts up to four Skill references,
  capability requests, and effect proposals, but validates only its generic
  JSON envelope (`services/tutor/provider_gateway.py:90-130`, `188-230`).
  Child 01 must validate these against the catalog and policy gateway after
  parsing; the provider must not become the source of executable names or
  schemas.

## Legacy Surfaces Are Retirement Evidence, Not New-Harness Dependencies

- `app/agents/graphs/router.py:21-65` selects specialist agents from
  `learning_stage`, keyword sets, attempts, profile text, and exercise
  availability. Its tests codify the old stage/handoff behavior. Child 01 must
  not import it into `app/agents/harness/` or `app/services/tutor/`.
- `app/agents/tooling/tools.py:105-201` exposes model-callable stage changes,
  diagnosis writes, code execution, attempt recording, learner-profile writes,
  and a teaching-material search. Several functions accumulate direct
  `AgentSideEffects` or call the runner callback
  (`tools.py:204-399`). They are legacy adapter behavior; none may be exposed
  through the new catalog.
- `app/agents/tooling/tools_web.py:63-127` provides arbitrary URL TOC fetch and
  Exa-backed `web_search`; `docs/setup/development-environment.md:219-230`
  still documents that legacy dynamic-plan-generation path. The target Tutor
  contract explicitly excludes both operations.

## Registry-Only Grounding Evidence

- `app/services/grounding/grounding_sources.py:15-27` defines a
  developer-owned registry record and `GROUNDING_SOURCES`; every source carries
  a language id, trust tier, seed-only policy, allowlisted domains, seed URLs,
  and topic tags. `validate_grounding_source_registry()` validates source ids,
  language coverage, allowlists, and trust policy (`:273-309`).
- `GroundingRetrievalQuery` and `retrieve_grounding_chunks()` are pure,
  deterministic retrieval primitives over already-indexed chunks
  (`grounding_retrieval.py:11-57`). They do not perform network I/O.
- `grounding_index_repository.py:123-205` does provide bounded citation-ready
  results, but it requires a psycopg connection. The Harness boundary must not
  import a database connection or repository directly. Child 01 should define
  an injected `GroundingLookup`/adapter port and use deterministic fake lookup
  tests; durable composition and storage remain Child 02 ownership.
- Existing tests prove source-registry validation, language isolation, bounded
  retrieval ranking, and citation metadata without model inference
  (`tests/test_grounding_sources.py`, `tests/test_grounding_retrieval.py`, and
  `tests/test_grounding_index_repository.py`).

## Applicable Target Constraints

- The parent design requires developer-reviewed, Git-versioned Skill bundles,
  immutable catalog snapshots, MCP-compatible schemas, and policy-filtered
  capability exposure (`.trellis/tasks/07-22-agent-harness-rearchitecture/design.md:231-325`).
- The parent grounding boundary permits only indexed registry sources and
  explicitly prohibits open-web search and arbitrary URL fetch (`design.md:523-529`).
- The feature-disabled Harness rule prohibits legacy Graph/router imports,
  routes, SSE, desktop wiring, database connections/repositories, workers, and
  outboxes in this stage (`.trellis/spec/backend/quality-guidelines.md:1602-1659`).

## Design Implications for Child 01

1. Keep immutable catalog/manifest contracts and schema export in
   `app/agents/harness/`; keep request policy and injected capability
   implementations in `app/services/tutor/`.
2. Use a manifest format that can be validated with current dependencies and
   exported as JSON Schema; do not add a parser dependency merely to accept a
   YAML example from the parent design.
3. Treat a model-provided Skill id/version, capability id, argument field, or
   effect type as untrusted until catalog and policy validation succeeds.
4. Catalog selection must use an exact published semantic version. `current`,
   unversioned ids, file paths, URLs, image names, SQL fragments, user ids,
   shell commands, and arbitrary function names are never executable values.
5. Effects may be catalog-recognized but remain proposal-only/default-denied
   until the owning durable transaction and domain service children are ready.
6. The first enabled read capability should be registry-only grounding through
   an injected lookup. It can return bounded content/citation facts, but cannot
   fetch, crawl, write, execute, or choose a database connection.

## Remaining Product Decision

The parent specifies the full future capability families but does not state
which Child 01 capabilities should be truly executable before the durable
state, sandbox, plan/memory, and activity owners exist. The pending decision
is whether this child enables only `grounding.retrieve` as the initial
read-only implementation and keeps all other future families unexposed or
policy-denied, versus enabling additional capability implementations now.

**Recommendation:** enable only `grounding.retrieve`. It establishes a real
catalog-to-policy-to-gateway path with the smallest authority surface and
leaves plan, memory, activity, runner, and review mutations to their named
children.
