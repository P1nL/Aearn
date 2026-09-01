# Teaching Orchestration and Branch Scheduling

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

让 Teaching loop 只能选择真实可用工件，并以确定性优先级管理用户答疑支线、Artifact completion 与自动教学继续。

## Scope

- tutor.lesson-teaching@1.2.0 与 decision v3
- available artifact candidate context
- impossible-instruction gate
- atomic message/checkpoint/artifact commit
- continuation intent 和 single-turn arbiter
- clarification/detour branch authority与 refocus policy

## Requirements

### R1

- learner response mode 增加 artifact，intent 与 exact handle 成对

### R2

- edit/run/review/query/demo intent 无候选时整条 public decision 拒绝

### R3

- 候选由服务器按 current scope、item publication、runtime readiness 构建

### R4

- 普通用户消息在 blocking artifact 下进入 depth=1 branch

### R5

- 用户消息优先于 explicit action、event、timer 和 background continuation

### R6

- 无关问题先回答再引导主线；明确主题切换走 control confirmation

### R7

- 支线 hint/direct answer 必须记录 assistance，不能绕过 Hint policy

### R8

- 一个 conversation 同时只有一个可发布 Tutor Turn

## Acceptance Criteria

- [x] provider 输出不可执行任务时 gate fail closed 且无消息泄漏
- [x] 合法候选在一个事务创建 Tutor message/checkpoint/action receipt/artifact/event
- [x] timer/interaction/result 与用户消息竞态只产生一条有序回复
- [x] 支线 item 与 anchor/branch identity 可 snapshot 恢复
- [x] 主线恢复后 branch resolved，结果 Turn 不留在支线
- [x] Skill 1.1.0 历史不改写

## Out of Scope

- Artifact DB/public contract 基础实现（Child 01）
- 支线视觉渲染（Child 03）
- 题库生成审核（Child 11）
- 具体工件 UI

## Dependencies and Ordering

- 依赖 Child 01 artifact/branch contracts
- online candidate 接入依赖 Child 11 published item seam

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
