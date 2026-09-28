# Research: D 规划独立压力审阅

- Query: 审阅本任务 PRD/design/implement、planning-consumer-seams/evidence-authorization-fence 两份研究与父 phase-II D；重点核实内部计划消费、跨稿反馈、既有 run 幂等、双开关、双表生命周期、C 授权 fence 和 D/E 边界。
- Scope: internal
- Date: 2026-09-27

## Findings

### 结论

**需小幅修订规划，修订后可请求用户批准实施；本轮不等于实施许可。** 主方向是对的：父 `phase-ii-design.md:68-78`、`phase-ii-implement.md:65-81` 要 D 做真实内部消费者和授权接口，题库全入口归 E/题库 owner；本任务 `prd.md:15-31,36-43`、`design.md:36-45,55-71`、`implement.md:28-40,67-74` 已把新 run、parent→successor、二次 selection、同事务 fence、默认关闭及证据分级写入，不是单独 helper 演示。下列缺口是可落地合同的最后一公里，而非要求新 provider、审核服务或全题库。

### P1：必须在规划中补明确的交付约束

1. **持久 parent feedback→target run 关联尚未落在选定的两表设计里。** 研究已准确提出新 `(run_id,input_revision)`、`MaterialFeedbackRef` 与 context-load/append 双 CAS（`research/planning-consumer-seams.md:22-31`），但 `design.md:39-42,47-51` 只说「新 run」「反馈 handle」「selection 的作用域内幂等」，未规定哪个持久记录把 *parent selection* 指派给 *这个 target run/input_revision*。`implement.md:14,30-32,35-38` 也未把这一约束列为集成通过条件。当前 `plan_repository.py:94-129` 要求 run 是同 conversation/user、interactive、非终止、且有 plan_drafting scope；`:145-179` 对同 run/revision 仅同 hash/facts 重放，并从当前 session 指针推 predecessor；`interactive.py:678-685,723-738` 的 context loader 只见 session/facts，不会凭空知道哪个 selection 应投递。若仅靠进程内参数，重启/异步回调会丢来源；若凭「当前 selection」查询，则会将旧反馈投给错误 run。**最小改法：**在 `design.md` 第4/5节、`implement.md` P1/P4 明示复用现有 run/session authority，在 target run 创建/关联时原子记录 `(user,session,parent draft/version/hash,selection handle/digest,target run_id,input_revision,expected session version)` 的不可变一次性分配；可加在 selection 表的受限 target 字段/附属唯一关联或复用现有可靠 run 元数据，不必第三套 run 系统或第三表。唯一约束禁止一个 target run/revision 认领两个 parent selection、一个 selection 乱投到并行 run；context load 和 capability append 前均按该持久关联及当前 parent CAS，取消/重试/重启时不重新选「最新」。模型只能读安全投影，不能自报 feedback ref。确定性替身测试须覆盖重启后定位、错 run、竞争认领、取消/旧回调，且沿真实 dispatcher→context→gateway→capability→repository 观察新稿和新 selection/binding；不能只直接调用 `material_selection`。

2. **binding 幂等的自然键/单一冻结语义不够明确。** `design.md:48-52` 要求相同 key 同 payload replay、不同 payload conflict，却未说明不同 retry key 在同一 draft/node/goal/purpose 下先后冻结两个不同证据集合时如何防双绑定；`prd.md:38,42` 要拒绝旧 selection、冲突与并发 CAS。研究 `planning-consumer-seams.md:24-31,39-42` 已选 parent selection 仅反馈、新 selection 才冻 successor，不能把 selection 表设计成跨稿授信。**最小改法：**明确 selection handle 的粒度（整稿含逐节点/用途快照，还是逐节点/用途行），binding FK 加服务端核对 exact draft/node/goal/purpose/selection digest，禁止仅凭 selection UUID 连接；定义 `(draft_id,node_id,goal_hash,purpose)` 唯一冻结或等价冲突规则，完全相同内容可幂等返回，不同 retry key/不同证据集合也冲突，授权失效后不得更新旧 binding 伪装重新授权，必须重选并取得受控新稿/修订。若允许同稿重新冻结，则需另写唯一当前版本决议，不可默认多行皆有效。

### P2：实施前在文档与验收矩阵补窄化断言

3. **真实内部接线的开关归属仍模糊。** `design.md:14-21,45` 和 `implement.md:35-41,67-69` 已要求 internal opt-in、原 provider/capability 路径和零默认 IO，但具体哪个 factory 注入、是否采用 API `Settings.rag_evidence_consumer_enabled` 尚未点名。已有 `core/config.py:85` 定义默认 false，`worker_composition.py:98-108` 自行读取环境开关；`interactive.py:1070-1115` 目前无 D port，仍传 `LearningPlanDraftCapabilityHandler(conn)`，且 provider 调用与 DB 事务分开（`run_loop.py:210-243`）。**最小改法：**在设计第2/4节指定实际 internal composition/factory 的受限注入点和双条件（existing flag + server-only D opt-in）；普通公开 dispatcher/factory、缺注入及 flag 关闭三种均 zero-call/zero-new-table read。不要把 worker `_gates` 的存在当 interactive 已接线，也不许用 harness 的直接 helper 调用冒充真实 run 路径。

4. **双表 purge 顺序需落到已有真实删除路径，而不是只写抽象 child-to-root。** `design.md:47-53`、`implement.md:18,40,73` 提到授权 purge，但现有 `local_user_data_repository.py:1477-1510` 会先取消 active runs 并设置 transaction-local `aearn.learning_track_purge_user_id`；`:1717-1719` 随后删除草案/session/scope。新增 binding→selection（含任何 target-run 关联）须在删除草案前、同一事务按子到父顺序清理；FK/immutable trigger 仅允许此 purge，不许普通改历史，不能让旧 reset/delete 因 FK 失败。若新增 run FK，还要校核该仓库的 run 清理/库存路径（`:1785-1808`）。在 D-AC7 明列 reset 和 delete 两条路径、回滚与别的用户/共享 corpus 不变；不需要本轮实际删除用户。

5. **fence 的锁和 expiry 方向正确，不能让「复用」二字代替 writer 证明。** `design.md:61-69`、`research/evidence-authorization-fence.md:29-39` 已给 exact version→link/review/admission→capture/policy/grant/root→pointer 及 READ COMMITTED 重读、DB `clock_timestamp()`、双连接 barrier。代码 `_verified` 先 `version(for_update=True)`（`corpus_governance.py:472-513`），activate/rollback 再 pointer CAS（`:515-533`）；`SourceReviewRepository._resolve_scoped` 锁 review/admission 再取 DB clock（`source_review_repository.py:382-405`）；`PostgresQualificationAuthority.resolve` 末尾锁 pointer（`corpus_governance.py:546-567`）。**最小改法：**把 `implement.md:25-26,72` 的锁矩阵验收写成逐 writer 对应的冲突锁/UPDATE 和最终重读/时钟断言；检查 grant/root/retention 多行 writer 顺序，不仅 pointer。禁止 autocommit、自开连接/自提交；expiry 在锁等待后过期必须失败，fence 成功但提交前过期不宣称永久有效，题库同事务紧贴写入及供题再验归 E。局部旧 C writer 修复须交接，无法同序则暂停，不用测试通过代替全局安全声明。

6. **D 接口和 E 真实发布的接受语义要保持拒绝态。** `design.md:55-61,71,75-80`、`prd.md:24-28,40-43,45-53` 已诚实区分接口/隔离事务与题库实际入口；`corpus_governance.py:546-552` 的现有 qualification authority 对 assessment 返回 `None`，研究 `evidence-authorization-fence.md:14-17,42-46` 未发现可信生产 claim/execution resolver。建议在 D-AC5/6 旁明列：D 可交付 strict callable + current deny + 注入可信 synthetic isolated-PG 的正/负原子性；**当前真实 assessment ready / 真实 item publication / materialization / 供题均 blocked/not_executed**，不得把读取 claim 行、机器审核的两片 supplementary excerpt 或合成 receipt 当生产正例。生产 claim resolver / 所有题库入口仍 E/owner；不因此扩 D 去建新服务。

### 文件与代码索引

- `.trellis/tasks/09-27-rag-plan-material-evidence-binding/prd.md:15-53` — 范围、D-AC1..8、实施授权边界。
- 同目录 `design.md:13-80` — 内部模块、双 selection 与双表、fence 顺序、回退；`implement.md:10-48,67-76` — 分段实施和验收矩阵。
- 同目录 `research/planning-consumer-seams.md:11-42` — 现行 plan 幂等与新 run/双 CAS/两次 selection；`research/evidence-authorization-fence.md:14-46` — C 权限、隔离门禁、锁与 claim 缺口。
- 父 `.trellis/tasks/09-03-rag-language-ecosystem-adaptive-retrieval/phase-ii-design.md:68-82`、`phase-ii-implement.md:65-85` — D/E 交付分界。
- `aearn/services/api/app/services/learning/plan_capability.py:105-150`、`plan_repository.py:94-129,145-179,229-244` — handler 事务与现有 run/revision 幂等及 predecessor。
- `aearn/services/api/app/services/tutor/interactive.py:678-738,1016-1047,1070-1115`、`run_loop.py:210-243` — 当前 plan context/provider/handler 和模型事务边界。
- `aearn/services/api/app/services/learning/track_repository.py:577-628` — 现有 run scope 继承边界；`app/services/repositories/local_user_data_repository.py:1477-1510,1717-1719` — 用户数据清理次序。
- `aearn/services/api/app/services/grounding/autonomous/corpus_governance.py:472-567`、`source_review_repository.py:382-405` — 当前 exact corpus/review/pointer 检验接缝。

### Related specs / external references

- `.trellis/spec/backend/plan-preflight-migration.md:5-39`（phase-I 只读、fixture 不可冒充授权）；`grounding-material-contracts.md:5-13`（需求/用途端口）；`grounding-source-admission.md:19-31,76-86`（C 摘录、candidate grant）；`grounding-retrieval-v2.md:17-31`（exact corpus/coverage 边界）。
- External references: 无；按委托仅本地文档/少量代码静态核对，没有联网或验证外部版本。

## Caveats / Not Found

- 未执行测试、数据库、网络/provider、task start 或任何产品修改；结论是规划审阅，不宣称代码已实现或运行时验证。
- 以上 P1 属于审批前必须补足的合同描述；P2 是最小验收与交接澄清。2026-09-26 21:26:59（北京时间）截止的 C 机器回执已过期，不能用作 2026-09-27 的 current-ready 证明。
- 代码索引是静态局部抽查，未对所有 writer/锁形成传递调用图证明；双会话竞态与正式 E 公共消费应在各自授权范围另证。
## 收敛复核（2026-09-27；仅复核原六项）

**结论更新：原 P1/P2 规划缺口均已闭合；规划文本达到可提交用户批准实施的门槛。** 此结论仅是规划审阅通过，不构成用户已批准实施，不触发 `task.py start`，不代表代码/PG/真实 provider 已验证。上文 2026-09-27 初审保留作为历史审计记录，其「需修订」结论由本节取代。

| 原发现 | 修订后的文档证据 | 收敛判断 |
| --- | --- | --- |
| P1 parent feedback→target run 持久关联 | `design.md:42,50-51`：既有 authority 新 run，provider 前同事务认领，整稿 snapshot 不变，五个 target 字段全空→全满一次性更新、唯一 target run/revision、assignment digest；context load 与 capability append 双 CAS，取消/重试新 run 重选。`implement.md:18,37-38,73` 纳入持久、重启及竞争验收；`prd.md:42` 对应 D-AC7。 | **闭合**；无需第三表或新 run 系统。实现时证明目标 run 的 scope、当前 parent/session 和重放约束。 |
| P1 binding 幂等与跨稿信任 | `design.md:27,42-44,51-52`：整稿 selection 内逐节点/用途，parent handle 仅反馈，successor 新 selection 才能冻；binding 唯一自然键 `(draft_id,node_id,goal_hash,purpose)`、exact scope/digest 校验，换 retry key 的异证据仍冲突，同内容重放也重验现时授权；失效改受控新稿。`implement.md:18,30-33,69,73` 有对应步骤/负例。 | **闭合**；不允许双 binding 或以旧选择向新稿授信。 |
| P2 实际 consumer 与双开关 | `design.md:21,38-47` 点名 API `Settings.rag_evidence_consumer_enabled` + server-only opt-in、`build_internal_material_planning_dispatcher` 的受限注入及 dispatcher→context→gateway→capability→repository；普通 factory、缺注入、flag 关闭均零新增调用。`implement.md:36-38,68-69` 明确接线与 transport 替身验收。 | **闭合**；仍须实施时运行路径证据，不能把 helper 直接调用充作通过。 |
| P2 双表 purge | `design.md:51-55` 将唯一允许的 selection 认领 UPDATE 与获准 purge 区分，并指定 active-run 终止、transaction-local purge capability、binding→selection→旧 draft/session/scope→run；`implement.md:36,40,73` 与 `prd.md:42` 纳入 reset/delete、回滚及其他用户/共享 corpus。 | **闭合**。 |
| P2 writer 锁、同事务、expiry | `design.md:63-71` 给 caller-owned 短事务、C 同序锁/重读、逐 writer 冲突锁或 UPDATE、两种 barrier、等待后 DB `clock_timestamp()`、失败回滚、不得以 fence 断言无限延迟后的有效性；`implement.md:25-26,72` 列执行矩阵。 | **闭合为可执行验收计划**，非已经证成所有 writer 安全；局部 C 修复需写权交接，无法同序应暂停。 |
| P2 D/E 与可信 claim 边界 | `design.md:71-73,77-82`、`implement.md:71-74` 明确缺可信 resolver fail closed，隔离 synthetic 正例只证合同，真实 assessment ready、item publication/materialization/供题 blocked/not_executed；`prd.md:24-28,40-43,45-53` 仍限 D 接口。 | **闭合**；不扩大到 E/题库全入口。 |

**不可变措辞专项：** 当前三稿并无「所有 selection 字段完全 append-only」的残留承诺。`design.md:9,51,54` 明确区分 immutable selection *snapshot/digest* 与五个 target 关联字段的唯一受限 UPDATE（全空→全满、不可重绑/清空）；`implement.md:18` 同样区分 selection snapshot 与 binding 不可变。`research/planning-consumer-seams.md:41` 的早期「immutable selection/feedback 快照」只指快照，不能覆盖当前设计允许的一次认领；本文件初审 `:15-17` 是保留的历史诊断，不是现行规划要求。实施时避免在 SQL trigger 中无条件禁止这一次受限 UPDATE，同时不能容许其他字段更新。

**余留验证边界：** 本轮只读重核三份规划，不运行测试/DB/网络/provider，也没有产品代码改动；通过是「规划可审批」而非 D-AC 的实测 passed。无需因本复核另增功能。