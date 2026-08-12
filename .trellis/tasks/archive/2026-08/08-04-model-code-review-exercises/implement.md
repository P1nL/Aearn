# 模型代码审核练习实施计划

## 开始前置条件

- `08-04-learning-track-plan-mastery-domain`、`08-04-exercise-gates-execution-unlock`、`08-12-tutor-authoritative-context-facts`、`08-12-tutor-controlled-action-runtime` 已完成并归档。
- 用户已明确批准开始实现；任务已进入 `in_progress`，并完成代码、测试、文档与浏览器验收。
- 开始实现前重新检查 `git status` 与相关 diff；`.trellis/tasks/.obsidian/plugins/translate/data.json` 含本地凭据，必须继续排除，禁止 stage、输出或提交。
- 实现前加载 backend、frontend、database 与 cross-layer Trellis spec，并重新核对正式 source of truth。

## 步骤一：冻结 contract 与纯评分内核

1. 在 `services/learning/practice` 下新增 model review 窄模块，定义 exercise public payload、private rubric、structured submission、expected finding、validation receipt 与 learner-safe result。
2. 为 `ExerciseType` 增加 `model_code_review`，质量门明确 learner attempt 为 `static_only`，预发布 validation profile 保持 private。
3. 实现 canonical JSON/hash、verdict/finding shape、line range、protected marker 和 public/private boundary 校验。
4. 实现确定性一对一 finding matcher、维度评分、duplicate/false-positive penalty、omission band 与 assistance summary。
5. 添加六场景和 Python/JavaScript/TypeScript/SQL fixture；先让纯 contract/quality/scorer tests通过。

## 步骤二：数据库 authority 与生命周期

1. additive 创建 authoring run、provider attempt receipt、candidate、validation run/check、publication link、visible evidence receipt 表。
2. 定义 user/track/knowledge/plan/Gate scope、request/profile/candidate hash、lease/CAS、idempotency和 lifecycle CHECK。
3. 给 `tutor_exercise_versions` 增加 `model_code_review`；给 action authority CHECK 增加 `model_review_validation`。
4. 扩展 execution intent/job owner/source one-of与复合FK，保持 Tutor effect和learner exercise旧路径约束不变。
5. 增加 immutable/lifecycle/purge trigger、索引和 publication transaction 所需唯一约束。
6. 更新 local export/reset/delete与cutover inventory，添加bootstrap twice、跨用户、非法owner、append-only和child-to-root测试。

## 步骤三：生成与预发布 Action

1. 实现 `ModelCodeReviewAuthorPort`、primary-only provider adapter、strict JSON prompt/parser和安全 provider receipt。
2. 实现 create/replay/claim/run/fail/publish authoring repository与background dispatcher；不得 provider fallback或模板兜底。
3. 创建内部 proactive conversation/run、learning scope、lease与terminalization helper，不进入learner history。
4. 注册 `model-code-review.validate@1.0.0` descriptor、input/output model、resource profile、adapter和verifier。
5. adapter创建/重放 existing executor validation jobs并只返回opaque authority；按Action Runtime receipt执行bounded retry/recovery，不实现第二套action状态机。
6. verifier检查candidate/hash/scope、check集合、job result/lock/profile、reachability/rubric/coverage和stale fence。
7. verified receipt 后原子发布exercise/rubric/publication并绑定exact Gate；失败保持draft/rejected并返回稳定安全错误。

## 步骤四：executor trusted-input 与验证矩阵

1. 扩展shared execution contract的source/owner union，保持serialization exact one-of。
2. executor按 `model_review_validation` 读取candidate、private tests和runtime profile；所有输入通过数据库受信引用解析。
3. 为四种语言实现或复用 parser/compile/typecheck/test profile；缺reviewed lock/profile/health时fail closed。
4. 生成schema/parser/compile/typecheck/visible/hidden/reachability/rubric/coverage/redaction check receipt。
5. 测试hash mismatch、cross-user、wrong profile、unexpected blocker、timeout/cancel/retry和no-host-launch。

## 步骤五：Gate、诊断与 mastery 接入

1. 扩展Gate prepare/read为 `preparing | ready | failed` authoring投影，保持普通exercise行为不变。
2. 扩展attempt request为普通字符串submission与model review structured submission严格one-of。
3. repository canonicalize结构化JSON并以private `structured_answer` 保存；公共响应不返回全文。
4. 添加visible validation evidence endpoint和append-only assistance receipt；映射到现有independence/mastery evidence summary。
5. `ExerciseGateService` 对 `model_code_review` 调用新deterministic scorer，再复用现有result/Gate/mastery/progress finalization。
6. 模块诊断item可选择该exercise type；本任务只验证兼容，不实现ReviewSession/FSRS调度。
7. 添加prepare/replay/attempt/result/evidence/diagnostic、stale、idempotency、double poll和unlock exactly-once测试。

## 步骤六：Desktop 结构化审核界面

1. 在 `types.ts` 增加exercise type、authoring status、submission/finding/verdict、score breakdown和safe result union。
2. 在 `api.ts` 增加exact-key runtime validator、prepare异步状态、structured submit和evidence API。
3. 新增 `ModelCodeReviewPanel`、finding editor和result组件；`LessonGatePanel` 只做exercise type分发。
4. 展示需求、只读带行号代码、verdict radio、可增删finding、字段错误、assisted badge和per-finding feedback。
5. 保留普通textarea路径；未知type/status/field fail closed，不做本地score/pass/unlock。
6. 完成typecheck和真实浏览器验证：preparing/retry、六场景关键交互、390/900/1440、键盘/focus、console和DOM protected marker。

## 步骤七：Tutor safe feedback、文档与规范

1. 将model review Attempt的bounded safe receipt加入权威context seam；不注入submission全文或private rubric。
2. 如实现模型补充反馈，只传用户finding与learner-safe score evidence，保留deterministic result authority。
3. 更新 `docs/README.md`、API contract、database schema、Tutor Harness runtime、product interaction、QA readiness与acceptance plan。
4. 将新的可执行数据库/Action/executor/structured-form约束写入对应 `.trellis/spec/`；不把旧review docs改写为当前authority。
5. 对legacy `review_ai_patch` source-of-truth声明做current/archive边界修正，避免后续任务误用旧实现。

## 聚焦验证

实施中按层运行，实际文件名可随实现调整但覆盖不可减少：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_model_code_review_contracts.py tests/test_model_code_review_scoring.py tests/test_model_code_review_quality.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_model_code_review_repository.py tests/test_model_code_review_authoring.py tests/test_model_code_review_action.py tests/test_model_code_review_gates.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_action_runtime.py tests/test_tutor_action_persistence.py tests/test_tutor_execution_repository.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\executor run python -m pytest -q
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-model-code-review-exercises
git diff --check
```

PostgreSQL/bootstrap-heavy tests串行运行，避免共享schema污染。真实provider和生产executor不进入默认suite。

## 完整质量门

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\executor lock --check
uv --directory .\aearn\services\executor run python -m pytest -q
uv --directory .\aearn\services\executor run ruff check aearn_executor tests
uv --directory .\aearn\services\executor run python -m mypy aearn_executor --no-incremental
pnpm --dir .\aearn desktop:check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-model-code-review-exercises
git diff --check
```

浏览器完成门使用本地web target、disposable verified user和stateful fake provider/executor；不得访问生产数据。

## 预计修改文件

### Trellis 任务工件

- `.trellis/tasks/08-04-model-code-review-exercises/**`

### 后端练习与authoring

- `aearn/services/api/app/services/learning/practice/contracts.py`
- `aearn/services/api/app/services/learning/practice/quality.py`
- `aearn/services/api/app/services/learning/practice/policies.py`
- `aearn/services/api/app/services/learning/practice/repository.py`
- `aearn/services/api/app/services/learning/practice/service.py`
- `aearn/services/api/app/services/learning/practice/diagnostics.py`
- `aearn/services/api/app/services/learning/practice/model_review_contracts.py`
- `aearn/services/api/app/services/learning/practice/model_review_scoring.py`
- `aearn/services/api/app/services/learning/practice/model_review_quality.py`
- `aearn/services/api/app/services/learning/practice/model_review_repository.py`
- `aearn/services/api/app/services/learning/practice/model_review_authoring.py`
- `aearn/services/api/app/services/learning/practice/model_review_actions.py`
- `aearn/services/api/app/services/learning/practice/model_review_fixtures.py`

### Harness、执行与生命周期

- `aearn/services/api/app/agents/harness/actions.py`
- `aearn/services/api/app/services/tutor/action_adapters.py`
- `aearn/services/api/app/services/tutor/action_persistence.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/services/tutor/cutover.py`
- `aearn/services/api/app/services/tutor/context_builder.py` 或当前authoritative context接缝
- `aearn/services/api/app/services/tutor/execution.py`
- `aearn/services/api/app/services/repositories/local_user_data_repository.py`
- `aearn/packages/shared/aearn_shared/execution/contracts.py`
- `aearn/services/executor/aearn_executor/trusted_input.py`
- executor store/service文件（仅owner/source接缝需要时）

### 数据库、API 与前端

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/models/exercise_gates.py`
- `aearn/services/api/app/routes/exercise_gates.py`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/styles.css`
- `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/LessonGatePanel.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/ModelCodeReviewPanel.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/ModelCodeReviewFindingEditor.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/ModelCodeReviewResult.tsx`

### 测试、文档与规范

- 新增model review contract/scoring/quality/repository/authoring/action/Gate/API/DB/executor/frontend测试。
- 更新当前product/architecture/QA source-of-truth与必要的`.trellis/spec/backend/*`、`.trellis/spec/frontend/*`。

## 高风险点与回滚

- **旧review回流：** 禁止从旧route/table/repository复制authority；发现耦合立即停在adapter边界。
- **Action双状态机：** authoring dispatcher不得自行定义action成功/重试/验证语义，只消费Action Runtime receipt。
- **执行队列弱化：** 新owner/source必须与旧两条路径共同有严格one-of、复合FK和回归测试。
- **public/private泄漏：** 任何expected finding/test/rubric/provider payload出现在公共投影即阻塞提交。
- **正确题误报训练：** fully-correct/suspicious-correct coverage不足时不得发布。
- **模型评分漂移：** matcher/score必须纯函数、版本化、可重放；模型反馈与score写入分离。
- **stale发布：** candidate、Action、executor、plan/Gate任一hash/version变化都拒绝发布。
- **回滚：** 关闭dynamic authoring/descriptor接入并fail closed；保留append-only candidate/receipt；普通Gate和旧Tutor execution路径继续可用，不删除additive schema或已发布不可变版本。

## 完成检查

- `prd.md`、`design.md`、`implement.md`、`research/*.md` 已全部使用简体中文且无英文模板占位。
- 任务范围、数据流、authority、Action/executor扩展、structured submission、评分、UI、风险和验证命令已冻结。
- `task.py validate` 通过只表示规划结构有效，不代表实施或发布批准。
- 用户已明确批准开始实现；当前实现、质量门、任务工件和归档前检查均已完成。


## 实施结果（2026-08-12）

- 已交付 `model_code_review` 公私 contract、六场景/四语言 fixture、确定性 scorer、authoring/validation/publication authority、Action Runtime descriptor、共享 executor trusted-input、Lesson Gate/API、Desktop 结构化审核界面与 learner-safe evidence。
- local export 只保留受限摘要；private candidate、expected finding、隐藏测试、matcher/proof 与 finding 自由文本不进入 export。confirmed reset 删除 user-owned model-review 生命周期和独占 internal run/conversation，同时保留去个性化的不可变 published exercise/rubric。
- PostgreSQL 环形 authoring FK 使用 `ON DELETE NO ACTION DEFERRABLE INITIALLY IMMEDIATE`，并由 bootstrap 与完整 lifecycle 回归锁定。
- API 完整测试 `491 passed, 1 skipped`；Executor `11 passed`；API/Executor lock、Ruff、Mypy 与 Desktop `tsc && vite build` 通过。
- 真实浏览器使用临时前端 harness 覆盖 finding 增加与字段阻断、evidence assisted 状态、结果映射、390/900/1440 无页面水平溢出、键盘焦点可见，console warning/error 为零；临时 harness 已删除且未进入提交。
- 未调用真实 provider、未批准生产 executor image、未部署或修改生产数据。
