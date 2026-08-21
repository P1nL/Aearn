# 最终集成验证证据

## 结论

2026-08-21，Parent `08-21-tutor-planning-intent-runtime-stream-reliability` 在两个 Child 均已独立提交并归档后完成跨 Child 最终集成复核。课程意图 authority、动态 Generated UI、Runtime delta coalescing、source/projection receipt 与语义预算保持同一条 `plan_drafting + codex_sidecar_v1` 数据流，未发现需要新增功能代码的集成缺陷。

## Child 交付边界

- Child 1 已归档：`.trellis/tasks/archive/2026-08/08-21-planning-course-intent-dynamic-generated-ui`。
  - 工作提交：`f45ffdc5 feat: add planning course intent generated UI`
  - 归档提交：`8ca93f80 chore(task): archive 08-21-planning-course-intent-dynamic-generated-ui`
- Child 2 已归档：`.trellis/tasks/archive/2026-08/08-21-reasoning-delta-coalescing-runtime-budget`。
  - 工作提交：`5699d97e fix: coalesce runtime deltas with semantic budgets`
  - 归档提交：`a82deb59 chore(task): archive 08-21-reasoning-delta-coalescing-runtime-budget`

## Parent 验收矩阵

| 验收项 | 结果 | 证据 |
| --- | --- | --- |
| Python + 数据分析自动确认 | 通过 | PostgreSQL/API 回归确认 `language_id=python`、`source_kind=deterministic_input`、`policy_version=planning-language-intent-v1`，下一缺失字段不是语言。Parent deterministic matrix 复验为 `auto_confirm`。 |
| 前端方向 shortlist | 通过 | PostgreSQL metadata 解析为 `html_css/javascript/typescript`，`selection_scope=intent_shortlist`，`recommended=null`。 |
| Python + Go 后端多语言 shortlist | 通过 | exact options 为 `python/go`，`selection_scope=explicit_shortlist`，不写自动确认 fact。 |
| 冲突与无信号 | 通过 | `Go + 前端` 为 `conflict/conflict_shortlist` 且无推荐；无方向/语言信号为 `full_catalog`。 |
| 课程 metadata authority | 通过 | 修改 title/description 不改变 course UUID shortlist；新增 active 未标注课程由 deferred constraint 与 bootstrap coverage 以 `language_course_intent_coverage_missing` 拒绝。 |
| 5,000 单字符 reasoning delta | 通过 | fake App Server 完整终态逐字一致，source count 5,000，coalesced reasoning chunks 小于 20；feature-off 也不恢复 2,000-event failure。 |
| LearningPlan tool repair 长 reasoning | 通过 | `aearn_learning_plan_draft` 一次 repair 后继续 2,500 delta 并完成，未出现 `runtime_event_budget_exhausted`。 |
| projection/recovery | 通过 | PostgreSQL receipt 保存 projection sequence 与 source range/count/hash；commentary、text-less completion、terminal discard、replay/conflict、gap/snapshot/reconnect/restart 回归通过。 |
| Desktop Generated UI | 通过 | 单选初始零 checked、提交 disabled；选择后恰好一个 checked、提交 enabled；session draft 重新挂载后恢复。 |

## Parent 最终质量门

- Full backend：`689 passed, 2 skipped in 156.82s`。两个 skip 均为显式真实 provider smoke；本次未启用。
- Ruff：`All checks passed!`
- Mypy：`Success: no issues found in 194 source files`
- `uv lock --check`：通过。
- `compileall`：通过。第一次补充检查使用了错误的相对路径并输出 `Can't list './aearn/services/api/app'`；随后按 `uv --directory` 工作目录语义改为 `python -m compileall -q app` 并通过，该探索性命令不计作失败门。
- Desktop Vitest：`7 files / 48 tests passed`。
- Desktop `tsc && vite build`：通过。
- PostgreSQL bootstrap 连续两次：均输出 `Aearn database bootstrap complete.`。
- Parent `task.py validate`：通过。
- `git diff --check`：通过；仅报告两个受保护 Obsidian 用户文件的既有 Windows line-ending warning。

## Browser smoke

- 使用本地 API/Vite、disposable 本地 PostgreSQL 用户进入学习主线和计划对话；只填写未发送的计划草稿，不触发 provider。
- 新一轮 DOM/交互复验覆盖 `1440x900`、`900x900`、`390x844`：三者均 `scrollWidth == clientWidth`、Composer 可见、无 framework overlay；计划草稿在视口切换间保持；console error/warning 为 0。
- 刷新后本地身份恢复到学习主线首页，无 overlay、无横向溢出、console 仍为 0。
- 本轮截图调用超时，因此不把新截图声明为证据；复用同一当前工作区 Child 2 已保存的三张截图：
  - `C:/Users/PINKING/AppData/Local/Temp/aearn-child2-1440x900.png`
  - `C:/Users/PINKING/AppData/Local/Temp/aearn-child2-900x900.png`
  - `C:/Users/PINKING/AppData/Local/Temp/aearn-child2-390x844.png`
- disposable 用户 `28ad043e-b9b2-4f8c-a954-f9adea227bd3` 及其一条空 planning session 已通过本地 API 删除。

## 非声明

- 未调用真实 provider。
- 未 push、部署或修改生产数据。
- 未覆盖或提交 `.trellis/tasks/.obsidian/plugins/translate/data.json` 与 `.trellis/tasks/.obsidian/workspace.json`。
- 本地最终集成通过只代表 repository readiness，不代表生产发布批准。
