# 实施计划

## 执行原则

- 父任务只作为规划图和最终集成验收，不直接实施。
- child 必须按依赖顺序逐个 `task.py start`、验证、归档。
- 每个 child 开始前重新读取父任务和前序 child 的最终工件/证据。
- 当前是 Codex inline 模式，Phase 2 使用 `trellis-before-dev`，不要求 JSONL context 清单。
- 未经明确批准不运行真实 provider、安装/升级 Codex、提交、push 或部署。

## Child 1：协议可行性验证

1. 固定 Codex binary/revision、App Server protocol、隔离 Codex Home和测试工作目录。
2. 建立 Python stdio JSON-RPC spike client、fake app-server与fake DeepSeek Responses fixture。
3. 配置 custom provider精确选择 `deepseek-v4-flash`、`wire_api = "responses"`、非OpenAI auth和环境变量secret。
4. 验证 initialize、thread/start、turn/start、item/turn event、dynamic tool server request、repair result、interrupt、timeout、child exit和redaction。
5. 经单独批准运行真实 `deepseek-v4-flash` tool-repair smoke；未授权/未执行记为pending，不打印prompt/response/secret。
6. 只有DeepSeek-specific Go才解锁Child 2；No-Go停止后续children，不用OpenAI或Chat Completions继续正式路线。

## Child 2：Runtime Adapter 与监管

1. 定义 runtime/tool/event ports和 Aearn-owned DTO。
2. 实现 stdio client、supervisor、version/auth/capability preflight和 shutdown。
3. 新增独立 `tutor-codex` Celery route/worker与 dev process lifecycle。
4. 建立 fake protocol tests、crash/restart tests、single-owner tests。
5. 不接正式 plan-drafting admission。

## Child 3：学习计划工具与恢复

1. 新增 typed planning context/draft schemas。
2. 从 planning facts构造 profile，复用 LearningPlan domain与 append-only repository。
3. 定义 safe issue taxonomy和 structured tool result。
4. 添加 Aearn tool registry与 tool-call budget/repair/fence。
5. 用 fake Codex loop证明 invalid -> repair -> completed；不接 public cutover。

## Child 4：持久化与公开投影

1. Additive DB runtime_kind、binding、receipt schema和 bootstrap测试。
2. 实现 Codex event -> Aearn lifecycle/public item映射。
3. 完成 final message safety、failed/error projection、idempotency和 stale fencing。
4. 接 conversation snapshot/SSE，但 feature保持 off/test-only。
5. 验证 reasoning/raw args不进入公共投影。

## Child 5：计划制定受控切换

1. 增加 server-side runtime selection/cutover config。
2. 仅新 plan-drafting run冻结 `codex_sidecar_v1`。
3. 接 Queue/Steer/Interrupt/Retry与 Codex control；保留 LearningPlan confirm authority。
4. Desktop继续使用 Aearn snapshot/SSE；只增加必要 readiness/error状态。
5. 运行 Harness/Codex并列回归和 rollback测试。

## Child 6：集成 QA 与文档

1. 运行全失败矩阵：version、auth、startup、tool repair、policy、stale、interrupt、crash、DB conflict、unsafe final。
2. 经授权执行真实 local `deepseek-v4-flash` Responses plan-drafting smoke和 rollback演练。
3. 更新 `docs/README.md`、runtime、API、DB、setup、user flows、acceptance与release evidence。
4. 明确非声明：不代表生产批准、不代表 Codex bundle/distribution、不代表所有 Tutor已切换。
5. 完成全仓最小相关验证与 final parent acceptance review。

## 统一验证命令候选

```powershell
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api run python -m pytest <focused tests> -q
uv --directory .\aearn\services\api run python -m app.db.bootstrap
pnpm --dir .\aearn\apps\desktop test
pnpm --dir .\aearn desktop:check
python ./.trellis/scripts/task.py validate <task-dir>
git diff --check
```

真实 smoke 命令由 Child 1/6 设计并默认 opt-in，不写入 secret。

## 风险文件与回滚点

- `aearn/services/api/app/services/tutor/interactive.py`
- `aearn/services/api/app/services/tutor/interactive_worker.py`
- `aearn/services/api/app/services/tutor/persistence.py`
- `aearn/services/api/app/db/schema.sql`
- `aearn/services/worker/aearn_worker/worker_app.py`
- `aearn/scripts/start-dev.ps1`
- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/hooks/useTutorConversationStream.ts`

每个 child只修改自己拥有的层；跨层变更由后续 child在前序已归档基线上实施。数据库只做 additive变更；回滚关闭 admission并保留已写 evidence。

## 启动门

规划批准后应启动：

```powershell
python ./.trellis/scripts/task.py start 08-17-codex-sidecar-protocol-spike
```

不要启动父任务，也不要跳过 Child 1 直接改正式 Runtime。


## 最终集成结果

- Child 1-6 已按依赖顺序完成；父任务从未 `task.py start`，仅承担规划与最终验收。
- 精确 `deepseek-v4-flash` + `aearn_deepseek` + Responses 在 Windows isolated Home 中完成获批真实 tool-repair smoke，未发生fallback。
- Aearn-owned Runtime、typed LearningPlan tools、durable safe projection、仅新 `plan_drafting` 的受控cutover、steer/interrupt与same-Runtime Retry均已交付。
- 完整 API：`660 passed, 2 skipped`；Codex focused：`66 passed`；public/SSE/redaction：`21 passed`。
- Ruff、Mypy（192 source files）、compileall、lock、bootstrap twice、Desktop、Trellis validate与`git diff --check`通过。
- source-of-truth、setup、user flow、acceptance与integration readiness证据已同步。
- 本地完成不批准production rollout、push、deploy、Codex安装/升级或所有Tutor scope切换。
