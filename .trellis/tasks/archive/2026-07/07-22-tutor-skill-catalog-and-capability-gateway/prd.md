# Tutor Skill Catalog and Capability Gateway

## Goal

Deliver a developer-owned, Git-versioned Skill catalog and a policy-filtered,
typed capability gateway for the feature-disabled Tutor Harness. The resulting
runtime can offer the model only reviewed Skill summaries and capability
schemas, validate every requested identifier and argument against an immutable
catalog/policy snapshot, and execute exactly one registry-only read capability
without any direct durable domain write.

The user value is a safe first vertical slice of dynamic Tutor capability
selection: Tutor can retrieve bounded, cited documentation facts from the
approved index, but cannot invoke an arbitrary function, URL, path, SQL,
image, user id, shell command, database connection, runner, or legacy tool.

## Dependencies and Authority

- **Upstream contract:** Child 00 freezes the bounded provider envelope,
  `TutorContextInput.capability_schemas`, revision-aware loop, effect proposal,
  and default-deny port seams. Child 01 extends only those internal seams.
- **Target authority:** the parent Harness `prd.md`, `design.md`, and
  `implement.md`, plus `docs/architecture/tutor-harness-transition.md`.
  Legacy Graph/router/tooling code establishes retirement evidence only.
- **Downstream authority:** Child 02 owns durable catalog/run/effect storage
  and transactional effect commit; Child 03 owns executor isolation; Child 04
  owns proactive scheduling; Child 05 owns plan/memory/activity semantics;
  Child 06 owns public API/SSE/Desktop exposure; Child 07/08 own cutover,
  legacy retirement, and final documentation consolidation.
- **Documentation delta:** this child updates only the Harness transition
  contract with catalog/policy/effect/grounding target rules. It does not
  rewrite public API, schema, Desktop, or legacy Graph contracts.

## Confirmed Repository Facts

1. `app/agents/harness/contracts.py:167-206` reserves a bounded
   `capability_schemas` context section, and
   `app/agents/harness/context_builder.py:108-190` selects/redacts it within
   the fixed context budget.
2. `TutorSkillReference` currently accepts an opaque id and defaults its
   version to `"current"` (`contracts.py:338-345`). The generic provider parser
   validates JSON shape but not catalog membership, exact Skill version,
   capability schema, or effect type (`services/tutor/provider_gateway.py:90-230`).
3. `TutorCapabilityGateway` is an injected port with
   `DefaultDenyCapabilityGateway` as the only safe default
   (`services/tutor/ports.py:71-77`, `247-254`). The run loop reloads the
   current input revision before capability dispatch and effect commit
   (`services/tutor/run_loop.py:255-347`).
4. Legacy routing is stage/keyword/handoff based
   (`app/agents/graphs/router.py:21-102`). Legacy teaching tools expose stage
   updates, diagnosis/profile accumulation, runner callbacks, attempt records,
   and a direct DB-backed material search
   (`app/agents/tooling/tools.py:105-399`). None may be imported or registered
   by the new Harness.
5. Legacy `tools_web.py` exposes arbitrary URL fetch and Exa-backed search;
   these are explicitly excluded from the Tutor target.
6. `grounding_sources.py` is a developer-governed language-aware source
   registry with allowlists and trust validation. Pure retrieval is available
   over pre-indexed chunks, while the persisted repository requires a psycopg
   connection and must not be imported by Harness modules.
7. The current Trellis configuration uses Codex auto-dispatch. This complex
   child must have `prd.md`, `design.md`, `implement.md`, and real context
   entries in both JSONL manifests before it can start.

Detailed anchors and implementation implications are recorded in
`research/current-skill-capability-baseline.md`.

## Requirements

### R1 — Published, Immutable Skill Catalog

- Add a developer-owned source root at
  `aearn/services/api/app/agents/skills/<skill_id>/<semantic_version>/`.
  A published bundle contains a manifest, instruction file, and evaluation
  suite under the same reviewed Git tree.
- Validate a stable Skill id, exact SemVer 2 version, owner/kind/summary,
  instruction/evaluation files, content hashes, declared resource references,
  required capability ids, allowed effect types, policy tags, and input/output
  contract versions.
- Compile valid bundles into a deterministic immutable catalog snapshot with a
  content digest. Reject duplicate id/version pairs, invalid/unpinned versions,
  missing files/evaluations, unknown capabilities/effects, untrusted resource
  refs, duplicate schema fields, path traversal, and manifest values that act
  as URLs, paths, image names, SQL, shell commands, or model-provided targets.
- Export capability schemas in MCP-compatible JSON Schema shape while retaining
  typed in-process Python calls. No MCP transport/server is added.

### R2 — Catalog-Constrained Tutor Decisions

- Replace the operational meaning of `TutorSkillReference(version="current")`
  with exact published-version resolution. `current`, empty/wildcard versions,
  and unknown id/version pairs are policy denials.
- Supply only the policy-eligible Skill summaries and capability JSON schemas
  to the existing bounded context builder.
- Add a catalog decision gate after provider-envelope parsing and before any
  capability/effect boundary. It validates selected Skills, capability ids,
  descriptor argument fields, and effect types against the effective catalog
  and policy context.
- Treat new Skill selection as a bounded no-effect step: persist it only in an
  injected run-local `TutorSkillSelectionStore`, rebuild context with the exact
  reviewed instruction on the next loop iteration, and prohibit capability/
  effect work in the same selection decision. Child 02 replaces that temporary
  store with durable replayable selection evidence.

### R3 — Capability Policy and Effect Boundary

- Define immutable capability descriptors with a stable id/version, mode,
  typed argument/result schema, policy tags, and allowed effect types.
- Resolve policy from the current run/user scope, origin, input revision,
  consent/runtime facts, catalog digest, and remaining budget. The default
  resolver is deny-by-default.
- Catalog-aware dispatch rejects unknown, malformed, policy-ineligible, or
  forbidden requests without fallback. Model values never select a user,
  function, URL, path, SQL fragment, image, shell command, or database target.
- Effects remain bounded/redacted `TutorEffectProposal` values with a declared
  catalog type and `expected_input_revision`; no repository, runner, worker,
  database, or product-domain mutation is reached in this child.

### R4 — Registry-Only Grounding

- Register exactly one executable capability: `grounding.retrieve`.
- It accepts only declared bounded language/query/topic/count fields, resolves
  the language and source scope through the developer registry, and returns
  bounded snippets plus explicit citation/source facts.
- Its implementation consumes an injected `GroundingLookup` adapter. The
  Harness imports no DB connection/repository, performs no HTTP request or
  fetch, and has no crawler/shell/runner/write path.

### R5 — Compatibility Boundary

- Keep `TUTOR_HARNESS_ENABLED=false`; do not add routes, SSE frames, Desktop
  code, database migrations/repositories, worker/outbox wiring, legacy Graph
  removal, or legacy-tool replacement.
- Legacy Graph/router/tooling modules remain available to legacy adapters only
  and are not exposed alongside the new catalog.

## Key Decision

**Confirmed on July 27, 2026:** Child 01 registers only the read-only
`grounding.retrieve` capability as truly executable. Plan/review/note/runner/
memory/activity families remain unexposed to the model and default-denied until
their owning children establish durable transactions, sandbox isolation, user
controls, and activity semantics. This minimizes authority surface while still
proving catalog → policy → gateway → bounded citation flow.

## Acceptance Criteria

- [ ] A catalog compiler accepts only complete, exact-versioned, Git-owned
  Skill bundles and emits the same immutable snapshot/digest for the same
  source tree.
- [ ] Invalid SemVer, `current`/wildcard versions, duplicate id/version,
  missing instruction/evaluation files, unknown capability/effect ids,
  untrusted resource refs, unsafe paths, and malformed schemas are rejected.
- [ ] The context path exposes only policy-eligible Skill summaries and
  `grounding.retrieve` JSON schema; it never exposes legacy Graph tools or an
  arbitrary function registry.
- [ ] A newly selected Skill is exact-version validated, triggers one bounded
  context rebuild with its reviewed instruction, and cannot dispatch a
  capability/effect in the same decision; no selection is durable in Child 01.
- [ ] An unknown/unversioned Skill, capability id, effect type, URL, path,
  image, SQL fragment, shell command, or user id cannot become executable and
  returns a typed denial/unavailable outcome.
- [ ] `grounding.retrieve` accepts only the descriptor-declared bounded fields,
  rejects URL/arbitrary-source inputs, uses an injected registry-index lookup,
  and returns bounded registry-backed snippets/citations without network or DB
  access.
- [ ] Every effect proposal stays bounded/redacted, carries
  `expected_input_revision`, has a catalog-declared type, and reaches no
  committer/domain mutation path.
- [ ] Focused catalog/gateway/grounding tests plus existing Child 00 Harness
  tests pass; `TUTOR_HARNESS_ENABLED` remains false and no public product
  surface changes.

## In Scope

- Internal Skill manifest/catalog contracts and initial published bundle;
  snapshot compiler/validator; MCP-compatible schema export; catalog context
  decorator and decision gate; policy resolver/fakes; catalog-aware capability
  gateway; injected registry-only grounding lookup; focused tests; transition
  contract update.

## Out of Scope

- Durable catalog/run/effect persistence, database migrations/repositories,
  effect commits, plan/memory/activity behavior, executor/sandbox,
  proactive scheduler, public API/SSE/Desktop rollout, provider routing,
  legacy Graph/tool removal, cutover, open-web search, arbitrary document
  fetch, and any direct domain-state mutation.

## Risks and Deferred Items

- The catalog snapshot is in-memory/immutable only in this child. Child 02
  persists the effective snapshot/digest for replay and transactional effects.
- The injected grounding lookup has deterministic fakes and a pure in-memory
  implementation; a production persistence adapter remains outside Harness
  imports and is wired only by its owning integration work.
- Future capability families must be added by their authority-owning child,
  together with descriptor, policy, transaction, and user-visible outcome
  tests. They must not be enabled merely by adding a manifest.
