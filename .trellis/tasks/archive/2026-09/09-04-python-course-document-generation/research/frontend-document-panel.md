# Research: Desktop active Lesson document panel

- Query: 追踪 `learning_workspace` 右侧 active Lesson 文档从路由/track snapshot 到 API DTO、`loading / missing / preparing / ready / failed`、重试和渲染的完整流程；定位“无法生成”文案/错误码，比较 Python 与无教材 LangChain，识别最可能故障与测试缺口。
- Scope: mixed（Desktop、LearningTrack/Lesson API、authoring/grounding、规格与测试；只读分析）
- Date: 2026-09-04

## Findings

### 结论摘要

1. **Desktop 的主状态机和 ready renderer 在静态代码上是连通的，未发现当前正常 `ready` DTO 与 renderer 的直接字段不一致。** `App -> LearningHomePage -> TrackLearningWorkspace -> LessonDocumentPage -> api/learning.ts -> Lesson API` 的正常链路字段基本对齐。
2. **最强根因候选不是 React renderer，而是本地运行时没有持久化 `grounding_chunks`。** Lesson authoring 只查询数据库里的已持久化 grounding，不实时抓取、不使用静态模板；无结果就把 run 标成 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT / 当前没有足够的受信课程来源。`。普通 `app.db.bootstrap` 与 `pnpm dev` 启动链路只建表/seed 语言与 Learning Item，不执行 grounding reindex；现有 Lesson 测试则都显式先执行 fixture reindex，所以没有覆盖真实 bootstrap-only 本地环境。
3. **计划卡“权威来源”不等于 Lesson 可用来源。** plan draft 的 source summary 来自静态 source registry；确认计划时 source summary 没有进入 LearningTrack/Lesson scope。Lesson 生成重新按 `language_id + knowledge_key/title` 查询全局 `grounding_chunks`。因此 UI 可以先显示 Python 官方来源，随后 Lesson 又因索引为空失败。
4. **“有教材 Python”与“无教材 LangChain”目前没有 Lesson 层面的材料差异。** 显式 Python 可直接确认语言；LangChain 仅是语义候选，必须由学习者确认 Python。确认后两者都成为 `language_id=python` 的 track；当前 plan/track/Lesson DTO 没有 user-material/source binding，grounding registry 也没有 LangChain 来源。只要 Python 索引存在，LangChain 节点甚至会 fallback 到任意 Python 官方 chunk；索引不存在时两者同样失败。
5. **Frontend 仍有次级问题：** failed 背景态能显示 code/message，但同步请求错误通常只显示 message；strict parser 错误变成无 code 的 `CLIENT_ERROR`；preparing polling 无上限；`TrackLearningWorkspace` 在 key 缺失时会猜第一个 available node，违反现有 spec；另有两个边缘 response-shape 不一致可触发“invalid payload”。

### 完整链路

```text
App verified tutor route
  -> LearningHomePage GET /api/learning-tracks
  -> track.current_knowledge_key
  -> App TutorSurface{learning_workspace, trackId, knowledgeKey}
  -> TrackLearningWorkspace parallel loads:
       GET track detail + GET roadmap + GET review queue + create/resume conversation
  -> choose/repair knowledgeKey
  -> stable Lesson panel mounts LessonDocumentPage
  -> GET /api/learning-tracks/{track}/lessons/{key}?user_id=...
  -> strict toLessonDocumentState(payload)
  -> loading | missing | preparing | failed | ready
       missing/failed -> POST .../prepare -> durable run -> FastAPI BackgroundTask
       preparing -> GET poll every 1400ms
       worker -> persisted grounding -> primary author twice -> quality -> publish assignment/document
       failed -> stored safe failure code/message -> GET projection -> retry POST
       ready -> LessonDocumentView -> registered LessonBlockRenderer + sources/Gates
```

### 1. 路由、track snapshot 与 active knowledge key

- `App` 的内部路由 union 包含 `learning_workspace {trackId, mode, knowledgeKey, reviewSessionId}`；verified Tutor 首页点击“继续学习”后把 track 与 server `current_knowledge_key` 放入该 surface：`aearn/apps/desktop/src/App.tsx:15-18`, `aearn/apps/desktop/src/App.tsx:126-149`。
- reload 时先从 user-scoped localStorage `aearn.learning-workspace.v1:{userId}` 恢复导航指针；它只是定位信息，不是 Lesson authority：`aearn/apps/desktop/src/App.tsx:31-40`, `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:459-478`。
- Learning Home 的按钮只在 `track.current_knowledge_key` 非空时启用并传递该 key：`aearn/apps/desktop/src/features/learning/LearningHomePage.tsx:123-142`。
- track public DTO 的 key/title 来自 `tutor_learning_tracks.current_knowledge_key` 与 active plan node；service 投影字段在 `aearn/services/api/app/services/learning/track_service.py:354-388`，repository join 在 `aearn/services/api/app/services/learning/track_repository.py:240-277`。
- Desktop 对 track detail/roadmap 做 exact runtime parsing：`aearn/apps/desktop/src/api/learning.ts:117-138`, `aearn/apps/desktop/src/api/learning.ts:601-704`；对应 TS DTO 在 `aearn/apps/desktop/src/contracts/learning.ts:1-65`。
- workspace mount 并行读取 track detail、roadmap、review queue、track-scoped conversation：`aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:129-166`。
- **偏离 spec 的点：** 当 requested/current key 都不可用时，代码使用 `[...availableKeys][0]` 猜首个可用节点：`aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:149-156`；spec 要求 key 缺失时显示 not-ready，不猜首节点：`.trellis/spec/frontend/component-guidelines.md:146-163`。

### 2. 右侧 active Lesson 的装配与显示

- `TrackLearningWorkspace` 始终挂载单一 Lesson sibling；knowledge key 变化时通过 `key={knowledgeKey}` 重建 Lesson page，并传入 exact user/track/key：`aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:393-407`。
- Guided 模式把 Tutor 放 primary、Lesson 放 secondary；Free Reading 反转，符合规格：`aearn/apps/desktop/src/styles/60-learning-workspace.css:454-510`，对应契约 `.trellis/spec/frontend/component-guidelines.md:448-481`。
- 宽屏 Lesson 是右侧 secondary；`secondaryCollapsed=true` 时会被 visibility/pointer-events 隐藏：`aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:83-85`, `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:366-374`, `aearn/apps/desktop/src/styles/60-learning-workspace.css:638-674`。
- `<768px` 一次只显示一个 panel。初始 `activePanel="learning"` 在 Guided 实际对应 Tutor 主区；Lesson 要点击标签“课程”后才获得 `mobile-active`：`aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:81`, `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:352-354`, `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:393-414`, `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx:495-497`, `aearn/apps/desktop/src/styles/60-learning-workspace.css:685-705`。这可能被误认为“右侧没渲染”，但不是生成请求失败。

### 3. Desktop Lesson 状态机、请求与重试

- `LessonDocumentPage` 本地状态包括 `state`, `loading`, `action`, `errorMessage`；初次/每次 key 变化发 GET：`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:51-87`, `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:105-120`。
- GET wrapper 固定请求 `http://127.0.0.1:8001/api/learning-tracks/{track}/lessons/{key}?user_id=...`，并对 payload 调用 `toLessonDocumentState`：`aearn/apps/desktop/src/api/client.ts:3-30`, `aearn/apps/desktop/src/api/learning.ts:155-167`。
- state DTO 为 `missing | preparing | ready | failed`，携带 track/progress versions、assignment/document/sources/update 或 authoring run：`aearn/apps/desktop/src/contracts/lesson.ts:53-118`。
- exact parser 按状态拒绝额外/缺失字段；ready 还验证 block 顺序与 citation membership：`aearn/apps/desktop/src/api/learning.ts:708-754`, `aearn/apps/desktop/src/api/learning.ts:1326-1407`, `aearn/apps/desktop/src/api/learning.ts:1419-1454`。
- `missing` 点击“准备课程”；`failed` 点击“重试准备”。两者都 POST prepare，携带当前 `track_version/progress_version` 与 fresh client action id，然后立即 GET：`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:138-158`, `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:385-390`。
- prepare DTO/HTTP body：`aearn/apps/desktop/src/api/learning.ts:196-220`；服务端 strict request model：`aearn/services/api/app/models/lesson_documents.py:9-26`。
- preparing 时每 1400ms 再 GET；当前实现没有最大次数、deadline 或“仍在队列/重新派发”动作：`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:116-120`。
- ready 后才挂 `LessonDocumentView`、Gate seam 与 sources：`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:390-427`。renderer 明确按注册 block union 渲染，不使用 HTML/Markdown fallback：`.trellis/spec/frontend/component-guidelines.md:122-191`。

### 4. Lesson API、authoring 与状态投影

- 所有 Lesson route 先过 verified gate。GET 调 `LessonDocumentService.read`；prepare/refresh 创建/replay run，commit 后才把 `dispatch_lesson_authoring_run` 放入 FastAPI `BackgroundTasks`：`aearn/services/api/app/routes/lesson_documents.py:27-39`, `aearn/services/api/app/routes/lesson_documents.py:73-86`, `aearn/services/api/app/routes/lesson_documents.py:129-153`。
- service 在 transaction 中校验 scope/version，创建 `pending` durable run；response 为 `preparing` 并带 `should_dispatch`：`aearn/services/api/app/services/learning/lesson_service.py:58-97`, `aearn/services/api/app/services/learning/lesson_service.py:176-198`。
- repository state 读取 active assignment、latest run、latest proposal；active assignment 存在时加载 immutable document/source snapshots：`aearn/services/api/app/services/learning/lesson_repository.py:343-389`。
- service projection：assignment+document -> `ready`；否则 latest run 的 `pending/claimed/running -> preparing`, `failed -> failed`, `cancelled -> missing`：`aearn/services/api/app/services/learning/lesson_service.py:226-252`, `aearn/services/api/app/services/learning/lesson_service.py:276-292`。
- dispatcher 依次 claim、running、读取 scope 与 persisted evidence、调用 primary author 生成 standard 与 personalized 两次、质量校验、最终 transaction 发布 document/snapshots/assignment 并完成 run：`aearn/services/api/app/services/learning/lesson_authoring.py:143-234`, `aearn/services/api/app/services/learning/lesson_repository.py:292-341`, `aearn/services/api/app/services/learning/lesson_repository.py:459-595`。
- authoring 明确无 provider fallback、无静态 Lesson fallback：`aearn/services/api/app/services/learning/lesson_authoring.py:99-136`，架构说明 `docs/architecture/tutor-harness-runtime.md:776-780`。

### 5. 用户看到的“无法生成”文案和错误码来源

仓库当前没有精确字面量“无法生成课程”。可见失败由以下组合构成：

| 场景 | UI 标题/正文 | 稳定 code 来源 |
| --- | --- | --- |
| 背景 authoring failed | 标题固定“课程准备未完成”；正文优先 `authoring_run.failure_message`；下方 `<code>` 显示 `failure_code`；按钮“重试准备” | `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:385-433` |
| 无 persisted source | `当前没有足够的受信课程来源。` | `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`，`aearn/services/api/app/services/learning/lesson_authoring.py:170-179` |
| provider/config/call 不可用 | `课程生成服务当前不可用。` | `LESSON_DOCUMENT_GENERATION_UNAVAILABLE`，`aearn/services/api/app/services/learning/lesson_authoring.py:106-129`, `aearn/services/api/app/services/learning/lesson_authoring.py:235-244` |
| provider JSON/contract 错误 | `课程生成结果未通过结构校验。` | `LESSON_DOCUMENT_INVALID`，`aearn/services/api/app/services/learning/lesson_authoring.py:124-129`, `aearn/services/api/app/services/learning/lesson_authoring.py:241-244` |
| 质量门失败 | `课程内容未通过发布质量门。` | `LESSON_DOCUMENT_QUALITY_BLOCKED`，`aearn/services/api/app/services/learning/lesson_authoring.py:235-236` |
| scope/source 在生成中变化 | `课程生成期间学习路线或来源已更新。` | `LESSON_DOCUMENT_VERSION_CONFLICT`，`aearn/services/api/app/services/learning/lesson_authoring.py:237-238` |
| failed payload 没有 message | fallback `课程生成失败，没有发布半成品或无来源模板。` | 无 code 时只显示 fallback，`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:389` |
| GET payload 被 strict parser 拒绝 | alert 显示 `LessonDocument API returned an invalid payload` + “重新读取” | 前端 `CLIENT_ERROR`，`aearn/apps/desktop/src/api/learning.ts:163-166`, `aearn/apps/desktop/src/lib/errorMessages.ts:46-50` |
| prepare 同步 4xx/5xx | alert 显示 error mapping 或 server message | `requestJson` 解析 `ApiRequestError`：`aearn/apps/desktop/src/api/client.ts:19-30`；Lesson codes 未列入本地 map，因此回退 server `error.message`：`aearn/apps/desktop/src/lib/errorMessages.ts:9-43` |

失败写库由 `_safe_fail` 完成，随后 GET 才把 code/message 投影给 Desktop：`aearn/services/api/app/services/learning/lesson_authoring.py:374-394`, `aearn/services/api/app/services/learning/lesson_repository.py:265-277`, `aearn/services/api/app/services/learning/lesson_repository.py:598-613`。

### 6. Python 与“无教材 LangChain”的预期差异和当前实际差异

#### 语言确认差异

- 显式 Python 是 deterministic explicit signal，可 auto-confirm；LangChain 是 model-semantic ecosystem hint，只产生一个未选中的 Python 候选，必须由学习者确认，不能直接写 language fact：`aearn/services/api/app/services/learning/planning_intent.py:71-95`, `aearn/services/api/app/services/learning/planning_intent.py:160-210`, `aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py:527-568`, `docs/qa/acceptance-test-plan.md:416-425`。

#### 来源/教材差异（当前实现的关键缺口）

- Python registry 有 `python-tutorial` 与 `python-library-reference`，但没有 LangChain source：`aearn/services/api/app/services/grounding/grounding_sources.py:33-61`；对 grounding 目录搜索 `langchain` 无匹配。
- plan draft 的“权威来源”由 registry 静态枚举，不检查 `grounding_chunks` 是否已持久化：`aearn/services/api/app/services/learning/plan_capability.py:215-231`；Desktop 直接展示 source summary：`aearn/apps/desktop/src/features/learning/LearningPlanBuilderPage.tsx:188-228`。
- plan draft 确认时创建 track 只传 `language_id/goal/target_level/plan/conversation`，没有 source summary、教材 ID 或 material binding：`aearn/services/api/app/services/learning/plan_service.py:281-305`；`LearningPlanNode` 也只有 key/title/description/prerequisite/capability：`aearn/services/api/app/services/learning/contracts.py:102-127`。
- Lesson authoring 不读取 draft source summary 或 user material，只按 `language_id + title + knowledge_key` 查询全局 persisted chunks：`aearn/services/api/app/services/learning/lesson_authoring.py:165-180`, `aearn/services/api/app/services/learning/lesson_authoring.py:275-319`。
- retrieval 在没有语义正匹配时会 fallback 到该语言的任意高信任 chunk：`aearn/services/api/app/services/grounding/grounding_retrieval.py:37-57`, `aearn/services/api/app/services/grounding/grounding_retrieval.py:94-103`。

**因此当前实际行为是：**

- “有教材 Python”并不会自动使用该教材；除非教材已经以本系统支持的 registered/persisted grounding 形式进入 `grounding_chunks`，否则它与无教材 Python 没有 Lesson authoring 区别。
- “无教材 LangChain”确认 Python 后也只会使用 Python 官方 registry/index。若索引存在，可能用 Python 基础文档 fallback 生成与 LangChain 目标弱相关的 Lesson；若索引为空，则与 Python 一样失败为 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`。
- 产品上合理的预期差异应是：有教材 Python 绑定 exact user-provided/approved source snapshot；无教材 LangChain 只有在注册并索引可信 LangChain 文档或明确接受 Python-only基础路线时才可生成。当前 schema/DTO/authoring path 尚不能表达这一差异。

### 7. 最可能问题排序

#### P0 候选：bootstrap/start-dev 未准备 grounding index

证据链：

- `grounding_chunks` schema 只建表，没有 seed insert：`aearn/services/api/app/db/schema/020_grounding.sql:20-44`。
- `bootstrap_database()` seed runtime/language/intent/Learning Item，但不执行 grounding reindex：`aearn/services/api/app/db/bootstrap.py:26-42`。
- `pnpm dev` 启动脚本只调用 bootstrap 后启动 API/worker/Desktop：`aearn/scripts/start-dev.ps1:276-305`。
- Lesson worker 只读 persisted index，无结果直接失败：`aearn/services/api/app/services/learning/lesson_authoring.py:170-179`, `aearn/services/api/app/services/learning/lesson_authoring.py:275-319`。
- grounding repository 自身明确测试“空 index -> `no_persisted_grounding`”：`aearn/services/api/tests/grounding/test_grounding_index_repository.py:106-115`。
- Lesson tests 全部在 prepare 前显式运行 fixture reindex：`aearn/services/api/tests/learning/test_lesson_document_authoring.py:65-83`, `aearn/services/api/tests/learning/test_lesson_documents.py:48-59`。

**推断：** 对普通 fresh/bootstrap-only 本地环境，点击“准备课程”最可能稳定进入 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`。需用只读 DB 查询确认当前实例，不应仅凭静态分析宣称已经复现。

#### P1：计划来源展示与实际 indexed readiness 脱节

- source summary 是 registry metadata，不是可检索 snapshot readiness；确认后还被丢弃。用户看到“权威来源”容易理解为教材已绑定/可生成，但 authoring 可能没有任何 chunk。

#### P1：材料来源没有贯穿 plan -> track -> Lesson

- 有教材 Python 与无教材 LangChain 最终共享同一 `language_id=python` 查询，无法满足任务目标中的教材关联验证。

#### P2：前端可观测性不足

- failed 背景态有 code，但同步 prepare/read 错误只显示 message；`getErrorInfo` 没有 Lesson code 的稳定用户文案映射：`aearn/apps/desktop/src/lib/errorMessages.ts:9-43`。
- strict parser 只报统一 invalid payload，不能指出 top-level、assignment、source、block 或 citation 哪一层失败：`aearn/apps/desktop/src/api/learning.ts:155-166`, `aearn/apps/desktop/src/api/learning.ts:708-754`。

#### P2：polling/recovery 不完整

- preparing poll 无上限/超时，且 Lesson authoring 只由 request 的 FastAPI BackgroundTask 唤醒；未找到类似 Tutor dispatch reconcile 的 pending authoring recovery job：`aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx:116-120`, `aearn/services/api/app/routes/lesson_documents.py:148-153`。API reload/进程退出发生在 202 后时，run 可能长期保持 pending/preparing。

#### P2：两个边缘 DTO shape 风险

- service 在 prepare 发现已有 assignment 时返回完整 ready state 并加 `idempotent_replayed`：`aearn/services/api/app/services/learning/lesson_service.py:68-74`；Desktop `toLessonPrepareResponse` 却只接受五个固定字段：`aearn/apps/desktop/src/api/learning.ts:844-859`。并发 tab/重复动作命中该分支时会把成功响应报成 invalid payload。
- latest run 为 `cancelled` 时 service 投影 `status=missing` 但仍带 `authoring_run`：`aearn/services/api/app/services/learning/lesson_service.py:248-252`, `aearn/services/api/app/services/learning/lesson_service.py:285-292`；Desktop 的 missing parser禁止 `authoring_run`：`aearn/apps/desktop/src/api/learning.ts:746-753`。当前没有公开 cancel route，但恢复/运维状态可能触发。

#### P3：纯布局/可见性误判

- 宽屏 secondary collapse 或移动端默认 Tutor tab 会隐藏 Lesson DOM。若 network GET 已返回 ready 且没有 parser error，应先检查 viewport、`secondary-collapsed` class、当前 tab/teaching mode，再归因 renderer。

### 8. 现有测试覆盖与缺口

已有：

- 后端 happy path 覆盖 missing -> prepare -> ready -> start -> refresh/proposal -> migrate：`aearn/services/api/tests/learning/test_lesson_documents.py:90-120`, `aearn/services/api/tests/learning/test_lesson_documents.py:266-314`。
- authoring 覆盖 standard/personalized publication 与 invalid fail-closed：`aearn/services/api/tests/learning/test_lesson_document_authoring.py:90-123`。
- Desktop `LessonDocumentView` 覆盖 ready 文档的 follow/hash/citation：`aearn/apps/desktop/src/features/learning/tests/LessonDocumentView.test.tsx:26-117`。
- workspace test 覆盖 role swap、collapse 与 drawer focus，但把 `LessonDocumentPage` 整体 mock 掉：`aearn/apps/desktop/src/features/learning/tests/TrackLearningWorkspace.test.tsx:15-36`, `aearn/apps/desktop/src/features/learning/tests/TrackLearningWorkspace.test.tsx:70-152`。

缺口：

1. **没有 `LessonDocumentPage.test.tsx`。** 无组件级 GET/POST/poll/missing/preparing/failed/retry/ready 测试。
2. **没有 `toLessonDocumentState` / `toLessonPrepareResponse` parser 测试。** 当前 Desktop tests 对这些函数无调用；无法保护 exact DTO 边界与上述 edge shape。
3. **后端 Lesson API 测试总是预先 fixture reindex + fake author。** 没有 `bootstrap_database()` 后不 reindex 的真实本地启动回归，也没有断言 API 最终公开 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT`。
4. **`test_invalid_or_unavailable_author_fails_closed_without_partial_document` 名称包含 unavailable，但正文只执行 `invalid=True`，没有 `unavailable=True` 分支：** `aearn/services/api/tests/learning/test_lesson_document_authoring.py:113-123`。
5. **API happy-path TestClient 背景任务很快完成。** 没有长期 preparing、lost BackgroundTask、lease expiry/reclaim、bounded Desktop poll 或 manual retry recovery。
6. **没有 LangChain plan -> confirmed Python track -> Lesson evidence 的集成测试。** 现有 LangChain 测试止于语言候选/确认，不验证来源适配或 Lesson 相关性：`aearn/services/api/tests/codex_sidecar/test_codex_learning_plan_tools_postgres.py:527-568`。
7. **核心语言 integration matrix 不经过真实 authoring请求。** 它手工插入 chunk 并直接调用 repository 发布 Lesson：`aearn/services/api/tests/integration/test_learning_agent_integration_matrix.py:159-235`, `aearn/services/api/tests/integration/test_learning_agent_integration_matrix.py:326-390`。
8. **没有可重复的当前 browser fixture 自动化覆盖 active Lesson 的 failed/retry。** 规格明确要求 failed/retry、三视口、console/overflow：`.trellis/spec/frontend/quality-guidelines.md:830-866`。
9. **没有教材绑定 round-trip。** 当前 DTO/schema 本身没有 source/material identity，因而也没有测试“Python教材进入 frozen source snapshots”与“无教材 LangChain 不冒充有来源”。

### 9. 建议验证命令

以下命令只做读取或运行现有测试；PostgreSQL 测试必须串行。未在本次 research 中执行。

#### A. 当前实例只读检查 grounding 与最近 Lesson run

```powershell
uv --directory .\aearn\services\api run python -c "from app.db.connection import connect; c=connect(); print('grounding chunks by language:'); [print(r) for r in c.execute('SELECT language_id, count(*)::int AS chunk_count FROM grounding_chunks GROUP BY language_id ORDER BY language_id').fetchall()]; print('recent lesson authoring runs:'); [print(r) for r in c.execute('SELECT id, track_id, knowledge_key, state, attempt_count, failure_code, failure_message, created_at, updated_at FROM tutor_lesson_authoring_runs ORDER BY created_at DESC, id DESC LIMIT 20').fetchall()]; c.rollback(); c.close()"
```

判定重点：Python `chunk_count=0` 且最近 run 为 `failed / LESSON_SOURCE_EVIDENCE_INSUFFICIENT`，即可直接支持 P0 推断。

#### B. 对同一 user/track/key 逐层读取 DTO

```powershell
$Base = "http://127.0.0.1:8001"
$UserId = "<uuid>"
$TrackId = "<uuid>"
$KnowledgeKey = "<exact-roadmap-key>"

Invoke-RestMethod "$Base/api/learning-tracks?user_id=$UserId" | ConvertTo-Json -Depth 20
Invoke-RestMethod "$Base/api/learning-tracks/$TrackId?user_id=$UserId" | ConvertTo-Json -Depth 20
Invoke-RestMethod "$Base/api/learning-tracks/$TrackId/roadmap?user_id=$UserId" | ConvertTo-Json -Depth 30
Invoke-RestMethod "$Base/api/learning-tracks/$TrackId/lessons/$KnowledgeKey?user_id=$UserId" | ConvertTo-Json -Depth 40
```

先确认 track snapshot 的 `language_id/current_knowledge_key` 与 roadmap exact key，再看 Lesson `status/authoring_run.failure_*`，避免把路由 key 错误与生成错误混在一起。

#### C. 现有后端 focused suite

```powershell
uv --directory .\aearn\services\api run python -m pytest -q `
  tests/grounding/test_grounding_index_repository.py `
  tests/learning/test_lesson_document_authoring.py `
  tests/learning/test_lesson_documents.py
```

#### D. 现有 Desktop focused suite

```powershell
pnpm --dir .\aearn\apps\desktop test -- `
  src/features/learning/tests/TrackLearningWorkspace.test.tsx `
  src/features/learning/tests/LessonDocumentView.test.tsx
```

#### E. 浏览器/Network 验证

```powershell
pnpm --dir .\aearn dev
```

然后在 `http://127.0.0.1:1420`：

1. 打开 Python track，记录实际 viewport 与 Guided/Free Reading、secondary collapse、移动 tab。
2. Network 依次核对 Lesson GET、prepare POST、后续 GET；保存响应 JSON，不只看 UI。
3. 断言 failed 时页面同时出现“课程准备未完成”、server `failure_message`、`failure_code` 和“重试准备”。
4. 断言 ready 时 `.lesson-document` 与每个 `.lesson-block` 存在；检查 console 与水平 overflow。
5. 使用 1440×900、900×900、390×844，区分“请求失败”与“面板因响应式 tab 隐藏”。

#### F. 仅 disposable test DB 的差分验证（会写 grounding fixture，禁止共享/生产库）

先证明 bootstrap-only 的 Python chunk count，再在明确可丢弃数据库中运行 fixture reindex，重试同一 Lesson。若 failure 从 `LESSON_SOURCE_EVIDENCE_INSUFFICIENT` 变成 ready/provider-related 状态，则根因被隔离到 grounding readiness。fixture helper 会替换注册 source 的 chunks，不应对当前用户共享开发库擅自执行。

### Files Found

- `aearn/apps/desktop/src/App.tsx` — verified Tutor 内部 surface 路由与 workspace 装配。
- `aearn/apps/desktop/src/features/learning/LearningHomePage.tsx` — 从 track summary 的 current key 进入学习区。
- `aearn/apps/desktop/src/features/learning/TrackLearningWorkspace.tsx` — track/roadmap snapshot、active key、Guided/Free 双面板和 Lesson mount。
- `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx` — Lesson 状态机、prepare/retry/poll 与 ready render boundary。
- `aearn/apps/desktop/src/api/learning.ts` — LearningTrack/Lesson HTTP wrapper 与 exact runtime parsers。
- `aearn/apps/desktop/src/contracts/learning.ts` — track/roadmap DTO。
- `aearn/apps/desktop/src/contracts/lesson.ts` — Lesson state/document/run DTO。
- `aearn/apps/desktop/src/api/client.ts` — 固定 API base、error envelope decoding。
- `aearn/apps/desktop/src/lib/errorMessages.ts` — stable error message mapping/fallback。
- `aearn/apps/desktop/src/styles/60-learning-workspace.css` — active Lesson primary/secondary/mobile visibility。
- `aearn/services/api/app/routes/lesson_documents.py` — verified Lesson endpoints 与 BackgroundTask dispatch。
- `aearn/services/api/app/services/learning/lesson_service.py` — scope/version、run creation 与 public state projection。
- `aearn/services/api/app/services/learning/lesson_repository.py` — Lesson scope/state、run、immutable publish/assignment persistence。
- `aearn/services/api/app/services/learning/lesson_authoring.py` — persisted evidence retrieval、primary-only generation、failure mapping。
- `aearn/services/api/app/services/grounding/grounding_sources.py` — Python 等静态可信 source registry；无 LangChain source。
- `aearn/services/api/app/services/grounding/grounding_index_repository.py` — persisted chunk search/reindex storage。
- `aearn/services/api/app/services/grounding/grounding_retrieval.py` — language-scoped scoring 与 generic fallback。
- `aearn/services/api/app/db/bootstrap.py` — 当前 bootstrap seed 清单；不含 grounding reindex。
- `aearn/scripts/start-dev.ps1` — 本地启动只执行 bootstrap，不准备 grounding index。
- `aearn/services/api/app/services/learning/plan_capability.py` — plan source summary 来自 registry。
- `aearn/services/api/app/services/learning/plan_service.py` — 确认 plan 时 source summary 未传入 track。
- `aearn/services/api/tests/learning/test_lesson_document_authoring.py` — fake author/fixture index authoring tests。
- `aearn/services/api/tests/learning/test_lesson_documents.py` — Lesson API happy path。
- `aearn/apps/desktop/src/features/learning/tests/TrackLearningWorkspace.test.tsx` — layout test，但 mock 掉 Lesson page。
- `aearn/apps/desktop/src/features/learning/tests/LessonDocumentView.test.tsx` — ready renderer/follow/citation tests。

### External References / Versions

- 未使用外部网页资料；本问题的权威来源是仓库代码、`docs/` 与 `.trellis/spec/`。
- Desktop 当前版本边界：React `^19.0.0`、Vite `^6.0.0`、Vitest `^4.1.10`，见 `aearn/apps/desktop/package.json:13-35`。
- API contract：`docs/architecture/api-contract.md:503-519`。
- Product flow：`docs/product/user-flows.md:207-218`, `docs/product/user-flows.md:262-278`。
- Runtime boundary：`docs/architecture/tutor-harness-runtime.md:776-780`。

### Related Specs

- `.trellis/spec/frontend/component-guidelines.md:122-172` — LessonDocument owner、状态矩阵、bounded poll、failed/retry、不得猜首节点。
- `.trellis/spec/frontend/type-safety.md:152-217` — Lesson unknown boundary 与 exact parsing。
- `.trellis/spec/frontend/state-management.md:159-196` — Guided/Free Reading authority 与稳定挂载。
- `.trellis/spec/frontend/component-guidelines.md:448-481` — Guided/Free 双面板与单一 Tutor/Lesson mount。
- `.trellis/spec/frontend/quality-guidelines.md:830-866` — missing/preparing/ready/failed/retry 与三视口 browser gate。
- `.trellis/spec/backend/error-handling.md:9-30`, `.trellis/spec/backend/error-handling.md:34-62` — stable error envelope 与 recoverability。
- `.trellis/spec/guides/cross-layer-thinking-guide.md:18-84` — source -> transform -> store -> retrieve -> display 的跨层验证方法。

## Caveats / Not Found

- 本次没有读取当前 PostgreSQL 数据、API response、浏览器 Network/console 或日志，因此 P0 是由启动链路与测试 fixture 差异推导出的**最强静态根因候选**，不是已完成的现场复现。
- 没有调用真实 provider、没有运行测试、没有启动服务，也没有修改业务代码或数据库。
- 未找到当前 production/dev grounding reindex CLI、startup reconcile 或 Lesson pending-run worker；只找到 test/fixture helper。
- 未找到 LangChain grounding source、user-material -> LearningTrack/Lesson source binding，或对应 end-to-end test。
- 未找到 `LessonDocumentPage` 组件测试或 `toLessonDocumentState` parser 测试。
- 正常 ready DTO 的 backend projection 与 frontend parser 当前静态对齐；如果现场 GET 已是 ready 但 UI 报 invalid payload，需要保存原始 JSON 后逐字段对比，不能先假定 renderer 有错。
