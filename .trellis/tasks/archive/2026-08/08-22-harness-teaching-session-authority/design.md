# 技术设计

## 1. 数据模型

### 1.1 Session root

在 `app/db/schema.sql` additive 增加 `tutor_teaching_sessions`。核心外键指向 user、LearningTrack、TutorConversation、knowledge key 与 active Lesson assignment/document。使用状态/mode check constraints、owner-scope composite foreign keys、optimistic `version` 和 partial unique index 保证同一知识点最多一个 current session。

不把当前 session 指针放入 localStorage；Desktop 保存的 knowledge pointer 只能用于导航请求，服务端读取后重新验证。

### 1.2 Checkpoints

`tutor_teaching_session_checkpoints` 使用 append-only row：

```text
id
teaching_session_id
predecessor_checkpoint_id?
session_version
objective_json
focus_json
suspended_focuses_json
unresolved_questions_json
covered_concepts_json
evidence_cursor_json
pause_reason
recommended_action_key?
authority_snapshot_json
source_run_id?
source_stimulus_id
schema_version / policy_version / source_hash
created_at
```

JSON 字段必须由 Pydantic typed DTO 严格生成和解析，限制数量、长度、enum 与 public fields。禁止 SQL update/delete 修改既有 checkpoint；测试覆盖 predecessor、单调 version 和 owner scope。

### 1.3 Run scope 与 stimulus

`tutor_run_teaching_scopes` 与 `tutor_runs` 一对一，保存 immutable session/checkpoint/version、mode、track/knowledge、assignment/document fence 与 stimulus identity。

新增 durable `tutor_run_stimulus_events`，统一记录三种 stimulus，但 payload 使用 discriminated union 和 kind-specific constraints。`learner_message` 必须有 message/input revision；`teaching_control` 必须有 closed control key/client action/expected versions；`domain_event` 必须有 source kind/id/version。数据库与 service 双层保证 exact one-of。

## 2. Repository 与 service

新增 learning/tutor 边界模块，职责分开：

- `TeachingSessionRepository`：SQL、owner scope、append-only checkpoint、CAS version。
- `TeachingSessionService`：open/resume、mode/action admission、authority refresh 与 learner-safe projection。
- `TutorTurnStimulusService`：创建/复用 durable stimulus，并与 fresh finite run 原子绑定。
- 现有 `TrackRepository` / `TutorRunRepository` 继续拥有 track conversation 与 run 生命周期，不复制其逻辑。

open 流程：

```text
读取 verified user + track + active plan/progress
-> 验证 knowledge available
-> 读取 active Lesson assignment/document
-> 创建或恢复 current teaching session
-> 生成 initial checkpoint（仅结构化 authority，不调用 provider）
-> 返回 session projection
-> 若调用方请求且 policy 允许，使用 teaching_control stimulus admission 一个 fresh run
```

## 3. API

最小路由：

```text
GET  /api/learning-tracks/{track_id}/teaching-sessions
GET  /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}
POST /api/learning-tracks/{track_id}/teaching-sessions/{knowledge_key}/open
POST /api/learning-tracks/{track_id}/teaching-sessions/{session_id}/actions
```

本 child 的 action endpoint 只负责通用 version/idempotency/stimulus admission 和 session mode/status mutation，不定义模型教学动作排序。响应提供 `schema_version`、session/checkpoint IDs、mode/status、authority identity、pending run 和空/基础 allowed-actions 容器，后续 child additive 扩展。

## 4. 与 Tutor runtime 的接点

扩展 run creation contract，teaching task kind 必须提供 `TutorTurnStimulus` 和 teaching scope。现有 learner message 路径转换为 `learner_message` stimulus，但保持消息/input revision authority。server/domain trigger 进入同一 interactive finite runtime，不经过 proactive scheduler。

提交路径在 transaction 内重新加载：run lease/status、stimulus、teaching scope、current session/checkpoint/version、assignment/progress。任何不一致返回 stale/superseded receipt，不修改 session。

## 5. 兼容与迁移

- 旧 `tutor_run_input_events` 保留，learner-message stimulus 可引用它；不 destructive generalize 旧表。
- 旧 conversation/message/run 缺少 teaching metadata 时继续按现有 snapshot/SSE 读取。
- 不从 message content、Lesson title 或本地 pointer 推断历史 session。
- feature gate 关闭时禁止新 teaching admission，但已有 session/checkpoint 可导出、重置和只读恢复。

## 6. 数据治理与隐私

将新表加入 cutover target inventory、scoped count query、export/reset/delete。export 只返回模式、状态、知识点、时间、bounded objective/unresolved summary；删除顺序先 run scope/stimulus/checkpoint，再 session root。trace 记录 enum/IDs/hash/version，不记录 raw payload body。

## 7. 测试设计

- PostgreSQL：约束、partial unique、append-only、CAS、bootstrap twice、bad insert。
- Repository：owner/track/conversation scope、lineage、stale predecessor。
- Service/API：open/resume、幂等、expected version、safe 404/409。
- Runtime：三种 stimulus、exact one-of、无伪造 message、无 proactive admission、stale fencing。
- Governance：cutover exhaustive classification、export privacy、reset/delete child-to-root。
