# 修复 Python 课程学习区文档生成失败

## Goal

让已有可信 Python 教材来源的课程在学习工作区中可靠生成并展示右侧 LessonDocument；当 provider 输出暂时不符合严格结构时，系统仍保持 fail-closed、可审计和可恢复，而不是要求用户在不知道原因的情况下反复手动尝试。

## Background / Confirmed Facts

- 用户当前有两条课程主线：LangChain 课程无对应教材，本任务明确不处理；Python 课程有可用可信来源，应能生成课程文档。
- 当前本地实例中，两条 track 都是服务端 `language_id=python`；LangChain current key 为 `lc-overview`，Python current key 为 `n1_1_variables_and_types`。
- LangChain run 以 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT` 失败，符合本轮 out-of-scope 边界。
- Python 第一次生成在 2026-09-03 17:16:33 以 `LESSON_DOCUMENT_INVALID` 失败；同日 19:42 发起的显式重试在 19:43 成功，发布 active assignment 与 11-block LessonDocument。
- 2026-09-04 的只读现场检查确认：Python Lesson GET 返回 HTTP 200 / `status=ready`；live JSON 通过当前 Desktop `toLessonDocumentState` strict parser。
- 当前 persisted Python grounding 为 1 个 chunk / 1 个 source，因此本次 Python 失败不是“来源索引为空”。
- 现有 LLM client 只对 retryable HTTP/transport 做 bounded retry；Lesson authoring 遇到结构化输出或 candidate contract invalid 时会直接终止整个 run。
- 第一次 invalid receipt 只保留通用 `LESSON_DOCUMENT_INVALID`，没有足够的 allowlisted failure stage/kind 来判断是 provider envelope/JSON 还是 Lesson block/citation/scope 校验失败。
- 工作区当前存在与本任务无关的并行改动及未跟踪路径；实现必须窄范围修改和验证，不得 reset/clean/覆盖它们。

## Requirements

### R1. 保持服务端严格发布权威

- 课程正文只能从 persisted、registry-owned、allowlisted grounding 生成。
- standard 与 personalized 文档仍须通过 exact schema、citation、scope、quality 和 publication gate。
- 不得增加静态课程模板、HTML/Markdown fallback、跨 provider/model fallback，或让 Desktop 自行生成课程内容。

### R2. 改善瞬态 invalid 的恢复能力

- 对可安全修复的 provider structured-response invalid、Lesson candidate contract invalid，以及仅依赖当前证据即可纠正的 deterministic quality issue，在同一 authoring run、同一 provider/model 下最多自动额外调用 1 次。
- 第二次调用必须收到服务端生成的版本化 `lesson_author_feedback_v1`：包含 `document_kind`、失败阶段、稳定 issue code、可选 field path / block ID 和具体约束；模型应明确知道上一版哪里不符合契约。
- feedback 只能从 adapter/parser/quality gate 的 allowlisted 结果构造，不得回传 raw provider body、reasoning、完整失败候选、内部 ID、路径、命令、credential 或数据库信息。
- 每次 authoring 调用必须独立记录安全 receipt；第一次失败和第二次结果均可审计，重复或恢复不得发布两个 winner。
- `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`、配置缺失、transport budget 耗尽、scope/version/source stale、lease loss，以及无法通过重写候选解决的 quality issue 不自动重试。

### R3. 增强安全诊断

- failed run/attempt 应记录 allowlisted failure stage/kind，使维护者可区分 provider envelope、missing content、non-JSON、standard candidate、personalized candidate、citation/scope 或 deterministic quality failure。
- 公共 UI 继续只显示 learner-safe code/message；不得暴露 prompt、provider body、reasoning、完整候选文档、credential、路径或命令。
- 若底层异常带有安全 model/usage 元数据，应在不泄露内容的前提下保留到 attempt receipt。

### R4. 修复 Desktop 状态与 DTO 边缘兼容

- Python Lesson 为 ready 时，Desktop 必须通过 strict parser 并显示真实 11-block document/source，而不是报 invalid payload。
- prepare 在已有 assignment/幂等 replay 分支返回成功时，Desktop 不得因响应 shape 差异报错。
- missing/cancelled/recovery 分支的服务端 projection 与 Desktop parser 必须有唯一一致契约。
- failed 状态必须同时显示 learner-safe message、稳定 failure code 和可用的显式重试动作。

### R5. 覆盖恢复测试

- 后端测试覆盖：首次 invalid 后收到精确 feedback 并 bounded recovery 成功、预算耗尽后 fail-closed、standard/personalized 各阶段、repairable quality feedback、无来源/不可修复 quality/version/lease 不重试、attempt receipt 与 single publication winner。
- Desktop 测试覆盖：missing、preparing、failed、retry、ready、prepare replay 与 parser edge shape。
- 默认自动测试使用 fake provider，不调用真实 provider，不修改生产数据。

## Acceptance Criteria

- [x] AC1：fake provider 第一次返回可修复 invalid、下一次根据 `lesson_author_feedback_v1` 返回合法 candidate 时，同一 authoring run 最终 `completed`，只发布一份 standard、一份 personalized 与一个 active/proposed assignment。
- [x] AC2：第二次模型请求包含精确且有界的失败阶段、issue code、field path / block ID 与约束；不包含 raw provider body、reasoning、完整失败候选、内部 ID、路径、命令、credential 或数据库信息。
- [x] AC3：可修复 deterministic quality issue 能进入同一份 feedback/retry 流；不可通过重写候选解决的来源、版本、lease 或系统错误保持 fail-closed。
- [x] AC4：超过最多 1 次额外调用的恢复预算后，run 稳定为 `failed`，公开 code/message learner-safe，数据库中无半成品 document/assignment。
- [x] AC5：无 persisted evidence、配置缺失、transport budget 耗尽、track/progress/source stale、lease loss 或不可修复 quality issue 不会进入 semantic retry。
- [x] AC6：每次 provider/candidate 尝试都有独立 safe receipt，能定位 document kind、failure stage/kind 和 issue codes，但不包含 prompt、provider body、reasoning、raw candidate、路径、命令或 secret。
- [x] AC7：当前 Python ready API fixture/live-shape 能通过 Desktop parser，并渲染真实 LessonDocument；prepare replay 与 cancelled/missing shape 不再产生客户端 invalid-payload 错误。
- [x] AC8：failed UI 显示稳定 code/message 和重试动作；preparing 继续只显示服务器权威状态，不生成本地 fallback。
- [x] AC9：focused 后端、Desktop parser/component 测试和相关最小质量门通过；测试过程不调用真实 provider，且不修改 LangChain 来源策略、无关并行改动、受保护前端原型、生产数据或真实 provider 配置。

## 与 `09-03-rag-language-ecosystem-adaptive-retrieval` 的关系

- RAG 2.0 任务会改善“课程是否有正确、足够且与 Subject/版本匹配的教材证据”：引入 Subject/生态身份、版本化 Corpus、facet coverage、bounded retrieval 和 plan preflight，避免 LangChain 节点错误回退到普通 Python 教材。
- 但截至 2026-09-04，该任务仍处于 `planning`、`0/6` children 完成；一期 adapter 为 default-off/shadow，明确不切换 learner-visible Lesson，也不发布真实 LangChain corpus。因此仅完成该一期任务不会立即改变用户当前右侧栏行为。
- 本次 Python 现场已有 persisted source，失败码是 `LESSON_DOCUMENT_INVALID`，后续手动重试成功；这属于 provider/candidate 结构失效及恢复/诊断问题，不是 RAG coverage 问题，RAG 2.0 不能替代本任务。
- 两项任务互补且无需互相阻塞：RAG 2.0 负责“取对证据并在证据不足时提前阻断”，本任务负责“已有足够证据后生成过程的 bounded recovery、safe diagnostics 与 Desktop DTO 一致性”。
- 当前修复必须保持未来 RAG v2 `LessonSourceSnapshot` adapter 兼容，但不把 default-off RAG v2、真实 corpus 发布或 LangChain 教材补齐拉入本任务。

## Out of Scope

- 为 LangChain 新增、抓取、注册或索引教材来源。
- 设计 user-uploaded material 到 LearningTrack/Lesson 的新持久化绑定体系。
- 放宽 LessonDocument schema/quality/citation gate，或使用无来源模板兜底。
- 跨 provider/model fallback。
- 真实 provider smoke、自动替用户重试当前课程、生产迁移、部署、push 或 release。
- 除非实现研究证明是本修复不可分割的一部分，否则不在第一阶段重做通用 grounding reindex/startup 体系。

## Key Decisions

- 用户已批准：对可安全修复的 Lesson authoring invalid/quality failure，在同一课程生成流程内最多自动额外调用 1 次相同 provider/model。
- 用户要求：第二次调用必须收到服务端生成的精确错误反馈，明确上一候选的失败阶段、位置和约束，而不是原样重复同一 prompt。
- 本任务保持独立，不并入 `09-03-rag-language-ecosystem-adaptive-retrieval`。RAG 2.0 负责 Subject/Corpus/Coverage/Retrieval/Preflight；本任务负责已有证据后的 authoring repair loop、safe diagnostics 和当前 Desktop 契约。
- 当前无阻塞产品问题；下一步完成 design、implement 与 sub-agent context manifest 后提交最终计划审核。
