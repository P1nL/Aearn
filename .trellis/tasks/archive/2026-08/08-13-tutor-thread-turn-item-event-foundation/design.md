# Tutor 会话/轮次/条目与统一事件底座：技术设计

## 权威与模块边界

- `PostgresTutorRepository`/新增小型 repository 负责 sequence、item projection、dispatch job 和 snapshot read；route 不直接拼 SQL/状态。
- `TutorRunDispatcher` 继续拥有 Harness composition；worker 只 claim durable job 后调用 dispatcher，不复制业务策略。
- `TutorPublicService` 负责 learner-safe DTO 和幂等 mutation envelope；SSE adapter 只读取 public event。
- `aearn_worker.worker_app` 保持 thin adapter，API-side service 持有 PostgreSQL policy 与 claim 逻辑。

## 数据库结构

### 会话扩展

- `next_public_event_sequence bigint NOT NULL DEFAULT 1 CHECK >= 1`
- `control_version bigint NOT NULL DEFAULT 1 CHECK >= 1`

旧数据无需 event backfill；这两个字段只控制新事件/mutation。

### 轮次扩展

- `interaction_protocol_version text`：迁移先回填 `legacy_v1`，再设置新默认 `thread_turn_v2`。
- `retry_of_turn_id`、`retry_root_turn_id` 可空并使用具体 run 外键；`response_to_request_id` 等请求关联留到 Child 2 在请求表存在后添加，禁止无外键约束的多态 item ID。
- 避免用未校验 `policy_json` 临时塞协议字段。

### 会话事件

`event_sequence` 用 bigint；repository 锁 `tutor_conversations FOR UPDATE`，读取并递增 next value，再插入 event。`event_key` 由稳定 mutation/item identity 派生，不包含 learner content。

公开 payload 通过 Pydantic/dataclass union 编码，写入前 canonical JSON + hash。数据库只接受闭合 kind/projection version，repository 再校验每种 payload 字段。

### 调度作业

lease 字段沿用现有 run/proactive pattern：owner、generation、expires_at。claim 查询按 `available_at, created_at, id`，`FOR UPDATE SKIP LOCKED`，一次 bounded batch。worker 成功后标 completed；transient error 进入 retry_wait/backoff；不可恢复或超过上限进入 dead 并追加 learner-safe error/control event。

## 公开条目与快照

- message item 由 `tutor_messages` 投影，turn link 从 `tutor_run_input_events` 或 process 获取。
- process item 由现有 public process 表投影；扩展 schema 添加闭合 display state：`thinking | waiting_input | waiting_approval | waiting_authority | completed | interrupted | superseded | unavailable | failed`，不保存模型自由文本。
- elicitation/approval 在本 child DTO 中先定义 union slot，表由 `08-14-tutor-typed-request-authority-turns` 完成。
- error item 从 safe terminal mapping 投影，内部 diagnostic 只映射到允许的 public code。

Snapshot 查询在一个 repeatable/read committed transaction 中获取：conversation/version → active foreground turn → pending request/queue（不存在时空）→ timeline page → current sequence。返回 `snapshot_version` 与 opaque cursor。

## 事件流

SSE endpoint 轮询/等待 `tutor_conversation_events`，按 sequence 输出：

```json
{
  "event_id": "uuid",
  "sequence": 42,
  "kind": "item_updated",
  "turn_id": "uuid-or-null",
  "item_id": "uuid-or-null",
  "item_kind": "process-or-null",
  "payload": {},
  "occurred_at": "..."
}
```

cursor 包含 version、conversation ID、sequence 和签名/完整性校验。跨 conversation cursor、负数、未来 sequence、未知 version 返回 stable recoverable error。保留 heartbeat，但 heartbeat 不写 DB、不推进 cursor。

## 后台工作进程与启动

- 新 API-side `interactive_worker.py` 提供 `dispatch_job(job_id?)` 与 `reconcile(limit)`。
- Celery tasks：`tutor.interactive.dispatch`（高优先级 queue）和 `tutor.interactive.reconcile`。
- `beat_schedule` 定期调用 reconcile；本地 dev 脚本管理 worker 和 beat 的 PID/log/status。
- HTTP commit 后 best-effort `apply_async`；失败只记录安全 code，job 留在 DB 等 reconciler。

## 兼容

- 旧 rows 明确 `legacy_v1`；旧 `/runs/{id}/inputs` 与 run SSE 不在本 child 改语义，最终 retirement 由 `08-14-tutor-thread-turn-v2-global-cutover` 完成。
- history union 对无新 event 的旧 message/process 正常工作。
- 新 snapshot/event contract 添加版本字段，Desktop 尚未切换时不影响旧消费方。

## 失败与回滚

- sequence insert 失败回滚 owning mutation，绝不跳过 authority event 后继续成功返回。
- worker unavailable 映射 dispatch delayed；不把 job 标 completed。
- feature gate 可停用新 dispatch consumer并保持 read-only snapshot；schema 不删除。
