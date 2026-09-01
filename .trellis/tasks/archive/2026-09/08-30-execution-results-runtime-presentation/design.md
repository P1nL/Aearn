# Execution Results and Runtime Presentation 技术设计

## Boundary

扩展 learner-safe 执行结果，使显式 Run 后产生权威、简洁、可恢复的测试结果工件和 Tutor Markdown 评价。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- shared execution contract拥有 safe presentation，不在 Desktop解析任意 safe_feedback JSON
- ResultProjector 将 owner Attempt转成 test-result artifact
- EvaluationTurnBuilder只注入 safe summary并与 result item原子发布
- 旧 SafeExecutionResultV1 adapter 显式转换成 v2 none presentation

## Data Flow

1. explicit Run -> Attempt/job -> safe v2 result
2. owner scorer -> artifact active/completed
3. continuation -> Tutor Markdown + immutable result artifact
4. Desktop snapshot刷新并原地更新原工件/追加结果Turn

## Contracts and Invariants

- Run 通过直接完成，不存在第二 Submit
- result artifact 由服务器生成，模型只生成评价
- 模型失败时仍发布权威结果和安全固定评价
- 失败优先显示，passed合并为其他N项通过
- stdout/stderr 仅非空显示且 redacted
- 错误位置不含内部路径/stack/container
- SQL table_result_v1 bounded且仅公开数据
- 多次 Run 产生独立历史 result item，原工件最新结果状态正确

## Affected Surfaces

- packages/shared/aearn_shared/execution/contracts.py
- services/api execution/practice/review result adapters
- services/executor result serialization
- artifact result contracts/projector
- Desktop ExecutionResultArtifact组件和API parser

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 保留v1 adapter，feature关闭时旧Gate结果继续可读
- 停用evaluation Turn不删除Attempt/result
- 禁止模型输出替代服务器result
