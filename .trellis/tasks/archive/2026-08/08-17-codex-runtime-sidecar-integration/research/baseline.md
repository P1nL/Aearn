# 基线调查

## 调查日期与边界

- 日期：2026-08-17。
- Aearn 工作目录：`E:\codee\Aearn`。
- Codex 公开源码参考：`openai/codex`，本次本地核对 revision `c6058ccaa91ab17159cf805bf4d6d4edd87fe5fc`。
- 本文件只记录规划证据，不修改产品代码。

## Aearn 当前事实

1. `docs/README.md:5-8` 将 Tutor Harness 定义为当前正式 Runtime。
2. `docs/architecture/tutor-harness-runtime.md:32-121` 定义 public adapter、learning domain、interactive dispatch、Harness、durable state、worker、Desktop 以及 long-lived conversation/fresh finite TurnRun。
3. `docs/architecture/tutor-harness-runtime.md:229-260` 定义 provider replacement retry 与 public `MODEL_UNAVAILABLE` 投影；`:416-428` 仍记录单 provider envelope 和 bounded action payload。
4. `aearn/services/api/app/services/tutor/interactive_worker.py:35-128` 负责 durable job claim；`interactive.py:689-773` 是当前 dispatcher组合根；`run_loop.py:49-77` 定义主要 ports。
5. `run_loop.py:436-451` 当前把非 completed capability结果收口为 terminal blocked，不能表达模型可修复错误。
6. `aearn/services/api/app/agents/capabilities.py:116-183` 与 `aearn/services/api/app/services/learning/plan_capability.py:49-177` 仍使用 `profile_json` 与 `module_1..8` 字符串，并将多类错误收敛。
7. Desktop 只消费 Aearn HTTP/SSE DTO；不应直接绑定 Codex App Server DTO。
8. `aearn/scripts/start-dev.ps1:306-320` 当前 worker使用 `pool=solo`，适合新增独立 `tutor-codex` worker ownership边界。

## Codex 可复用能力与约束

1. App Server 提供 stdio JSON-RPC、`thread/start`、`thread/resume`、`turn/start`、`turn/steer`、`turn/interrupt`、item事件和明确turn终态。
2. Dynamic tools 可以把工具错误作为 model-visible result 回灌，但当前为 experimental，必须固定版本并执行 capability preflight。
3. WebSocket transport明确不作为本路线生产基础；Windows不支持 app-server daemon lifecycle，因此由 Aearn worker拥有stdio child。
4. TypeScript SDK适合简单嵌入，但Aearn后端为Python且需要完整server request、控制与event投影，首选App Server。
5. 本机 `codex-cli 0.142.0-cometix` 与公开main revision不同，不能仅以命令存在作为兼容证据。
6. 正式实现必须使用隔离Aearn Codex Home，不读取或写入用户全局 `C:\Users\PINKING\.codex` 状态根。

## Trellis 与工作树基线

- `08-15-tutor-public-thinking-text-stream` 和 `08-16-tutor-plan-confirmation-entry` 已于 2026-08-17 完成并归档。
- 创建本任务前工作树无tracked/untracked产品修改；当前只规划 `08-17-codex-runtime-sidecar-integration` 及其children。
- 当前实施入口是 `08-17-codex-sidecar-protocol-spike`，状态仍为 planning；父任务不得直接start。
- `.trellis/tasks/.obsidian/workspace.json` 在规划期间出现本地UI状态修改，不属于本任务交付，不应覆盖或提交。

## 最小可验证路线

1. Child 1 先隔离验证protocol/version/auth/dynamic tool repair/interrupt/crash并给出Go/No-Go。
2. Go后建立Aearn-owned Runtime Adapter与独立worker，不接正式流量。
3. 接typed planning tools和同Turn修复，再补持久化/public projection。
4. 仅对新 `plan_drafting` 受控切换；existing和其他scope保持Harness。
5. 最后执行失败矩阵、可选真实smoke、回滚演练和source-of-truth更新。

## 阻塞问题

无。产品范围、兼容边界、首个cutover scope、Runtime authority与真实调用授权门均已明确。
