# Technical Design: Tutor TurnRun 生命周期、公开历史与 DeepSeek Responses

## Summary

目标是把 Tutor 从“一个可复用的有限 interactive run”改为“一个长期 `TutorConversation` 加每条普通输入一个有限 `TurnRun`”。普通聊天不再续写旧 run；新输入取代仍在前台执行的旧 run，并在运行时和持久化事务两层阻止旧 run 继续产生 learner-visible 结果或副作用。

模型适配只在精确配置为 `deepseek-v4-flash` 时采用经官方文档核验的 Responses 契约。adapter 只读取最终可见文本；`reasoning` 和 provider 原文不得跨越 adapter。桌面端的“正在思考”是服务端持久化的安全公开步骤投影，不是模型原始思维链。

## Boundaries and Data Flow

```text
Desktop Tutor shell
  ├─ conversation sidebar / local draft / history rendering
  └─ useTutorSSE (transport-only, one active run)
          │
          ▼
Tutor Public API
  ├─ atomic first-turn / ordinary-turn mutations
  ├─ explicit run continuation only
  ├─ conversation list/history reads with opaque cursor
  └─ safe SSE projection
          │
          ▼
Tutor repository + lifecycle
  ├─ conversation lock + foreground replacement transaction
  ├─ TurnRun/public-process/title persistence
  └─ terminal write guard for cancelled/superseded run
          │
          ▼
TutorRunLoop
  ├─ finite policy/deadline/budget per run
  ├─ post-provider and pre-effect cancellation checks
  └─ no public message/effect after supersede
          │
          ▼
Primary provider adapter
  ├─ deepseek-v4-flash → documented Responses path
  ├─ other DeepSeek → fixed Chat Completions path
  └─ strict TutorDecision / no reasoning extraction / no fallback
```

Desktop never derives durable history ordering, title, public process steps or elapsed duration from local timestamps or raw SSE. It renders server projections only.

## Conversation and TurnRun Lifecycle

### Long-lived context, finite ordinary turns

```text
TutorConversation (durable)
  ├─ TurnRun #1: learner input → public process → tutor reply → completed
  ├─ TurnRun #2: learner input → public process → tutor reply → completed
  └─ TurnRun #N: learner input → public process → tutor reply → completed
```

每个普通 learner 输入都获得新的 `run_id`、policy snapshot、deadline 和 counters。conversation history 仍是 context source，因此新的 run 保留历史学习上下文，但绝不继承旧 run 的预算。

一个 run 只有在持久化的 explicit continuation kind 被服务端 checkpoint 允许时才可以 `waiting_for_input`。普通回复必须完成；模型不能创建任意无限期等待的聊天 run。

### Latest-input-wins

普通 turn 的 repository transaction 必须：

1. 校验归属并以 `FOR UPDATE` 锁定 conversation；
2. 锁定尚未终态、未取消的 interactive foreground run；
3. 标记旧 run 为 cancelled/superseded，并将其 public-process projection 切换为安全的“已根据你的新消息更新本轮处理”；
4. 创建具有新 policy 的 run、learner input event 与初始 public-process projection；
5. 更新 conversation `last_public_activity_at`，并在 public API idempotency boundary 内提交。

通过 partial unique foreground index 保证一个 conversation 最多一条未取代的 interactive foreground run；index predicate 和 repository selector 必须使用同一份 terminal/cancelled/superseded 定义。

### Race protection

provider 可在更新输入已被接收后才返回，因此必须双层防御：

- **Run loop：** `provider.decide()` 返回后、decision gate 前、capability dispatch 前、effect commit 前、terminal public message 前，重新加载 cancellation/replacement 状态。
- **Persistence：** terminal write transaction 锁定并重新核验 run。若 `cancelled_at` 或 `superseded_by_run_id` 已设置，只能写安全取消终态投影；不得插入/关联 learner-visible Tutor message、title 或 effect。

capability/effect 使用同一 pre-boundary recheck；过期结果直接丢弃，不附着到新 run。

## Provider and Strict Decision Contract

### Protocol selection

Provider choice is based on exact capability, not merely `llm_provider_type == "deepseek"`:

- `deepseek-v4-flash`: documented DeepSeek Responses request/SSE/final-text path;
- other DeepSeek models: fixed Chat Completions compatibility path;
- all other providers: existing generic Responses path.

The chosen adapter emits a bounded internal protocol category only. A transport, parser, incomplete-response or schema error returns a safe outcome from that selected adapter; it never triggers a request through another provider, model or protocol.

### Final visible text only

The Responses parser accepts a completed response only when the documented final visible text field is nonempty. It classifies but never exposes:

- reasoning-only/no visible text → content missing;
- incomplete/failed response → bounded protocol failure;
- malformed event/envelope → bounded envelope failure;
- non-JSON final visible text → content-not-JSON failure.

Raw response bodies, reasoning, prompts and headers must not appear in exception strings returned past the adapter, durable data, public APIs, titles, process cards or logs.

### Canonical decision

One frozen Pydantic envelope with `extra="forbid"` is the source for first attempt and repair prompt:

```json
{
  "public_message": "...",
  "conversation_title": "... or null",
  "skill_references": [],
  "capability_requests": [],
  "effect_proposals": [],
  "checkpoint_reason": null,
  "continuation_kind": null,
  "terminal_intent": "completed"
}
```

`conversation_title` is optional and normalized/validated to no more than 48 visible characters. `continuation_kind` is a closed enum and valid only with an allowed checkpoint. A normal direct reply uses `terminal_intent="completed"`; an ambiguous nonterminal decision is rejected. The gateway can issue at most one repair using the same configured client/model and a prompt that repeats the canonical shape without echoing rejected content or sensitive validation detail.

## Persistent Data Model

All schema changes are additive and Tutor-scoped.

### Conversations and runs

Add `title text NULL` and `last_public_activity_at timestamptz` to `tutor_conversations`. `title` is written only through guarded `UPDATE ... WHERE title IS NULL`; `NULL` projects to `新对话`. There is no title rename API or UI.

Add `superseded_by_run_id uuid NULL` and a bounded persisted continuation state to `tutor_runs`, plus the partial unique foreground index described above.

### Public process projection

Introduce `tutor_run_public_processes`, one safe projection per new-version interactive run, with run/conversation/user scope, bounded display state, current/completed allowlisted step keys, optional linked Tutor message, timestamps and projection version.

Only symbolic keys such as `input_received`, `context_prepared`, `authorized_resource_checked` and `learning_response_generated` are persisted. The server maps keys to learner-facing text. Existing `tutor_messages` remains the source for message text; raw event payloads, traces and diagnostics are never copied into the process table.

## Public APIs

### Writes

- `POST /api/tutor/conversations/first-turn`: atomically creates conversation, first run, input and process projection.
- `POST /api/tutor/conversations/{conversation_id}/turns`: atomically supersedes old foreground run if needed, then creates a fresh run/input/projection.
- `POST /api/tutor/runs/{run_id}/inputs`: only accepts the persisted explicit continuation kind.

The desktop draft flow no longer calls empty conversation creation before a first message.

### Reads

- `GET /api/tutor/conversations?limit=8&cursor=...`: current-user learner-visible summaries sorted by backend `last_public_activity_at`.
- `GET /api/tutor/conversations/{conversation_id}/history?limit=40&cursor=...`: merged safe messages/process cards in reverse time order; desktop reverses each page for rendering.
- existing run/SSE reads: current safe status/process/duration only; terminal diagnostics remain internal.

The opaque cursor carries stable sort position and server integrity protection; it is scope-checked for user and conversation before querying. Client timestamps and IDs are not authoritative cursors.

## Title and Process Completion

When a learner-visible Tutor reply first succeeds, one terminal persistence transaction must:

1. verify the run is not cancelled/superseded;
2. store/link the Tutor message;
3. store a validated `conversation_title` only if the conversation title is still null;
4. complete/freeze the public-process projection with allowlisted keys and server-calculated elapsed time;
5. update last public activity.

If a title candidate fails validation, the reply still succeeds and the title remains null for a later normal decision retry. A superseded run writes neither title nor learner-visible reply.

## History, Desktop and Compatibility

New process cards are emitted between their linked learner input and Tutor reply. Legacy messages without a process row remain ordinary historical messages; no retroactive card, step or duration is synthesized.

The Tutor route owns conversation selection. “新对话” closes the prior EventSource and creates only an in-memory draft. First send uses first-turn; later sends use normal turns. Selecting a conversation tears down prior SSE, hydrates history, and subscribes only when an active public run exists.

A process card is a compact semantic disclosure button with `aria-expanded`, a light status indicator, `正在思考` or `已处理 <duration>`, and an expanded list of server-projected steps. It defaults collapsed, respects reduced motion, and lives inside the locally scrollable timeline while the composer stays visible. `useTutorSSE` remains transport-only.

## Rollout, Rollback and Security

Deploy additive schema/indexes first, then backend routes/lifecycle, then desktop adoption. Existing data stays readable. Rollback disables the new desktop flow/API gate to a safe unavailable state rather than converting new turns back to merged runs; additive data remains for audit/recovery.

Security invariants:

- no raw CoT/reasoning/provider body in database, public API, SSE, title, card or logs;
- no stale/superseded public message, capability dispatch or effect commit;
- no cross-user conversation/list/history access;
- no client-generated durable title, duration, ordering or process facts;
- no empty learner-visible conversation from draft navigation;
- no manual title write path.
