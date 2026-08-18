# Codex Tutor 持久化与公开投影

## 目标

把 Codex Runtime 的外部执行状态安全、幂等地关联到 Aearn TutorRun，并投影为现有 Aearn conversation/turn/item/SSE 契约。Aearn 数据库和 ID 保持唯一产品 authority；Codex ID 只用于诊断与恢复 correlation。

## 依赖

- 父任务：`08-17-codex-runtime-sidecar-integration`。
- 前置任务：`08-17-codex-runtime-adapter-supervisor` 与 `08-17-codex-learning-plan-tools-recovery`。

## 需求

### R1：Runtime 归属与关联

- `tutor_runs` additive 增加闭合 `runtime_kind`，默认 `harness_v1`。
- 增加 run-runtime binding，保存外部 thread/turn correlation、runtime/protocol version、connection generation 与状态。
- Aearn run/conversation/user scope 是主外键 authority；外部 ID 不进入公共 URL 或客户端请求。

### R2：安全 Receipt

- 持久化 allowlisted external item kind、状态、tool name、input/result hash、安全诊断、sequence 和时间戳。
- 禁止保存 raw prompt、reasoning、完整 agent body、tool arguments/results、command/path、credential 或 provider response。
- 领域 mutation 继续使用现有 action/capability receipt，不由 Runtime receipt 取代。

### R3：公开生命周期投影

- Codex turn started、tool activity、agent final message、completed/interrupted/failed 映射为 Aearn 现有 turn/process/message/error item。
- final message 必须通过 ownership、lease、revision、generation 和 safety gate 才可写入 `tutor_messages`。
- failed/interrupted 必须产生可见终态；任何 action/tool 失败不得吞掉已经批准的 learner-visible message。

### R4：幂等与恢复

- 重复 notification、reconnect replay 与 late callback 不重复写 public item或 mutation。
- stale revision/generation 的 item 被忽略并留下安全 receipt。
- Runtime crash 或协议失败能够从 DB authority 恢复 job/run 状态，不依赖 Codex 本地 thread 文件作为唯一事实。

## 范围外

- feature gate 与新 plan-drafting admission。
- Desktop 直连 Codex 或公开 Codex DTO。
- raw reasoning 的公开展示；若无法证明安全，Codex path 使用静态 Think/process。

## 验收标准

- [ ] 新 schema additive、bootstrap/restart安全，既有 run 默认 `harness_v1`。
- [ ] Aearn API/SSE 中不出现外部 thread/turn/item ID、raw reasoning、tool argument 或 provider body。
- [ ] completed、interrupted、failed、tool repair 和 crash 均产生确定性 Aearn lifecycle 投影。
- [ ] final message 与 domain commit 可独立审计；domain commit 成功但 final message unsafe 时不会回滚 mutation，也不会公开 unsafe message。
- [ ] duplicate/replayed item 不重复写 message、process、error 或 receipt。
- [ ] stale generation/revision callback 无法覆盖新 run 或当前 draft。
- [ ] Harness snapshot/SSE 契约和现有 Desktop 类型保持兼容。
