# 实施计划

## 1. 开始前

1. 运行 `task.py start 08-22-harness-teaching-session-authority`。
2. 运行 `task.py current --source`，必须精确指向本 child。
3. 加载 `trellis-before-dev`，读取父任务与本 child 的 `prd.md`、`design.md`、`implement.md` 及父任务 research。
4. 检查 `git status`，保护既有用户修改与 Obsidian 文件。

## 2. Schema 与 contracts

1. 新增 session/checkpoint/run-scope/stimulus schema、constraints、indexes 与 typed DTO。
2. 为 JSON bounded fields 增加长度/数量/enum validator。
3. 增加 bootstrap twice、append-only、partial unique、owner scope 与 bad insert tests。

## 3. Repository / service / API

1. 实现 `TeachingSessionRepository` 与 CAS checkpoint append。
2. 实现 open/resume/current/list 和 mode/status mutation。
3. 实现 `TutorTurnStimulus` exact one-of 与 idempotent admission。
4. 在 run creation/commit 加入 immutable teaching scope 与 stale fence。
5. 增加 additive routes、public parser 和 stable error envelope。

## 4. 数据治理

1. 更新 cutover inventory 与 exhaustive schema test。
2. 更新 local export/reset/delete，使用 child-to-root 顺序。
3. 添加 cross-user/cross-track/privacy tests。

## 5. 验证

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/test_db_bootstrap.py `
  tests/test_harness_cutover.py `
  tests/test_tutor_run_repository.py `
  tests/test_tutor_routes.py `
  tests/test_tutor_teaching_sessions.py `
  tests/test_tutor_teaching_session_postgres.py `
  tests/test_tutor_teaching_turn_stimulus.py -q
uv --directory .\aearn\services\api run python -m ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .trellis\tasks\08-22-harness-teaching-session-authority
git diff --check
```

对 disposable local PostgreSQL 同一空 schema 连续执行两次 bootstrap。默认不调用真实 provider。

## 6. 完成

1. 加载 `trellis-check` 并修复问题后复验。
2. 按 Phase 3.3 更新相关 backend/database/Harness spec 与 source-of-truth 文档。
3. 按 Phase 3.4 创建只包含本 child 的工作提交。
4. 归档本 child并记录 journal。
5. 停止，不自动启动 Child 2；把 `08-22-harness-closed-teaching-action-loop` 交给用户作为下一步。
