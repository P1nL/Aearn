# Tutor Harness Transition Contract

## Status and Authority

This Child 00 contract creates only a feature-disabled, in-process Tutor
Harness seam. It adds no learner-facing API, SSE stream, desktop entry point,
database table, migration, worker, or outbox.

| Authority | Meaning |
| --- | --- |
| **Legacy baseline** | Current routes, Graph routing, `learning_stage`, Graph checkpoints, SSE vocabulary, persistence, and desktop flows remain the compatibility baseline. |
| **Target contract** | The immutable Harness contracts, bounded context builder, primary-only provider gateway, finite loop, input revision protocol, and typed compaction request introduced by Child 00. |
| **Adapter window** | Until Child 06, the Harness is unreachable from product traffic. Existing API/SSE/Desktop flows preserve legacy contracts while future adapters translate at the boundary. |
| **Retired** | Nothing is retired by Child 00. Later cutover work owns explicit retirement and migration decisions. |

Current code/tests establish legacy facts. This document only defines the new
internal target contract.

## Legacy Baseline: Explicit Non-Changes

- `LANGGRAPH_ENABLED` remains the legacy Graph flag and is not reused.
- Legacy `learning_stage` routing, specialist handoffs, Graph checkpoints,
  routes, SSE events, and desktop flows continue to own product traffic.
- Existing provider configuration and selected-provider retry remain owned by
  `OpenAICompatibleClient`.
- Existing persistence remains the legacy schema/repository boundary; Child 00
  stores no Tutor run, event, checkpoint, or outbox data.

`TUTOR_HARNESS_ENABLED=false` is a separate future-integration seam. No
current product route, Graph path, SSE producer, or UI reads it in Child 00.

## Target Run and Input Contract

`TutorRunSnapshot` is immutable and contains opaque run/conversation/user ids,
a monotonic `input_revision`, and fixed policy/lease/counter data.
`TutorCheckpoint` retains only redacted source/budget metadata, while terminal
results expose only learner-safe public text and stable diagnostic codes. None
of those contracts contains raw provider payloads, prompts, full history,
hidden tests, reference answers, submitted code, or secrets.

```text
queued -> leased -> running
running -> waiting_for_input | waiting_for_capability | awaiting_effect_commit
running -> completed | model_unavailable | blocked_policy | budget_exhausted | cancelled | failed
```

Each accepted `TutorInputEvent` has an opaque message id and monotonic
revision. `TutorRunStore.current_input_revision(run_id)` is authoritative. The
loop reloads it before every model call, before capability dispatch, after a
capability result, and before effect commit. A different expected revision makes
an effect `stale_rejected`; its committer is never called.

The fixed policy bounds iterations, model/capability/effect calls, deadline,
and context tokens. Child 00 supplies ports plus deterministic fakes/default
denials only; later persistence makes the same protocol durable.

## Target Context, Checkpoint, and Compaction Contract

`TutorContextBuilder` accepts only pre-scoped facts and selects them in this
stable order: system/selected-Skill/policy descriptors; active plan revision;
review/FSRS snapshot; recent sanitized messages; working summary; learner-
visible memory; activity/execution facts; allowed capability schemas.

Each section has explicit item/token budgets. The default estimator is
deterministic and conservative (UTF-8 byte count). Sanitization/runtime
redaction happens before selection. Checkpoints retain only section counts,
source ids/hashes, and consumed-budget metadata—never composed prompts or raw
source content.

High-water output is an idempotent typed compaction *request*, not a Curator
call. It is emitted only on a terminal state, safe checkpoint, or configured
context high-water condition, never per streamed token.

## Target Provider and Decision Contract

`PrimaryTutorProviderGateway` is the only Child 00 model boundary. It wraps
the configured `OpenAICompatibleClient`, retaining the selected provider/model
and bounded retry behavior for DeepSeek Chat Completions and legacy
OpenAI-compatible Responses. It never changes settings or attempts a cross-
provider/model fallback.

The strict Harness decision envelope permits bounded learner-safe public text,
Skill refs, capability requests, effect proposals, optional safe-checkpoint
reason, and terminal intent. It rejects unknown/malformed/duplicate fields,
reasoning/diagnostic fields, and unsafe text. Generic teaching-output
guardrails remain the text safety boundary.

Configuration, selected-provider call, response/schema, or guardrail failures
become redacted `MODEL_UNAVAILABLE`; raw provider errors, prompts, keys, and
payloads never cross this contract.

## Child 01 Target: Skill Catalog, Policy, and Registry Grounding

Child 01 adds an isolated internal catalog/gateway composition only. It does
not make the Harness reachable from product traffic or change the default
`TUTOR_HARNESS_ENABLED=false` posture.

### Published Skill Catalog

- Reviewed bundles live under
  `aearn/services/api/app/agents/skills/<skill_id>/<semantic_version>/` and
  contain `manifest.json`, a UTF-8 reviewed instruction, and a non-empty JSON
  evaluation suite in the same Git-owned tree.
- The compiler accepts exact SemVer 2 references only, verifies bundle-relative
  resource names and content hashes, checks reviewed registry references,
  declared descriptors/effects, and compiles the complete set into an ordered,
  immutable snapshot with a canonical SHA-256 digest. An invalid bundle rejects
  the whole snapshot; there is no partial or `current` fallback.
- `tutor.registry-grounding@1.0.0` is the initial published Skill. It requires
  only `grounding.retrieve`, declares the reviewed
  `registry:grounding_sources` resource, and declares no allowed effect type.
  Skills remain instruction/resource data, not model-authored or executable
  code.

### Catalog Context and Decision Boundary

- A catalog context loader decorates the existing bounded context input. Before
  selection it supplies only policy-eligible exact-version Skill summaries and
  MCP-compatible JSON schemas. After a validated selection it supplies that
  exact reviewed instruction plus id/version/hash facts. It never exposes a
  legacy tool registry or arbitrary catalog file body.
- Selection is stored only in an injected run-local store keyed by run id and
  input revision. A newly selected Skill causes a context rebuild and cannot
  dispatch a capability or propose an effect in the same model decision. Child
  02 owns durable selected-version/hash evidence for replay and restart.
- The catalog decision gate runs after strict provider-envelope parsing and
  before checkpoint/capability/effect work. It rejects unversioned, unknown,
  policy-ineligible, malformed, or mixed selection/action decisions without
  fallback. The default uncomposed gate denies model-selected Skills,
  capabilities, and effects.

### Capability Policy and Effect Boundary

- `CapabilityPolicyContext` binds run/user scope, origin, current input
  revision, catalog digest, consent, runtime availability, remaining budget,
  policy tags, eligible exact Skill references, and registered source scope.
  The default resolver publishes no Skill, capability, effect, or source.
- Only descriptor-declared fields are decoded from the bounded provider
  envelope. Unknown field names, URLs, paths, images, SQL fragments, shell
  commands, arbitrary user identifiers, and function-like targets are denied
  before a lookup is attempted.
- Effects remain typed `TutorEffectProposal` values carrying
  `expected_input_revision`. The initial catalog has no effect descriptor or
  allowed effect type, so effect proposals are denied before the default-deny
  committer and no domain mutation path is reached.

### Registry-Only Grounding

- The sole executable Child 01 capability is `grounding.retrieve@1.0.0`. It
  accepts only bounded language/query/topic/count fields, derives eligible
  source ids from `grounding_sources.py`, and returns capped snippets with
  citation/source metadata.
- The gateway receives an injected `GroundingLookup` adapter. Its in-memory
  implementation reuses pure retrieval over supplied indexed chunks; the
  catalog, Harness, and gateway do not directly import a database connection,
  persisted index repository, HTTP fetcher, crawler, shell, runner, or legacy
  teaching tool.
- A future persisted lookup adapter and any durable invocation/effect evidence
  remain outside this child. No route, SSE frame, Desktop component, migration,
  repository, worker, outbox, provider-routing change, or legacy Graph/tool
  removal is authorized here.

## Target Loop and Future Ownership

The finite loop leases, loads, checks fixed budgets/cancellation, builds bounded
context, asks the primary provider for one decision, and rechecks revision and
policy before every unsafe boundary. Default capability/effect ports deny or
report unavailable; they execute no tools and write no product state.

Safe checkpoints and compaction candidates are emitted through injected ports
only for terminal, safe-checkpoint, or high-water reasons. Child 00 does not
create a Curator, worker, transactional outbox, background loop, or direct
mutation of memory, plans, reviews, FSRS, attempts, messages, or activity.

| Future child | Ownership after Child 00 |
| --- | --- |
| Child 01 | Skill catalog, capability policy, registered capability implementations. |
| Child 02 | Target SQL repos, durable events/checkpoints, transactional commit, compaction outbox. |
| Child 06 | Tutor API/SSE replay, feature exposure, desktop adaptation. |
| Child 07/08 | Cutover, legacy retirement, and source-of-truth reconciliation. |

This document does not authorize product traffic to enter the Harness.
