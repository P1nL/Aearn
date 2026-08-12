# 实施计划

## 执行状态

- 2026-08-12 已运行 `task.py start`，当前任务状态为 `in_progress`。
- 已在修改前核对 dirty worktree，并保持既有 Tutor provider、Desktop、Trellis 升级等用户改动不被覆盖或撤销。
- 已读取 backend database、quality、error handling、logging guidelines 和跨层思考指南。
- 本轮不执行 commit、push、deploy 或 task archive；这些动作仍需用户明确要求。

## 步骤一：冻结 contract

**状态：已完成。**

1. 定义 intake field/question enum、fact state、lineage 和 normalization contract。
2. 定义 `AuthoritativeContextSnapshot`、required fact item 与 selection receipt。
3. 明确 model proposal、server candidate、confirmed fact 和 draft profile 的 authority 分界。
4. 更新 API/database/runtime source-of-truth 设计段落，但只写已实现内容时才改 current docs。

## 步骤二：数据库与 repository

**状态：已完成。**

1. additive 创建 fact/question tables、FK/CHECK/unique/index 和 append-only trigger。
2. 实现 scoped repository、current projection、supersede、idempotent replay 和 conflict 检查。
3. 扩展 reset/delete/cutover/export inventory，保持 learner-safe projection。
4. 添加 bootstrap twice、cross-user、lineage、immutability 和 cleanup tests。

## 步骤三：Planning intake 写入

**状态：已完成。**

1. 在 planning session input flow 接入 server-owned candidate normalization。
2. 保存 asked/answered/confirmed/reopened state。
3. draft capability 只读取 current confirmed facts，并绑定 facts fingerprint。
4. confirmation 检查 draft 与 facts snapshot 未 stale。
5. 不从旧历史自动写 confirmed facts。

## 步骤四：统一 Snapshot projector

**状态：已完成。**

1. 从 loader/builder 前抽出 authoritative snapshot projector。
2. actual provider、resume/replay 和 context eval 复用同一 projector。
3. 增加 required facts section 和 conflict order。
4. 将 selection/skip reason 写入安全 receipt。
5. 保持 current-input pinning、adaptive budget 与 provider usage 语义不变。

## 步骤五：语义 history 与 compaction barrier

**状态：已完成。**

1. 标注 confirmed source、correction、unresolved question 和 ordinary history。
2. 修改 recent selection：先 pin semantic required，再按 token/recency 补充，最后应用硬上限。
3. 检查 retirement candidates 是否已有 fact/summary/domain coverage。
4. uncovered critical source 阻止退休或进入确定性 fallback projection。
5. summary conflict 记录 telemetry，不覆盖 fact。

## 步骤六：Decision gate 与公共投影

**状态：已完成。**

1. provider 再次询问 confirmed question 时默认拒绝，除非用户明确 correction/reopen。
2. public planning/session projection暴露安全 question status，不暴露内部 prompt/hash。
3. SSE/trace/checkpoint/export 添加必要指标并通过 redaction。

## 步骤七：验证

至少执行：

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_learning_plan_sessions.py tests/test_tutor_context_loader.py tests/test_tutor_context_builder.py tests/test_tutor_context_budget.py tests/test_tutor_context_summary.py tests/test_tutor_input_merge.py tests/test_tutor_evals.py
.venv\Scripts\python.exe -m pytest -q tests/test_db_bootstrap.py tests/test_tutor_run_repository.py tests/test_tutor_event_replay.py tests/test_tutor_trace_redaction.py
.venv\Scripts\python.exe -m ruff check app tests
.venv\Scripts\python.exe -m mypy app --no-incremental
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-12-tutor-authoritative-context-facts
git diff --check
```

如果 `uv run` 继续发生 Windows trampoline 错误，使用项目 `.venv`，并单独记录环境问题。

### 已执行验证

- `60 passed in 14.13s`：planning、context loader/builder/budget/summary/input merge/eval 聚焦矩阵。
- `97 passed in 3.68s`：schema bootstrap、run repository/replay/redaction/provider/run loop 聚焦矩阵。
- 新增 unresolved-answer compaction barrier 后：`7 passed in 7.03s`（`tests/test_learning_plan_sessions.py`）。
- `uv run ruff check app tests`：通过。
- `.venv\Scripts\python.exe -m mypy app --no-incremental`：`Success: no issues found in 141 source files`。
- `python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-12-tutor-authoritative-context-facts`：通过。
- `git diff --check`：通过，仅出现既有 Windows LF/CRLF 提示。

## 实施结果

- 新增 append-only typed planning facts 与 question-event lineage，支持 deterministic/explicit input、correction、reopen、idempotent replay 和安全公开投影。
- 实际 provider、resume/replay 与 context eval 复用 `build_authoritative_context_snapshot()`；confirmed facts 进入不可驱逐的 `required_facts` section。
- recent history 先按 semantic class pin；未确认/reopened 且尚无 replacement 的来源消息进入 compaction protection。
- planning decision gate 要求稳定 `question_key`，阻止 confirmed field 重复询问并记录 checkpoint/eval 指标。
- 草案绑定 facts fingerprint/revision，事实更新后旧草案确认返回 `LEARNING_PLAN_DRAFT_STALE`。
- export/reset/cutover inventory 已覆盖新表并保持 hash、gate reason、prompt/provider payload 不外泄。

## 回滚

- 应用层可回退本任务新增的 fact producer/projector/gate wiring，但不得删除或改写已经追加的 facts/question events。
- draft generation 可回退旧入口，但不得把新 facts 静默改写回消息历史。
- schema 只 additive；不做 destructive migration。
- 任何失败不得恢复旧 Graph/router runtime。
