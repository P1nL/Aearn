# 实施计划

## 实施前总门槛

- [ ] 当前工作目录必须是 `E:\codee\Aearn-dsh-ui-reuse`，分支为 `codex/dsh-ui-reuse`。
- [ ] 父任务保持 `planning`，只启动当前要实施的 child；不得启动父任务。
- [ ] 加载 `trellis-before-dev`，读取当前 child 的 `prd.md`、`design.md`、`implement.md`、相关 `.trellis/spec/` 和 parent research。
- [ ] 检查 `E:\codee\Aearn` 原始工作树 dirty state；只记录当前 child 重叠 diff，不覆盖或撤销用户修改。
- [ ] 确认固定 DSH checkout revision 仍为 `47f943859bef60e4160492346772ded9b24f765a`。

## 执行顺序

### Child 1：DSH-derived UI foundation

- [ ] 创建白色浅色 `--aearn-*` tokens 与内部 DSH compatibility alias。
- [ ] 派生选定 primitives、所需非品牌 icons 和 CSS modules。
- [ ] 使用现有 sonner 建立 DSH 外观 toast adapter，不创建第二套全局通知 runtime。
- [ ] 增加 `THIRD_PARTY_NOTICES.md`、`UPSTREAM.md` 和逐文件来源注释。
- [ ] 增加 Vitest/Testing Library/jsdom 及 primitive/accessibility 测试。
- [ ] 运行 child 验证并 archive 后再进入 Child 2。

### Child 2：受控 pending input

- [ ] 对照原始工作树 continuation/prompt diff，语义移植 `clarification` / `planning_input`，保留用户已做的 prompt 安全修改。
- [ ] 新增 `tutor_run_pending_inputs` schema、repository 和 public projection。
- [ ] 新增七字段 question catalog/template 和 unknown/reask fail-closed。
- [ ] 扩展 run/history/API/Desktop types 为 additive `pending_input` contract。
- [ ] typed answer 增加 pending identity + expected revision，原子 resolve 并恢复 run。
- [ ] 更新相关 skill/provider prompts，加入正例、反例和边界示例；测试 enum 不混用。
- [ ] 运行 child 验证并 archive 后再进入 Child 3。

### Child 3：Persistent Queue + Stop

- [ ] 新增 queue table、indexes、constraints、cutover/export/reset 分类。
- [ ] 扩展 conversation input `delivery_mode`，保留缺省 legacy behavior。
- [ ] 实现 queue list/edit/delete/steer API、幂等、版本和 20-item bound。
- [ ] 实现 queue drain coordinator、completed auto-advance、failure/stop pause 和 next-send wake。
- [ ] 将 Steer 接入现有 input revision/safe-boundary fencing。
- [ ] 新增 run cancel service/route，复用 `request_cancellation()` 并限制 cancellable statuses。
- [ ] 增加 Queue SSE/history projection 和 replay/reconnect 测试。
- [ ] 运行 child 验证并 archive 后再进入 Child 4。

### Child 4：Tutor UI integration

- [ ] 将 `TutorConversationSurface` 拆为 controlled Composer、QueueDock、QuestionComposer、ThinkRow 和 PlanReviewPanel。
- [ ] 移除 continuation 提示卡/手动 mode 切换；pending input 完全接管 Composer。
- [ ] 普通 Composer 默认 Queue delivery，active run 显示 stop；正确处理 queued/queued_and_woke/started 响应。
- [ ] 忽略 process timeline renderer，只在 message `public_thinking_steps[]` 非空时显示 `Think`。
- [ ] 保留右侧浮动 plan inspector，替换内部 DSH card/strip/body/footer/actions 视觉。
- [ ] 迁移 Tutor CSS 到 modules；确认 legacy rules 无引用后再窄范围清理。
- [ ] 更新六份正式 source-of-truth 文档和 acceptance matrix。
- [ ] 完成 component tests 与 1440/900/390 浏览器验证。

## 子任务完成后的父级集成复核

- [ ] 全量检查 Child 1-4 API/types/state data flow，没有重复 authority 或隐式格式假设。
- [ ] 核对普通 first turn、existing conversation、active Queue、Typed Question、stop、paused Queue wake、plan approval 全链路。
- [ ] 核对旧客户端不带 `delivery_mode` 时仍走 latest-input-wins compatibility。
- [ ] 核对旧 history/process/pending-input-absent fixtures 可读取。
- [ ] 核对原始工作树重叠修改均已保留或有明确不移植理由。
- [ ] 搜索 DeepSeek 品牌、Cordis/runtime import、raw reasoning/trace/hidden-test 泄漏。

## 验证命令

每个 child 先运行最小相关命令；Child 4 和父级集成运行完整矩阵：

```powershell
# Backend focused examples
uv --directory .\aearn\services\api run python -m pytest tests/test_tutor_routes.py tests/test_tutor_run_repository.py tests/test_tutor_run_loop.py tests/test_tutor_sse.py tests/test_learning_plan_sessions.py tests/test_db_bootstrap.py -q
uv --directory .\aearn\services\api run ruff check .
uv --directory .\aearn\services\api run python -m mypy app
uv --directory .\aearn\services\api lock --check

# Desktop
pnpm --dir .\aearn\apps\desktop test
pnpm --dir .\aearn desktop:check

# Full backend integration after Child 4
uv --directory .\aearn\services\api run python -m pytest

# Planning/docs/diff hygiene
python .\.trellis\scripts\task.py validate .\.trellis\tasks\08-13-deepseek-harness-ui-reuse
python .\.trellis\scripts\task.py validate <current-child-path>
git diff --check
```

如果实际新增测试文件，应把它们加入 focused command；不得为了让命令通过而删除 P0 queue/pending-input/cancel coverage。

## 浏览器验收

- [ ] 启动本地 fake/stateful API 与 Desktop Vite，不调用真实 provider。
- [ ] 1440px：白色主面、中心 timeline、sticky Composer、右侧浮动 plan inspector 均可用。
- [ ] 900px：Queue 与 Composer 不溢出，plan inspector 不挤压主列。
- [ ] 390px：单列、底部浮动 inspector、Question pager、Queue actions、stop target 可触达。
- [ ] 键盘：Tab/Shift+Tab、Enter、Shift+Enter、Escape edit、radio/checkbox、visible focus。
- [ ] IME：composition Enter 不发送普通消息、不翻页、不提交 Queue edit。
- [ ] reduced motion：关闭非必要 transition/animation 后信息和状态仍完整。
- [ ] console 无 error/warning，页面无 Vite error overlay、horizontal overflow。

## 高风险文件与回滚点

- `aearn/services/api/app/db/schema.sql`：只 additive；bootstrap twice 与 cutover inventory 是硬门。
- `aearn/services/api/app/services/tutor/persistence.py`：conversation/run lock order、queue claim、cancel/write fence 不得改变既有安全顺序。
- `aearn/services/api/app/services/tutor/public_api.py` 与 `routes/tutor.py`：旧 response 和 idempotency 兼容必须保留。
- `aearn/services/api/app/services/tutor/run_loop.py`：Steer/revision/cancel 检查不得绕过 provider/effect stale fencing。
- `aearn/apps/desktop/src/api.ts`、`types.ts`、`TutorConversationSurface.tsx`：与原始 dirty worktree 重叠，修改前后必须逐文件 diff。
- `aearn/apps/desktop/src/styles.css`：不做大范围重写；先新增 modules，确认引用为零再删除旧规则。

## 明确不运行

- [ ] 不运行真实 provider smoke，除非用户另行明确批准。
- [ ] 不启动或批准生产 container fleet。
- [ ] 不部署、不修改生产数据、不提交或 push，除非用户在实施阶段另行要求。
- [ ] 不对原始工作树执行 reset/clean/checkout 覆盖。
