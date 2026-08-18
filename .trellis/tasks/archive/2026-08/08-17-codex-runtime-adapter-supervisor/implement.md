# 实施计划

1. 读取 Child 1 `research/result.md`，确认 `deepseek-v4-flash` Responses specific Go，再固定支持版本、custom provider启动参数和 capability 条件。
2. 新建 Aearn-owned Runtime/tool/event DTO 与 `AgentRuntimePort`。
3. 实现 JSON-RPC stdio connection、Codex method/item mapper 与 bounded event stream。
4. 实现 `CodexRuntimeSupervisor` 的 preflight、generation、shutdown、crash 和 process-tree 清理。
5. 新增 `tutor-codex` Celery route、默认启动的 solo worker 与本地 dev lifecycle；保留显式 opt-out，且不 admission 业务 run。
6. 添加 fake app-server tests、single-owner tests、timeout/crash/restart tests 和日志 redaction tests。
7. 验证现有 Harness worker 与 desktop development command 不回归。
8. 运行 focused pytest、ruff、mypy、相关启动 smoke、Trellis validate 和 `git diff --check`。

## 风险文件

- `aearn/services/api/app/agents/`
- `aearn/services/api/app/config.py`
- `aearn/services/worker/aearn_worker/worker_app.py`
- `aearn/scripts/start-dev.ps1`
- 相关 worker/process tests

## 回滚

新 Adapter 和 worker route 默认不可达；回滚时关闭或移除新 worker 配置，不改 Harness 路径，不迁移数据库。
