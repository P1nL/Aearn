# 实施合同摘录：Lesson authoring repair

本文件用于避免大型 source-of-truth 在 sub-agent context injection 中被截断。以下内容是相关原文件的任务级摘要；实现和检查时仍应按锚点读取原文。

## Backend Lesson Authoring Quality Gate

来源：`.trellis/spec/backend/quality-guidelines.md:3501-3584`

- Authoring 只消费 persisted、registry-owned、allowlisted grounding；provider 只收到短 evidence handles。
- provider 返回 candidate，服务端拥有 handle rewrite、source snapshots、canonical hash、quality、publication 和 assignment lifecycle。
- standard/personalized 都使用注册的十类 block exact parser；不得 HTML/Markdown/static-template/cross-provider fallback。
- factual blocks 必须 citation；authority note 必须 official；personalized 必须保留 standard coverage 与 Gate contract。
- no evidence、provider unavailable、candidate invalid、quality blocked、stale/lease/unknown 各自稳定 fail closed。
- attempt receipt 只允许 safe provider/model/protocol/outcome/usage 与 hash，不得 prompt/body/reasoning/raw document/path/command/credential。
- 默认测试不能访问网络；真实 provider smoke 单独批准。

本任务扩展：对显式 allowlist 的可修复 invalid/quality issue，同 provider/model 最多额外一次，并发送 `lesson_author_feedback_v1`；严格 gate 与最终发布权威不变。

## Database / Receipt

来源：`aearn/services/api/app/db/schema/080_lesson_teaching_practice.sql:162-232,371-374`、`.trellis/spec/backend/database-guidelines.md:25-38,133-142`

- authoring run 是 durable state/lease/CAS；attempt receipt 以 `(run_id, attempt_index)` 唯一并由 immutable trigger 拒绝 UPDATE/DELETE。
- usage 缺失必须 `usage_available=false` 且 token columns 为 NULL，不写 0 占位。
- schema 通过排序 manifest 在 caller-owned transaction 中 repeatable bootstrap；新增列采用 fresh create + additive `ADD COLUMN IF NOT EXISTS`，bootstrap twice 必须通过。
- 本任务只给既有 receipt 增加 defaulted private `diagnostic_json`，不新增 user-owned root table，因此 cutover/reset 删除顺序不应改变，但测试必须验证。

## Public API

来源：`docs/architecture/api-contract.md:503-519`

- Lesson GET 返回 `missing | preparing | ready | failed`；ready 只含 learner-safe document、active assignment、source snapshots 和 optional proposal。
- prepare 使用 expected track/progress version 和 idempotency key 创建/replay durable run，新 run 为 202；dispatch 不持有长事务。
- stable failures 包括 evidence insufficient、generation unavailable、invalid、quality blocked、version/assignment conflict。
- public projection 禁止 prompt、provider body、reasoning、internal quality report、full source、hidden test、answer、command、path、credential。

本任务扩展：prepare replay 统一为 compact prepare response；private diagnostic/feedback 不进入 public DTO。

## Desktop Unknown Boundary

来源：`.trellis/spec/frontend/type-safety.md:152-217`、`.trellis/spec/frontend/component-guidelines.md:122-172`

- 所有 Lesson response 从 `unknown` exact parse；按状态校验 top-level keys、十类 block、连续 order、citation membership、URL/enums/timestamps。
- 未知或额外字段显示 visible contract error，不得 cast、`any`、HTML/Markdown fallback。
- LessonDocumentPage 拥有 loading/prepare/retry/poll/start/refresh/migration 与 safe errors；failed 显示 code/message/retry。
- browser/fixture 要覆盖 missing/preparing/ready/failed-retry；不调用真实 provider。

## RAG 2.0 边界

来源：`.trellis/tasks/09-03-rag-language-ecosystem-adaptive-retrieval/prd.md:93-112,138-161`、`design.md:428-433`

- RAG 2.0 负责 Subject/Corpus/Coverage/Retrieval/Preflight；phase 1 adapter 为 default-off/shadow。
- existing Lesson authoring 继续使用 v1，未来 adapter 只转换为现有 `LessonSourceSnapshot` 语义。
- phase 1 不发布真实 LangChain corpus/learner-visible ecosystem Lesson，也不修复当前 active track。
- 因此本任务独立拥有现行 authoring repair；RAG 2.0 不复制 retry/feedback/persistence 逻辑。
