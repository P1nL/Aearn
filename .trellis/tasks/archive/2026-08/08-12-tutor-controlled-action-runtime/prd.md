# Tutor 统一受控 Action Runtime

## 目标

在现有 exact Skill、capability、effect、execution intent/job 和 PostgreSQL receipt 基础上，建立统一、可扩展、可取消、可验证、可恢复的受控 Action Runtime，使 grounding、计划生成、练习执行、模型代码审核和未来审核过的外部连接器共享一致的调用生命周期。

本任务不是开放任意 shell、文件系统或 MCP，也不是推倒现有 capability/effect。它负责把现有分散机制收敛为通用 action contract，并继续保持 learner-facing Tutor 的 deny-by-default、安全投影和服务器 authority。

## 用户价值

1. 工具调用不再只以“handler 返回成功”作为完成，而有独立验证和恢复结果。
2. 运行中取消、超时、暂时失败和永久拒绝拥有一致状态与用户反馈。
3. provider 能看到已执行 action 的安全元数据，避免重复调用或基于过期结果继续推理。
4. 新增审核过的 action 不需要复制一套特殊 persistence、trace 和 retry 逻辑。
5. 模型代码审核、练习和 grounding 可以形成 inspect/run/verify/recover 闭环。

## 依赖

必须完成：

- `08-12-tutor-authoritative-context-facts`。
- `08-04-exercise-gates-execution-unlock`。
- 现有 Tutor Harness、Skill catalog、capability/effect persistence 和 executor lifecycle。

本任务完成后：

- `08-04-model-code-review-exercises` 才能使用统一 parser/compile/test/rubric verification lifecycle。
- `08-04-learning-workspace-context-references` 才能展示统一 action/verification/recovery projection。
- `08-04-learning-agent-integration-migration-qa-docs` 才能进行最终双重 authority 审计。

## 已确认事实

1. Aearn 已有 immutable capability/effect descriptors、exact Skill selection、policy tags、revision/lease gate、receipt 和 default deny。
2. runner execution 已有 intent/job、lease、launch token、result authority、timeout 与安全输出，但与 generic capability lifecycle 仍是不同 contract。
3. 当前 action 结果回灌主要依赖特定 capability/effect context，缺少统一的 executed-action metadata、verification 和 recovery 状态。
4. learner-facing Tutor 不需要 Codex 式任意宿主 shell/Git；工具广度必须由目标场景和 resource policy 审核。
5. `08-12-tutor-authoritative-context-facts` 将提供统一 `AuthoritativeContextSnapshot`；action receipt 必须通过该投影进入后续 provider context。
6. 研究依据位于 `.trellis/tasks/archive/2026-08/08-11-codex-aearn-agent-architecture-comparison/research/`。

## 需求

### R1 — 统一 Action contract

定义并版本化：

- `ActionDescriptor`
- `ActionInvocation`
- `ActionExecutionResult`
- `ActionVerificationResult`
- `ActionReceipt`
- `ActionRecoveryDirective`

每个 action 必须声明 stable id/version、input/output schema、owner adapter、allowed origins/task kinds、resource profile、timeout、side-effect class、retry class、verification policy 和 public projection policy。

### R2 — 与现有 capability/effect 兼容

- capability 继续表示模型可请求的受控读取/生成 action。
- effect 继续表示需要事务提交的领域 mutation proposal。
- executor intent/job 继续拥有练习代码执行权威。
- Action Runtime 作为统一 orchestration/receipt 层，不复制上述领域表的业务真相。
- 同一 action invocation 只能有一个 authority owner，禁止 capability receipt 与 action receipt 分别声称执行成功。

### R3 — 生命周期与状态机

至少支持：

- `requested`
- `admitted`
- `running`
- `succeeded_unverified`
- `verified`
- `retryable_failed`
- `permanent_failed`
- `denied`
- `cancel_requested`
- `cancelled`
- `timed_out`
- `superseded`

状态迁移必须绑定 run、input revision、lease/action generation 和 idempotency key。stale/superseded action 不能写最终业务结果或回灌为 current evidence。

### R4 — Resource 与 permission policy

- resource profile 至少表达：approved grounding source、artifact IDs、execution profile、network class、temporary workspace、最大输入/输出、成本和并发限制。
- 未声明资源默认不可用；provider 不能提交 URL、路径、命令、镜像或环境变量提升权限。
- learner-facing API 不提供任意 permission escalation；需要用户确认的领域 mutation 继续由显式 API action 完成。
- 未来 MCP/connector 只能通过审核 adapter 和 resource allowlist 接入，不直接暴露动态任意 server。

### R5 — 取消、重试与恢复

- action 支持 cancellation token/lease fencing；取消请求与实际终止分开记录。
- retry 只能由 descriptor policy 和安全错误分类允许；不得由模型自由决定无限重试。
- retry 保留 invocation lineage，不重复副作用。
- verification 失败时可以产生 bounded recovery directive，例如重新读取、重新执行、请求澄清或安全终止。
- 每个 run 的 action、retry、verification 和 recovery 次数受服务器预算限制。

### R6 — Verification

- action success 与业务 verified 必须分开。
- grounding 验证 source/allowlist/citation coverage。
- plan drafting 验证 schema、facts fingerprint 和 DAG contract。
- runner 验证 terminal result、test contract、artifact/version 和 safe projection。
- model code review 预发布验证 parser/compile/typecheck/test/rubric/reachability。
- verifier 不能读取或泄露超过其 resource profile 的数据。

### R7 — Context feedback 与可观测性

- `AuthoritativeContextSnapshot` 增加 bounded executed-action receipt section。
- 模型只看到 action id/version、status、safe summary、artifact handle、verification status 和 retry/recovery hint。
- raw command、路径、hidden tests、private rubric、provider body、secret 和内部错误不进入 context/public SSE。
- trace 能关联 model call → action invocation → execution → verification → recovery → final answer。

### R8 — 第一批迁移 action

至少迁移并验证：

1. `grounding.retrieve`
2. `learning.plan.draft`
3. `runner.execute`

后续 `model_code_review.validate` 由 `08-04-model-code-review-exercises` 在该 contract 上实现。

## 验收标准

- [ ] 三个第一批 action 使用同一 descriptor、invocation、receipt、状态机和 trace contract。
- [ ] 现有 capability/effect/execution authority 不被复制，业务写入仍由原 owner transaction 完成。
- [ ] action 支持 timeout、cancel、retryable/permanent error、supersede 和 idempotent replay。
- [ ] action success 与 verification success 独立，验证失败不会被发布为完成。
- [ ] stale revision/lease/action generation 不能提交或回灌 current evidence。
- [ ] resource profile 默认拒绝未声明 URL、路径、命令、镜像、网络和 artifact scope。
- [ ] executed-action metadata 通过 `AuthoritativeContextSnapshot` 安全进入下一轮，且不会重复调用已 verified action。
- [ ] public API/SSE/trace/export 不泄露 raw command、路径、secret、hidden test、private rubric 或 provider body。
- [ ] grounding、plan drafting、runner execution 的原有测试和新增统一 lifecycle 测试通过。
- [ ] model code review child 能在不修改 Action Runtime 核心状态机的情况下注册预发布验证 action。

## 范围外

- learner-facing 任意 shell、Git、filesystem patch 或动态 MCP server。
- 替换 PostgreSQL 领域表为通用 action log。
- 多 agent、thread fork 或通用 coding project workspace。
- production container image fleet 的构建、签名和发布。
- 未经单独批准的 commit、push、deploy 或生产数据迁移。
