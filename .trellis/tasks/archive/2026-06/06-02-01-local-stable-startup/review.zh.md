# 01 本地稳定启动 - 中文 Review

## 需要你审核的结论

这个 child task 的目标不是重写启动链路，而是把现有 `aearn/scripts/start-dev.ps1` 和 `pnpm --dir .\aearn dev*` 命令族复核并产品化成 Phase 1 的稳定本地启动基线。

## 范围

本任务负责：

- `pnpm --dir .\aearn dev`
- `pnpm --dir .\aearn dev:status`
- `pnpm --dir .\aearn dev:restart`
- `pnpm --dir .\aearn dev:stop`
- Docker PostgreSQL/Redis 启动与状态可见性
- database bootstrap
- API `/health`
- Celery worker 启动
- Tauri desktop dev server readiness
- `aearn/.logs/` 日志和 `dev-processes.json` 进程状态
- `docs/setup/development-environment.md` 与实际脚本保持一致

不负责：

- 生产部署
- 自动安装 Docker / Node / pnpm / uv / Rust / WebView2 / Python
- 修改全局 PATH、Docker Desktop、WSL 或系统注册表
- 替代后续 `05-environment-doctor-and-install-guidance`
- 改学习业务流程

## 验收重点

- `dev:status` 能清楚显示 Docker、API、desktop 和 tracked PIDs。
- `dev` 能按顺序启动或复用 Docker、bootstrap DB、API、worker、desktop，并写日志。
- `dev:restart` 只处理脚本追踪的 API / worker / desktop 进程。
- `dev:stop` 能停止脚本追踪的 API / worker / desktop 进程。
- 缺少命令或 readiness 失败时，能明确指出失败组件和诊断位置。
- `aearn/.logs/` 文件名稳定，`dev-processes.json` 成功启动后可解析。
- `docs/setup/development-environment.md` 与实际命令、端口、health endpoint、手动 fallback 一致。
- `tests/test_health.py`、`tests/test_db_bootstrap.py`、`tests/test_worker_import.py` 和 `pnpm --dir .\aearn desktop:check` 仍通过。

## 关键设计取舍

- 继续采用 PowerShell 脚本作为 Windows-first 本地入口，不引入跨平台包装器。
- 继续用 Docker 管理 PostgreSQL 和 Redis，不改成内嵌服务。
- 继续用 tracked PID 管理脚本拉起的进程，避免按端口粗暴杀进程。
- 保留手动 fallback 命令，方便脚本失败时排查。
- 环境医生页面后续再做；本任务只提供可靠的启动、状态和失败签名基础。

## 实施顺序

1. 读取 `trellis-before-dev` 相关规范。
2. 复核当前 worktree，排除无关脏文件。
3. 跑或检查 `pnpm --dir .\aearn dev:status` 当前行为。
4. 检查 `aearn/scripts/start-dev.ps1` 的 stale PID、corrupt state、command assertions、错误信息、日志命名和状态可读性。
5. 检查 `aearn/package.json` 命令是否稳定。
6. 检查 `docs/setup/development-environment.md` 是否和脚本漂移。
7. 只在真实漂移或验收缺口存在时做最小改动。
8. 跑 focused backend smoke、desktop check 和安全 lifecycle 子集。

## 风险与回滚

- `dev:restart` / `dev:stop` 可能影响本机正在运行的 Aearn API / worker / desktop，需要确认 PID 追踪逻辑。
- `dev` 可能启动交互式 Tauri desktop，验证时要明确说明。
- Docker Desktop 不可用时，部分检查会因环境失败，不一定是代码失败。
- worker readiness 依赖 Celery 日志中的 `ready`，如果日志格式变化会变脆。
- 回滚方式是撤回脚本改动并继续使用 `docs/setup/development-environment.md` 中的手动命令。

## 完成结果

- `dev:status` 现在会区分 tracked PID 的 `alive`、`stale`、`untrusted` 状态。
- `dev:stop` / `dev:restart` 只会停止命令行已验证的 tracked Aearn 进程，遇到 stale/untrusted PID 会跳过并清理状态。
- 旧的 stale `dev-processes.json` 已通过 `dev:stop` 验证不会误杀进程。
- 完整 `dev` 启动、`dev:restart` 和 `dev:stop` 已验证通过。
