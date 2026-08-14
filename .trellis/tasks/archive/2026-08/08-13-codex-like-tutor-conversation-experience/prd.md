# 复刻 Codex 对话运行体验

## 目标与用户价值

将 Aearn Tutor 从“有限 run 可能跨多次用户往返并共享累计预算”的交互模型，升级为接近 Codex 的持久化 conversation/thread、独立 turn、稳定 item/event 和明确控制操作。学习者应能连续表达需求、在运行中默认排队后续消息、显式引导或停止当前处理、准确回答 Tutor 的结构化问题、从失败中重试，并在刷新或断线后恢复同一权威时间线。

本任务复刻的是 Codex 的交互语义与状态边界，不复制品牌、文案、像素外观，也不把 Shell、Git、patch、workspace 等 coding-specific 能力引入教学产品。

## 背景与已确认事实

- `TutorConversation` 已承担持久化会话范围，`TutorRun` 是当前有限执行单元。
- 普通 conversation input 已可创建 fresh run，但 `/runs/{run_id}/inputs` 会把 `clarification`、`planning_input` 等回复合并回同一个 `waiting_for_input` run，并继承旧 deadline、`model_call_count` 与其他累计预算。
- 2026-08-13 的实际故障 run `1a24887e-41b7-4a06-a38e-cc85e4865bd8` 在第三次模型调用后以 `model_call_budget_exhausted` 结束，前端显示 `TUTOR_RUN_UNAVAILABLE`；根因是一次追问往返复用了旧 run 的有限预算，而不是 transport/schema 故障。
- 当前 Desktop 只订阅 active run 的 run-local SSE，事件类型有限，composer 只有 `ordinary | continuation`，没有 Queue、Steer、Interrupt 或关联原 turn 的 Retry 契约。
- 当前路由通过 FastAPI `BackgroundTasks` 在 HTTP commit 后启动 run；它不是浏览器断开、API 重启或 worker 崩溃后的持久调度权威。
- Codex 源码基线采用 `Thread -> Turn -> Item`，并区分 `turn/start`、带 `expected_turn_id` 的 `turn/steer`、Queue、`turn/interrupt` 与精确 request/item identity 的用户输入/approval 响应。证据见 `research/codex-conversation-baseline.md`。
- Aearn 当前差距与源码锚点见 `research/aearn-conversation-gap.md`。
- 独立 worktree `E:\codee\Aearn-dsh-ui-reuse` 中存在 `08-13-deepseek-harness-ui-reuse` 规划树，固定审计 `deepseek-ai/deepseek-harness` MIT revision `47f943859bef60e4160492346772ded9b24f765a`，其可复用价值集中在 React/CSS、UI primitives、Composer、QueueDock、QuestionComposer、PlanReviewPanel 与测试矩阵，不应引入 Cordis/plugin/runtime。
- 两棵任务树目录均被 `.gitignore` 忽略，普通 `git merge` 不会自动合并。2026-08-14 复核时 `main` 为 `2cb7f2095444ad3f7e6d7d21c6fa59a248def2fc`，`codex/dsh-ui-reuse` 为 `a4f832dca0aed179ff6a054c2c280d698b2e84ba`；DSH 分支可 fast-forward 到 `main`。

## 已确认产品决策

1. **运行中普通输入默认 Queue。** 输入先持久化到服务端队列，当前 turn 不被隐式改变，也不被自动 supersede。
2. **Steer 是显式次级操作。** 它只投递给仍是当前 active 的精确 turn；stale 或 mismatch 必须拒绝，不能静默改为 Queue 或投递给新 turn。
3. **普通下一轮、Queue、Steer、Interrupt、Retry、elicitation response 与 approval response 使用不同 mutation contract。** 前端不得根据一段普通文本猜测语义。
4. **`clarification`、`planning_input`、`approval` 使用 typed item/request。** 用户回答精确关联 item/request，但会创建 fresh turn 与 fresh budget；旧 turn 不恢复累计预算。
5. **`capability_result`、`external_result` 是服务端 authority receipt 唤醒。** 它们不进入普通 learner composer。
6. **Queue 是服务端持久状态。** 关闭页面、SSE 断线或 HTTP 请求结束后仍可恢复；只有正常 `completed` 才自动出队，主动 Stop/Interrupt 或失败会保留并暂停 Queue。
7. **不公开隐藏推理。** 只展示专门生成且经 allowlist/redaction 的计划、过程摘要、受控动作、验证和终态。
8. **Codex-like runtime 契约是唯一产品与后端权威。** Thread/Turn/Item/Event、fresh budget、Queue/Steer/Interrupt、typed request、durable dispatch、Retry 与副作用安全均以本任务树为准。
9. **DSH 仅作为 UI 源码、交互细节和测试矩阵来源。** 允许从固定 MIT revision 派生 Aearn-owned React/CSS、semantic tokens、primitives 与 controlled Tutor components，但不得让 DSH Queue、pending-input、session 或 runtime 语义覆盖 Aearn authority。
10. **两棵任务树合并为一棵主树实施。** 保留当前父任务作为唯一协调父级；迁入 DSH-derived UI foundation，重写冲突工件，并在信息核对完成后将分支中的重复规划标记为 superseded。
11. **Stop/Interrupt 后 Queue 保留并显式暂停。** 正常 `completed` 是唯一自动 drain 终态；用户主动停止后不得自动启动下一项，也不得把下一次普通 Send 隐式解释为恢复。Desktop 提供明确的“继续队列”操作；Queue “立即执行”仍是显式 interrupt + claim 指定项。
12. **Desktop 只显示 message-level `Think`，不渲染独立 process timeline row。** `Think` 仅消费成功 Tutor message 上经安全校验的 `public_thinking_steps[]`；服务端继续保留 `TutorPublicProcess` authority、事件和历史兼容投影，用于生命周期、恢复、审计和测试，但新 Desktop 不展示其 steps、duration 或 terminal card。
13. **MVP Queue 容量固定为每个 conversation 最多 10 条 pending item。** 单条继续限制 16,000 字符，超限返回 recoverable `TUTOR_QUEUE_FULL`；首轮不增加环境可配置容量，权威 snapshot 返回 `pending_count` 与 `max_pending=10`，Desktop 显示 `n/10`。
14. **首轮完整支持 Queue 编辑、删除、稳定重排、Steer 与“立即执行”。** 重排使用键盘可达的上移/下移，不要求拖拽；Steer 将选中项投递到当前 turn 并共享剩余预算，“立即执行”则 interrupt 当前 turn、claim 选中项并创建 fresh turn。两者必须使用不同 mutation、确认文案和 stale/version 检查。
15. **Required Typed Question 完全接管 Composer。** pending `clarification`、`planning_input` 或 approval 时不并列显示普通 Composer、QueueDock、skip 或 close；回答使用精确 item/request identity。退出整个规划仍使用页面级取消，已有 Queue 只在后台保留并保持暂停。
16. **选定 DSH Tutor surfaces 采用近像素派生，但保持 Aearn 产品身份。** 首轮为白色浅色主题、Aearn 绿色 semantic tokens；近像素复用 Composer、QueueDock、QuestionComposer、`Think` disclosure 与 PlanReviewPanel 内部结构，不复制 DeepSeek 品牌或 DSH runtime。计划草案继续使用右侧浮动 inspector，窄屏改为底部浮层。
17. **实施复用现有 `E:\codee\Aearn-dsh-ui-reuse` worktree。** 最终规划获批后、任何 child `task.py start` 前，先将其本地分支 fast-forward 到最新 `main`，再把分支重命名为 `codex/codex-like-tutor-conversation`；随后迁入合并后的唯一 Trellis 树。`E:\codee\Aearn` 保持干净基线，旧 DSH 规划在完成信息核对前不删除。
18. **v2 cutover 立即禁用旧 continuation 写入。** 从 v2 contract 生效时起，`POST /api/tutor/runs/{run_id}/inputs` 对新旧 run 一律拒绝，返回 HTTP `410 Gone` 与稳定 learner-safe code `TUTOR_LEGACY_CONTINUATION_DISABLED`；旧 history、run detail 与 run-local SSE 继续只读可访问。新 Desktop 不保留 silent fallback，也不能通过旧入口恢复共享预算的 `waiting_for_input` run。
19. **cutover 统一终结所有 unresolved legacy `waiting_for_input` run。** 迁移在 conversation/run 锁下将其终结为 `failed`，内部诊断为 `legacy_continuation_requires_new_turn`，公开映射为 recoverable `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN`；保留旧消息、事件、continuation kind 与只读 SSE，不自动创建 v2 typed request、不重放回答、不自动批准或伪造 authority receipt。学习者下一次普通 Send 创建 fresh v2 turn。
20. **thread/turn v2 采用一次全局原子 cutover，不按 user 或 conversation 灰度。** additive schema、API、worker、reconciler 与 Desktop 先在 effective gate 未启用时部署和验证；`TUTOR_THREAD_TURN_V2_ENABLED` 是环境 kill switch，数据库 cutover singleton 的 `state=enabled` 是原子 authority，两者同时满足才开放 v2。gate-off 只允许 legacy history/read 与明确 unavailable，不重新开放旧 continuation mutation；现有 `harness_cutovers(user_id, ...)` 继续只负责旧 Graph→Tutor 产品切换，不承载 v2 protocol cohort。
21. **全局 cutover 不等待普通 legacy run drain，立即取消所有可取消的非终态 run。** cutover 进入 preparing 后先冻结新的 legacy turn/dispatch/lease，再将 `queued | leased | running | waiting_for_capability` 原子终结为 `cancelled`，内部诊断 `legacy_protocol_cutover`，清除 lease并依赖写屏障丢弃迟到结果；`waiting_for_input` 仍按决策 19 终结为 recoverable `failed`。任何 `awaiting_effect_commit` 或 effect receipt 不明确的 run 都必须阻塞并中止 cutover，禁止强制取消或带歧义启用 v2。
22. **合并后的唯一任务树固定为六个可独立验证的 child。** Runtime foundation 与 DSH UI foundation 分离；typed request/authority fresh turns、Queue/control/retry、global cutover 与 Desktop integration 各有独立 ownership。依赖写入每个 child 的 `task.json`、PRD 与实施门，不依赖列表位置暗示；global cutover 不再埋入 Queue child。
23. **因 global cutover 取消的 active legacy run 对外显示普通 `interrupted`。** 内部继续记录 `legacy_protocol_cutover` 供审计，但 public item/event、timeline 与控制状态复用用户 Stop 的 `interrupted` 投影；不新增专用迁移错误码或卡片，不自动 Retry、不自动创建 fresh v2 turn。`waiting_for_input` legacy row 仍按决策 19 使用专用 recoverable 迁移卡。

## 范围内

- 定义 Aearn `Conversation/Thread -> TurnRun -> TutorPublicItem` 的稳定外部模型与内部权威关系。
- 建立 conversation-level、持久化、单调有序、可重放的公开事件流及 snapshot/cursor 契约。
- 建立持久化 interactive dispatch job、Celery 唤醒与周期 reconciler；PostgreSQL 是权威，Redis/Celery 不是状态源。
- 实现默认 Queue、显式 Steer、Interrupt、Retry、Queue 编辑/重排/删除/立即执行和确定性并发控制。
- 将 `clarification | planning_input | approval | capability_result | external_result` 从旧 run-input merge 迁移到 typed blocking item/authority receipt + fresh turn。
- 调整 run loop 的 stale revision、interrupt、effect/capability/public-message 屏障与 learner-safe 终态映射。
- 重构 Desktop Tutor 时间线、message-level `Think` disclosure、composer、Queue 区、停止/重试/回答请求及历史恢复；后端 process authority 保留但不作为新 Desktop timeline row。
- 建立 Aearn-owned DSH-derived UI foundation：固定 revision、MIT NOTICE/upstream mapping、白色浅色 semantic tokens、低耦合 primitives、所需非品牌图标、controlled Tutor components 与组件测试基础。
- 保留旧 history、run detail 与 run-local SSE 的有界只读兼容窗口；cutover 时立即禁用旧 continuation mutation，将 unresolved legacy `waiting_for_input` run 统一终结为可恢复失败，并要求学习者以普通 fresh v2 turn 继续，不删除历史 Tutor 数据。
- 同步 PostgreSQL、API、worker、SSE、Desktop、source-of-truth 文档和端到端验收。

## 范围外

- 复制 Codex 商标、品牌文案、完整布局或像素视觉。
- 新增任意 Shell、文件 patch、Git、通用 coding workspace、worktree、多 agent 或远程执行能力。
- 引入 Cordis、DSH plugin/runtime/session/slot dependency、DeepSeek 品牌资产，或让 DSH 的运行状态机成为 Aearn 产品权威。
- 更换模型供应商、取消 Tutor Harness 有限预算、capability/effect policy、审批、隐私与 learner scope。
- 暴露 raw chain-of-thought、provider payload、prompt、trace、内部 diagnostics、hidden tests、secrets 或受控 DSL/template 的内部验证细节。
- 生产部署、不可逆数据删除或未经单独批准的生产迁移执行。
- 在此父任务中直接实施业务代码；父任务只负责跨子任务契约和最终验收编排。

## 功能需求

### R1：Conversation、Turn 与 Item 分层

- `TutorConversation` 是持久化 thread，保存长期上下文、控制版本、公开事件序列、active turn、阻塞 item 与 Queue 摘要。
- 每条 idle 状态下的普通学习者输入创建新 `TutorRun`/turn，拥有 fresh deadline、model/capability/effect 预算与独立终态。
- 外部 turn 状态收敛为 `in_progress | completed | interrupted | failed`；等待输入/批准由 pending typed item 和 conversation control state 表达，不再把新协议 run 长期留在 `waiting_for_input`。
- `TutorPublicItem` 是 learner-safe union，至少覆盖 `message | process | elicitation | approval | error`；稳定 ID 来自权威 message/process/request/error 记录，不要求客户端合成。

### R2：统一公开事件与恢复

- 每个 conversation 有单调递增的 public event sequence；同一 mutation 内在 conversation 行锁下分配，`event_key` 幂等去重。
- conversation SSE 支持 `after` cursor/sequence 续传，事件至少覆盖 turn started/completed、item started/updated/completed、queue changed、control state changed 与 recoverable error。
- snapshot/history 返回当前 control state、active turn、pending blocking item、Queue 和稳定 timeline projection；页面刷新后结果与 live stream 收敛一致。
- run-local SSE 在兼容窗口内只读保留，但新 Desktop 只依赖 conversation stream。

### R3：默认 Queue

- active turn 存在时，普通 Send 默认创建 pending Queue item，不改变 active turn input revision。
- Queue item 在被 claim 前不进入正式 learner message timeline；被 claim 时原子创建 learner message、fresh turn、input event 和 dispatch job，避免重复文本。
- Queue 最多保留 10 条 pending item，每条沿用 16,000 字符上限；超限返回 recoverable `TUTOR_QUEUE_FULL`。
- Queue 支持编辑、删除、稳定重排、Steer 和“立即执行”。重排使用完整 pending ID 顺序与 expected control version；Steer 进入当前 turn input revision并共享预算；“立即执行”显式 interrupt 当前 turn 后 claim 指定 item创建 fresh turn。pending blocking item 存在时两者均不得绕过。
- active turn 正常 `completed` 后，若 conversation 无 pending blocking item 且 Queue 未暂停，服务端自动 claim 队首并创建下一 fresh turn；该行为不依赖浏览器在线。`interrupted` 或 `failed` 不自动 drain。

### R4：显式 Steer 与 Interrupt

- Steer mutation 必须携带 `expected_turn_id`、`expected_input_revision` 与幂等键，仅当前 interactive active turn 可接受。
- Steer 复用现有 input revision/latest-input-wins 屏障并共享当前 turn 剩余预算；provider 旧 revision 返回后不得写消息、执行 capability 或提交 effect。
- stale/mismatch/terminal/waiting-request 状态返回稳定 conflict；不得 fallback 到 Queue。
- Interrupt 必须携带精确 active turn 与 control version，形成 learner-safe `interrupted` 终态；终态后不得产生新的公开回复或副作用，并将现有 Queue 标记为显式暂停。恢复 Queue 使用独立 mutation。

### R5：Typed Elicitation、Approval 与 Authority Receipt

- `clarification` 和 `planning_input` 生成 typed elicitation item；`planning_input` 必须携带受控 `question_key`，回答只接受对应 schema 的字段。
- `approval` 生成 typed approval item，绑定安全 action proposal identity；approve/deny 通过精确 item ID 和版本提交。
- 产生 blocking item 后，来源 turn 以公开 `completed` 状态和安全 completion reason（`awaiting_user | awaiting_approval | awaiting_authority`）形成可审计终态，conversation control state 进入 waiting；回答后创建 fresh turn，数据库关联具体 request ID，公开投影以 `in_reply_to_item_id` 关联来源。
- `capability_result` 与 `external_result` 只能由受信 authority receipt 写入，验证来源、hash、scope 和幂等后创建 fresh turn；learner composer 不提供这两类选择。
- blocking item 未解决时 Queue 保留但不自动出队；取消/回答/authority receipt 解决后才可继续 drain。

### R6：持久化调度与恢复

- 创建 fresh turn 的事务同时创建唯一 dispatch job；不得只依赖 FastAPI `BackgroundTasks`。
- worker 通过 PostgreSQL lease/CAS 和 `FOR UPDATE SKIP LOCKED` claim job；Celery task 只是低延迟 wakeup。
- 周期 reconciler 重新发现 pending、lease-expired 和 terminal 后可继续的 Queue，确保 API/worker crash 后恢复。
- dispatch 与 queue drain 的每一步均幂等；同一 run 最多形成一个 active dispatch authority，重复 wakeup 不重复 provider/effect。

### R7：失败、Retry 与副作用安全

- learner-safe 错误至少区分模型暂不可用、turn 预算耗尽、调度延迟、stale mutation、Queue 已满、用户中断与不可恢复内部失败。
- recoverable failure 提供 Retry；Retry 创建新 turn、fresh budget，并记录 `retry_of_turn_id` / retry root lineage。
- retry lineage 中的 effect 使用稳定 logical action key 查询/复用 authority receipt；已提交 effect 不得因新 turn ID 再执行。
- 若 effect 状态不可证明安全，Retry fail closed 并要求显式恢复，不伪造成功。

### R8：Codex-like Desktop 体验

- timeline 以 learner/tutor message 为主；Tutor message 仅在 `public_thinking_steps[]` 非空时显示可折叠 `Think`，不渲染独立 process row。`Think` 只包含服务端安全校验的公开说明，不读取 raw reasoning、trace 或 run-level process steps。
- running 时主 Send 行为为 Queue，composer 附近明确显示“将加入队列”；Steer 通过显式次级菜单/按钮触发，不依赖隐藏快捷键。
- Queue 区固定在 composer 上方，支持键盘可达的编辑、上移/下移、删除和立即执行，不能只依赖拖拽。
- running 显示 Stop；Stop 后若 Queue 非空则显示“继续队列”；failed 显示 Retry；pending elicitation/approval 时 Required Typed Question 完全接管 Composer，不显示普通 Queue/Steer/Send、skip 或 close。
- SSE 状态变化无需刷新；刷新、重连、切换 conversation 后由 snapshot + cursor 恢复同一 active turn、pending request、Queue 和 timeline。

### R9：兼容、安全与可观测性

- 新 run 带明确 protocol version；新协议不再创建 `waiting_for_input` continuation run。
- v2 cutover 后，旧 `POST /runs/{run_id}/inputs` 对所有 run 返回 HTTP `410 Gone` + `TUTOR_LEGACY_CONTINUATION_DISABLED`；旧 history、run detail 与 run-local SSE 仅只读保留，不能让任何客户端回退到旧预算模型。
- cutover inventory 中所有 `legacy_v1 + waiting_for_input + non-terminal` run 必须幂等终结为 `failed`，内部诊断 `legacy_continuation_requires_new_turn`，公开错误 `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN`；不得根据不完整的 `continuation_kind` 自动合成 typed request、approval 或 authority receipt。
- v2 protocol 使用 env kill switch + DB singleton enabled 的全局 effective gate，不复用或扩展现有 per-user Harness cutover receipt；同一运行环境不得同时接受 v1 continuation mutation 与 v2 thread/turn mutation，也不得按 conversation 懒迁移。
- cutover preparing 必须先冻结 legacy 新建/dispatch/lease，再立即取消 `queued | leased | running | waiting_for_capability`；`awaiting_effect_commit` 或 effect receipt 歧义是硬阻塞，必须由 reconciler/operator 证明 committed/failed 后重新运行 preflight，不得超时后强行跨过。
- 上述 active legacy cancellation 的内部诊断 `legacy_protocol_cutover` 不进入专用公开错误；外部统一投影为普通 `interrupted`，与用户 Stop 共用 UI 和控制语义，且不触发自动 Retry/重放。
- trace 必须关联 conversation、turn、input revision、item/request、queue item、dispatch job、provider receipt、capability/effect 与 public event，但公开 API 仅返回安全 ID/枚举/摘要。
- 所有 mutation 采用 idempotency key 与 expected identity/version；任何 stale 状态都明确拒绝。

## 验收标准

- [ ] 连续完成至少三组“学习者提问 → Tutor typed 追问 → 学习者回答”的往返；每次回答创建不同 turn ID 和 fresh budget，不再复现 `model_call_budget_exhausted` 继承问题。
- [ ] active turn 期间连续发送三条普通消息时，三条均按顺序进入服务端 Queue，当前 turn ID/input revision 不变；刷新页面后 Queue 仍一致。
- [ ] 当前 turn 正常 `completed` 后，即使 Desktop 已断开，worker/reconciler 仍会按顺序为队首创建 fresh turn；主动 Interrupt 或失败后 Queue 保留且不自动执行，显式“继续队列”后才恢复；重复 wakeup 不创建重复 turn/message/provider call。
- [ ] 显式 Steer 只作用于精确 active turn；stale `expected_turn_id` 或 revision 返回 conflict，且消息既不进入新 turn也不被静默 Queue。
- [ ] Interrupt 后旧 turn 不再写公开 Tutor message、dispatch capability 或提交 effect，公开状态为 `interrupted`。
- [ ] clarification、`planning_input`、approval、capability/external result 均通过精确 item/receipt identity；普通聊天输入不能冒充响应。
- [ ] pending blocking item 会暂停 Queue 自动出队并由 Required Typed Question 完全接管 Composer；解决后才可继续。Queue edit/delete/reorder/Steer/立即执行在 stale control version 下拒绝且不部分写入，运行中“立即执行”会显式 interrupt 后启动指定 fresh turn。
- [ ] recoverable failure 可 Retry 为 fresh turn，关联原 turn；已提交 effect 不重复，状态不确定时 fail closed。
- [ ] conversation SSE 断线重连和页面刷新不会重复 timeline item、丢失 Queue/pending request 或错配 turn 终态。
- [ ] v2 cutover 后，旧 `POST /runs/{run_id}/inputs` 对 legacy 与 v2 run 均稳定返回 HTTP `410 Gone` + `TUTOR_LEGACY_CONTINUATION_DISABLED`，且不会修改 run、message、input event、预算或 dispatch 状态；旧 history/run detail/run-local SSE 仍可只读查看。
- [ ] 所有 unresolved legacy `waiting_for_input` run 经重复执行 cutover migration 后均只终结一次，公开显示 `TUTOR_LEGACY_CONTINUATION_REQUIRES_NEW_TURN`；旧消息/事件仍可读，不生成 typed request/answer turn/approval/authority receipt，后续普通 Send 创建 fresh v2 turn。
- [ ] `TUTOR_THREAD_TURN_V2_ENABLED=false` 或 DB cutover state 非 `enabled` 时，v2 writes/worker drain 明确 unavailable 且旧 continuation write 仍为 `410 Gone`；preflight 通过后由 DB authority 一次全局启用 API、worker、reconciler 与 Desktop v2，不存在按 user/conversation 混合协议流量。
- [ ] cutover preparing 后没有新的 legacy run、lease 或 dispatch 被接受；所有 `queued | leased | running | waiting_for_capability` legacy run 被幂等取消并清除 lease，迟到 provider/capability 结果无法写公开消息或 effect；存在 `awaiting_effect_commit`/歧义 receipt 时 cutover 保持 blocked 且 v2 不启用。
- [ ] cutover 取消的 active legacy run 在 public snapshot/event/Desktop 中与用户 Stop 一样显示 `interrupted`，不出现专用 cutover 错误卡、不自动 Retry或创建turn；内部 trace仍可按 `legacy_protocol_cutover` 审计。
- [ ] Desktop 主 Send 在 running 时默认为 Queue，并提供可见、可访问的 Steer/Stop/Retry/请求回答操作；timeline 只显示 message-level `Think`，不显示独立 process row，且后端 process authority 仍可用于恢复与审计。
- [ ] API、数据库、worker、run loop、Desktop 类型与四份 source-of-truth 文档一致；相关 pytest、Ruff、Mypy、TypeScript build 与浏览器集成测试通过。
- [ ] 新表、事件、日志与 UI 均不含 hidden reasoning、raw provider payload、prompt、内部 diagnostics、hidden tests、secrets 或不受控自由文本状态。

## 子任务与实施顺序

1. `08-13-tutor-thread-turn-item-event-foundation`：无前置依赖；建立数据模型、公开 item/event、snapshot/stream 与 durable dispatch 底座。
2. `08-14-dsh-derived-ui-foundation`：无代码前置依赖；迁入固定 revision 的 tokens、primitives、icons、NOTICE 与组件测试基础。
3. `08-14-tutor-typed-request-authority-turns`：依赖子任务 1；实现 typed request/approval/authority receipt 与 fresh response turn。
4. `08-13-tutor-queue-steer-interrupt-control`：依赖子任务 1、3；实现 Queue、Steer、Interrupt、pause/resume/execute、Retry 与副作用屏障。
5. `08-14-tutor-thread-turn-v2-global-cutover`：依赖子任务 1、3、4；实现 global gate、legacy freeze/cancel/migration、effect block、410 tombstone 与 preflight。
6. `08-13-codex-like-tutor-desktop-migration-qa`：依赖前五个子任务；实现 DSH-derived Desktop 集成、只读 legacy 展示、浏览器 QA 与文档。

父任务不直接 `task.py start`；最终规划获批且目标 worktree 准备完成后，只启动第一个依赖满足的子任务。虽然子任务 1、2 无代码依赖，inline 模式仍按编号逐个完成和归档，不并行派发 implement/check sub-agent。

## 风险与约束

- 当前 `main` 基线已包含 prompt、Model Review、continuation enum 与文档提交；目标 worktree fast-forward 后必须逐文件保留并融合，禁止 reset/覆盖。
- conversation-level event、Queue、worker/reconciler 跨数据库/API/worker/Desktop，多层契约漂移是主要风险；所有字段先在后端 typed contract 定义，再传播到前端。
- Celery/Redis 不能成为 Queue 或 dispatch 状态源；Redis 丢消息后 PostgreSQL reconciler 必须可恢复。
- schema 只做 additive 迁移；不原地重写或删除历史 Tutor 记录。旧 continuation route 可保留为稳定 `410 Gone` tombstone，但不得再产生 mutation。
- 本任务仍处于规划阶段；未获得对本最终规划摘要的后续明确实施批准前，不启动任何子任务或业务代码修改。
