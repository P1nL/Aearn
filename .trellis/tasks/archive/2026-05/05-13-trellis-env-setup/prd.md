# 配置 Trellis 前置环境

## Goal

按照 Trellis 初始化输出的前置要求，配置当前本机 Codex 环境，使 Trellis hooks 具备被 Codex Desktop 发现和批准的基础条件。

## Background / Known Context

- 当前项目位于 `E:\codee\ReActAgentsTest`，已经完成 Trellis 初始化与刷新。
- Trellis 初始化输出提示：Codex hooks 需要在 `C:\Users\PINKING\.codex\config.toml` 中启用 `features.hooks = true`。
- Codex 0.129+ 还需要用户在客户端执行 `/hooks` 并批准 Trellis `UserPromptSubmit` hook；该步骤需要交互，不能由普通消息代替。
- 当前仓库已有大量未提交删除项和未跟踪项，本任务不处理这些既有工作树变化。

## Requirements

- 在不改动仓库业务代码的前提下，检查并按文档更新 Codex 本机配置。
- 对 `C:\Users\PINKING\.codex\config.toml` 这类关键配置，编辑前先读取现状并创建备份。
- 确保 `[features]` 下存在 `hooks = true`，保留已有配置项。
- 配置后通过读取文件验证 `hooks = true` 已落盘。
- 明确告知用户仍需新开/重启 Codex 会话，并在客户端输入 `/hooks` 进行交互批准。

## Acceptance Criteria

- [x] `C:\Users\PINKING\.codex\config.toml` 已备份。
- [x] `C:\Users\PINKING\.codex\config.toml` 的 `[features]` 下包含 `hooks = true`。
- [x] 已用只读命令验证配置结果。
- [x] 已说明剩余手动步骤：重启或新开 Codex 会话后输入 `/hooks` 批准 Trellis hook。

## Verification

- Backup created: `C:\Users\PINKING\.codex\config.toml.bak-20260513-172032`
- Verified config lines:
  - `[features]`
  - `memories = true`
  - `hooks = true`

## Out of Scope

- 不处理仓库现有删除项、未跟踪项或 Git 提交。
- 不替用户完成 Codex 客户端 `/hooks` 交互批准。
- 不修改项目业务代码。

## Notes

- Keep `prd.md` focused on requirements, constraints, and acceptance criteria.
- Lightweight tasks can remain PRD-only.
- For complex tasks, add `design.md` for technical design and `implement.md` for execution planning before `task.py start`.
