# 技术设计

## 1. Skill 与 provider contract

发布版本化 `tutor.lesson-teaching@1.0.0`，声明可读 authority、允许的 teaching action、输出 schema、预算和禁止边界。provider request 明确：最新 learner input 优先；只解决一个中心问题；引用 exact Lesson/evidence handle；不得生成 UI schema、数据库 target、mastery 或路线 mutation。

扩展 typed decision union，新增 `teaching_step` 分支：

```text
TeachingStepDecision(
  action,
  objective_id,
  focus_id,
  source_handles[],
  public_message,
  focus_resolution,
  pause_kind,
  escalation_hint?,
)
```

所有字段 strict、closed、长度有界，未知 action/handle/extra field 拒绝。

## 2. Context builder

新增 `TEACHING_SESSION` required section，在 `CURRENT_INPUT/CURRENT_TEACHING_EVENT` 后、optional history 前。section 只含 session/checkpoint projection、objective/focus stack、unresolved questions、covered summary、mode、authority versions、allowlisted handles 与 pause/action policy。

required payload 超预算时不驱逐；直接产生 stable fail-closed terminal。recent messages、旧 session summary、memory/activity 按现有预算规则驱逐，不能覆盖 current input/focus。

## 3. Decision gate 与 commit

执行链：

```text
load immutable run scope + stimulus
-> build required teaching context
-> provider selects one closed action
-> validate action/focus/handles/policy/version/budget
-> derive learner-safe public message
-> derive next bounded focus/checkpoint/pause
-> derive server-owned Action Shelf
-> atomically persist message + checkpoint + receipt + terminal run
```

commit 前重新读取 run lease/status、session/checkpoint/version、assignment/progress 和 stimulus。stale 或 superseded 返回 typed receipt，不公开旧 output。

## 4. Focus reducer

Aearn reducer 接受 closed `focus_resolution`：

- `stay`；
- `push_child`；
- `resolve_and_resume_parent`；
- `replace_objective`；
- `abandon_branch`；
- `wait`。

模型不能提交任意 focus JSON。server 使用 current checkpoint + validated decision 生成下一 bounded state。栈深、未解决问题数、摘要长度超过阈值时先压缩；不能压缩 active focus、最新纠正或唯一 evidence handle。

## 5. Pause 与 admission

run terminal 后必须写一个 pause kind。Action Shelf 根据 pause/runtime/request/mode/completion 状态生成：

- soft pause：继续、换例子、暂停等；
- answered interruption：返回主线或按推荐继续；
- free reading escalation：转为引导讲解；
- evidence pause：前往/查看 Gate 或等待结果，不复制 Submit；
- completion pause：进入下一知识点、查看反馈、开始复习、返回路线。

普通 shelf 不负责 mode-switch 顶栏按钮，也不包含 artifact-local submit。active run 时由 runtime controls 接管；blocking request 时 request presentation 接管。

## 6. Completion transition

当 progress authority 变为 completed：

1. 当前 session 标记 completed/completion pause；
2. 写 bounded completion summary 与真实 evidence handles；
3. 读取最新 roadmap projection，返回 candidate next available node；
4. 不修改 Desktop pointer，不创建 next run。

`enter_next_knowledge` stimulus 带 expected versions 和 candidate key。服务端重新验证 active plan/availability，成功后 open/resume 下一 session 并仅 admission 一个 first-unit run；冲突返回 refresh projection。

## 7. Free reading

free reading learner message 仍进入同一 session/conversation 的 fresh finite run，但 policy 限制为 reactive answer 或 escalation hint。回答完成写 soft/session pause，不修改 mode。显式 escalation control 原子保存原问题/reference lineage、切换 guided、创建 focus，并 admission 一个有界 Turn。

## 8. 测试设计

- provider schema：good/base/bad、extra field、unknown action/handle。
- run loop：one stimulus -> one teaching action -> one pause；无新 stimulus 不再运行。
- focus reducer：连续插问、纠正、拒绝、返回主线、深度上限、摘要。
- completion：不自动 transition、stale roadmap conflict、显式 next node。
- free reading：reactive answer 留在原 mode、显式 escalation 保留 lineage。
- privacy/trace：无 raw question/body/reasoning/protected markers。
