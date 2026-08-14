# Tutor 会话/轮次/条目与统一事件底座

## 目标

为 Codex-like Tutor 对话建立可被后续交互控制和 Desktop 共同依赖的权威底座：明确 conversation/thread、fresh turn 与 learner-safe item 的边界，提供 conversation-level 持久事件流、snapshot/cursor、durable dispatch job、Celery wakeup 和周期 reconciler，同时保留旧 history/run SSE 的有界兼容。

## 依赖与范围

- 父任务：`08-13-codex-like-tutor-conversation-experience`。
- 本 child 是执行顺序第 1 个，无上游 child 依赖。
- 只建立底座，不实现 typed request、Queue/Steer/Interrupt/Retry、全局 cutover 或最终 Desktop 行为；这些分别由后续 Child 3、4、5、6 拥有。
- 当前工作树已有 schema、Tutor、prompt/Model Review 修改；必须保留并融合。

## 需求

### R1：协议版本与 turn lineage 基础

- 历史 run 明确为 `legacy_v1`，新路径可创建 `thread_turn_v2` fresh turn。
- 为 retry、request answer 与后续控制预留严格 scoped lineage 字段，不改变现有 Harness policy/capability/effect authority。
- public turn status 只暴露 `in_progress | completed | interrupted | failed`；内部状态继续保留。

### R2：Learner-safe item contract

- 定义 `TutorPublicItem` typed union：`message | process | elicitation | approval | error`。
- item 使用现有 message/process 与后续 typed request 的稳定 ID，不建复制所有内容的任意 JSON transcript。
- process 扩展仅使用受控 stage/state/label key；公开 display state 收敛为 `thinking | waiting_input | waiting_approval | waiting_authority | completed | interrupted | superseded | unavailable | failed`，禁止 raw reasoning、prompt、provider payload、trace、capability args、hidden tests/rubric。

### R3：Conversation event authority

- 新增 append-only `tutor_conversation_events` 和 conversation-global sequence。
- sequence/event append 与 owning mutation 同 transaction；支持幂等 event key。
- 提供 snapshot 和 conversation SSE，支持 scoped opaque cursor、断线续传、cursor too old/version mismatch 后安全重建。
- SSE 只读 public event 表，不调用 provider，不从 raw harness event 猜测 UI。

### R4：Durable dispatch authority

- 新增一 run 一行的 durable dispatch job、lease/CAS、retry/backoff 与 dead state。
- fresh turn transaction 同时创建 dispatch job；FastAPI `BackgroundTasks` 不再是唯一入口。
- worker 注册 interactive dispatch 和 reconcile task；PostgreSQL 为 authority，Celery 为 wakeup。
- periodic reconciler 恢复 pending/lease-expired job，并提供后续 Queue drain 扩展点。

### R5：Snapshot 与兼容

- snapshot 返回 conversation control version、active turn、pending request/Queue 占位结构、timeline page 与 stream cursor。
- 历史 conversation 无 event backfill 时仍能从 message/process 投影读取。
- 旧 run-local SSE/history 保留兼容；新 contract 版本化，旧客户端不被静默赋予新语义。

### R6：安全与可观测性

- event/job logs 只记录 IDs、enum、duration、attempt 和安全 diagnostic code，不记录 learner content。
- trace 可关联 conversation event、dispatch job 与 turn。
- bootstrap schema 重复执行、cutover delete inventory、fixture cleanup 顺序和数据库文档同步。

## 验收标准

- [ ] 同一 conversation 并发 append 公开事件仍产生无重复、严格递增 sequence；相同 event key 幂等返回同一结果。
- [ ] snapshot + SSE 重连能重建同一 timeline/active turn，重复事件不会生成重复 item。
- [ ] 创建 fresh turn 与 dispatch job 原子；强制中间失败不留下孤儿 turn 或无 job turn。
- [ ] Celery wakeup 丢失或 worker 在 lease 后崩溃时，reconciler 能重新 claim；重复 task 不重复 dispatch authority。
- [ ] 历史 `legacy_v1` conversation 在没有 conversation event rows 时仍能读取旧 message/process history。
- [ ] run-local SSE 保持兼容，新 conversation SSE 不读取或泄露 raw `tutor_run_events` payload。
- [ ] schema bootstrap、repository、route/SSE、worker import、Ruff、Mypy 测试通过。

## 范围外

- Queue 编辑/重排/立即执行的完整状态机。
- typed request response 与 authority receipt 业务语义。
- Queue、Steer、Interrupt、Retry 业务语义。
- 全局 v2 cutover、legacy retirement 与最终 Desktop UI。

