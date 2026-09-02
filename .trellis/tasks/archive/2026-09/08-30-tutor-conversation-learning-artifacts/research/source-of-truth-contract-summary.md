# 当前 Source of Truth 合同摘要

## Runtime 与 Authority

- Aearn 当前正式 runtime 是 Tutor Harness；LearningTrack、LessonDocument、Exercise Gate/Attempt、ReviewSession、TeachingSession/checkpoint/action receipt、conversation snapshot/SSE 和 context references 都是现有 authority。
- Desktop 只呈现服务器投影，不计算 score、pass、mastery、unlock、due、execution tier 或题目答案。
- 新 Learning Artifact 必须作为 facade/interaction projection 复用这些 authority，不得建立第二套评分、进度或 conversation。

## Conversation 与 SSE

- 普通 learner message 创建 fresh finite TurnRun；active turn 下普通 Send 当前进入 Queue。新 Artifact 设计要显式引入 branch/priority contract，不能从消息正文猜关联。
- Snapshot 是 timeline/control/request 的唯一恢复 authority；conversation SSE 只做有序通知，除 validated turn_output 外由客户端节流刷新 snapshot。
- 当前 snapshot v3，事件 kind 固定 turn/item/control/dispatch/turn_output；新 Artifact 应使用 item_added/item_updated 并发布新 snapshot 版本，而不是增加大量临时 UI 事件。
- SSE payload 不携带 raw learner code、submission、hidden test、rubric、provider body/reasoning、command/path/container/secret。

## Teaching

- 一条 LearningTrack 只有一条长期 learner-visible Tutor conversation；TeachingSession 只是 knowledge-scoped authority segment。
- checkpoint/action receipt/message/run terminal 必须原子持久化；authority/stale/lease/version 变化 fail closed。
- Provider 只能选择 reviewed exact contract/candidate，服务器拥有 action identity、schema、scope、verification 和效果。
- 新 artifact response mode 必须由 deterministic gate 校验 exact candidate handle；无合法 handle 的 edit/run/query/review 指令不得公开。

## Learning / Attempt / Execution

- ExerciseVersion/private rubric/Gate binding 是共享/冻结内容；Attempt、submission、result、hint、execution link 是 user/track/assignment scoped authority。
- 完整 submission 只进私有表；公共 result 只允许安全、bounded、redacted projection。
- public execution tier 只有 reviewed immutable image lock + compatible health 才能是 container_verified；当前 lock 为空，本地 runner/preview 只能标记 teaching_local 或非权威体验。
- Browser Preview、SQL、TypeScript 等现有 runner 可复用，但不能让 Preview 成为 mastery 证据。

## Model Review

- 已有 model review authoring/candidate/validation/publication/private rubric/evidence authority；provider candidate 与 server-owned tests/rubric 分离。
- 新 v2 应 additive 扩展 diff/hash/hunk/finding，不改写 v1 历史。

## Sources

- Lesson source snapshot/citation 和 tutor_message_context_references 已保存 exact user/track/document/version/block/hash 与 bounded excerpt。
- 新 Artifact source refs 应复用该 validator/projection，不复制完整文档或按文本猜测定位。

## Database

- Schema 由 manifest ordered fragments 重复 bootstrap；新增 fragment 必须显式加入 manifest。
- 所有 user-owned tutor_* 表必须进入 cutover target inventory、export/reset/delete；shared immutable catalog/item/rubric 必须进入 shared allowlist。
- Scope FK、one-of owner、partial unique、CAS/idempotency、append-only/lifecycle trigger 和 bootstrap twice 是 P0。

## Desktop

- 正式 Desktop 在 aearn/apps/desktop；TutorConversationSurface 拥有 timeline/SSE/Composer。
- 所有 API payload 从 unknown 严格解析 closed union；未知 enum/extra field 是可见 contract error。
- 交互必须覆盖 1440x900、900x900、390x844，无页面级水平溢出，键盘/focus/reduced-motion/console clean。
- 右侧区域是 Lesson/文档来源，不应改造成 Artifact 工作区；Artifact 在对话流渲染。
