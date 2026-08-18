# 技术设计

## Runtime Policy

新增 `TutorRuntimeSelectionPolicy`，输入 server-authoritative scope、run创建原因、retry root、feature配置与 Codex health snapshot，输出闭合 runtime kind 和安全 reason code。

选择顺序：

1. retry -> 继承 root runtime；
2. 非新 plan-drafting -> `harness_v1`；
3. feature off -> `harness_v1`；
4. 已选入 Codex cohort 但 readiness 不满足 -> 不创建 run，返回明确 unavailable；
5. 条件全部满足 -> `codex_sidecar_v1`。

第 4 步必须 fail closed，不允许把已选入 Codex cohort 的请求静默改成 Harness；未选入 cohort 在前面的 scope/feature 判断中正常创建 Harness run。

## Dispatch Router

~~~text
TutorInteractiveWorker
  -> claim durable job/run
  -> TutorRuntimeDispatchRouter
     -> HarnessTutorRunDispatcher
     -> CodexTutorRunDispatcher
~~~

Router只读取已冻结 runtime kind，不重新评估 feature。Codex dispatcher把 input/context/tool registry交给 `AgentRuntimePort`，再把 Runtime events交给 projector。

## 控制同步

Codex dispatcher在 active turn期间周期读取或订阅 Aearn control/revision：

- 新 user revision且 run仍active -> `turn/steer`；
- cancel/supersede/lease loss -> `turn/interrupt`；
- steer失败或 revision stale -> interrupt并写明确terminal；
- tool mutation与final persist仍执行三段 fence。

## Retry 与回滚

Retry root保存 runtime kind。失败重试可以重建外部 turn/thread binding，但不得改成另一 runtime，也不得重复已commit mutation。关闭 feature只影响新 admission；active Codex run按运维策略完成或interrupt。

## Desktop/API

不新增 Codex DTO。若需要 readiness提示，API返回 Aearn-owned code，如 `RUNTIME_UNAVAILABLE`；Desktop沿用 error/process item渲染。LearningPlan确认入口和确认API不变。

## 发布顺序

1. feature默认off部署；
2. test-only scope验证；
3. 本地/受控 cohort开启新 plan-drafting；
4. 回滚演练；
5. 生产 rollout另立任务和批准。
