# Codex 计划制定受控切换

## 目标

在前序 Runtime、typed tools、持久化和公开投影均验证通过后，通过 server-side feature policy 仅让新建 `plan_drafting` run 使用 `codex_sidecar_v1`。既有 conversation/run 与其他 Tutor scope 继续 `harness_v1`，并保持 Queue、Steer、Interrupt、Retry、LearningPlan confirm 和 Desktop 契约的 Aearn authority。

## 依赖

- 父任务：`08-17-codex-runtime-sidecar-integration`。
- 前置任务：`08-17-codex-tutor-durable-projection`，其依赖的 Adapter 与 typed tools 已完成。

## 需求

### R1：Server-side Runtime Selection

- 新增受控 cutover policy，只有 feature enabled、worker healthy、版本/auth/capability ready 且 scope 为新 `plan_drafting` 时选择 Codex。
- `runtime_kind` 在 run 创建时冻结；客户端和模型不能指定或修改。
- existing run、retry root、非 plan-drafting、proactive 与 lesson/exercise/review 始终沿用原 runtime。

### R2：Dispatcher Router

- `TutorInteractiveWorker` claim durable job 后，由 `TutorRuntimeDispatchRouter` 根据冻结 runtime kind 选择 Harness 或 Codex dispatcher。
- Codex dispatcher 不再套 `TutorRunLoop`；Harness dispatcher保持现有 loop。
- feature off 时不启动或不依赖 Codex worker也能完整运行现有产品。

### R3：控制流

- Queue/new input revision 映射为 Codex steer；cancel/supersede 映射为 interrupt。
- Retry 沿用同一 runtime root，不在已发生 message/tool/domain side effect 后跨 Runtime fallback。
- Codex 不可用时阻止新的 Codex admission并给出可见 unavailable；active run 只完成、interrupt 或失败，不静默迁移。

### R4：计划确认边界

- Codex 只生成 append-only draft，不执行 confirm。
- 右侧 LearningPlan confirm entry、确认事务与 LearningTrack 创建继续走现有 Aearn API/domain。
- Desktop继续消费 Aearn snapshot/SSE，仅按需展示 Aearn-owned readiness/error，不显示 Codex控制面。

## 范围外

- 已存在 conversation/run 的迁移。
- 所有 Tutor scope、proactive、Lesson、Exercise、Review 的全量切换。
- 双写比较、跨 Runtime 自动 fallback、生产发布与真实用户 rollout。

## 验收标准

- [ ] feature off 时所有新旧 run 均为 `harness_v1`，现有回归测试通过。
- [ ] feature on 且 readiness通过时，只有新 `plan_drafting` run冻结为 `codex_sidecar_v1`。
- [ ] 客户端伪造 runtime参数无效；run创建后不能切换 runtime kind。
- [ ] Queue/steer、cancel/interrupt、Retry在 Codex路径有确定性测试。
- [ ] Codex worker unhealthy 时新 admission fail closed并显示安全错误，Harness scope不受影响。
- [ ] action/tool失败、interrupt或Runtime crash不会出现空白 Turn或吞掉已批准 message。
- [ ] Draft确认和LearningTrack创建仍由现有 Aearn确认事务完成。
- [ ] rollback只需关闭新 admission；active/历史 Codex evidence保留且不跨 Runtime续跑。
