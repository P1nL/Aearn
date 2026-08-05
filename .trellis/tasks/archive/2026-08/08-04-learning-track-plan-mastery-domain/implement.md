# LearningTrack、计划路线与掌握度领域实施计划

## 开始前置条件

- 用户必须在父任务最终规划摘要之后另行明确批准实施。
- 启动本 child，而不是父任务。
- 编辑前加载 `trellis-before-dev`，读取后端 directory/database/error/quality 规范、父任务设计和当前 runtime/API/schema source of truth。
- 重新检查 `schema.sql`、`main.py`、Tutor models/routes/persistence/cutover/local user data 和相关测试的未提交 diff；不得覆盖用户修改。

## 有序实施清单

### 1. 冻结 Contract 与错误

- 新增 LearningTrack Pydantic request/response、plan/module/node、revision impact、scope、mastery 和 execution tier contract。
- 定义 canonical plan hash、stable key 校验、DAG 校验和 learner-safe disclosure。
- 添加纯单元测试覆盖合法/非法 plan 与 tier resolver。

### 2. Additive Schema

- 在 `schema.sql` 新增 track、plan revision/active pointer、module/node、progress、migration、mastery evidence/state、conversation scope 和 run scope 表。
- 添加复合 FK、partial unique、CHECK、updated_at trigger 和必要 index。
- 更新 cutover/user data inventory 与删除顺序，保证同 user 精确作用域。
- 添加 bootstrap/constraint/跨作用域真实 PostgreSQL 测试。

### 3. Repository 与 Mastery Projector

- 实现 transaction-bound repository：create/list/read/roadmap/propose/activate/scope snapshot/evidence append/state projection。
- 使用 track row lock、expected version 和现有 idempotency store。
- 实现计划影响 diff、progress stable-key merge 和 DAG validation。
- 添加 repository integration tests，包括 replay 和并发 conflict。

### 4. Execution Tier Resolver

- 将四层 tier 定义集中到新 learning contract。
- 通过注入 port 读取 composition、local runner、runtime catalog、reviewed lock 和 executor health；默认 public fail closed。
- 不启动 runner/executor；使用 fake 证明 public 无 lock 不返回 verified、development local 可返回 teaching_local。

### 5. Public Service 与 Routes

- 注册 `/api/learning-tracks` 路由族，复用 cutover gate、统一 error envelope 和 request id。
- 提供 create/list/detail/roadmap/revision list/propose/activate。
- 为 conversation/first-turn 输入增加 additive optional scope contract，保持未提供时 general 兼容；必要时使用单独 scope binding endpoint，避免破坏现有请求 shape。
- 添加 API tests 和 safe projection audit。

### 6. Tutor Context Adapter Seam

- 提供只读 adapter，把 run scope、track、active plan、当前 knowledge key 和 bounded mastery summary 转成未来 ContextBuilder 可消费的 source。
- 本 child 不改变 provider prompt 和 context priority；只冻结 adapter contract。
- 测试旧 run general fallback 和 scoped run 不变性。

### 7. 文档与规范

- 代码和测试通过后更新 `docs/architecture/database-schema.md` 与 `docs/architecture/api-contract.md` 的已实现部分。
- 更新 `docs/architecture/tutor-harness-runtime.md` 说明 track scope seam，但不得描述未实现 Lesson/Gate/Review。
- 如形成可复用跨 user/track 复合 FK 规则，更新后端 database guideline。

### 8. 审查与验证

- 检查重复 plan authority、旧表调用、跨 user leak、mutable revision、frontend-owned tier、模型直写 mastery 和敏感字段泄露。
- 运行聚焦 tests 后再运行完整 API gate。

## 预期文件范围

- `aearn/services/api/app/db/schema.sql`
- `aearn/services/api/app/models/learning_tracks.py`
- `aearn/services/api/app/routes/learning_tracks.py`
- `aearn/services/api/app/services/learning/**`
- `aearn/services/api/app/main.py`
- 必要的 Tutor models/interactive scope seam、cutover/local data inventory
- `aearn/services/api/tests/test_learning_track_*.py`
- 现有 Tutor/cutover/bootstrap 回归测试
- 当前架构/API/数据库文档

## 验证命令

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py tests/test_learning_tracks.py tests/test_learning_track_repository.py tests/test_learning_execution_tiers.py -q
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_conversation_history.py tests/test_tutor_input_merge.py tests/test_tutor_learner_state.py tests/test_harness_cutover.py -q
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-04-learning-track-plan-mastery-domain
git diff --check
```

测试文件名可按项目实际命名调整，但覆盖项不可减少。数据库不可用时必须报告精确阻塞，不能仅用 mock 替代所有约束测试。

## 回滚点

- 新 route 注册可独立回滚；schema/data 保留。
- tier resolver 一律 fail closed。
- scope seam 若影响旧 Tutor，可暂时只允许 general，但不得删除已写 scope 或从聊天文本推断。
- 不回滚用户已有无关修改。
