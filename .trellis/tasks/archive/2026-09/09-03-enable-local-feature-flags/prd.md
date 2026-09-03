# 开启本地 Tutor 可写功能

## 目标

解除 Desktop 的全局 thread/turn v2 只读模式，并开启 Learning Artifact 平台当前默认关闭的本地产品功能。

## 范围

- 在正式运行目录 `D:\works\Aearn\Aearn\aearn\.env` 开启：
  - `TUTOR_LEARNING_ARTIFACTS_ENABLED=true`
  - `TUTOR_ARTIFACT_TEACHING_MODE_ENABLED=true`
  - `LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED=true`
- 保持已有 `TUTOR_THREAD_TURN_V2_ENABLED=true`，并将 fresh PostgreSQL 的全局 cutover authority 从初始状态推进到 `enabled`。
- 重启本地项目使配置生效。

## 边界

- “未开启的功能”按当前只读问题解释为 thread/turn v2 写入 authority 与 Artifact 平台三个产品 gate。
- 不启用 real-provider smoke、Docker conformance、生产发布、push/deploy 开关。
- 不修改 inverse safety flags、runner/container verification 或 published Skill bundle。
- 按用户要求不运行额外测试或独立验收；仅执行配置/state transition 和必要重启。

## Acceptance Criteria

- [x] `.env` 三个 Artifact/Item Bank gate 为 true，原文件有时间戳备份。
- [x] thread/turn v2 cutover 完成 prepare + enable。
- [x] 本地项目重启完成。
- [x] 未运行用户明确省略的额外验证。


## 2026-09-03 执行记录

- `.env` 备份：`D:\works\Aearn\Aearn\aearn\.env.backup-20260903-094351`。
- 新增/更新三个本地 gate 为 true：`TUTOR_LEARNING_ARTIFACTS_ENABLED`、`TUTOR_ARTIFACT_TEACHING_MODE_ENABLED`、`LEARNING_ITEM_BANK_AGENT_REVIEW_ENABLED`。
- `TUTOR_THREAD_TURN_V2_ENABLED=true` 原已存在；数据库 authority 已执行 prepare + enable，结果为 `state=enabled`、`generation=1`、`effective_enabled=true`。
- `pnpm --dir .\aearn dev:restart` 完成。脚本自身报告 PostgreSQL/Redis healthy、API/Desktop ready，以及五个 tracked PID alive/command verified。
- 按用户要求未运行额外 pytest、Ruff、Mypy、browser smoke 或 provider验证。
- `TUTOR_DEEPSEEK_RESPONSES_JSON_SCHEMA_ENABLED=false` 与 `RUNNER_COMPILED_SANDBOX_ENABLED=false` 保持原值，因为它们不控制本次 Desktop thread/turn 写入只读状态；真实 smoke/conformance 也未启用。
