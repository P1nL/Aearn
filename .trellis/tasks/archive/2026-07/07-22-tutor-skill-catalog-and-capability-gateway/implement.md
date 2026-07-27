# Tutor Skill Catalog and Capability Gateway Implementation Plan

## Preconditions Before Start

- The parent remains `planning`; only this child may enter `in_progress`.
- The user confirmed the initial runtime scope: only read-only
  `grounding.retrieve` is executable in Child 01.
- The implementation sub-agent must load the curated backend specs/research,
  this PRD, design, and parent transition contract before editing.
- No code may connect to a database, call HTTP, import legacy Graph/router or
  legacy tools, add an API/SSE/Desktop surface, or flip `TUTOR_HARNESS_ENABLED`.

## Ordered Implementation Checklist

### 1. Catalog Contracts and Published Bundle

- Add the narrow `app/agents/skills/` source package and the initial
  `tutor.registry-grounding/1.0.0` reviewed bundle with manifest, instruction,
  and evaluation files.
- Add frozen Pydantic catalog/manifest/descriptor/snapshot models under
  `app/agents/harness/`.
- Implement SemVer validation, safe bundle-relative path validation,
  resource-ref allowlisting, file/hash verification, deterministic compiler
  order, snapshot digest, exact-version resolution, and MCP-compatible schema
  export.
- Add tests that demonstrate every invalid catalog condition is fail-closed.

**Risk / rollback:** Keep all files unreachable from product composition. If
the catalog contract is wrong, remove only the new internal bundle/compiler;
no state needs migration.

### 2. Integrate Catalog into the Existing Tutor Boundary

- Change `TutorSkillReference`/provider parsing as needed so `current` is no
  longer an executable version choice; retain the provider's strict bounded
  envelope and redaction behavior.
- Add a `TutorDecisionGate` port plus catalog implementation; inject it into
  the finite run loop after provider parsing and before capability/effect work.
- Add an injected run-local `TutorSkillSelectionStore`: a validated selection
  records only the exact id/version/hash for the current run/revision and
  forces a bounded context rebuild before any capability/effect decision.
  Do not make this temporary store durable; Child 02 owns replay persistence.
- Add a catalog context-loader decorator that supplies only policy-eligible
  Skill summaries before selection, the selected reviewed instruction after
  selection, and capability schemas through existing `TutorContextInput`.
- Preserve existing revision reloads, model-only provider behavior, loop
  budgets, default feature-off mode, and fake-friendly constructor patterns.

**Risk / rollback:** Constructor changes can break Child 00 tests. Supply an
explicit deterministic test fake/default that preserves isolation while forcing
real catalog composition to be opt-in and policy-bound.

### 3. Policy Resolver and Capability Gateway

- Add frozen `CapabilityPolicyContext`, `CapabilityPolicyResolver`, and
  deterministic fakes/default-deny resolver under `app/services/tutor/`.
- Implement a catalog-aware gateway that parses only descriptor-declared fields,
  checks user/run/origin/revision/catalog/consent/runtime/budget scope, and
  emits typed denial/unavailable results without fallback.
- Implement catalog validation for effect types while retaining default-deny
  effect commit. The initial published Skill declares no allowed effect.
- Add negative tests for unknown Skills, unversioned refs, unknown capability
  ids, field extras, URLs/paths/SQL/images/user IDs/commands, policy denial,
  unavailable runtime, and effect proposal non-commit.

**Risk / rollback:** Do not convert generic provider validation into an
unbounded function registry. All executor selection remains descriptor-first
and the policy resolver has no model-controlled allowlist.

### 4. Registry-Only Grounding Implementation

- Add `GroundingLookup`/query/result contracts and deterministic in-memory
  lookup that uses existing pure grounding retrieval with supplied chunks.
- Implement `grounding.retrieve@1.0.0` dispatch from the catalog gateway.
- Derive source scope exclusively from `grounding_sources.py`, cap `top_k` and
  snippets/citations, and reject URL or arbitrary-source fields before lookup.
- Test valid bounded retrieval, unsupported language, empty lookup, source
  mismatch filtering, and no lookup call for a rejected request.

**Risk / rollback:** Do not import the persisted grounding repository or DB
connection into Harness code. Production composition is intentionally deferred;
test adapters prove only the contract.

### 5. Documentation and Full Focused Check

- Update `docs/architecture/tutor-harness-transition.md` with Child 01 catalog,
  exact-version, policy, effect proposal, and registry-only grounding target
  boundaries plus explicit non-changes.
- Update the Harness scenario in
  `.trellis/spec/backend/quality-guidelines.md` only if implementation reveals
  a reusable rule not already captured by Child 00's scenario.
- Search the changed code for forbidden imports and identifiers; inspect the
  complete diff and run `git diff --check`.

## Required Validation

Run focused tests first, then regression/final checks from
`E:\codee\Aearn\aearn\services\api` or the repository root as shown:

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_skill_catalog.py tests/test_tutor_capability_gateway.py tests/test_tutor_grounding_policy.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_context_builder.py tests/test_tutor_provider_gateway.py tests/test_tutor_run_loop.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\07-22-tutor-skill-catalog-and-capability-gateway
git diff --check
```

Known environment fallback: if direct `uv --directory .\aearn\services\api run
mypy app` reports `uv trampoline failed to canonicalize script path`, use the
listed `python -m mypy app --no-incremental` command. Do not change project
tooling merely to work around that local trampoline behavior.

## Review Gates

Before dispatching implementation, confirm all source changes stay inside the
child's catalog/gateway/grounding/test/transition-contract scope and that the
feature flag is not read by legacy product code.

Before committing, run the full Child 01 validation list, inspect all affected
backend specs' Quality Check guidance, and confirm no previously dirty user
file is staged. Work commit(s) must precede archive/journal bookkeeping; do
not push without a separate user request.

## Rollback Summary

- Pre-integration: delete/revert the isolated catalog/gateway registration and
  published bundle; legacy product flow continues untouched.
- No data rollback exists because this child creates no tables, migrations,
  outbox records, or domain mutations.
- Do not leave an unsafe broad fallback enabled as a rollback mechanism; return
  to default-deny instead.
