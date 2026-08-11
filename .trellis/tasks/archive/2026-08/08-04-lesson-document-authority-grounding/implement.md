# LessonDocument 与权威来源教学内容实施计划

## 开始前置条件

- 只启动 `08-04-lesson-document-authority-grounding`，不启动产品父任务。
- 用户审阅本规划并明确批准实施后，才运行：

```powershell
python .\.trellis\scripts\task.py start .\.trellis\tasks\08-04-lesson-document-authority-grounding
```

- 启动后先使用 `trellis-before-dev` 读取 backend/frontend/database/error/quality/type-safety、cross-layer 与当前 source-of-truth。
- 重新检查 `git status --short --branch`、相关 diff 与当前 task source；不得覆盖用户修改。
- 默认使用 fixture grounding、fake author port、fixed clock 和 disposable PostgreSQL user；不调用真实 provider。
- 前端只做 `http://127.0.0.1:1420` 网页端验证，不运行 `desktop:check`、Tauri build 或 Desktop typecheck。

## 有序实施清单

### 1. 冻结 Lesson contract 与质量门

- 新增 `lesson_contracts.py`：document identity、block discriminated union、source snapshot、gate slot、assignment、authoring state、canonical payload/hash 与 impact。
- 规定 block/string/array/document 总量上限和需要 citation 的 block 类型。
- 新增 `lesson_quality.py`，覆盖 registry-only source、coverage、language、citation、code example、gate slot、sensitive field 与 personalized-preserves-standard 验证。
- 先写纯单元测试；不在 service/repository 重复 block 校验。

### 2. Grounding source version 与文档 hash

- 扩展 `GroundingSource`，为每个 registry entry提供明确 `source_version_label` 与 `source_version_kind`。
- 扩展 fetch/processing chunk contract，保留 raw document hash 与 chunk hash的不同语义。
- additive 更新 `grounding_chunks` 字段、repository round-trip、fixture/reindex/search/citation contract。
- 更新 grounding tests，证明旧 source helper、allowlist、trust policy、HTML/CSS 组合语言与 gateway 不回归。

### 3. Additive Lesson schema

在 `schema.sql` 增加：

- `tutor_lesson_documents`
- `tutor_lesson_source_snapshots`
- `tutor_lesson_block_citations`
- `tutor_lesson_gate_slots`
- `tutor_lesson_assignments`
- `tutor_lesson_authoring_runs`
- `tutor_lesson_authoring_attempt_receipts`

同时增加：

- standard/personalized shape CHECK、复合 scope FK、partial unique active assignment；
- authoring lifecycle/lease/attempt index；
- document/source/block/gate/attempt append-only trigger；
- confirmed user purge capability；
- 必要的 `updated_at` trigger 与 retrieval index。

更新 `test_db_bootstrap.py` / Lesson repository schema tests，串行验证 bootstrap twice、constraints、indexes、triggers 与 bad inserts。

### 4. Repository 与数据生命周期

- 实现 `PostgresLessonDocumentRepository`：read state、create/replay authoring run、claim/reclaim、attempt receipt、publish documents、assignment start、proposal/activate、safe projection input。
- 所有 user/track/key query 显式 scope；standard read与 personalized write 分离。
- final publish transaction 写 document、snapshots、block citation refs、gate slots、assignment 与 run terminal state。
- 更新 `local_user_data_repository.py`：summary、export、reset/delete child-to-root 顺序；standard shared rows不删除。
- 更新 `services/tutor/cutover.py` target count roots；新增 Lesson data 的 target-contamination regression。

### 5. Authoring pipeline

- 定义注入式 `LessonDocumentAuthorPort` 与 strict request/response；生产 adapter只复用当前 primary provider配置，不引入 fallback/model routing。
- 构造 server-owned evidence handles，不允许 provider指定 URL/source ID/路径/命令。
- 实现 post-commit authoring dispatcher：claim → persisted grounding → standard reuse/generate → personalized generate → quality gate → stale recheck → publish。
- provider call期间不持有 transaction；记录安全 attempt receipt，缺 usage 保持 unknown。
- provider unavailable/invalid/quality blocked/no evidence 返回稳定 failure code，不创建 document/assignment，不使用模板 fallback。
- 添加 fake author、invalid output、source change、lease recovery、concurrent winner/replay tests。

### 6. Service 与 verified-only API

- 新增 Pydantic request/response 与 runtime-safe error mapping。
- 注册 `routes/lesson_documents.py` 到 `main.py`，精确安排静态/动态 route 顺序。
- 实现 read、prepare、start、refresh 和 migration activate。
- prepare 校验 active plan node、progress 非 locked、expected track/progress version 与 idempotency；202 后安排 post-commit dispatch。
- start 原子冻结 assignment、推进 `available -> in_progress`、更新 current knowledge/last learned，不写 completion/mastery/unlock。
- API tests 覆盖 missing/preparing/ready/failed、idempotency、cross-user、locked node、stale version、unexpected error redaction。

### 7. Tutor context seam

- 仅在 assignment ready 时为 `TutorLearningContextAdapter` 增加 bounded document identity/source summary（如 implementation 检查确认本 child 需要）；不注入完整 blocks/source excerpt。
- 不新增通用 Tutor capability payload，不扩大 `MAX_TUTOR_PAYLOAD_FIELDS` / value limit。
- 现有 `general`、`plan_drafting`、`lesson_teaching` scope、fresh TurnRun、current-input、budget、usage/cache 和 summary tests保持通过。

### 8. Desktop 类型、API 与 Lesson 阅读面

- 在 `types.ts` 增加 exhaustive Lesson block union、citation、document、assignment、authoring state。
- 在 `api.ts` 增加 read/prepare/start/refresh/migrate wrappers 与 unknown runtime validators；未知 block/type/URL/status 进入 contract error。
- 扩展 `TutorSurface` 为 `lesson_document`；Learning Home 的 continue intent传入服务端 `current_knowledge_key`，不本地猜首节点。
- 实现 `LessonDocumentPage`、`LessonDocumentView`、`LessonBlockRenderer`、`LessonSourcesPanel`。
- UI 覆盖 prepare/failed/retry/ready/start/update proposal，inline citation、source panel 与Gate slot 未开放状态。
- 不实现完整三栏、右侧 Tutor、selection reference、练习按钮、运行结果或复习页。

### 9. 后端聚焦验证

按实际文件名调整，但覆盖不可减少。先运行纯测试，再串行运行 PostgreSQL/bootstrap 测试：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_lesson_document_contracts.py tests/test_lesson_document_quality.py tests/test_lesson_document_authoring.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_lesson_document_repository.py tests/test_lesson_documents.py tests/test_db_bootstrap.py tests/test_learning_track_repository.py tests/test_harness_cutover.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_grounding_sources.py tests/test_grounding_fetcher.py tests/test_grounding_processing.py tests/test_grounding_retrieval.py tests/test_grounding_citations.py tests/test_grounding_reindex.py tests/test_grounding_index_repository.py tests/test_tutor_grounding_policy.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_tracks.py tests/test_learning_plan_sessions.py tests/test_tutor_context_builder.py tests/test_tutor_run_loop.py -q
```

如果 PostgreSQL 不可用，记录精确连接/服务阻塞，不用 mock 代替 schema/FK/trigger 证据。

### 10. 网页端浏览器验证

启动当前 Vite web target：

```powershell
pnpm --dir .\aearn\apps\desktop dev
```

使用 disposable verified fixture、fixture grounding 和 fake author port，在 `http://127.0.0.1:1420` 验证：

1. Learning Home “继续学习”进入 Lesson，而不是 not-ready 占位。
2. missing → prepare → preparing → ready，及 failed → retry。
3. 每种注册 block 至少一条真实渲染；未知 payload显示 contract error。
4. inline citation 与来源面板互相定位，展示 trust/version/section/time/URL/excerpt。
5. start 后 frozen 状态与返回首页路径正确；重复 start 不产生第二 assignment。
6. proposed update 显示 impact，未激活前旧文档保持 active。
7. Gate slot 明确不可练习，不出现 run/submit/score/unlock 伪事实。
8. 1440px、900px、390px：无水平溢出、键盘可操作、focus可见、console 无相关 error/warning、无 framework overlay。

不运行 `pnpm --dir .\aearn desktop:check`；浏览器 target/fixture 不可用时报告精确阻塞，不用 build/static search 替代。

### 11. 文档与 QA evidence

代码和测试通过后同步：

- `docs/product/user-flows.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/qa/acceptance-test-plan.md`
- `docs/qa/tutor-harness-release-readiness.md`
- 必要时更新 backend database/quality 与 frontend component/type/quality spec

文档必须区分：fixture/fake contract、真实 provider 未执行、Gate/Workspace/Review 未交付和“非发布批准”。

### 12. 完整质量门

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-lesson-document-authority-grounding
git diff --check
```

API suite 串行运行。真实 provider smoke 不执行；用户若另行批准，必须单独命令、固定 fixture、无 prompt/body/secret 输出，且结果仍不是 release approval。

## 预期修改文件

### Trellis

- `.trellis/tasks/08-04-lesson-document-authority-grounding/**`

### Backend

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/main.py`
- `aearn/services/api/app/models/lesson_documents.py`
- `aearn/services/api/app/routes/lesson_documents.py`
- `aearn/services/api/app/services/learning/lesson_contracts.py`
- `aearn/services/api/app/services/learning/lesson_quality.py`
- `aearn/services/api/app/services/learning/lesson_repository.py`
- `aearn/services/api/app/services/learning/lesson_authoring.py`
- `aearn/services/api/app/services/learning/lesson_service.py`
- `aearn/services/api/app/services/learning/context_adapter.py`（仅 bounded seam 需要时）
- `aearn/services/api/app/services/grounding/grounding_sources.py`
- `aearn/services/api/app/services/grounding/grounding_fetcher.py`
- `aearn/services/api/app/services/grounding/grounding_processing.py`
- `aearn/services/api/app/services/grounding/grounding_index_repository.py`
- `aearn/services/api/app/services/grounding/grounding_reindex.py`
- `aearn/services/api/app/services/grounding/grounding_fixtures.py`
- `aearn/services/api/app/services/repositories/local_user_data_repository.py`
- `aearn/services/api/app/services/tutor/cutover.py`
- 对应 Lesson/Grounding/LearningTrack/bootstrap/cutover tests 与 fixture support

### Frontend

- `aearn/apps/desktop/src/App.tsx`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/styles.css`
- `aearn/apps/desktop/src/features/learning/LearningHomePage.tsx`
- `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/**`

### 文档

- 当前 product/architecture/QA source-of-truth 文档与必要 Trellis spec

## 高风险点与回滚

- **共享 standard scope：** nullable owner/partial unique/自引用 lineage 易出现跨 scope 漏洞；必须用 shape CHECK、复合 key、trigger 和跨用户测试。
- **provider 长事务：** 禁止在 author call 时持有 track/authoring transaction；失败时停用 dispatcher，不允许分步补写半 document。
- **source reindex race：** final source-set hash 不一致即 stale fail；不把旧 chunk静默绑定为新快照。
- **个性化越界：** quality gate必须比较标准版本，不能删除核心 coverage/citation/gate。
- **Gate overlap：** 本 child 只交付 slot，不创建 exercise/Attempt/private rubric/unlock。
- **前端 contract drift：** unknown block fail visible；不使用 HTML/Markdown fallback。
- **数据清理：** user purge只删 personalized scope，不能删除共享 standard 或其他用户 document。
- **回滚：** route/authoring可 fail closed，schema/document保留；Desktop可临时回退明确未就绪页，不恢复旧 learning documentation runtime。

## 启动前最终检查

- `prd.md`、`design.md`、`implement.md`、research 与 JSONL 均为简体中文且内容完整。
- `task.py validate` 通过不等于实施批准。
- 用户已审阅范围、数据模型、authoring flow、API、前端边界、风险和验证方案，并明确批准开始实施。
