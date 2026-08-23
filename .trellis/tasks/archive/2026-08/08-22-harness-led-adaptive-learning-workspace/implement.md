# 实施计划

## 1. 执行策略

父任务不作为实现目标，不运行 `task.py start`。依次启动、完成、检查、提交并归档四个 child；每次只启动一个 dependency-satisfied child，禁止并行建立相互竞争的 schema/API authority。

实施顺序：

1. `08-22-harness-teaching-session-authority`
2. `08-22-harness-closed-teaching-action-loop`
3. `08-22-guided-free-reading-workspace-ui`
4. `08-22-adaptive-learning-integration-evals`

每个 child 开始前必须运行 `task.py start <child>` 与 `task.py current --source`，并确认 current 精确指向该 child；随后加载 `trellis-before-dev`。Inline 模式不派发 implement/check sub-agent。

## 2. Child 1 — Teaching session authority

1. 增加 additive schema、约束、索引与 bootstrap-twice coverage。
2. 实现 session/checkpoint/run teaching scope typed contracts、repository 与 service。
3. 实现 learner message / teaching control / domain event exact one-of stimulus，不伪造 learner message、不滥用 proactive。
4. 增加 open/resume/read/action admission 的基础 API 和 version/idempotency fence。
5. 更新 cutover inventory、export/reset/delete、privacy 与 cross-user tests。
6. 保持旧 conversation/history 可读，不回填猜测型 teaching state。

## 3. Child 2 — Closed teaching action Loop

1. 发布 `tutor.lesson-teaching@1.0.0` 专用 Skill 与 closed teaching action schema。
2. 扩展 provider decision/context，使 teaching run 必须携带 current stimulus、required teaching session 与 server-provided handles。
3. 实现单步主动、逐段停顿、焦点栈、未解决问题、纠正覆盖和 stale result fencing。
4. 原子提交公开 Tutor message、checkpoint、pause state、receipt 与 Action Shelf projection。
5. 实现 completion pause 和显式 `进入下一知识点` 的 roadmap revalidation；禁止自动 next Turn。
6. 使用 fake provider 编写自然分支、恢复、interrupt、provider unavailable 与预算测试。

## 4. Child 3 — Guided/自由阅读 Desktop

1. 扩展 `types.ts` / API parser，对所有新 payload 按 `unknown` 严格校验。
2. 建立 teaching workspace controller，保持一份 Tutor surface、一份 Lesson document 与一套 SSE。
3. 实现 Guided/Free Reading 主次换位及中间顶栏双向转换箭头。
4. 实现 current session 展开、历史 session 折叠只读和 exact cross-session reference。
5. 实现 Guided 文档混合跟随、`follow_paused`、`回到当前讲解` 与 reduced-motion。
6. 实现 Composer Action Shelf 与 runtime controls、blocking typed request、artifact-local actions 的互斥。
7. 覆盖 1440×900、900×900、390×844、键盘、focus、无横向溢出和 mode mutation conflict。

## 5. Child 4 — 集成、评估与文档

1. 接通 Gate/Attempt、ReviewSession、progress、assignment/migration terminal domain events。
2. 完成 structured teaching summary、跨 session 检索、压缩保护与 stale rebuild。
3. 扩展 deterministic eval：连续追问、纠正、跨日恢复、自由阅读、completion、provider unavailable、stale run。
4. 完成 cutover inventory exhaustive classification、bootstrap twice、export/reset/delete 与 privacy audit。
5. 更新 `.trellis/spec/**` 和 `docs/README.md` 指向的 source-of-truth 文档。
6. 运行完整跨层质量门，不调用真实 provider。

## 6. Focused 验证

实际文件名可在实现中新增，但至少覆盖以下现有/计划测试：

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/test_db_bootstrap.py `
  tests/test_harness_cutover.py `
  tests/test_tutor_run_repository.py `
  tests/test_tutor_context_builder.py `
  tests/test_tutor_run_loop.py `
  tests/test_tutor_routes.py `
  tests/test_tutor_sse.py `
  tests/test_tutor_context_summary.py `
  tests/test_tutor_context_references.py `
  tests/test_lesson_documents.py `
  tests/test_review_sessions.py `
  tests/test_learning_agent_integration_matrix.py `
  tests/test_tutor_teaching_sessions.py `
  tests/test_tutor_teaching_action_loop.py `
  tests/test_tutor_teaching_context.py -q

pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
```

## 7. 完整质量门

每个 child 运行与其范围相关的 focused tests；Child 4 和父任务集成复核运行完整质量门：

```powershell
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate <current-child>
git diff --check
```

数据库必须使用本地 PostgreSQL 对同一空 schema 连续执行两次 bootstrap，并运行现有 bootstrap/cutover inventory regression。UI 变更必须在 `http://127.0.0.1:1420` 使用 disposable fake App Server/provider 完成 browser smoke：

- 1440×900、900×900、390×844；
- Guided 首个单步教学后停止；
- 插问、换例子、返回主线；
- Guided/Free Reading 双向换位；
- 文档手动操作后不抢滚动，显式恢复跟随；
- Action Shelf 互斥与草稿/reference 保留；
- completed 后不自动进入下一知识点；
- refresh/SSE reconnect 恢复同一 session；
- DOM/console/network 无 protected data、framework overlay、相关 error/warning 或水平溢出。

默认禁止真实 provider。真实 provider smoke 只有用户在实施线程再次明确批准后才允许运行，并且不能替代 fake provider 确定性测试。

## 8. 文档与 spec 更新

按 Child 4 的最终实现同步：

- `docs/architecture/database-schema.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/product/user-flows.md`
- `docs/setup/development-environment.md` 或现有 QA 入口
- `.trellis/spec/backend/index.md` 及相关数据库、Harness、context、QA contracts
- `.trellis/spec/frontend/index.md` 及 component、state、type-safety、quality contracts

不得创建与上述 source of truth 重复的平行规格。

## 9. 风险文件与回滚点

高风险区域：

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/services/tutor/**`
- `aearn/services/api/app/agents/harness/**`
- `aearn/services/api/app/services/learning/**`
- `aearn/services/api/app/routes/tutor.py`
- `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx`
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`

每个 child 的工作提交前必须检查完整 diff，保护既有用户修改。回滚只关闭新 admission/presentation feature gate 或恢复旧布局读取路径；不删除已持久化 session/checkpoint，不把 authority 回退到 localStorage，不重写历史 conversation。

## 10. 完成门

- 四个 child 按依赖顺序分别实现、检查、提交并归档。
- P0/P1 验收映射完整，父任务 PRD 的每条跨层验收都有自动测试或 browser evidence。
- 没有真实 provider、push、部署或生产数据修改。
- 不覆盖或提交 `.trellis/tasks/.obsidian/plugins/translate/data.json` 与 `.trellis/tasks/.obsidian/workspace.json`。
- 最终按 Phase 3.3 更新 spec/docs，Phase 3.4 创建范围清晰的工作提交；全部 children 归档后再决定父任务归档。
