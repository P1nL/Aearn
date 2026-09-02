# 仓库现状证据

## 当前运行时边界

- 正式运行目录是 `aearn/`，`docs/` 是 source of truth；受保护原型 `docs/design/learning-agent-claude-desktop-framework.html` 不得删除。
- 当前 Tutor conversation 是 snapshot-first：`tutor_conversation_snapshot_v3`，conversation SSE 事件仅有 `turn_created | turn_updated | item_added | item_updated | turn_output | control_updated | dispatch_delayed | dispatch_dead`。证据：`aearn/services/api/app/services/tutor/conversation_contracts.py:13-17,45-53`。
- 当前公共 timeline item union 只有 `message | process | elicitation | approval | error`，没有 artifact。证据：`aearn/services/api/app/services/tutor/conversation_contracts.py:240-254`。
- Desktop 只对 `turn_output` 做局部 reducer，其他 SSE 事件触发节流 snapshot refresh。证据：`aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx:304-324,450-456`。
- 当前 Teaching learner response mode 只有 `none | composer`。`TeachingActionDescriptor.target_kind` 虽允许 `artifact`，当前 shelf builder 只构造 teaching-control 与 navigation。证据：`aearn/services/api/app/services/learning/teaching_contracts.py:328-343,374-381`；`aearn/services/api/app/services/learning/teaching_loop.py:178-228`。
- Desktop 当前把 artifact target 与 navigation 一并转发，没有 artifact 渲染或动作实现。证据：`aearn/apps/desktop/src/features/learning/useTeachingWorkspaceController.ts:161-179`。
- 当前 Lesson Gate 使用 textarea、hint/run/submit 和同卡结果；它不是 Tutor 对话内的工件系统。证据：`aearn/apps/desktop/src/features/learning/lesson/LessonGatePanel.tsx:99-143`。
- `SafeExecutionResultV1` 只有 stdout、stderr、测试反馈、计数、时长和 diagnostic code，没有浏览器预览或表格结果。证据：`aearn/packages/shared/aearn_shared/execution/contracts.py:361-419`。
- Gate scorer 只把 SafeExecutionResult 投影成状态、stdout/stderr、计数和 tests，不能承载 SQL grid。证据：`aearn/services/api/app/services/learning/practice/policies.py:34-64`。
- Desktop 已依赖 `@monaco-editor/react@^4.7.0`、`@assistant-ui/react@0.14.7` 和 `partial-json`。证据：`aearn/apps/desktop/package.json:13-21`。
- Tauri 主窗口当前 `csp=null`，默认 capability 只绑定 main window。证据：`aearn/apps/desktop/src-tauri/tauri.conf.json:12-24`；`aearn/apps/desktop/src-tauri/capabilities/default.json:1-7`。

## 现有可复用权威

- LearningTrack、LessonDocument、ExerciseVersion、Gate、Attempt、ReviewSession、TeachingSession、checkpoint、Action receipt 和 context reference 已有 server-authoritative contract；新工件不得复制第二套评分或掌握度状态机。
- 当前 exercise type 已含 `code_completion | sql_query | browser_preview | static_code_reasoning | model_code_review`。
- 当前 Runner registry 已有 browser、Python、TypeScript、SQL、Java/Go/C# 教学能力；公开 container-verified 仍因 reviewed image lock 为空而不可声称可用。
- Model code review 已有 v1 authoring/publication/private rubric/structured submission，可扩展 v2 diff，而不是重建。
- Lesson source snapshots、citation 和 message context references 已有稳定 hash/version/scope 约束，可供 A10 复用。

## 架构结论

1. 问题不是缺少若干 SSE event name，而是缺少 artifact authority、public projection、动作协议和教学交接。
2. Artifact 必须成为现有 TutorPublicItem 的新成员，继续沿用 item_added/item_updated + snapshot recovery。
3. 工件是对话时间线内容，不建立另一个中央工作区或第二条 conversation。
4. 浏览器实时预览只作为本地非权威反馈；Run 是用户显式触发的服务端权威验证。
5. 题库必须建立在 immutable Learning Item、私有 rubric/test、机器验证和审核发布之上，不能让在线模型临时出题后直接评分。
