# Aearn 集成接缝调查

## 当前组合根

1. `TutorInteractiveWorker` 从 PostgreSQL durable job claim 开始，再调用 `TutorRunDispatcher`；Celery 只负责 wakeup，数据库保持权威（`aearn/services/api/app/services/tutor/interactive_worker.py:35-128`）。
2. `TutorInteractiveRunDispatcher` 在每个 job 中组合 `TutorRunLoop`、context、provider、capability、decision gate 与 persistence（`aearn/services/api/app/services/tutor/interactive.py:689-773`）。
3. `TutorRunLoop` 当前把 provider/capability/effect 作为内部细粒度端口，但整个 loop 仍由 Aearn 自己实现（`aearn/services/api/app/services/tutor/run_loop.py:49-77`）。
4. Capability 非 completed 时当前直接终止为 `BLOCKED_POLICY / capability_denied`（`run_loop.py:436-451`），这正是需要由 Codex tool loop 改善的边界。
5. Aearn 已有 public `message | process | elicitation | approval | error` union 和 `in_progress | completed | interrupted | failed` turn status（`conversation_contracts.py:24-40,85-220`），无需让 Desktop 直接理解 Codex DTO。
6. 当前 worker 以 `--pool=solo` 启动，适合在独立 queue/process 中拥有一个长期 stdio child，但现有 worker 同时消费多个 Tutor queue；正式 Codex Runtime 应使用独立 `tutor-codex` worker，避免 process ownership 与其他任务混杂。

## 推荐替换层级

不把 Codex 塞入 `TutorProviderGateway`，也不让现有 `TutorRunLoop` 再包一层 Codex loop。推荐在更高层替换 `TutorRunDispatcher`：

```text
TutorInteractiveWorker
  -> TutorRuntimeDispatchRouter
       -> HarnessTutorRunDispatcher
       -> CodexTutorRunDispatcher
```

选择依据来自 run 的 server-owned `runtime_kind`，不是自然语言、客户端参数或模型决定。

这样可以：

- 保留公共 input、Queue、job、lease、conversation、SSE 与 LearningPlan authority；
- 对 selected run 使用 Codex 自己的 turn/tool loop；
- 不形成“Aearn loop 内再运行 Codex loop”的双重 budget/stop/retry；
- 通过同一 `TutorRunDispatcher` 输出收口到现有 public persistence。

## 目标进程拓扑

```text
Aearn API
  -> PostgreSQL accepted input + tutor_interactive_dispatch_job
  -> Celery route by runtime_kind
       -> existing tutor-interactive worker
       -> dedicated tutor-codex worker (--pool=solo, concurrency=1)
            -> CodexRuntimeSupervisor
                 -> codex app-server --stdio --strict-config
```

`CodexRuntimeSupervisor` 在 worker process 内维护一个 async event loop/child process，负责 request correlation、thread subscriptions、tool callbacks、timeout、interrupt 与 crash recovery。Celery task是 durable job 的入口，不是 app-server transport owner。

## Steer / Interrupt / Revision

- API 继续通过 PostgreSQL control/revision CAS 接收 learner Steer/Interrupt。
- Codex dispatcher 在消费 app-server events 时监听/poll run control state；发现新 input revision 时向同一 Codex connection 发 `turn/steer`，发现 cancel/supersede 时发 `turn/interrupt`。
- 每次 tool 回调和 final message 持久化前继续刷新 Aearn lease、input revision 与 terminal ownership。
- Codex thread/turn id 不能替代 Aearn run id；Aearn id 始终是公共和数据库 authority。

## 学习计划工具边界

当前 `LearningPlanDraftCapabilityInput` 使用 `profile_json + module_N` 字符串（`capabilities.py:116-183`），并在 handler 内二次解析、事实校验与持久化（`plan_capability.py:49-177`）。目标 typed tools：

1. `aearn_planning_context_read`：返回 bounded confirmed facts、missing fields、current draft summary 和 version fence。
2. `aearn_learning_plan_draft`：输入结构化 `modules[]`；服务端从 planning facts 构造 profile，执行 domain/safety/quality 校验并 append draft。

Repairable domain errors作为正常 structured tool result返回：

```json
{
  "status": "repairable_invalid",
  "issues": [{"path": "modules.1.nodes.0.prerequisite_keys.0", "code": "forward_reference"}],
  "retry_allowed": true
}
```

不把错误作为公共 Tutor 终态；policy/fatal/预算耗尽才终止。

## 持久化建议

- `tutor_runs.runtime_kind`：`harness_v1 | codex_sidecar_v1`，创建 run 时冻结。
- `tutor_run_runtime_bindings`：Aearn run 与 Codex thread/turn、Codex version、connection generation 的 1:1 correlation。
- `tutor_runtime_item_receipts`：只保存 allowlisted item kind/status/hash/安全诊断，不保存 raw arguments、reasoning、command、path 或 secret。
- Aearn domain tool继续写现有 `tutor_capability_invocations`、LearningPlan session/draft 表和 action receipts。
- public timeline继续写现有 `tutor_messages`、process/error/request item 与 `tutor_conversation_events`。

## 公开投影

- Codex final `agentMessage` 在 turn success、Aearn safety、lease/revision 检查后写 Tutor message。
- Codex failed turn始终写 public error item并完成 process=`failed|unavailable`；不能只更新隐藏 run receipt。
- `reasoning` 永不进入 Aearn public surface。
- `agentMessage` commentary/public delta 只有在明确 phase allowlist、累计 safety 和 generation fence 下才可进入现有 public thinking stream；若 spike 不能证明该边界，Codex path 的 MVP 保持静态 `Think`，不冒充 live public thinking。现有 Harness path不回归。

## 切换边界

- 第一条正式 cutover 只覆盖新建 `plan_drafting` conversation/run。
- existing conversations和非 plan scope继续 `harness_v1`。
- run 创建后 runtime_kind不可变；失败后 Retry沿用同一 runtime root，不跨 Runtime fallback。
- Sidecar关闭只影响新 run admission；active Codex turn必须完成或显式 interrupt。
- HTTP LearningPlan confirm仍是创建 LearningTrack的唯一 authority。
