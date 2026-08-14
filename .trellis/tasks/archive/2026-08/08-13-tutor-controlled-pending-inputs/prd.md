# 建立 Tutor 受控 Pending Input

## 目标

把 `clarification` 与 `planning_input` 建模为准确、独立、服务端权威的 continuation enum，并为 `waiting_for_input` 提供版本化 `pending_input` projection。`planning_input` 的 UI schema 只能由服务端 allowlisted question catalog/template 构造；模型只选择受控 key 并生成 learner-safe question text。

## 依赖

- 依赖父任务需求和 `research/dsh-ui-reuse-audit.md`。
- 不依赖 `08-13-dsh-derived-ui-foundation` 代码；本 child 只实现 contract/authority 和必要的 Desktop type/API seam。
- 实施前必须检查 `E:\codee\Aearn` 原始工作树中 `clarification` / `planning_input`、prompt 和教学场景/tests/rubric 修改，逐文件语义移植重叠部分；不得整包覆盖。
- 后续 `08-13-tutor-dsh-conversation-integration` 依赖本 child 完成。

## 范围内

- 后端/前端 `TutorContinuationKind` 增加准确 enum 并保持旧值兼容。
- `tutor_run_pending_inputs` additive persistence、repository、run/history/API/SSE projection。
- 七个 `PlanningFactField` 的受控 question catalog/template。
- typed answer identity、expected revision、结构化 facts、learner-visible content 和 stale/scope/idempotency validation。
- provider/skill prompts 的正例、反例、边界示例和 contract tests。
- API、数据库、runtime 与 acceptance 文档的本 child 事实更新。

## 范围外

- DSH QuestionComposer 视觉实现、Composer takeover 和浏览器 UI；由集成 child 完成。
- 持久化普通消息 Queue、Steer 和 stop；由 Queue/Stop child 完成。
- optional question、skip、close、单独 wait-cancel authority。
- 模型生成任意 UI schema、tests、hidden rubric 或 reference answer。
- 重写原始工作树中受控教学场景/候选代码与服务端 tests/rubric 实现。

## 需求

1. continuation enum 包含 `clarification`、`planning_input`、`approval`、`capability_result`、`external_result`，决策协议不得混用前三者。
2. `waiting_for_input` 必须持久化一个 `tutor_pending_input_v1`；重连、history hydrate 和 run read 返回同一稳定 identity。
3. `clarification` projection 为 required bounded text；问题正文来自 learner-safe `public_message`，不能由 Desktop猜测。
4. `planning_input` 必须携带 allowlisted `question_key`，对应七个 required planning facts。
5. question catalog/template 由服务端代码和已发布课程目录构造 presentation/validation；provider 不得返回 options/schema。
6. unknown question key、confirmed fact 重问、catalog/version 不匹配、stale expected revision 和跨用户请求均 fail closed。
7. typed answer 在同一事务中验证 pending input、写 learner message/input receipt、记录 planning fact、resolve pending input 并恢复原 run。
8. required input 不允许空值、skip 或 close；退出规划继续使用 learning plan session cancel。
9. prompts/skill instructions 至少各包含：应使用 `clarification` 的例子、应使用 `planning_input` 的例子、不得用 `approval` 代替的反例、已确认 fact 不得重问的边界例子。
10. 保持“模型只生成教学场景与候选代码，tests/rubric 由服务端受控 DSL/template 构造”的现有安全边界。

## 验收标准

- [ ] Python/TypeScript enum、parsers 和 API projection 对五种 continuation kind 一致。
- [ ] PostgreSQL bootstrap twice 建立 pending-input additive schema，约束一个 run 最多一个 unresolved item。
- [ ] 七个 required facts 均有受控 catalog definition、value validation 和测试。
- [ ] provider 只能给出 kind/key/text；任意 options/schema 字段被 contract 拒绝或忽略，不进入 public projection。
- [ ] same pending identity replay 稳定；stale/cross-user/unknown/confirmed-reask 返回稳定安全错误。
- [ ] typed answer 原子恢复 run，重复 idempotency key replay 同一响应，不重复写 message/fact/event。
- [ ] prompt 正例/反例/边界测试通过，`clarification`、`planning_input`、`approval` 不混用。
- [ ] 原始工作树重叠语义已核对，用户 prompt/tests/rubric 修改未被覆盖或回退。
- [ ] focused pytest、Ruff、Mypy、Desktop typecheck 和文档一致性检查通过。

## 风险

- pending input 是跨 run-loop、DB、API、SSE 和 Desktop type 的新 contract，任何一层按文案猜测都会造成漂移。
- question options 可能依赖课程 catalog；必须按 stable key/version 查询，不能按列表位置。
- 原始工作树存在大量相关 dirty changes，需以 hunk 级语义移植避免夹带其他工作。
