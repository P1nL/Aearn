# 技术设计

## 文档与规范

- `docs/README.md` 继续作为唯一当前文档索引。
- 将 `docs/current/Aearn/*` 移入 `docs/archive/2026-06-18/current-state-audit/`，保留内容中的历史标识，并修复相对链接。
- backend directory spec 改为描述 `agents/harness`、`agents/runtime`、`agents/skills`、`services/tutor`、`services/learning` 等实际边界。
- frontend directory spec 明确 `features`、`ui/dsh-derived`、域级 API/contract/style 的目标结构。

## 依赖锁

`aearn/pnpm-lock.yaml` 是唯一权威 Node lock。删除已跟踪的 desktop `package-lock.json`，并通过 `.gitignore` 防止误提交，不改变任何依赖版本。

## Obsidian 状态

保留可共享的 vault 配置和已决定 vendored 的插件资源；仅取消跟踪并忽略 `workspace.json` 与 `plugins/*/data.json` 等易变个人状态。

## 兼容与回滚

历史文档移动必须更新非归档引用。归档任务记录中的旧路径不改写。若某 README 或 spec 仍需保留历史计划链接，只能明确标注其历史属性。
