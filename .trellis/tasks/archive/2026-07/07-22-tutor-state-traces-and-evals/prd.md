# Tutor State, Traces, and Evaluation Foundation

## Goal

Deliver the internal durable-state foundation for the feature-disabled Tutor
Harness: target-only PostgreSQL storage, transactionally ordered run events,
metadata-only checkpoints and diagnostics, revision/lease compare-and-set
protection, exact catalog-selection replay evidence, a redacted compaction
outbox/proposal envelope, and deterministic fake-only Harness evaluations.

The learner value enabled by this foundation is reliable continuation and later
reconnectable Tutor work: newly accepted messages cannot be lost or applied to
a stale run, unsafe effects cannot be committed twice, and later API/Desktop
work can replay a safe ordered event suffix without reconstructing a full raw
conversation or exposing protected diagnostic material.

## Dependencies and Authority

- **Upstream contracts:** Child 00 owns the finite run-loop, bounded context,
  metadata-only checkpoint, lease, input-revision, provider-outcome, and
  compaction-request contracts. Child 01 owns the reviewed catalog, exact
  Skill selection, capability policy, and registry-only capability boundary.
  This child makes those contracts durable without widening their authority.
- **Target authority:** the approved parent Harness planning artifacts and
  `docs/architecture/tutor-harness-transition.md`; the latter assigns Child 02
  target SQL repositories, durable events/checkpoints, transactional commit,
  and the compaction outbox. Current implementation files and legacy docs are
  evidence of current behavior, not target contracts.
- **Downstream boundary:** Child 04 owns queue leasing/retry policy and worker
  execution; Child 05 owns Curator execution, proposal semantics, and domain
  projections; Child 06 owns public API, `Last-Event-ID`, SSE delivery, and
  Desktop deduplication. This child exposes no route, SSE frame, worker, or UI.
- **Documentation delta:** update only the Harness transition contract with
  additive schema, lifecycle transaction, internal replay, redaction, curation
  envelope, and evaluation boundaries. Do not rewrite legacy API/SSE/product
  documentation before the owning integration work proves the new behavior.

## Confirmed Repository Facts

1. The API currently applies one repeatable `schema.sql` through
   `bootstrap_database()` and commits once; there is no checked-in Alembic,
   migration runner, or schema-version table. `schema.sql` already relies on
   idempotent `CREATE`/`ALTER` forms, and `test_db_bootstrap.py` runs bootstrap
   twice. See `research/persistence-and-schema-baseline.md`.
2. `TutorRunStore` is only an injected port and `InMemoryTutorRunStore` is a
   non-durable fake. Its `accept_input()` helper is not part of the formal
   protocol. The loop currently calls checkpoint persistence, compaction
   publishing, and terminal result recording independently, so those calls do
   not form a transactional outbox. See the persistence research report and
   `aearn/services/api/app/services/tutor/{ports,run_loop}.py`.
3. Child 01's catalog snapshot is deterministic and digest-backed, while exact
   selected Skill version/manifest/instruction hashes are only stored in the
   run-local `InMemoryTutorSkillSelectionStore`. Durable selection evidence is
   expressly assigned to this child by the transition contract.
4. Current SSE `evt_*` identifiers are request-local writer counters; no
   durable event sequence, replay cursor, `Last-Event-ID`, or client-side
   deduplication exists. A durable internal sequence must therefore be added
   before Child 06 exposes reconnection behavior. See
   `research/trace-redaction-replay-eval-baseline.md`.
5. Existing Harness context/checkpoint redaction and runtime redaction helpers
   establish metadata-only diagnostic behavior, but no persistent trace,
   export, curation outbox, proposal, or Harness evaluation runner exists.
## Requirements

### R1 — Additive, Target-Only Persistence Schema

- Append a clearly marked, idempotent Tutor Harness SQL delta to the existing
  bootstrap schema; do not introduce Alembic or a second schema application
  mechanism in this child.
- Add only namespaced `tutor_*` tables, indexes, constraints, and update
  triggers required for conversations/messages, catalog snapshots, runs,
  selected Skills, input events, checkpoints, ordered run events, capability
  invocations, effect records, redacted traces, curation outbox records, and
  curation proposal envelopes.
- Use PostgreSQL UUID identifiers, `timestamptz`, scoped foreign keys, explicit
  JSONB names, natural idempotency keys, and unique constraints for replay and
  per-run ordering. Preserve all legacy learner tables and records unchanged.
- Prove that `bootstrap_database()` can apply the complete schema repeatedly.

### R2 — Transactional Lifecycle, Input, Lease, and Effect Boundaries

- Define a durable Tutor persistence/repository boundary rather than extending
  a fake-only helper. It owns user/run scope checks, input idempotency request
  hashes, revision allocation, lease generation/expiry checks, terminal-state
  uniqueness, event-sequence allocation, and transaction commit/rollback.
- Accept a learner input in one transaction: validate user/run scope, replay a
  same request key/body hash, reject a key/body mismatch, persist the raw
  learner message only in the target conversation/message store, allocate the
  next input revision, append an `input_accepted` safe event, and return the
  authoritative snapshot.
- Make a checkpoint or terminal lifecycle result atomic with its safe event,
  redacted trace, and deduplicated compaction-outbox request. A forced failure
  must leave no visible partial event, checkpoint, result, or outbox row.
- Make effect claiming/commit conditional on the active lease owner/generation
  and expected current input revision. A stale proposal persists only a safe
  `stale_rejected` result/event and never calls a domain committer. No Child 02
  code authorizes a new domain effect type or direct plan/review/FSRS/memory
  mutation.

### R3 — Durable Catalog and Replay Evidence

- Persist the effective immutable catalog digest and safe manifest/hash facts,
  then record each exact selected Skill id/version plus manifest/instruction/
  evaluation hashes against a run/input revision. `current`, ranges, and
  mutable aliases are never persisted as an executable selection.
- Persist capability invocations and effects as structured, bounded records
  with catalog/policy/revision/lease evidence, safe status codes and hashes;
  never serialize raw provider requests, arbitrary targets, or unbounded
  capability results.
- Allocate a monotonic, gap-free, run-local integer `event_sequence` in the
  owning transaction. Repository replay returns only events strictly after a
  supplied cursor in ascending sequence order and never treats request-local
  SSE IDs as a durable cursor.

### R4 — Diagnostics, Trace, and Export Redaction

- Separate canonical learner message storage from diagnostics. Raw learner
  text may exist only in `tutor_messages`; trace, event, checkpoint, outbox,
  proposal, and export paths use allowlisted safe projections and hashes.
- Apply redaction before each diagnostics/outbox/proposal write and again
  during export. Reject or omit raw prompts/history, provider payloads/errors
  and reasoning, keys/tokens, hidden tests, solution references, full code,
  stack traces, host/container paths, shell/SQL targets, and credential-bearing
  URLs, including nested/value-based variants.
- Reuse the existing redaction/checkpoint contracts where possible; do not copy
  disconnected deny lists or invent an alternate raw checkpoint shape.

### R5 — Curation Persistence Envelope, Not a Curator

- Persist only a redacted, ordered, deduplicated compaction request and typed
  proposal envelope: closed source range, source IDs/hashes, policy and memory
  setting versions, retention/staleness metadata, priority, idempotency, and
  safe pending/no-action/stale/failed state.
- Allow at most one proposal identity for an outbox identity. The repository
  may validate structural bounds/redaction and idempotency, but does not call a
  model, lease a queue, choose retry policy, evaluate proposal meaning, or
  project into plan/memory/activity/domain tables.

### R6 — Deterministic Evaluation Foundation

- Add source-controlled `tests/fixtures/tutor_evals/` fixtures and a fake-only
  eval runner based on existing deterministic clocks, providers, gateways,
  stores, and effect committers. Ordinary evals may not require live models,
  network, worker, or wall-clock time.
- Cover policy denial, strict provider-schema rejection, finite loop budgets,
  revision/CAS races, primary-provider-only `MODEL_UNAVAILABLE`, exact catalog
  identity, transactional replay/outbox behavior, and protected-data leakage.

### R7 — Compatibility and Feature-Off Safety

- Keep `TUTOR_HARNESS_ENABLED=false`; do not alter legacy Graph/router/tool
  composition, public routes, current SSE encoder, Desktop components, worker
  registration, legacy learner data, or model-provider routing.
- Establish internal repository contracts that Child 06 can later adapt to
  `Last-Event-ID` and delivery acknowledgements without changing an existing
  public stream in this child.
## Key Decisions

1. **Schema delivery:** follow the verified current convention: an additive,
   idempotent Tutor-only delta in `app/db/schema.sql`, applied by existing
   `bootstrap_database()`. Introducing a migration framework is intentionally
   deferred because it would be a second persistence delivery mechanism rather
   than the minimum safe implementation for this child.
2. **Lifecycle atomicity:** add an explicit transaction-level lifecycle
   persistence boundary. It must write the state transition/checkpoint/result,
   safe event, redacted trace, and compaction outbox together; composing the
   current independent store and publisher calls is not sufficient.
3. **Replay scope:** `event_sequence` is an internal repository cursor. Child
   02 proves ordered suffix reads; Child 06 later maps it to transport-level
   `Last-Event-ID`, SSE framing, reconnect, and Desktop deduplication.
4. **Effect authority:** the repository provides lease/revision/idempotency CAS
   and safe stale evidence. Actual domain-effect semantics remain default-deny
   until their owning child can commit through the normal domain repository
   transaction.
5. **Curation ownership:** Child 02 stores redacted outbox/proposal envelopes
   only; Child 04 owns queue/lease/retry execution and Child 05 owns Curator
   generation, semantic validation, and projections.
6. **Privacy posture:** diagnostics are never a backup conversation store. A
   dual write/export projection is mandatory even for data that initially looks
   structured or safe.

## Acceptance Criteria

- [ ] Applying `bootstrap_database()` twice creates the target `tutor_*` table
  family, indexes, constraints, and triggers without changing or deleting
  legacy learner data.
- [ ] A scoped input transaction returns the first authoritative acceptance for
  the same idempotency key/body hash, rejects a mismatched body hash, advances
  exactly one revision, stores raw learner text only in `tutor_messages`, and
  creates exactly one ordered safe event.
- [ ] Competing lease holders or terminal writers cannot produce two committed
  terminal outcomes or conflicting event sequences; a failed lifecycle
  transaction exposes no partial checkpoint/result/event/trace/outbox state.
- [ ] Replay after cursor `K` returns exactly `K+1..N` in sequence order and
  idempotent event append returns the original event rather than a duplicate.
  No public SSE or `Last-Event-ID` endpoint is introduced here.
- [ ] Catalog snapshots and selected Skills persist only exact digest/version/
  hash evidence; an unresolved `current` alias cannot be used for recovery or
  replay.
- [ ] An effect with a stale revision or invalid lease is durably marked
  `stale_rejected`/unavailable without invoking a domain committer; duplicate
  effect identity cannot commit twice.
- [ ] Trace, event, checkpoint, capability, outbox, proposal, and export tests
  prove that the protected-field/value corpus cannot reveal prompts, provider
  data, hidden tests, solution references, secrets, full code, paths, shell/
  SQL targets, credential URLs, or stack traces.
- [ ] Duplicate curation-outbox/proposal operations produce one durable identity
  and retain closed source-range/version/retention facts; no worker, Curator,
  memory, plan, review, FSRS, attempt, activity, or chat mutation occurs.
- [ ] Fake-only evaluation fixtures deterministically cover denial, strict
  schema rejection, bounded loop, revision conflict, primary-only model
  failure, and redaction leakage; focused repository/eval tests, bootstrap
  tests, Ruff, Mypy, task-manifest validation, and `git diff --check` pass.
- [ ] The Harness remains feature-disabled and the changes are unreachable from
  legacy public product composition.

## In Scope

Target-only SQL schema and repositories; run/input/lease/checkpoint/result/
event/capability/effect/catalog persistence; transactional lifecycle methods;
redacted diagnostic/export projection; outbox/proposal storage envelope;
deterministic fixtures and focused tests; the narrow transition-contract delta.

## Out of Scope

Alembic or a global migration-framework introduction; public routes or SSE;
`Last-Event-ID` handling; Desktop changes; worker/queue leasing and retry
execution; Curator model calls or semantic proposal/domain projection; plan,
memory, activity, review/FSRS, attempt, or runner behavior; sandbox work;
legacy-data migration/deletion; provider fallback/routing; legacy Graph/tool
retirement; deployment or feature-flag activation.

## Risks and Deferred Items

- PostgreSQL bootstrap tests require the local database prerequisite and must
  run sequentially with other bootstrap-heavy suites; absence of PostgreSQL is
  a verification blocker, not a reason to substitute a fake schema test.
- Future domain effects must implement the same-transaction commit contract;
  this child does not solve an external/non-transactional side-effect problem
  by pretending an insert alone is exactly-once business execution.
- Repository replay is durable evidence, not delivered UX until Child 06
  consumes it; worker states are storage-only until Child 04/05 own them.
- Schema additions are forward-compatible and unused while feature-off.
  Rollback removes the composition/repository use; it does not drop stateful
  production tables or touch legacy data.