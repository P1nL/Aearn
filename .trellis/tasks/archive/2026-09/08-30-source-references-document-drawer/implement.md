# Source References and Document Drawer 实施计划

## Prerequisites

- 父任务与本 child 的最新 planning summary 已在后续用户消息中明确批准。
- 依赖 child 已满足本 PRD 声明的可用 contract。
- implement.jsonl/check.jsonl 已包含真实 spec/research context。

## Ordered Checklist

1. [x] 扩展artifact-safe ref adapter
2. [x] 实现统一drawer controller和exact resolver
3. [x] 实现scroll/highlight/reduced-motion
4. [x] 实现narrow overlay/collapse/focus/scroll isolation
5. [x] 接入message/artifact citations
6. [x] 补充version mismatch/cross-scope/keyboard tests

## Validation

- [x] context reference backend/API tests
- [x] Desktop drawer/animation/focus Vitest
- [x] browser多视口/scroll smoke
- [x] protected URL/content audit

## Review Gates

- [x] 逐条映射本 child Acceptance Criteria 到自动测试或 fixture/browser evidence。
- [x] 检查 public/private、scope、idempotency、stale/replay、feature-off 和 rollback。
- [x] 运行相关最小验证后，再运行所属 package 完整门。
- [x] 需要 bootstrap 的 PostgreSQL 测试单进程串行。
- [x] 不把 fake provider、本地 runner 或空 image-lock 证据描述为生产批准。

## Rollback Points

- 关闭artifact引用入口，保留现有Lesson source panel
- 无法解析时不做文本搜索fallback
- 不删除历史引用snapshot

## Stop Condition

若设计需要改变用户已确认行为、公共 contract 或 child 边界，停止实现并返回 planning；不得在代码中自行选择新产品策略。


## 2026-09-02 Pre-check Evidence

- Backend exact resolver covers direct Lesson block, persisted lesson_selection context reference, source_inspector_v1 Artifact provenance, stale hash/version, strict extra-field rejection, cross-user scope, and historical assignment migration. Focused PostgreSQL/API run: 6 passed; changed-file Ruff/Mypy passed.
- Desktop exact parser and component/workspace coverage: 6 files / 35 tests passed with TypeScript noEmit. Tests cover exact response echo, async render/retarget, historical notice, absolute highlight, global Escape, narrow focus trap/backdrop, trigger focus restoration, source chips, and stable Tutor/Lesson mounts/drafts.
- Disposable real Chromium harness mounted production components/CSS at 1440x900, 900x900, 390x844, and reduced motion. All document/body/workspace horizontal overflow deltas were 0; conversation scroll stayed exact; narrow width was 0.88 viewport; backdrop stayed open; focus returned; mount count/draft remained 1/unchanged; reduced motion used auto + no highlight animation; fresh warning/error arrays were empty. Temporary files/server were removed.
- Static audit found no protected/private runtime fields in the new resolver projection and no textContent/selector/navigation fallback in the drawer. artifacts/__init__.py remains contracts-only/lazy and fragment 110 was not changed.


## 2026-09-02 Final Validation

- The one permitted native trellis-check was launched read-only with an 8-minute scope and a 2-minute focused-test cap. It remained running past the bounded wait, returned no report, and was terminated; no files were changed and no second check was started. Main-thread review then found and fixed the retry-retarget abort race and post-close browser focus timing.
- Complete API with LLM_TYPE=disabled and real_provider excluded: 865 passed, 2 deselected in 259.03s. Full API Ruff passed; Mypy passed on 248 source files; compileall, uv lock --check (55 packages), and contracts-only Artifact/Lesson/Tutor import smoke passed.
- Complete Desktop: 24 files / 160 tests passed. Production TypeScript/Vite build passed with 139 modules transformed.
- Child task validation passed (implement 4 / check 1). Documentation/spec link and control-character audit: 6 files, 0 errors. git diff --check passed with only configured LF-to-CRLF notices.
- Browser acceptance remained: 1440x900, 900x900, 390x844, and 390x844 reduced-motion had zero document/body/workspace overflow; conversation scroll was unchanged; normal drawer scroll reached the exact block; historical retarget showed the frozen version; 390px drawer width was 88vw and backdrop clicks did not close it; button/Escape restored the exact trigger; Tutor/Artifact draft and mount count were preserved; reduced motion used auto scroll and no highlight animation; fresh console warning/error arrays were empty. Target offset/size and stage height were stable while the absolute overlay animated.
- No real provider/executor, Docker conformance, production image build/sign/publish, Tauri installer, push, deploy, or production data migration was run.
