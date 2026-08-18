# 技术设计

## 设计边界

新增包建议位于 `aearn/services/api/app/agents/runtime/`，其中通用端口与 Codex wire adapter 分离；Tutor 组合根只依赖通用端口。

~~~text
Tutor/Tests
  -> AgentRuntimePort
     -> CodexAppServerRuntime
        -> CodexRuntimeSupervisor
           -> JsonRpcStdioConnection
              -> codex app-server --stdio --strict-config
~~~

## Aearn 自有契约

`AgentRuntimePort` 接收 Aearn-owned run context、bounded input、tool registry 与控制回调，输出标准 Runtime event stream 和 terminal result。外部 thread/turn/item id 只作为 opaque correlation。

建议 terminal result：`completed | interrupted | unavailable | failed`。具体领域失败继续由后续 Tool Result taxonomy 表达，Adapter 不猜测 LearningPlan 语义。

## Supervisor 生命周期

1. worker 启动后懒启动或显式启动 app-server；
2. 完成 executable/version probe、initialize、account/read 与 capability preflight；
3. 生成单调 `connection_generation`；
4. 为每个 request 注册 pending future，为 notification/server request 分发有界队列；
5. worker shutdown 时先 interrupt active turn，再关闭 stdin，超时后终止 process tree；
6. child crash 时一次性 fail 所有 pending future，废弃 generation，禁止旧 callback 写入新连接。

## 并发与线程模型

Celery 继续同步 claim durable job；Codex worker 内使用一个专用 asyncio loop 管理 child 和事件。`pool=solo`、`concurrency=1` 保证 Windows 无多进程复制和 writer 竞争。Runtime Adapter 本身仍用 ownership guard 防止未来配置误改导致并发写者。

## 配置

新增 settings 建议包含 binary path、isolated home、allowed version range、startup/request/turn/shutdown timeout、feature readiness。配置只接收路径和非敏感策略；认证状态通过 preflight 读取，不把 token 注入日志或 DB。

## 失败策略

- 启动/preflight 失败：worker unavailable，不领取 Codex admission；
- transport/protocol failure：当前 run failed/unavailable，连接 generation 失效；
- shutdown timeout：终止 process tree 并记录安全错误码；
- restart：只服务新 run；未知 mutation 状态不得自动 resume；
- unknown notification：计数并忽略；unknown server request：明确 error response 并 fail closed。

## 兼容与回滚

根据用户 2026-08-18 的最新决定，Runtime 基础设施和独立 `tutor-codex` worker 默认启用，但业务 admission 仍不存在；可通过 `CODEX_RUNTIME_ENABLED=false` 或 `-NoCodexWorker` 显式回滚。现有 Harness dispatcher 不改行为，本任务不做 DB schema 变化。
