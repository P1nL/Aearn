# Claude 前端改造对接模板

本文档用于把 Aearn desktop 前端改造任务交给 Claude 或其他代码助手执行。它不是新的 source of truth；所有产品、交互、API、验收边界仍以 `docs/README.md` 中列出的正式文档为准。

## 适用场景

- 调整 Aearn desktop 的页面布局、组件层级、文案、视觉密度或交互动线。
- 修复浏览器 QA 发现的前端状态问题，例如 stale 状态、按钮禁用、错误提示、恢复流程或设置边界。
- 做小范围 UI polish，但不改产品边界、API 契约、FSRS 规则或后端评分逻辑。

## Claude 必读文档

在修改前先读这些文件：

```text
docs/README.md
docs/product/frontend-interaction-spec.md
docs/qa/acceptance-test-plan.md
.trellis/spec/frontend/index.md
.trellis/spec/frontend/quality-guidelines.md
.trellis/spec/frontend/state-management.md
.trellis/spec/frontend/type-safety.md
```

如果改动涉及 API 响应、学习会话、复习或笔记，还要读：

```text
docs/architecture/api-contract.md
.trellis/spec/backend/quality-guidelines.md
.trellis/spec/backend/error-handling.md
```

## 真实实现位置

```text
aearn/apps/desktop/src/App.tsx
aearn/apps/desktop/src/pages/
aearn/apps/desktop/src/features/
aearn/apps/desktop/src/components/
aearn/apps/desktop/src/lib/
aearn/apps/desktop/src/api.ts
aearn/apps/desktop/src/types.ts
aearn/apps/desktop/src/styles.css
```

默认不要修改：

```text
docs/design/learning-agent-claude-desktop-framework.html
```

这个文件是用户设计的受保护主原型，只能作为视觉和布局参考；除非用户明确要求，否则不能删除、重写或替换。

## 硬性边界

- 不要把旧教程目录或历史原型当成 runtime。
- 不要在前端计算最终评分、FSRS Rating、`due_at` 或 ReviewState。
- 不要向用户暴露 `Attempt(run)`、`Attempt(submit)`、`review_submit` 这类内部事实标签。
- 不要给 Settings 增加修改评分规则、Attempt 必填事实、FSRS 参数或 raw `due_at` 的控件。
- 不要把 compiled 语言统一展示为“可完整运行”：Java / Go / C# 只有 `managed_compiled_test` teaching-grade 单练习能力；C++ / Rust 暂不支持公开路线。
- 不要持久化真实模型 API key 到前端、数据库或仓库文件。
- 不要把 API-only 成功当成前端通过；必须看真实渲染 UI。

## 推荐任务提示词

把下面这段交给 Claude，然后替换 `<任务目标>`、`<验收点>` 和 `<是否需要修改前先询问>`：

```text
你在 Aearn 项目中修改 desktop 前端界面。

任务目标：
<任务目标>

验收点：
<验收点>

交互要求：
<是否需要修改前先询问>

必须遵守：
1. 真实实现目录是 aearn/apps/desktop/src。
2. docs/product/frontend-interaction-spec.md 是前端交互 source of truth。
3. docs/qa/acceptance-test-plan.md 是验收口径。
4. .trellis/spec/frontend/quality-guidelines.md 是前端实现规则。
5. 不要暴露 Attempt(run)、Attempt(submit)、review_submit、FSRS 内部规则、score 规则编辑或 raw due_at 控件。
6. 不要修改 docs/design/learning-agent-claude-desktop-framework.html，除非用户明确要求。
7. 修改后必须运行 pnpm --dir .\aearn desktop:check。
8. 如果涉及学习闭环，必须浏览器验证 onboarding -> learning -> run visible tests -> explain-error -> stale -> rerun -> check explanation -> submit。

输出要求：
- 说明改了哪些用户可见行为。
- 说明是否触碰 API contract 或后端状态边界。
- 给出实际运行过的验证命令和结果。
```

## 最小验收命令

前端代码改动后至少运行：

```powershell
pnpm --dir .\aearn desktop:check
```

如果涉及 API-connected UI 或学习闭环，还要启动真实本地服务：

```powershell
docker compose -f .\aearn\infra\docker-compose.yml up -d
uv --directory .\aearn\services\api run python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
pnpm --dir .\aearn\apps\desktop dev
```

浏览器打开：

```text
http://127.0.0.1:1420
```

学习闭环手工 QA 路径：

```text
clear bootstrap / cold start
-> onboarding
-> select JavaScript DOM Beginner
-> generate draft
-> confirm plan
-> run visible tests with flawed blanks
-> explain-error
-> edit blanks and verify stale warning + submit disabled
-> rerun fixed blanks
-> check explanation
-> submit
-> reload and verify dashboard/resume restores real learning state
-> settings boundary check
```

## 常见回归点

- 选择课程后创建用户会触发表单重置，导致草稿标题和真实 draft 不一致。
- 代码修改后旧运行结果没有 stale 提示，或者 submit 仍然可点。
- 设置页新增了看似方便但越界的评分、FSRS 或 Attempt 控件。
- reload 只信任 localStorage，没有触发 user / plan / dashboard / resume 请求链。
- 只跑 `desktop:check`，但没有验证真实浏览器 UI。

## 交付清单

Claude 完成后必须给出：

- 修改文件清单。
- 用户可见变化。
- 触碰的风险边界。
- 运行过的命令和结果。
- 如果有浏览器 QA，说明通过的页面路径和关键 UI 状态。
