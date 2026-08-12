# 当前系统调研

## 已验证的现状

1. 正式教学 authority 位于 `tutor_learning_tracks`、不可变 `tutor_track_plan_revisions`、`tutor_track_node_progress`、`tutor_mastery_evidence` 与 `tutor_mastery_states`。
2. `LearningTrackService._project_track` 仍把 `review_due_count` 固定为 `0`，尚无 track-scoped 复习投影。
3. 正式练习使用不可变 `tutor_exercise_versions` / private rubric 与 append-only `tutor_exercise_attempts`、submission、result；现有 executor trusted-input 只依赖 Attempt、submission、ExerciseVersion 和 rubric，因此可复用于 review owner。
4. 旧 `review_states`、`review_logs` 与 `app/services/repositories/review_scheduler.py` 属于历史运行时；可迁移纯调度思想，但不能作为 active authority 或重新开放旧 `/api/reviews`。
5. `AuthoritativeContextSnapshot` 已是服务器权威上下文类型；ReviewSession 可使用同一类型保存由 LearningTrack、用户偏好、当前计划与 mastery 构成的冻结快照，从而不依赖聊天 history 或 summary。
6. 模型代码审核已进入统一 `ExerciseVersion` 与确定性评分链，可作为 ReviewSession 候选；普通代码练习继续服从 `execution_tier`。
7. `diagnostic_skipped` 已是正式节点状态和 mastery evidence 来源，但尚未建立低频 schedule。
8. 计划迁移依赖稳定 `knowledge_key`，当前激活流程保留同 key 进度；复习 schedule 需要在同一激活事务内显式 retained/suspended migration。

## 关键约束

- warmup 不创建 Attempt、不写 mastery、不修改 schedule。
- 正式 item 每次提交创建一个 `review_submit` Attempt；中间结果只终结 Attempt。
- 只有 finalization 在同一事务内聚合写入一条 review mastery evidence、一条 schedule event，并更新 schedule projection。
- 候选不足必须返回可恢复的稳定状态，不生成未经质量门的题目。
- 所有读写严格绑定 `user_id + track_id`，并使用幂等键、request hash 和 expected version。
- 导出只包含安全摘要；submission 全文、private rubric、隐藏测试和内部 context hash 材料不导出。
