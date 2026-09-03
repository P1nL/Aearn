# 技术设计

## 根因与边界

旧正式 checkout `b09dd36` 的 `080_lesson_teaching_practice.sql` 会先重建只接受 `none|composer` 和 receipt v1/v2 的约束，而本地数据库已有 `teaching_action_receipt_v3`、`learner_response_mode=artifact`。仅放宽旧 fragment 会继续造成 event-v3、Artifact 表/约束和 runtime 代码不一致，因此先安全 fast-forward 到完整平台实现。

fast-forward 后，旧 database volume 又暴露 Learning Item import receipt 的 raw source-file hash 与 CRLF checkout 不同。用户于 2026-09-03 明确选择放弃旧数据，因此不修改 repository idempotency contract，也不重写 immutable receipt；只重建 Aearn 专用本地 Compose volumes。

## 实施方案

1. 在 `.git/codex-backups/` 保存正式 checkout 的 old/new HEAD、before/after status、binary dirty patch、tracked dirty SHA-256 和 untracked Trellis workspace 副本。
2. 机械比较 dirty paths 与 `main..codex/tutor-conversation-learning-artifacts` 变更集；交集必须为空。
3. 对正式 checkout 执行 `git merge --ff-only codex/tutor-conversation-learning-artifacts`，不 stash、不 reset、不 checkout 用户 dirty files。
4. 停止仅由 Aearn state file 追踪且 command verified 的进程；删除 `aearn_aearn_pgdata` 与 `aearn_aearn_redisdata`，重建健康 PostgreSQL/Redis。
5. 在正式 checkout fresh database 上 bootstrap twice；在独立 disposable DB 中提交真实 v3 Artifact teaching receipt，再 bootstrap twice 并断言 receipt 保留。
6. 启动 stack，验证 API/Desktop 与所有受控 worker/beat PID。

## Rollback 与不可逆边界

- Git fast-forward 的旧 HEAD 为 `b09dd36`，dirty patch 独立备份；必要时可在停止进程后恢复代码指针。
- 用户授权放弃的旧 PostgreSQL/Redis volumes 已删除，没有独立 volume/database backup，因此旧本地数据不可恢复。不得把 Git patch 误称为数据库备份。
- 当前新 volumes 可再次清空重建，但不得执行生产数据操作、破坏性 down migration 或删除其他 Compose project 的 volume。
