# SQL Learning Workspace 技术设计

## Boundary

交付对话内 SQL Editor/Schema/Result workspace，显式执行公开查询并以隐藏测试安全判断完成。

本 child 不拥有父任务中分配给其他 child 的业务 authority，不得为了局部便利复制 Artifact、Attempt、Teaching、Markdown、Result 或 Item Bank 状态机。

## Architecture

- SqlWorkspacePresentation含dialect/public schema/sample refs/starter query/result bounds
- Runner v2返回table result presentation，hidden test使用独立fixture
- QueryPolicy在服务端AST/token gate和SQLite只读连接双层限制
- Desktop result grid虚拟/截断但保持简洁

## Data Flow

1. edit -> explicit Run -> public query result bottom
2. same Attempt hidden tests -> artifact pass/fail
3. new Tutor Turn evaluation+test result
4. failure return modify -> scroll original SQL artifact

## Contracts and Invariants

- SQL不实时执行，只有Run触发
- 宽屏Editor/Schema 50:50固定，结果全宽底部；窄屏上下
- Schema只显示published public tables/columns/types/relations
- 名称可复制但不自动插入/聚焦
- Run public dataset返回bounded grid；hidden dataset只返回test summary
- 只允许SELECT/WITH只读语句，拒绝DDL/DML/ATTACH/PRAGMA/extension/file access
- 全部测试通过直接完成

## Affected Surfaces

- runners SQL adapter/runtime contracts
- shared SafeExecutionResult v2
- learning practice SQL contracts/fixtures/tests
- Desktop SqlWorkspaceArtifact/SchemaTree/ResultGrid
- API parser/result tests

## Compatibility

- 保持现有历史数据和旧 contract 读取；新行为通过 additive version/feature gate 引入。
- 所有未知 enum、extra field、stale identity、跨 scope 和受保护内容 fail closed。
- 不从历史归档恢复已移除 runtime，也不删除受保护前端原型。

## Security and Privacy

- 公共 API/SSE/Desktop/日志/导出不得包含完整 submission、private rubric/test、reference answer、provider body/reasoning、命令、路径、容器或 secret。
- 前端不能把本地 UI state 当作业务 authority。

## Rollback

- 关闭SQL artifact候选，保留现有Gate SQL路径
- table presentation缺失时显示安全无表格结果，不解析stdout伪表格
