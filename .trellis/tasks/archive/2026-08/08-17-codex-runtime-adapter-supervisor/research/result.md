# Codex Runtime Adapter 与进程监管实施结果

## 当前结论

- 日期：2026-08-18。
- Child 1 前置条件：`deepseek-v4-flash` Responses specific Go 已满足。
- Child 2 实施结论：通过。
- Runtime 默认状态：`CODEX_RUNTIME_ENABLED=true`。
- 普通 `pnpm --dir .\aearn dev` 默认启动独立 `tutor-codex` worker；用户明确说明任务执行期间不会启动项目。
- 正式 Tutor admission：未接入。
- DB/API/Public projection/Desktop：未修改业务契约。
- 工作提交：`5804d628 feat(runtime): add Codex sidecar adapter and supervisor`。
- push、部署：未执行。

## Aearn-owned Runtime 契约

新增 `app/agents/runtime/contracts.py`，业务层只依赖以下 Aearn-owned 类型：

- `AgentRuntimePort`；
- `RuntimeThreadRequest/Handle`；
- `RuntimeTurnRequest/Result`；
- `RuntimeEvent` 与稳定 event/terminal enum；
- `RuntimeToolDefinition/Call/Result/Registry`；
- `RuntimeHealthSnapshot`。

业务契约不导入 Codex wire DTO。外部 thread/turn/item id 只作为 opaque correlation；tool arguments 只进入受控 callback，不进入普通 Runtime event。

## JSON-RPC Connection 与 Adapter

Child 1 验证过的通用 stdio connection 已提升到 `app/agents/runtime/codex_connection.py`，spike 保持薄包装，避免复制第二套 transport。

正式 Adapter `CodexAppServerRuntime` 支持：

- `start_thread`；
- `resume_thread`；
- `run_turn`；
- `steer`；
- `interrupt`；
- bounded event stream；
- terminal result；
- shutdown。

Wire mapper只允许 turn、agent message、dynamic tool和warning等必需表面。Reasoning item 被忽略；tool arguments 不进入 event；event queue 满时返回 `runtime_event_backpressure_exhausted`，不会无限等待。

## Tool Callback 竞态修复

自动化重复运行发现：App Server 可以在 `turn/start` response 后立即发送 `item/tool/call`，reader task 可能先于调用协程恢复。如果只在取得 `turn_id` 后注册 registry，会偶发 `tool_registry_unavailable`。

最终实现先按 thread 预注册 tool registry，再在取得 turn ID 后绑定到 turn；终态或失败时同时清理 thread/turn registry。该回归连续运行 20 次通过。

## Supervisor 与 Ownership

`CodexRuntimeSupervisor` 实现：

1. runtime enablement 检查；
2. exact Codex executable/version allowlist；
3. provider env credential presence；
4. isolated Codex Home strict config；
5. `initialize + initialized + account/read` preflight；
6. 单调 connection generation；
7. pending request/child crash/protocol failure收口；
8. active turn interrupt + graceful/forced shutdown；
9. process-local owner registry；
10. 跨 OS process 一字节文件锁，防止两个 worker同时拥有同一 Runtime Home。

Child crash 后旧 generation 失效；旧 thread handle 不能写入新 connection。Restart 只增加 generation，不自动恢复未知 mutation。

## 配置与隔离 Home

新增 settings：

- `CODEX_RUNTIME_ENABLED`；
- `CODEX_RUNTIME_BINARY_PATH`；
- `CODEX_RUNTIME_HOME`；
- `CODEX_RUNTIME_ALLOWED_VERSIONS`；
- startup/request/turn/shutdown timeout；
- notification queue size。

Runtime 默认启用；默认 Home 位于 `%LOCALAPPDATA%\Aearn\codex-runtime`，不使用用户全局 `C:\Users\PINKING\.codex`。配置不包含 credential；credential只从当前 worker环境读取。

## 独立 tutor-codex Worker

Celery新增的只有 lifecycle task：

- `tutor.codex.runtime_health`；
- `tutor.codex.runtime_shutdown`。

两者固定路由到 `tutor-codex` queue。不存在 `tutor.codex.dispatch`，因此本任务没有业务 admission。

`CodexRuntimeWorkerHost` 在一个专用 background asyncio loop 中拥有单个 Runtime/Supervisor。Celery worker shutdown signal会关闭 Runtime。默认 Harness worker process匹配显式排除 `tutor-codex` worker。

普通本地启动默认包含独立 Codex worker：

~~~text
pnpm --dir .\aearn dev
~~~

显式回退命令：

~~~text
pnpm --dir .\aearn dev:no-codex
~~~

其独立 worker命令固定：

~~~text
--pool=solo --concurrency=1 -Q tutor-codex -n tutor-codex@%h
~~~

业务 admission 仍不存在；默认启动 worker 不会把 Tutor run 路由到 Codex。

## Startup Smoke

### 真实 Supervisor Preflight（不调用模型）

- status：`ready`；
- generation：`1`；
- version：`0.142.0-cometix`；
- model：`deepseek-v4-flash`；
- provider：`aearn_deepseek`；
- shutdown：完成；
- 临时隔离根目录：已删除。

### 真实 Worker Host Smoke（不调用模型）

在临时 `CODEX_RUNTIME_HOME` 下启用 Runtime，调用 lifecycle health/shutdown：

- health：`ready`；
- generation：`1`；
- shutdown：`stopped`；
- 临时目录：已删除。

显式设置 `CODEX_RUNTIME_ENABLED=false` 的回退 smoke 返回 `runtime_disabled`，没有启动 child。

## 自动化覆盖

- disabled runtime；
- missing credential；
- unsupported version；
- initialize/account preflight；
- start/resume/steer/interrupt；
- same-turn dynamic tool repair；
- immediate tool callback registration race；
- bounded event backpressure；
- reasoning忽略；
- stderr secret/path redaction；
- single active writer；
- stale generation；
- child crash与restart；
- process-local ownership；
- cross-process file lock；
- worker loop single ownership与shutdown；
- Celery route和无business admission；
- PowerShell worker lifecycle和默认opt-in；
- Child 1 spike回归；
- Harness cutover、health、environment doctor和Desktop build不回归。

## 验证结果

- 最终合并 focused suite：`47 passed, 1 skipped`。
  - skipped 项是仍受单独授权门保护的真实 provider pytest；Child 2 本身没有调用模型。
- Ruff全API/worker范围：通过。
- Mypy：`188 source files` 无问题。
- `uv lock --check`：通过。
- `compileall`：通过。
- Desktop `desktop:check`：通过。
- `start-dev.ps1` parser：通过。
- Trellis validate：通过。
- `git diff --check`：通过；仅有既存/工作树文件的行尾提示。
- 进程与临时目录检查：`process_count=0`、`temp_dir_count=0`。

## 剩余边界

1. Runtime Adapter尚未接正式 Tutor run；这是本任务的明确范围外。
2. 未实现 LearningPlan typed tools、DB mutation或repair taxonomy；由Child 3负责。
3. 未新增 runtime_kind、binding、receipt或public projection；由Child 4负责。
4. 未启动正式 `tutor-codex` 长期进程或部署。
5. Child 1与Child 2代码已由工作提交 `5804d628` 固化，可按 Trellis 顺序归档。
