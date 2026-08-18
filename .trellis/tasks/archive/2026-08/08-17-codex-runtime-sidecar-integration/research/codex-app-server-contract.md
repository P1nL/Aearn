# Codex App Server 集成契约

## 固定基线

- 调查日期：2026-08-17。
- 开源源码：`openai/codex@c6058ccaa91ab17159cf805bf4d6d4edd87fe5fc`。
- 本机可执行文件：`codex-cli 0.142.0-cometix`。
- 本机版本与开源 `main` revision 不同，因此实施不得按“命令存在”推断协议完全兼容；必须执行 initialize/Schema/version capability preflight。

## 传输与生命周期

1. `codex app-server` 默认使用 `stdio://`，协议是 newline-delimited JSON-RPC。
2. `ws://` 在当前 README 中明确是 experimental / unsupported，不用于 Aearn 正式路径。
3. Unix socket 是本地 control-plane 入口，但本机 `codex app-server daemon version` 返回“only supported on Unix platforms”；Windows MVP 不能依赖 daemon/proxy 生命周期。
4. Aearn 的 Windows 目标必须由一个进程长期拥有 app-server stdio 子进程，并在同一连接上完成：
   - `initialize`；
   - `thread/start` / `thread/resume`；
   - `turn/start` / `turn/steer` / `turn/interrupt`；
   - `item/*` 与 `turn/completed` 消费；
   - `item/tool/call` server request 响应。
5. App Server 同一 paginated thread 只有一个写入 owner；Aearn 必须保证一个 Tutor run/thread 的单 Runtime owner，不允许多 worker 同时 resume/write。

## 事件模型

- `turn/started`：Turn 进入 `inProgress`。
- `item/started` / `item/completed`：agent message、tool call、command、MCP 等独立 item 生命周期。
- `item/agentMessage/delta`：可见 agent message 增量；不得与 raw reasoning 混用。
- `turn/completed`：明确携带 `completed | interrupted | failed`，失败包含 error。
- Aearn 只消费 allowlist item；reasoning、raw response、command/path、内部诊断默认不进入公共投影。

## Dynamic Tools

1. `dynamicTools` 在 `thread/start` 注册，要求 initialize capability `experimentalApi=true`。
2. 调用通过 `item/tool/call` JSON-RPC server request 返回宿主；输入有独立 `inputSchema`。
3. 该表面当前为 experimental。Aearn 的控制措施：
   - 固定 Codex 版本或 revision；
   - 启动时协议能力探测；
   - Adapter 内部隔离 wire DTO；
   - 为未来替换成 MCP 保留 `AgentToolRegistryPort`；
   - 版本不兼容时 fail closed，不静默降级到无 Schema 调用。
4. 首个 spike 使用 dynamic tools，因为它允许 Python 宿主直接调用现有 Aearn domain service，避免先引入第二个 MCP 进程；是否保留到正式 cutover 由 spike 的兼容性结论决定。

## 认证与 Codex Home

1. App Server 提供 `account/read`、`account/login/start`、`account/logout` 等账户接口。
2. 支持 API key、ChatGPT browser/device flow；凭据写入当前 `CODEX_HOME`。
3. 正式 Aearn Runtime 不得复用用户全局 `C:\Users\PINKING\.codex` 作为可写状态根，否则会混合用户 Codex threads、memory、plugins、config 和 Aearn 运行记录。
4. 目标方案使用独立、gitignored 的 Aearn Codex Home；认证由本地 operator preflight 完成。本任务不把 API key、access token、auth.json 或全局配置复制进仓库、日志、任务工件或公共 API。
5. 首个 spike 需要验证：
   - 独立 Codex Home 的 account state；
   - 当前目标 provider/model 是否可由 Codex 支持；
   - 不输出 secret 的 login/readiness 诊断；
   - thread/session 是否只写入隔离目录。

## SDK 与 App Server 选择

- TypeScript SDK 会 spawn Codex CLI，通过 JSONL 提供 `runStreamed()`，适合 Node 应用。
- Aearn 的权威调度和领域服务在 Python worker 中，且需要动态工具回调、turn interrupt/steer、精确 item 生命周期和独立 Codex Home；因此主设计使用 Python App Server Adapter，而不是在 Desktop 或独立 Node 层直接使用 SDK。
- SDK 只作为协议行为参考和备选 PoC，不作为 MVP 正式依赖。

## Go/No-Go 条件

首个 child 必须证明以下条件后才能继续：

- Windows stdio 子进程稳定；
- initialize/version/capability 可探测；
- 目标 provider/auth 在隔离 Codex Home 中可用；
- dynamic tool 能收到 typed input 并返回 structured result；
- repairable tool result 能促使同 Turn 继续；
- interrupt、timeout、child crash 能被 Aearn 收口；
- 全程没有 raw reasoning、secret 或全局 Codex 状态污染。
