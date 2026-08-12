# 三栏学习工作区与结构化上下文引用实施计划

## 前置检查

- [x] 前置 child 已归档，父任务完成 9/11。
- [x] 已核对当前 Desktop、Tutor 输入事务、Lesson/Gate、Review API 与任务 PRD。
- [x] 当前工作树只有敏感 Obsidian 翻译插件数据文件，实施和提交均排除该文件。
- [x] 用户已明确要求“继续执行任务”并允许提交后继续，本 child 可直接激活实施。

## 实施步骤

### 1. 冻结引用契约与 schema

- [x] 新增严格 context reference input/domain/safe projection contract。
- [x] 新增 append-only `tutor_message_context_references`、FK、索引与 immutable trigger。
- [x] 将新表纳入 local export/reset、cutover inventory、schema/lock tests。

### 2. 接入 Tutor 输入、历史与 context loader

- [x] first-turn、conversation input、continuation 接受 bounded typed references。
- [x] 在外层输入事务内先固定 run scope，再验证 source artifact 并绑定 message/run revision。
- [x] acceptance 与 public history 返回 safe references。
- [x] context loader 以独立 structured source 注入当前 revision references，不拼接 learner content。
- [x] 覆盖 idempotency、跨用户/track/version、terminal attempt、frozen replay 和 redaction 测试。

### 3. 补齐 Desktop contracts

- [x] 增加 roadmap、track detail、Review queue/session/attempt、context reference 类型与 exact-key parser。
- [x] 增加 Tutor conversation create/resume 和 references 请求字段。
- [x] 保持 unknown-first parsing，不使用 `any` 或直接断言绕过。

### 4. 实现工作区与 Review 主路径

- [x] 新建 `TrackLearningWorkspace`、`LearningRoadmapPanel`、`ReviewSessionPanel`。
- [x] 从首页继续学习/开始复习均进入同一 workspace。
- [x] 增加宽屏三栏、中宽 drawer、窄屏 tabs、独立滚动、焦点与 reduced-motion。
- [x] 用版本化本地导航指针恢复位置，挂载后服务端复核。

### 5. 接入 Lesson/Practice 与 Tutor references

- [x] Lesson block 支持同 block 文本/代码选择并创建 `lesson_selection` 草稿。
- [x] terminal Gate Attempt 提供 `exercise_feedback`；真实执行 Attempt 额外提供 `execution_result`。
- [x] Review terminal Attempt/finalization 提供 `review_feedback`。
- [x] Tutor composer 显示可移除 chips，发送后按 acceptance 清空；历史显示 safe reference cards。
- [x] scope key 切换时取消 SSE/请求并清空旧用户作用域状态。

### 6. 文档与规格同步

- [x] 更新 `docs/product/frontend-interaction-spec.md` 的正式工作区行为。
- [x] 更新 API/database source of truth 与必要 Trellis spec，记录引用不得进入 learner content 和 retired basename 约束。

## 验证命令

```powershell
# API focused tests
cd .\aearn\services\api
uv run pytest tests/test_tutor_context_references.py tests/test_tutor_routes.py tests/test_tutor_conversation_history.py tests/test_tutor_context_loader.py tests/test_review_sessions.py tests/test_tutor_run_loop.py::test_retired_runtime_paths_and_settings_are_absent -q
uv run ruff check app tests
uv run mypy app
uv run pytest -q

# Desktop
cd ..\..\..
pnpm --dir .\aearn desktop:check

# Trellis / diff
python .\.trellis\scripts\task.py validate .trellis\tasks\08-04-learning-workspace-context-references
git diff --check
```

如本地 API/PostgreSQL 可启动，再用真实浏览器验证 `1440x900`、`1024x768`、`390x844` 的 Lesson、Review、引用发送/重放、drawer/tab 键盘和 scope 切换；若环境阻塞，记录精确阻塞并保留静态/contract 证据。

## 风险文件与回滚点

- `aearn/services/api/app/db/schema.sql`、Tutor input/persistence/context loader：先跑 focused API tests，再继续 UI。
- `aearn/apps/desktop/src/api.ts`、`types.ts`：exact-key parser 与 API 同步提交，不拆成不兼容中间状态。
- `App.tsx` 与全局 CSS：保留 learning home/plan builder/cutover；不恢复旧 router 或 retired basename。
- 每个阶段均检查 `git status`，绝不 stage `.trellis/tasks/.obsidian/plugins/translate/data.json`。


## 完成验证记录

- 2026-08-12：`pnpm --dir .\aearn desktop:check` 通过，`tsc && vite build` 完成 60 个模块转换。
- 2026-08-12：API focused suite 通过，`20 passed`。
- 2026-08-12：全量 Ruff 通过，`All checks passed!`。
- 2026-08-12：全量 mypy 通过，`Success: no issues found in 163 source files`。
- 2026-08-12：全量 API 测试通过，`509 passed, 1 skipped`。
- 2026-08-12：真实本地浏览器验证覆盖宽屏三栏、中宽 drawer、窄屏 tabs；Review queue → warmup → terminal Attempt → finalize、Review feedback 引用、Lesson selection 引用均通过，页面无水平溢出，运行时无 exception/error。
- 2026-08-12：drawer 初始焦点、焦点循环、Escape 关闭和焦点归还通过。
- 2026-08-12：`python .\.trellis\scripts\task.py validate .trellis\tasks\08-04-learning-workspace-context-references` 与 `git diff --check` 通过。
- 浏览器验收使用可删除的本地 verified fixture，未调用真实 provider、真实 executor 或生产数据；验收后已调用本地用户删除接口清理 fixture。
