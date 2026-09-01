# Teaching Orchestration and Branch Scheduling 技术设计

## Boundary

让 Teaching loop 只能选择真实可用工件，并以确定性优先级管理用户答疑支线、Artifact completion 与自动教学继续。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- Teaching candidate builder 只返回 bounded safe handles
- Decision gate 拥有 mode/intent/handle/scope/capability 最终校验
- ContinuationIntent 是 durable/幂等调度事实，timer/terminal 不能直接调用模型
- BranchResponseDisposition 固定 answer_and_refocus / offer_switch / confirmed_switch

## Data Flow

1. context builder -> candidate handles -> provider decision -> decision gate
2. accepted decision -> atomic teaching commit -> artifact item
3. learner message during wait -> branch turn -> answer/refocus -> artifact remains waiting
4. artifact action/event -> resolve branch -> mainline result/continuation

## Contracts and Invariants

- learner response mode 增加 artifact，intent 与 exact handle 成对
- edit/run/review/query/demo intent 无候选时整条 public decision 拒绝
- 候选由服务器按 current scope、item publication、runtime readiness 构建
- 普通用户消息在 blocking artifact 下进入 depth=1 branch
- 用户消息优先于 explicit action、event、timer 和 background continuation
- 无关问题先回答再引导主线；明确主题切换走 control confirmation
- 支线 hint/direct answer 必须记录 assistance，不能绕过 Hint policy
- 一个 conversation 同时只有一个可发布 Tutor Turn

## Affected Surfaces

- agents/skills/tutor.lesson-teaching/1.2.0（新增）
- services/tutor/decision_protocol.py、decision_gate.py、provider_request.py
- services/learning/teaching_contracts.py、teaching_loop.py、teaching_sessions.py
- Tutor interactive dispatch/queue/continuation persistence
- teaching evals/fixtures/prompt contract tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 关闭 artifact teaching flag 后候选为空且 artifact intent 被拒绝
- 切回 Skill 1.1.0
- 保留 branch/artifact rows 只读，不重放自动 continuation
