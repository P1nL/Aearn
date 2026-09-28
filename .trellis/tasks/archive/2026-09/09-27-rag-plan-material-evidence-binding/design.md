# D 技术设计：内部教材反馈与精确绑定

> 已批准并完成首批内部实现；2026-09-27。追加修复正在实施：research/repair-acceptance-plan.md 与经主会话批准的 research/semantic-repair-design.md 约束本批次。语义审查不得简化成免责声明匹配或禁止合法计划修订；不一致进入既有有界修复，不确定/服务失败拒绝，模型审查不替代C授权。重试的完整消息必须重新核算输入预算。要求与验收的唯一任务入口是 prd.md。

## 1. 现有能力与选择
- 沿用 LearningPlanDraftArtifact、PlanDraftRepository 和既有 plan_drafting provider/capability；不重写计划引擎。
- 沿用 A 的严格 LearningMaterialDemand / RagEvidenceBinding、actor/policy/用途校验与 C SourceReviewRepository、candidate grants、corpus governance。新增 V2 envelope，不改旧合同含义或旧hash。
- phase-I retrieval/preflight/shadow 含 fixture-only 校验，不能整体拿来给 C 真资料背书。D 在 grounding 边界以当前正式 corpus 和 C 授权解析 exact rows，复用可用 FTS/coverage 基础逻辑，不新建搜索引擎、向量provider或第二source authority。
- 采用持久化 selection + binding 两张最小表，而非纯内存演示；selection内容不可变且仅允许一次受限target-run关联，binding完全不可变。复用既有draft/run authority，不引入第三套run系统。

代码依据与候选写集详见 research/planning-consumer-seams.md 和 research/evidence-authorization-fence.md。

## 2. 模块和单向依赖
- `learning/material_selection.py`：D 内部服务编排，需求、反馈安全投影、successor核验与冻结。通过明确注入的 grounding ports 访问证据，不让旧 plan_coverage/migration/shadow 被公开消费者直接导入。
- `grounding/evidence_binding_v2.py`：严格版本化需求/选择/绑定 envelope 及 exact evidence 解析；旧 A contract 作为内嵌身份，不接受任意URL/SQL/数据库目标。
- `grounding/current_authorization.py`：同连接 C 适配及 final authorization/fence；复用 authorize_binding/authorize_assessment_claim，不另发独立信任判定。
- `grounding/material_binding_repository.py`：selection/binding持久化、幂等、scope查验，不能写 corpus/pointer/题库。
- `grounding/release_scope.py` 或同模块小型 typed policy：仅内部服务构造时注入 Python/SQLite scope，不增加公开发布authority或管理入口；能内嵌则不为文件数另拆。
- 新增 `370_rag_plan_material_bindings.sql`（实施时重验编号占用），注册唯一 schema manifest；不改已发布070/260的历史定义。

现有API `Settings.rag_evidence_consumer_enabled`（默认false）与server-only D opt-in双重控制。新增内部 `learning/material_planning_composition.py::build_internal_material_planning_dispatcher`，仅在两条件满足时构造D ports并向既有 `TutorInteractiveRunDispatcher` 注入可选 `material_feedback_consumer`；默认None。dispatcher既有context loader和 `LearningPlanDraftCapabilityHandler` 共享此受限依赖，普通公开factory不注入。普通公开factory、缺注入、flag关闭三条路径均零新增表读取/resolver/provider调用。不能把worker的环境flag当成interactive已接线。测试必须经真实dispatcher→context→gateway→capability→repository，而非直接调helper。旧adapter反向引用与autonomous边界只增加精确D路径/符号例外及负向测试，不删全局检查。

## 3. 输入输出合同
### 3.1 Demand / selection
服务器重建 `DraftScope`：user/session、draft_id/version/content_hash、source_run/input_revision、节点ID/目标hash、canonical subject/version/facets/purpose、registry/policy坐标。调用方/模型传入的 hash 不能取代服务器查验。

selection粒度固定为**整份draft快照，内部含逐node/用途结果**，不是每node独立handle；后续bindings引用其中exact node/goal/purpose和selection digest。

`MaterialSelectionResult` 至少含：server opaque handle、合同版本、完整draft scope、demand/selection digest、逐节点/用途 exact evidence candidates、覆盖摘要、gap/前置阻断原因、已存在的真实 preparation job handle（如有）、生成时authority摘要。不输出凭空job、正文、私钥、原始搜索词或learner文本。

状态为内部 bounded `disabled/pending/gap/partial/ready`：无已提交job不能只写pending；partial保留逐节点缺口；总ready要求该需求的全部必须facet/用途和前置依赖满足。对补充用途ready不外推到主教材/评分。历史selection里的ready只是时点事实，消费时重验。

### 3.2 Frozen binding V2
绑定每个 draft/node/purpose 的有界exact证据集合：原A binding身份、document revision/hash、chunk ID/hash/获审excerpt身份、source review/admission/授权generation/policy、corpus ID/active generation/summary/validation/registry、检索与coverage摘要、claim+独立性/执行坐标（若用途需要）、selection handle/hash、版本化binding hash。

多文档取证先canonical排序并去重；哈希仅用于完整性，真实性来自current resolvers。绑定不复制全文，也不是长期通行证；重读/供题要当前授权。

## 4. 实际消费链与草案转换
1. 读取当前草案，在短事务构造server demand；退出事务。
2. 合格已有池优先选择。若不足，仅调用既有受控B端口提交typed需求（须已授权且不在消费事务内），或返回gap；existing_only不执行新增发现。D不创造新scheduler/重试框架。
3. 保存选择快照；把受控安全反馈投影交给**既有规划模型**，不添加外部搜索/provider、不携带网页指令。模型IO不处于DB事务中，预算/取消沿用现有planning runtime。
4. 模型修订使用既有authority创建的显式新planning run/input_revision。在开始provider前，同一短事务锁当前session/parent并**一次性认领**已保存parent selection到exact target run/input_revision，持久保存 `MaterialFeedbackRef` 全坐标及assignment digest。context loader按target run/revision读取该关联，不查询“最新selection”；再次检查当前parent/session CAS。capability append前再重验同一关联、run未取消及parent CAS。一次显式修订最多处理一轮反馈，绝不在同一幂等run硬append第二稿。取消/重启后不另投旧关联；新run重试须重新核验并生成新selection，再认领。
5. 模型返回新稿后核验 parent→successor、用户/会话、完整目标与节点依赖。旧handle仅证明反馈来源，不对新稿授信。**针对新draft重新计算需求、重新选择/核验并生成新handle**；即使文字未变也不直接搬旧authority。
6. 同一短事务锁定当前session/draft并CAS；以新scope重验selection及current authority，持久冻结可用节点的exact bindings并保留不可用节点缺口。并发新revision/撤权/expiry使本次写入整笔回滚。
7. 不改变公开confirm DTO或旧confirm行为，不自动activate track。D 内部服务的成功不等于用户确认、公开release或Gate通过。

真实内部接线使用既有 provider gateway / capability / draft repository 的代码路径和显式注入；测试模型 transport 替身可证明消费顺序和持久写入，不宣称真实provider已运行。

## 5. 存储与幂等
两张新表名：`rag_material_selections`、`rag_plan_material_bindings`。
- selection：UUID/opaque handle、user/session/draft FK及version/hash、整稿需求/反馈hash和逐节点受控snapshot、producer/policy version、created_at、完整作用域idempotency key。snapshot与selection digest写后不可变。另有可空target_run_id/target_input_revision/expected_session_version/assignment_digest/assigned_at；五者必须全空或全满。唯一受限UPDATE允许全空→一次全满，使用当前parent/session CAS与同事务run scope核验，之后禁止重绑定/清空；普通UPDATE仍拒绝。assignment digest绑定user/session/parent draft版本hash/selection handle与digest/target run与revision/expected_session_version。对target run/revision设唯一约束，一个target不能认领两个selection，一个selection不能投给两个target。关联不改snapshot hash，不授新稿信任，也不让模型自报MaterialFeedbackRef。
- binding：UUID、successor selection FK与digest、同scope draft身份、node/goal/purpose、exact evidence有界JSON及digest、created_at、同scope幂等键。唯一自然键为 `(draft_id,node_id,goal_hash,purpose)`，每项只能冻结一组canonical evidence；不只按selection UUID匹配，必须重验exact draft/节点/目标/用途/hash链。同key同内容重放，异内容冲突；即使换retry key，相同自然键不同证据也冲突。同内容重放也需current授权才能返回本次可用，否则只保留历史receipt并拒绝消费。授权失效后不UPDATE旧binding；需要重新选择并经受控新稿/修订产生新绑定，不新增第二current-version权威。
- FK和CHECK匹配既有user/session/draft复合身份，payload在Python边界严格extra-forbid/长度限制并在DB做基本形状/用途约束。新增索引限scope查验和重放，不建第二active pointer。
- 除selection指定的一次性关联外业务更新/删除禁止。获准purge沿 `local_user_data_repository.py` 既有active-run终止与transaction-local `aearn.learning_track_purge_user_id`：同事务先binding再selection（含target关联），再旧draft/session/scope，最后既有run清理。新增run FK不能阻断此顺序；普通业务不得借purge改历史。分别验证reset/delete、事务失败回滚、其他用户与共享corpus不变；本轮不执行真实用户删除。
- 新表只存用户级坐标/安全投影，保留政策沿既有草案生命周期；共享corpus不随用户清理而删除。旧source_summary、draft hash、v1 payload完全不变。

## 6. 当前授权与publication fence
接口：
- `resolve_evidence(conn, demand, draft_scope, ...) -> MaterialSelectionResult`
- `check_current_authorization(conn, binding, purpose, ...) -> AuthorizationReceipt`
- `assert_publication_fence(conn, binding, exact_item_claims, expected_generation, ...) -> AuthorizationReceipt`

以上是真实DB adapter的同连接调用，不把纯policy token当DB锁。fence要求调用方已进入短写事务，禁止self-commit、自开连接、TTL缓存、网络/provider。题库owner在该事务保存receipt及publication/materialization；D只用隔离测试表证明原子性，不写正式item代码。

复核链：exact corpus/version/summary/validation → doc/chunk/approved excerpt → review/admission → capture/retention → registered policy 或 candidate policy/grant/root → 当前active pointer/generation → final clock/flags/scope。所有真实路径仍由C current verifier判断，不读一行SQL就说可信。

锁设计以现有C顺序为基线：session/draft（仅冻结）→ exact corpus version → 有序source/link/review/admission → capture/policy/grant/root（沿既有resolver顺序）→ active pointer。同subject多source稳定排序；不得先拿pointer再拿version与activate/rollback相反。重用既有pointer advisory/CAS和冲突row share锁；不存在pointer直接not_ready，不以空行SELECT声称锁定。读取遵循READ COMMITTED并在锁等待后重新读当前行。

实施须列清每个authority writer（admission撤权、policy/retention/grant/root、pointer activate/rollback）的实际锁/UPDATE，逐项记录writer→冲突锁/更新行→两种barrier顺序→等待后current重读/clock_timestamp→事务回滚断言；必要的小型同序修复计入D，不能修改其权限语义。双连接barrier证明两种顺序，无死锁；遇到无法局部修复的全局事务重构先回规划，不能把缺口写成已统一。

期限在最后fence以DB当前时刻核验，纯单测可注入clock；不使用事务开始时间把长等待后的过期变有效。fence的断言点不保证任意延迟提交后仍未过期，调用方须紧贴正式写入并保持短事务，供题再验；E负责全部真实入口合同。

assessment分支复用现有review_claim/authorize_assessment_claim与受信resolver ports。缺真实PG claim/执行适配器时明确CLAIM_VERIFICATION_REQUIRED/EXECUTION_UNVERIFIED；测试注入可信fixture仅证明合同。D交付strict callable、current deny和注入可信synthetic isolated-PG正负原子性；**当前真实assessment ready、真实item publication/materialization/供题保持blocked/not_executed**。可信生产claim/执行resolver及题库全部入口是E/相应owner的真实前置，D不新造审核/执行服务，不用补充片段替代评分信任。

内部错误复用A枚举并增加必要的D scope/事务码：DRAFT_REVISION_STALE、NODE_GOAL_MISMATCH、BINDING_MISMATCH、CORPUS_GENERATION_STALE、SOURCE_AUTHORIZATION_STALE、TRANSACTION_REQUIRED；安全化映射，不扩公开API错误合同。

## 7. 兼容、验证边界与回退
- C authorizers当前只接受`aearn_rag260_c_*`隔离库；D保留此guard，用新专用测试库，不改业务库、不复用C真实capture库。
- schema fragment可部署并不意味着consumer启用；批准实施默认先运行隔离测试；真实API/公开资料已有项目持续授权，具备项目人工费用监控和当前来源政策后可运行并单列证据，不重复申请同范围权限。关闭D组合停止新消费，不删历史binding，历史可读也不能绕当前用途授权。
- 回退保留新增表/历史，撤回D内部composition，不能盲目逆迁移或重置C/用户数据。
- 实现后才更新docs/README.md指定的runtime/database/QA文档与backend spec；当前计划不把未来设计写成已实施。
- 对比旧数据库/源码hash、旧fixture、旧public snapshot，单列真实provider/current source/public consumer/E尚未执行。

## 9. 项目持续运行授权（2026-09-27更新）
遵循 `docs/setup/project-external-resource-policy.md` 与核算状态登记；300元是跨任务总额，不是每个run额度。既有B预算是root/period资源单位，目前没有证据证明已覆盖全部模型API人民币费用；开发期由用户监控账单，不以建设统一计费基础设施为调用前置，也不能把文档登记冒充runtime硬限额。此更新不新增D审核系统、不启用公开消费者、不修改旧回执、不宣称已实测。

2026-09-27 费用策略补充：侧会话转达用户选择人工监控供应商账单；该政策取代本稿历史“先实现自动费用预留才能调用”的限制，300元总额与其他授权边界不变。

## 实施收敛补充
实际D反馈和完整parent snapshot进入required facts而非易被挤掉的SYSTEM摘要；按现有1200字符分片并严格比较实际序列化值，仍受8项/总token上限。两者由context_for_run在同一个外层短事务成对取得。scope策略只可选择已批准版本/facets/用途，不能更换Python/SQL课程Subject。具体验收与既存失败见research/implementation-verification.md。
