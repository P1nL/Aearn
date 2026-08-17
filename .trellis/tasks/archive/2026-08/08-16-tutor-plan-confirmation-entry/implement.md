# 实施计划

## 1. 运行时与 Skill 契约

- [x] 修改 `aearn/services/api/app/agents/skills/tutor.learning-plan-draft/1.0.1/instructions.md`，明确 successful draft 后结束 turn，禁止以 `approval` 请求计划确认。
- [x] 修改 `aearn/services/api/app/services/tutor/decision_protocol.py` 的 canonical approval example，替换为非学习计划的受控授权场景。
- [x] 增加或调整 Skill catalog、provider decision/fake-provider 回归测试，证明新计划草案不会产生 pending approval。
- [x] 运行相关后端定向测试，确认 generic approval identity/CAS 和 learning-plan confirm 未回归。

## 2. Desktop 职责与文案

- [x] 由 `LearningPlanBuilderPage` 向 `TutorConversationSurface` 传递窄的计划 Composer 提示状态，不传递完整 draft。
- [x] `current_draft` 存在时，将 planning Composer placeholder/accessible label 改为“对计划有修改意见？直接告诉我……”。
- [x] 保持 `TypedRequestSeat` 对非计划 approval 的现有行为，不使用前端 prompt 文案识别或隐藏请求。
- [x] 保持右侧 `LearningPlanDraftCard` 为唯一计划创建按钮，并验证 exact confirm API 参数、busy/error/success 行为。
- [x] 增加 `LearningPlanBuilderPage` 与 `TutorConversationSurface` 相关 Vitest 覆盖。

## 3. 同 Turn 重复渲染修复

- [x] 在 snapshot replace 与 history prepend 的统一时间线 reconciliation 中，按 `turn_id` 折叠正式 Tutor message 与配套 request 记录。
- [x] pending request 继续由底部 `TypedRequestSeat` 承担交互；不修改服务端 message/request 原子持久化契约。
- [x] 保留 request-only legacy snapshot 的 `TutorRequestHistory` 回退渲染。
- [x] 增加回归测试，锁定“配对记录单次显示”和“legacy request-only 仍显示”。

## 4. Think 验证屏障、首段稳定与恢复修复

- [x] 保留 `350ms` 首段稳定窗口与 recovery snapshot 保留策略，但不再把 timer 作为独立展示 authority。
- [x] 将 projector 的 provider EOF 改为仅校验 JSON 闭合和 flush；由 Provider gateway 在完整 schema/domain/safety/stream-match 验证后调用 `complete_attempt()`。
- [x] Desktop 仅在 validated `complete + 350ms` 同时满足后把 received buffer 交给 DOM/typewriter；incomplete snapshot 保持静态 Think。
- [x] authoritative reset/discard 在 complete 前无论多晚到达都取消候选 generation；recovery snapshot 请求前不清空已经 validated 且可见的文本。
- [x] 增加慢速 rejected attempt、超过窗口仍未 complete、incomplete snapshot、sequence gap recovery 和 validated 后逐字显示回归测试。

## 5. 正式文档同步

- [x] 更新 `docs/product/frontend-interaction-spec.md`：通用 pending request 接管 Composer，但 learning-plan draft confirmation 是右侧 inspector 的明确例外。
- [x] 更新 `docs/product/user-flows.md`：草案完成后 Composer 用于修改，右侧窗口用于唯一确认。
- [x] 更新 `docs/architecture/tutor-harness-runtime.md`：generic approval 与 HTTP plan confirmation 的 authority 边界。
- [x] 使用 `trellis-update-spec` 同步 backend、frontend 与 cross-layer guideline，记录 validated complete authority 和慢速 rejected attempt 回归。

## 6. 验证

- [x] 后端定向测试：Skill/decision protocol、Tutor run/provider、interaction request、learning plan session。
- [x] `pnpm --dir .\aearn\apps\desktop test`
- [x] `pnpm --dir .\aearn desktop:check`
- [ ] 在 `http://127.0.0.1:1420` 使用全新 planning session 验证：生成草案后底部仍是 Composer，右侧为唯一确认入口。
- [ ] 浏览器检查 1440px、900px、390px、键盘焦点、无水平溢出、console clean、reduced-motion。
- [x] 检查 Git diff，确认没有修改无关的通用 approval contract、数据库 schema 或用户现有改动。

## 风险文件与检查点

- `aearn/services/api/app/agents/skills/tutor.learning-plan-draft/1.0.1/instructions.md`：模型行为主约束；先补测试再调整措辞。
- `aearn/services/api/app/services/tutor/decision_protocol.py`：通用 provider schema/example；只改 example 文案与场景，不改 exact schema。
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`：已有未提交修改；实施前必须重新查看 diff，避免覆盖当前 public-thinking 工作。
- `aearn/apps/desktop/src/features/tutor/tests/TutorConversationSurface.test.tsx`：已有未提交修改；追加测试时保持现有 turn identity/public-thinking 覆盖。
- `aearn/apps/desktop/src/features/learning/LearningPlanBuilderPage.tsx`：计划 session、右侧 inspector 和 confirm authority 所有者。
- `docs/product/frontend-interaction-spec.md`、`docs/product/user-flows.md`：正式产品 source of truth，必须与实现同行更新。

## 停止与回滚条件

- 如果实现需要删除 generic approval DTO/API 或改变 proposal identity/CAS，停止并回到设计阶段。
- 如果计划 Composer 修改必须通过自动批准/自动拒绝历史 request 才能工作，停止并重新评估历史兼容方案，不在页面加载时静默写入。
- 如果确认 API 需要数据库 schema 变化，停止并重新拆分任务；当前设计不需要 schema migration。
- 任一验证失败时只回滚本任务窄范围修改，不清理或覆盖现有工作树中的其他改动。


## 实施验证记录（2026-08-16）

- `uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_provider_gateway.py tests/test_tutor_skill_catalog.py tests/test_tutor_interaction_requests.py tests/test_learning_plan_sessions.py -q`：`109 passed`。
- `uv --directory .\aearn\services\api run ruff check ...`：通过。
- `uv --directory .\aearn\services\api run python -m mypy app`：`173 source files` 无问题。
- `uv --directory .\aearn\services\api lock --check`：通过。
- `pnpm --dir .\aearn\apps\desktop test`：`7 files / 37 tests` 通过。
- `pnpm --dir .\aearn\apps\desktop test -- TutorConversationSurface.test.tsx`：重复渲染修复后 `1 file / 11 tests` 通过。
- 重复渲染修复后的完整 `pnpm --dir .\aearn\apps\desktop test`：复跑结果 `7 files / 38 tests` 通过；首次运行仅出现一次既有 planning idle class 异步断言时序失败，立即复跑通过。
- 重复渲染修复后的 `pnpm --dir .\aearn desktop:check`：TypeScript 与 Vite production build 通过，`84 modules transformed`。
- Think 稳定窗口/恢复修复定向测试：`pnpm --dir .\aearn\apps\desktop test -- TutorConversationSurface.test.tsx`，`1 file / 13 tests` 通过。
- Think 稳定窗口/恢复修复完整 Desktop 测试：`7 files / 40 tests` 通过。
- Think 稳定窗口/恢复修复 `pnpm --dir .\aearn desktop:check`：TypeScript 与 Vite production build 通过，`84 modules transformed`。
- `pnpm --dir .\aearn desktop:check`：TypeScript 与 Vite production build 通过，`84 modules transformed`。
- `git diff --check`：无 whitespace error；仅报告工作树既有 LF/CRLF 提示。
- 本地 `dev:restart` 后 API 与 Desktop 均 ready；浏览器页面 identity、非空 DOM、无 framework overlay、console warning/error 均通过。
- 计划页真实浏览器状态未创建测试用户复现：当前本地数据停在首次建档页，为避免未经授权写入用户数据，1440/900/390 的计划页截图与真实点击确认保留为人工验收项；对应组件交互已由 Vitest 覆盖。
- 修复失败复盘证据：本地持久化的 rejected generations 从首个 `append` 到 `discard` 为 `494ms..4954ms`，证明 `350ms` timer 不能作为 authority；旧事件还出现 `complete` 后 `17ms..103ms` 再 `discard`。
- 验证屏障修复定向后端：`tests/test_tutor_public_thinking_stream.py tests/test_tutor_provider_gateway.py`，`88 passed`；相关 Tutor runtime/history/request 矩阵 `131 passed`。
- 验证屏障修复 Desktop：`TutorConversationSurface.test.tsx`，`1 file / 14 tests`；完整 Desktop `7 files / 41 tests`；`desktop:check` production build 通过，`84 modules transformed`。
- 最终后端完整 suite：`594 passed, 1 skipped`；`ruff check app tests`、`mypy app --no-incremental`、`uv lock --check` 均通过。
- Trellis task validate 与 `git diff --check` 通过；后者仅有工作树既有 LF/CRLF 提示，无 whitespace error。

## 收尾说明（2026-08-17）

- 用户明确要求任务收尾；自动化、完整后端 suite、Desktop suite、build、lint、typecheck、lock、Trellis validate 与 diff hygiene 均通过。
- 未为浏览器人工验收创建新的本地用户或调用真实 provider；对应计划确认、Composer 修改、响应式与可访问性行为已有组件/API 测试覆盖。该人工 smoke 作为非阻断 post-archive 验证保留，不代表生产发布批准。
- 本轮只归档 `08-16-tutor-plan-confirmation-entry`；并行的 `08-15-tutor-public-thinking-text-stream` 与 `08-17-codex-runtime-sidecar-integration` 保持原任务状态。
