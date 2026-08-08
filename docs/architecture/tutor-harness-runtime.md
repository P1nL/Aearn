# Tutor Harness Runtime Architecture

**Status:** Current runtime contract as of 2026-08-08.
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
| Learning domain | `routes/learning_tracks.py`, `services/learning/` | Owns track-scoped plans, progress/mastery, execution-tier projection, immutable scope snapshots, and a read-only Tutor context adapter; it does not implement Lesson/Gate/Review or execute code. |
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
   terminal persistence. A stale run converges to a safe cancelled/superseded
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
This child freezes that adapter contract only. The existing provider context
priority and item limits are unchanged; a later integration task may compose the
adapter after defining how track sources coexist with the current user-level Tutor
plan. Raw plan JSON and mastery evidence bodies never enter this adapter.

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
At most one same-provider repair retry may follow a repairable visible-content,
JSON, or Tutor-decision rejection; incomplete, failed, malformed-envelope, and
transport responses terminate without repair. The reminder never echoes the
rejected response, validation detail, prompt, or credentials.

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
response envelope, missing response content, non-JSON response content, invalid
Tutor decision, output-safety rejection, or adapter failure. Public run reads and
API/SSE still expose only `MODEL_UNAVAILABLE` and never return the internal code,
raw provider bodies, prompts, reasoning, transport details, or credentials.

### Primary JSON decision protocol

Before a JSON Tutor decision, `OpenAICompatibleClient.complete_json()` selects one
protocol from the configured provider and model, and never changes that selection
for a retry or failure:

- non-DeepSeek configurations retain the existing Responses path;
- DeepSeek uses the Responses path only when the configured model is the exact,
  case-sensitive value `deepseek-v4-flash`; its normalized endpoint is
  `/responses`, with `input`, optional `instructions`, `stream=true`,
  `text.format=json_object`, and bounded `max_output_tokens`. The configured
  DeepSeek V4 Flash window is `1_000_000` tokens and its generated-output cap is
  `384_000`; the interactive ContextBuilder receives the remaining `616_000`
  token selection budget, without broadening the fixed, learner-safe context
  source allowlist;
- every other DeepSeek model retains the Chat Completions path at
  `/chat/completions` with `response_format=json_object`.

The Responses adapter accepts final learner-visible content only from
`output_text`. It rejects reasoning-only output, missing visible text, malformed
SSE/envelopes, non-object JSON text, `response.incomplete`, and `response.failed`
with bounded internal categories. A selected-provider HTTP `400` is likewise a
safe internal request-rejected category; it never triggers a protocol, model, or
provider fallback and its response body is not retained.

Tutor decision JSON is a frozen, `extra=forbid` envelope with one canonical
example shared by the initial prompt and the at-most-once same-model repair. A
normal direct reply explicitly sets `terminal_intent="completed"`. A
`continuation_kind` is an enum and is valid only with
`checkpoint_reason="capability_result"` and no terminal intent. The optional
`conversation_title` is an NFKC-normalized, single-line, learner-safe candidate
of at most 48 characters. This adapter validates and types the candidate only;
conversation-title persistence and public history behavior remain owned by the
separate lifecycle boundary.

## 4. Skills, capabilities, effects, and grounding

- Published Skills are exact `id@semantic-version` bundles with reviewed
  manifest, instruction, and evaluation hashes. Aliases, ranges, `current`, and
  unknown references are denied.
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
traces, checkpoints, capability/effect/provider-attempt receipts, exports, outbox rows,
and public SSE are projected twice through learner-safe allowlists. They omit raw
prompts/history, provider payloads/errors/reasoning, hidden tests, reference
answers, submitted code, filesystem/container paths, shell/SQL targets,
credentials, and checkpoint payloads.

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

This foundation intentionally does not implement a LearningTrack UI,
LessonDocument, exercise Gate, module diagnostic, spaced review, model code-review
exercise, or actual code execution. Those remain separate product children.

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

## 9. Optional live-provider latest-input smoke

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
Lesson/Gate/Review/UI/code execution, prove a public container fleet, or authorize
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
