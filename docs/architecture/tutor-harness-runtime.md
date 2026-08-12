# Tutor Harness Runtime Architecture

**Status:** Current runtime contract as of 2026-08-11.
**Authority:** Current route registration, `aearn/services/api/app`,
`aearn/apps/desktop`, `aearn/services/worker`, `services/learning/`,
`schema.sql`, and their tests.
The transition document is historical migration evidence; it is not the normal
runtime specification.

## 1. Product boundary

Aearn is a local, controlled Tutor workspace. A learner enters through a local
identity and a server-authoritative cutover receipt; the active runtime is not
a compatibility bridge to the former product.

```text
local identity
  -> GET /api/harness/cutover
  -> verified receipt
  -> LearningTrack routes and Tutor conversation/activity/inbox/memory/preferences
```

A missing, pending, blocked, failed, or malformed cutover state denies both the
Tutor runtime and the removed legacy runtime. A client cannot choose deletion
scope, bypass the receipt, restore a saved legacy plan id, or recreate deleted
legacy learner history.

## 2. Runtime composition

| Layer | Owner | Contract |
| --- | --- | --- |
| Public adapter | `routes/tutor.py`, `services/tutor/public_api.py` | Validates user scope and idempotency, exposes learner-safe projections, and never performs Graph/router compatibility work. |
| Learning domain | `routes/learning_tracks.py`, `routes/exercise_gates.py`, `services/learning/` | Owns track-scoped plans, progress/mastery, immutable LessonDocument/source snapshots/assignments, exercise Gate/Attempt/module-diagnostic authority, execution-tier projection, immutable scope snapshots, and a read-only Tutor context adapter; Review remains separate. |
| Interactive dispatch | `services/tutor/interactive.py` | Starts an already accepted input only after its transaction commits, composes a bounded loop, and keeps provider failures out of the accepted-input response. |
| Harness | `agents/harness/`, `services/tutor/run_loop.py` | Bounded run loop, lease ownership, input-revision reload, exact Skill selection, capability/effect gate, checkpoint lifecycle, and typed terminal outcome. |
| Durable state | `services/tutor/persistence.py`, `learner_state.py`, `proactive_repository.py` | PostgreSQL owns user/run/conversation scope, ordered events, idempotency, CAS effects, redacted projections, plan/memory/activity state, and queue leases. |
| Worker | `services/worker/aearn_worker/worker_app.py` | Thin Celery wrappers for `health.ping`, `tutor.proactive.scan_due_signals`, `tutor.proactive.drain_candidates`, and `tutor.curation.drain`. |
| Desktop | `apps/desktop/src/` | Bootstraps `loading -> welcome -> cutover -> tutor`; it presents server decisions and cannot override them. |

## 3. Interactive Tutor conversation and finite TurnRun

A learner-visible `TutorConversation` is long-lived history/context scope; an
ordinary learner message is a **fresh, finite** interactive `TurnRun`:

```text
local draft
  -> POST /conversations/first-turn
  -> conversation + first TurnRun + learner input + public process (one transaction)

existing conversation + ordinary learner message
  -> POST /conversations/{conversation_id}/inputs
  -> supersede old foreground run + fresh TurnRun

explicit server-authorized continuation only
  -> POST /runs/{run_id}/inputs
  -> same waiting run receives the next revision
```

1. Selecting “新对话” creates only local Desktop draft state. The first nonblank
   submission calls `POST /api/tutor/conversations/first-turn`; it atomically
   creates the learner-visible conversation, fresh run, learner message/input
   event, and `input_received` public-process projection. API idempotency owns
   replay; a rollback cannot leave an empty conversation or duplicate dispatch.
2. `POST /api/tutor/conversations/{conversation_id}/inputs` never merges normal
   chat into a live run. Under the conversation lock, it terminalizes the prior
   foreground interactive run as cancelled/superseded, freezes its process card,
   creates a fresh run with new policy deadline/counters/lease, accepts the new
   learner message, and dispatches only that new run. The partial unique
   foreground index is the durable one-run invariant.
3. `POST /api/tutor/runs/{run_id}/inputs` is not an ordinary follow-up route. It
   is allowed only for a current interactive `waiting_for_input` run whose
   persisted `continuation_kind` explicitly authorizes it. The accepted
   continuation clears the consumed kind, advances the same run revision, and
   may acquire a fresh lease.
4. Raw learner text is stored only in `tutor_messages`; normal input acceptance
   appends an ordered safe event and updates `last_public_activity_at`. The
   conversation list/history reads never reconstruct raw content from events,
   trace, provider output, or diagnostics.
5. A post-commit dispatcher obtains a lease and runs the finite Harness loop.
   Its provider call is outside an implicit PostgreSQL transaction: lifecycle
   methods own short atomic transactions, so a new ordinary turn can acquire the
   conversation lock while a provider response is pending. The loop refreshes
   cancellation/supersede and revision state immediately after every provider
   return, before decision gating, capability dispatch, effect commit and
   terminal persistence. A heartbeat that arrives after nominal expiry may renew
   only while the exact owner and lease generation still match; a replacement
   claim increments the generation and permanently fences the stale worker. A
   stale run converges to a safe cancelled/superseded
   projection and cannot write a Tutor message, conversation title, capability
   receipt or effect.
6. Each interactive context load resolves the authoritative learner input from the exact
   `tutor_run_input_events(run_id, input_revision).message_id` evidence within the
   snapshot's user/run/conversation scope. The Harness carries that input separately
   from optional history, reserves its bounded token cost before every optional
   section, and never calls the provider if even a minimum safe representation cannot
   fit. The optional history excludes that exact message, keeps the newest bounded
   suffix using stable `created_at, id` ordering, and presents the selected suffix in
   chronological order. Proactive runs explicitly declare that no learner input is
   required; they never invent chat text.
7. `GET /api/tutor/runs/{run_id}/events` remains incremental run-local transport
   using a non-negative `Last-Event-ID` cursor. It never calls a provider while
   streaming; Desktop history remains the server-authoritative conversation read.
8. Conversation creation, first-turn, and ordinary-turn requests may carry an
   additive structured `learning_scope`. Each fresh run writes one immutable
   `tutor_run_learning_scopes` snapshot containing `scope_kind`, `task_kind`,
   optional track, and optional knowledge key. Missing scope remains
   `general/general_tutor`; old conversations are never classified from natural
   language. Explicit continuation reuses the persisted snapshot and rejects a
   supplied replacement scope.

### LearningTrack context seam

The LearningTrack package provides `TutorLearningContextAdapter`, a read-only
adapter that converts a run snapshot into bounded sources for scope/task kind,
track language/goal/active plan, and the current node's progress/mastery summary.
`PostgresTutorLearningContextLoader` composes that adapter with the planning fact
projector before context selection; raw plan JSON and mastery evidence bodies never
enter this adapter.

### Authoritative planning facts and snapshot reconstruction

A `plan_drafting` learner input may contribute server-normalized typed facts for
`language_id`, `goal_text`, `target_level`, `weekly_minutes`, `experience_level`,
`teaching_preferences`, and `pace_constraints`. Each confirmed fact is append-only
and retains exact learner-message/run/input-revision evidence. A correction appends
a successor and never rewrites the previous value. Question lifecycle is also an
append-only predecessor chain using the stable field key; the current state follows
the actual leaf rather than timestamp or UUID ordering because PostgreSQL `now()` is
transaction-stable.

Before each provider request, the production loader and context eval both call
`build_authoritative_context_snapshot()`. The result binds the run/input revision,
planning session, current fact revision/fingerprint, required fact sources, question
states, a deterministic snapshot hash, and the confirmed-question reask count.
Resume and replay rebuild the same snapshot from persisted authority instead of
recovering facts from free-form history or an asynchronous summary.

`required_facts` is a non-evictable context section immediately after system/policy
and the separately pinned `current_input`. It is reserved before optional history,
active plan, summary, memory, activity, or capability schemas. If all confirmed facts
cannot fit without truncation, context construction fails closed with
`TUTOR_REQUIRED_FACTS_UNREPRESENTABLE`; it does not silently drop one field.

Recent-history selection pins sources marked `confirmed_fact_source`, `correction`,
or `unresolved_question` before filling the remaining hard item limit by recency. A
confirmed fact is already a structured replacement for its source. An unresolved or
reopened answer without a replacement fact is added to
`compaction_plan.protected_message_ids`, which blocks retirement and increments
`summary_blocked_by_unprojected_fact`. Structured summary remains continuity-only
and cannot override the typed fact authority.

A planning `wait_for_input` action must include a valid stable `question_key`. The
planning decision gate records `asked`, rejects a question whose field is already
confirmed with internal diagnostic `confirmed_question_reasked`, and records a safe
reask counter. Explicit learner correction/reopen creates new lineage before the
field may be asked again. Public API/SSE never exposes gate reasons, fact/event hashes,
prompt text, or provider payloads.

### Public conversation history and process projection

`GET /api/tutor/conversations` returns only learner-visible conversation
summaries in public-activity order. `GET /api/tutor/conversations/{id}/history`
returns reverse chronological public message/process items with a server-signed,
user- and conversation-scoped opaque cursor. A process item is a durable,
server-owned projection with one of `thinking`, `completed`, `superseded`, or
`unavailable`, fixed allowlisted symbolic steps, and server-calculated bounded
elapsed seconds. Legacy message-only rows remain visible without invented cards
or durations.

The only title source is the same successful `TutorDecision.conversation_title`
that writes a learner-visible Tutor reply. It is normalized/validated and stored
once only while `tutor_conversations.title IS NULL`; absence projects as
“新对话”. There is no learner-text fallback, title-only provider call, or rename
surface.

For interactive runs, the provider payload exposes `current_input` separately from
optional `context`. The shared initial/repair teaching policy treats it as the
authoritative request, answers or acknowledges it before any older path, treats
corrections/refusals/completion statements as overrides, avoids repeating rejected
steps, answers advice/comparison questions first, and asks at most one necessary
follow-up. This is an instruction contract backed by deterministic fixtures, not a
keyword router or a claim that fake-model tests prove teaching quality.

The provider boundary uses only the configured primary compatible provider. A
missing, malformed, unsafe, or failed provider response maps to a stable
learner-safe `MODEL_UNAVAILABLE` outcome. There is no provider/model fallback.
At most one same-provider replacement retry may follow a repairable
visible-content, JSON, or typed-item rejection; incomplete, failed,
malformed-envelope, and transport responses terminate without repair. The
replacement request is rebuilt from the authoritative input/context and contains
only bounded field paths plus validation categories. It never echoes the rejected
candidate, provider validation message, prompt, or credentials.

Each actual provider attempt returns a safe `TutorProviderAttemptReceipt`. The first
request and the optional same-provider repair have separate `attempt_index` values,
while `tutor_runs.model_call_count` continues to count one run-loop decision boundary,
not raw HTTP requests. The lifecycle persists attempt receipts immediately after the
provider returns and before the refreshed cancellation/supersede gate; this preserves
already-incurred usage for a stale run without authorizing its public message, title,
capability, or effect.

`LLMUsage` normalizes Responses and Chat Completions fields without changing provider
routing. Provider `input_tokens`/`prompt_tokens` already include cached input, so
`uncached_input_tokens = input_tokens - cached_input_tokens`; cached tokens are never
added to input again. Provider-reported total and calculated input-plus-output remain
separate facts. Missing or malformed usage is unavailable (`None`/SQL `NULL`), not a
zero-valued success and not a Tutor failure. A completed envelope may retain numeric
usage even when visible content, JSON, decision, or safety validation rejects it;
transport failure before an envelope never fabricates usage.
The durable run may retain a bounded internal diagnostic code for configuration,
timeout, authentication/quota/rate-limit, HTTP/transport, invalid provider
response envelope, missing response content, non-JSON response content, typed
contract categories such as missing/extra/invalid action fields, output-safety
rejection, or adapter failure. Public run reads and API/SSE still expose only
`MODEL_UNAVAILABLE` and never return the internal code, raw provider bodies,
prompts, reasoning, transport details, diagnostic artifact identifiers, or
credentials.

### Primary typed-item decision protocol

Before a JSON Tutor decision, `OpenAICompatibleClient.complete_json()` selects one
protocol from the configured provider and model, and never changes that selection
for a retry or failure:

- non-DeepSeek configurations retain the Responses path and receive the generated
  `TutorProviderItemsEnvelope` through strict `text.format=json_schema`;
- DeepSeek uses the Responses path only when the configured model is the exact,
  case-sensitive value `deepseek-v4-flash`; its normalized endpoint is
  `/responses`, with `input`, optional `instructions`, `stream=true`, and a
  bounded Tutor-decision output budget. Official-compatible operation remains
  `text.format=json_object`; `TUTOR_DEEPSEEK_RESPONSES_JSON_SCHEMA_ENABLED=true`
  is an explicit opt-in only for a verified compatible gateway. The physical
  DeepSeek V4 Flash window/output capability remains `1_000_000`/`384_000`,
  leaving a physical input hard limit of `616_000`, but the narrow decision task
  defaults to `16_384` output tokens and does not inherit the physical 384K cap.
  The first attempt keeps the provider's configured/default thinking behavior; a
  repair attempt sends `thinking.type=disabled` by default so replacement behaves
  as a narrow serializer (`TUTOR_DEEPSEEK_REPAIR_THINKING_DISABLED=false` opts
  out). The physical hard limit is a capability boundary, not a per-turn fill target:
  the adaptive planner first estimates the exact serialized system/user messages
  plus protocol reserve and safety margin, then gives ContextBuilder only the
  remaining optional budget;
- every other DeepSeek model retains the Chat Completions path at
  `/chat/completions` with `response_format=json_object` and the conservative
  `TUTOR_DECISION_MAX_OUTPUT_TOKENS` budget.

### Adaptive context budget planning

Every new interactive TurnRun freezes a `TutorContextBudgetPolicy` in
`policy_json` and its policy fingerprint. The policy contains explicit provider
capability evidence, configurable `compact`/`normal`/`complex`/`extended`
targets, warning/critical ratios, one bounded expansion count, and estimator and
policy versions. The exact `deepseek-v4-flash` registry entry uses the verified
1M/384K limits; every other model uses explicit conservative Settings and never
gains a large window from a fuzzy model-name match. Older runs without the new
policy continue to replay their persisted `context_token_budget`.

The planner and provider gateway share one deterministic serializer, so dry-run
estimation covers the real system teaching policy, canonical strict decision
shape, current input, selected context, metadata, JSON envelope, protocol
reserve, and safety margin. Fixed-point metadata stabilization treats the
required-only estimate as a conservative lower bound, so prompt or metadata
length changes cannot make a later total estimate violate the required-request
floor. Required current input is selected first and can never be evicted. Confirmed
planning facts are then reserved as the required-facts section before optional
sources. Optional sources remain bounded and deterministic; activity
and unrelated capability schemas are skipped before a request can cross the
hard limit. A required serialized request that cannot fit returns
`TUTOR_CONTEXT_REQUIRED_OVERFLOW` before any provider call.

Initial mode selection uses only safe structural facts such as current-input
length/line structure, fenced-code volume, candidate-source counts, long-source
counts, recent-history volume, and summary availability. Only the controlled
internal `REBUILD_CONTEXT / insufficient_context` gate can advance one mode,
subject to both the frozen expansion count and existing iteration/model-call
budgets. Context high-water is computed from `required estimate + the selected
mode's optional target ratio`, not from a fixed percentage of a 616K physical
window that normal bounded sources could never reach. Checkpoint metadata stores
only mode, estimates, budgets, counts, source IDs/hashes, thresholds, and
versions; public API/SSE remains unchanged.
Provider `input_tokens` already includes cached input, so cache is never deducted
from preflight physical usage and is never added to actual input a second time.

### Long-conversation summary retrieval and compaction

Interactive context preserves three ordered fidelity tiers: authoritative
`current_input`, the newest prior raw-message suffix, and at most one structured
`working_summary` for older retired messages. The loader resolves all three from
the conversation timeline `(created_at, message_id)`. The current input never
enters the retirement set; equal timestamps use the UUID key to avoid gaps,
duplicates, or later-row interference.

A non-empty continuous retirement prefix produces `tutor_context_summary_v2`
evidence containing the prior summary identity/hash, retired message IDs and
SHA-256 content hashes, and the coverage cursor. Checkpoints, traces, and
`tutor_memory_curation_outbox` persist only this bounded evidence. A leased
`context_summary` curation job re-reads the exact `tutor_messages` rows under the
same user/conversation scope, revalidates ordering, coverage continuity, and
hashes, and sends the bounded raw text only to the configured primary Curator
request. Raw retired content is never copied into a trace, outbox, proposal,
receipt, or summary metadata envelope.

The committed projection is an append-only `tutor_context_summaries` row with a
bounded learner-safe overview plus versioned JSON fields for current goal,
confirmed facts, completed steps, rejected paths, open questions, and learner
preferences. Retrieval accepts only a committed, unexpired, non-stale row with
exact schema/policy versions and coverage earlier than the current input. Legacy
280-character rows remain compatible storage but are never presented as v2.
Malformed or unavailable summaries fail closed to `current_input +
recent_messages`; original messages are not deleted.

Provider conflict priority is fixed as `current_input > required_facts >
semantically pinned recent_messages > ordinary recent_messages > working_summary >
learner_memory/activity`. A newer correction or completion therefore overrides stale
summary content, and the next incremental summary can record the corrected fact.
Conversation continuity is independent of the
inferred-memory opt-in, while the existing scheduler pause, lease, retry,
budget, circuit, finite TurnRun, adaptive request budget, and provider hard limit
remain authoritative.

The Responses adapter accepts final learner-visible content only from
`output_text`. It rejects reasoning-only output, missing visible text, malformed
SSE/envelopes, non-object JSON text, `response.incomplete`, and `response.failed`
with bounded internal categories. A selected-provider HTTP `400` is likewise a
safe internal request-rejected category; it never triggers a protocol, model, or
provider fallback.

The provider contract is the generated, frozen, `extra=forbid`
`tutor_provider_items_v2` envelope: one `agent_message` plus exactly one typed
action (`turn_completed`, `select_skill`, `request_capability`,
`propose_effect`, or `wait_for_input`). The message also carries one to four bounded
`public_thinking_steps`: learner-visible explanations authored specifically for display.
Their wording, tone, ordering, and granularity are model-selected for the current request;
no fixed sentence pattern or transition sequence is required. They are validated as public
teaching output and remain separate from
provider-native hidden reasoning, which the Responses adapter still never reads.
Capability arguments and effect payloads
are bounded `{key,value}` arrays rather than open JSON objects. The provider never
chooses `request_id`, `effect_id`, `expected_input_revision`, checkpoints, input
revision, or terminal state. The server derives deterministic action IDs from the
run/revision/model-call boundary, copies the current revision into effects, maps
the typed action into the domain `TutorDecision`, and then applies the existing
decision gate. The optional `conversation_title` remains an NFKC-normalized,
single-line, learner-safe candidate of at most 48 characters; persistence and
public history remain owned by the lifecycle boundary. A successful public Tutor message
atomically persists its `public_thinking_steps`; failed, denied, stale, superseded, or
message-less results never publish them. Legacy rows project an empty list.

### Context governance eval and calibration

The context-governance evidence layer is offline and additive. The versioned
`tutor_context_eval_v2` fixture composes the already-owned current-input, provider
attempt usage, adaptive budget, and structured-summary contracts; it does not
introduce a second selection algorithm or change online defaults. Each case uses a
fixed capability/policy, deterministic estimator, fake provider, fixed numeric
latency, and synthetic learner-safe content. PostgreSQL-backed owning tests remain
the authority for timeline ordering, scope, append-only receipts, bootstrap, and
summary persistence.

Each case emits `tutor_context_eval_receipt_v1`, whose fields are limited to safe
numbers, booleans, enums, versions, diagnostic codes, and opaque source IDs. Cached
input remains a subset of actual input, repair attempts remain separate, provider
reported total remains distinct from calculated input-plus-output, and unavailable
usage stays `null`. Raw prompt/history, provider body, reasoning, credentials, paths,
commands, and reconstructable summary text are not receipt fields.

`tutor_context_calibration_v1` groups estimate/actual evidence by
provider/protocol/capability/budget mode/estimator/config version. P50/P95 appear only
after the configured sample threshold; excessive estimation error recommends review
of the estimator or safety margin but never changes production settings
automatically. Fake contract evidence, optional real-provider behavior sampling, and
human release approval are three separate states.

## 4. Skills, capabilities, effects, and grounding

- Published Skills are exact `id@semantic-version` bundles with reviewed
  manifest, instruction, and evaluation hashes. Aliases, ranges, `current`, and
  unknown references are denied.
- Skill-managed actions are two-phase. The provider is instructed to select an exact
  eligible Skill first, then request the capability/effect only after the server rebuilds
  context with the reviewed instruction. If a provider skips that step, the decision gate
  may recover only when descriptor/payload validation passes and exactly one
  policy-eligible reviewed Skill covers every requested action: it records only the Skill
  selection and returns `REBUILD_CONTEXT`; it never executes the action from that same
  decision. Zero matches remain `skill_selection_required`, and multiple matches fail
  closed as `action_skill_ambiguous`.
- A decision may select a Skill or request an action, but it cannot mix initial
  selection with a capability/effect in one turn.
- Capability schemas are descriptor-owned and default-deny. Model data never
  becomes a URL, path, shell command, SQL fragment, user id, or database target.
- Grounding reads only the developer-governed registry and pre-indexed facts.
  It does not grant open-web search, arbitrary fetch, crawler, or filesystem
  access.
- Effects require selected-Skill evidence, policy permission, current input
  revision, a valid lease, and a repository transaction. The initial default
  policy denies undeclared actions.

## 5. Privacy, diagnostics, and persistence

The canonical learner message body is limited to `tutor_messages`. Events,
traces, checkpoints, capability/effect/provider-attempt receipts, exports, outbox
rows, and public SSE are projected twice through learner-safe allowlists. They
omit raw prompts/history, provider payloads/errors/reasoning, hidden tests,
reference answers, submitted code, filesystem/container paths, shell/SQL targets,
credentials, diagnostic artifact identifiers, and checkpoint payloads.

Raw provider response capture is a separate local operator boundary and defaults
to `off`. The generic LLM client captures nothing unless the Tutor gateway
explicitly calls it with `capture_provider_body=true` and injects the diagnostic
store. When `TUTOR_PROVIDER_DEBUG_CAPTURE_MODE=rejected`, a valid random
32-byte base64 key is mandatory. Each attempt buffers at most
`TUTOR_PROVIDER_DEBUG_CAPTURE_MAX_BYTES`, accepted attempts zero/discard the
buffer, and rejected attempts write an AES-GCM artifact under the configured
local directory with a random 96-bit nonce and authenticated safe metadata.
Artifacts are never database rows or API fields, use a 24-hour default retention,
and are pruned only inside the configured directory. A capture/configuration
failure never exposes the body or changes the learner-safe terminal projection.

`event_sequence` is a run-local durable ordering key, not an acknowledgement
store. API idempotency records bind an operation, user scope, request body hash,
and safe response. A reused idempotency key with different immutable input is a
conflict, never a second write.

## 6. LearningTrack authority and learner controls

`/api/learning-tracks` is the verified-only HTTP boundary for multiple independent
language/goal tracks. PostgreSQL owns immutable predecessor-linked plan revisions,
one active pointer per track, stable-key progress, append-only mastery evidence,
and a deterministic mastery projection. Activation uses expected track version
and direct-predecessor checks; it preserves progress/mastery for retained
`knowledge_key` values and initializes new nodes from satisfied prerequisites.

`ExecutionTierResolver` is the sole LearningTrack capability projection. Local
development may expose `teaching_local`; public composition requires both a
reviewed immutable image lock and compatible executor health for
`container_verified`. Static teaching/review capability falls back to
`static_only`; all other cases are `unavailable`. Resolution never launches a
runner or executor.

LearningTrack Home, the single-page immutable LessonDocument reader, server-authoritative exercise Gate binding/scoring, append-only Attempt flow, module diagnostic confirmation, and existing-queue execution handoff are now implemented. Spaced review, model code-review exercise, the full three-column workspace, and a reviewed production container image fleet remain separate product work.

Existing user-level Tutor controls remain unchanged:

- Plan revisions are immutable. `tutor_active_plans` is the only active pointer;
  rollback can move only to the stored predecessor and writes an action record.
- Memory entries carry bounded evidence and retention facts. Corrections append
  replacements; deletion is a guarded state transition.
- Activity and inbox items are learner-safe projections. Read/dismiss actions
  are user-scoped and idempotent.
- Preferences expose inferred-memory control and a proactive pause; they never
  expose provider configuration, global budget controls, or unrestricted
  capability permission.

## 7. Verified-only proactive delivery and curation

The proactive scheduler is an active but deliberately narrow default. Its
configuration defaults to `TUTOR_PROACTIVE_SCHEDULER_ENABLED=true`,
`TUTOR_BACKGROUND_HARD_PAUSED=false`,
`TUTOR_PROACTIVE_CUTOVER_ELIGIBLE=true`, a daily proactive budget of `1`, and
a proactive concurrency limit of `1`. A user preference defaults to
`enabled=true` and `hard_paused=false`; repeatable bootstrap restores the old
unpaused `enabled=false` default to enabled without overriding an explicit
pause.

Default availability is **not** blanket background execution. Before a
candidate or run is allowed, the scheduler checks global enablement/hard pause,
cutover eligibility, the current `verified` receipt for that exact user, the
user pause/enablement record, daily budget, cooldown, concurrency, lease/retry
limits, and circuit breaker. An unverified user's candidate records
`cutover_unverified`; it does not call the provider or reserve a proactive run.

Signals are derived only from durable terminal interactive-run metadata: run
identity, terminal outcome, and terminal timestamp are hashed into a stable
safe source fact. The scanner does not read learner messages, prompt/history,
code, trace, checkpoint, or provider diagnostics. Production scan semantics are
global (`user_id=None`). Explicit user scope exists only for fixture and
maintenance isolation and must not silently change the normal queue.

The production composition records the persisted catalog snapshot, loads exact
`TutorRunSkillSelection` evidence, and permits only the reviewed
`tutor.learner-state@1.0.0` selection plus `tutor.activity.record`. Provider
public text is stripped from background decisions. A successful background run
can create learner-safe activity/inbox projections only; it cannot create a
learner-visible chat message or desktop notification, execute
`runner.execute`/learner code, start a subprocess, or directly write
`tutor.memory.record`.

Curation and inferred memory remain default-off: inferred-memory is false,
curation daily budget is `0`, and curation max output tokens is `0`. Enabling a
curation setting later does not weaken any verified, policy, lease, source,
retention, or safe-projection gate.

## 8. Cutover, deletion, and rollback

`harness_cutovers` records server states including `required`, `summary_ready`,
`verified`, `verification_failed`, `blocked_target_state`, and
`blocked_checkpoint_scope`.

The server recomputes the exact legacy summary, nonce, and hash during
confirmation. It deletes only proven legacy ownership, verifies the same scope,
preserves local identity/display name and allowed notification preferences, and
commits a `verified` receipt atomically. Pre-cutover `tutor_*` rows are target
contamination and block without deletion. Unknown checkpoint scope fails closed.

Before explicit confirmation, code/configuration rollback can restore code only
while legacy rows remain. After confirmed deletion, rollback does not recreate,
migrate, or infer deleted learner plans, sessions, attempts, FSRS state, notes,
or messages.

## 9. Optional live-provider smokes

The default suite remains offline and fake-only. A developer may intentionally run the
controlled latest-input scenario against the already configured local provider with:

```powershell
$env:AEARN_RUN_TUTOR_LATEST_INPUT_SMOKE = "1"
uv --directory .\aearn\services\api run python -m app.services.tutor.latest_input_smoke
```

The command uses normal settings/environment credential handling and does not print
credentials, provider payloads, prompts, reasoning, or transport diagnostics. It emits
only bounded learner-visible messages plus boolean rubric fields for latest-turn
relevance, correction acknowledgement, rejected-step repetition, answer-first
behavior, and stale-path abandonment. This smoke is optional model-behavior evidence;
it is not CI, release approval, or a substitute for deterministic contract tests.

The integrated context-governance smoke is a separate five-turn boundary and remains
disabled unless explicitly approved and enabled:

```powershell
$env:TUTOR_REAL_PROVIDER_SMOKE = "1"
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_real_provider_smoke.py -q -m real_provider
```

It uses the fixed five learner turns from the acceptance plan, the production planner
and primary gateway, and bounded synthetic user/conversation/run IDs. Output is limited
to learner-safe replies, usage numbers, cache ratio, selected budget mode, safe latency,
attempt count, and boolean rubric. It never prints or persists provider request/response
bodies, prompt/history, reasoning, credentials, paths, or commands. The smoke is not
run by default and does not authorize release.

## 10. Verification and release non-claim

### Latest-input teaching relevance verification (2026-08-05)

The authoritative-current-input change was verified locally against real PostgreSQL
and the complete API suite, not released:

- focused context/provider/eval/smoke batch -> **71 passed**;
- input-merge/run-loop/SSE regression batch -> **23 passed**;
- PostgreSQL bootstrap/run-repository/context-loader batch -> **15 passed**;
- complete `python -m pytest -q` -> **365 passed**;
- `ruff check app tests`, `python -m mypy app --no-incremental`
  (**109 source files**), and `uv lock --check` -> passed;
- Trellis task validation and `git diff --check` -> passed (line-ending
  warnings only).

The optional live-provider smoke was added but not executed, because no separate
approval to use a real provider was given. These checks verify the local contract;
they do not prove live-model teaching quality or authorize commit, push, deployment,
or production-data changes.

### LearningTrack foundation verification (2026-08-05)

The additive LearningTrack foundation was verified locally against real
PostgreSQL and the complete API suite, not released:

- `uv --directory .\aearn\services\api run python -m app.db.bootstrap` twice -> passed;
- LearningTrack/schema/Tutor/cutover focused batch -> **95 passed**;
- complete `python -m pytest -q` -> **345 passed**;
- `ruff check app tests` and `python -m mypy app --no-incremental` -> passed
  (**108 source files**);
- `uv --directory .\aearn\services\api lock --check`, Trellis task validation,
  and `git diff --check` -> passed (line-ending warnings only).

This verifies contracts, scoped PostgreSQL constraints, progress merge, mastery
replay, local-data inventory, and Tutor scope compatibility. It does not enable
Gate/Review/full-workspace/code execution, prove a public container fleet, or authorize
commit, release, push, or deployment.

### Prior current local change verification (2026-08-03)

The TurnRun/history and strict provider-decision changes were verified locally,
not released:

- `uv --directory .\aearn\services\api lock --check && uv --directory .\aearn\services\api run python -m pytest -q` -> **321 passed**;
- `uv --directory .\aearn\services\api run ruff check app tests` -> passed;
- `uv --directory .\aearn\services\api run python -m mypy app` -> **99 source files** with no issues;
- `pnpm --dir .\aearn desktop:check` -> `tsc && vite build` passed;
- `git diff --check` -> passed (line-ending warnings only).

Focused coverage includes fresh ordinary TurnRuns, first-turn idempotency,
post-provider supersede suppression, title/process/history projection, cursor
scope, strict DeepSeek decision handling, and injected-clock proactive
lease/CAS behavior. These checks confirm the local contract only; they do not
prove live-provider teaching quality, latency, quota, browser interaction flow,
or production image-fleet behavior.

### Historical release-readiness matrix (2026-07-29)

The earlier final local verification matrix was run serially on 2026-07-29: the
API suite passed **275 tests**, API Ruff and Mypy passed (Mypy: **99 source
files**), API lock check passed, standalone executor tests passed **9 tests**,
Desktop `tsc && vite build` passed, current source/dependency audit returned no
legacy matches, task validation passed, and `git diff --check` passed. The
full command/output record, fixture posture and resolved test regression are in
[`../qa/tutor-harness-release-readiness.md`](../qa/tutor-harness-release-readiness.md).

Neither the current local checks nor the historical matrix is deployment,
release approval, commit, push, or task-archive authorization.


### Adaptive context budget verification (2026-08-08)

The adaptive planner change was verified locally without a live provider, release,
or production-data mutation:

- focused context/builder/provider/run-loop/input-merge batch -> **101 passed**;
- PostgreSQL bootstrap/constraint and run-policy round-trip batch -> **12 passed**;
- complete serial `python -m pytest -q` -> **390 passed**;
- `ruff check app tests`, `python -m mypy app --no-incremental`
  (**112 source files**), and `uv lock --check` -> passed;
- Trellis task validation and `git diff --check` -> passed.

These checks prove deterministic local contracts, policy persistence, hard-limit
preflight, bounded rebuild, safe metadata, and cache accounting semantics. They do
not claim live-model tokenization parity or authorize commit, push, deployment, or
production-data changes.

### Context governance eval verification (2026-08-10)

The versioned eval/observability patch was exercised locally without a real provider,
commit, push, deployment, or production-data mutation. The first cross-contract batch
completed with **130 passed, 1 skipped**; the skipped case is the explicitly gated
`real_provider` smoke. It covered v1 compatibility, v2 fixture validation, safe receipts,
current/history ordering through PostgreSQL, usage/cache/repair attempts, all budget
modes and hard limits, summary retirement/correction/stale behavior, run-loop regression,
provider gateway regression, run persistence, and repeatable bootstrap. The final matrix then completed with **404 passed, 1 skipped in 33.41s**, Ruff
passing, Mypy passing on **114 source files**, `uv lock --check` passing, Desktop
`tsc && vite build` passing with **46 modules transformed**, and Trellis/diff hygiene
passing. These results still do not authorize a real-provider call, commit, push,
deployment, task archive, or release approval.

## 2026-08-10 Learning-plan drafting composition

The interactive dispatcher remains deny-by-default. A PostgreSQL-backed policy resolver grants only `tutor.learning-plan-draft@1.0.0` and `learning.plan.draft@1.0.0` for a current, non-terminal, non-superseded interactive `plan_drafting` run whose conversation owns an active planning session. The capability validates compact nested JSON, server-owned language/source/runtime facts and the frozen LearningPlan DAG, then appends one typed draft. Generic capability receipts contain only draft id/version/hash/status. Effects remain denied and HTTP confirmation is the only track-creation action. The learning context decorator appends bounded scope/session/current-draft descriptors without changing current-input pinning, adaptive budget order, usage/cache accounting or summary compaction.

### LessonDocument authoring boundary (2026-08-11)

Lesson authoring is a separate server-owned artifact workflow, not an expansion of the generic Tutor capability payload. A durable run is created and committed before dispatch. The dispatcher claims a lease, reads only persisted registry-owned grounding, assigns short evidence handles, calls the configured primary provider through a strict JSON port, applies deterministic schema/citation/coverage/Gate quality gates, rechecks track/progress/source versions, and publishes standard + personalized documents, snapshots, assignment, and terminal run state in one final transaction.

There is no provider/model fallback and no static lesson template fallback. Provider calls happen outside long PostgreSQL transactions. Attempt receipts contain only safe provider/model/protocol/outcome/usage/hash metadata. The interactive Tutor context limit and `12 × 360` generic capability envelope are unchanged; ordinary Tutor context does not receive full Lesson blocks or source excerpts.

### Exercise Gate execution reuse boundary (2026-08-11)

Exercise Gate is a separate learning artifact workflow, not a generic Tutor capability/effect call. The API accepts a scoped Attempt and private submission, then maps execution-required work into the existing `tutor_execution_intents` / `tutor_execution_jobs` lifecycle with `source_kind=exercise_submission` and `owner_kind=exercise_attempt`. It does not create a Tutor conversation, message, run, or effect. Existing Tutor execution remains on `tutor_message` / `tutor_effect`; database one-of checks prevent a row from mixing the two ownership models.

The executor claims the same lease/launch-token job, but its trusted-input loader resolves Gate input only after matching user, Attempt, submission, exercise version, private rubric and runtime profile references. The public API never receives the trusted input or private artifacts. Terminal execution output is reduced to an immutable learner-safe Attempt result before the learning service can project Gate/mastery/progress; the executor itself never writes pass, mastery or unlock authority.

`container_verified` remains fail-closed and is not granted solely because a route exists. Public execution requires a reviewed immutable image lock and compatible health/profile evidence. `teaching_local` is development-only; `static_only` uses deterministic server evaluation with `execution_claim=not_run`; `unavailable` creates no execution job and never falls back to host subprocess, legacy runner or a second queue. This child did not build, sign, publish or approve a reviewed image fleet and did not call a real provider.
