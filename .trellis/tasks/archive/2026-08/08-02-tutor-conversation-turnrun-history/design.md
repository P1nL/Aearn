# Technical Design: Conversation TurnRun、公开历史与 Desktop 导航

## Scope and Dependency

本 child 在 `08-02-deepseek-responses-decision-contract` 已归档后开始。它消费该 child 提供的严格 `TutorDecision.conversation_title` 和 `continuation_kind`，但不复制或改写 provider protocol/parser。它负责普通互动的 durable lifecycle、公开 projection/read contract 和桌面交互。

## Lifecycle Model

```text
long-lived TutorConversation
  ├─ ordinary learner message → fresh finite TurnRun → terminal Tutor reply
  ├─ ordinary learner message → fresh finite TurnRun → terminal Tutor reply
  └─ explicit checkpoint continuation → same run only when authorized
```

普通输入不再调用 `find_or_create_interactive_run()` 的 merge 语义。新 repository operation 创建新 run，带 fresh policy/deadline/counters，同时由 conversation history loader 读取长期上下文。

`TutorRunStatus.CANCELLED` 继续作为 terminal outcome；不增加暴露给客户端的 `superseded` terminal enum。`superseded_by_run_id` 是内部 audit link，public projection 映射为安全的“已根据你的新消息更新本轮处理”。

## Database Changes

所有变化为 additive，bootstrap schema 可重复运行。

### `tutor_conversations`

新增：

- `title text NULL`：只保存验证后的模型简述；null 对外投影为 `新对话`。
- `last_public_activity_at timestamptz NOT NULL DEFAULT now()`：唯一的 conversation list ordering authority。

标题更新必须是 `UPDATE ... WHERE title IS NULL`。没有 rename mutation、无条件更新或 learner-input fallback。

### `tutor_runs`

新增：

- `superseded_by_run_id uuid NULL REFERENCES tutor_runs(id)`：指向最新替代该 run 的普通 turn。
- `continuation_kind text NULL`：只保存 Child 1 contract 允许的明确 continuation；普通 completed turn 为 null。

新增 partial unique foreground index，覆盖 interactive run 且 `terminal_outcome IS NULL`、`cancelled_at IS NULL`、`superseded_by_run_id IS NULL`。repository 的 foreground select、cancel 和 insert 必须使用同一 predicate。

### Safe public-process projection

新增一张一 run 一行的 `tutor_run_public_processes`，至少包含：

- `run_id`、`user_id`、`conversation_id`；
- `projection_version`、`display_state`（例如 `thinking`、`completed`、`superseded`、`unavailable`）、`current_step_key`；
- `tutor_message_id NULL`（成功 public Tutor reply 后链接）；
- `started_at`、`last_public_activity_at`、`finished_at NULL`；
- 仅由服务端闭合 enum 控制的状态字段。

另设 append-only `tutor_run_public_process_steps`：`run_id`、bounded `step_key`、`ordinal`、`state`、`occurred_at`，以 `UNIQUE(run_id, ordinal)` 保证顺序。只允许固定枚举，例如 `input_received`、`context_prepared`、`authorized_resource_checked`、`learning_reply_generated`、`replaced_by_newer_input`。数据库 check 与 repository allowlist 双重约束；不存任何自由文本、trace、prompt、provider payload 或工具参数。

在 read projection 中，服务器将 key 映射为固定中文 public text，并由 `started_at/finished_at/server now` 计算非负、bounded elapsed seconds。前端不保存或推断 duration。

## Atomic Mutations

### First turn

新 `POST /api/tutor/conversations/first-turn` 在一个 public idempotency transaction 中调用 repository 的 atomic operation：

1. 校验 user；
2. 创建 learner-visible interactive conversation；
3. 创建 fresh run；
4. 插入首条 learner message 与 run input event；
5. 插入 `input_received` public-process projection/step；
6. 返回同一 `conversation_id`、`run_id`、safe run/process projection。

任何失败都会回滚全部步骤，因此点击新对话、请求取消或首发失败永不留下空 conversation。相同 idempotency key/body 重放读取 `tutor_api_idempotency_records` 的同一安全响应；同 key 不同 body 保持冲突。

现有 `POST /api/tutor/conversations` 可暂时作为受控兼容入口，但新的 Desktop draft flow 不调用它；不能把它用于预创建 learner-visible 空 conversation。

### Ordinary turn and replacement

继续使用 conversation-scoped input route，但将其语义改为每普通消息新建 run：

1. 在 transaction 内锁定 conversation；
2. 查找并锁定 foreground run；若存在，写 `cancelled_at`、`superseded_by_run_id`，终止其 public-process display，并追加 `replaced_by_newer_input` step；
3. 创建 fresh run、learner message/input event 和 `input_received` process；
4. 更新 conversation public activity；
5. 返回新 run，并仅 dispatch 新 run。

用于普通 turn 的 idempotency response 包含新 IDs；旧 run 的 cancel event 只是受控 public event，不可包含新输入正文。

### Explicit continuation

`POST /api/tutor/runs/{run_id}/inputs` 在写入前读取/锁定 run，并仅在：该 run 属于该用户、未 superseded/cancelled/terminal，且 persisted `continuation_kind` 与 checkpoint state 允许时继续同一 run。否则返回稳定 public conflict；普通聊天需要改走 conversation input 路由。

## Run-loop and Persistence Race Guards

扩展 run store/lifecycle 的 active check，使它同时读取 cancellation 和 supersede。run loop 必须在以下点调用它：

- provider return 后、decision gate 前；
- 每个 capability dispatch 前；
- 每个 effect commit 前；
- terminal public-message persistence 前。

如果发现 supersede，run loop 返回 `CANCELLED` 安全结果而非继续使用 provider decision。terminal persistence 方法必须在 locked transaction 内二次确认 run 仍是 foreground；若不是，只允许更新 safe run/process terminal display，绝不插入 Tutor message、title、capability/effect receipt 或 conversation public activity。

这两个防御层都必须通过 post-provider race test 证明。只靠 `current_input_revision` 不足以防护不同 run 的替代竞态。

## Server-safe History and List Projections

### Conversation summaries

`GET /api/tutor/conversations` returns only learner-visible interactive conversations scoped to the caller user. The response is:

```json
{
  "items": [
    {
      "conversation_id": "uuid",
      "title": "函数基础练习",
      "last_public_activity_at": "ISO-8601",
      "active_run": { "run_id": "uuid", "status": "running" }
    }
  ],
  "next_cursor": "opaque-or-null",
  "has_more": false
}
```

The query sorts `(last_public_activity_at DESC, id DESC)`. It never returns learner raw-input preview, diagnostics, provider/model data, trace data or arbitrary message bodies. The compact recent call uses limit 8. The full panel reuses the same read contract with a bounded page size.

### Timeline history

`GET /api/tutor/conversations/{conversation_id}/history` returns reverse chronological, server-authoritative public timeline items:

```json
{
  "items": [
    {
      "kind": "message",
      "id": "uuid",
      "role": "learner | tutor",
      "content": "public message content",
      "created_at": "ISO-8601"
    },
    {
      "kind": "process",
      "id": "run-id",
      "run_id": "uuid",
      "display_state": "thinking | completed | superseded | unavailable",
      "steps": [
        { "key": "input_received", "state": "completed", "label": "已接收你的问题" }
      ],
      "elapsed_seconds": 12,
      "created_at": "ISO-8601",
      "finished_at": null
    }
  ],
  "next_cursor": "opaque-or-null",
  "has_more": true
}
```

The implementation must define stable order and avoid duplicated process/message items. A process record is linked to its run and, after successful reply, Tutor message. The merged query uses one canonical event-time field plus a type/id tie-breaker. A server-signed opaque cursor encodes the last stable sort tuple, scope and version; decode failures, scope mismatch and malformed tokens return a safe cursor error, not SQL detail.

Legacy `tutor_messages` without a public-process record emit only `kind="message"`. The history read cannot inspect trace/event payloads to invent a card, title or duration.

### SSE role

SSE remains incremental current-run transport. It can carry only safe status/process fields for the selected run. Upon navigation, the Desktop cancels the old EventSource before history hydration. On reconnection it uses only a run-local event sequence; conversation/history pagination never treats SSE sequence as cursor.

## Title, Process and Event Projection Rules

Repository owns all message/process/title interactions:

- initial `input_received` process step is written with the learner input event;
- safe state transitions append only allowlisted step keys, never arbitrary model text;
- `tool_status`/activity events can advance only a mapped public tool-category step, not reveal capability IDs/arguments;
- terminal success locks the run, verifies it is not superseded, writes the Tutor message, links the process, freezes elapsed and writes title once when safe candidate exists;
- terminal cancellation/supersede freezes the process as `superseded`, appends the replacement-safe step, and cannot link a new Tutor message;
- public API/SSE history projections map symbolic keys to fixed labels, so localization does not change durable truth.

`last_public_activity_at` is updated only after a learner input, safe public process transition or safe Tutor response. It is never driven by background diagnostics or raw provider activity.

## Desktop State and Interaction

### Ownership

`App.tsx` or a Tutor route-level controller owns selected conversation identity and delegates workspace rendering. It does not place conversation state in global bootstrap/local storage. `TutorWorkspacePage` owns ephemeral draft text, disclosure open/closed state, hydrated timeline and request loading/errors.

### New conversation

Selecting `新对话` must:

1. close SSE and reset active run state;
2. set selected conversation to null/draft;
3. clear the displayed timeline/composer context;
4. make no network mutation.

First nonblank submit invokes first-turn. The returned IDs become active only after the atomic response succeeds. Errors leave the user in the local draft and must not optimistically add a sidebar item.

### Existing conversation

Selecting a recent/full-list item must:

1. cancel prior fetch/EventSource work (via `AbortController` / hook cleanup);
2. reset local run/timeline/cursor state;
3. hydrate latest history page;
4. subscribe to returned active foreground run only when server says it is nonterminal;
5. keep "load earlier" prepend order stable and preserve focus/scroll anchor.

Normal composer submit always targets the selected conversation's turn endpoint. It must not choose run-input merely because a run exists. The UI only exposes continuation input affordance when backend run state explicitly grants it.

### Process disclosure

Each history process item is a `<button>`-like disclosure row with an accessible label, `aria-expanded`, visible status/elapsed label and chevron. The expanded region lists server-projected steps and marks completion/current state. It starts collapsed after hydration; local expand state is keyed by `run_id` and does not alter durable data. Animation is removed/reduced with `prefers-reduced-motion`.

The card uses the requested compact inline treatment: no gradient, heavy frame, thick shadow or three-column dashboard. The main timeline, not the whole page, has `min-height: 0`, `overflow-y: auto`, overscroll containment and scroll-to-latest only for active conversation updates. The composer remains outside that scroll region.

## Testing and Rollout

Backend tests must use database fixtures/fake provider and cover: ten distinct normal turns; first-turn atomic rollback/replay; foreground index/concurrency; provider-return supersede race; capability/effect suppression; continuation authorization; title write-once/invalid candidate; process step allowlist/redaction; history/list cursor scope; legacy message compatibility; safe duration calculation.

Frontend tests/type checks must cover: draft sends no create mutation; first submit endpoint selection; existing turn endpoint selection; old SSE cleanup on switch; history sort/prepend; recent/full list pagination; disclosure keyboard state; server-only process labels; and local timeline scrolling layout contracts where test tooling supports it.

Deploy additive schema before backend mutation/read paths, then Desktop UI. Rollback disables the new UI/route gate to a safe unavailable/read-only state; do not convert already-created new run rows into the old merge behavior and do not delete process/title audit data.
