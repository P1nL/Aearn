# AI Code Review Learning Artifact

## Parent

- `08-30-tutor-conversation-learning-artifacts`
- 本 child 的实现必须遵守父任务 PRD/design 和 confirmed product decisions；若产生物质性冲突，先返回父任务规划。

## Goal

扩展现有模型代码审查为对话内 code/diff 工件，训练用户识别可验证的 AI 编码常见错误。

## Scope

- model review artifact/submission v2
- Monaco code/diff read-only view
- stable hash/hunk/line mapping
- structured finding range/category/explanation
- AI error taxonomy/rubric/scoring
- Tutor result/remediation与v1历史兼容

## Requirements

### R1

- 评分类别限需求偏离、虚构API、逻辑边界、契约集成、异步生命周期、安全信任、错误处理虚假成功；弱测试可专题扩展

### R2

- 风格/维护性只作非评分建议，除非明确规范

### R3

- Finding范围必须匹配当前hash/hunk并有简短说明

### R4

- 完成审查后原submission immutable

### R5

- 遗漏关键问题、误报、重复finding和severity由server rubric确定

### R6

- 题面/代码/rubric/test公私分离，不能在线随意生成未验证题

## Acceptance Criteria

- [x] v1历史和旧Lesson Gate仍可读
- [x] v2 diff line mapping稳定，stale hash拒绝
- [x] 结构化finding评分可重复且不依赖精确措辞
- [x] 模型评价不能修改result
- [x] 补救review缩小范围/难度而非修改原答案
- [x] protected rubric/test/proof不进入API/SSE/Desktop

## Out of Scope

- 多文件架构审查
- 主观风格评分
- 实时开放模型出题
- 自动修改用户代码

## Dependencies and Ordering

- 依赖Child01/03/05/07/11；复用现有model review authority

## Open Questions

无阻塞产品问题。实现中若发现仓库事实与本规划冲突，必须回到 planning 更新 artifact 并重新审阅。
