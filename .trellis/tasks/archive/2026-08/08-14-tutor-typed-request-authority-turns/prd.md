# Tutor 类型化请求与权威续轮

## 目标

在 Thread/Turn/Item/Event 底座上，将 `clarification`、`planning_input`、`approval` 与 `capability_result | external_result` 建模为精确、持久、可审计的 typed item/request。来源 turn 在产生阻塞请求后安全结束；学习者回答或受信 authority receipt 解决精确 request，并创建拥有 fresh deadline、fresh counters 与独立 dispatch job 的新 turn，彻底取消“恢复原 `waiting_for_input` run 并继承预算”的语义。

## 依赖与范围

- 父任务：`08-13-codex-like-tutor-conversation-experience`。
- 依赖 `08-13-tutor-thread-turn-item-event-foundation` 完成并冻结 public item/event、snapshot、dispatch 与 protocol version contract。
- 不依赖 DSH UI foundation；本 child 只拥有后端 authority、共享 DTO、受控 catalog/prompt 和最小 Desktop type/API seam。
- 后续 Queue/control child 必须消费本 child 的 blocking-request contract；Desktop integration child 负责最终 Question/Approval UI。

## 范围内

- `tutor_interaction_requests` additive schema、repository、item/event/snapshot projection。
- `clarification | planning_input | approval` learner request 与 `capability_result | external_result` authority request/receipt。
- 七个 `PlanningFactField` 的 allowlisted question catalog、typed value validation 与版本。
- 来源 turn 安全终结、精确 response/receipt CAS、fresh answer/authority turn、`response_to_request_id` 与 `in_reply_to_item_id`。
- approval proposal identity、authority issuer/scope/hash、幂等与 stale/scope 校验。
- continuation enum、decision protocol、prompts/examples、API/runtime/database/acceptance 文档与测试。

## 范围外

- Queue CRUD/reorder/Steer/立即执行、Interrupt、Retry；由 `08-13-tutor-queue-steer-interrupt-control` 实现。
- DSH-derived QuestionComposer、Composer takeover 和 browser UI；由 Desktop integration child 实现。
- 全局 v2 cutover、legacy row 收口和旧 POST `410 Gone`；由 `08-14-tutor-thread-turn-v2-global-cutover` 实现。
- optional question、skip、close、模型自定义 UI schema、raw reasoning、hidden tests/rubric 或 learner 伪造 authority receipt。

## 需求

### R1：稳定 request authority

- request kind 为闭合 union：`clarification | planning_input | approval | capability_result | external_result`；actor 为 `learner | authority`。
- request 保存 user/conversation/source turn、稳定 item ID、safe descriptor、schema/catalog version、state/version 与 response/receipt hash；复合外键防止跨用户/会话引用。
- 每个 conversation 同时最多一个 unresolved blocking request；来源 turn 与 request/event 写入同一 transaction。

### R2：来源 turn 终结与 fresh turn

- 产生 request 后，来源 turn 以公开 `completed` 和安全 completion reason `awaiting_user | awaiting_approval | awaiting_authority` 终结，不保持可继续消耗预算的 `waiting_for_input`。
- response/receipt CAS 成功后原子解决 request，创建 learner/authority evidence、fresh turn、run input event、public events 与唯一 dispatch job。
- fresh turn 记录 `response_to_request_id`，公开 item 使用 `in_reply_to_item_id`；不得继承来源 turn 的 deadline、model/capability/effect counters 或 lease。

### R3：Clarification 与 Planning Input

- `clarification` 是 required bounded text，不携带 planning `question_key`。
- `planning_input` 必须携带 allowlisted `question_key`，覆盖 `language_id`、`goal_text`、`target_level`、`weekly_minutes`、`experience_level`、`teaching_preferences`、`pace_constraints`。
- catalog/template 由服务端构造 presentation、options、limits、recommended value 与 validation；provider 只能选择 kind/key 并生成 learner-safe question text。
- unknown key、confirmed fact 重问、catalog version 不匹配、值域错误、stale request version 与跨用户响应 fail closed。

### R4：Approval 与 authority receipt

- approval 绑定安全 action proposal identity、authority key、risk level 与 bounded summary；learner 只能提交 `approve | deny` 和可选 bounded reason。
- `capability_result | external_result` 只能由内部受信 service 写 issuer、subject、scope、request hash、result hash 与 verification result；learner route/composer 不暴露该 mutation。
- 重复相同 receipt 幂等返回同一 fresh turn；同 identity 不同 body/hash 冲突。

### R5：阻塞与 Queue 接缝

- unresolved request 时 conversation control state 为 waiting，Queue 保留但不得 drain；Queue/Steer/execute mutation 必须拒绝。
- response/receipt 创建 fresh turn 后仍由正常 completed-only Queue policy 接管；本 child 不自行 claim Queue。
- request cancel/expire 仅按服务端明确 policy；required learner request 不提供 skip/close。页面级取消规划仍属于 planning session authority。

### R6：安全与兼容

- public payload 只包含稳定 ID、enum、bounded learner-safe text、typed options/limits 与 recoverability；不含 prompt、provider body、trace、raw reasoning、capability args 或内部 validation 实现。
- 新 protocol 不调用 `/runs/{run_id}/inputs`；legacy read 由 snapshot/history adapter 处理，legacy write retirement 由 cutover child 负责。
- 原始工作树已有 continuation enum、prompt、受控 tests/rubric 修改必须逐文件融合，禁止整包覆盖。

## 验收标准

- [ ] 五种 request kind 在 Python DTO、PostgreSQL、API、events、snapshot 与 TypeScript seam 中一致，跨用户/跨 conversation 引用被约束拒绝。
- [ ] 三组“问题→回答”往返均终结来源 turn 并创建不同 fresh turn，deadline/counters/lease 不继承，不再出现共享预算耗尽。
- [ ] 七个 planning facts 均有稳定 key/version、presentation 和 value validation；provider authored options/schema 无法进入 public projection。
- [ ] approval approve/deny 精确绑定 proposal；普通文本不能冒充批准。
- [ ] learner 无法提交 capability/external receipt；受信 receipt 的 issuer/scope/hash、幂等与冲突测试通过。
- [ ] pending request 阻塞 Queue drain 与控制 mutation；解决后 fresh turn 运行，重复 response/receipt 不重复 message/turn/job。
- [ ] prompt 正例、反例、边界示例证明 clarification、planning_input、approval 不混用，confirmed fact 不重问。
- [ ] focused pytest、DB bootstrap twice、Ruff、Mypy、Desktop typecheck 和文档一致性检查通过。

## 风险

- request/answer 跨 DB、run loop、API、events 与 planning facts；任何一层仍按文案猜测都会破坏 identity。
- approval/authority receipt 是副作用安全边界；状态不明确时必须 fail closed。
- 本 child 与 Queue/control 的依赖必须通过冻结 DTO/event/error contract 衔接，不能在后续 child 重新定义。