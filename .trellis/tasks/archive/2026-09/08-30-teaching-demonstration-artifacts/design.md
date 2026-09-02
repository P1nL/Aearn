# Teaching Demonstration Artifacts 技术设计

## Boundary

提供只读、受控、可恢复的静态和交互示例演示，使模型能在不破坏教学流程的前提下展示真实行为。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- DemonstrationDescriptor定义mode、source version、steps、expected events、duration policy
- ClientVisibleClock只上报受控elapsed/completion，不作为业务时间唯一authority；server receipt做幂等完成
- interactive event来自preview nonce bridge并经descriptor validator

## Data Flow

1. Tutor选择demo handle -> artifact item
2. static: visibility clock -> completion action -> continuation intent
3. interactive: user event -> validated completion -> continuation intent
4. learner message -> branch/priority arbiter先处理

## Contracts and Invariants

- 模型只能选择published演示handle，不能修改源码/步骤/时间
- 交互演示仅exact expected event完成
- 静态演示只有foreground/current/visible/render-ready时间计入
- 课程时长6-30s优先，系统计算兜底，过长拆步
- 演示不创建评分Attempt/mastery evidence
- 用户消息抢占自动继续
- 程序关闭前未完成静态演示重开后重新计时

## Affected Surfaces

- Learning Item demo contracts/catalog
- Artifact demonstration service/routes
- Desktop DemonstrationArtifact/visibility hook/progress CSS
- Preview bridge event validation
- teaching demo tests/evals

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 关闭demo candidate admission
- 已有演示只读展示但不自动继续
- 不将演示转换为评分练习
