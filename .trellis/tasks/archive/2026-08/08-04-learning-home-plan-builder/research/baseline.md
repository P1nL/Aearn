# 学习首页与计划制定仓库基线

## 已冻结的后端基础

- `aearn/services/api/app/models/learning_tracks.py` 已定义完整 `LearningPlanDraft`、track list/detail/roadmap/revision public contract。
- `aearn/services/api/app/services/learning/contracts.py` 已冻结 `LearningPlan`、stable key、DAG、canonical hash、`LearningScopeKind.PLAN_DRAFTING`、`LearningTaskKind.PLAN_DRAFTING` 和四级 `ExecutionTier`。
- `aearn/services/api/app/services/learning/track_repository.py` 的 `create_track` 已在同一 repository transaction 中创建 track、active revision、modules/nodes、initial progress，并可把 conversation 绑定到新 track。
- `aearn/services/api/app/services/learning/track_service.py` 的 list projection 已返回 progress、当前节点、`review_due_count` 和 `execution_tier`；当前 review child 尚未接管时 due count 为 0。
- `docs/architecture/api-contract.md` 与 `database-schema.md` 已把 `/api/learning-tracks`、复合 user scope、plan revision 和 execution tier 记录为当前 contract。

## Tutor Harness 复用边界

- Tutor input 已支持 additive `learning_scope`；first/ordinary input 能快照 `plan_drafting/plan_drafting`，ordinary input 创建 fresh finite `TurnRun`。
- `TutorInteractiveRunDispatcher` 当前使用 `DefaultDenyCapabilityPolicyResolver`、`DefaultDenyCapabilityGateway` 和 `DefaultDenyEffectCommitter`，因此生产交互式流还不能执行任何 Skill/capability/effect。
- default catalog 当前只有 `grounding.retrieve` capability；`CatalogTutorDecisionGate` 已提供 exact Skill、policy、revision、budget 和 selected-Skill gate，可直接扩展。
- `TutorPayloadField` 仍限制最多 12 个字段、单值最多 360 字符；规划设计通过 compact capability-specific JSON 字段复用该上限，不扩大通用 envelope。
- capability invocation 表只保存 request/result hash、catalog/policy/Skill/lease/status 等安全元数据，不保存 argument/result body；完整计划草案应进入新的 user-scoped domain table，而不是通用 receipt。
- current-input、usage/cache、adaptive budget、summary/compaction 和 eval contract 已在前置任务完成，新的 planner composition 不应修改这些优先级或计量语义。

## 语言与来源

- `language_capabilities.py` 已覆盖 Python、JavaScript、TypeScript、SQL、Java、Go、C#、HTML/CSS、Rust、C++，并分别暴露 public selection、lesson/exercise/execution/review、trust policy 和 UX disclosure。
- `ExecutionTierResolver` 已是 LearningTrack 的单一 tier authority；public 无 reviewed image lock 时不会声明 `container_verified`。
- grounding source registry 与预索引事实已经存在，计划草案只需投影 registry-owned source summary，不应接受模型任意 URL/source target。

## Desktop 基线

- `App.tsx` 当前顶层状态为 loading/welcome/cutover/tutor；verified 后直接进入 conversation-first `TutorWorkspacePage`，左栏是“新对话/最近对话”。
- `TutorWorkspacePage` 内聚了 history hydrate、SSE、composer、continuation、activity/memory/plan preferences，planner 若直接复制会产生第二套 run lifecycle，应先提取可复用 conversation surface。
- `api.ts` 和 `types.ts` 尚无 LearningTrack、language catalog 或 planning session 类型；Desktop 当前也未发送 `learning_scope`。
- Desktop package 只有 TypeScript/Vite build，没有 Vitest/Testing Library；响应式与可访问性需要本地浏览器 smoke 补充，不能把 build 当成交互证明。
- `styles.css` 与受保护原型已提供当前奶油色桌面视觉和居中 conversation 参考；原型中的旧 onboarding/Graph 语义不得恢复。

## 文档差异

- `docs/product/user-flows.md` 的旧对话步骤仍描述先创建空 conversation、后续输入复用 live run；当前 API/runtime contract 已改为 first-turn 原子创建和 ordinary input fresh run。本 child 更新产品流程时必须以当前代码/API 文档为准修正该差异。
- `docs/product/frontend-interaction-spec.md` 当前仍把 verified `tutor` 直接描述为 conversation workspace；本 child 实装后应改为 verified shell 内的 LearningTrack 首页与次级 general history。

## 设计结论

1. 不新增 Trellis 任务，不启动父任务；本 child 同时承担 planner backend seam 与 Desktop 首页/规划 UI。
2. planning session 需要独立持久化根和 append-only draft，因为 Conversation 不能成为正式计划或确认状态的唯一 authority。
3. `learning.plan.draft` 使用 exact Skill + task-aware policy +显式 handler；确认保持独立 HTTP 用户动作，不做模型 effect。
4. 通用 Tutor envelope、context budget、usage/cache、summary 和 safe projection contract保持不变。
5. Lesson/Review/完整 learning workspace 未交付时，首页 CTA 只能发出稳定 intent 与真实未就绪状态，不能伪造教学内容或执行结果。
