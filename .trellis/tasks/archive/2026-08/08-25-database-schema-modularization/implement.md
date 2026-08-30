# 实施计划

1. 搜索所有 `schema.sql`、`SCHEMA_PATH` 和 bootstrap 依赖。
2. 识别 SQL 对象依赖并设计 fragment manifest。
3. 按边界移动 SQL，建立 loader 和顺序校验。
4. 更新 bootstrap 和测试。
5. 在空数据库执行 bootstrap、重复 bootstrap，并运行数据库/完整后端测试。
6. 更新 database/setup 文档和 Trellis spec。

## 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest -q tests/database tests/test_db_bootstrap.py
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
git diff --check
```

实际测试路径应以第三阶段完成后的目录为准。

## 实施结果

- 将原 7,402 行 `schema.sql` 按连续依赖顺序拆为 12 个职责 fragment；生成阶段验证拼接内容与原文件逐字节一致。
- `app/db/schema/__init__.py` 显式声明 `SCHEMA_FRAGMENT_NAMES`，同时拒绝重复、缺失和未登记 SQL 文件。
- `apply_schema(conn)` 按 manifest 在同一 caller-owned connection 中逐片执行，不在 fragment 之间提交。
- `bootstrap_database()` 保持原 seed 顺序与最终单次 commit，增加 transaction advisory lock，并对 deadlock/serialization failure 有界重试完整事务。
- 新增 manifest、组合视图、执行顺序、无 fragment commit 与 deadlock retry 测试。
- 当前文档、backend/frontend Trellis spec 与 API README 已切换到 manifest/fragments source-of-truth。

## 验证结果

- `python -m app.db.bootstrap` 连续两次：通过。
- `tests/database/test_schema_manifest.py tests/database/test_db_bootstrap.py`：8 passed。
- `python -m pytest -q`：721 passed，2 skipped。
- `python -m pytest --collect-only -q`：723 tests。
- `ruff check app tests`：通过。
- `python -m mypy app --no-incremental`：通过。
- `uv lock --check`：通过。
- `git diff --check`：通过。
