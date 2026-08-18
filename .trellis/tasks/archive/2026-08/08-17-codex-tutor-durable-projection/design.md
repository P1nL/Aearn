# 技术设计

## 数据模型

### `tutor_runs.runtime_kind`

闭合枚举 `harness_v1 | codex_sidecar_v1`，创建后不可变。迁移默认 `harness_v1`，避免历史 run 被误认成 Codex。

### `tutor_run_runtime_bindings`

建议保存 `run_id`、user/conversation scope、runtime kind/version、protocol version、external thread/turn id、connection generation、state 与 terminal timestamps。外部 ID 需要唯一性/长度约束并按敏感诊断数据处理。

### `tutor_runtime_item_receipts`

以 run + external item hash/sequence 幂等，字段仅允许 item kind/status/tool name/hash/safe code/timestamp。不得加入通用 JSON raw payload 列。

## Event Projector

新增 `TutorRuntimeEventProjector` 接收 Aearn-owned Runtime events：

- turn started -> in_progress/process；
- tool started/completed -> bounded process step 与 safe receipt；
- final agent message -> safety + ownership + revision 后写 Tutor message；
- turn completed -> completed；
- interrupted -> interrupted，不生成猜测式 final；
- failed/unavailable -> failed/error item，保留安全 code。

Projector 不消费 Codex wire DTO，由 Adapter 先规范化。

## 消息与 Tool 解耦

learner-visible message 和 tool/domain outcome 分别持久化。Tool 失败只影响对应 process/terminal 状态，不得回滚或删除已经通过安全门的 message；反之，unsafe final message 不得掩盖已成功提交的 domain receipt。

## 幂等与 Fence

每次写入前验证 run active/terminal、lease owner/generation、input revision、runtime binding generation。Receipt 使用唯一键或 compare-and-set；重复 event 返回已有投影。Late event 只写 allowlisted ignored code，不能改变当前状态。

## SSE 与 Desktop

继续由 Aearn conversation snapshot/event service发布已有 public DTO。若需要 runtime readiness，只新增 Aearn 命名的安全状态，不公开 Codex protocol细节。Desktop 不增加 Codex连接或认证代码。

## 迁移与回滚

数据库迁移仅 additive。关闭 Codex admission后保留 binding/receipt 用于审计；无需删除历史行。旧 Harness路径不要求创建外部 binding。
