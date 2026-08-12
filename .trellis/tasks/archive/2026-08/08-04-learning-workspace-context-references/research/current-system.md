# 当前系统调研

## 已确认入口

- `aearn/apps/desktop/src/App.tsx`：当前 Tutor surface 仅有 learning home、plan builder、独立 Lesson 和 Review 占位。
- `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx`：Lesson/Gate/执行/模型审核均已消费服务端 authority，可改为嵌入工作区并暴露引用回调。
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`：已有 history abort、SSE cleanup、fresh TurnRun 与 continuation 分流，但仅 plan drafting 会发送 scope。
- `aearn/services/api/app/services/tutor/public_api.py`：`_mutate` 提供外层幂等事务；input acceptance 后 snapshot run scope，适合原子追加引用快照。
- `aearn/services/api/app/services/tutor/interactive.py`：current learner input 是最高优先级，learning authority 以独立 descriptors 追加。
- `aearn/services/api/app/services/learning/reviews/service.py`：Review queue/session/attempt 已只返回 learner-safe projection。

## 关键结论

1. 引用不能只存在于前端，否则无法满足 message/run revision 绑定、跨 scope 拒绝、刷新重放与模型上下文要求。
2. 不应把 excerpt 或 feedback 拼进 learner content；需要独立 append-only safe snapshot。
3. Conversation 只绑定 track，task/knowledge 绑定 fresh TurnRun；工作区应复用该现有边界。
4. 当前没有通用 PracticeSession API，因此 MVP Practice 使用 Lesson Gate 与 Model Code Review，而不是客户端伪造新权威。
5. 导航恢复可使用非权威本地指针，但所有 artifact 必须在恢复时由服务端重新读取和验证。
