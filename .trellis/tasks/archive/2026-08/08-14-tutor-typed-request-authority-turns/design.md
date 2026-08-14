# Tutor 类型化请求与权威续轮：技术设计

## 数据模型

新增 `tutor_interaction_requests`：

- scope：`id`, `user_id`, `conversation_id`, `source_turn_id`, `item_id`；
- contract：`kind`, `actor`, `schema_version`, `catalog_version`, `question_key`, safe descriptor/presentation；
- authority：proposal/request identity、issuer/subject/scope/hash 等闭合字段；
- state：`pending | answered | denied | cancelled | expired`，带 `version`、response/receipt hash 与 resolved time；
- lineage：`answer_turn_id`，并在 `tutor_runs` 添加具体 `response_to_request_id` 外键。

使用 partial unique index 保证每 conversation 最多一个 pending blocking request。JSON 字段由 typed serializer/allowlist 写入，不接受任意 provider schema。

## Public item 与事件

`TutorPublicItem` 的 `elicitation | approval` 由 request row 投影，公开字段包括稳定 item/request ID、source turn、kind、required、presentation、state/version 与允许动作。authority wait 只暴露安全状态摘要，不暴露 issuer secret、raw result 或 capability args。

来源 turn 产生 request 的 transaction：

1. 锁 conversation 与 run 并验证 lease/revision；
2. 创建 request/item；
3. 将来源 turn 公开终结为 `completed`，写 completion reason；
4. append item 与 turn/control events；
5. 释放 lease，conversation 进入 waiting。

## Learner response transaction

`POST /api/tutor/conversations/{conversation_id}/requests/{item_id}/responses`：

- 验证 user/conversation、request kind/actor、`expected_request_version` 与 idempotency key；
- clarification 验证 bounded answer text；planning_input 只接受当前 key 的 typed fact；approval 只接受 approve/deny；
- CAS request state，写 learner-safe evidence/message；
- 创建 fresh `thread_turn_v2`、input event、public events 与 dispatch job；
- 回填 `answer_turn_id/response_to_request_id`；
- 重复同 body 返回同一 answer turn，不同 body 返回 conflict。

Context loader 只读取来源 request question、learner answer、来源 turn learner-safe evidence 和允许的历史上下文，不读取隐藏推理。

## Authority receipt transaction

内部 service 接受经过认证的 issuer/subject/scope/request hash/result hash：

- 不提供 learner-facing route；
- 验证 request 仍 pending 且 actor=authority；
- receipt identity/body hash 幂等；
- 解决 request 并创建 fresh authority continuation turn/job；
- ambiguous verification 结果保持 pending/blocked，不伪造成功。

## Planning question catalog

`services/learning/planning_questions.py` 维护 exact key→immutable template/version。选项来自 allowlist 或已发布课程目录 stable ID，并与 `normalize_planning_fact()` 共享 value contract。provider decision 只含 continuation kind、question key 和安全问题文本。

## 与 Queue/control 的契约

Snapshot 输出 nullable `pending_request` 与派生 waiting control state。Queue child 只能读取该 authority：pending 时拒绝 drain/Steer/execute；response 创建 fresh turn 后由正常 completed-only drain 规则继续。两者通过 request ID、control version 和 public events 连接，不共享隐藏状态。

## 兼容与回滚

历史 row 没有 request 时由 legacy adapter 只读投影；不回填伪 request。schema additive 保留。代码回滚可停用新 mutation 并只读保留 request/turn，绝不恢复旧 run-input merge。