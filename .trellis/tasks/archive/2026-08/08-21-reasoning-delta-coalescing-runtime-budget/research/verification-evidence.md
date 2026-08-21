# 验证证据

## 自动化

- Focused backend：`68 passed`，后续最终 focused Runtime/dispatcher：`44 passed`。
- Full backend：`689 passed, 2 skipped`；两个 skip 均为显式真实 provider smoke，未调用真实 provider。
- Ruff：通过。
- Mypy：`194 source files`，通过。
- `uv lock --check`：通过。
- `compileall`：通过。
- Desktop Vitest：`48 passed`。
- Desktop `tsc && vite build`：通过。
- PostgreSQL bootstrap 连续执行两次：通过。
- Child 与 Parent `task.py validate`：通过。
- `git diff --check`：通过，仅有现有 Windows line-ending warning。

## Runtime 场景

- fake App Server 5,000 个单字符 reasoning delta：正常完成，文本逐字一致，projection chunks 小于 20。
- `aearn_learning_plan_draft` repair 后继续 2,500 个 delta：正常完成，未出现 `runtime_event_budget_exhausted`。
- 稀疏 timer flush、item/kind/channel/index/phase 边界、feature-off 逐 delta、raw runaway、item、tool、text、time、pending bytes 均有独立回归。
- PostgreSQL receipt 验证 projection sequence 与 source range/count/hash；raw reasoning/final text 不进入 receipt。
- commentary correction、text-less reasoning completion、terminal discard、replay/conflict、snapshot/gap/reconnect 既有回归保持通过。

## 浏览器

使用当前本地 Vite/API 与 disposable 本地用户进入计划界面，不发送消息、不调用 provider。验证 `1440x900`、`900x900`、`390x844`：无水平溢出、无 framework error overlay、console error/warning 为 0；Composer 输入交互正常。截图保存在系统临时目录，未进入仓库。临时用户及其一条未生成草案的 planning session 已通过本地 API 删除。

## 非声明

- 未调用真实 provider。
- 未 push、部署或修改生产数据。
- 未覆盖或提交两项受保护 Obsidian 用户修改。
