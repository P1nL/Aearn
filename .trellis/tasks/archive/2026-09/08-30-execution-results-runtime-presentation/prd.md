# Execution Results and Runtime Presentation

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

扩展 learner-safe 执行结果，使显式 Run 后产生权威、简洁、可恢复的测试结果工件和 Tutor Markdown 评价。

## Scope

- SafeExecutionResult v2/presentation union
- test-result artifact contract
- Attempt terminal -> artifact completion/failure
- Tutor evaluation Turn 与 deterministic fallback
- 失败项/位置/stdout/stderr/table presentation
- hidden test redaction 和 result bounds

## Requirements

### R1

- Run 通过直接完成，不存在第二 Submit

### R2

- result artifact 由服务器生成，模型只生成评价

### R3

- 模型失败时仍发布权威结果和安全固定评价

### R4

- 失败优先显示，passed合并为其他N项通过

### R5

- stdout/stderr 仅非空显示且 redacted

### R6

- 错误位置不含内部路径/stack/container

### R7

- SQL table_result_v1 bounded且仅公开数据

### R8

- 多次 Run 产生独立历史 result item，原工件最新结果状态正确

## Acceptance Criteria

- [ ] SafeExecutionResult v1 历史仍可读或明确迁移
- [ ] API/executor/shared/Desktop v2 strict round-trip
- [ ] hidden case id/input/expected/private payload 不泄漏
- [ ] pass atomically terminalizes artifact并调度一次评价 Turn
- [ ] failure 保持 active且返回修改可定位原工件
- [ ] 模型 unavailable 不丢 result、不重复执行

## Out of Scope

- Monaco/Preview UI
- SQL editor/schema UI
- mastery/Gate scorer重写
- 大型成绩dashboard

## Dependencies and Ordering

- 依赖 Child 01 artifact/attempt link
- 供 Child 04和09使用

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
