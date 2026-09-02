# Artifact Integration QA and Rollout 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 建立contract/version矩阵
2. [x] 创建端到端HTML/knowledge/demo/review/SQL/source fixtures
3. [x] 执行SSE/reload/branch concurrency tests
4. [x] 执行Markdown/Preview/SQL/hidden data/item review攻击矩阵
5. [x] 执行多视口/keyboard/reduced motion/scroll focus smoke
6. [x] 审计schema/cutover/export/reset和feature rollback
7. [x] 更新docs/acceptance/readiness非声明
8. [x] 运行全量门并汇总父任务证据

## Validation

- [x] 完整API单进程串行pytest
- [x] Ruff/Mypy/lock/compileall（如当前矩阵要求）
- [x] 完整executor tests（显式排除未获批准的 Docker conformance）
- [x] desktop:test、desktop:check、Tauri cargo check
- [x] browser/webview多视口安全smoke（复用当前工作树 Child03-10 证据；Child12 无新 UI runtime）
- [x] task.py validate所有child与parent、git diff --check

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- 任何P0失败停止rollout并关闭artifact admission
- 先停止model candidate，再禁Desktop/Preview
- 保留additive history，无破坏性down migration
- 文档不得把fixture或local preview写成生产批准

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。


## 2026-09-02 Implementation / Pre-check Evidence

- Added tests/integration/test_tutor_artifact_platform_contract.py as the executable final contract/version audit. It compares backend Pydantic presentation/action/public-item unions to the Desktop static renderer/action registry, verifies routes, default-off gates, the explicit 21-fragment manifest, fragment-110 event-v3 compatibility, contracts-only artifacts package imports, protected prototype retention, family evidence modules, and current source-of-truth markers.
- The first focused audit exposed real documentation drift: database-schema.md still claimed 20 fragments while the explicit manifest has 21. The source of truth was corrected and is now protected by the integration test.
- Updated docs/README.md, runtime architecture, API contract, database schema, development environment, and acceptance plan. The acceptance plan now contains the closed version matrix, one reproducible evidence row for parent AC1-AC20, happy/bad-path family matrix, safe rollout/rollback order, and explicit non-claims.
- Serial cross-family PostgreSQL/API matrix: 98 passed in 51.90s across teaching commit, branch/recovery, execution result, demonstration, knowledge/Hint/remediation, model review, SQL policy, exact source, Item Bank, and the new final contract audit.
- Focused Desktop cross-family matrix: 13 files / 113 tests passed across snapshot/API parsing, Tutor/branch, Safe Markdown, shell, editor/Preview, result, demonstration, knowledge/Hint, model review, SQL, and source drawer.
- Existing current-workspace per-child browser/native evidence remains the interaction source: Child03-10 cover 1440x900, 900x900, 390x844, keyboard/focus, reduced motion, scroll isolation, clean console, isolated Preview attacks, and protected-marker absence. Child12 adds no new UI runtime and will rerun final package/Rust/static gates after the single check.

## 2026-09-02 Final Gate Evidence

- The one bounded read-only trellis-check reported 0 P0 / 2 P1 / 2 P2 and changed no files. Main-thread fixes made family evidence symbol-specific, documentation markers Child12-specific, and the contract guard cover Artifact version/item-reference, exact action fields, and Desktop snapshot v2-v5. The agent was closed and no second check ran.
- Complete API with `LLM_TYPE=disabled` and `not real_provider`: 869 passed / 2 deselected in 622.12s. Ruff, compileall, API lock (55 packages), and Mypy (255 API/worker/shared source files) passed.
- Shared contracts: 34 passed. Executor non-Docker suite: 11 passed; Ruff, Mypy (9 files), and lock (29 packages) passed. Docker conformance remained excluded by approval boundary.
- Desktop: focused Monaco/SQL 6 passed, full 24 files / 160 tests passed, TypeScript/Vite build passed with 139 modules. Rust fmt/check/strict Clippy passed; cargo test 9 passed.
- Disposable local PostgreSQL: explicit bootstrap completed twice; schema/bootstrap/cutover and persisted event-v3 compatibility batch passed 21 tests in 27.37s; disposable database dropped afterward.
- Docs/control audit checked 8 files and 33 relative links with 0 errors. All 12 child contexts plus parent validated. Final diff hygiene passed with only configured line-ending warnings.
- AC19 reuses the recorded current-workspace Child03-10 1440/900/390, keyboard/focus, reduced-motion, scroll-isolation, clean-console, and Preview security evidence because Child12 added no UI runtime. No real provider, Docker conformance, production image/Tauri installer build/sign/publish, production migration, push, deploy, release, or production data operation ran.
