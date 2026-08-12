# 仓库基线与复用边界

## 当前权威运行时

- `docs/README.md:5-11` 与 `docs/architecture/tutor-harness-runtime.md:27-36` 确认当前产品运行时是 Tutor Harness，旧 Graph/router/SDK 运行时已经退出 active source tree。
- `aearn/services/api/app/main.py:25-30` 当前只注册 health、users、courses、environment、harness cutover 和 Tutor 路由；旧 plans/learning/review 路由未注册。
- `docs/README.md:42-46` 明确旧 Attempt、FSRS、隐藏测试和计划数据不能被 active Tutor API 重建或修改，但相应算法与安全原则仍可在新领域边界内复用。

## Harness 与长期会话

- `docs/architecture/tutor-harness-runtime.md:38-55` 定义长期 `TutorConversation` 与每条普通消息的 fresh finite `TurnRun`。
- `docs/architecture/tutor-harness-runtime.md:156-170` 定义 exact Skill、default-deny capability/effect、registry-only grounding 和事务 effect 边界。
- `docs/architecture/tutor-harness-runtime.md:188-196` 已有不可变 plan revision、active pointer、memory 与 learner controls，但当前 plan 是 user-level 概要，不支持多个 LearningTrack。
- `aearn/services/api/app/db/schema.sql:1593-1630` 的 `tutor_plan_revisions` / `tutor_active_plans` 以 user 为 active key，无法直接承载同一用户的多个语言学习主线。

## 旧领域能力与新领域隔离

- `aearn/services/api/app/db/schema.sql:72-144` 保留旧 `learning_plans`、`plan_modules`、`knowledge_points`；`228-264` 保留 Attempt/ReviewState；这些表不能重新成为 active 产品路由的权威状态。
- `aearn/services/api/app/db/schema.sql:268-316`、`services/repositories/review_scheduler.py` 和 exercise services 含可复用的候选池、FSRS、评分与审核题算法；复用时必须迁入新的 track-scoped contract，不能直接重新开放旧 API。
- 新表应使用 `tutor_` 前缀并绑定 `user_id + learning_track_id`，使其与已退休旧领域表和现有 Harness 表边界清晰。

## Grounding

- `aearn/services/api/app/services/grounding/grounding_sources.py:30-240` 已有语言官方/可信来源注册表；`273-309` 有 registry 完整性与 trust policy 校验。
- `aearn/services/api/app/services/tutor/grounding_lookup.py:12-48` 已有 bounded query/result contract；`51-95` 的实现只在注入的预索引 chunk 上检索，不执行开放网络访问。
- `aearn/services/api/app/db/schema.sql:522-556` 已有持久化 grounding chunk 和 reindex run，可作为 LessonDocument 来源快照的输入，而不是最终教学文档本身。

## Runner 与 Executor

- `aearn/services/api/app/services/runners/language_capabilities.py:65-281` 已有 Python、JavaScript、TypeScript、SQL、Java、Go、C#、HTML/CSS、Rust、C++ 能力矩阵。
- `aearn/services/api/app/services/runners/runner_registry.py:121-246` 的本机 runner 是 teaching-grade，明确不是 container-grade；适合受控本地/MVP验证。
- `aearn/infra/executor/runtime-catalog.json:1-69` 已定义七个固定 container runtime protocol；`image-locks.json:1-5` 当前没有 reviewed image lock，因此 container executor 必须保持 safe unavailable。
- `aearn/services/api/app/db/schema.sql:854-896` 已有 Tutor execution intent/job 生命周期，但 intent 当前指向旧 `exercises`；新练习版本需要兼容迁移为明确 one-of artifact reference，不能复制第二套 executor 生命周期。

## Desktop

- `aearn/apps/desktop/src/App.tsx:128-232` 当前 bootstrap 为 loading/welcome/cutover/tutor，verified 后直接进入 conversation-first Tutor workspace。
- `aearn/apps/desktop/src/App.tsx:163-179` 当前左栏是最近对话；新产品需要把 verified 后的主入口改成 LearningTrack 首页，并把 conversation 移到学习页右栏。
- 外层 cutover authority 不变；在 `tutor` verified shell 内增加 `learning_home | track_planner | learning_workspace` 产品视图，可以避免恢复旧 router 和旧页面。

## 设计结论

1. 保留 Tutor Harness、finite TurnRun、cutover、safe projection、Skill/capability/effect 和 executor 生命周期。
2. 新建 track-scoped Tutor 教学领域，不恢复旧 `learning_*` API/Graph。
3. 复用 grounding registry/index、runner adapter、FSRS/评分/题目校验算法时，必须通过新 contract 和新表适配。
4. 当前 user-level `tutor_plan_revisions` 保持历史兼容；不从其自由文本 outline 自动推断语言或生成 LearningTrack。
5. 公开执行只允许 `container_verified`；`teaching_local` 只能进入开发/fixture composition。
