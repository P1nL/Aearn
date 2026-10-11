# AGENTS.md

## 仓库概览

Aearn 是面向 AI 编程的编程语言学习 Agent MVP。当前正式实现目录是 `aearn/`，产品、架构、状态机、API、数据库和验收规则以 `docs/` 为 source of truth。

旧教程仓库内容已经从当前工作树移除，不再作为运行目录、依赖来源或默认参考实现。

## 关键规则

- 默认在 `aearn/` 下执行项目命令；仓库根目录只用于 Git、Trellis、文档和 agent 配置。
- 新业务代码默认进入 `aearn/services/`、`aearn/apps/`、`aearn/packages/` 或 `aearn/infra/`，不要重新引入历史教程目录。
- 文档变更优先同步 `docs/README.md` 中列出的 source of truth，不要创建重复规格。
- `docs/design/learning-agent-claude-desktop-framework.html` 是用户设计的受保护前端主原型，不能删除；如需替换，必须先获得用户明确确认。
- 后端依赖以 `aearn/services/api/pyproject.toml` 为准，前端与桌面端依赖以 `aearn/package.json` 和 workspace 配置为准。
- 本地密钥、`.env`、缓存、构建产物和工具 worktree 不进入 Git。

## 开发期联网与真实 API 授权

- 持续授权以 `docs/setup/project-external-resource-policy.md` 为准，外部资源操作前读取该政策及其核算状态登记。
- 2026-10-10用户授权已配置、已获准真实模型的开发/验收调用次数与费用均不限，替代此前累计300元/240元提醒约定；免费搜索耗尽后existing_only，不逐次重复申请范围内联网/真实API权限，不自动充值/升级或新增收费服务。
- 开发期采用人工监控，不以先建设自动计费/预留/硬封顶阻塞已授权调用；合理控制规模与有界重试，不清零历史用量、不把unknown当零，不修改旧runtime预算窗口来伪造新权限。用户叫停时停止新增付费调用；生产、隐私和Trellis实施门禁仍独立。

## 常用命令

```powershell
pnpm --dir .\aearn desktop:check
pnpm --dir .\aearn desktop:dev
```

后端、worker、数据库和 Redis 命令以 `docs/setup/development-environment.md` 与实际 `aearn/` 配置为准。

## 注意事项

- 不要把历史教程项目当作 Aearn runtime。
- 不要在仓库根目录新增 Python 虚拟环境或散装依赖文件。
- 修改代码前先查看相邻文件和 `docs/` 对应规格。
- 提交前优先运行与改动相关的最小验证命令。

<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->
