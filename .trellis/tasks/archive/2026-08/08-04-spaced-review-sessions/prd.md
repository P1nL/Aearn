# 间隔复习、ReviewSession 与掌握度调度

## 目标

在每个 LearningTrack 下建立动态间隔复习队列和结构化 ReviewSession，使复习由已验证 mastery evidence 驱动，而不是固定章节或聊天历史猜测。

## 依赖

- `08-04-learning-track-plan-mastery-domain`。
- `08-04-exercise-gates-execution-unlock`。
- `08-12-tutor-authoritative-context-facts`：ReviewSession 必须消费服务器权威目标、偏好、当前 track facts 和 correction lineage，不能从聊天历史重新推断。

## 需求

### R1 — Track-scoped 复习队列

- 每个 knowledge_key 有独立 review schedule state，绑定 user + track。
- 首页卡片投影到期数量；学习页左栏提供今日复习入口。
- 普通到期复习不自动阻止继续课程；只有关键前置知识明显遗忘时，才可成为依赖节点的短 Gate。
- due、risk 和 gate 必须由服务端计算，前端不得自行比较日期决定可点击性。

### R2 — ReviewSession

- 复习在中间主区域呈现独立 ReviewSession，支持 warmup、正式练习、反馈和 final summary。
- warmup 只用于选择和诊断，不直接写 mastery/review schedule。
- 中间练习结果先写 append-only attempt；只有 session finalization 才聚合更新 schedule 和 mastery state。
- session、item、finalization 和重放均有版本与幂等保证。

### R3 — 调度和 Evidence

- 复用现有 FSRS/候选池/评分算法时迁入新的 track-scoped repository，不重新开放旧 Review API 和旧表。
- 独立完成与提示后完成对下一次间隔产生不同影响。
- 模块诊断跳过的知识点进入低频复习候选，避免一次诊断永久豁免。
- 计划版本变化使用稳定 knowledge_key 保留 schedule；删除/替换节点通过 migration 显式处理。

### R4 — 复习题型

- 优先测试回忆、迁移和应用，不默认完整重播 LessonDocument。
- 可包含普通代码练习、解释题和模型代码审核练习；题型必须服从语言 execution tier。
- 无法生成覆盖当前薄弱能力的合格题时保持 session 可恢复并返回稳定错误，不用低质量 fallback。

## 验收标准

- [ ] 到期数量、今日复习列表和关键前置 Gate 均由服务端权威投影并严格 track scoped。
- [ ] warmup 不写长期状态；finalization 只执行一次并聚合更新 mastery/schedule。
- [ ] 独立完成、提示完成、失败和关键能力失败产生不同调度结果。
- [ ] 普通到期复习不阻止课程；关键前置遗忘的短 Gate 有明确证据和补救路径。
- [ ] 计划 revision 切换后稳定 knowledge_key 保留复习状态，不产生跨 track 污染。
- [ ] 模块诊断跳过内容进入低频复习候选。
- [ ] 候选池不足不会生成无质量门的 fallback 练习。
- [ ] ReviewSession context 使用 `AuthoritativeContextSnapshot`，已确认学习目标/时间/偏好在 resume、history 截断和 summary 暂不可用时保持一致。
- [ ] FSRS/property、batch、idempotency、cross-user、API 和回归测试通过。

## 范围外

- 重新注册旧 `/api/reviews` 路由或使用旧 `review_states` 作为 active authority。
- Desktop 三栏整体布局；本任务只提供复习 domain/API contract。
- 生产通知和跨设备提醒。
