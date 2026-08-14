# Tutor thread/turn v2 全局切换

## 目标

在 v2 runtime、typed request 与 Queue/control contract 全部冻结后，实现一次全局、原子、可审计的协议切换：冻结 legacy 写入和调度，立即终结可取消的 legacy 非终态 run，阻塞任何不明确 effect commit，统一关闭旧 continuation POST，并只在 preflight 证明安全后启用 v2 API、worker、reconciler 与 Desktop capability。

## 依赖与范围

- 依赖 `08-13-tutor-thread-turn-item-event-foundation`、`08-14-tutor-typed-request-authority-turns`、`08-13-tutor-queue-steer-interrupt-control` 完成归档。
- 不依赖 DSH UI foundation；Desktop integration 依赖本 child 冻结的 capability/error/migration-card contract。
- 本 child 实现 cutover 机制和自动化验证，不执行生产部署或不可逆数据删除。

## 范围内

- 数据库 singleton cutover state、advisory lock/generation、inventory/preflight/summary 与幂等操作。
- 有效 v2 gate：环境 kill switch `TUTOR_THREAD_TURN_V2_ENABLED` + DB state `enabled`。
- preparing 时冻结 legacy create/input/dispatch/lease acquisition。
- legacy 非终态分类终结、lease 清理、迟到写屏障、公开 migration error/event。
- 旧 `POST /api/tutor/runs/{run_id}/inputs` 的无副作用 HTTP `410 Gone` tombstone。
- legacy history、run detail、run-local SSE 只读保留。
- capability endpoint、operator CLI/service、dry-run/preflight、blocked recovery 与 rollback 规则。

## 范围外

- 按 user cohort 或 conversation 懒切换。
- 自动构造 legacy typed request、自动重放回答/批准、伪造 authority receipt。
- 强制跨过 `awaiting_effect_commit` 或不明确 effect receipt。
- 物理删除 legacy rows、route、SSE 或生产迁移执行。
- Desktop 最终视觉；由 integration child 完成。

## 需求

### R1：全局 cutover authority

- 新 singleton 记录 version、state=`idle|preparing|blocked|ready|enabled`、generation、summary hash、block code、timestamps 与安全 counts。
- operator 动作必须持有 PostgreSQL advisory lock 并以 generation/CAS 推进；并发调用幂等或明确冲突。
- runtime 有效 v2 状态为 env allow 且 DB state=enabled；DB state 是原子激活 authority，env 是 kill switch。

### R2：Preparing freeze

- 进入 preparing 后，legacy conversation/run create、普通 input、旧 continuation、dispatch wakeup、lease acquisition 和 reconciler 全部 fail closed。
- read routes 继续工作；旧 continuation POST 始终返回 `410 Gone + TUTOR_LEGACY_CONTINUATION_DISABLED`。
- freeze 与 inventory 共享数据库 authority，不能仅靠进程本地缓存。

### R3：Legacy 状态收口

- `legacy_v1 + waiting_for_input + non-terminal` 终结为 `failed`，内部诊断 `legacy_continuation_requires_new_turn`，公开 `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN`。
- `queued | leased | running | waiting_for_capability` 立即终结为 `cancelled`，内部诊断 `legacy_protocol_cutover`，清除 lease 并冻结公开 process；对外复用普通 `interrupted` 投影，不新增 cutover 专用错误码或卡片，也不等待 deadline。
- 不自动创建 typed request、answer turn、approval 或 authority receipt；历史消息/events/continuation kind 保留。
- 所有 terminal/event 写使用稳定 key，重复 cutover 不产生重复终态或事件。

### R4：Effect 安全阻塞

- 任一 `awaiting_effect_commit`、未决 action/effect receipt 或无法证明 scope/hash/result 的 row 使 cutover 进入 blocked。
- blocked 时 v2 不启用、legacy writes 仍冻结、read 继续；由 reconciler/operator 解决 receipt 后重新 preflight。
- 禁止超时后强制 cancel、假定成功或假定失败。

### R5：Preflight 与启用

- preflight 证明：schema/version 就绪、v2 worker/beat import 可用、无可写 legacy run、无 active legacy lease、无 ambiguous effect、旧 POST 无副作用 410、snapshot/history 可读、Desktop capability contract 匹配。
- 全部通过后写 ready；显式 enable 在同一 DB authority 中写 enabled 并产生安全审计记录。
- 不存在 per-user/per-conversation protocol selector。

### R6：Rollback 与可观测性

- rollback/kill switch 只关闭 v2 mutation/dispatch/drain 并进入 read-only unavailable；不得恢复 legacy mutation 或复活已终结 run。
- logs/summary 只记录 counts、IDs、state、duration 和 safe code，不记录 learner content/provider payload/secret。
- 物理删除 legacy route/data 必须另开任务。

## 验收标准

- [ ] 两个并发 cutover 调用只有一个 generation 推进；重复相同请求幂等，不同 summary/generation 冲突。
- [ ] preparing 后没有新 legacy run/lease/dispatch 穿透，旧 POST 对任意 run 稳定 410 且无 DB/service/dispatch 副作用。
- [ ] waiting rows 使用专用 recoverable migration error；其他可取消 active rows 只终结一次并公开为普通 `interrupted`，不出现 cutover 专用卡片，历史读取保持。
- [ ] 迟到 provider/capability 结果不能写 message/effect；active lease 被清除。
- [ ] ambiguous effect 使 cutover blocked 且 v2 不启用；receipt 明确后可安全重跑 preflight。
- [ ] env=false 或 DB 非 enabled 时 v2 API/worker/drain unavailable；两者满足且 enable 后所有用户统一进入 v2。
- [ ] rollback 不重新开放旧 write；focused pytest、bootstrap twice、worker import、Ruff、Mypy 和文档检查通过。

## 风险

- 这是协议切换安全边界，不能与普通 Queue 实现混成一个不可独立验证的发布步骤。
- 多进程环境只靠 env 无法原子切换，必须以 DB singleton 为 authority。
- effect 不确定性优先于可用性；blocked 是正确结果，不得为了完成切换而猜测。