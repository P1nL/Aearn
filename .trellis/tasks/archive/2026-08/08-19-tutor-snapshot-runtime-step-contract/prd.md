# 修复 Tutor snapshot 运行步骤契约回归

## 目标

修复 Desktop 将合法 Tutor conversation snapshot 错误判定为 invalid payload 的回归，使 Codex sidecar 生成的公开运行步骤可以被严格解析，并让当前对话在刷新或重试后正常恢复时间线。

## 背景与已确认事实

- 2026-08-19 的本地真实请求 `GET /api/tutor/conversations/{conversation_id}/snapshot` 返回 HTTP `200`，顶层 `tutor_conversation_snapshot_v2` 字段完整。
- 失败 payload 的 `timeline[].kind=process` 包含公开步骤 `runtime_started`、`domain_tool_running`、`domain_tool_completed`。
- 后端 allowlist 已在 `aearn/services/api/app/services/tutor/persistence.py:140-150` 与数据库约束 `aearn/services/api/app/db/schema.sql:6570-6585` 接受这些 key。
- Codex runtime projection 会在 `aearn/services/api/app/services/tutor/runtime_projection.py:303-319` 生成这些步骤。
- Desktop 的 `TutorPublicProcessStep` 与 `isTutorProcessStepKey` 仍只接受旧集合，见 `aearn/apps/desktop/src/types.ts:147-151` 与 `aearn/apps/desktop/src/api.ts:3190-3192`，导致 `toTutorPublicProcess` 返回 `null`，继而在 `aearn/apps/desktop/src/api.ts:253-254` 抛出 `Tutor snapshot API returned an invalid payload`。
- 当前工作树已有用户修改 `.trellis/tasks/.obsidian/workspace.json`，本任务不得覆盖或整理该文件。

## 范围内

- 将 Desktop 的公开 process step literal union 与后端现行 allowlist 同步。
- 保持 `unknown` 输入与严格 runtime validation，不用宽松 cast、未知 key 忽略或关闭 exact DTO 边界来绕过错误。
- 增加 API boundary 回归测试，覆盖包含 Codex sidecar process steps 的合法 snapshot。
- 保留并验证未知 process step key 仍会拒绝整个 snapshot。
- 运行相关 Desktop Vitest、typecheck/check，并使用本地真实 snapshot 或浏览器流程验证错误消失。

## 范围外

- 不改变后端 runtime projection、数据库 schema、process label 或 Tutor 状态机。
- 不改变 Desktop 视觉布局、Think 展示策略、Queue、typed request 或 SSE 行为。
- 不修改历史数据，不执行生产部署，不提交代码。
- 不修改已归档的 `08-13-codex-like-tutor-conversation-experience` 父任务。

## 需求

1. `TutorPublicProcessStep["key"]` 必须覆盖后端公开 allowlist 的全部当前值：`input_received`、`context_prepared`、`authorized_resource_checked`、`runtime_started`、`domain_tool_running`、`domain_tool_completed`、`learning_reply_generated`、`replaced_by_newer_input`。
2. `isTutorProcessStepKey` 必须与类型 union 保持一致，并继续拒绝不在 allowlist 中的值。
3. snapshot parser 必须接受真实 Codex sidecar process timeline，同时继续验证 step state、label、elapsed time 和其他既有字段。
4. 测试必须直接经过 `fetchTutorConversationSnapshot` 的 `unknown -> parser -> typed DTO` 边界，不能只测试局部 helper 或使用类型断言替代运行时验证。
5. 修复不得扩大 public payload 权限或把 provider reasoning、tool arguments/results、command/path 等受保护内容带入 Desktop。

## 验收标准

- [x] 包含 `runtime_started`、`domain_tool_running`、`domain_tool_completed` 的合法 snapshot 可由 `fetchTutorConversationSnapshot` 成功解析。
- [x] 包含未知 process step key 的 snapshot 仍抛出 `Tutor snapshot API returned an invalid payload`。
- [x] 现有 Tutor API boundary 测试通过。
- [x] `pnpm --dir .\aearn\apps\desktop test -- tutorApiV2.test.ts` 或项目等价 focused Vitest 命令通过。
- [x] `pnpm --dir .\aearn desktop:check` 通过。
- [x] 本地真实 Tutor conversation snapshot 不再触发截图中的 client error，页面可渲染 learner/Tutor 消息。
- [x] `git diff --check` 通过，且 diff 不包含 `.trellis/tasks/.obsidian/workspace.json` 的用户修改。

## 关键决策

- 本任务是 PRD-only 的轻量 bugfix，不新增 `design.md` 或 `implement.md`。
- 以服务端 `persistence.py` allowlist 与数据库约束为当前契约权威；Desktop 做最小同步，不回退后端新增运行阶段。
- 继续使用 closed union 和 fail-closed parser；修复方式不是放宽校验，而是补齐已正式发布的 allowlisted key。

## 风险与延期项

- 若未来后端再次新增 process step key，仍需同步 Desktop 契约与 API boundary fixture；本任务不引入共享代码生成机制。
- `process.turn_id` 是否进入 Desktop `TutorPublicProcess` 类型属于更广泛的 DTO exactness 整理，本次错误并非由该字段触发，暂不扩展范围。

## 验证结果

- `pnpm --dir .\aearn\apps\desktop test -- tutorApiV2.test.ts`：通过，1 个文件、4 个测试。
- `pnpm --dir .\aearn\apps\desktop test`：通过，7 个文件、42 个测试。
- `pnpm --dir .\aearn desktop:check`：通过，TypeScript 与 Vite production build 成功。
- 浏览器真实恢复：进入 `Aearn Dev Test User` 的未完成学习计划，原 learner/Tutor message 均可见，invalid payload 横幅为 0，console warning/error 为 0。
- `git diff --check`：通过。
- 用户已有 `.trellis/tasks/.obsidian/workspace.json` 修改保持未触碰、未纳入本任务 diff。
