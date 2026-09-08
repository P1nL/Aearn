# 后端现场研究：Python 课程 LessonDocument 生成失败

- 日期：2026-09-04
- 范围：只读检查当前本地 PostgreSQL、公开 Lesson API、运行状态、后端代码与测试；未触发新的课程生成，未调用真实 provider，未修改业务数据。

## 结论

当前 Python 课程并非仍处于失败状态：服务端已经存在 active assignment 与 11-block personalized LessonDocument，公开 GET 返回 `status=ready`，当前 Desktop strict parser 也能成功解析。用户遇到的真实失败对应 2026-09-03 的第一次生成：run 以 `LESSON_DOCUMENT_INVALID` 终止；同日晚些时候的显式重试成功。

因此本任务的主要修复目标不是放宽前端 parser 或伪造 fallback，而是提高课程 authoring 对单次 provider 结构化输出失效的可恢复性与诊断能力，同时保留严格发布质量门。

## 当前实例证据

### 用户课程

同一当前本地用户（ID 仅记录前缀 `2d4b1036…`）有两条 active track：

1. LangChain 目标 track（`2c0b9859…`），`language_id=python`，current key `lc-overview`。
2. Python 基础 track（`0d7a7fdf…`），`language_id=python`，current key `n1_1_variables_and_types`。

LangChain track 的 2026-09-03 run 为 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`，符合用户本轮明确的“不处理 LangChain 无教材课程”范围。

Python track 的 run 历史：

- 2026-09-03 17:14:49 创建；17:16:33 failed；`attempt_count=1`；`LESSON_DOCUMENT_INVALID`。
- 2026-09-03 19:42:09 创建显式重试；19:43:09 completed；两次成功 provider call 分别生成 standard 与 personalized 文档。
- 成功 run 的安全 receipt 显示 exact provider/model/protocol 为 DeepSeek / `deepseek-v4-flash` / `deepseek_responses`；未保存 provider body 或 reasoning。
- 当前存在一条 active assignment 和一份题为“变量与基本数据类型”的 11-block 文档。

当前 persisted grounding 按语言统计为 Python 1 个 chunk / 1 个 source；本实例不是“Python grounding 全空”。

### 公开 API 与 Desktop parser

- 2026-09-04 对 Python track/current key 执行只读 GET：HTTP 200，`status=ready`，11 blocks，1 source。
- 同一 GET 响应的 top-level、assignment、document、source 与全部 block exact keys 均匹配 Desktop parser，block order 连续且 citation 全部可解析。
- 临时 Vitest probe 直接把 live GET JSON 输入 `toLessonDocumentState`：1 test passed，解析结果 `ready`，标题“变量与基本数据类型”，11 blocks，1 source。临时测试文件随后删除。
- 对 LangChain track/current key 的只读 GET：HTTP 200，`status=failed`，`LESSON_SOURCE_EVIDENCE_INSUFFICIENT`。

## 代码链路

1. Desktop GET + strict parser：`aearn/apps/desktop/src/api/learning.ts:155-166,708-754,1326-1454`。
2. Lesson 页面状态机与用户显式 retry：`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:77-158,385-416`。
3. prepare route 在 commit 后用 FastAPI `BackgroundTasks` 调度：`aearn/services/api/app/routes/lesson_documents.py:129-153`。
4. service 创建 durable pending run，read 按 assignment/latest run 投影状态：`aearn/services/api/app/services/learning/lesson_service.py:50-97,226-292`。
5. dispatcher 读取 persisted grounding，依次生成 standard 与 personalized，全部校验通过后原子发布：`aearn/services/api/app/services/learning/lesson_authoring.py:143-244`。
6. provider candidate 缺字段、非法 block/citation/scope 或 adapter JSON 错误最终映射为 `LESSON_DOCUMENT_INVALID`：`aearn/services/api/app/services/learning/lesson_authoring.py:106-129,343-371`。
7. 通用 LLM client 只对 retryable HTTP/transport 做最多 3 次重试；`LLMInvalidResponseError` 不在该 transport retry 中：`aearn/services/api/app/services/llm/llm_client.py:26-35,169-224,641-658`。

## 已确认的可靠性缺口

### 1. 单次结构化输出失效直接终止整个课程 run

Lesson 需要 standard + personalized 两次 provider call。任一步出现 adapter JSON invalid 或 candidate contract invalid，当前 run 立即 failed；没有 Lesson-authoring 层的 bounded semantic retry。现场第一次失败、后续同请求重新创建 run 成功，证明失败至少具有瞬态/非确定性特征。

不能通过放宽 parser、跳过 quality gate、静态模板或跨 provider fallback 修复；这些都违反 `.trellis/spec/backend/quality-guidelines.md:3525-3560`。

### 2. 失败 receipt 丢失安全诊断维度

第一次 invalid receipt 只记录 `configured-primary / unknown` 与通用 diagnostic code，没有保留 `LLMInvalidResponseKind`、exception 上附带的 model/usage，也无法区分 provider envelope、missing content、非 JSON object，还是 Lesson candidate scope/block/citation 失败。无需保存 raw body，也应保留 allowlisted failure stage/kind。

### 3. pending run 仅依赖请求进程 BackgroundTask 唤醒

route 创建 durable run 后只注册 FastAPI BackgroundTask；未发现 Lesson authoring reconcile/lease recovery worker。API 在 202 后退出可能留下长期 pending/claimed/running。Desktop 每 1.4 秒无限轮询，没有 deadline 或 stalled recovery 提示。此项不是本次现场失败的直接证据，但属于同一路径的恢复缺口。

### 4. 两个 DTO 边缘分支

- 已有 assignment 时 prepare service 返回完整 ready state + `idempotent_replayed`，而 Desktop `toLessonPrepareResponse` 只接受五字段响应；并发/重复 prepare 可能把成功响应报为 invalid payload。
- cancelled latest run 可被 service 投影成 missing + authoring_run，而 Desktop missing parser 不接受 authoring_run。

## 测试缺口

- `test_invalid_or_unavailable_author_fails_closed_without_partial_document` 实际只覆盖 invalid，没有执行 unavailable 分支：`aearn/services/api/tests/learning/test_lesson_document_authoring.py:113-123`。
- 没有“第一次 invalid、同一 run 内 bounded retry 成功”的 Lesson authoring 测试。
- 没有断言每次 provider call/失败阶段都有安全 attempt receipt 的测试。
- 没有 BackgroundTask 丢失后的 pending/lease recovery 测试。
- Desktop 没有 `LessonDocumentPage` 状态机组件测试，也没有 `toLessonDocumentState` / `toLessonPrepareResponse` 专项 parser 测试。

## 规划建议

推荐把 MVP 修复分为：

1. 对 `LLMInvalidResponseError` 与可明确归类的 candidate contract invalid，在同一 authoring run、同一 provider/model 下增加最多 1 次 semantic retry；每次都写独立安全 receipt。证据不足、质量门阻断、scope/version stale 与配置缺失不自动重试。
2. 增加 allowlisted `failure_stage/failure_kind` 诊断，不保存 provider body/reasoning/prompt。
3. 修复 Desktop prepare/missing 边缘 DTO，并增加状态机/parser 回归。
4. pending reconcile 与 bounded polling 可作为同任务第二阶段或明确 defer；它不应阻塞第一版对现场 invalid failure 的修复。

是否接受自动额外一次真实 provider 调用涉及成本与等待时间，是实现前必须由用户确认的产品/风险决策。
