# 复刻 Codex 对话运行体验：父任务实施编排

## 启动门

- 父任务仅用于协调，不直接执行 `task.py start`。
- 用户看到最新最终规划摘要后，必须用后续消息明确批准实施；此前六个 child 保持 `planning`。
- 最终规划获批后，在 `E:\codee\Aearn-dsh-ui-reuse` 确认 clean，执行 `git merge --ff-only main`，再把本地分支重命名为 `codex/codex-like-tutor-conversation`；成功前不启动 child。
- 将本 worktree 中合并后的唯一 Trellis 树迁入目标 worktree，read-back 并验证；旧 DSH 规划树在来源核对完成前保留，随后标记 superseded，不并行实施。
- 每个 child 开始前执行 `trellis-before-dev`，读取本 child PRD/design/implement、依赖 child 的完成证据、对应 specs 与 source-of-truth。
- inline 模式逐个实施和检查，不派发 implement/check sub-agent；只启动依赖已满足的下一个 child。
- `E:\codee\Aearn` 保持最新干净基线；所有融合逐文件检查 scoped diff，不 reset、不覆盖用户修改。

## 执行顺序

1. **Child 1：Thread/Turn/Item/Event 与 durable dispatch 底座**
   - additive conversation/run/event/job schema；
   - snapshot、conversation SSE、opaque cursor；
   - PostgreSQL dispatch authority、Celery wakeup、beat reconciler；
   - legacy history/run SSE 只读兼容；
   - 冻结 DTO/event/cursor/job contract 后归档。

2. **Child 2：DSH-derived UI Foundation**
   - 固定 revision 的 light tokens、scoped CSS compatibility aliases；
   - primitives、非品牌 icons、toast adapter 与组件测试基础；
   - MIT NOTICE、UPSTREAM mapping 与 import boundary tests；
   - 不修改 Tutor 业务行为，验证后归档。

3. **Child 3：Typed Request 与 Authority Fresh Turns**
   - clarification/planning_input/approval typed request；
   - capability/external authority receipt；
   - 七字段 planning catalog、prompt examples 与 exact identity；
   - 来源 turn 终结、response/receipt 创建 fresh turn/job；
   - 冻结 request/receipt/error/event contract 后归档。

4. **Child 4：Queue、Steer、Interrupt 与 Retry**
   - 默认 Queue、固定 10 项、CRUD/reorder/execute；
   - 显式 Steer、Interrupt、pause/resume 与 completed-only drain；
   - pending request 阻塞接缝、Retry/effect lineage 与迟到写屏障；
   - 完成并发、崩溃恢复与副作用幂等测试后归档。

5. **Child 5：Thread/Turn v2 Global Cutover**
   - singleton/advisory lock、preparing freeze、inventory/preflight；
   - waiting rows recoverable failure、其他可取消 legacy run immediate cancel；
   - ambiguous effect blocked、旧 continuation POST 410 tombstone；
   - env kill switch + DB enabled authority、rollback/read-only contract；
   - 只验证机制，不执行生产 cutover，完成后归档。

6. **Child 6：Desktop Integration、Migration QA 与文档**
   - snapshot-first conversation reducer/SSE hook；
   - DSH-derived Composer/Queue/Question/Think/Plan UI；
   - Stop/Retry/Steer/typed response 与 legacy migration card；
   - 删除/隔离旧 continuation caller，验证 global gate-off/read-only 与 v2 capability；
   - browser/Tauri、响应式、键盘、reduced-motion、文档和父任务验收证据。

## 跨子任务冻结点

- Child 1 冻结 schema基座、public DTO/event、cursor、snapshot与dispatch job contract；后续 child 不私自重命名。
- Child 2 冻结 UI public exports、tokens、NOTICE/upstream mapping与test harness；Child 6只通过受控props/actions消费。
- Child 3 冻结 request/receipt identity、fresh-turn lineage、planning catalog、completion reason和error/events；Child 4不修改request authority。
- Child 4 冻结 Queue/Steer/Interrupt/resume/execute/Retry状态机与learner-safe errors；Child 5只负责切换，不重新定义正常运行语义。
- Child 5 冻结effective gate、cutover state、migration errors与legacy read/write边界；Child 6不从UI猜测protocol。
- 任一 child 发现必须改变默认Queue、fresh answer turn、blocking request、effect fail-closed、global cutover或DSH复用边界时，停止实施并回到父任务重新规划审批。

## 总体验证矩阵

### 后端与后台工作进程

```powershell
uv --directory .\aearn\services\api run python -m pytest tests/test_db_bootstrap.py tests/test_tutor_run_repository.py tests/test_tutor_run_loop.py tests/test_tutor_input_merge.py tests/test_tutor_conversation_history.py tests/test_tutor_sse.py tests/test_tutor_routes.py tests/test_tutor_effect_commit.py tests/test_worker_import.py -q
uv --directory .\aearn\services\api run ruff check app tests
uv --directory .\aearn\services\api run python -m mypy app
```

新增 focused suites 至少覆盖 conversation events、dispatch/reconcile、typed requests/receipts、Queue/control、Retry/effects、global cutover freeze/cancel/effect block/410 与 crash recovery。共享 PostgreSQL bootstrap 测试串行执行。

### Desktop 与集成验收

```powershell
pnpm --dir .\aearn\apps\desktop test
pnpm --dir .\aearn desktop:check
pnpm --dir .\aearn dev:status
git diff --check
```

使用本地 fake provider/fixture user 做 browser/Tauri smoke，不调用真实 provider、不执行生产迁移。覆盖 running默认Queue、Steer、Stop、resume、Retry、typed request、legacy migration card、gate-off/read-only、刷新/重连、1440/900/390、键盘与reduced-motion。

### Trellis

```powershell
python .\.trellis\scripts\task.py validate .trellis/tasks/08-13-tutor-thread-turn-item-event-foundation
python .\.trellis\scripts\task.py validate .trellis/tasks/08-14-dsh-derived-ui-foundation
python .\.trellis\scripts\task.py validate .trellis/tasks/08-14-tutor-typed-request-authority-turns
python .\.trellis\scripts\task.py validate .trellis/tasks/08-13-tutor-queue-steer-interrupt-control
python .\.trellis\scripts\task.py validate .trellis/tasks/08-14-tutor-thread-turn-v2-global-cutover
python .\.trellis\scripts\task.py validate .trellis/tasks/08-13-codex-like-tutor-desktop-migration-qa
python .\.trellis\scripts\task.py validate .trellis/tasks/08-13-codex-like-tutor-conversation-experience
```

## 高风险与回滚点

1. **Schema/sequence：** conversation sequence与control version必须在同一row lock下更新；异常时fail closed。
2. **Dispatch：** Redis/Celery丢失不能丢turn；PostgreSQL job/reconciler是恢复authority。
3. **Typed authority：** request/approval/receipt必须精确scope/version/hash；普通文本不能冒充。
4. **Queue：** claim与message/turn/job原子；不得留下pending与已创建turn双重状态。
5. **Run loop/effect：** stale provider、interrupt与retry effect不确定时禁止public/effect写入。
6. **Cutover：** preparing必须冻结legacy lease/write；ambiguous effect必须blocked，rollback不得重新开放旧mutation。
7. **Desktop：** backend gate未就绪时只显示unavailable/read-only，不fallback旧continuation。
8. **DSH reuse：** 不引入Cordis/runtime/DeepSeek品牌；derived source和MIT attribution必须完整。

## 完成门

- 六个 child 均归档，显式依赖、验收证据和 source-of-truth 更新完整。
- 默认 Queue、显式 Steer、fresh typed response turn、global cutover 与 Desktop 行为在 API、worker、Desktop 和 docs 中一致。
- 2026-08-13 clarification预算继承故障有回归测试，证明回答进入 fresh turn。
- DSH-derived UI 来源清晰且无 runtime/brand泄漏；无raw hidden reasoning/provider/prompt/diagnostic/secret泄漏。
- 父任务在最终 integration evidence 审核通过后才可 finish/archive。