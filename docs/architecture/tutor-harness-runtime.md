# Tutor Harness Runtime Architecture

**Status:** Current runtime contract as of 2026-07-29.
**Authority:** Current route registration, `aearn/services/api/app`,
`aearn/apps/desktop`, `aearn/services/worker`, `schema.sql`, and their tests.
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
  -> Tutor conversation, activity, inbox, memory, plan revisions, preferences
```

A missing, pending, blocked, failed, or malformed cutover state denies both the
Tutor runtime and the removed legacy runtime. A client cannot choose deletion
scope, bypass the receipt, restore a saved legacy plan id, or recreate deleted
legacy learner history.

## 2. Runtime composition

| Layer | Owner | Contract |
| --- | --- | --- |
| Public adapter | `routes/tutor.py`, `services/tutor/public_api.py` | Validates user scope and idempotency, exposes learner-safe projections, and never performs Graph/router compatibility work. |
| Interactive dispatch | `services/tutor/interactive.py` | Starts an already accepted input only after its transaction commits, composes a bounded loop, and keeps provider failures out of the accepted-input response. |
| Harness | `agents/harness/`, `services/tutor/run_loop.py` | Bounded run loop, lease ownership, input-revision reload, exact Skill selection, capability/effect gate, checkpoint lifecycle, and typed terminal outcome. |
| Durable state | `services/tutor/persistence.py`, `learner_state.py`, `proactive_repository.py` | PostgreSQL owns user/run/conversation scope, ordered events, idempotency, CAS effects, redacted projections, plan/memory/activity state, and queue leases. |
| Worker | `services/worker/aearn_worker/worker_app.py` | Thin Celery wrappers for `health.ping`, `tutor.proactive.scan_due_signals`, `tutor.proactive.drain_candidates`, and `tutor.curation.drain`. |
| Desktop | `apps/desktop/src/` | Bootstraps `loading -> welcome -> cutover -> tutor`; it presents server decisions and cannot override them. |

## 3. Interactive Tutor run

1. `POST /api/tutor/conversations` creates or resumes one learner-visible
   conversation.
2. `POST /api/tutor/conversations/{conversation_id}/inputs` creates an
   interactive run or merges an input into a compatible non-terminal run.
   `POST /api/tutor/runs/{run_id}/inputs` is the explicit follow-up form.
3. The input transaction stores raw learner text only in `tutor_messages`,
   increments the run-local input revision, and appends an ordered safe event.
4. A post-commit dispatcher obtains a lease and runs the finite Harness loop.
   The loop reloads the authoritative input revision before every unsafe
   boundary. Stale effects are recorded as `stale_rejected`; their handlers are
   not called.
5. `GET /api/tutor/runs/{run_id}/events` replays only the ordered safe suffix
   using a non-negative `Last-Event-ID` cursor. It never calls a provider while
   streaming.

The provider boundary uses only the configured primary compatible provider. A
missing, malformed, unsafe, or failed provider response maps to a stable
learner-safe `MODEL_UNAVAILABLE` outcome. There is no provider/model fallback.

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
traces, checkpoints, capability/effect receipts, exports, outbox rows, and
public SSE are projected twice through learner-safe allowlists. They omit raw
prompts/history, provider payloads/errors/reasoning, hidden tests, reference
answers, submitted code, filesystem/container paths, shell/SQL targets,
credentials, and checkpoint payloads.

`event_sequence` is a run-local durable ordering key, not an acknowledgement
store. API idempotency records bind an operation, user scope, request body hash,
and safe response. A reused idempotency key with different immutable input is a
conflict, never a second write.

## 6. Learner controls

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

## 9. Verification and release non-claim

The final local verification matrix was run serially on 2026-07-29: the API
suite passed **275 tests**, API Ruff and Mypy passed (Mypy: **99 source
files**), API lock check passed, standalone executor tests passed **9 tests**,
Desktop `tsc && vite build` passed, current source/dependency audit returned no
legacy matches, task validation passed, and `git diff --check` passed. The
full command/output record, fixture posture and resolved test regression are in
[`../qa/tutor-harness-release-readiness.md`](../qa/tutor-harness-release-readiness.md).

Those checks do not prove a live provider's teaching quality, latency, quota,
or production image fleet behavior. PostgreSQL/Redis were healthy during
verification; API/Desktop processes were intentionally not left running and
the local dev-state file still reports stale historical PIDs. No deployment,
release approval, commit, push, or task archive follows from this documentation.
