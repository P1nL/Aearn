# 修复 Tutor Teaching Receipt Bootstrap 兼容性

## 背景

用户从 `D:\works\Aearn\Aearn` 的旧 `main` 启动本地环境时，数据库 bootstrap 在 `tutor_teaching_action_receipts` CHECK 约束处失败。现有 PostgreSQL 已包含完成后的 Learning Artifact v3 receipt 数据，而该 checkout 仍停留在 Artifact 平台实施前的提交。

## 目标

让正式本地 checkout 使用已经完成并验证的 Artifact 平台代码，恢复可重复 bootstrap 与完整开发启动。最初要求保留既有本地数据；该要求已被用户在 2026-09-03 的最新明确决策“放弃旧数据”取代。

## 当前要求

- 将正式 checkout 安全快进到已完成的 `codex/tutor-conversation-learning-artifacts`，保留其现有无关脏改动。
- 合并前保存可恢复的 dirty patch/status 证据，并确认 dirty 路径与分支变更无重叠。
- 仅清空 Compose project `aearn` 的本地开发数据 volumes：`aearn_aearn_pgdata` 与 `aearn_aearn_redisdata`；不得删除其他 Docker volume、仓库文件或生产数据。
- fresh bootstrap 连续执行两次；使用独立 disposable PostgreSQL fixture 验证 committed `teaching_action_receipt_v3` 与 conversation event v3 能跨 bootstrap twice 保留。
- 启动/状态验证不得调用真实 provider、Docker conformance、push、deploy 或生产迁移。

## 被取代的要求

- ~~不得删除或改写既有本地业务数据。~~ 已于 2026-09-03 被用户明确授权的本地 Aearn volume 重建取代。
- 实际旧数据库未保留；schema 兼容性通过 synthetic committed v3 regression 验证，而不是声称旧 volume 已迁移成功。

## Acceptance Criteria

- [x] 根因确认是旧 `main` fragment 080 只允许 receipt v1/v2，而数据库已有合法 v3 rows。
- [x] 正式 checkout 以 fast-forward 集成完成分支；合并前的 57 个 status paths 均得到保留和备份。
- [x] 只删除并重建用户授权的两个 Aearn 本地 named volumes。
- [x] fresh 正式 checkout `python -m app.db.bootstrap` 连续两次成功。
- [x] disposable PostgreSQL 中 committed Teaching Receipt v3 与 conversation event v3 bootstrap-twice regression 通过。
- [x] `pnpm dev` 不再报 database bootstrap failed；API/Desktop/worker/beat/infra 状态通过。
- [x] focused tests、Ruff、Trellis validate 与变更范围审计通过。
