# 技术设计：Python LessonDocument 有界修复生成

## 1. 设计目标

在不放宽 LessonDocument schema、citation、quality 和 publication 权威的前提下，为当前 learner-visible Lesson authoring 增加一次服务端控制的修复机会：第一次候选被严格校验拒绝后，服务端把“哪里错了、必须如何修正”转换为有界、版本化、无敏感内容的反馈，再调用同一 provider/model 一次。

设计同时补齐安全 attempt receipt 和当前 Desktop prepare/read DTO 的边缘一致性。默认测试全部使用 fake provider；本任务不执行真实 provider smoke。

## 2. 任务归属与 RAG 2.0 边界

本修改**不并入** `09-03-rag-language-ecosystem-adaptive-retrieval`：

- RAG 2.0 的职责是 `Subject -> Corpus -> Coverage -> Retrieval -> Plan preflight`，解决“证据是否正确、足够、版本匹配”。其一期 adapter 为 default-off/shadow，不改变当前 learner-visible Lesson。
- 本任务修改当前生产形态的 Lesson authoring：证据已经由现有 grounding 选定后，provider candidate 如何校验、反馈、重试、记录和投影。
- 二者通过既有 `LessonSourceSnapshot` 边界兼容。未来 RAG v2 adapter 只需提供相同 immutable snapshots，不应复制 repair loop。
- 不把 LangChain corpus、user-uploaded material、public RAG v2 rollout 或计划迁移引入本任务。

## 3. 当前失败链路

`prepare route -> durable run -> BackgroundTask -> persisted grounding -> standard provider call -> parse/identity/quality -> personalized provider call -> parse/identity/quality -> atomic publish`

当前任一 provider/parse/identity/quality invalid 都会立即让整个 run 失败。现场第一次 Python run 为 `LESSON_DOCUMENT_INVALID`，后来新建 run 成功，说明至少存在可通过重新生成恢复的瞬态 invalid。

## 4. 版本化反馈合同

新增内部合同 `lesson_author_feedback_v1`，只作为第二次 provider 请求的一部分，不进入 learner public API。

建议结构：

```json
{
  "schema_version": "lesson_author_feedback_v1",
  "document_kind": "standard",
  "failed_stage": "candidate_contract",
  "previous_attempt_index": 1,
  "issues": [
    {
      "code": "LESSON_BLOCK_FIELDS_INVALID",
      "location": "blocks[5]",
      "constraint": "code_example must contain only the registered exact fields"
    }
  ]
}
```

约束：

- `document_kind` 仅为 `standard | personalized`。
- `failed_stage` 仅为 `provider_response | candidate_shape | candidate_contract | candidate_identity | quality_gate`。
- 最多 12 个 issue；code、location 和 constraint 都有字符上限。
- location 只包含稳定字段路径、block index 或模型自己生成的合法 block ID；不包含数据库 ID、user/track/run ID、URL、路径或命令。
- constraint 来自服务端固定映射或现有静态质量门消息；不回显 candidate 字段值或大段原文。
- 未知/额外模型字段名只在通过稳定 token allowlist、长度和数量限制后用于 location；否则降级为文档级 issue。
- feedback 自身使用 canonical JSON SHA-256；receipt 只持久化安全诊断投影和 feedback hash。

## 5. 可重试分类

### 5.1 可以额外调用一次

1. Provider structured response invalid：
   - envelope invalid；
   - content missing；
   - content not JSON object；
   - response incomplete，且可以通过“输出更短、只返回一个 JSON object”纠正。
2. Candidate shape/contract invalid：
   - 缺少/多出字段；
   - 未注册 block type；
   - block/order/citation handle/字段类型或长度不合法；
   - document `language_id/knowledge_key` 与请求不一致。
3. 可由模型重写候选修复的 quality issue：
   - 缺 heading/objectives/concept/summary；
   - 事实块缺 citation；
   - authority note 缺官方 citation；
   - coverage 不完整；
   - code language/execution claim 错误；
   - gate duplicate 或 personalized Gate/coverage/scope 发生改变；
   - 候选包含被禁止的 HTML/script/style/internal marker。

### 5.2 不自动重试

- `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`；
- provider 配置缺失；
- retryable HTTP/transport 已由 LLM client 耗尽其预算；
- provider 明确 response failed；
- source registry/language/URL/hash integrity 错误；
- standard lineage/orchestration 内部错误；
- track/progress/source set stale；
- lease generation 丢失或 duplicate dispatcher；
- 未知异常。

这些错误继续 fail-closed，不向模型发起无意义或可能扩大成本的调用。

## 6. Authoring orchestration

将“调用 provider”和“记录最终 attempt outcome”拆开，避免当前 provider 返回成功但 candidate/quality 失败时 receipt 仍错误记录为 success。

standard 与 personalized 共用一个 **run-level repair budget = 1**；不能各自额外调用一次。内部 helper 接收同一预算对象：

```text
repair_budget = 1
standard = author_and_validate(standard_request, repair_budget)
personalized = author_and_validate(personalized_request, repair_budget, standard)

author_and_validate(request, shared_repair_budget, standard_document?)
  feedback = null
  document_attempt = 1
  loop:
    response_or_error = call same provider/model(request, feedback)
    if provider error:
      build safe diagnostic
      record attempt receipt as invalid/unavailable/failed
      if retryable and shared_repair_budget.take_one():
        feedback = diagnostic.to_feedback()
        document_attempt += 1
        continue
      raise terminal LessonAuthoringFailure

    try:
      rewrite evidence handles
      parse exact candidate
      assert scope identity
      run deterministic quality gate
    except validation/quality error:
      build safe diagnostic
      record attempt receipt as invalid
      if repairable and shared_repair_budget.take_one():
        feedback = diagnostic.to_feedback()
        document_attempt += 1
        continue
      raise terminal LessonAuthoringFailure

    record attempt receipt as success
    return validated document + quality report
```

standard 完成后才开始 personalized。如果 standard 已消耗唯一 repair budget，则 personalized 的任何后续 invalid 直接 fail-closed；反之 personalized 可使用尚未消耗的预算，并必须携带已验证 standard document 与“保留 standard coverage/Gate contract”的反馈。任何阶段预算耗尽都不发布半成品；最终 publish transaction 仍是唯一 authority。

## 7. Attempt receipt 与数据库兼容

在现有 `tutor_lesson_authoring_attempt_receipts` 增加一个 learner-private、allowlisted `diagnostic_json jsonb NOT NULL DEFAULT '{}'`，并增加 JSON object CHECK。

新记录建议包含：

- `schema_version=lesson_author_attempt_diagnostic_v1`；
- `document_kind`；
- `document_attempt_index=1|2`；
- `failure_stage`；
- `issue_codes[]`；
- `issue_locations[]`；
- `feedback_hash`（只有生成 feedback 时存在）。

不持久化 constraint 文本、prompt、provider body、reasoning 或 raw candidate。provider/model/protocol/usage 应从合法 response 或 `LLMInvalidResponseError` 的安全 metadata 保留；确实不可得时继续使用明确的 configured/unknown 值。

兼容规则：

- 旧行通过 default `{}` 继续可读。
- receipt 仍 append-only，`(run_id, attempt_index)` 唯一。
- run `attempt_count` 表示已经记录/预留的全局 provider attempt index；standard/personalized 各自的第几次由 diagnostic JSON 表达。
- duplicate lease owner 不能覆盖已有 receipt 或发布第二个 winner。
- schema fragment 使用 fresh-create 列定义加 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`，bootstrap twice 必须通过。

## 8. Provider 请求构造

`_author_messages(request, feedback=None)` 保留现有 system instruction、canonical example 和原始 safe request payload。仅第二次调用向 user payload 增加 exact `previous_attempt_feedback`。

不附带第一次 candidate。这样：

- 模型知道错误位置和约束；
- 不会因为回传整份失败内容扩大 token、重复潜在敏感 marker 或形成 prompt injection 回声；
- 每次 request hash 能准确反映是否携带反馈；
- provider/model/protocol 不变，不发生 fallback。

## 9. API 与 Desktop 一致性

### 9.1 prepare replay

当前已有 assignment 时 service 返回完整 ready state 加 `idempotent_replayed`，但 Desktop prepare parser 只接受 prepare response。服务端应统一返回：

`status, track_id, knowledge_key, authoring_run, idempotent_replayed, should_dispatch`

ready/idempotent 分支使用 `authoring_run=null`，route 移除内部 `should_dispatch` 后符合现有 Desktop `LessonPrepareResponse`。

### 9.2 cancelled/missing

`_project_state` 只有 public status 为 `preparing | failed` 时才附加 `authoring_run`。cancelled 映射 missing 时不附加该字段，保持 Desktop missing exact parser。

### 9.3 learner-visible failure

public Lesson state 不暴露内部 diagnostic JSON 或模型反馈。预算耗尽后继续显示稳定 `LESSON_DOCUMENT_INVALID` / `LESSON_DOCUMENT_QUALITY_BLOCKED` 与现有“重试准备”。诊断细节仅进入私有 receipt 和测试/维护读取。

## 10. 并发、幂等与恢复

- prepare idempotency 仍由 `user_id + run_kind + idempotency_key + request_hash` 控制。
- semantic repair 是同一 run 内的内部 provider attempt，不创建第二个 run。
- publish 前重新校验 lease、track/progress/revision、source set hash 和 current evidence。
- 不在本任务中新增 Lesson reconcile worker 或改写 BackgroundTask 调度；长期 pending recovery 与 bounded UI polling作为后续独立任务记录。

## 11. 测试设计

### 后端

- standard 第一次 contract invalid -> 消耗唯一共享 budget -> feedback -> 第二次成功 -> personalized 首次成功。
- standard 首次成功 -> personalized 第一次 Gate/coverage quality issue -> 消耗唯一共享 budget -> feedback -> 第二次成功。
- standard 已消耗 budget 后 personalized invalid，或使用 budget 后第二次仍 invalid -> run failed、无 document/assignment。
- no evidence/config unavailable/transport exhausted/source integrity/stale/lease loss 不进入 semantic retry。
- provider invalid subtype、model/usage metadata、document kind、failure stage、issue codes、feedback hash 正确写 receipt。
- response 返回后 candidate invalid 时 receipt outcome 必须是 invalid，而不是 success。
- duplicate/replay 只有一个 publication winner。
- bootstrap twice 和新 CHECK/column/immutable trigger。
- prepare ready replay 与 cancelled/missing public shape。

### Desktop

- `toLessonDocumentState` 覆盖四状态与 cancelled/missing compatibility fixture。
- `toLessonPrepareResponse` 覆盖 preparing、failed、ready idempotent replay。
- `LessonDocumentPage` 覆盖 failed code/message/retry、preparing poll、ready render；不调用真实 provider。

## 12. Rollout 与回滚

- 本地实现默认立即作用于当前 Lesson authoring，但严格限制为同 provider/model、每个 authoring run 全程最多一次额外调用；standard 与 personalized 共享该预算。
- 若回归或成本不可接受，代码回滚到单次调用；新增 nullable/defaulted diagnostic column 与历史 receipt 保留，不删除证据。
- 不自动重试用户当前已经完成的 Python run，不迁移或删除已有 failed run。
- 不修改 RAG 2.0 feature gate、corpus state、LangChain track 或真实 provider 配置。
