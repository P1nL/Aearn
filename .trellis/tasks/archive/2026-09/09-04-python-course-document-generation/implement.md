# 实施计划：Python LessonDocument 有界修复生成

## 0. 实施前门禁

- [ ] 重新运行 `python ./.trellis/scripts/get_context.py`，确认当前任务仍为本目录、状态为 `planning`，并在用户批准本计划后才执行 `task.py start`。
- [ ] 记录 `git status --short --branch`；保护现有 Tauri generated permission/schema、`aearn/package.json`、`Python/` 和图片等并行改动，不 reset/clean/广泛 stage。
- [ ] 读取本任务 PRD/design、两份 research，以及 manifest 注入的 backend/frontend 规格。
- [ ] 记录 `pnpm --dir .\aearn dev:status`；任何数据库测试前避免与 live API/worker/beat 共用 PostgreSQL，停止/恢复只能使用受管 dev 脚本并在 finally 恢复原状态。

## 1. 后端 feedback 合同与分类

建议由一个 `trellis-implement` worker 独占后端写集：

- `aearn/services/api/app/services/learning/lesson_authoring.py`
- 必要时新增 `aearn/services/api/app/services/learning/lesson_authoring_feedback.py`
- `aearn/services/api/app/services/learning/lesson_contracts.py`（仅为安全结构错误信息提供最小支持）
- 对应 backend tests 和 schema/docs/spec

步骤：

- [ ] 定义 `lesson_author_feedback_v1`、issue/stage/document-kind 枚举、长度/数量限制和 canonical hash。
- [ ] 建立 repairable/non-repairable 分类；quality issue 使用显式 allowlist，不用字符串模糊判断扩大重试。
- [ ] 将 provider adapter 的 `LLMInvalidResponseKind`、model 和 usage 安全元数据保留到 authoring failure/attempt 层。
- [ ] 对 candidate exact-field、block index、citation handle、scope identity 和 quality report 构造有界 issue；不得回传 candidate values 或 raw body。
- [ ] 增加 contract 单元测试：合法 feedback、issue 上限、非法 code/path、敏感 marker、canonical hash 稳定性。

## 2. 重构 authoring attempt 与一次修复循环

- [ ] 把 provider call 与 attempt receipt final outcome 分离：只有 parse + identity + quality 全通过才记录 `success`。
- [ ] 为 standard/personalized 复用一个内部 `author_and_validate` helper，并共享一个 run-level repair budget；整个 authoring run 最多额外一次 provider call。
- [ ] 第二次调用在原 safe request payload 中加入 exact `previous_attempt_feedback`；不附带第一次 candidate。
- [ ] standard 成功后才进入 personalized；personalized repair 始终携带已验证 standard document。
- [ ] 任一步预算耗尽后使用现有 public failure family 终止；不发布半成品。
- [ ] 保持同 provider/model/protocol、existing LLM transport retry、lease/CAS/source/current-state 和 atomic publication boundary。
- [ ] 测试：standard 消耗共享 repair budget 后成功、personalized 使用未消耗预算后成功、standard 已耗尽预算后 personalized invalid 直接失败、second failure、non-retryable matrix、单 winner、无半成品。

## 3. 安全 receipt 与 additive schema

- [ ] 在 `080_lesson_teaching_practice.sql` 为 `tutor_lesson_authoring_attempt_receipts` 增加 `diagnostic_json jsonb NOT NULL DEFAULT '{}'` 和 object CHECK；fresh create 与 existing bootstrap 都支持。
- [ ] repository `record_authoring_attempt` 接受并 canonicalize allowlisted diagnostic projection。
- [ ] 新 receipt 记录 document kind、document attempt index、failure stage、issue codes/locations 和 feedback hash；不记录 constraint/prompt/body/reasoning/raw candidate。
- [ ] 保留旧 row `{}` 兼容、append-only trigger、usage NULL 语义和唯一 identity。
- [ ] 更新 database/bootstrap tests，运行 bootstrap twice；确认 cutover/reset/export 无需新增表或删除顺序变化。

## 4. API response shape 收口

- [ ] 修改 `LessonDocumentService.prepare` 的已有 assignment/idempotent 分支，只返回统一 prepare response；`ready` 时 `authoring_run=null`。
- [ ] 修改 `_project_state`：只有 `preparing/failed` 带 `authoring_run`；cancelled 映射 missing 时不携带额外字段。
- [ ] 增加 API/service tests：prepare ready replay、same-key replay、cancelled/missing exact projection、failure public state 不泄露 diagnostic JSON。
- [ ] 确认 `docs/architecture/api-contract.md` 的 GET/prepare 状态与实现一致。

## 5. Desktop parser 与状态机回归

建议第二个 `trellis-implement` worker 独占 frontend 写集，与后端并行：

- `aearn/apps/desktop/src/api/learning.ts`
- `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx`（仅在测试发现真实缺口时最小修改）
- 新增/更新 Lesson parser/page tests

步骤：

- [ ] 为 `toLessonDocumentState` 增加 missing/preparing/failed/ready、citation/order/extra field 和 cancelled-compatible fixtures。
- [ ] 为 `toLessonPrepareResponse` 增加 preparing/failed/ready replay fixtures，并与设计中的统一后端 shape 对齐。
- [ ] 新增 `LessonDocumentPage` 组件测试：failed code/message + 重试、preparing poll、ready render；fake fetch，不调用真实 provider。
- [ ] 不放宽 unknown boundary，不使用 cast/`any`/Markdown fallback，不把内部 diagnostic 投影给 learner。

## 6. 文档与 Trellis 规格同步

- [ ] 更新 `.trellis/spec/backend/quality-guidelines.md` 的 Lesson Authoring Quality Gate：一次 repair、feedback safety、receipt outcome 和 non-retryable matrix。
- [ ] 更新 `.trellis/spec/backend/database-guidelines.md`：Lesson authoring receipt diagnostic JSON、legacy default 和 append-only要求。
- [ ] 如 frontend contract 有实质变化，更新 `.trellis/spec/frontend/type-safety.md` / `component-guidelines.md`；若只是实现对齐，避免重复规格。
- [ ] 更新 `docs/architecture/api-contract.md`、`database-schema.md` 与必要的 release/acceptance ledger，明确不属于 RAG 2.0 learner-visible rollout。
- [ ] 不修改 `09-03-rag-language-ecosystem-adaptive-retrieval` 的产品 scope；最多在其后续集成时引用本任务已存在的 Lesson repair boundary，不复制实现。

## 7. 最小验证

### 7.1 后端静态门

```powershell
uv --directory .\aearn\services\api run ruff check <touched-python-files> <focused-tests>
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\api lock --check
```

### 7.2 PostgreSQL focused tests

在 live stack 已按受管流程停止、且 finally 会恢复原状态后串行运行：

```powershell
uv --directory .\aearn\services\api run python -m pytest -q `
  tests/learning/test_lesson_document_authoring.py `
  tests/learning/test_lesson_documents.py `
  tests/database/test_db_bootstrap.py
```

如 schema/cutover classification 受影响，再追加最小相关 database/cutover tests；不得为方便运行 full suite 而清理当前用户数据。

### 7.3 Desktop tests

```powershell
pnpm --dir .\aearn\apps\desktop test -- `
  <lesson-parser-test> `
  <lesson-document-page-test> `
  src/features/learning/tests/LessonDocumentView.test.tsx `
  src/features/learning/tests/TrackLearningWorkspace.test.tsx
```

默认不运行 `desktop:check`，除非用户另行要求。

### 7.4 Browser gate

- [ ] 在 `http://127.0.0.1:1420` 使用 disposable/fake state 验证 failed -> retry -> preparing -> ready；不创建真实课程、不调用真实 provider。
- [ ] 检查有意义 DOM、无 framework overlay、相关 console error/warning 为零、Lesson panel 可见。
- [ ] 若没有 CSS/布局变化，使用正常视口即可；若 UI 发生变化，再补 900px/390px 与 overflow/focus。

### 7.5 Hygiene

```powershell
python ./.trellis/scripts/task.py validate 09-04-python-course-document-generation
git diff --check -- <task-owned-paths>
git diff --cached --check
```

- [ ] 只 stage 本任务拥有的文件；不得把既有 Tauri generated files、`aearn/package.json`、`Python/` 或图片带入提交。
- [ ] 恢复实施前的 dev stack 状态并再次运行 `pnpm --dir .\aearn dev:status`。

## 8. Review Gate

- [ ] 派发独立 `trellis-check`，检查 PRD/设计符合度、重试分类、feedback 注入、敏感信息、receipt outcome、schema compatibility、API/Desktop round trip、测试与未声明事项。
- [ ] 若 checker 发现 source coverage/Subject/Corpus 问题，记录到 RAG 2.0 task，不在本任务扩张实现。
- [ ] 最终报告明确区分：实现/测试是否完成、是否 commit、是否真实 provider smoke、是否 push/deploy、是否修改用户现有课程数据。

## 9. 回滚点

1. feedback/repair loop 可整体回滚到单次调用；新 diagnostic column 保留为兼容空对象。
2. API response shape 可独立回滚，但必须同步 Desktop parser tests。
3. Desktop test/小修可独立回滚，不改变服务端 authority。
4. 回滚不得删除历史 authoring run/receipt/document/assignment，也不得修改 RAG 2.0 corpus state。
