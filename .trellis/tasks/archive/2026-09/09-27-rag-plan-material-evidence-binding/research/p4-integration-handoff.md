# D P4 窄接线交接（2026-09-27）

## 本写集

- `app/db/schema/__init__.py` 与 `tests/database/test_schema_manifest.py` 在既有 360/C 清单后登记 P1 的 `370_rag_plan_material_bindings.sql`，保留所有 C 片段及显式完整清单；未修改 370 原文。
- `local_user_data_repository.py` 在既有 run 取消、事务局部 `aearn.learning_track_purge_user_id` 授权与 deferred FK 设置下，先删除该用户的 `rag_plan_material_bindings`，再删除 `rag_material_selections`，最后按旧顺序删除 draft/session/run scope。reset/delete 均复用同一路径；没有新的泛化 purge 或共享 corpus 删除。summary counts 仅新增两项用户私有计数，不输出 selection/binding 原文。
- `tests/grounding/test_rag_d_user_inventory.py` 为单独 `AEARN_RAG_D_TEST_DATABASE_URL` 且数据库名 `aearn_rag260_c_d_*` 的显式、预先 bootstrap 的本地 PG 集成测试；用两名临时用户、两个真实 draft 和各自 selection/binding，分别检查 reset/delete、被拒绝的通用/错用户删除、操作后失败的 savepoint rollback、其他用户不变及共享 corpus 行数不变。测试末尾外层 rollback；本代理未连接或执行 PostgreSQL，主会话须串行验证。
- `tests/learning/test_rag_plan_shadow_boundary.py` 保持原 phase-I 只读 sidecar 与旧 shadow 零 consumer 扫描；新增 D 模块/符号直接导入审计，精确允许 grounding D 模块内部、learning 的 material_selection/material_planning_composition、plan_capability 的 consumer/transaction/conflict 以及 Tutor interactive 的 consumer 类型。负样本覆盖 route、worker、C source 反向导入；不允许整个 learning/tutor 子树。P3/P4 新符号或路径须在审阅后再精准扩展，不得整体豁免。

## 离线证据和待执行

- 离线 84 passed、2 skipped（这两项恰是未设置 D PG 环境的 reset/delete 集成测试）；Ruff 目标文件通过。`git diff --check` 无错误；其他工作树的 CRLF 提示不是本写集验收失败。
- 主会话负责先确认唯一 disposable `current_database()`，执行两次 bootstrap、再设置 `PYTHON_DOTENV_DISABLED=1`、`LLM_TYPE=disabled` 和显式 `AEARN_RAG_D_TEST_DATABASE_URL` 串行运行 PG 两例；勿继承业务 `DATABASE_URL` 或调用真实 provider。运行失败时不要用手填 receipt 代替。
- 此侧只覆盖 D 用户数据回收与静态引入边界，不证明 D current authorization/fence 的双连接时序、真实模型调用、公开来源现时有效性或 E 题库发布。即使单元测试通过，C 旧到期机器回执也不复活。

## PG 复验前修正（2026-09-27）

主会话在双 bootstrap 后报告 PG 套件 14 passed / 2 failed：reset/delete 因 `fk_tutor_learning_plan_session_current_draft_scope` 的 `ON DELETE RESTRICT`，`draft_ready` session 的 `current_draft_id` 仍指向将删除的 draft。已仅在原 `_delete_learning_track_data` purge 事务中、删除两张 D 表后和 draft 前，对目标 `user_id` 且通过 `tutor_learning_track_purge_allowed(user_id)` 的 session 暂置 `cancelled`、清空 current draft/confirmed track 及确认时间、设置取消时间；随后按原顺序删除 draft/session/scope。不能只靠 `SET CONSTRAINTS ALL DEFERRED` 绕过 RESTRICT。使用非 active 的 cancelled 状态避免多条旧 session 冲突 one-active 索引；相关 session 都会在同一事务删除，外部历史不变。

保留真实 fixture 的 `draft_ready + current_draft_id`，新增删除前、回滚后及其他用户指针断言。此代理只重跑离线目标测试 11 passed / 2 skipped、Ruff/Mypy/差异检查；尚未并行执行 PG。主会话现在可按既有隔离库环境串行复跑两个 D inventory PG 用例及 P1+P4+manifest 套件。若仍失败，回传实际约束/SQL 错误，不在 fixture 上置空 current draft 掩盖。
