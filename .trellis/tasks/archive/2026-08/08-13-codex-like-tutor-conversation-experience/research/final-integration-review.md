# 最终集成验收记录

## 结论

- 验收日期：2026-08-14。
- 分支：`codex/codex-like-tutor-conversation`。
- 工作目录：`E:\codee\Aearn-dsh-ui-reuse`。
- 六个 child 均已按冻结顺序完成并归档；父任务保持 coordination-only，未执行 `task.py start`。
- API、PostgreSQL authority、worker/reconciler、Desktop、全局 cutover、迁移边界、source-of-truth 与本地 QA 结果一致。
- 未发现需要变更冻结产品契约的 blocker。

## Child 完成证据

| 顺序 | Child | Work commit | Archive commit | Journal commit | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 | `08-13-tutor-thread-turn-item-event-foundation` | `b04898d9` | `0d6031af` | `a5fab034` | 已归档 |
| 2 | `08-14-dsh-derived-ui-foundation` | `555bc06f`、`c2e89987` | `49fb4140` | `c3926d15` | 已归档 |
| 3 | `08-14-tutor-typed-request-authority-turns` | `a1523e5f` | `90ad4a57` | `4e68d977` | 已归档 |
| 4 | `08-13-tutor-queue-steer-interrupt-control` | `6e768da8` | `0554563b` | `dfd6f408` | 已归档 |
| 5 | `08-14-tutor-thread-turn-v2-global-cutover` | `c7cd6724`、`a112f006` | `15dd9e19` | `e9717a03` | 已归档 |
| 6 | `08-13-codex-like-tutor-desktop-migration-qa` | `04b2b85d` | `d7ecb3ac` | `327ac71f` | 已归档 |

补充治理提交：`19dbd2e7` 迁移冻结任务树；`2dda894b`、`533d1dcc`、`e505a688` 校正 Trellis 完成日期。

## 契约验收

### Conversation / Turn / Item / Event 与持久调度

- conversation-global sequence、opaque cursor、snapshot、public event 与 durable dispatch job 均由 PostgreSQL 记录承担权威。
- Celery 只作为 wakeup；worker/reconciler 使用 lease/CAS 恢复 pending 或 lease-expired job。
- run-local history/detail/SSE 保留只读兼容，新 Desktop 不再依赖 run-local SSE。

### Typed request 与 fresh authority turn

- clarification、planning input、approval 使用精确 request/item identity 与 version。
- capability/external result 仅由受信 authority receipt 解决。
- request response 创建不同 fresh turn/job/budget，不恢复来源 turn 的 deadline/counters/lease。

### Queue、Steer、Interrupt、Retry

- active Send 默认 Queue；容量固定为 10；编辑、删除、完整顺序重排均使用 control/item CAS。
- Steer 使用精确 active turn 与 input revision，共享当前预算；stale 状态 fail closed，不隐式 Queue。
- Interrupt 产生 learner-safe `interrupted` 并暂停 Queue；resume/execute 使用独立 mutation。
- “中断并执行”在 active turn 存在时保持可用，后端原子 interrupt 当前 turn 并 fresh-claim 指定 Queue 项。
- Retry 创建 fresh lineage；effect receipt 已提交时复用，歧义时 fail closed。

### 全局 v2 cutover 与 legacy 边界

- env kill switch 与数据库 singleton `enabled` 同时满足才开放 v2。
- preparing 冻结 legacy create/dispatch/lease；waiting row 迁移为 recoverable fresh-turn error；其他可取消 active row 对外投影普通 `interrupted`。
- ambiguous effect 阻塞 cutover；rollback 不重新开放旧 continuation。
- `POST /api/tutor/runs/{run_id}/inputs` 为永久 `410 Gone` tombstone，无数据库副作用。
- 本次只验证机制，未执行生产 cutover。

### Desktop 与 DSH-derived UI

- Desktop 使用 snapshot-first + conversation-global SSE；event 只触发节流 snapshot refresh。
- opaque cursor 原样发送；重复 sequence 忽略；gap/cursor invalid/协议错误重新读取快照。
- pending typed request 完全占用 composer seat；authority request 为只读等待。
- timeline 不渲染独立 process；`Think` 只来自 Tutor message 的 `public_thinking_steps[]`。
- running Send 进入 Queue；Steer、Stop、Retry、resume、立即执行均为显式操作。
- gate-off 显示只读 unavailable，不回退到 `/runs/{run_id}/inputs`。
- 受保护原型 `docs/design/learning-agent-claude-desktop-framework.html` 未修改或替换。
- DSH-derived primitives/tokens 保持 Aearn 品牌与 MIT/upstream 映射，不引入 Cordis、DSH runtime/session 或 DeepSeek 品牌运行依赖。

## 最终质量门

### 后端与 worker

- 完整 API：`569 passed, 1 skipped`。
- 父任务 focused backend/worker 矩阵：`49 passed`。
- Ruff：通过。
- Mypy：`172 source files`，无问题。
- `uv lock --check`：解析 `54 packages`，通过。
- `compileall app tests`：通过。

### Desktop 与本地集成

- Vitest：`5 test files / 21 tests passed`。
- `pnpm --dir .\aearn desktop:check`：TypeScript 与 Vite production build 通过。
- `pnpm --dir .\aearn dev:status`：PostgreSQL、Redis healthy；API/Desktop 已停止，无残留 tracked PID。
- Browser/Tauri fixture：snapshot-first timeline、公开 Think、process 隐藏、running Queue、Queue edit/reorder/delete/Steer/execute、Stop、键盘发送、390×844、900×900 与 1440×900 无横向溢出、reduced-motion、SSE 断线错误与恢复后重连、console error 为 0。
- typed request composer-seat 与 exact request version 由 Desktop component test 和 API request suite 覆盖；本地 fake dispatcher fixture 不作为真实 provider 或发布批准证据。

### Trellis 与 diff hygiene

- 六个 archived child 与父任务的 `task.py validate` 全部通过。
- `git diff --check` 通过。
- 所有 child `completedAt`、journal 日期和索引日期归一为 `2026-08-14`。

## 未执行事项与剩余风险

- 未调用真实 provider。
- 未执行生产 cutover、生产迁移、部署、push 或生产数据修改。
- 未运行需真实外部授权的 capability/provider smoke。
- 本地 Browser/Tauri 使用 disposable fixture；它证明 UI/契约集成，不等同于真实模型质量或生产 release approval。
- blocker：无。
