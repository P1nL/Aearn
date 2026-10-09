# Tutor Harness Runtime Architecture

**Status:** Current runtime contract as of 2026-09-02.
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
  case-sensitive value `deepseek-flash`; its normalized endpoint is
  `/responses`, with `input`, optional `instructions`, `stream=true`, and a
  bounded Tutor-decision output budget. Official-compatible operation remains
  `text.format=json_object`; `TUTOR_DEEPSEEK_RESPONSES_JSON_SCHEMA_ENABLED=true`
  is an explicit opt-in only for a verified compatible gateway. The physical
  The physical DeepSeek Flash context remains `1_000_000`. Ordinary Aearn
  provider calls admit at most `131_072` input tokens and `61_440` output
  tokens; Tutor's internal request-budget envelope is therefore `192_512`, not
  a replacement physical model window. The narrow decision task defaults to
  `16_384` output tokens and does not inherit the 60K hard cap.
  The first attempt keeps the provider's configured/default thinking behavior; a
  repair attempt sends `reasoning.effort=none` by default so replacement behaves
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
policy versions. The exact `deepseek-flash` registry entry uses the verified
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
32-byte base64 key is mandatory, supplied by `KEY_BASE64` or an external
`TUTOR_PROVIDER_DEBUG_CAPTURE_KEY_FILE` (direct value takes precedence). Each attempt buffers at most
`TUTOR_PROVIDER_DEBUG_CAPTURE_MAX_BYTES`, accepted attempts zero/discard the
buffer, and rejected attempts write an AES-GCM artifact under the configured
local directory with a random 96-bit nonce and authenticated safe metadata.
Artifacts are never database rows or API fields, use a 24-hour default retention,
and are pruned only inside the configured directory. A capture/configuration
failure never exposes the body or changes the learner-safe terminal projection.

Operational logs may expose paths verified against the generated provider schema,
schema-owned expected enum values and rule guidance, never rejected values or raw
Pydantic messages. Unknown path segments remain hashed. Each rejected-attempt log
and encrypted artifact identifies `(run_id, input_revision, decision_iteration,
attempt)`; `decision_iteration` is the same `model_call_count + 1` used by durable
attempt receipts. Logs link a saved capture by opaque `artifact_id` and distinguish
saved/empty/not_captured/failed, with truncation and byte counts. Artifact IDs stay
out of public API/SSE. The local `provider_debug_cli` lists metadata and requires
`show <id> --body` to decrypt content; it never writes plaintext files. See the
local diagnostic commands in the development environment guide.

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

The interactive dispatcher remains deny-by-default. A PostgreSQL-backed policy resolver grants only `tutor.learning-plan-draft@1.0.2` and `learning.plan.draft@1.0.0` for a current, non-terminal, non-superseded interactive `plan_drafting` run whose conversation owns an active planning session. The capability validates compact nested JSON, server-owned language/source/runtime facts and the frozen LearningPlan DAG, then appends one typed draft. Generic capability receipts contain only draft id/version/hash/status. Effects remain denied and HTTP confirmation from the plan inspector is the only track-creation action. After a draft capability succeeds, the selected Skill must return a learner-visible review message with `turn_completed`; it must not create a generic `approval` continuation for plan confirmation, so the ordinary planning Composer remains available for revision requests. The interactive provider boundary also converts an accidental `approval` decision to ordinary completion only when the exact run owns an active `plan_drafting` session; outside that scope the generic approval decision is preserved unchanged. Generic approval remains valid for unrelated gated operations. The learning context decorator appends bounded scope/session/current-draft descriptors without changing current-input pinning, adaptive budget order, usage/cache accounting or summary compaction.

The corrected Skill and exported capability schema both declare the complete opaque JSON contract. `profile_json` uses `language_id`, `goal_text`, `target_level`, `weekly_minutes`, `experience_level`, `teaching_preferences`, `pace_summary`, and `title`; each module contains typed `nodes` rather than shorthand aliases. Invalid nested input remains a typed capability denial across Psycopg transaction boundaries, records a safe session error after rollback, creates no draft, and terminal persistence emits a learner-safe retry message so a completed public-thinking stream never becomes the only visible output. A fresh Turn retry is allowed only for exact `blocked_policy/capability_denied` or `budget_exhausted/deadline_exhausted` diagnostics so a corrected catalog/Skill or a fresh finite deadline may recover the same source input without reopening unrelated policy or budget denials.

Capability result fields are bounded raw strings, so the Action adapter maps draft id/version/hash directly before constructing `plan_draft` authority; it never reuses the JSON argument decoder. Structured context-summary curation keys include exact run/input identity, preventing fresh retries with the same retired history from conflicting with another run while still deduplicating high-water and terminal triggers inside one run.

After a server-owned executed-action receipt verifies `learning.plan.draft` with `plan_draft` authority, the interactive context removes only that consumed capability schema while retaining the selected Skill and receipt. The provider no longer receives conflicting instructions to draft again. A duplicate request from stale context produces `plan_draft_already_verified` and a bounded completion repair requiring `turn_completed`, not another profile/module payload. This does not force a terminal state or alter historical failed runs. Active drafting semantic repairs obey the trusted selected capability version's raw plan-string bound; additional transport space is for outer JSON escaping only.

For DeepSeek, a strictly verified same-revision plan-save receipt with a nonempty authority ID makes only the acknowledgement request non-reasoning (`thinking_mode="disabled"`, mapped by the existing Responses transport to `reasoning.effort="none"`). Selection/draft requests retain normal thinking, and the formal input/output limits are unchanged. The actual model must still return a valid completion message; the server does not manufacture a successful terminal or treat an incomplete response as completed.

Pure CompactPlanProfile/Module validation is reused before paid material-semantic review and capability execution. Invalid field shape or length enters the same bounded provider repair with allowlisted paths, observed types/counts and bounds derived from the actual local schemas; candidate values never enter diagnostics. Domain limits such as `pace_summary`240 remain unchanged, and the handler still performs final server-fact, goal and current-authority validation. Already-verified repeated draft actions take the completion-repair path before even parsing an oversized repeated payload.

### LessonDocument authoring boundary (2026-08-11)

Lesson authoring is a separate server-owned artifact workflow, not an expansion of the generic Tutor capability payload. A durable run is created and committed before dispatch. The dispatcher claims a lease, reads only persisted registry-owned grounding, assigns short evidence handles, calls the configured primary provider through a strict JSON port, applies deterministic schema/citation/coverage/Gate quality gates, rechecks track/progress/source versions, and publishes standard + personalized documents, snapshots, assignment, and terminal run state in one final transaction.

There is no provider/model fallback and no static lesson template fallback. Provider calls happen outside long PostgreSQL transactions. Attempt receipts contain only safe provider/model/protocol/outcome/usage/hash metadata. The generic capability envelope remains at 12 fields with a 360-character serialized-value bound; ordinary Tutor context does not receive full Lesson blocks or source excerpts. Legacy `learning.plan.draft@1.0.0` JSON-string fields remain at360 raw characters and2162 outer-escaped characters. Explicit internal D material planning selects the new Skill and capability1.1.0: `LearningPlanDraftCapabilityInputV110` permits1024 raw and6146 escaped characters for profile/module JSON strings only, with action input bytes capped65536 instead of legacy16384. Version comes from complete hash-valid selected Skill and exact server capability schema, not model hints; dispatch rechecks it. Ordinary planning remains on Skill1.0.3/capability1.0.0 with unchanged published hashes. Neither version broadens other capabilities/results/effects, coerces objects into strings, truncates goals, or skips domain/semantic/current-source validation.

For normal internal D verification, the operator imports a strict allowlisted snapshot of the effective runtime Settings; it must not silently substitute a 4096-output/8192-input boundary profile or disable first-call thinking. Explicit boundary tests are separately labelled. Selected catalog Skill instructions must retain verified identity and instruction digest and enter mandatory context intact; insufficient budget fails before provider IO. Capability schemas are atomic JSON, not prose to clip. Safe repair diagnostics retain only closed type/length/count metadata and allowlisted paths; logs and repair prompts must not include rejected values. A successful protocol parse is distinct from plan business validation, material review, and persisted bindings.

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

Harness remains the default implementation for general, learning-track, proactive, historical, and feature-off traffic. The server freezes `runtime_kind` only when a fresh TurnRun is created. A new `plan_drafting` conversation may select `codex_sidecar_v1` only from fresh shared worker readiness matching the allowlisted Runtime version plus exact `deepseek-flash` / `aearn_deepseek` / `responses`; an enabled cohort with failed readiness receives safe unavailable instead of Harness fallback. Existing conversations and retry roots inherit their original Runtime.

The durable interactive job table remains the authority. Harness and Codex workers claim it with disjoint Runtime filters, and `TutorRuntimeDispatchRouter` routes only from the persisted run snapshot. The Codex dispatcher does not wrap `TutorRunLoop`: it owns the Runtime thread/turn, typed LearningPlan tool registry, lease heartbeat, steer/interrupt monitor, and durable Runtime projector. LearningPlan confirmation and LearningTrack creation stay outside Codex in the existing Aearn HTTP/domain transaction.

## 2026-08-20：Codex conversation thread、local compaction 与原始运行流

`codex_sidecar_v1` 的长期上下文边界从 run 提升为 learner conversation：每个 `TutorConversation` 最多拥有一个 active `tutor_conversation_runtime_threads` 记录和一个持久 Codex App Server thread；每个 fresh `TutorRun` 只在该 thread 内执行新的 `turn/start`。worker/App Server 重启后必须用持久 external thread identity 执行 `thread/resume`，但 external thread/turn/item identity 始终是 private correlation，不进入公共 DTO。旧 run-level binding 只有在一个 conversation 恰好对应一个 legacy thread 时才可自动采用；歧义历史创建新 thread，并用一次性 bounded learner-visible timeline + confirmed planning facts reseed，随后仍须重新调用 Aearn planning context tool。

当前 `aearn_deepseek` 只允许本地 Codex compaction。`CodexRuntimeConfig` 写入 `model_context_window=1_000_000`、`model_max_output_tokens=61_440` 和 `model_auto_compact_token_limit=950_000`，并使用 `model_auto_compact_token_limit_scope="total"`。Codex 持久线程不受普通 LLM 客户端 128K 单次输入限制；达到 950K 累计上下文时先执行本地压缩。950K 到物理窗口只余 50K，因此 60K 是允许的最大输出而非临界点上的保证输出。`thread/compact/start` 与 turn 内 `contextCompaction` lifecycle 都属于 local App Server control，当前 provider 不声明、发送或回退到 remote compaction request。

Codex item stream 使用闭合 phase/channel 规则：raw `reasoning` text 进入 private owner-scoped reasoning projection；`agentMessage phase=final_answer` 进入 answer projection；`commentary` 只留下 nonpublic safe receipt；reasoning summary 保持独立内部事件，不冒充 raw reasoning。delta 先经 run input revision、lease owner/generation、Runtime connection generation、thread/turn identity 和单调 sequence fence，再写入 `tutor_runtime_text_items` 并发布版本化 `turn_output`。completed item 用完整 text/hash 原子校准；若 completed phase 把先前 provisional `final_answer` 校正为 `commentary`，服务端必须清空并 discard 该暂存 item，发布无 text 的 discard 事件。任何 turn terminal 都必须清空并 discard 剩余 streaming item，避免刷新后残留卡住状态；final answer 仍必须通过 teaching safety 后才能关联正式 Tutor message。Runtime publisher 对短时队列饱和使用有界异步背压，只有 subscriber 在等待窗口后仍未释放容量时才以 `runtime_event_backpressure_exhausted` fail closed。

planning context tool 返回 confirmed facts、missing fields、facts revision/fingerprint 和 server question catalog version。出现 `awaiting_user` 时，Aearn 还会返回 `next_missing_fact {field_key, meaning, exact_question, wording_policy, response_authority}`；当 `language_id` 缺失时 additive 返回 bounded `language_candidates`，只含 canonical language、course title、level、capability state 与 execution family。Codex 先执行一次不含 action 的只读调用，再立即执行一次包含唯一 closed `direction_action` 的调用；只有 `continue_mainline` 可同时携带 strict `planning-intent-hint-v2` 的 1..3 个当前 language IDs，证据不足则选择 `clarify_direction`。服务端 gate 仅从 accepted marker 构造 exact fact question、bounded answer/refocus、固定方向澄清或 append-only switch reopen；缺失/非法 marker 不得回退到 primed `next_missing_fact`。typed response 创建 fresh run 并 resume 同一 Codex conversation thread。PostgreSQL planning facts、typed request、LearningPlan、Queue、权限和 effect commit 继续是 Aearn authority。

该 Codex raw-runtime contract 仅替代 `codex_sidecar_v1` 对 provider-native reasoning 一律禁止公开的旧规则。Harness `tutor_public_thinking_stream_v1` 与 legacy `public_thinking_text` 继续作为兼容路径，不得把二者和 raw Runtime reasoning 混写、拼接或互相推导。

## 2026-09-03: Explicit language authority and semantic shortlist confirmation

`PostgresPlanningFactRepository.record_input()` invokes `planning-language-intent-v2` for accepted `plan_drafting` input. The resolver uses the exact learner message, current confirmed language, active courses/capabilities, deterministic PostgreSQL intent tags, and an optional validated semantic hint. A single explicit active language remains the only auto-confirm path. Deterministic direction/conflict results may shape a shortlist; semantic hints never append facts and are limited to 1..3 active canonical values.

Harness exposes a compact server candidate descriptor in planning context and accepts the v2 hint only on `planning_input + language_id`. The decision gate rechecks current input revision and active candidates before recording the question. Codex uses its typed planning-context tool rather than the Harness provider action: after the initial read, exactly one `direction_action` is required, and the same hint may accompany only `continue_mainline`. The dispatcher converts only that validated state into the existing durable request, while missing/invalid actions use the fixed direction clarification and non-direction Runtime failures remain failures. Persistence performs the final unsafe-boundary re-resolution for both paths.

Enabled ambiguity, invalid/stale hints, and no active semantic match cannot construct a language selector or widen to the catalog; they require clarification or fail closed. Feature-off is the only full-catalog rollback. Once persisted, the exact presentation and ordering remain immutable, and the next fresh TurnRun records only the learner-selected public value from that stored presentation.

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

下一次 teaching run 的 required projection 包含最近四个已提交 v2/v3 单元的 action、focus、moves、response mode、public-message hash 与 schema version。投影主动删除重复 summary/UI 字段并保持既有 1,200 字符 required-section 上限，不通过提高全局 context budget 掩盖溢出。`continue` 若与最近单元 public-message hash 完全相同，decision gate 以 `teaching_unit_not_advanced` fail closed。普通 learner Continue 的同 focus/moves/response mode 策略签名重复也拒绝；只有 owner 通过 consumed intent、Artifact event 与 immutable response receipt 的 exact join 证明新知识检查结果时，反馈可以复用同一策略签名。此 server-only 证据标记不能由模型或 learner control 提供，不豁免 exact text、source handle、completion pause 或正式 Gate 规则。

Teaching request 保留完整通用协议规则与 canonical teaching-step example，但不再重复附带该上下文不允许的普通 direct-reply / generic wait-for-input examples；非 teaching request 仍包含完整普通示例。此去重不截断 required authority/question/receipt，也不提高输入硬上限、输出预留或物理上下文容量。若完整 required request 仍超限，必须在调用 provider 前以 `TUTOR_CONTEXT_REQUIRED_OVERFLOW` 失败；无公开评价消息的早期失败不发布结果工件，也不能被二次发布错误改写成 `teaching_authority_stale`。

checkpoint reducer 先尊重 session/evidence/completion/authority 状态，再解释 response mode。需要学习者作答时推荐 `respond_in_composer`；只有明确推荐继续才显示 Continue。这个决策只改变 server-owned projection，不增加新的客户端状态机、provider 控件或自动 next run。

## 2026-09-01：Artifact-aware teaching、clarification branch 与 continuation arbiter

新 teaching run exact 选择 `tutor.lesson-teaching@1.2.0` 与 strict decision v3。server 在 provider 前从 current TeachingSession/checkpoint、最新 published Learning Item、capability set、Practice materialization、runtime readiness 和 feature flags 构建 bounded `teaching_artifact_candidates_v1`；provider 只能返回 `none/none/null`、`composer/text_answer/null` 或 `artifact/<closed intent>/li:<sha256>` 三类 exact pairing，不能发明题目、owner、payload 或 runtime identity。`TUTOR_ARTIFACT_TEACHING_MODE_ENABLED` 默认关闭；关闭时候选为空且 Artifact decision fail closed，历史 Artifact/Teaching read 不受影响。

合法 Artifact teaching decision 在一个 caller-owned PostgreSQL transaction 内提交 Tutor message、next checkpoint/session CAS、`teaching_action_receipt_v3`、Learning Artifact、Artifact event、conversation `item_added` 与 source Turn terminalization。materializer 在 commit 前重新验证 publication state/version、public content hash、capability、Practice/runtime 与全部 session/track/progress/assignment fence；任一变化或 event append 失败都会回滚所有 public write。Artifact facade 不创建 Attempt、score、Gate/Review completion、mastery 或 progress authority。

blocking Artifact 等待期间的普通 learner message 仍创建 fresh finite Turn，但额外绑定一条 durable depth-one clarification branch。branch anchor 固定 Artifact、TeachingSession、checkpoint lineage 与 explicit item membership；nested branch、跨 scope 或 stale ancestry fail closed。response disposition 只有 `answer_and_refocus | offer_switch | confirmed_switch`；topic switch 必须先 offer 再接受 typed confirmation。hint/direct answer 必须携带同 scope 的 authoritative Hint/Teaching receipt，不能从自由文本推断 assistance。

Artifact action/event、static timer 与 background work 只追加 durable continuation intent，不直接调用 provider。single-turn arbiter 固定优先级为 learner message > explicit Artifact action > expected interactive event > static display timer > background continuation；active foreground run、pending learner input 或 active branch 会阻止 automatic continuation，timer/background 只允许 Guided mode。claim generation、lease、authority version 与 checkpoint ancestry共同保证竞争 claimant 最多 materialize 一条 mainline Turn；branch resolved 后 result continuation 才回到 mainline。存在 branch history 的 reconnect 使用 additive snapshot v5；v3/v4 conversation 兼容保持不变。


## 2026-09-02：Conversation-native model review v2

Published model-review Learning Items now materialize into an additive conversation Artifact rather than
restoring or bypassing the existing Lesson Gate/Review runtime. The server converts the immutable published
code into a deterministic `model_code_review_artifact_v2` code/diff target with stable hashes, hunks, sides,
and line keys. The Desktop is a read-only Monaco presenter and structured-finding editor; it does not execute
code or own scoring.

`complete_review` is handled by the Learning Item owner adapter under the current TeachingSession and
publication fences. The service validates exact presentation/hunk/range identity, upgrades the existing private
v1 rubric into the closed v2 taxonomy, runs the deterministic server scorer, writes one immutable private
submission receipt, and completes the Artifact without creating an Attempt or writing mastery/progress. A
failed result requires a distinct published unused D(n-1)/D(n) remediation with smaller scope/lower difficulty;
missing authority rolls back the complete action.

One exact Artifact-event/receipt continuation admits a new teaching Turn. Its context contains only
`reason_code=model_review_evaluation`, the source Artifact handle, a bounded safe evaluation, and at most the
persisted remediation handle. Provider output can explain the already-saved result but cannot change score,
outcome, successor, receipt, Gate, Review, mastery, or progress. Full submission, private rubric/tests/proofs,
and provider internals remain absent from API/SSE/Desktop/context/export.

## 2026-09-02：Conversation-native SQL workspace

Published structured SQL Learning Items materialize into `sql_workspace_v2` Artifacts. The public descriptor
contains only SQLite teaching schema and one public dataset; private visible/hidden test cases retain independent
datasets and exact expectations. The Learning Item owner adapter executes no runner under the Artifact lock: it
only admits one exact pending Attempt. After commit, the route observer creates a fresh in-memory SQLite database
for each dataset, applies read-only authorizer/resource limits, preserves the public query columns/rows, redacts
hidden identities/values, and finalizes the same Attempt through the existing scorer.

The standard execution-result projector remains the only Artifact result path. Passing every test completes the
SQL source directly; any runtime/test failure keeps it editable, creates one immutable result Artifact, and admits
one result-evaluation continuation. Neither the local runner nor the Tutor model can create a Gate, override score,
write mastery/progress, expose private datasets, connect to Aearn PostgreSQL, or claim container verification.
Desktop owns only draft/view/copy/stale state and submits the latest query on explicit Run.


## 2026-09-02：Tutor Conversation Learning Artifact platform final composition

The active runtime has one server-authoritative Learning Artifact protocol rather than per-widget authorities. tutor_learning_artifact_v1 owns stable public identity, state/version, a closed presentation/action union, safe source references, an optional Attempt summary, and branch summary. Gate, Review, Attempt, TeachingSession, mastery/progress, and Learning Item publication remain their existing owners. Artifact routes are facades over those owners; Desktop local state never changes an outcome, score, publication state, continuation priority, or progress.

The current closed presentation matrix is exercise_workspace_v1, browser_preview_v1, test_result_v1, knowledge_check_v1, model_code_review_v1/v2, sql_workspace_v1/v2, demonstration_v1/v2, and source_inspector_v1. Artifact actions are request_hint, request_direct_answer, run, respond, complete_review, cancel, acknowledge_demo_event, and complete_demo. TutorPublicItem includes artifact; conversation events use tutor_conversation_event_v3; backend snapshots read v3/v4/v5 and Desktop retains v2-v5 compatibility. Large detail stays behind scoped reads; SSE carries stable item references and bounded safe deltas.

Published Learning Item handles are the only online candidate source. The two write/admission gates TUTOR_LEARNING_ARTIFACTS_ENABLED and TUTOR_ARTIFACT_TEACHING_MODE_ENABLED, plus the offline review gate LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED, default false. When admission is off, candidate projection is empty and an Artifact interaction decision fails before a public Tutor message; existing rows remain readable. Rollback disables candidate/admission first, then Desktop/Preview presentation, while retaining additive history and never performing a destructive down migration.

HTML editing uses a process-local Monaco draft and an app-owned isolated Preview; live Preview is non-authoritative and explicit Run alone creates an Attempt. Terminal execution, knowledge, review, SQL, and demonstration evidence enters exactly one existing owner/result/continuation path. A blocking Artifact can anchor only a depth-one clarification branch; the arbiter keeps learner messages above explicit actions, expected events, timers, and background continuations. Exact Lesson sources are resolved by user/conversation/track/document/version/block/hash and displayed in the isolated right drawer without text search, conversation scroll, or component remount.

Public API/SSE/Desktop/export/readiness evidence excludes complete submissions, private rubric/tests/reference answers, hidden SQL data, provider body/reasoning, commands, paths, container identity, credentials, and secrets. Local fake-provider, SQLite, browser, WebView2, and empty-image-lock evidence is engineering verification only, not provider quality, production sandbox, image, deployment, or release approval.

## 2026-09-04: Codex planning direction candidate, gate, and receipt

Codex plan drafting separates direction judgment from planning-fact authority. After one read-only planning-context call, the model must submit exactly one internal closed direction action. The server validates that result and maps it to the existing exact planning question, a bounded answer/refocus message, a fixed direction clarification, or the existing four-field append-only switch reopen. Missing/invalid direction resolution never falls through to the primed old `next_missing_fact`. Since the 2026-09-08 repair, budget/time/fatal Runtime failures remain visible failures rather than being misrepresented as semantic ambiguity; genuine direction clarification retains its existing server mapping.

Primed waiting-for-user turns use low effort and 45 seconds with separate limits of 2,000 message characters and 16,000 reasoning characters; the aggregate hard ceiling remains unchanged. One wrong-order tool call can use the existing single repair allowance, with at most three actual calls but only one accepted direction action. Budget, timeout, fatal tool and cancellation cleanup fence callbacks and require bounded interrupt plus matching terminal confirmation; ACK alone is insufficient, and unconfirmed stop closes the owned runtime. Complete-fact draft turns retain the normal quality profile. Successful mapped postconditions append one closed, idempotent `planning_direction_resolved` receipt in `tutor_run_events` without a migration. The receipt is internal and contains hashes/closed metadata only. Public snapshot/SSE/Desktop contracts gain no direction field. Raw Codex reasoning remains owner-visible through Runtime output, snapshot/history/SSE, and Desktop `think`; commentary, reasoning summary, and unknown channels remain excluded. Harness plan drafting continues to select immutable `tutor.learning-plan-draft@1.0.3`, with 1.0.2 and earlier versions unchanged.


## 2026-09-23：RAG v2 内部检索基础（尚未接入公开消费者）

`retrieval_contracts.py`、`retrieval_planner.py`、`hybrid_retrieval.py` 与 `coverage.py`
增加独立的 exact-scope 检索与资料覆盖合同，不替换当前 `grounding.retrieve` owner、Lesson/Tutor
读取或旧 `grounding_chunks` 检索，也不新增 HTTP、后台任务、维护入口或 provider。
确定性 fixture 身份策略提取为中性只读 `corpus_fixture_policy.py`；原 `corpus_fixtures.py` 保持兼容
重导出，fixture 内容和哈希不变，检索层不依赖 operator 入口模块。

内部请求固定 Subject/version、active-or-exact corpus selector、required/optional facets、stage 和
named budget profile；active selector 在开始时解析为 exact published 身份。计划先解析允许来源、trust
与 facet 范围，再通过 PostgreSQL 的存储 tsvector 做带 LIMIT 的全文检索，不能载入所有语言片段后
在 Python 排序。框架缺口不能由基础语言材料静默补齐。

stage 支持 plan_preflight、lesson_authoring、tutor_focus、practice、review；standard/compact
预算由服务端定义，随必要 facet 复杂度变化，而不是把固定 top_k 当覆盖证明。选中的证据同时受字符、
估算 token 和片段数上限约束。覆盖报告区分 satisfied、partial、insufficient、unavailable，并保留
缺失 facet、来源多样性、trust、版本/新鲜度、预算与封闭原因码。资料覆盖不等于学习者掌握或 Gate 通过。
当前用量按所选证据正文统计，estimated tokens 采用保守的 UTF-8 字节上界，不是 provider 实际 usage；
未来消费者组装引用元数据、system 和其他上下文时仍须另做完整 prompt 预算。

可选 embedding 默认为 disabled；本阶段只有 deterministic fake adapter 与明确 synthetic 的
server-owned receipt/config，绑定 exact corpus/content/registry 哈希。候选必须重新从 PostgreSQL
精确范围加载并核对哈希、模型、维度和归一化标识；不合格或不可用时降级到 FTS，不能凭相似度覆盖缺失
facet。本仓库此阶段没有真实 embedding 索引回执或 pgvector 部署，fake 不能冒充生产索引。

当前可验证的是已发布 synthetic fixture corpus；unsupported policy、错误版本/哈希、过期或退役
语料关闭准入。内部结果保留 fixture 身份及稳定 request/plan/result/report 哈希；尚未实现的真实来源
授权与消费者发布不能从这些工程回执推导。后续 adapter 必须单独完成治理与兼容验收后才能接入公开路径。

## 2026-09-23：RAG 计划预检与迁移投影（阶段 I）

`plan_coverage.py` 与 `plan_migration.py` 提供内部 shadow 预检及不可变修复提案：按精确 Subject/version、corpus coverage、Lesson/评估能力声明及已发布 Learning Item 事实判定节点，不接入公开计划确认、学习轨道激活、worker、启动脚本或 Desktop。

- 每个节点保留 supported / partial / insufficient / unavailable 差异；核心目标缺口阻断，不能用删除核心节点或普通 Python 替换 LangChain 来伪造通过。
- 现有学习轨道只读其 active immutable revision；提案绑定 predecessor、原计划哈希、节点级差异、源/能力事实和策略版本。重复请求产生稳定投影，过期身份关闭。
- 当前交付是未持久化、未确认、不可激活的提案投影，不是新增 successor revision；不改变 active plan、学习进度、assignment 或既有 Lesson 失败记录。
- 检索仅由显式内部依赖注入调用；默认关闭的适配器不构成公开发布开关。fixture corpus 和静态运行能力声明不是真实资料覆盖、健康 sandbox、教学完成或掌握证据。
- 实际权限、事务及测试边界见 `.trellis/spec/backend/plan-preflight-migration.md`；生产真实源、公开迁移与完整学习闭环仍属于后续阶段。

## RAG 2.0 阶段 I：内部 shadow 集成边界

共享corpus authority、精确检索与计划预检之外，阶段I只增加默认关闭的内部Lesson/Tutor引用形状适配与确定性演示场景。适配输出不是公开DTO或可持久化来源权限：合成fixture、fixture_only生态、candidate/retired语料均不能借兼容形状进入学习者可见状态；不把v2 chunk身份伪装成v1 `grounding_chunks` 行。

四个route Subject仍为shadow，六个生态仍为fixture_only。active fixture corpus仅表示operator指针，不代表课程公开、Lesson可交付或runtime健康。没有新公开route、计划确认拦截、worker schedule或Desktop管理入口；既有Lesson、Tutor及citation链保持原实现。

[架构讲解与可重复离线演示](rag-v2-interview-guide.md)是面试/工程说明，不替代本文和验收计划。真实抓取、真实embedding、来源证据绑定及逐scope消费者启用仍属于后续单独验收。


## 2026-09-27 RAG D 内部规划材料反馈接缝

D以 `build_internal_material_planning_dispatcher` 在现有TutorInteractiveRunDispatcher上做明确内部注入。现有 `rag_evidence_consumer_enabled`、server opt-in及受信RequirementResolver/EvidenceSelection依赖缺一不接入；旧公开factory、DTO、v1 hash和历史active plan不变。模型与网络许可不隐式打开公开consumer。

内部流程：当前草案→服务端逐节点/用途需求→实际来源/缺口结果→持久认领到指定新planning run/revision→安全反馈context→既有Skill选择/能力调用协议→保留核心目标与前置关系的新稿→新scope重新selection/授权→持久冻结。旧handle不能直接批准新稿，源/版本/用途不能由模型自报。source/document handles等安全有界元数据可进入反馈，网页指令、全文和私密数据不进入该投影。

模型调用继续在数据库事务外。内部材料操作仅在IDLE边界暂切短事务并恢复，final current check/fence不能另开连接或绕过C隔离guard。发布fence只证明该事务核验点，真实题库发布/供题仍由E及owner接入并重验，评分缺受信claim/执行resolver时拒绝。

具体可执行合同与正反例见 `.trellis/spec/backend/grounding-plan-material-consumption.md`；测试/真实证据分层见D任务记录。本节描述代码接缝，不宣称真实provider、业务库或公开消费者已验收。

追加语义检查：D材料驱动的修订候选（含同次公开消息/公开解释）经独立模型请求对照完整服务端材料事实复核；明确不一致通过安全诊断进入既有至多两次候选循环，不确定/无效/不可用拒绝。审查是概率性语义检查，不能替代C来源权限或目标/用途等确定性校验。派发与结果审计绑定run/revision、selection/parent/candidate哈希，append还核验已接受provider attempt；已有草案未关联材料反馈时不能旁路追加。另行生成的终结自由文本不在本候选审查范围。

每次真实provider发送前重算完整消息输入预算，包含第二次追加的修复指令；超限终止而不是越界发送。reviewer使用相同配置的服务、实例级单HTTP尝试和有界输出，协议的合法verdict/reason枚举也写入系统消息，不能假定所有JSON模式都会传输schema参数。费用usage已知/未知分别保留，不提供人民币硬封顶。

## 2026-09-30：题库 P0/P1 离线供给基础合同

`learning/item_supply` 增加内部严格的覆盖蓝图、供给需求/结果、条款级proof、exposure与支持矩阵纯函数。矩阵直接复用现行语言能力、公课分组与Item类型枚举；声明的能力与M01/M02/M03首批目标不代表真实runtime/source/库存就绪。

纯供给评估按exact objective/clause/scope/version、item/content、当前声明矩阵hash及policy/runtime/scorer/assistance与当前来源授权事实判断覆盖；默认每条目标保留2练习/2独立考核/1补救的基础冗余，重放或重复题族不虚增独立覆盖。独立组合采用有界确定性匹配，避免贪心碰撞制造不存在的缺口；同handle存在矛盾不可变来源坐标时全部副本失效。候选必须published、适用物化、实际能力/运行条件/授权均有效，private owner与learner匹配，正式考核不使用已暴露题族，也不能把main/supplementary用途升级成assessment。非评分demo不能用scorer字符串伪造assessment，planned/unsupported声明不能被runtime布尔事实提升。前置缺口或部分覆盖不伪装成ready_exact。

所有供给判断及scope/blueprint/demand/proof hash边界均完整重验原始模型；不能先按base注解序列化，丢掉nested子类额外字段后再验证以洗白不可信数据。

这只是可信调用方事实的离线校验层，**不签发来源权限、不解析生产claim回执、不读写数据库、不生成或发布题目、不运行执行器、不接线既有Tutor/Practice/Gate/worker/公开route**。合成正例的ready_exact只证明算法；后续题库持久化、真实审核/沙盘、发布fence、供题和RAG E联合仍需独立交付，正式Attempt/Gate/进度与收尾owner不变。本节不是部署或消费者发布批准。

## 2026-09-30：题库 P2 内部存储与用户清理边界

item_supply新增P2持久化模块，保持P1包入口/coverage等纯函数不自动导入数据库。shared和private物理分离，私有repository只认current user/epoch/active scope；现行用户export/reset/delete与cutover新增清单按原事务接入，不引入第二套用户重置或评分权威。

默认LEARNING_ITEM_GENERATION_ENABLED、LEARNING_ITEM_NETWORK_ENABLED、LEARNING_ITEM_V2_ADMISSION_ENABLED、LEARNING_ITEM_SUPPLY_ENABLED均false。即使显式开启v2开关，本阶段缺trusted source/risk/review/execution adapters仍只能evidence_pending，不能发布。v1审核/试点/人审保持原样。

reset前epoch fencing、job/binding失效及私有拓扑清理保证旧请求不恢复材料；不改shared库存、另一用户或历史正式成绩规则。此处只有一次性PostgreSQL fixture的合成验证，不代表P3 worker、P6真实沙盘/collector、P7发布、P8 Gate或P10/E已就绪。不开启公开consumer，不进行默认库迁移或部署。

## 2026-10-01：题库 P3 作业、预算、恢复与离线参数控制

item_supply作业只由显式owner partition和有界scheduler入口内部认领；额外LEARNING_ITEM_SUPPLY_SCHEDULER_ENABLED默认为false，且必须同时满足SUPPLY/GENERATION开关。未接入生产worker/broker/public route。缺参数/预算/未来P4-P6处理器保持preparing或blocked，不用占位处理器制造completed。

lease generation/CAS与owner/epoch/current scope约束阶段写入，checkpoint仅续缺失阶段；父deadline冻结且heartbeat不能无限延期。失租不能完成业务阶段，只能记录实际匹配的成本事实。等价需求/取消重启/新profile沿用canonical root，累计system/user/provider/window/pool额度不因重建清空。shared consumer取消只处理自己的subscription，不伤其他consumer。

参数按provider/model/role/题型/风险难度/输入桶/runtime版本化，保留initial/current/last_stable/floor/ceiling与可信初始化事实。离线控制器只用synthetic观测验证无样本保持、单维canary、质量覆盖退化回退、冷却冻结等行为；shadow/timeout截断/只成功样本/版本或负载漂移不构成真实校准证明。不得重新默认固定旧2轮90秒30秒。真实provider初值与小流量质量验证仍在后续独立阶段。

可执行合同见.trellis/spec/backend/learning-item-supply-runtime.md。本阶段不改正式Attempt/Gate/评分/进度，不宣称真实供题、沙盘或RAG E完成；测试与尚未执行项见B1b实际验收记录。

## 2026-10-01：题库 P4/P5 内部生成与自主审核

`item_supply.pipeline`将严格公开材料生成、现行纯KC确定性验证、独立盲解及六角色首次盲审接到P2私有候选/版本、460 typed报告和P3当前租约/累计资源账本。调用方先提交prepare预留事务，provider IO只能在IDLE连接执行，再单独提交usage结算与带current source fence的阶段结果。来源权限必须来自同connection现行RAG authority及assessment claim，持久化原request/receipt后在验证和审核提交时重新查当前授权；题库agent不自抓取或自授trust。

生成adapter默认单次HTTP；审核必须使用冻结profile/deadline的BoundedOpenAIReviewClient，每端口单次HTTP，资源按七个实际port bound预留。缺完整usage仍unknown，不把缺货币费用记零。blind solve不能接触答案/hidden/rubric/同行结果；六角色记录真实provider/model/prompt/run，相关模型不伪称独立。硬blocker不能被多数票或minor标签覆盖。

Live producer/reviewer还必须匹配不可变root provider与注册冻结profile；内部`trusted_model_bindings`把profile model-version key映射到实际配置model，不能由公开输入选alias。缺该服务端计划或跨provider/role profile计划不受支持时pending，不自动新建root重置预算。生成结算必须匹配原candidate/scope/source/attempt/provider身份，来源形状假冒或stale source/hash/mode/candidate/version报告均不能提交。KC无execution profile时只绑定实际`static-exact-v1`确定性路径，不虚造OS隔离profile。

内部v2结果即使`eligible_internal`也不是publication；没有真实publisher仍pending。代码/SQL缺可信隔离execution或P6资源适配时blocked，short_text无独立评分也blocked。Synthetic仅专属fixture且不得形成live source-current admission。所有能力开关保持关闭，没有新公开route或worker接线，也未改Attempt/Gate/评分/进度；P6-P10及RAG E另行验收。可执行合同见`.trellis/spec/backend/learning-item-supply-pipeline.md`，实际验证记录位于B1c任务research。

## P6 内部隔离沙盘与终态观察（B1d）

新增sandbox严格Run/TerminalReceipt/Observation及固定十一类场景。观察写入和读取必须resolve+verify受信terminal，完整绑定namespace/tenant/actor/scope/content/profile/origin，重放不增数、改origin拒绝；真实learner缺正式collector/session/actor/terminal权威即拒绝。场景expected标签、opaque actor或模型自报成功不能产生sample/completed事实，模拟不触发正式学习结果。

API只持纯runner/receipt端口，standalone executor桥复用已有固定launch/Docker client，P6自有in-image adapter运行Python或SQLite内存DB，原scorer消费真实输出。候选与宿主不共享网络/挂载/凭据；固定digest、nonroot、readonly、cap drop及有界资源。可信父进程输出隔离与adapter退出码门禁保护terminal真实性；P6固定local日志16k/1file/compress=false不改变全局Docker或旧public profile。正式image-locks仍空，内部候选镜像不能产生公开runtime/health批准。

P6两段式执行复用450累计预算：execution_seconds预留时HTTP请求/token真实为0，470 intent绑定授权零header；prepare先commit，IDLE容器IO，usage另行commit，最后current source/lease fence存460 validation。缺独立equivalent/wrong/boundary或语义probe计划保持blocked；真正machine_verified代码/SQL V2直接进入typed P5路径，无legacy V1 receipt且不得伪造。有限first-batch真实来源/评分/审核证据见B1d research；Python当前独立教材审核仍quarantine，不能将机器通过当准入。完整M01/M02/M03候选资格、正式learner、P7-P10/Practice/Gate/E和公开发布另验收。内部合同见`.trellis/spec/backend/learning-item-supply-sandbox.md`。

内部授权时钟来自PostgreSQL clock_timestamp，等待control/global限额/root/window锁后必须重新取时钟并重验lease及所有预算窗口；等待前的时间或调用方now不能批准过期工作。复制/构造的profile/policy/observation/window在早返回前仍严格重验；混合人口不能掩盖精确匹配canary的确定性失败，commit/begin_canary不能绕过cooldown。

当前安全限制：普通reserve仍拒绝legacy execution-only envelope；仅精确当前470 intent可通过reserve_execution批准私有零request/token header，不造假计数。失租/取消且namespace仍合法时只允许原generation记录原reservation成本；revision失效或reset后不能认证新的真实late-actual callback，拒绝新写但保留已有匿名事实和保守占用。此处不宣称真实provider成本对账已完成。

## 2026-10-02 Python assignment goal 有限内部增量

新 `python-assignment-sum-print-v1` 为独立 D1 目标，受保护父进程在密封容器中核验整个程序 AST；仅固定 numbers 赋值后直接 sum/print，或经 total 中间变量两种结构。子进程只接收代码，不接收私有真值。API 服务依据精确公开指令与冻结 blueprint 编译目标规则，实际 candidate/reference/equivalent/negative/blind/ambiguity 共用同一评分器：正确 stdout 与严格 Boolean goal fact 同时满足才通过，缺失或基础设施故障为 pending。

该 profile 有界12容器/120秒；blind与两次ambiguity在原review预留30执行秒内。481事实须验证同一个实际 Docker bridge issuer 的原密封回执，不能用 injected verify=True 或 bare digest 替代。goal-only reviewer v2.3 输入包含服务派生的有效评分描述并绑定 input_hash/资源计划，不泄漏其它角色投票或盲解答案、不指示批准。真实机器评分通过不取消独立教材审核否决，也不构成 P7/P8/E、正式 image lock 或公开消费者验收。

## 2026-10-06：有限题型证据与展示约束简化

用户批准新版本不再以固定四家族、六pair/十二方向完整答案迁移作为统一前置；每条目标仍保留2练习/2考核/1补救，正式Gate、六角色审核、隔离/隐私与budget/source权限不变。`PackInputsV2` 经原 `build_pack` / `select_pack` 入口选择KC/Python/SQLite三种证据profile：逐题质量事实、实际曝光完整性、两道考核之间及与所选训练/已曝光内容之间的具体关系证据。允许同family练习补救；family名称/随机seed/不同hash不自动证明考核不重复。旧V1算法/合同及历史否决保持，不把新规则追溯套到旧结果。

新 `finite-public-spec-v3` 允许标题、规范任务核心外的引言/收尾变化；既有8000字题面上限、一次完整规范任务块、结构化目标/选项/schema/dataset/其他public字段保持。显式兼容slot allocation使同族训练可从factory实际构建；Python scorer接受范围不扩大。生成request仍绑定规范spec，审核/持久化/当前读取绑定实际生成source/public哈希，不能凭“仍符合模板”接受审核后的改写。V3原生current-query核对493事实中实际已审source；无可信finite spec的private publication仍关闭。

内容关系审核绑定稳定的exact contents与目标上下文，可按角色批量处理多pair；不绑定每次变化的30秒exposure receipt。当前资格计算仍需新的owner/epoch/watermark完整快照并比较实际新曝光，不续签旧报告、不把选项字母或标量输出相同当作语义克隆。

这些V2包对象本身仍是可信调用方事实的纯计算，不是签发/验签authority。后续501原生issuer按真实493/494重建逐题事实与稳定关系批次；502复用原495完整曝光collector并消费同事务501 capability，不接收裸DTO作为许可。公共li题目在496私有学习context中使用显式scopedV2投影，不更改题目visibility或旧V1所有权校验。

关系审核执行期限与新证据期限分离：prepare/run/commit服从原P3 lease/root，首次签发的关系判断最多7天且不超过实际source/retention期限，复用不续期；当前source/runtime/mapping/epoch及30秒完整曝光每次重新检查。503/504按签名owner/epoch选择性处理actual-D私有proof和到现有PUBLIC载体的精确关联，准备只允许原producer持有的draft_ready路径，正式消费仍要求原流程confirmed。普通reset/delete按原权限清理；cutover遇到这些数据仍阻止迁移，不为迁移删除当前资料。

2026-10-06本增量216项离线集成、Ruff及全后端446文件Mypy通过；501–504真实PG同片/全manifest重放及空表reset演练全部回滚，未安装。首个KC V3练习已真实生成/验证，但盲解不通过，未进入六角色审核或发布，不重投旧题。501/503/504独立复核、填充私有链、真实完整题包/交付、Attempt/Gate、P8-P10和E仍待验收。内部规格分别见 `.trellis/spec/backend/learning-item-supply-type-evidence.md` 与 `learning-item-supply-native-evidence.md`。

## 2026-10-07：显式诊断式盲解准入策略

用户在2026-10-06批准：对新`autonomous_evidence_policy_v3`，一次真实完成的盲解答错不再前置否决题目，继续独立六角色审核；只有独立正确性、来源、执行/评分/反例/歧义、风险和全部规定审核充分，才可得到`eligible_internal`，并在`diagnostic_warnings`保留`blind_solution_incorrect`，原blind score仍为false。模型回答不能替代题目质量证据，模型答对也不能覆盖其他硬失败。未完成、超时、解析失败当前明确pending，不制造完成回执或自动重试。

`AutonomousEvidencePolicyV3` / `ReviewBundleV3` / `AdmissionEvaluationV3`集中定义在`diagnostic_policy.py`；原V2默认、schema/hash及严格盲解行为不变。原`GenerationRequestV2`保持字节形状，新增独立`SharedGenerationPolicyBindingV3`在首次author预留前绑定原canonical root/job/request/blueprint/profile/lease generation，不因policy变化清预算或新开root。题面`finite-public-spec-v3`不是新准入授权。

新policy经原generation→shared review→admission→493facts→494publication/current-query→501重建一致校验；警告在事实/evaluation摘要中封住，current-query和501提供只读诊断投影。六角色仍看各自独立输入，不读取solver答案/score或同行结论。旧private481不自动升级；没有新增公开路由、自动发布、Attempt/Gate/mastery权限。旧失败候选不能事后追加新policy，不能将其旧结果改成通过。

本节描述已批准的代码合同；正式安装、真实新V3候选与完整供题包仍需单独验收，历史KC失败保持。可执行规则和正负矩阵见 `.trellis/spec/backend/learning-item-supply-diagnostic-blind.md`。

本增量最终离线验证：main核心组合198通过，独立operator63通过，Ruff及后端Mypy447文件/两个operator类型检查通过。执行脚本支持显式`--admission-policy diagnostic-v3`；旧默认`strict-v2`三种计划JSON/hash不变，新policy必须进入新不可变计划，不可追贴旧campaign。Main四次真实CLI plan均零DB/provider，迁移只做强制回滚，未运行新V3真实候选；旧29个SQL文件和旧KC失败18个文件均保持。完整证据见`.runtime/e-blind-diagnostic-20261006/acceptance.json`。


## 2026-10-07后续：真实finite规划与actual-D准备

501–505已在B1d指定隔离库安装；通过原thread/turn服务的prepare/enable启用generation1，不启用生产或公开consumer。新用户自动birth仅是private bookkeeping，原cutover不再把它误算为学习内容，真实inbox/watermark等仍阻断。原规划质量校验新增精确闭合finite课程映射：原语言必须可选，描述及完整语义能力tuple必须与注册表同语言目标完全一致；普通节点仍按原language/runner规则。目标/描述hash不变，描述函数抽到纯registry避免planner引入重型mapping依赖。

原provider/dispatcher/action链已真实生成KC有限草稿；教学消费helper通过原C签名/qualification/current corpus/policy/root授权生成两节点全草案selection，再走原actual-D prepare。来源阶段实际执行并签发新私有scope证明，不复制PUBLIC签名或把教学facet就绪当全部KC评分证据。规划本轮共8HTTP，原D累计69→77，失败和unknown金额保留；没有继续自动扩大该规划窗口。

有数据source落库曾暴露503局部别名冲突，506修复及真实插入在本日较早阶段仅回滚通过，独立复核一度受Codex子代理网关403阻塞。该失败及回滚历史保留，不是Aearn项目预算耗尽的证明；后续恢复状态如下，不再把403当作当前阻塞。

### 同日恢复：KC actual-D私有链已按原owner通过

506独立复核passed，接受SQL SHA256为`5856416e9a2c81ce7b2c0d9c4356260ddace1d59ce7d23f9ebbb728c874642a9`；main正式隔离安装，并复用保留的正确私有signed经原repo.persist提交，current readback通过。随后按原次序完成：draft_ready的真实教学selection/actual-D来源→原assessment producer preparation/private bridge/freeze→原confirm_session/CAS（confirmed v4）→confirmed正式current authority→496 finite mapping正式提交。没有手改session status、把PUBLIC签名重贴为私有来源，或用true callback跳过authority。

原reset/delete在该实际填充链上分别force_rollback验收：proof/review/admission/claim/provenance五类各1条→0，179张PUBLIC/其他用户保护表摘要不变，回滚后292表全恢复。持久化的课程/source/mapping仍保留；回滚验收不等于永久删除，也不证明Attempt/Gate或完整供题包已通过。

证据集中在`.runtime/e-actual-d-native-20261007/`：`506-install-persist-4c62a0c556984e3b9cd86475533496c2/result.json`、`kc-assessment-freeze-c10b3fbdce744c55aab34cb6b5537a48/result.json`、`kc-confirm-5b452a3e34c14b399bf7a33f2ad1ea3c/result.json`/`response.json`、`kc-mapping-fcf13940d4bd4ce98e145e79df14db85/result.json`/`mapping.json`、`kc-populated-lifecycle-6692cbbd7bc140e2a72842d0dd01f112/result.json`。独立结论在原题库任务`research/native-private-independent-check-20261007.md`。

上述来源/确认/映射/生命周期恢复窗口0provider/GET/新oracle/新签名，规划历史累计77不变，金额unknown不当0、旧失败/lease/政策窗口不改。后续候选阶段单独追加如下；仍需KC完整2/2/1、Python/SQLite供给和P8、P9、P10/E联合验收。任务保持in_progress；没有提交、推送、归档、生产部署或公开release。最新入口仍为`.trellis/tasks/09-22-multi-agent-item-bank-sandbox/research/fast-continuation-progress-20261007.md`。

### 新diagnostic-v3候选的真实partial结果

新immutable campaign `.runtime/e-native-type-20261006/kc-diagnostic-v3-20261007-actual-d-1`中，`practice-1`已实际author 1HTTP并staged，原validator计算结果`machine_verified`；首次505运行时generic RECORD→generation composite转换报SQLSTATE42846，原`commit_validation`未成功提交。原失败attempt `e417d025a3714b71958849be85c4a339`保留；该停止点尚未进入盲解/六角色/发布。507后原491续跑已完成validation提交，随后盲解传输失败，仍不是ready_exact或完整包通过。

main的零provider、未提交PG诊断记录在`.runtime/e-fast-continuation-20261007/schema507-record-diagnosis-c6da9b73d14f4d8da6885f04459427b0/result.json`：generic record失败，typed `%ROWTYPE`通过。随后checker离线4 tests/Ruff和main审阅接受append-only507，只有3处声明改为`%ROWTYPE`，其余BEGIN之后body逐字不变。SHA256=`5cc76ad7f096eb5944a46d269b478ef3b4ca3f29d78e218feac930bd837e71a8`；真实同片/全manifest截至507重放通过，292表行不变，rehearsal回滚恢复原函数/行后正式隔离安装。证据`.runtime/e-fast-continuation-20261007/schema507-acceptance-6c7a29a58d1a4e658638488514a034b8/result.json`，`ddl_committed=true`、provider=0、新author=0。

原491一次续跑已结束：复用同一题目、0新增author，continued-validation-staged.json确认machine_verified及校验回执已提交。随后盲解请求URLError，review.json为blind_solve_pending且blind/bundle均null；六角色未调用，facts/publication未产生。一次无鉴权、无推理HEAD也出现SSLEOFError，当前阻塞为provider TLS/network，不是已完成答错；不能按V3诊断策略放行。已停止新增付费调用，不重审刷通过、不改UNKNOWN或旧lease。 原author已知input12841/output2137/total14978 tokens；盲解请求尝试1次、六角色0次，服务端usage unknown，费用null。两项均追加原ledger，规划累计77不变。传输诊断`.runtime/e-fast-continuation-20261007/provider-head-diagnostic-20261007.json`。

### 2026-10-08：原生供给续行与历史491兼容读取

网络及三目标current source恢复，既有confirmed496课程映射通过只读核验。501不再误要求原generation request.profile等于合法491新facts profile：改为检查实际validation preparation、不可变491原行及原bind重算；普通同job路径仍精确比较。真实回滚readback区分旧历史DATA通过、同旧题current source拒绝，以及新V3当前消费通过。不得用历史重构修复复活旧source/lease。

新增KC同连接pack装配helper已完成实现与独立窄检查，按实际内容slot计数2/2/1而非强制variant各异；仍由原501/502关系/消费owner及真实Artifact writer分别负责。23项native证据文件测试、4项helper测试及scoped Ruff/Mypy通过，**helper live包/交付尚未执行**。

新的有界diagnostic-v3 campaign完成24个provider请求：1道KC题经原493/494内部发布，2道被重大独立审核否决而quarantine。零provider静态重建18个原role输入hash一致，但hash-only findings不足以定位具体缺陷，不能称为模型误判或重审放行。已停止余下付费生成，保留UNKNOWN及旧结果；P7b完整题包、P8–P10/E仍pending。最新实证与调用登记见`.trellis/tasks/09-22-multi-agent-item-bank-sandbox/research/fast-continuation-progress-20261008.md`及`.runtime/e-continue-20261008/acceptance.json`；不代表公开release。

### 2026-10-09：版本化六角色证据审核与显式 high 思考

用户要求直接修复角色职责、字段级否决证据、裁决一致性、失败回执及质量样本，并按官方文档开启思考。复用原题库任务，不替代原admission/publisher/Attempt/Gate权威。新审核协议为`evidenced-v1`，对应`item_supply_evidenced_review_input_v1`、`item_supply_evidenced_review_output_v1`、`item_supply_evidenced_review_report_v1`；旧`ReviewInputV2`/`ReviewReportV2`及外层V2/V3 policy/hash保持历史兼容。新版本不能将真实新output压缩成旧格式后冒充provider output_hash。

六角色分别按课程匹配、难度、技术正确性、歧义、安全、对抗清单审核；重大主张必须提供私有problem、expected_behavior和精确pointer/value_hash引用，部分原因还需具体counterexample。引用校验只证明字段归属/完整性，不自动证明模型主张为真。无依据或矛盾输出不产生成功审核；不能把invalid/pending翻译为approved。任何角色发现真实硬问题仍可报告，不以专业分工屏蔽跨角色安全缺陷。旧quarantine与UNKNOWN不可重审刷通过。

新fresh审核显式使用DeepSeek高强度思考，当前本地模型配置为`deepseek-flash`：Responses发送`reasoning.effort=high`；受支持的`deepseek-v4-pro` Chat发送`thinking.type=enabled`及`reasoning_effort=high`。使用原冻结token/输出/单请求限额，禁provider body捕获，不保存或显示思维链；输出预算耗尽或过滤必须pending。没有显式effort的旧传输调用保持原样；作者、旧盲解和Tutor不因此全局改策略。官方核验见题库任务`research/deepseek-review-thinking-official-20261009.md`。

新协议需在新campaign中冻结；旧计划缺marker按legacy处理，不能因代码更新自动升级旧campaign/预算。部分已完成角色回执是私有诊断记录，不是完整bundle或发布许可。同模型相关性仍明确标记，高风险独立第二bundle规则不变。小型标注样本/离线测试仅证明协议和已知案例行为；真实模型误报/漏报率、真实新候选、完整题包、交付、P8/P9/P10/E仍须分别取得实证。此修复不含真实模型/DB/Docker执行、旧SQL迁移改写、Git提交推送或公开发布。

独立检查进一步补齐：原生CLI、导入执行和直接campaign准备均在DB/provider/预留之前验证协议及既有冻结计划一致性；private准备在预留前拒绝mixed协议。预留REPLAY不重新签发prepared review或dispatch能力，不能借重放重审旧题或重置UNKNOWN。
