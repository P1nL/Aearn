# Codex Sidecar 本地运行与运维边界

**状态：** 2026-08-20 本地受控集成契约；不是生产发布批准。

## 支持范围

- Runtime：Windows `codex app-server --stdio --strict-config`。
- 固定版本：`codex-cli 0.142.0-cometix`；其他版本必须先更新 allowlist 并重新验收。
- 固定目标：model `deepseek-v4-flash`、provider `aearn_deepseek`、`wire_api = "responses"`。
- 业务范围：仅没有既有 Runtime lineage 的全新 `plan_drafting` conversation。
- Harness 继续负责 general、LearningTrack、proactive、历史 conversation 和 feature-off 流量。

不支持 OpenAI、其他 DeepSeek 模型、Chat Completions、WebSocket/daemon、跨 Runtime fallback、所有 Tutor scope 全量切换或生产流量发布。

## 配置

```text
CODEX_RUNTIME_ENABLED=true
CODEX_RUNTIME_BINARY_PATH=
CODEX_RUNTIME_HOME=
CODEX_RUNTIME_ALLOWED_VERSIONS=0.142.0-cometix
CODEX_RUNTIME_STARTUP_TIMEOUT_SECONDS=15
CODEX_RUNTIME_REQUEST_TIMEOUT_SECONDS=15
CODEX_RUNTIME_TURN_TIMEOUT_SECONDS=300
CODEX_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS=5
CODEX_RUNTIME_NOTIFICATION_QUEUE_SIZE=256
TUTOR_CODEX_PLAN_DRAFTING_ENABLED=true
TUTOR_CODEX_RUNTIME_HEALTH_MAX_AGE_SECONDS=90
```

`CODEX_RUNTIME_HOME` 缺省为 `%LOCALAPPDATA%\Aearn\codex-runtime`，不得指向或位于用户全局 `C:\Users\PINKING\.codex` 下。credential 只从 worker 环境的 `DEEPSEEK_API_KEY` 读取；不要复制 `auth.json`、token、session、memory 或 plugin state。

## 进程与 Queue

默认开发启动：

```powershell
pnpm --dir .\aearn dev
```

它启动普通 Harness worker、Celery beat 和独立 worker：

```text
python -m celery -A aearn_worker.worker_app:celery_app worker --pool=solo --concurrency=1 -Q tutor-codex -n tutor-codex@%h
```

显式本地 opt-out：

```powershell
pnpm --dir .\aearn dev:no-codex
```

`tutor-codex` 只消费 `tutor.codex.runtime_health`、`tutor.codex.runtime_shutdown`、`tutor.codex.dispatch` 和 `tutor.codex.reconcile`。Harness/Codex worker 对 `tutor_interactive_dispatch_jobs` 使用互斥 `runtime_kind` claim filter。

## Readiness 与 admission

worker 每 10 秒将 bounded health 写入 shared `tutor_codex_runtime_health`。新 plan-drafting admission 要求：

1. 两个 feature 均开启；
2. latest heartbeat 未超过 `TUTOR_CODEX_RUNTIME_HEALTH_MAX_AGE_SECONDS`；
3. status=`ready`、generation >= 1；
4. Runtime version 在 allowlist；
5. model/provider/protocol 精确匹配。

feature off 时新计划对话走 Harness。feature on 但 readiness 不通过时返回 `503 TUTOR_RUNTIME_UNAVAILABLE`，first-turn transaction 不留下空 conversation。existing conversation 和 Retry 继承已冻结 Runtime，不随 heartbeat 或 feature 改写。

## 可观测性与数据保留

允许记录 version、generation、method、status、safe code、duration、count、SHA-256 和 opaque correlation。禁止记录 raw prompt/response/reasoning、tool arguments/results、credential、auth 文件、command、完整路径或 provider body。

`tutor_run_runtime_bindings`、`tutor_runtime_item_receipts`、`tutor_runtime_public_errors` 是保留证据；关闭 admission、停止 worker或代码 rollback 不删除这些行，也不把历史 Codex run 迁移到 Harness。

## 回滚

1. 设置 `TUTOR_CODEX_PLAN_DRAFTING_ENABLED=false`，阻止新的 Codex admission。
2. 让 active Codex run 完成，或通过现有 Tutor Interrupt 明确中止；不要跨 Runtime 续跑。
3. 停止 dedicated worker，或使用 `pnpm --dir .\aearn dev:no-codex` 重启本地环境。
4. 验证 general/track/proactive 与 feature-off plan-drafting 继续由 Harness 服务。
5. 保留历史 Runtime binding/receipt/public error 和 committed LearningPlan draft。

## 真实 Smoke 门

真实 provider smoke 不是默认命令。执行前必须明确模型、endpoint、调用次数、隔离 Home、合成输入和日志/保留边界并获得批准。默认测试使用 fake App Server/Responses fixture。2026-08-18 已有一次获批的 `deepseek-v4-flash` Responses tool-repair smoke；集成 QA 不重复产生第二次付费调用。

## 2026-08-20 持久 thread 与 compaction 配置

- 一个 `TutorConversation` 对应一个持久 App Server thread；fresh run 只创建新 turn。重启后执行 `thread/resume`，不能因 worker restart 创建第二个 conversation thread。
- isolated config 必须同时包含 `model_context_window = 1000000`、`model_auto_compact_token_limit = 616000`、`model_auto_compact_token_limit_scope = "total"`。384000 output reserve 与 616000 input/auto-compact limit 从同一 capability 派生。
- 当前 `aearn_deepseek` 只支持 local compaction；禁止配置或发送 remote compaction request。manual `thread/compact/start` 和 turn 内 `contextCompaction` 使用 fake App Server 验证。
- owner-scoped raw reasoning/final answer 持久化在 PostgreSQL private runtime projection；public receipt 不含 raw text。commentary/summary 不显示。
- 默认验证仍使用 fixture，不调用真实 provider。真实 provider smoke 继续要求新的明确批准，本任务没有授权调用。
