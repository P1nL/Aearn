# 技术设计

## 验收分层

1. 协议层：fake app-server contract与process lifecycle；
2. Runtime层：Adapter、supervisor、health与single ownership；
3. 领域层：typed tools、repair、policy、idempotency；
4. 持久化层：schema、receipt、event projection、SSE；
5. 产品层：new plan-drafting cutover、confirm、Desktop与rollback；
6. 真实smoke：仅在授权后执行。

## 失败矩阵

每个场景记录：触发条件、预期Runtime terminal、Aearn run/turn/item状态、DB receipt、安全public code、是否允许retry、是否需要operator动作。矩阵不得用一个通用 `INTERNAL_ERROR` 覆盖全部情况。

## 安全证据

自动扫描日志、fixtures、snapshot、DB测试数据与public DTO；禁止字段包含raw prompt/reasoning、完整tool body、credential/token、auth文件、command/path和provider body。允许保存版本、method、hash、duration、safe code与opaque correlation。

## 真实 Smoke

Smoke使用隔离Aearn Codex Home、固定binary/version、精确 `deepseek-v4-flash` Responses custom provider、测试账号状态与非生产数据。结果文件只写环境摘要、通过/失败rubric、耗时和redacted diagnostics。若用户未授权，结果明确为 `not_run_requires_approval`。

## 文档结构

优先更新 `docs/README.md` 已索引的source-of-truth，不创建重复规格。至少覆盖 Tutor Runtime架构、开发环境/认证、数据库runtime字段、API/SSE失败投影、plan-drafting用户流和验收证据。

## 父任务关闭条件

Child 1-6均归档，feature默认值与支持边界已记录，父任务跨任务验收全部有证据；否则父任务保持未完成并列出残余风险。
