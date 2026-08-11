# 练习 Gate、模块诊断与受控执行解锁实施计划

## 开始前置条件

- 只启动 `08-04-exercise-gates-execution-unlock`，不得启动产品父任务。
- 本规划通过 `task.py validate` 后仍停在实施审批门；只有用户明确批准实施，才运行：

```powershell
python .\.trellis\scripts\task.py start .\.trellis\tasks\08-04-exercise-gates-execution-unlock
```

- 启动后先使用 `trellis-before-dev` 读取 backend/frontend/database/error/quality/type-safety、cross-layer、code-reuse 与当前 source-of-truth。
- 重新检查 `git status --short --branch`、当前 task source 和相关 diff，不覆盖或撤销用户修改。
- 默认使用 curated exercise fixtures、fake/static evaluator、disposable PostgreSQL user 和 reviewed-lock-missing fail-closed场景；不调用真实 provider，不批准真实镜像fleet。
- 前端只通过 `http://127.0.0.1:1420` 做网页端真实浏览器验证，不运行 `desktop:check`、Tauri build 或 Desktop build校验。

## 有序实施清单

### 1. 冻结练习、Gate 与诊断 contract

- 新增 `services/learning/practice/contracts.py`，定义 registered exercise types、public/private version contract、Gate binding/state、Attempt/result/hint、diagnostic version/session/item、API projection 和 canonical hash。
- 保留 `ExerciseGateBlock.gate_kind` 教学形态；新增 `requirement_kind`，禁止重解释旧 slot。
- 新增 `policies.py`：pass threshold、independence、hint/remediation、diagnostic all-core 0.80 threshold、cooldown 和 execution requirement 的版本化常量/解析。
- 新增 `quality.py`，验证 exact fields、size、hash、hidden marker、runtime profile、public/private边界和四个核心fixture。
- 先写纯单元测试；service/repository/executor不重复实现contract解析。

### 2. 扩展 mastery evidence 非降级语义

- 给 `MasteryEvidence` 和数据库 evidence additive 增加 `evidence_effect=reinforcing | observational_non_degrading`，既有行默认 reinforcing。
- 升级 `MasteryProjector`：confidence/mastery level只消费 reinforcing evidence；observational只增加观察计数/薄弱项，不降低既有confidence。
- 保持既有 Gate/review/trusted evidence投影兼容；新增 diagnostic fail/partial不降级、diagnostic pass可增强的确定性测试。
- 更新相关 API/model projection时只增加安全字段，不把内部评分解释直接暴露给模型或前端。

### 3. 增量 PostgreSQL 结构

在 `aearn/services/api/app/db/schema.sql` 增加：

- `tutor_exercise_versions`
- `tutor_exercise_private_rubrics`
- `tutor_lesson_gate_bindings`
- `tutor_lesson_gate_states`
- `tutor_exercise_attempts`
- `tutor_exercise_attempt_submissions`
- `tutor_exercise_execution_links`
- `tutor_exercise_attempt_results`
- `tutor_exercise_hint_receipts`
- `tutor_module_diagnostic_versions`
- `tutor_module_diagnostic_sessions`
- `tutor_module_diagnostic_items`

同时 additive 扩展：

- `tutor_mastery_evidence.evidence_effect`
- `tutor_execution_intents` source owner one-of字段与复合scope约束
- `tutor_execution_jobs` owner one-of字段与复合scope约束

数据库要求：

- shared version与user-owned state形状CHECK分离；
- Lesson slot/binding/assignment复合FK；Attempt的Lesson/diagnostic exact one-of；
- old Tutor/new Gate execution source与owner exact one-of；
- active Gate/diagnostic partial unique；
- append-only/immutable/lifecycle trigger；
- terminal result和execution link唯一；
- idempotency identity/index；
- reset/delete transaction-local purge capability；
- bootstrap可重复执行两次。

先扩展 `test_db_bootstrap.py` 与新的 schema/repository tests，使用真实PostgreSQL证明坏shape、跨scope、update/delete、并发和旧行兼容。

### 4. 练习 repository、质量门与 curated fixtures

- 实现 `PostgresExerciseGateRepository` 或等价窄repository：exercise/rubric读取、binding/state、Attempt reservation/insert、submission、execution link/result、hint、diagnostic和finalization所需锁。
- 所有user/track/plan/assignment/gate/session/item查询显式scope，不依赖裸UUID。
- 新增Python、JavaScript browser preview、TypeScript Node、SQL SQLite四个版本化fixture；发布时调用统一quality gate。
- fixture source明确为`curated_fixture`；runtime/profile或private rubric无效时拒绝bootstrap/发布，不产生简化题。
- legacy exercise repository只允许复用纯semantic validator或受控development runner，不恢复旧表/route authority。

### 5. Gate binding 与 Lesson assignment 接缝

- 从已发布 `tutor_lesson_gate_slots` 创建不可变binding；保存slot/binding contract hash。
- Gate read/prepare必须从active/frozen Lesson assignment解析binding，不按最新document猜版本。
- 实现Gate state lazy materialization或显式prepare，确保assignment/binding一一对应。
- 扩展Lesson migration impact：contract hash完全一致时生成carry-forward receipt；任一binding/policy/exercise变化时fresh state。
- 新增started assignment冻结、successor migration、跨document/gate拒绝和旧Attempt保留测试。

### 6. 复用 execution intent/job 生命周期

- 扩展 `services/tutor/execution.py` 的intent/job repository与typed contract，支持：
  - `tutor_message + tutor_effect`旧路径；
  - `exercise_submission + exercise_attempt`新路径。
- 保持旧Tutor accepted input/effect/run/conversation复合FK、claim/lease/launch token和terminal状态机。
- Gate service在Attempt/submission接受事务内创建existing intent/job；不创建Tutor conversation/message/effect。
- 更新 `aearn/packages/shared/aearn_shared/execution/contracts.py` 和必要catalog/redaction contract，序列化strict owner one-of。
- 更新executor `trusted_input.py`：按owner/source读取legacy message/test或新private submission/exercise/rubric/profile。
- 先运行old Tutor execution contract/repository/effect/redaction回归，再运行new Gate owner round-trip和trusted-input tests。

### 7. execution tier 与四类执行路径

- 复用 `ExecutionTierResolver`，为Gate binding/exercise profile返回server-owned tier与disclosure。
- `container_verified`：创建existing job，返回202 Attempt并轮询。
- `teaching_local`：只在development fixture/internal dependency injection调用受控runner，同步形成terminal result；route层再次断言非public composition。
- `static_only`：只允许`static_code_reasoning`等确定性答案，隐藏Run并同步评分。
- `unavailable`：拒绝执行依赖动作，返回`EXECUTION_UNAVAILABLE`，不创建job、不host fallback。
- 测试reviewed lock缺失、health stale/incompatible、executor disabled、profile mismatch和production teaching_local误授权。

### 8. Attempt finalizer、Gate 与路线解锁事务

- 实现 `ExerciseAttemptFinalizer`，可由Attempt poll、recovery sweep和同步static/local路径调用。
- terminal job/result先验证hash、exercise/rubric/policy/assignment/plan/progress版本，再插入immutable result。
- `run` finalization只返回safe result。
- `submit` finalization在一个transaction：result → mastery evidence → mastery state → Gate CAS →当前progress completion →下游availability → track current/last key/version → receipt。
- required Gate全部通过才完成知识点；recommended/diagnostic不阻塞。
- failure更新remediation state和evidence但不完成progress；remediation exercise和hint receipts影响independence。
- 对同Attempt/result/evidence/unlock做唯一性和winner-replay；stale不把旧结果投影到新版本。
- 使用并发PostgreSQL tests验证double poll、executor retry、Gate CAS、progress version冲突和unlock exactly-once。

### 9. 模块诊断 session 与计划确认

- 实现immutable diagnostic version和session item冻结；覆盖route module全部core capabilities。
- create校验active plan/module、是否允许诊断、cooldown、expected track/plan version和幂等。
- item提交复用Attempt/result/execution路径，但强制`diagnostic_submit`、independent、无hint/remediation。
- 聚合全部item：
  - partial/fail不创建plan revision，写observational evidence和weak capability summary；
  - all-core >= 0.80创建predecessor-linked proposed revision和migration impact，session进入`passed_pending_confirmation`。
- 实现窄 `confirm_diagnostic_skip` transaction：验证session/proposed/active predecessor →激活successor →模块节点`diagnostic_skipped` →重算下游availability/current key →session confirmed/receipt。
- 测试partial不跳过、failure不降级mastery、pass未确认不生效、confirm并发winner、active plan变化冲突和cooldown重放。

### 10. Verified-only API 与错误边界

- 新增 `models/exercise_gates.py` 和 `routes/exercise_gates.py`，注册到 `main.py`，注意静态/动态route顺序。
- 实现Gate read/prepare/hint/attempt/poll和module diagnostic create/read/item attempt/confirm。
- Pydantic只接受公开字段；服务端计算hash、tier、independence、score/pass/unlock。
- 所有mutation要求expected version和idempotency；同key不同request返回稳定409。
- 映射 `LESSON_GATE_*`、`EXERCISE_*`、`EXECUTION_UNAVAILABLE`、`MODULE_DIAGNOSTIC_*` 和 `MODULE_SKIP_*`。
- API tests覆盖happy、pending、terminal、remediation、stale、cross-user/track、locked、unexpected exception redaction和X-Request-Id。

### 11. 数据生命周期、cutover 与安全投影

- 更新local user data summary/export/reset/delete，按execution link/result/hint/submission/attempt/Gate/diagnostic child-to-root清理。
- 共享exercise/diagnostic versions和curated fixtures不进入单用户删除target。
- 执行中job先安全cancel/terminalize，避免删除owner后仍可claim。
- 更新Tutor cutover target count和contamination tests。
- 确认export/public projection/trace/checkpoint/log不含完整code、private rubric/tests/reference、container/image/command/path和raw exception。
- 若Tutor context需要Gate摘要，只通过既有bounded adapter加入identity/state/safe next action，不注入submission或private feedback。

### 12. Desktop类型、API与Gate界面

- 在 `types.ts` 增加Gate/binding/exercise/Attempt/result/diagnostic/impact literal union。
- 在 `api.ts` 增加所有Gate/diagnostic wrapper和`unknown` runtime validator；未知field/status/tier/exercise type显示contract error。
- `LessonDocumentPage`拥有Gate map、editor、hint、run/submit/poll/stale和diagnostic modal state。
- `LessonBlockRenderer`增加typed render seam，不包含API逻辑。
- 新增 `LessonGatePanel.tsx` 和 `ModuleDiagnosticModal.tsx`；首版使用accessible textarea/editor shell。
- execution tier行为：container显示Run/Submit、development local明确标注、static隐藏Run、unavailable隐藏依赖动作。
- 代码变化后旧result标stale；所有pass/mastery/unlock/roadmap来自API响应。
- 样式继续使用现有global CSS/token，不新增UI库或编辑器依赖。

### 13. 聚焦后端验证

实际文件名可按实现调整，但覆盖不可减少。先纯测试，再串行运行PostgreSQL和execution tests：

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_exercise_gate_contracts.py tests/test_exercise_gate_quality.py tests/test_learning_execution_tiers.py tests/test_learning_mastery.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_exercise_gate_repository.py tests/test_exercise_gates.py tests/test_module_diagnostics.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_learning_track_repository.py tests/test_learning_tracks.py tests/test_lesson_document_repository.py tests/test_lesson_documents.py tests/test_learning_plan_revisions.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_execution_contracts.py tests/test_tutor_execution_repository.py tests/test_tutor_execution_effect.py tests/test_tutor_execution_redaction.py -q
uv --directory .\aearn\services\executor run python -m pytest tests/test_executor_service.py tests/test_executor_main.py tests/test_executor_launch.py -q
```

如果PostgreSQL、Docker或reviewed lock不可用：

- PostgreSQL schema/transaction测试必须报告精确阻塞，不能用mock代替；
- Docker conformance/reviewed image smoke可保持明确未批准/不可用，但必须证明no-launch/no-host-fallback；
- 默认suite不得访问真实provider或生产数据。

### 14. 网页端浏览器验证

启动Vite web target：

```powershell
pnpm --dir .\aearn\apps\desktop dev
```

使用disposable verified user、stateful fake Gate/execution API和四种curated fixture，在 `http://127.0.0.1:1420` 验证：

1. Learning Home进入当前server-owned Lesson，locked知识点无法打开。
2. Gate未准备 → prepare → available；not-ready/error可重试。
3. `container_verified` run 202/poll/result；修改代码后旧result stale；submit pass/remediation由服务端返回。
4. `teaching_local`只在development fixture显示明确披露。
5. `static_only`无Run且不声称执行；`unavailable`无伪Run/Submit。
6. required Gate通过后roadmap推进；recommended/diagnostic Gate失败不阻塞。
7. hint/remediation路径可恢复，前端不本地改pass/mastery/unlock。
8. module diagnostic partial/fail明确“未跳过任何知识点”；pass只显示impact，confirm后才更新roadmap。
9. 1440px、900px、390px无水平溢出，textarea/modal/按钮可键盘操作、focus可见、reduced motion可用。
10. console无相关error/warning、无framework overlay；network中没有private rubric/tests/reference或内部executor信息。

不运行 `pnpm --dir .\aearn desktop:check`、Tauri build或Desktop build。浏览器target/fixture不可用时记录精确阻塞，不用静态搜索或build结果替代。

### 15. Source-of-truth 文档与规范

代码和验证通过后同步：

- `docs/product/user-flows.md`
- `docs/product/frontend-interaction-spec.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/qa/acceptance-test-plan.md`
- `docs/qa/tutor-harness-release-readiness.md`
- 必要时更新 `.trellis/spec/backend/database-guidelines.md`
- 必要时更新 `.trellis/spec/backend/quality-guidelines.md`
- 必要时更新 `.trellis/spec/frontend/component-guidelines.md`
- 必要时更新 `.trellis/spec/frontend/state-management.md`
- 必要时更新 `.trellis/spec/frontend/type-safety.md`
- 必要时更新 `.trellis/spec/frontend/quality-guidelines.md`

文档必须明确区分：curated/fake contract evidence、真实container fleet未批准、公开`container_verified`前置条件、development `teaching_local`、static/unavailable诚实降级和后续workspace/review未交付。

### 16. 完整质量门

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
uv --directory .\aearn\services\executor lock --check
uv --directory .\aearn\services\executor run python -m pytest -q
uv --directory .\aearn\services\executor run ruff check aearn_executor tests
uv --directory .\aearn\services\executor run python -m mypy aearn_executor --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-exercise-gates-execution-unlock
git diff --check
```

API/PostgreSQL tests串行运行，避免共享数据库并发污染。真实provider、reviewed image fleet和生产executor smoke只在用户另行批准后单独运行，且结果仍不是release approval。

## 预计修改文件

实施时按相邻代码确认最终命名；以下是当前预计范围，不授权超出本任务恢复旧runtime。

### Trellis 任务工件

- `.trellis/tasks/08-04-exercise-gates-execution-unlock/**`

### 后端数据库、模型与路由

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/main.py`
- `aearn/services/api/app/models/exercise_gates.py`
- `aearn/services/api/app/routes/exercise_gates.py`

### 后端学习练习模块

- `aearn/services/api/app/services/learning/practice/__init__.py`
- `aearn/services/api/app/services/learning/practice/contracts.py`
- `aearn/services/api/app/services/learning/practice/policies.py`
- `aearn/services/api/app/services/learning/practice/quality.py`
- `aearn/services/api/app/services/learning/practice/repository.py`
- `aearn/services/api/app/services/learning/practice/execution_adapter.py`
- `aearn/services/api/app/services/learning/practice/finalizer.py`
- `aearn/services/api/app/services/learning/practice/service.py`
- `aearn/services/api/app/services/learning/practice/fixtures.py`
- `aearn/services/api/app/services/learning/practice/diagnostics.py`
- `aearn/services/api/app/services/learning/contracts.py`
- `aearn/services/api/app/services/learning/mastery.py`
- `aearn/services/api/app/services/learning/execution_tiers.py`
- `aearn/services/api/app/services/learning/lesson_repository.py`
- `aearn/services/api/app/services/learning/lesson_service.py`
- `aearn/services/api/app/services/learning/track_repository.py`
- `aearn/services/api/app/services/learning/track_service.py`
- `aearn/services/api/app/services/learning/plan_repository.py`
- `aearn/services/api/app/services/learning/plan_service.py`
- `aearn/services/api/app/services/learning/context_adapter.py`（仅bounded safe seam确有需要时）

### 现有执行队列与数据生命周期

- `aearn/services/api/app/services/tutor/execution.py`
- `aearn/services/api/app/services/tutor/cutover.py`
- `aearn/services/api/app/services/repositories/local_user_data_repository.py`
- `aearn/packages/shared/aearn_shared/execution/contracts.py`
- `aearn/packages/shared/aearn_shared/execution/redaction.py`
- `aearn/services/executor/aearn_executor/trusted_input.py`
- executor store/service文件（仅owner/source one-of接缝需要时）

### 后端与执行器测试

- `aearn/services/api/tests/test_exercise_gate_contracts.py`
- `aearn/services/api/tests/test_exercise_gate_quality.py`
- `aearn/services/api/tests/test_exercise_gate_repository.py`
- `aearn/services/api/tests/test_exercise_gates.py`
- `aearn/services/api/tests/test_module_diagnostics.py`
- `aearn/services/api/tests/test_learning_mastery.py` 或现有mastery测试文件
- `aearn/services/api/tests/test_learning_execution_tiers.py`
- `aearn/services/api/tests/test_tutor_execution_contracts.py`
- `aearn/services/api/tests/test_tutor_execution_repository.py`
- `aearn/services/api/tests/test_tutor_execution_effect.py`
- `aearn/services/api/tests/test_tutor_execution_redaction.py`
- `aearn/services/api/tests/test_db_bootstrap.py`
- Lesson/LearningTrack/plan/cutover/local-user regression tests
- `aearn/services/executor/tests/test_executor_service.py`
- `aearn/services/executor/tests/test_executor_main.py`
- `aearn/services/executor/tests/test_executor_launch.py`
- 必要的新Gate trusted-input测试

### 前端

- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/styles.css`
- `aearn/apps/desktop/src/App.tsx`（仅路由/props接缝需要时）
- `aearn/apps/desktop/src/features/learning/LearningHomePage.tsx`（仅module action/roadmap入口需要时）
- `aearn/apps/desktop/src/features/learning/LessonDocumentPage.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/LessonDocumentView.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/LessonBlockRenderer.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/LessonGatePanel.tsx`
- `aearn/apps/desktop/src/features/learning/lesson/ModuleDiagnosticModal.tsx`

### 文档与规范

- `docs/README.md`（仅索引或交付状态需要时）
- 当前product/architecture/QA source-of-truth文件
- 必要的`.trellis/spec/backend/*`、`.trellis/spec/frontend/*`

## 高风险点与回滚

- **execution owner迁移：** 旧字段变nullable容易弱化Tutor scope；必须用source/owner one-of CHECK、复合FK和旧回归保护。
- **第二队列风险：** Gate只可创建existing intent/job；任何独立queue/outbox/job表方案都超出设计。
- **虚假Conversation风险：** 不得为Gate代码执行创建Tutor message/effect；完整code保存在private submission artifact。
- **私有事实泄漏：** public result、error、trace、checkpoint、export和QA evidence必须做protected-marker测试。
- **重复finalization：** executor终结job与API poll并发时，result/evidence/unlock必须以Attempt唯一性和数据库锁exactly-once。
- **stale投影：** 旧job可终结但不能推进新assignment/plan；保留旧Attempt事实并返回version conflict。
- **诊断错误降级：** observational evidence不能进入confidence平均；必须有既有高mastery失败诊断不下降测试。
- **模块跳过原子性：** proposed revision、confirm activation、diagnostic_skipped迁移和unlock必须在窄事务内；partial/fail不得创建revision。
- **tier误授权：** production不能使用teaching_local，missing lock/health不能host fallback。
- **前端伪权威：** UI只显示API allowed actions/result，不本地计算pass或跳过。
- **回滚：** routes/finalizer/diagnostic confirm可fail closed；additive schema和append-only事实保留；旧Tutor execution路径继续可用。

## 启动前最终检查

- `prd.md`、`design.md`、`implement.md`、`research/*.md` 与 JSONL reason 全部为简体中文且没有英文模板占位。
- 数据模型、execution queue additive migration、Attempt finalization、module diagnostic plan revision和frontend网页端边界已经冻结。
- `task.py validate` 通过只表示规划结构有效。
- 用户已审阅任务范围、关键设计、预计文件、数据流、风险与验证方案，并明确批准开始实施。



## 实施结果与验证证据（2026-08-11）

### 已交付范围

- 新增不可变 exercise/private rubric/Gate binding authority、assignment-scoped Gate state、append-only Attempt/submission/result/hint、模块诊断 version/session/item 与 execution link。
- 以 `source_kind=exercise_submission`、`owner_kind=exercise_attempt` additive 复用现有 `tutor_execution_intents` / `tutor_execution_jobs`；旧 Tutor message/effect 路径继续由 one-of CHECK、复合 FK、claim/lease/launch token 和回归测试保护。
- `run` 只产生 learner-safe 执行反馈；terminal `submit` 在服务端事务中投影 result、mastery evidence、Gate、progress 和 route change。`static_only` 使用确定性 evaluator 且声明 `not_run`；`unavailable` 不创建 job、不回退 host/legacy runner。
- 模块诊断只允许模块入口边界；fail/partial 写 `observational_non_degrading` evidence、薄弱项与 cooldown，不创建计划版本、不跳过节点。全部核心能力独立通过后只产生 proposed revision，显式 confirm 后才激活 `diagnostic_skipped`。
- Lesson 前端通过 typed render seam 接入 `LessonGatePanel` 与独立 `ModuleDiagnosticModal`；只按服务端 `allowed_actions` 渲染，支持 prepare/hint/run/submit、same-Attempt poll、editor stale、四 tier 披露和诊断确认。
- 已同步 product、API、database、Harness runtime、QA source-of-truth，以及 backend/frontend Trellis 可复用规范。

### 最终自动验证

```powershell
uv --directory .\aearn\services\api lock --check
# Pass；Resolved 51 packages

uv --directory .\aearn\services\api run ruff check app tests
# All checks passed

uv --directory .\aearn\services\api run python -m mypy app --no-incremental
# Success: no issues found in 138 source files

uv --directory .\aearn\services\api run python -m pytest -q
# 442 passed, 1 skipped in 71.60s

uv --directory .\aearn\services\executor lock --check
# Pass；Resolved 29 packages

uv --directory .\aearn\services\executor run ruff check aearn_executor tests
# All checks passed

uv --directory .\aearn\services\executor run python -m mypy aearn_executor --no-incremental
# Success: no issues found in 9 source files

uv --directory .\aearn\services\executor run python -m pytest -q
# 11 passed in 0.65s

pnpm --dir .\aearn\apps\desktop exec tsc --noEmit
# Pass
```

### 网页端验证

在 `http://127.0.0.1:1420` 使用 disposable verified user 和 stateful fake Gate/execution API 完成真实浏览器验证：

- Learning Home 进入 server-owned Lesson；Gate unbound→prepare→exact binding。
- safe hint、`container_verified` pending→同一 Attempt poll→terminal、editor 修改后 stale、submit 路线变化。
- `teaching_local` 显示 development-only；`static_only` 无 Run 且明确未执行；`unavailable` 无 Run/Submit。
- diagnostic fail 明确“未跳过任何知识点”，pass 显示 predecessor-linked impact，只有显式 confirm 后才更新路线并隐藏入口。
- 1440px、精确 900px、390px 均无水平溢出；390px modal 适配视口；键盘焦点可见；无 framework overlay；console 0 error/0 warning。
- DOM 未出现 `private_test`、`reference_answer`、`rubric_hash`、`container_name`、`docker.sock`、`image_reference`。
- in-app Browser 完成交互、DOM、响应式、console 和 focus 验证；截图命令超时后，仅截图采集使用 standalone Playwright fallback。截图保存在本机临时目录，未进入工作树。

### 明确非声明

- 未运行 Desktop/Tauri build；网页真实交互是本任务前端完成门，`tsc --noEmit` 仅为类型补充。
- 未调用真实 provider、真实生产 executor，未运行 Docker conformance，未构建、签名、发布或批准 reviewed image fleet。
- `container_verified` 公开可用仍要求 reviewed immutable image lock 与兼容 executor health/profile；当前 curated/fake 证据不是 release approval。
- 本地 work commit、child archive 与 session journal 仅用于收尾；未 push、部署或修改生产数据，父任务继续保持 `planning` 且不启动。
