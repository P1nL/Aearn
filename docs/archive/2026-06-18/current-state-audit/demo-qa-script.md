# Demo 与 QA 脚本

> **历史快照，非当前 source of truth。** 本文生成于 2026-06-18，描述已经被 Tutor Harness 替代的旧运行时。当前事实请从 [`../../../README.md`](../../../README.md) 路由。

生成日期：2026-06-18

## 本地前置

从仓库根目录 `E:\codee\Aearn` 执行 PowerShell 命令。

| 目标 | 命令 |
|---|---|
| 安装/刷新 frontend workspace 依赖 | `pnpm install --dir .\aearn` |
| 启动 PostgreSQL / Redis | `docker compose -f .\aearn\infra\docker-compose.yml up -d` |
| 一键启动 API、worker、desktop | `pnpm --dir .\aearn dev` |
| 查看当前状态 | `pnpm --dir .\aearn dev:status` |
| 重启本脚本管理的进程 | `pnpm --dir .\aearn dev:restart` |
| 启动并写入确定性测试数据 | `pnpm --dir .\aearn dev:test-data` |
| 停止本脚本管理的进程 | `pnpm --dir .\aearn dev:stop` |

不要在文档或日志里输出真实 `aearn/.env` 内容。需要配置时从 `aearn/.env.example` 复制，再本地填写 key。

## 快速健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:8001/health
pnpm --dir .\aearn dev:status
```

预期：

| 项 | 预期 |
|---|---|
| API | `http://127.0.0.1:8001/health` 可访问 |
| Desktop | `http://127.0.0.1:1420` 可访问 |
| PostgreSQL | `aearn_postgres` healthy 或 ready |
| Redis | `aearn_redis` healthy 或 ready |
| Worker | `aearn_worker.worker_app:celery_app` tracked 或可启动 |

## 建议 demo 路径

### 1. Cold start

目标：证明没有假 demo 数据，frontend 会从真实 API 启动。

操作：

1. 清空或忽略 `localStorage["aearn.bootstrap"]`。
2. 打开 desktop dev server。
3. 观察进入 onboarding，而不是自动进入假学习页。

讲法：本地 bootstrap 只是缓存指针，真正恢复要通过 users/plans/dashboard/resume。

### 2. Onboarding route card

目标：展示 Agent 生成式 UI 和 latest-card-wins。

操作：

1. 输入学习目标，例如“我想用 JavaScript 学会读懂 AI 生成的 DOM 事件代码，每天 30 分钟”。
2. 等待 `show_learning_route` card。
3. 再发一条修订，例如“把节奏压缩到一周内”。
4. 只点击最新路线卡的 `开始学习`。

讲法：普通文本回复和路线卡是分开的，确认计划前只是 draft；正式写库在 confirm。

### 3. Learning workspace

目标：展示文档阅读、概念检查、练习卡和 runner。

操作：

1. 进入第一个知识点。
2. 查看右侧 `DocumentationPanel`。
3. 点击概念检查触发卡片。
4. 进入练习，运行 `visible_tests`。
5. 修改代码后观察 stale 状态。
6. 请求 hint、explain error、check explanation。
7. 提交结果，观察后端返回评分和 ReviewState。

讲法：前端不计算分数、不计算 `due_at`；它只展示 backend response。

### 4. Review flow

目标：展示复习不是简单重做题，而是 batch + warmup + candidate pool。

操作：

1. 使用 `pnpm --dir .\aearn dev:test-data` 准备确定性数据。
2. 打开 review page。
3. 选择到期知识点，开始复习。
4. 回答 warmup 或 skip。
5. 对 review exercise 运行/提交。
6. 观察 final summary、`due_at`、`forget_risk`。

讲法：warmup 不写 Attempt；中间 submit 不立即改长期 ReviewState；最终 batch 聚合后才写 ReviewLog。

### 5. Notes and settings

目标：展示本地学习资料沉淀和隐私边界。

操作：

1. 从学习页或复习页打开 note drawer。
2. 创建/更新笔记。
3. 在 Notes page 检索。
4. 打开 Settings，展示本地用户数据 summary、export/reset/delete 入口和 environment doctor。

讲法：这是本地优先学习 Agent，不做 SaaS 多租户 auth；隐私边界靠本地用户数据管理和导出/重置。

## 验证命令

### 文档/任务验证

```powershell
Get-ChildItem .\docs\current -Filter *.md
git diff --check
python .\.trellis\scripts\task.py validate .\.trellis\tasks\06-18-current-project-docs-regeneration
```

### Frontend

```powershell
pnpm --dir .\aearn desktop:check
```

该命令从 `aearn/package.json` 进入 `apps/desktop`，实际执行 `tsc && vite build`。

### Backend targeted tests

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_health.py tests/test_runner_registry.py tests/test_language_capabilities.py
uv --directory .\aearn\services\api run python -m pytest tests/test_onboarding_m2.py tests/test_learning_sessions_m3.py tests/test_reviews_m4.py tests/test_notes_m5.py tests/test_dashboard_resume_m6.py
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
```

如果本地 PostgreSQL/Redis 或模型 provider 未配置，优先运行不依赖外部服务的 unit tests；涉及 DB 的测试需要本地服务可用。

## 面试 Q&A 提纲

| 问题 | 建议回答要点 |
|---|---|
| 这个项目解决什么问题？ | 面向 AI 编程时代的编程语言学习，闭环覆盖路线、练习、验证、复习和笔记 |
| 为什么用桌面端？ | 本地优先、低摩擦访问本机工具链、便于展示代码运行和数据隐私 |
| Agent 如何避免乱写库？ | Agent 输出受控 tool call/intent；service/repository 拥有写库、幂等和 public response |
| 为什么不用前端算分？ | 分数、FSRS、due_at 和 hidden test 都是后端事实，前端只展示 |
| 语言支持到什么程度？ | JS/Python/TS/SQL/Java/Go/C#/HTML/CSS 是公开路线；C++/Rust planned/non-public |
| Java/Go/C# 的 runner 安全性？ | teaching-grade 本机单练习 runner，不是生产级容器沙箱，不支持项目级依赖 |
| LangGraph 的作用？ | 可选编排层，做 routing/intent/safe context；默认关闭，服务层仍可运行 |
| Review 为什么复杂？ | 避免一次中间提交污染长期记忆，通过 warmup、candidate pool、batch finalization 提高稳定性 |
| 如何处理模型不可用？ | 映射为 stable error，如 `MODEL_UNAVAILABLE` / `PLAN_GENERATION_UNAVAILABLE`，不泄露 provider 细节 |
| 项目下一步？ | 刷新 source-of-truth docs、补 shared contracts、加强真实模型配置路径、继续收敛 planned endpoints |

## Demo 风险控制

| 风险 | 处理 |
|---|---|
| 模型 key 未配置 | 演示 deterministic local flow、runner、dashboard、review seed fixtures；说明 LLM 能力需要 `.env` |
| Docker 未启动 | 先运行 `docker compose -f .\aearn\infra\docker-compose.yml up -d` |
| `localhost` 连接异常 | 使用 `127.0.0.1`，当前代码默认也是 `127.0.0.1` |
| Java/Go/C# toolchain 缺失 | 展示 missing toolchain / unsupported 状态，说明这是能力边界而不是 UI bug |
| C++/Rust 被问到 | 明确 planned/non-public，当前不承诺编译运行 |
