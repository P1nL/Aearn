# 实施计划

1. 建立 production import 与测试收集基线。
2. 提取 contracts 与 mapping 纯逻辑。
3. 按职责提取 repository mixin/组件，保持 facade 与 connection 所有权。
4. 运行 Tutor persistence focused tests。
5. 建立测试领域目录与 support package，分批移动测试。
6. 核对 pytest collection 数量并运行完整后端 gate。
7. 搜索旧内部 import、重复 helper 和残留单体文件。

## 验证

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest --collect-only -q
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
git diff --check
```

## 实施结果

- 将 `persistence.py` 转换为 16 个模块的 `persistence/` package；公开入口仍为 `app.services.tutor.persistence`。
- `PostgresTutorRepository` 继续持有唯一 caller-owned connection；100 个原方法的 AST 逐一比对，仅 `as_run_store` 增加循环导入规避。
- 最大职责模块约 1,160 行，原 7,018 行单体文件已删除。
- 110 个测试文件分入 8 个领域目录，6 个共享 helper 迁入 `tests/support/`，新增目录说明。
- pytest 收集前后均为 719。
- 增加测试级外部 Celery wakeup 隔离，保留 API 本地 fast path，7 个历史波动用例连续通过。

## 验证结果

- `uv lock --check`：通过。
- `ruff check app tests`：通过。
- `python -m mypy app --no-incremental`：215 个 source files 通过。
- `pytest --collect-only -q`：719 tests。
- 完整测试：最高结果为 716 passed、2 skipped、1 次 PostgreSQL Schema 重复应用 deadlock；失败用例单独复跑通过。该剩余问题与下一阶段 `schema.sql`/bootstrap 重构直接相关，不是 persistence 方法语义差异。
- `git diff --check`：通过。

## 后续验证闭环

数据库 Schema 模块化阶段加入 manifest、bootstrap advisory lock 与整事务 deadlock retry 后，完整 API 套件最终通过：`721 passed, 2 skipped`。第三阶段记录的剩余 bootstrap deadlock 已闭环。
