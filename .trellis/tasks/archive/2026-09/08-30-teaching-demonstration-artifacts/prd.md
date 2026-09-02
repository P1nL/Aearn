# Teaching Demonstration Artifacts

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

提供只读、受控、可恢复的静态和交互示例演示，使模型能在不破坏教学流程的前提下展示真实行为。

## Scope

- demonstration presentation/step contract
- 只读代码+交互Preview
- expected event completion
- visible-time static timer
- 2-3px progress animation
- completion receipt与低优先级continuation

## Requirements

### R1

- 模型只能选择published演示handle，不能修改源码/步骤/时间

### R2

- 交互演示仅exact expected event完成

### R3

- 静态演示只有foreground/current/visible/render-ready时间计入

### R4

- 课程时长6-30s优先，系统计算兜底，过长拆步

### R5

- 演示不创建评分Attempt/mastery evidence

### R6

- 用户消息抢占自动继续

### R7

- 程序关闭前未完成静态演示重开后重新计时

## Acceptance Criteria

- [ ] 无关点击/加载/滚动不能误完成交互演示
- [ ] 重复event/timer只产生一个completion和一个continuation intent
- [ ] 进度动画与有效计时暂停/恢复一致
- [ ] reduced motion改为离散进度
- [ ] 用户消息竞态先回答且不重复下一步
- [ ] 只读代码不可编辑、粘贴或产生草稿

## Out of Scope

- 可编辑练习
- 评分测试结果
- 复杂模拟器
- 模型在线生成任意演示host

## Dependencies and Ordering

- 依赖 Child 01 artifact authority、02 arbiter、03 shell、04 preview isolation、11 published item

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
