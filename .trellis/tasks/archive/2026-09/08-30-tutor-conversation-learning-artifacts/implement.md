# Tutor 对话式学习工件平台实施计划

## Planning State

本父任务只负责 source requirements、任务地图、跨 child 验收和最终集成，且从未作为业务实现目标启动。用户已批准实施；十二个 child 已按依赖完成实现、验证、提交与归档，父任务现仅记录最终验收结果。

## Ordered Delivery

### Phase A：Authority Foundations

1. Child 01：Artifact authority、public union、snapshot v4、SSE/API facade、DB/cutover/reset/export。
2. Child 11：Learning Item Bank、validation/review/publish，先完成可供后续 fixture 使用的 curated seed seam。
3. Child 02：Teaching v3、candidate handles、impossible-instruction gate、continuation/branch arbiter。
4. Child 03：Inline shell、安全 Markdown、branch renderer、展开/折叠/滚动/焦点基础。

### Phase B：Execution Vertical Slice

5. Child 05：SafeExecutionResult v2、test-result artifact、Tutor evaluation Turn。
6. Child 04：Monaco + isolated Preview + Run end-to-end HTML slice。
7. 用 HTML 场景完成第一条垂直验收：message -> artifact -> edit -> live preview -> explicit run -> result Turn -> completion -> next teaching。

### Phase C：Learning Artifact Families

8. Child 06：static/interactive demonstrations。
9. Child 07：knowledge checks、difficulty、hint overlay、remediation/transfer。
10. Child 08：AI code review v2。
11. Child 09：SQL workspace/table result。
12. Child 10：source reference/document drawer。

Child 06-10 可以在基础 contracts 稳定后按不重叠写集并行，但不得分别发明 Artifact、Attempt、Markdown 或 result contract。

### Phase D：Integration and Rollout

13. Child 12：完整 integration matrix、security/adversarial smoke、responsive/accessibility、feature rollback、source-of-truth docs、release non-claims。
14. 父任务最终核对所有 child acceptance，确保没有重复 authority、遗漏 inventory 或未归档风险。

## Per-Child Required Planning Gate

每个 child 在 `task.py start` 前必须：

- PRD 无阻塞问题并通过 convergence pass。
- design/implement 与父任务边界一致。
- implement.jsonl/check.jsonl 至少包含真实 spec/research entry。
- 依赖 child 状态和兼容入口明确。
- 最新 planning summary 由用户在后续消息明确批准。

## Validation Matrix

### Backend / Database

~~~powershell
uv --directory ./aearn/services/api run python -m pytest <focused tests> -q
uv --directory ./aearn/services/api run python -m pytest -q
uv --directory ./aearn/services/api run ruff check app tests
uv --directory ./aearn/services/api run python -m mypy app --no-incremental
uv --directory ./aearn/services/api lock --check
~~~

Bootstrap-heavy PostgreSQL tests必须单进程串行；需要显式覆盖 bootstrap twice、cutover exhaustive inventory、scope FK、CAS、append-only、idempotency、reset/export redaction。

### Shared Executor

~~~powershell
uv --directory ./aearn/services/executor run python -m pytest -q
uv --directory ./aearn/services/executor run ruff check aearn_executor tests
uv --directory ./aearn/services/executor run python -m mypy aearn_executor --no-incremental
~~~

默认不启用真实 Docker/container fleet，不声称 reviewed locks。

### Desktop

~~~powershell
pnpm --dir ./aearn desktop:test
pnpm --dir ./aearn desktop:check
~~~

按 child 需要运行 Vitest、web fixture/browser smoke、Tauri cargo check。必须验证 1440x900、900x900、390x844、keyboard、screen reader semantics、reduced motion、scroll/focus anchors 和 console zero error/warning。

### Preview Security

验证无限循环、top navigation、fetch/WebSocket、popup、download、form submit、parent access、Tauri IPC、oversized logs、invalid nonce、stale artifact/session、host crash/recreate。失败不能退回 main DOM execution。

### Item Bank

验证 schema、answer uniqueness、standard answer、starter failure、hidden-data redaction、difficulty/remediation consistency、reviewer independence、content-hash binding、risk publish gate、retire/version replay。

### Final Hygiene

~~~powershell
python ./.trellis/scripts/task.py validate <active-child>
git diff --check
~~~

最终 integration child 更新 docs 后，运行 source-of-truth link/audit，明确 fake provider/local preview/empty image-lock 的非声明。

## Risky Files and Rollback Points

- Conversation public contracts、snapshot parser、schema manifest、cutover inventory：任何遗漏是 P0。
- Teaching Skill/decision gate：若 artifact mode 可以在无 handle 时通过，会重现原问题。
- Tauri CSP/capabilities/preview host：必须独立安全检查，不能以 UI smoke 代替。
- SafeExecutionResult v2：API/executor/shared/Desktop 必须同步，避免 silent field loss。
- Artifact facade 与 Gate/Review：禁止双写 mastery/progress。
- Item publication：agent consensus 不能覆盖机器/安全失败。

## Rollback

- 先关闭 admission/candidate flags，再关闭 Desktop renderer/Preview；不能先让 UI 消失而模型继续发 artifact 指令。
- 保留新表和历史 rows，只读投影；不做破坏性 down migration。
- 切回 teaching Skill 1.1.0、snapshot v3 和现有 Lesson Gate UI。
- Preview 单独关闭时显示安全 unavailable，不执行伪预览。

## Final Review Gate

所有规划工件写完后只向用户提交最终 planning summary，不运行 `task.py start`。只有用户在该总结之后再次明确批准实施，才可按依赖顺序启动首个 child。

## 2026-09-02 Final Parent Acceptance

- Child01-Child12 all completed in dependency order and were committed/archived without restoring the removed Generative UI runtime or deleting the protected prototype.
- Parent AC1-AC20 are mapped to executable test symbols and the current-workspace browser/native evidence in `docs/qa/acceptance-test-plan.md`; the exact final command ledger and non-claims are in `docs/qa/tutor-harness-release-readiness.md`.
- Final gates: API 869 passed / 2 real-provider cases deselected; Ruff/compileall/lock/Mypy passed; shared 34; executor non-Docker 11; Desktop 160 plus build; Rust 9 plus fmt/check/strict Clippy; disposable PostgreSQL bootstrap twice plus focused schema/cutover/event-v3 21; docs links/control 0 errors; 13 Trellis contexts valid; diff hygiene passed.
- Server authority, snapshot-first recovery, public/private redaction, one Gate/Review/Attempt authority, isolated Preview, Learning Item risk review, contracts-only Artifact initializer, and fragment-110 event-v3 compatibility remain intact.
- Real provider, Docker conformance, production image/Tauri installer build/sign/publish, production data migration, push, deploy, release, and production data mutation were not executed and remain separately approved gates.
