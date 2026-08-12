# 教学 Agent 最终集成实施计划

## 实施顺序

- [x] 核对所有依赖 child 已归档，启动本 integration child。
- [x] 读取当前 PRD、backend/frontend/guides 规范和 source-of-truth 文档。
- [x] 新增四种核心语言确定性 PostgreSQL 集成矩阵。
- [x] 新增 Java/HTML/CSS 扩展与 Go/C#/Rust/C++ tier 真实性断言。
- [x] 断言空 image lock 时 public 不产生 `container_verified`，local fixture 仅 `teaching_local`。
- [x] 扩展 cutover target inventory，逐表分类 user-owned 与 shared `tutor_*` schema。
- [x] 新增 schema reconciliation test，未来未分类表 fail closed。
- [x] 更新 runtime、user flows、frontend、API、database、development、executor 与 acceptance；历史新人导读保持原状。
- [x] 将旧中间状态标为 dated historical snapshot，不恢复旧 runtime。
- [x] 运行聚焦测试与静态检查。
- [x] 运行完整 API/executor/Desktop/数据库/Trellis/diff 质量门。
- [x] 把精确命令结果写入 readiness ledger。
- [x] 完成 Trellis check、spec update、validate、提交与归档。

## 验证命令

```powershell
uv --directory ./aearn/services/api run python -m pytest -q tests/test_learning_agent_integration_matrix.py tests/test_harness_cutover.py
uv --directory ./aearn/services/api lock --check
uv --directory ./aearn/services/api run ruff check app tests
uv --directory ./aearn/services/api run python -m mypy app --no-incremental
uv --directory ./aearn/services/api run python -m pytest -q

uv --directory ./aearn/services/executor lock --check
uv --directory ./aearn/services/executor run ruff check aearn_executor tests
uv --directory ./aearn/services/executor run mypy aearn_executor --no-incremental
uv --directory ./aearn/services/executor run python -m pytest -q

pnpm --dir ./aearn desktop:check
uv --directory ./aearn/services/api run python -c "import psycopg; conn=psycopg.connect('postgresql://postgres:postgres@127.0.0.1:5432/postgres?sslmode=disable', connect_timeout=10); print(conn.execute('select 1').fetchone()[0]); conn.close()"
python ./.trellis/scripts/task.py validate ./.trellis/tasks/08-04-learning-agent-integration-migration-qa-docs
git diff --check
```

## 审查门

- 核心四语言每个参数化 case 都生成一条 Gate evidence 和一条 Review evidence。
- public Gate 在空 lock 下 `allowed_actions=[]`，development Gate/Review 明确 `teaching_local`。
- schema 中每张 `tutor_*` 表必须被 target 或 shared 分类，二者不重叠。
- 现有 context eval、Action Runtime、context reference、cutover、export/reset 与 executor lifecycle tests 全部通过。
- readiness ledger 记录实际数字、唯一 skip、未执行的真实 provider/Docker smoke 和“不等于发布批准”。

## 回滚点

- 集成测试可独立删除，不影响生产 schema。
- cutover inventory 的新增项只增加检测范围；若某 query 错误，应修正 ownership join，不能退回 root-only 隐式清单。
- 文档更新可以回退文字，但不得恢复旧页面、路由或虚假能力声明。
- 不执行数据删除、provider 调用、container 启动、push 或 deploy。
