# 实施计划

1. [x] 记录正式 checkout HEAD/status/dirty patch，并验证 branch ancestry。
2. [x] 确认 dirty paths 与完成分支变更集无交集。
3. [x] fast-forward 正式 `main` 到完成分支，复核原有 status paths 未丢失。
4. [x] 按用户最新决策清空两个 Aearn 专用本地 volumes并重建健康 infra。
5. [x] fresh bootstrap twice；添加并运行 committed Teaching Receipt v3 / conversation event v3 regression。
6. [x] 启动开发栈并验证 API/Desktop/worker/beat 状态；当前保持运行。
7. [x] 完成 check findings、更新 code-spec、提交测试/spec并同步正式 checkout；准备归档任务。

## 验证命令

```powershell
# 正式 checkout / fresh local database
uv --directory .\aearn\services\api run python -m app.db.bootstrap
uv --directory .\aearn\services\api run python -m app.db.bootstrap
pnpm --dir .\aearn dev
pnpm --dir .\aearn dev:status

# 独立 disposable PostgreSQL
uv run python -m pytest -q `
  tests/tutor/test_tutor_teaching_session_postgres.py::test_bootstrap_twice_installs_tables_partial_unique_and_immutable_triggers `
  tests/tutor/test_tutor_teaching_artifact_commit.py::test_bootstrap_twice_preserves_committed_v3_teaching_action_receipt `
  tests/learning/test_learning_artifact_governance.py::test_bootstrap_twice_preserves_committed_v3_conversation_event
```

## 非声明

不调用真实 provider，不运行 Docker executor conformance，不 push/deploy，不修改生产数据，不清理用户无关脏改动。Codex runtime health 只验证本地 sidecar readiness，不构成 provider smoke。

## 2026-09-03 执行摘要

- 正式 checkout `main` 从 `b09dd36` fast-forward 到 `69dd41b`；57 个原始 status paths 与 334 个 branch paths 交集为 0。
- 57 个 status paths 全部保留：56 个 tracked files 与 pre-merge SHA-256 一致；单个 untracked `.trellis/workspace/pinl/` 目录下两文件与备份一致。
- 备份目录含 244,484-byte binary patch；它只备份 Git working tree，不备份已放弃的数据库 volume。
- fresh bootstrap twice 成功；正式 checkout focused schema/bootstrap matrix **6 passed in 3.04s**，Ruff 通过。
- 新增 exact Teaching Receipt v3 regression；worktree 使用独立 disposable DB 的 receipt/schema/event-v3 matrix **3 passed in 11.02s**，Ruff 通过，临时 DB 已删除。
- 最终 `dev:status`：PostgreSQL/Redis healthy，API/Desktop ready，API、main worker、Codex worker、beat、Desktop 五个 tracked PID 均 alive 且 command verified。
- Tauri dev 触碰的八个 generated paths 在 Git raw/filtered object hash 上均与 HEAD 相同，`git diff` 为零；记录为 content-identical metadata/stat entries，不把它们当业务改动提交。
- 初始兼容实现子代理在用户改变决策后立即中断并关闭，未留下 repository 代码修改。唯一 check 的 findings 已由主线程修复。


## 提交与检查结论

- `2391bad` — 添加 committed Teaching Receipt v3 bootstrap-twice regression 与早期 schema v3 assertions。
- `0d8d9d5` — 将旧 checkout / newer schema、disposable DB、显式 local-volume reset 边界写入 database code-spec。
- 同一只读 trellis-check 的 2 high / 2 medium / 1 low findings 全部修复并复核；最终 re-check 无剩余 blocker。
- 正式 checkout 已 fast-forward 到 `0d8d9d5`；运行中的 API/Desktop/worker/beat不需要重启，因为提交只涉及测试和 spec。


## 归档后最终运行复验

- 将 test/spec/archive commits fast-forward 到正式 checkout 时，Uvicorn `--reload` 检测到 test 文件变化；现有 Desktop SSE 长连接使旧 server 停在 graceful shutdown，短暂显示 API not ready。这不是 bootstrap/schema 回归。
- 使用项目自带 `pnpm --dir .\aearn dev:restart`：只停止 state file 中 command-verified 的五个 Aearn 进程，bootstrap 再次成功，然后重新启动全部组件。
- 最终状态：PostgreSQL/Redis healthy，API/Desktop ready；API PID 30428、main worker 34312、Codex worker 38580、beat 38384、Desktop 37624 均 alive 且 command verified。当前 stack 保持运行。
