# D 语义修复独立早期检查（2026-09-27，滚动检查点）

> 审查者只读生产代码/测试，实施代理仍有 app/tests 写权；本文件不是验收通过，不代替真实 reviewer/provider/C 来源。以下行号以写入时工作树为准，后续修改需重核。未调用真实 API、未改 app/tests。

## 已确认的阻断风险

1. **[P1] 已持久 `consistent` 但 provider 尚未接受，导致修复被唯一约束挡住。** `provider_gateway.py:301-330` 在 D `decision_validator` 后才核对 streaming `public_thinking_text` 与最终对象并调用 `thinking_sink.complete_attempt`；D 的 `material_selection.py:431-466` 已提前提交 `consistent` receipt，380 schema:39-40 对 `(run_id,input_revision)` 只许一条 `consistent`。当第一候选语义通过、其流文本与对象不符时，gateway 拒绝并尝试修复；第二候选无论是什么，审查通过时再次 INSERT 会违反唯一索引，gateway 走 adapter failure，不可能接受有效修复。第一条记录还为未获 provider 接受的候选保留了 `consistent`，与“accepted 前 durable”不同。建议把 review/落库移动至所有 provider 验证之后、真正返回 accepted 之前；若 `complete_attempt` 可能失败也需先处理。并用真实 gateway+fake stream 的首轮 mismatch→第二轮修复测试，不要仅测无流 fake transport。

2. **[P1/P2] Reviewer receipt 无幂等重放分支。** `material_selection.py:454-466` 始终 INSERT，380 schema:27 的 `(run,revision,decision_iteration,attempt)` 唯一以及 :39 的单 consistent 唯一会使同一 provider 候选/同一 attempt 在 worker 重启/重试后再次 `review_decision` 报唯一冲突；即使 reviewer 第二次语义一致，不能安全继续。按 exact binding/digest/verdict 区分合法 replay 与冲突，避免重新调用模型（应先查已落同 attempt receipt），并测试相同与异内容 replay。该问题和第1项独立。

3. **[P2] append 的 receipt 校验未独立重算公开最终消息的 digest。** `material_selection.py:411-414` 将 `decision.public_message` 放进 reviewed candidate，但 `candidate_digest_for_input` 只算 capability input；`assert_review_before_append` (:473-497) 只拿 capability input，直接重用 DB 行 `candidate_hash`，没有从将发布的 message 重算它。正常 gateway 决策未被中途改写时有入口校验，但 persisted receipt 本身不证明具体最终 public message 与审查时相同。若目标是最终消息亦获审，应明确传 accepted `TutorDecision`/message 到 append fence，或独立保证同一不可变决策对象；测试 reviewed M1 / same plan M2 不可复用 receipt。不要误称目前的 exact receipt 覆盖 final message。

## 已核的正向边界（非整体通过）

- `MaterialReviewRequest` digest 包含 run/revision/selection digest/parent hash/candidate input hash 及 authority/candidate hash；selection digest 自身包含 handle，380 FK 约束 run/user、run/conversation、selection handle/digest，review 写入后重读 run lease/selection。未见 reviewer 扩张 C 来源用途的分支；append/selection 当前授权仍由 D/C 路径承担。
- 主会话正在追加安全 repair guidance；本文不把缺少 guidance 当最终缺陷，待实现后验证 WHERE 域信息是否给第二次模型足够具体且不会携带未受信来源全文。

## 后续待核

PG 双 bootstrap、真实 receipt SQL/FK、purge、默认关闭/注入 provider、防止 provider I/O 落在 DB 事务内、usage 失败/未知值、gateway+假模型两轮的实际输出及 lint/mypy/tests。工作树仍并发变化，不能用当前局部静态检查称整体 passed。

## 追加具体发现

4. **[P1] 学习者可见文本并非全部进入 reviewer，且最终 terminal 消息完全跳过。** `TutorDecision.public_thinking_text` 是 learner-visible (`provider_request.py:53-56`)，可被 gateway 流式展示；但 `material_selection.py:411-414` 的 review candidate 只有 capability input 与 `public_message`。同一接受候选的 public thinking 可继续把 WHERE 错译为学习地点而 reviewer 只看正确的简短 message/plan。并且 `review_decision:380-383` 对无 `learning.plan.draft` 的 terminal 决策直接返回 None；实际 dispatcher 测试在修订后还有独立 `turn_completed` 消息。终结消息可宣称“全部教材 ready/审核过”而根本没受 semantic review。须将要展示的 public thinking 和最终总结纳入准确审查范围，或由服务端生成不会越权的安全摘要；若不纳入，明确不能声称“最终输出已审查”。加两个负例（候选 thinking 错义、终结消息 overclaim）。

5. **[P2，实施测试本身失败]** 在本人专用 `aearn_rag260_c_d_check_20260927` DB 用现有 manifest 两次 `apply_schema` 均成功；随后运行新 `test_rag_d_semantic_repair.py` + `test_rag_d_schema.py` 得 **5 passed, 1 failed**。失败是正在写的测试 `test_rag_d_semantic_repair.py:257-260` 查询 `d.conversation_id`，但 `tutor_learning_plan_drafts` 无该列；应取 `s.conversation_id` 或 join session。此为测试查询错误，非 production schema 不兼容；worker 拥有 tests 写权，请由其修复后重跑。无 app/tests 编辑。

## 当前验证（并发快照）

- checker DB：`current_database()` 精确为 `aearn_rag260_c_d_check_20260927`；`apply_schema(conn)` 两次成功。未触碰 C 真实资料/业务库。
- Ruff（七个触及 Python 源文件）：pass；Mypy（同七文件，`--no-incremental`）：pass。它们并非最终全库 gate。
- 新 semantic PG/manifest 测试：5 passed / 1 failed（上述 worker 测试 SQL）；测试之后的并发变更尚未复验。
- Safe repair guidance 已在 `decision_protocol.py:104-122` 出现，明确 SQL WHERE/schema 教材意义。原滚动检查点关于“尚在补 guidance”现在只作历史状态；它不再是当前阻断项。需最终 gateway 用例确认第二请求实际包含该 guidance，现有新增测试在失败前的正例已断言。

6. **[P1] D opt-in 的“无 feedback”可当作静默旁路。** `material_selection.py:398-400` 在当前 run 没有 target feedback 时直接返回 None，gateway 接受 `learning.plan.draft` 而不调用 reviewer；`validate_successor_before_append:357-359` 也返回 None，`plan_capability.py:142-154` 因而照常 append、且不执行 successor reselect/binding。`plan_repository.py:176-179,229-244` 本来允许已有 current_draft 的显式修订。这意味着用已启用 D 的 dispatcher 对已有草案发起未成功关联 feedback 的 revision，仍能生成新版草案而完全跳过 D 审查/材料绑定。初稿是否应该进入 D 是产品接线决策，但对已有草案的 D opt-in revision 应明确 fail closed（或强制先签发/分配完整 feedback），不能把缺反馈误认作“不需 D”。增加有 current_draft/no target feedback 的 primary 与 custom provider 双路径负例；当前 fake provider 正例依赖显式 assign_parent_feedback，未覆盖旁路。

7. **[P1/P2] reviewer 已发生计费调用后，失租/撤权/SQL 冲突会丢失实际 usage 与 unknown 状态。** `material_selection.py:417-430` 在事务外调用模型；随后 `:431-466` 的 run lease/selection/C 授权检查或 INSERT 若失败，唯一 audit INSERT 被整笔回滚、函数抛出异常，调用者只留下 primary-provider attempt。已发生的一次 reviewer 请求及其 receipt.usage（或未知）不持久保留；其中 source revoke/lease 失效正是需要保守核算的常见竞态。建议将“已 dispatch reviewer / usage unknown”作为独立有界、私有的调用审计锚点，在去权后也只允许结算 usage 而绝不授 consistent authority；或者明确等价的失败保留机制。测试 reviewer 返回已知 usage 后让 lease 在审查期间失效、selection 撤权、第二条 unique 冲突，断言无 append/binding 且 reviewer 调用与已知/unknown usage 仍可审计。不能以失租时没有 receipt 冒称零费用。

## 最终复审结论（2026-09-27；实施代理 CLOSED 后）

**结论：本轮五组具体问题在当前补丁中已关闭；未发现需要窄修的剩余 P1 阻断。允许主会话进入自身 broad/quality gate 收敛；不代表 full-live C+D 或公开发布通过。** 上文为早期快照问题，当前状态以下表为准。本复审未修改 app/tests、来源基础设施、真实 harness 或主会话拥有的规格文档。

| 早期问题组 | 当前代码复核与决定 |
|---|---|
| gateway 尚未接受却产生可授信审查 | `provider_gateway.py:299-333` 先解析/安全/stream equality 后调用 D validator；380 删除单 run/revision consistent 唯一索引；append 的查询要求同 run/revision/decision_iteration/attempt 的持久 provider `accepted` receipt + settled consistent review。之后 sink/lifecycle 失败留下的审查 audit 不等于 append 资格。已关闭。 |
| exact-attempt 重放 | `material_selection.py:438-469` 在任何 reviewer 调用前读 exact attempt，校验 request binding、selection handle、candidate digest；settled 精确重放复用 verdict，dispatched 未结算重放 fail closed，异内容拒绝。PG replay 用例通过且调用计数不增加。已关闭。 |
| 草案可见文本审查/receipt 关联 | 同一次 draft candidate 的 `public_message` 和 `public_thinking_text` 均进入 request/candidate hash；gateway 返回同一个已验证 immutable decision，append 通过 accepted attempt + 精确 capability candidate/authority digest 连接审查。未看到当前生产接线会在审查后替换同一次 decision 的文本。原要求不扩展为“全部聊天正确”。已关闭本轮候选范围。 |
| D existing-draft 无反馈旁路 | context、review、pre-append 三处拒绝有 parent/current draft 却没有 target feedback 的 revision；首次无 parent 路径明确独立。primary/custom provider 双负例通过，模型调用为零、无 successor/binding。已关闭。 |
| 失租/撤权后 reviewer usage 丢失 | 网络前提交 dispatched/unknown；网络后独立短事务 settled 保存实际或 null usage，之后才做 current lease/selection/C 资格核验。失租后的已知与 unknown usage PG 两例均通过且无 successor。settlement 故障仍保留 dispatched unknown，不冒充零费用。用户并发授权 purge 不复活已删个人记录，属于已明确记录的生命周期边界。已关闭。 |

### 最终独立验证

- 同本人 checker 数据库：`current_database()` 精确确认 `aearn_rag260_c_d_check_20260927`，使用**最新 schema（含 dispatched→settled）连续 bootstrap 两次均成功**；旧检查测试行无需删除或改写。
- `pytest -q tests/learning/test_rag_d_semantic_repair.py tests/learning/test_rag_d_material_semantic_reviewer.py tests/learning/test_rag_d_planning_consumer.py tests/database/test_rag_d_schema.py tests/tutor/test_tutor_provider_gateway.py`：**107 passed in 33.57s**。无 skip；仅 fake provider/reviewer/合成证据；不调用真实 API。
- Ruff：8 个触及源文件及 2 个新语义测试文件 **pass**。
- Mypy：8 个触及源文件 `--no-incremental` **pass**。
- 上轮 `d.conversation_id` 测试查询失败已在当前版本修复；本次对应测试通过。
- 读取 `semantic-repair.md`、最新 backend scoped spec 和 `real-semantic-review-controls-2.json`：闭集 JSON 指令已进入实际 reviewer system message；记录中 wrong/faithful 两例符合预期，且明示单组件/合成公开 SQL facts。本人没有重做真实调用。

### 批准的残余边界（不是本轮 P1）

- 同一 draft 候选之后独立 `turn_completed` 自由文本**不在此 draft reviewer 保证内**；主会话已批准此边界，spec 与实施报告已明确，不新增 terminal 协议/审查，不声称 all learner prose reviewed。
- full current-source C+D live 仍未通过：主会话报告首轮 timeout、末轮 supplemental config 在 HTTP 前拒绝并已停止；此复审不改判，不碰来源授权、infra 或 live harness。
- 本结论是上述代码/专项的独立 gate，不替代主会话正在运行的全库 lint/typecheck/broad regression，也不新增 commit/push 授权。
