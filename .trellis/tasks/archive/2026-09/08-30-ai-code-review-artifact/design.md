# AI Code Review Learning Artifact 技术设计

## Boundary

扩展现有模型代码审查为对话内 code/diff 工件，训练用户识别可验证的 AI 编码常见错误。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- 发布immutable v2而不改写v1
- ReviewPresentation可为code或diff，diff由server构造hunks/line map
- FindingMatcher以range overlap+category+required concept+false positive评分
- 现有authoring/validation/publication可扩展AI error mutation/template metadata

## Data Flow

1. published review item -> inline artifact
2. user select range/add finding -> complete review
3. server score -> result Turn
4. insufficient -> successor remediation review

## Contracts and Invariants

- 评分类别限需求偏离、虚构API、逻辑边界、契约集成、异步生命周期、安全信任、错误处理虚假成功；弱测试可专题扩展
- 风格/维护性只作非评分建议，除非明确规范
- Finding范围必须匹配当前hash/hunk并有简短说明
- 完成审查后原submission immutable
- 遗漏关键问题、误报、重复finding和severity由server rubric确定
- 题面/代码/rubric/test公私分离，不能在线随意生成未验证题

## Affected Surfaces

- services/learning/practice/model_review_* contracts/repository/scorer
- exercise/model review authoring templates
- Desktop ModelCodeReviewPanel replacement/adapter
- Monaco DiffEditor artifact
- review API/privacy/tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- feature关闭时继续使用v1 panel/history
- 不迁移旧submission
- v2 item退役不删除已完成attempt
