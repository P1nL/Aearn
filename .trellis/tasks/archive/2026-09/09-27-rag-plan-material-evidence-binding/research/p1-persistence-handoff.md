# P1 持久化与类型交接（2026-09-27）

## 已落盘接口

模块 `app.services.grounding.material_contracts_v2`：`DraftScope(user_id,conversation_id,session_id,draft_id,draft_version,content_hash,source_run_id,source_input_revision)`；`NodeMaterialRequirement(node_id,goal_hash,prerequisites,demand: LearningMaterialDemand)`；`MaterialSelectionEntry(node_id,goal_hash,purpose,status,covered_facets,gaps,evidence,preparation_job_id)`；`MaterialSelectionResult(handle,draft,requirements,entries,selection_digest)`；`EvidenceBindingV2(selection_handle,selection_digest,draft,node_id,goal_hash,purpose,evidence,binding_digest)`；`MaterialFeedbackRef(selection_handle,selection_digest,draft,target_run_id,target_input_revision,expected_session_version,assignment_digest)`。构建选择/冻结值时先用不含尾部digest的dict调用 `digest(payload)`。读库后会重新解析全部嵌套与摘要。

`EvidenceCoordinate` 精确字段：`binding: RagEvidenceBinding`（A）、`subject_id`（逻辑Subject text）、`corpus_version_id`（260 version UUID）、`active_generation`、`summary_hash`、`validation_hash`（canonical validation_summary_json的独立digest，需resolver校验）、`registry_digest`（260原字段，无虚构整数generation）、`source_review_id`、`source_policy_id/source_policy_generation`、`chunk_id`（260 text key）、`chunk_hash/approved_excerpt_hash/retrieval_hash/coverage_hash`；assessment另有`claim_id/claim_receipt_hash/corroboration_id/execution_receipt_id`。没有URL、全文、原始查询或任意SQL字段。

选择handle格式 `selection.<32 lowercase hex>`。A需求的`plan_ref="draft.<draft UUID>"`、`node_ref="node.<knowledge_key>"`，purpose须分别精确匹配。仓库`goal_hash_for_node(canonical_plan_node_mapping)` 以 knowledge_key/title/description/is_core/prerequisite_keys/required_capabilities/catalog_knowledge_key 计算；不要对模型提供的目标摘要直接授权。仓库record时遍历plan_json并要求每个node至少一条需求。

模块 `app.services.grounding.material_binding_repository.PostgresMaterialBindingRepository(conn)`（同连接身份可读 `repo.conn`；调用方显式READ COMMITTED短写事务，`autocommit=False`且INTRANS；不自开/提交连接）：
- `record_selection(selection, *, idempotency_key) -> MaterialSelectionResult`；`get_selection(*, handle, draft) -> MaterialSelectionResult`；
- `assign_feedback(*, handle, draft, target_run_id, target_input_revision, expected_session_version, current_authorization) -> MaterialFeedbackRef`；`get_feedback_for_target(*, user_id, conversation_id, target_run_id, target_input_revision) -> MaterialFeedbackRef`；
- `freeze_binding(*, binding, idempotency_key, current_authorization) -> EvidenceBindingV2`。

授权callback分别签名 `(conn, MaterialSelectionResult) -> CurrentMaterialAuthorizationReceipt`、`(conn, EvidenceBindingV2) -> CurrentMaterialAuthorizationReceipt`；须真实C/current同连接检查。receipt 严格类型字段 `(kind: selection|binding, object_digest, draft: DraftScope, purposes: sorted unique tuple[Usage,...], authorization_digest, checked_at: aware datetime)`，selection绑定selection_digest及全entry purpose集合，binding绑定binding_digest及单purpose。仓库在callback返回后用DB clock_timestamp校验时间不早于30秒、不在未来，并重验嵌套、exact scope/digest/purpose；None/boolean/任意形状均拒绝。P2可将`check_current_authorization`逐exact证据适配进callback。重放也重验current；binding同自然键、同内容但不同重试key可返回同一行，异内容冲突。父选择只可反馈，successor冻结要其自己的selection handle。按target pair查关联，绝不可查最新selection。DB持久选择snapshot hash不含后续assignment，assignment_digest含full parent/target坐标。

## 接线提醒与边界

主代理注册`370_rag_plan_material_bindings.sql`并在user purge中binding→selection→draft/session/run删除。SQL仅两张用户级表，无第二corpus writer；发布/当前来源权威仍P2/C。default-off组合处不得实例化repository或访问新表。dispatcher现有autocommit=True；仅可在IDLE先切False、开启短事务、退出恢复True，不能弱化repo/C guard，provider IO不在事务。P1专项本地纯测试5 passed、4 PG skipped；PostgreSQL测试由主代理串行执行；这里不调用数据库/外部provider。
