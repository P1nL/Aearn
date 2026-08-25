# 实施计划

## 执行顺序

1. 启动并完成 `08-25-repository-governance-hygiene`。
2. 启动并完成 `08-25-desktop-frontend-modularization`。
3. 启动并完成 `08-25-api-persistence-test-modularization`。
4. 启动并完成 `08-25-database-schema-modularization`。
5. 运行全量集成验证并核对四个子任务验收矩阵。
6. 更新必要的 Trellis spec 与开发日志；未经授权不提交。

## 最终验证

```powershell
uv --directory .\aearn\services\api lock --check
uv --directory .\aearn\services\api run python -m pytest -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app --no-incremental
pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
git diff --check
```

根据子任务实际结构补充数据库 bootstrap、executor 和文档链接验证。

## 最终实施结果

### 仓库治理

- 保留“仓库根目录治理、`aearn/` 正式运行代码”的宏观边界。
- 归档误放在 `docs/current/Aearn/` 的 2026-06-18 历史审计包，并同步文档索引与相对链接。
- 固定 `pnpm@10.8.0`，删除 Desktop `package-lock.json`，只保留 root `pnpm-lock.yaml`。
- 将 Trellis Obsidian workspace/plugin data 从 Git 跟踪中移除，但保留本地文件并加入 ignore。
- 刷新 backend/frontend 目录规范和 API/root README。

### Desktop 模块化

- `api.ts`、`types.ts`、`styles.css` 转为兼容 barrel/import entry。
- 新增 6 个 API 模块、7 个 contract 模块、8 个样式模块。
- `TutorConversationSurface.tsx` 从约 1,113 行降到约 633 行，提取视图部件与模型 helper。
- 浏览器验证覆盖桌面双侧栏、390x844 移动布局、overflow、课程切换和 console 零错误。

### API 持久化与测试

- 原 7,018 行 Tutor persistence 单体替换为 16 个模块；公开 import 路径保持兼容，100 个 repository 方法 AST 等价。
- API 测试从根目录 110 个同级文件迁到 8 个领域目录；6 个共享 helper 进入 `tests/support/`。
- 默认测试禁止向真实 Celery broker 发送 Tutor wakeup，保留本地 fast path，消除双消费者测试波动。

### 数据库 Schema

- 原 7,402 行 `schema.sql` 替换为 12 个显式 manifest fragment；生成阶段逐字节校验内容不变。
- 所有 fragment 继续在同一 caller-owned connection 与最终提交事务中执行。
- bootstrap 增加 transaction advisory lock 和 deadlock/serialization failure 整事务有界重试。

## 最终验证结果

- API：`721 passed, 2 skipped`；收集 `723 tests`。
- API Ruff：通过；API Mypy：通过；API `uv lock --check`：通过。
- Database bootstrap 连续两次：通过；Schema/DB focused：`8 passed`。
- Desktop Vitest：`9 files / 60 tests` 通过。
- Desktop TypeScript/Vite build：通过，101 modules transformed。
- Executor：lock、Ruff、Mypy 通过，`12 passed`。
- Docker Compose config：通过。
- 当前 Markdown 相对链接：57 个非归档文档检查通过。
- 四个子任务与父任务 Trellis JSONL validation：通过。
- 受保护原型仍存在。
- `git diff --check`：通过。

## 安全与 Git 结果

- 未覆盖用户已有工作树修改。
- 未保留提交、未 push、未部署、未修改生产数据。
- Trellis archive 曾触发一次非预期本地自动提交，已立即通过精确 soft reset 移除，工作树与索引内容未丢失。
