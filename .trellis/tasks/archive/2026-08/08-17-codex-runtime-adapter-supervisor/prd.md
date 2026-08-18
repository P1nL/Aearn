# Codex Runtime Adapter 与进程监管

## 目标

在 Child 1 给出 Go 结论后，为 Aearn 建立稳定的 Codex Runtime 边界：业务层只依赖 Aearn 自有端口，由独立 `tutor-codex` worker 通过 stdio 托管一个 `codex app-server` 子进程，并把版本、认证、协议、生命周期与崩溃收口在 Adapter 内。本任务不开放正式学习计划流量。

## 依赖

- 父任务：`08-17-codex-runtime-sidecar-integration`。
- 前置任务：`08-17-codex-sidecar-protocol-spike` 必须取得 `deepseek-v4-flash` Responses specific Go，并产出支持版本、能力矩阵和安全启动参数；OpenAI/Chat Completions对照结果不能解锁本任务。

## 需求

### R1：Aearn 自有 Runtime 契约

- 定义 `AgentRuntimePort`、Runtime command/event/result、tool callback 与健康状态 DTO。
- 上层代码不得导入 Codex wire-generated DTO；Codex method、item 与 status 映射只存在于 Adapter。
- DTO 必须表达 start/resume、run turn、steer、interrupt、shutdown、unavailable 与 fatal。

### R2：stdio Client 与 Supervisor

- 实现异步 JSON-RPC request/response、notification、server request、超时、背压和 stderr redaction。
- Supervisor 负责 child 启动、initialize、account/capability preflight、连接 generation、优雅 shutdown 与强制终止。
- 协议损坏、未知 server request、stdout 非 JSON、child exit 与超时均 fail closed，不泄漏后台任务。

### R3：独立 Worker Ownership

- 增加 `tutor-codex` 队列和独立 worker 启动入口，Windows 使用 `pool=solo`、`concurrency=1`。
- 单一 worker process 持有 app-server connection 和 active thread writer ownership。
- 现有 Tutor Harness worker、队列和本地开发启动不受 feature off 场景影响。

### R4：隔离配置与可观测性

- Codex binary、Home、strict config、启动超时和兼容版本由 Aearn 配置提供。
- 使用隔离 Aearn Codex Home，不自动读取或写入用户全局 Codex sessions、memory、plugins。
- 日志只记录 request method、hash/correlation、安全错误码、版本与时长；不记录 prompt、reasoning、raw tool body 或 credential。

## 范围外

- 学习计划领域工具和 DB mutation。
- `tutor_runs.runtime_kind`、Codex correlation 持久化和公开 item 投影。
- 正式 `plan_drafting` admission、Desktop 交互或生产部署。

## 验收标准

- [ ] 业务层只通过 `AgentRuntimePort` 使用 Codex Runtime。
- [ ] fake app-server contract tests 覆盖 handshake、server request、notification、timeout、invalid JSON、child exit 和 shutdown。
- [ ] 同一 worker 不会创建并发 writer；第二个 active ownership 会被明确拒绝或排队。
- [ ] 版本、认证或 capability preflight 失败时 worker health 为 unavailable，Harness 路径仍可启动和运行。
- [ ] child crash 后当前 generation 被关闭，pending request 全部收到可区分错误，进程与 reader task 不残留。
- [ ] 日志和测试快照不含 raw prompt、模型正文、tool arguments、credential 或全局 Codex Home 内容。
- [ ] 本任务结束时 Runtime Adapter 仍未接入正式用户流量。
