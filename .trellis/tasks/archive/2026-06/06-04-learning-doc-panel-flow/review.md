# Planning Review: learning-doc-panel-flow

## 结论

当前任务仍处于 planning。`prd.md`、`design.md`、`implement.md` 已补齐到可 review 状态，但按照当前 workflow-state，实施前必须由用户确认规划，然后再运行：

```powershell
python .\.trellis\scripts\task.py start .\.trellis\tasks\06-04-learning-doc-panel-flow
```

## 用户已确认的产品决策

- 左侧「复习」栏可以显示未到期复习项。
- 未到期复习项必须禁用点击。
- 未到期项不能跳转复习页，不能发送 `POST /api/reviews/start`。
- 推荐文案：`未到期 · 下次 MM-DD HH:mm`；如缺少 `due_at`，降级为 `已安排，未到期`。

## 当前代码事实核对

- 学习会话后端入口是 `aearn/services/api/app/routes/learning_sessions.py`。
- 学习会话状态和初始 tool call 由 `aearn/services/api/app/services/repositories/learning_session_repository.py` 组装。
- 当前 DB CHECK 不允许 `documentation_reading`，如采用该新阶段必须同步更新 schema 和类型。
- 计划详情 `GET /api/plans/{id}` 当前不返回 `ReviewState`，复习侧栏要实现禁用态需要先补后端数据。
- 当前复习页今日队列只展示 `due_at <= now()`，后端 `POST /api/reviews/start` 会拒绝未到期项。

## 推荐执行顺序

1. Phase 0：先修复复习侧栏到期/未到期语义，直接解决截图问题。
2. Phase 1：新增知识点文档读取 API。
3. Phase 2：新增右侧文档面板 MVP。
4. Phase 3：新增主动触发概念检验。
5. Phase 4：实现文档引用到对话。
6. Phase 5：修复练习反馈消息顺序。
7. Phase 6：后端、前端、Trellis 和手工 smoke 收口。

## 风险

- 任务范围较大，建议至少把 Phase 0 作为第一批独立可验证修复。
- `documentation_reading` 是新阶段，涉及 DB CHECK、前后端类型、API contract 和 learning graph/tool transition。
- 文档生成如果强依赖模型配置，会影响本地未配置模型的学习入口；MVP 推荐先用现有 lesson outline/chunks 组装结构化文档。

## 准备状态

- [x] PRD 有明确需求和验收。
- [x] 设计已对齐当前代码路径。
- [x] 实施计划已按可验证阶段拆分。
- [x] 当前截图问题已纳入 Phase 0。
- [ ] 用户确认规划后启动 implementation。
