# Tutor Harness Runtime Architecture

**Status:** Current runtime contract as of 2026-08-27.
**Authority:** Current route registration, `aearn/services/api/app`,
`aearn/apps/desktop`, `aearn/services/worker`, `services/learning/`,
the manifest-ordered `app/db/schema/` fragments, and their tests.
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
  -> LearningTrack, Lesson/Gate/Review routes and Tutor conversation/activity/inbox/memory/preferences
```

A missing, pending, blocked, failed, or malformed cutover state denies both the
Tutor runtime and the removed legacy runtime. A client cannot choose deletion
scope, bypass the receipt, restore a saved legacy plan id, or recreate deleted
legacy learner history.

## 2. Runtime composition

| Layer | Owner | Contract |
| --- | --- | --- |
| Public adapter | `routes/tutor.py`, `services/tutor/public_api.py` | Validates user scope and idempotency, exposes learner-safe projections, and never performs Graph/router compatibility work. |
| Learning domain | `routes/learning_tracks.py`, `routes/exercise_gates.py`, `routes/learning_track_reviews.py`, `services/learning/` | Owns track-scoped plans, progress/mastery, immutable LessonDocument/source snapshots/assignments, exercise Gate/Attempt/module-diagnostic authority, spaced-review schedule/session authority, execution-tier projection, immutable scope snapshots, and a read-only Tutor context adapter. |
| Interactive dispatch | `services/tutor/interactive_worker.py`, `services/tutor/interactive.py` | Claims a PostgreSQL durable job after commit, invokes the existing bounded Harness dispatcher, and maps wakeup/worker failure to retry/dead state without exposing provider errors in the accepted-input response. |
| Harness | `agents/harness/`, `services/tutor/run_loop.py` | Bounded run loop, lease ownership, input-revision reload, exact Skill selection, capability/effect gate, checkpoint lifecycle, and typed terminal outcome. |
| Durable state | `services/tutor/persistence/`, `conversation_contracts.py`, `learner_state.py`, `proactive_repository.py` | PostgreSQL owns protocol version, user/run/conversation scope, run-local and conversation-global ordered events, snapshots, idempotency, durable dispatch leases, CAS effects, redacted projections, and background queues. |
| Worker | `services/worker/aearn_worker/worker_app.py` | Thin Celery wrappers for `health.ping`, high-priority `tutor.interactive.dispatch/reconcile`, proactive scan/drain, and low-priority curation. Celery is wakeup/periodic scheduling, never the interactive authority. |
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
  -> idle: fresh TurnRun
  -> active/waiting/paused: pending FIFO Queue item

explicit control
  -> Steer: same active turn + next input revision
  -> Interrupt: public interrupted + optional Queue pause
  -> resume/execute: fresh claimed TurnRun
  -> Retry: fresh retry lineage

typed blocking request
  -> source TurnRun completes with awaiting_* reason
  -> POST /conversations/{conversation_id}/requests/{item_id}/responses
  -> fresh answer TurnRun + fresh dispatch job
```

1. Selecting “新对话” creates only local Desktop draft state. The first nonblank
   submission calls `POST /api/tutor/conversations/first-turn`; it atomically
   creates the learner-visible conversation, fresh run, learner message/input
   event, and `input_received` public-process projection. API idempotency owns
   replay; a rollback cannot leave an empty conversation or duplicate dispatch.
2. `POST /api/tutor/conversations/{conversation_id}/inputs` never implicitly supersedes
   or resumes a live run. Under the conversation lock it creates a fresh turn only when idle;
   otherwise it appends a pending `tutor_queued_inputs` item (maximum 10) with immutable
   input metadata and increments `control_version`. FIFO claim creates the learner message,
   input event, process, fresh policy and dispatch job atomically. Explicit `Steer` alone may
   claim one pending item into the current run by advancing its input revision.
3. A `thread_turn_v2` continuation decision never reopens its source run. It atomically
   creates one `tutor_interaction_requests` row/item, terminalizes the source turn as
   completed with `awaiting_user | awaiting_approval | awaiting_authority`, releases the
   lease, and increments conversation control authority. Learner response or verified
   authority receipt CAS-resolves that exact request and creates a new run with fresh
   policy deadline, zeroed counters, revision 1, `response_to_request_id`, a new process,
   and a new one-row dispatch job. `/runs/{run_id}/inputs` remains legacy-only until the
   global cutover child retires it.
4. Raw learner text is stored only in `tutor_messages`; normal input acceptance
   appends an ordered safe event and updates `last_public_activity_at`. The
   conversation list/history reads never reconstruct raw content from events,
   trace, provider output, or diagnostics.
5. Every new learner-visible fresh turn is explicitly `thread_turn_v2`; historical,
   proactive, and internal runs remain `legacy_v1`. The accepting transaction creates
   or rearms exactly one `tutor_interactive_dispatch_jobs` row and appends initial
   conversation events with the owning mutations. After commit, FastAPI performs a
   best-effort Celery wakeup plus a local low-latency claim. A duplicate task cannot
   dispatch without winning the PostgreSQL job lease; expired leases and lost wakeups
   are recovered by `tutor.interactive.reconcile` from Celery beat.
6. A claimed dispatcher obtains the existing run lease and runs the finite Harness loop.
   Its provider call is outside an implicit PostgreSQL transaction. Normal Send can enqueue
   while the provider is pending without invalidating the current turn; explicit Steer or
   Interrupt changes revision/cancel authority. The loop refreshes cancellation, lease and
   revision immediately after every provider return and before decision, capability, effect
   and terminal writes. A stale revision/interrupted run cannot publish a message/title or
   commit capability/effect. After a normally completed job, the worker alone performs
   completed-only FIFO drain; failed/interrupted/request-pending paths pause instead.
7. Each interactive context load resolves the authoritative learner input from the exact
   `tutor_run_input_events(run_id, input_revision).message_id` evidence within the
   snapshot's user/run/conversation scope. The Harness carries that input separately
   from optional history, reserves its bounded token cost before every optional
   section, and never calls the provider if even a minimum safe representation cannot
   fit. The optional history excludes that exact message, keeps the newest bounded
   suffix using stable `created_at, id` ordering, and presents the selected suffix in
   chronological order. Proactive runs explicitly declare that no learner input is
   required; they never invent chat text.
8. `GET /api/tutor/runs/{run_id}/events` remains incremental run-local compatibility
   transport using a non-negative `Last-Event-ID` cursor. The current
   `GET /api/tutor/conversations/{conversation_id}/snapshot` returns
   `tutor_conversation_snapshot_v3`, while Desktop keeps read compatibility with v2.
   `/events` replays only `tutor_conversation_event_v2` rows with a signed,
   user/conversation-scoped opaque cursor v2. `turn_output` may carry either the
   Harness-compatible `tutor_public_thinking_stream_v1` or the Codex-only
   `tutor_runtime_item_stream_v1`; every other event still invalidates the snapshot.
   Neither stream calls a provider; heartbeat comments do not advance durable sequence.
9. Conversation creation, first-turn, and ordinary-turn requests may carry an
   additive structured `learning_scope`. Each fresh run writes one immutable
   `tutor_run_learning_scopes` snapshot containing `scope_kind`, `task_kind`,
   optional track, and optional knowledge key. Missing scope remains
   `general/general_tutor`; old conversations are never classified from natural
   language. A typed response/authority turn snapshots the same immutable conversation
   scope onto its fresh run; the response contract has no scope override field.

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

provider continuation intent 是精确五分支枚举：`clarification` 只处理一处普通歧义；
`planning_input` 只补齐一项计划事实；`approval` 只请求明确授权；`capability_result` 与
`external_result` 只等待已声明的受信结果。只有 `planning_input` 必须携带 allowlisted
`question_key`；provider 不得定义 options/schema/proposal/authority receipt。server-side
`tutor_planning_questions_v1` 为七字段构造 immutable presentation，并复用
`normalize_planning_fact()` value contract。planning decision gate 记录 `asked`、拒绝无 active
session 或 confirmed-field reask。typed request public payload 不包含 provider body、raw reasoning、
capability args、issuer secret 或 raw authority result。每个 typed request 在同一事务中同时持久化
一条 `tutor_messages` 正式回答和一个 elicitation/approval item；时间线固定先显示正式回答，再显示
composer/审批栏，不能让请求卡片替代正式回答。

learner request response 是 closed union 并以 request item ID + expected version + response hash CAS；
approval 还必须匹配 exact proposal identity。authority receipt 没有 learner route，内部 service
验证 issuer/subject/scope/request hash/result hash/receipt identity；ambiguous verification 保持 pending。
fresh response context 固定包含来源 request identity、safe descriptor、learner answer或 verified receipt
摘要和 `in_reply_to_item_id`，不从自由文本猜测批准或 authority success。

### Queue 与显式 conversation control（2026-08-14）

Queue authority 存在 PostgreSQL，而不是 Desktop 本地数组或 Celery。所有 edit/delete/reorder/
Steer/Interrupt/resume/execute/Retry 都先锁 conversation 并校验 expected `control_version`；item mutation
还校验 item version。pending request 阻塞所有执行型 control，但普通 Send 仍可排队。Interrupt 将
当前 turn 投影为 `interrupted` 并在仍有 pending item 时设置 `queue_paused`; failed completion 使用
reason=`failed`，request 使用 reason=`pending_request`。普通 Send 不清除 pause。

`resume` 仅在 idle、无 pending request 时解除 pause 并 FIFO claim；`execute` 可原子 interrupt 当前
turn 后 claim 指定 item；`Steer` 不创建新 run，只把指定 item 的原始 metadata 应用到同一 scope 的
下一 input revision。completed-only drain 与 duplicate worker 由 conversation lock、partial position unique、
item state CAS 和 one-foreground-run invariant 去重。Retry 创建 fresh run，并沿稳定 retry root 对 effect
logical action receipt 去重；不明确的 proposed authority 禁止再次调用 handler。

### Public conversation history and process projection

`GET /api/tutor/conversations` returns only learner-visible conversation
summaries in public-activity order. The legacy `/history` endpoint keeps its existing
reverse-chronological message/process shape. The v1 snapshot exposes a strict
`message | process | elicitation | approval | error` item union, public active-turn
status (`in_progress | completed | interrupted | failed`), typed pending request/item projection,
the typed pending Queue, control/pause authority, and a stream cursor. Current process states are `thinking`,
`waiting_input`, `waiting_approval`, `waiting_authority`, `completed`, `interrupted`,
`superseded`, `unavailable`, or `failed`; labels remain server allowlisted and elapsed
time remains bounded. Legacy message-only rows remain visible without invented cards,
events, or durations.

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

### Learner-visible public thinking text stream

Tutor provider output uses `tutor_provider_items_v4`. A successful `agent_message`
contains one bounded `public_thinking_text` string before the authority-first answer
`text`; the model owns paragraphs and line breaks, while the client must not number,
sort, or reinterpret it. Legacy `public_thinking_steps_json` remains read-only history
compatibility and is joined with `"\n\n"`; new rows never dual-write both
representations.

`OpenAICompatibleClient` exposes a generic `LLMVisibleOutputObserver`. The Responses
adapter forwards only `response.output_text.delta`; provider `reasoning`,
`reasoning_content`, prompts, raw events, bodies, trace, and diagnostics never enter the
observer. `TutorProviderPublicTextProjector` incrementally decodes only the exact JSON
path `message.public_thinking_text`, handles arbitrary chunking and JSON escapes, and
publishes learner-safe cumulative prefixes in at most 160-character durable chunks.
Those `append` chunks remain provisional even when provider transport reaches EOF. The
projector only closes and flushes its parser at EOF; `PrimaryTutorProviderGateway` emits
the durable `complete` event only after the entire object passes schema/domain validation,
public-output safety checks, and exact stream/final text matching. Duplicate/invalid fields,
a transport restart, cumulative safety failure, final-text mismatch, lease loss, stale
revision, repair, interrupt, or supersede reset/discard the current generation and fail
closed. A rejected attempt therefore has no `complete` event.

`tutor_turn_public_thinking_streams` stores only the approved prefix and its exact
run/input-revision/decision-iteration/generation/provider-attempt fence. Each mutation
and matching `turn_output` event is one short PostgreSQL transaction. Snapshot v2 may
project an exact active row as `active_thinking`; a terminal Tutor message, or the formal
Tutor message plus its typed request, accepts the completed stream atomically only when it equals
the validated decision.
The final answer is never streamed from partial provider JSON and remains hidden until
normal decision, action/effect, stale-authority, and terminal persistence gates pass.

Desktop displays a non-interactive `StateDot + Think` immediately for a running active
turn. Live `append` text is buffered off-DOM and becomes a native disclosure only after
both the fixed first-text stability window and the validated `complete` event are satisfied.
A completed snapshot may restore its text immediately; an active incomplete snapshot stays
buffered. The disclosure defaults expanded, preserves literal whitespace, and reveals one
grapheme per visual tick. The newly persisted answer starts only after the thinking queue
catches up; `Think` remains expanded until the answer queue completes, then auto-collapses
once. Historical messages render immediately and collapsed. Reduced motion synchronizes
approved text without animation but preserves the same authority and one-time collapse
semantics.

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
`tutor_provider_items_v3` envelope: one `agent_message` plus exactly one typed
action (`turn_completed`, `select_skill`, `request_capability`,
`propose_effect`, or `wait_for_input`). `wait_for_input` 使用上述五类精确
`continuation_kind`，并由 generated schema、canonical branch examples 与 server-side pairing
validator 同时约束。The message carries one to four bounded
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

### Controlled Action Runtime (2026-08-12)

The Harness now wraps approved `grounding.retrieve`, `learning.plan.draft`, and
`runner.execute` work in one versioned Action Runtime lifecycle. An exact
`ActionDescriptor` declares input/output schema, owner adapter, allowed origin/task
kind, resource profile, timeout, retry policy, verifier, recovery policy, and safe
projection. The runtime persists `requested -> admitted -> running ->
succeeded_unverified -> verified` separately from denied, retryable/permanent failure,
cancel, timeout, and supersede outcomes.

Action orchestration does not replace domain authority. Grounding and plan capabilities
continue to write their existing capability/draft receipts; runner actions only read an
already-created durable execution job and never launch a process in the API transaction.
Each action receipt stores one authority kind/id/hash reference instead of copying raw
results. Current input revision, exact lease owner/generation, action generation,
idempotency key, catalog digest, policy fingerprint, and resource fingerprints fence
every durable transition.

Resource admission is deny-by-default: provider arguments cannot grant a URL, path,
command, image, environment variable, dynamic MCP server, network class, source, or
artifact outside the descriptor and server allowlist. Per-run action, retry,
verification, and actionable-recovery budgets are server-owned. A handler success is
only `succeeded_unverified`; a separate verifier must prove current capability, planning
facts/DAG, grounding citation scope, or terminal execution-job evidence before the
result becomes `verified`.

Recent terminal action receipts enter `AuthoritativeContextSnapshot` as bounded metadata:
action id/version, input/action/retry generation, lifecycle status, safe summary,
authority handle, verification status, and recovery hint. Raw arguments, command/path,
provider body, private tests/rubric, learner submission, internal exception, and secret
never enter provider context, public SSE, local export, or trace projection. A current
verified stable action key is replayed/deduplicated instead of invoking the owner again.

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

LearningTrack Home, the responsive three-column learning workspace, immutable LessonDocument reader, server-authoritative exercise Gate binding/scoring, append-only Attempt flow, module diagnostic confirmation, model code-review exercises, track-scoped spaced review, structured Tutor context references, and existing-queue execution handoff are now implemented. The reviewed production container image fleet and real-provider release smoke remain unavailable and require separate operator approval.

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
uv --directory .\aearn\services\api run python -m pytest tests/smoke/test_tutor_real_provider_smoke.py -q -m real_provider
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

The interactive dispatcher remains deny-by-default. A PostgreSQL-backed policy resolver grants only `tutor.learning-plan-draft@1.0.1` and `learning.plan.draft@1.0.0` for a current, non-terminal, non-superseded interactive `plan_drafting` run whose conversation owns an active planning session. The capability validates compact nested JSON, server-owned language/source/runtime facts and the frozen LearningPlan DAG, then appends one typed draft. Generic capability receipts contain only draft id/version/hash/status. Effects remain denied and HTTP confirmation from the plan inspector is the only track-creation action. After a draft capability succeeds, the selected Skill must return a learner-visible review message with `turn_completed`; it must not create a generic `approval` continuation for plan confirmation, so the ordinary planning Composer remains available for revision requests. The interactive provider boundary also converts an accidental `approval` decision to ordinary completion only when the exact run owns an active `plan_drafting` session; outside that scope the generic approval decision is preserved unchanged. Generic approval remains valid for unrelated gated operations. The learning context decorator appends bounded scope/session/current-draft descriptors without changing current-input pinning, adaptive budget order, usage/cache accounting or summary compaction.

The corrected Skill and exported capability schema both declare the complete opaque JSON contract. `profile_json` uses `language_id`, `goal_text`, `target_level`, `weekly_minutes`, `experience_level`, `teaching_preferences`, `pace_summary`, and `title`; each module contains typed `nodes` rather than shorthand aliases. Invalid nested input remains a typed capability denial across Psycopg transaction boundaries, records a safe session error after rollback, creates no draft, and terminal persistence emits a learner-safe retry message so a completed public-thinking stream never becomes the only visible output. A fresh Turn retry is allowed only for exact `blocked_policy/capability_denied` or `budget_exhausted/deadline_exhausted` diagnostics so a corrected catalog/Skill or a fresh finite deadline may recover the same source input without reopening unrelated policy or budget denials.

Capability result fields are bounded raw strings, so the Action adapter maps draft id/version/hash directly before constructing `plan_draft` authority; it never reuses the JSON argument decoder. Structured context-summary curation keys include exact run/input identity, preventing fresh retries with the same retired history from conflicting with another run while still deduplicating high-water and terminal triggers inside one run.

### LessonDocument authoring boundary (2026-08-11)

Lesson authoring is a separate server-owned artifact workflow, not an expansion of the generic Tutor capability payload. A durable run is created and committed before dispatch. The dispatcher claims a lease, reads only persisted registry-owned grounding, assigns short evidence handles, calls the configured primary provider through a strict JSON port, applies deterministic schema/citation/coverage/Gate quality gates, rechecks track/progress/source versions, and publishes standard + personalized documents, snapshots, assignment, and terminal run state in one final transaction.

There is no provider/model fallback and no static lesson template fallback. Provider calls happen outside long PostgreSQL transactions. Attempt receipts contain only safe provider/model/protocol/outcome/usage/hash metadata. The interactive Tutor context limit and `12 × 360` generic capability envelope are unchanged; ordinary Tutor context does not receive full Lesson blocks or source excerpts.

### Exercise Gate execution reuse boundary (2026-08-11)

Exercise Gate is a separate learning artifact workflow, not a generic Tutor capability/effect call. The API accepts a scoped Attempt and private submission, then maps execution-required work into the existing `tutor_execution_intents` / `tutor_execution_jobs` lifecycle with `source_kind=exercise_submission` and `owner_kind=exercise_attempt`. It does not create a Tutor conversation, message, run, or effect. Existing Tutor execution remains on `tutor_message` / `tutor_effect`; database one-of checks prevent a row from mixing the two ownership models.

The executor claims the same lease/launch-token job, but its trusted-input loader resolves Gate input only after matching user, Attempt, submission, exercise version, private rubric and runtime profile references. The public API never receives the trusted input or private artifacts. Terminal execution output is reduced to an immutable learner-safe Attempt result before the learning service can project Gate/mastery/progress; the executor itself never writes pass, mastery or unlock authority.

`container_verified` remains fail-closed and is not granted solely because a route exists. Public execution requires a reviewed immutable image lock and compatible health/profile evidence. `teaching_local` is development-only; `static_only` uses deterministic server evaluation with `execution_claim=not_run`; `unavailable` creates no execution job and never falls back to host subprocess, legacy runner or a second queue. This child did not build, sign, publish or approve a reviewed image fleet and did not call a real provider.


### Model code-review authoring and controlled validation (2026-08-12)

A `model_code_review` Gate may create a user/track/knowledge-scoped draft candidate from bounded
learning facts. 服务端先选择 versioned controlled template；provider 只能返回 strict
`model_review_author_candidate_v2={schema_version,title,learner_instruction,candidate_code}`，即教学
场景文案与候选代码，不能选择 `template_id`，也不能生成 requirements、tests、hidden tests、
expected outcomes、rubric、finding、matcher/proof 或 score policy。服务端随后从受控 template 与
private test DSL 构造 public requirements、private tests、expected outcomes、finding rubric、
reachability/coverage proof 和评分策略，并把完整 template identity/hash 写入 private rubric。
The candidate is not selectable until an internal proactive Tutor run invokes exact descriptor
`model-code-review.validate@1.0.0` and receives a verified `model_review_validation` authority.

The adapter stores only opaque candidate/validation IDs in Action Runtime and reuses the existing
execution intent/job queue. API and authoring workers never launch a host process or a second queue.
Parser, compile/typecheck, visible/hidden tests, finding reachability, rubric consistency, coverage
and redaction are versioned checks; validation 还要求 exact runtime id、test count、visible/hidden
顺序和 server-authored expected pass/fail outcome 全部匹配。executor 只在 claim 后读取 private DSL，
传入 sandbox 前会剥离 template test id、`candidate_expected_pass` 与 `proof_ids`。Any
missing, failed, or stale evidence prevents publication. Learner
submission remains static-only and deterministic: model-authored teaching feedback may consume only
learner-safe score evidence and cannot change score, mastery evidence or unlock.

### Track-scoped spaced review and finite ReviewSession (2026-08-12)

The active review authority is owned by `services/learning/reviews/` and
`routes/learning_track_reviews.py`; it does not reopen the removed top-level `/api/reviews`
runtime. A schedule is uniquely scoped by `user_id + track_id + knowledge_key`,
uses stable knowledge keys across plan revisions, and is seeded only from trusted
mastery evidence. Confirmed module-diagnostic skips receive a low-frequency seed.
Plan activation retains matching keys and writes explicit suspension events for
removed keys.

`GET /api/learning-tracks/{track_id}/reviews` returns the server-owned actionable
queue. Ordinary due items do not block course progress. A persisted
`critical` risk item that is a direct or transitive prerequisite of the current
node is included immediately even before its next ordinary `due_at`, and is the
only item projected as `critical_prerequisite_gate`. `review_due_count` follows
the same actionable definition: ordinary due schedules plus immediate critical
recovery Gates.

A finite `ReviewSession` freezes the active plan revision, expected track and
schedule versions, immutable exercise versions, and a bounded
`AuthoritativeContextSnapshot`. Warmup and hint receipts are append-only session
facts and never update mastery or the schedule. Each formal item creates exactly
one `Attempt(review_submit)` and may reuse static/model-review scoring or the
existing executor queue according to the server-resolved execution tier. Only
when every item has a terminal result can one finalization transaction append a
review mastery evidence row, append a schedule event, update the schedule
projection, and terminalize the session. Replays return the stored result; a
conflicting request hash or stale version fails closed.

Candidate shortage leaves the same session in recoverable `blocked` state with
`REVIEW_CANDIDATE_UNAVAILABLE`; no unvalidated fallback exercise is synthesized.
Public projections omit full submissions, private rubrics/tests, provider bodies,
execution internals, and context hashes. Local export includes bounded review
summaries only, while reset/delete and cutover inventory include all user-owned
review rows in child-to-root order.

### Final learning-agent integration audit (2026-08-12)

The final integration boundary is deterministic and repository-grounded:

- Python, JavaScript, TypeScript, and SQL each have a real-PostgreSQL fixture that creates a track, publishes a source-backed immutable LessonDocument, starts the assignment, binds a Gate, records a terminal learner-safe result, projects mastery/progress, creates a due ReviewSession, and finalizes one review evidence/schedule event.
- The same fixture proves public composition remains `unavailable` for execution-required Gates while `image-locks.json` is empty. Development-only execution is explicitly `teaching_local`; it is never promoted to `container_verified`.
- Java and HTML/CSS remain extension capabilities with runner-level tests but no claim of the four-language core end-to-end course matrix. Go and C# remain partial local managed-compiled capabilities; Rust is public `unavailable`; C++ is public `static_only`. None has a reviewed public container lock.
- Cutover now classifies every `tutor_*` table as either user-owned target state or an explicitly shared catalog/health/private-exercise table. A schema reconciliation test fails whenever a future Tutor table is not classified.
- Legacy `learning_*`, user-level Tutor plan, review, note, and Graph/runtime data are never silently converted into LearningTrack evidence. Clean-slate cutover deletes only the exact confirmed legacy scope; ordinary reset/delete clears current user-owned learning state, while feature rollback preserves stored evidence and cannot bypass the verified cutover gate.
- Planning, Review, code-review validation, and the right-side Tutor consume persisted authoritative snapshots or verified Action receipts. Execution completion and verification success remain distinct, and stale/superseded authority cannot publish an effect, mastery fact, unlock, or message.

This is local integration evidence, not a release approval, provider-quality claim, image-supply-chain approval, push, deployment, or production-data migration.


### Global thread/turn v2 cutover (2026-08-14)

The effective v2 runtime gate is the conjunction of `TUTOR_THREAD_TURN_V2_ENABLED` and the PostgreSQL singleton state `enabled`. Preparing freezes public mutations and worker claims before inventory convergence. Safe legacy waiting turns fail with a fresh-turn migration code; other cancellable active turns become ordinary interrupted projections with leases/jobs cleared. Ambiguous effects block activation. Reads remain available, the legacy continuation POST is a permanent 410 tombstone, and rollback is read-only disablement rather than legacy resurrection. Operator commands are documented in `docs/setup/tutor-thread-turn-v2-cutover.md`.


## Controlled Codex plan-drafting cutover (2026-08-18)

Harness remains the default implementation for general, learning-track, proactive, historical, and feature-off traffic. The server freezes `runtime_kind` only when a fresh TurnRun is created. A new `plan_drafting` conversation may select `codex_sidecar_v1` only from fresh shared worker readiness matching the allowlisted Runtime version plus exact `deepseek-v4-flash` / `aearn_deepseek` / `responses`; an enabled cohort with failed readiness receives safe unavailable instead of Harness fallback. Existing conversations and retry roots inherit their original Runtime.

The durable interactive job table remains the authority. Harness and Codex workers claim it with disjoint Runtime filters, and `TutorRuntimeDispatchRouter` routes only from the persisted run snapshot. The Codex dispatcher does not wrap `TutorRunLoop`: it owns the Runtime thread/turn, typed LearningPlan tool registry, lease heartbeat, steer/interrupt monitor, and durable Runtime projector. LearningPlan confirmation and LearningTrack creation stay outside Codex in the existing Aearn HTTP/domain transaction.

## 2026-08-20：Codex conversation thread、local compaction 与原始运行流

`codex_sidecar_v1` 的长期上下文边界从 run 提升为 learner conversation：每个 `TutorConversation` 最多拥有一个 active `tutor_conversation_runtime_threads` 记录和一个持久 Codex App Server thread；每个 fresh `TutorRun` 只在该 thread 内执行新的 `turn/start`。worker/App Server 重启后必须用持久 external thread identity 执行 `thread/resume`，但 external thread/turn/item identity 始终是 private correlation，不进入公共 DTO。旧 run-level binding 只有在一个 conversation 恰好对应一个 legacy thread 时才可自动采用；歧义历史创建新 thread，并用一次性 bounded learner-visible timeline + confirmed planning facts reseed，随后仍须重新调用 Aearn planning context tool。

当前 `aearn_deepseek` 只允许本地 Codex compaction。`CodexRuntimeConfig` 从同一 verified capability 派生 `model_context_window=1_000_000`、`model_max_output_tokens=384_000` 和 `model_auto_compact_token_limit=616_000`，以 `model_auto_compact_token_limit_scope="total"` 写入 isolated `CODEX_HOME`。`thread/compact/start` 与 turn 内 `contextCompaction` lifecycle 都属于 local App Server control；当前 provider 不声明、发送或回退到 remote compaction request。

Codex item stream 使用闭合 phase/channel 规则：raw `reasoning` text 进入 private owner-scoped reasoning projection；`agentMessage phase=final_answer` 进入 answer projection；`commentary` 只留下 nonpublic safe receipt；reasoning summary 保持独立内部事件，不冒充 raw reasoning。delta 先经 run input revision、lease owner/generation、Runtime connection generation、thread/turn identity 和单调 sequence fence，再写入 `tutor_runtime_text_items` 并发布版本化 `turn_output`。completed item 用完整 text/hash 原子校准；若 completed phase 把先前 provisional `final_answer` 校正为 `commentary`，服务端必须清空并 discard 该暂存 item，发布无 text 的 discard 事件。任何 turn terminal 都必须清空并 discard 剩余 streaming item，避免刷新后残留卡住状态；final answer 仍必须通过 teaching safety 后才能关联正式 Tutor message。Runtime publisher 对短时队列饱和使用有界异步背压，只有 subscriber 在等待窗口后仍未释放容量时才以 `runtime_event_backpressure_exhausted` fail closed。

planning context tool 返回 confirmed facts、missing fields、facts revision/fingerprint 和 server question catalog version。出现 `awaiting_user` 时，Aearn 还会为第一个缺失字段返回 `next_missing_fact {field_key, meaning, exact_question, wording_policy, response_authority}`；字段语义和问题文案由同一 server question catalog 派生。`language_id` 固定表示要学习的编程语言或已发布课程，不表示教学内容使用的自然语言；模型可以简短确认已知事实，但必须把 `exact_question` 逐字作为唯一问题，不得自行补充括号示例、选项或第二个问题。服务端持久 Tutor message 与 generated UI 同样复用该 question source of truth，然后创建 durable `planning_input` request 并 terminalize source turn；模型不能自定义 question key、presentation 或 catalog。typed response 写入 confirmed fact 后创建 fresh run，并 resume 同一 Codex conversation thread。PostgreSQL planning facts、typed request、LearningPlan、Queue、权限和 effect commit 继续是 Aearn authority。

该 Codex raw-runtime contract 仅替代 `codex_sidecar_v1` 对 provider-native reasoning 一律禁止公开的旧规则。Harness `tutor_public_thinking_stream_v1` 与 legacy `public_thinking_text` 继续作为兼容路径，不得把二者和 raw Runtime reasoning 混写、拼接或互相推导。

## 2026-08-21: Planning intent authority before provider execution

`PostgresPlanningFactRepository.record_input()` invokes the versioned deterministic planning resolver for accepted `plan_drafting` input. The resolver uses the exact learner message, current confirmed language, active courses, and PostgreSQL intent tags. Compatible single-language evidence becomes a confirmed fact before context reconstruction, so Harness and Codex both see `language_id` as required authority and cannot re-ask it. Direction, multiple-language, conflict, unsupported, and feature-disabled results remain request-shaping context only.

When a language request is still needed, request persistence resolves candidate course UUIDs and writes an immutable public presentation. The model supplies only the stable `question_key`; it never defines the shortlist. Response validation reads the persisted options, while the next fresh TurnRun records the learner's selected public language value through the existing typed fact path.

## 2026-08-21：Codex Runtime delta 合并与语义预算

Codex adapter 为每个 turn 建立独立 `RuntimeDeltaCoalescer`。仅连续同 `thread/turn/item/kind/channel/index/phase` 的 reasoning/final-answer delta 可合并；默认 25ms、1,024 字符或 4KB flush，任意 item/phase/summary/tool/compaction/completed/terminal 边界强制 flush。合并后的文本必须逐字等于 source delta 串联，`item/completed` 仍是最终文本校准 authority，commentary、reasoning summary 与 terminal discard 规则不变。

source sequence 与 projection sequence 分离。Runtime result、PostgreSQL text reducer、conversation SSE 与 Desktop 只按 projection sequence 工作；append-only receipt 保存安全 source range/count/hash。关闭 `CODEX_RUNTIME_DELTA_COALESCING_ENABLED` 时恢复逐 delta projection，但不会恢复 `len(events) >= 2000` 或 `runtime_event_budget_exhausted` 正常失败。

Runtime 资源限制现在是独立语义预算：100,000 raw notification runaway guard、item、tool、累计可见文本、turn time 与 pending bytes。普通日志只记录 source delta/projection/flush 数、maximum pending bytes、duration 与 safe code，不记录文本。UI/SSE gap、refresh 和 reconnect 继续通过 fresh snapshot 恢复，不 terminalize 模型 turn。

## 2026-08-23：Knowledge-scoped TeachingSession 与 closed teaching action Loop

LearningTrack learner conversation 仍是长期 history/context scope；TeachingSession 是其中一个知识点的 durable authority segment，不是新 conversation，也不改变“普通 learner message = fresh finite TurnRun”的全局模型。server 在 open/resume 时读取 active plan node、progress、唯一 track-scoped learner conversation、active Lesson assignment 与 immutable LessonDocument，冻结 session authority 并创建首个 append-only checkpoint。旧 conversation 没有 session 时保持可读，不扫描聊天正文做猜测型 backfill。

每个 teaching-scoped fresh run 额外冻结 `tutor_run_teaching_scopes`，并关联一个 exact `TutorTurnStimulus`：真实 learner message、显式 teaching control 或 server-owned domain event。control/event 不伪造 learner message、不使用 proactive origin。authority version 变化时，旧 current session 追加 `authority_pause` checkpoint 并置为 blocked，successor 通过 `predecessor_session_id` 冻结新 authority；partial unique 只允许 exact scope 同时存在一条 `active | paused` session。

Harness 为 teaching run 注入 required `TEACHING_SESSION` section，并只授权 `tutor.lesson-teaching@1.1.0`。`tutor.lesson-teaching@1.0.0` 的 manifest、instructions 与 evals 保持不可变，仅作为历史 catalog evidence。provider 先选择 exact Skill，context rebuild 后只能返回一个 strict `tutor.teaching-step-decision.v2`：closed action、exact objective/focus/source handles、closed focus resolution、一个 pause kind、2--4 个互不重复的 `teaching_moves`、显式 `learner_response_mode` 和 learner-safe public message。unknown handle/focus、extra field、missing/duplicate move、response/action 不兼容、Free Reading 越权主动控制、伪造 completion 或 next node 均在 durable commit 前 fail closed。

一次成功 Turn 在同一 PostgreSQL transaction 内 append next checkpoint、CAS session、insert `tutor_teaching_action_receipts`、写 Tutor public message、outbox/event 并 terminalize run。v2 receipt 只保存 action/focus/pause、safe handles、`teaching_moves`、`learner_response_mode`、schema/policy version、context IDs/hashes 与 public-message hash；最近四个 v2 单元以这些安全字段进入下一次 `TEACHING_SESSION`，不复制消息正文。provider unavailable、stale/superseded/lease loss 不写 checkpoint/receipt/message；provider 返回后 authority 失效的 teaching run durable cancel 为 `teaching_authority_stale`。

Aearn 根据 checkpoint/pause/runtime/request/mode/completion 与最近已提交教学单元生成 `TeachingActionShelfV1`，最多一个 primary 与三个 visible secondary；active runtime、blocking request 和普通 shelf 互斥。只有 `recommended_action_key=continue` 时才投影主操作“继续”，需要学习者回答的单元改投影 `respond_in_composer`，不存在真实 descriptor 时 shelf 为空。Free Reading 普通问题只产生 reactive finite answer，只有显式 `escalate_guided` 才切 Guided 并 admission 一个新 Turn。completed progress 只接受 `summarize_progress + completion_pause`，不自动改 workspace knowledge key；只有显式 `enter_next_knowledge` 才重新验证最新 roadmap/availability、复用同一 conversation、推进 track pointer并 admission 下一 session 的 first-unit run。

Harness 在 effect commit、waiting result 和 terminal result 前重新验证 current session/checkpoint、track/active plan/progress、active assignment/document 与 stimulus scope。conversation snapshot/API additive 返回 bounded session/checkpoint/Action Shelf metadata；trace/export 不包含 raw checkpoint/authority JSON、prompt、reasoning、provider body、完整题目/提交、hidden test/rubric、command/path 或 secrets。五张 user-owned teaching 表全部进入 cutover exhaustive inventory 与 local export/reset/delete；删除 action receipt 后再按 run scope/stimulus/checkpoint/session 清理，deferred `NO ACTION` lineage FK 保证同一事务 child-to-root reset 与 bootstrap twice 可重复。

## 2026-08-23：三时间尺度恢复、summary precedence 与 domain-event Turn

长期 track conversation、知识点 TeachingSession 与单次 TurnRun 继续是三个不同时间尺度。owner domain event 只触发一个 fresh interactive Turn；每个 Turn提交一个 closed teaching action 后必须停顿。authority 变化时旧 session 写 `authority_pause` 并 blocked，successor 冻结新 progress/assignment/document；重复事件复用既有 run，stale source 被忽略。

教学 context 优先级为 current input/typed stimulus → current session compact authority → exact references → bounded recent current-session messages → current checkpoint-backed summary → 至多一个 exact predecessor summary → generic conversation summary/memory/activity。`teaching_control | domain_event` 不伪造 current learner input，但 context loader 仍按 frozen `teaching_session_id + session_version + scope chronology` 读取当前 run 之前的 same-session learner-visible messages；legacy group、其他 session/knowledge 与未来消息不进入该窗口。`continue/resume` 必须在最新教学消息之后推进，不能仅凭相同 objective/checkpoint 重启或近义复述已讲解内容；`change_example`、remediation 与 summary authority 例外。active/suspended focus 中的 exact message handle、unresolved question source message 与当前 session 最新 learner input进入 compaction protected set。summary source hash、checkpoint cursor或 authority snapshot失配时 provider 前 fail closed，不允许旧 summary 覆盖最新纠正或完成事实。

## 2026-08-27：Teaching Skill v1.1 与教学单元推进门

exact `tutor.lesson-teaching@1.1.0` 使用 `tutor.teaching-step-decision.v2`。每个教学单元必须选择 2--4 个互不重复的 closed `teaching_moves`：`targeted_explanation`、`worked_example`、`counterexample`、`misconception_contrast`、`guided_derivation`、`prediction`、`error_detection`、`micro_transfer` 或 `learner_feedback`。`learner_response_mode=composer` 只允许搭配 `check_understanding | wait_for_input`，并且必须包含至少一个诊断性 move；`none` 不允许这两个 action。`change_example` 必须实际包含 `worked_example | counterexample`。

下一次 teaching run 的 required projection 包含最近四个已提交 v2 单元的 action、focus、moves、response mode、public-message hash 与 schema version。投影主动删除重复 summary/UI 字段并保持既有 1,200 字符 required-section 上限，不通过提高全局 context budget 掩盖溢出。`continue` 若与最近单元 public-message hash 完全相同，或 objective/focus/moves/response mode 形成相同策略签名，decision gate 以 `teaching_unit_not_advanced` fail closed；改变例子、诊断策略、迁移练习或学习者反馈等真实推进可以继续提交。

checkpoint reducer 先尊重 session/evidence/completion/authority 状态，再解释 response mode。需要学习者作答时推荐 `respond_in_composer`；只有明确推荐继续才显示 Continue。这个决策只改变 server-owned projection，不增加新的客户端状态机、provider 控件或自动 next run。

## 2026-09-01：Artifact-aware teaching、clarification branch 与 continuation arbiter

新 teaching run exact 选择 `tutor.lesson-teaching@1.2.0` 与 strict decision v3。server 在 provider 前从 current TeachingSession/checkpoint、最新 published Learning Item、capability set、Practice materialization、runtime readiness 和 feature flags 构建 bounded `teaching_artifact_candidates_v1`；provider 只能返回 `none/none/null`、`composer/text_answer/null` 或 `artifact/<closed intent>/li:<sha256>` 三类 exact pairing，不能发明题目、owner、payload 或 runtime identity。`TUTOR_ARTIFACT_TEACHING_MODE_ENABLED` 默认关闭；关闭时候选为空且 Artifact decision fail closed，历史 Artifact/Teaching read 不受影响。

合法 Artifact teaching decision 在一个 caller-owned PostgreSQL transaction 内提交 Tutor message、next checkpoint/session CAS、`teaching_action_receipt_v3`、Learning Artifact、Artifact event、conversation `item_added` 与 source Turn terminalization。materializer 在 commit 前重新验证 publication state/version、public content hash、capability、Practice/runtime 与全部 session/track/progress/assignment fence；任一变化或 event append 失败都会回滚所有 public write。Artifact facade 不创建 Attempt、score、Gate/Review completion、mastery 或 progress authority。

blocking Artifact 等待期间的普通 learner message 仍创建 fresh finite Turn，但额外绑定一条 durable depth-one clarification branch。branch anchor 固定 Artifact、TeachingSession、checkpoint lineage 与 explicit item membership；nested branch、跨 scope 或 stale ancestry fail closed。response disposition 只有 `answer_and_refocus | offer_switch | confirmed_switch`；topic switch 必须先 offer 再接受 typed confirmation。hint/direct answer 必须携带同 scope 的 authoritative Hint/Teaching receipt，不能从自由文本推断 assistance。

Artifact action/event、static timer 与 background work 只追加 durable continuation intent，不直接调用 provider。single-turn arbiter 固定优先级为 learner message > explicit Artifact action > expected interactive event > static display timer > background continuation；active foreground run、pending learner input 或 active branch 会阻止 automatic continuation，timer/background 只允许 Guided mode。claim generation、lease、authority version 与 checkpoint ancestry共同保证竞争 claimant 最多 materialize 一条 mainline Turn；branch resolved 后 result continuation 才回到 mainline。存在 branch history 的 reconnect 使用 additive snapshot v5；v3/v4 conversation 兼容保持不变。
