# 类 Codex Tutor Desktop 与集成迁移验收：实施计划

## 启动门

- 前五个 child 均已完成归档，v2 API/event/error/state、DSH UI foundation 与 global cutover capability contract 已冻结。
- 加载 `trellis-before-dev`、React best practices 和 frontend testing/debugging skill；阅读 frontend component/hook/state/type/quality specs 与 frontend interaction source-of-truth。
- 检查当前 Desktop 未提交 diff，不覆盖 continuation enum/API 类型修改。

## 有序实施

1. 在 `types.ts` 建立 v2 discriminated unions、expected version mutation payload 与 exhaustive helpers。
2. 在 `api.ts` 添加 snapshot/events/turn/queue/steer/interrupt/retry/request endpoints；删除或强隔离旧 continuation write helper，只保留 legacy read methods。
3. 新建 conversation stream hook/reducer，完成 snapshot-first、sequence 去重、gap/reset、switch cleanup。
4. 重构 Tutor surface 的 message timeline、DSH-derived `Think` disclosure、server-safe error cards、waiting migration card 与 ordinary interrupted cutover projection；独立 process item 仅兼容解析，不进入 renderer。
5. 实现 composer 状态：idle send、running default Queue、explicit Steer、Stop、typed response/approval、Retry。
6. 实现 Queue tray 的编辑/上移/下移/删除/立即执行及 stale conflict refresh。
7. 完成窄屏、键盘、focus、live region、reduced-motion 和滚动锚点。
8. 移除所有 Tutor surface 对 `/runs/{id}/inputs` 的依赖与可触达 caller；v2 surface 不依赖 run-local SSE，legacy timeline 仅保留 read adapter，并验证 `410 Gone` 不触发 continuation 重试。
9. 使用 fake provider/fixture user 完成 browser/Tauri 集成流程；同步 docs 与验收矩阵。

## 验证

```powershell
pnpm --dir .\aearn desktop:check
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_routes.py tests/test_tutor_sse.py tests/test_tutor_conversation_history.py -q
python .\.trellis\scripts\task.py validate .trellis/tasks/08-13-codex-like-tutor-desktop-migration-qa
git diff --check
```

若项目已有前端 test runner，新增 reducer/hook/component tests；否则以 TypeScript build + Browser plugin smoke 记录。浏览器覆盖 running default Queue、Queue operations、Steer conflict、Stop、Retry、typed request、legacy waiting migration card/fresh v2 Send、active cutover cancellation=ordinary interrupted、offline/reconnect、narrow viewport、keyboard/reduced motion。

## 高风险文件

- `aearn/apps/desktop/src/api.ts`
- `aearn/apps/desktop/src/types.ts`
- `aearn/apps/desktop/src/features/tutor/TutorConversationSurface.tsx`
- `aearn/apps/desktop/src/hooks/useTutorSSE.ts` 或新增 v2 stream hook
- Tutor page/controller/styles/tests
- `docs/product/frontend-interaction-spec.md`
- `docs/architecture/api-contract.md`
- `docs/architecture/database-schema.md`
- `docs/architecture/tutor-harness-runtime.md`
- `docs/qa/acceptance-test-plan.md`

## 回滚与完成门

- v2 feature gate 关闭时显示明确 unavailable/read-only，不 silent fallback 到旧 continuation merge。
- 不删除受保护原型和 legacy data/routes。
- 所有父任务可观察验收均有自动测试或记录的 browser smoke，且 Desktop 无敏感输出后完成。
