# 实施计划

## 1. 数据库与 catalog

1. 在 `app/db/schema.sql` 增加 taxonomy/tag 表、约束、索引、updated_at 和 seed/backfill。
2. 增加 active course/tag 双向 coverage query 与 bootstrap-twice tests。
3. 确认 cutover inventory、local export/reset/delete 不泄漏或遗漏新表。

## 2. Intent resolver

1. 新建 `planning_intent.py` typed DTO、policy version、语言 alias/方向解析与 course query。
2. 对 Python/JS/TS/Java/Go/C#/HTML/CSS/SQL 的中英文强信号、词边界和 false positive 写单元测试。
3. 增加 optional closed model hint tool/contract；未知 tag、extra field、无课程 tag 安全回退。

## 3. Planning fact 接入

1. 在 plan_drafting fresh input authority 中运行 resolver。
2. 唯一明确语言通过 `deterministic_input` 写 confirmed fact，保持 source evidence、revision 和 idempotency。
3. 多语言/direction/conflict 只保存本轮 request presentation，不创建假 fact。
4. 保证已 confirmed language 不被普通新消息覆盖。

## 4. Generated UI 与 Desktop

1. 扩展 presentation closed schema 和 API parser。
2. Language options 按 candidate course IDs 查询并固定排序。
3. `recommended` nullable；Desktop 初始无选中项，提交 gate 和 a11y 更新。
4. 刷新、重连、历史 request、catalog 更新时保持 durable options。

## 5. 文档与验证

更新：

- `.trellis/spec/backend/codex-runtime-sidecar.md`
- backend database/quality specs
- frontend component/hook/type-safety/quality specs
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/product/frontend-interaction-spec.md`
- QA/setup 文档

建议 focused tests：

```powershell
uv --directory .\aearn\services\api run python -m pytest `
  tests/test_codex_learning_plan_tools.py `
  tests/test_codex_learning_plan_tools_postgres.py `
  tests/test_codex_plan_drafting_cutover.py `
  tests/test_learning_plan_sessions.py `
  tests/test_db_bootstrap.py

pnpm --dir .\aearn\apps\desktop test -- --run
pnpm --dir .\aearn desktop:check
```

随后运行 full pytest、Ruff、Mypy、bootstrap twice、browser smoke 和 `git diff --check`。

## Browser 场景

- 明确 Python：无语言 UI，继续下一缺失事实。
- 前端：仅前端课程，无默认 radio。
- 后端：metadata shortlist。
- Python + Go：仅两项。
- conflict、无信号 full catalog、刷新恢复、窄屏和 console error=0。

## 完成门

- P0/P1 自动测试或 browser evidence 完整。
- 不调用真实 provider，除非用户在实施线程再次明确批准。
- 不覆盖 `.trellis/tasks/.obsidian/plugins/translate/data.json` 与 `.trellis/tasks/.obsidian/workspace.json`。
- 完成检查后按 Phase 3.4 提交并归档 child；不 push、不部署。
