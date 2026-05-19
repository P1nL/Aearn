# Aearn 第一版 release 收口 Design

## Scope and Boundary

这不是新功能任务，而是第一版的发布前收尾任务。它围绕现有实现做三件事：

1. 依据既有计划和验收规则重新验证第一版主闭环。
2. 对验证中暴露的 `P0/P1` 问题做最小必要修复或明确降级。
3. 把最终发布结论和必要文档回写落成稳定记录。

边界是“收口当前第一版”，不是继续扩功能。

## Source of Truth

- 计划边界：`docs/plans/learning-agent-implementation-plan.md`
- 发布门禁：`docs/qa/acceptance-test-plan.md`
- 用户流程：`docs/product/user-flows.md`
- 前端边界：`docs/product/frontend-interaction-spec.md`
- API / 数据边界：`docs/architecture/api-contract.md`、`docs/architecture/database-schema.md`
- 现状证据：现有测试、最近 M1-M6 归档任务、当前代码实现、当前工作树状态

当前仓库没有独立 release 文档，因此这次收口的主记录优先放在 Trellis task 产物和 session journal 中；只有当 source-of-truth 文档本身存在歧义或偏差时，才回写 `docs/`。

## Release Closure Workflow

### 1. Evidence-first audit

先跑自动化验证和最小桌面端 smoke，基于结果判断是否已经满足第一版发布门禁，而不是先写“已完成”结论。

### 2. Severity-based triage

- `P0`：硬阻塞。必须修复并重跑相关验证。
- `P1`：默认也应修复；若决定不修，必须形成已知问题记录，并明确说明为什么不阻塞发布。
- `P2`：不阻塞发布，但需要被记录，避免混淆为“尚未分析”。

### 3. Minimal remediation

如果验证暴露问题，只做与第一版发布直接相关的最小修复，不借机扩展产品范围或重构无关模块。

### 4. Final release decision

最终必须给出明确结论：

- `ready to release`
- 或 `not ready`

该结论由验证结果和问题分级决定，不由里程碑名称或已归档任务数量直接决定。

## Validation Strategy

### Automated checks

- 后端 pytest 继续按顺序执行，避免共享 bootstrap DB 带来的并发干扰。
- 桌面端以 `pnpm --dir .\aearn desktop:check` 作为基础静态验证。
- Trellis task 本身也要通过 `task.py validate`，保证收口记录可归档。

### Manual smoke

自动化通过后，仍要补最小人工 smoke，重点看：

- 首次进入 onboarding 路径是否仍然可用；
- returning-user / resume 路径是否正常；
- review notice / review-first 路由是否符合 M6 边界；
- settings 七类边界是否没有越权控制项。

## Output Artifacts

- 当前 task 的 `prd.md` / `design.md` / `implement.md`
- 必要时的代码或文档修复
- 本次任务对应的验证结果与发布结论
- 若存在未修复 `P1/P2`，则形成明确的已知问题说明

## Rollback / Safety

- 如果 release 验证暴露 `P0` 问题，结论直接回到 `not ready`，先修复再谈归档。
- 如果收口过程中为了修复问题改动代码，所有变更都必须以“最小必要修复”为原则，并重跑受影响验证。
- 如果某项实现与文档冲突，以 source-of-truth 文档为起点决定是修代码还是改文档，不能两边都不处理。
