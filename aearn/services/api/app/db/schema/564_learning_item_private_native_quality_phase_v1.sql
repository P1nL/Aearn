-- C20: one fixed committed B, one independent original-owner quality-only phase.
-- Frozen <=563 untouched. Six new functions / three triggers; no copies or old prosrc patches.
-- Caller owns Q0 TOP; full commit before original quality. No author/resettlement/restart/lease renewal.
DO $install564$
DECLARE spec record; prior record; expected_names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='564 isolated PRIVATE database required'; END IF;
 IF to_regprocedure('item_supply_internal.private_native_quality_phase_ready()') IS NULL AND (
  EXISTS(SELECT 1 FROM public.tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
   AND (j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' OR j.payload_json->>'schema_version'='private_native_quality_phase_v1'))
  OR EXISTS(SELECT 1 FROM public.tutor_item_supply_private_jobs j JOIN public.tutor_item_supply_private_job_controls c ON c.job_id=j.id
   WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
   AND j.job_key=encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871','UTF8')),'hex') AND c.lease_generation>0))
 THEN RAISE check_violation USING MESSAGE='564 preexisting unguarded quality authority denied'; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_native_quality_phase_first_claim(uuid,uuid,uuid,uuid)', 'private_native_quality_phase_first_claim(p_completion uuid,p_job uuid,p_batch uuid,p_origin uuid)', 'public.tutor_item_supply_private_job_controls', true, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
 binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 phase_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 mapping_row public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE;
 source_end timestamptz; stamp timestamptz; deadline timestamptz; identity uuid;
 target_job uuid; target_batch uuid; expected_body jsonb; ref_json jsonb; quality_deadline timestamptz;
BEGIN
 IF p_completion IS DISTINCT FROM 'db9b6e57-21c0-4e19-8e99-01ca1ddfa871'::uuid THEN RAISE check_violation USING MESSAGE='564 fixed committed B required'; END IF;
 IF item_supply_internal.private_native_quality_phase_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='564 exact installed quality receivers required'; END IF;
 -- Historical DATA only; private_native_epoch starts the canonical exposure/user/epoch lock domain.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON (p.track_id,p.user_id,p.revision_id)=(s.track_id,s.user_id,s.revision_id)
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Original562 locks original task/root/aux/approval/old controls, without demanding an unexpired old writer.
 SELECT d.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data('755b5f67-bee2-47c9-bc2f-ec7790b97f4d') d;
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb' FOR SHARE;
 SELECT j.payload_json INTO complete_body FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='755b5f67-bee2-47c9-bc2f-ec7790b97f4d' FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context'; ref_json:=ctx->'ref';
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id='c8057dcb-a110-45fa-ab0b-46cd91c99191';
 IF completion_row.id IS DISTINCT FROM 'db9b6e57-21c0-4e19-8e99-01ca1ddfa871'::uuid
  OR completion_row.payload_hash IS DISTINCT FROM '96caf0f71a8b97e7bcd0066e22f5fdb58f8082bda1f754cf9372321ea033b972'
  OR completion_row.payload_json->>'binding_id' IS DISTINCT FROM '755b5f67-bee2-47c9-bc2f-ec7790b97f4d'
  OR completion_row.payload_json->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb'
  OR completion_row.payload_json->>'writer_job_id' IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'
  OR completion_row.payload_json->>'artifact_id' IS DISTINCT FROM 'c8057dcb-a110-45fa-ab0b-46cd91c99191'
  OR completion_row.payload_json->>'candidate_id' IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'
  OR completion_row.payload_json->>'version_id' IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'
  OR completion_row.payload_json->>'checkpoint_id' IS DISTINCT FROM '60be139b-058f-4db7-aa9d-f68a332f89eb'
  OR complete_body->>'original_settlement_id' IS DISTINCT FROM 'b621b72c-48d0-4ab9-9e94-0f98a0df30d6'
  OR complete_body->>'bound_top_xid'=pg_current_xact_id()::text
  OR completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text
  OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR artifact.id IS NULL OR artifact.job_id IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'::uuid
  OR artifact.version_id IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'::uuid OR artifact.candidate_id IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'::uuid
  OR artifact.artifact_hash IS DISTINCT FROM completion_row.payload_json->>'artifact_hash'
  OR output_row.payload_json->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR ref_json->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  OR ref_json->>'pack_task_id' IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  OR ref_json->>'user_id' IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' OR ref_json->>'epoch' IS DISTINCT FROM '1'
  OR ref_json->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR ref_json->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
  OR ref_json->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c' OR ref_json->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ref_json->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
 THEN RAISE check_violation USING MESSAGE='564 fixed committed B required'; END IF;
 target_job:=p_job; target_batch:=p_batch; origin_id:=p_origin;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=target_job FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=target_job FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=target_batch FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871','UTF8')),'hex')
  OR ctrl.profile_snapshot_json->>'schema_version' IS DISTINCT FROM 'item_supply_job_snapshot_v1'
  OR item_supply_internal.snapshot_keys(ctrl.profile_snapshot_json,ARRAY['schema_version','profile','retry_policy']) IS DISTINCT FROM true
  OR ctrl.profile_snapshot_json->'profile'->>'profile_hash' IS DISTINCT FROM profile_row.profile_hash
  OR ctrl.profile_snapshot_json->'profile'->>'profile_key_hash' IS DISTINCT FROM profile_row.profile_key_hash
  OR ctrl.profile_snapshot_json->'profile'->'values' IS DISTINCT FROM profile_row.profile_json->'last_stable'
  OR ctrl.profile_snapshot_json->'profile'->>'profile_version' IS DISTINCT FROM profile_row.profile_json->>'version'
  OR ctrl.profile_snapshot_json->'retry_policy'->>'max_transient_attempts' IS DISTINCT FROM '1'
  OR ctrl.profile_snapshot_json->'profile'->'values'->>'request_timeout_ms' IS DISTINCT FROM '100000'
  OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM 'deepseek'
  OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM 'deepseek-flash'
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.quality_only.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-native-quality-only-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_committed_generation_new_quality_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR (ctrl.profile_snapshot_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'parent_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
  AND (j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' OR (j.payload_json->>'schema_version'='private_native_quality_phase_v1'
   AND j.payload_json->>'completion_id'='db9b6e57-21c0-4e19-8e99-01ca1ddfa871')))
 THEN RAISE check_violation USING MESSAGE='564 quality phase already allocated'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND r.epoch=1 AND r.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND r.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND (r.reservation_key LIKE 'private.native.review.%' OR r.reservation_key LIKE 'review.%'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'job_id' IN(target_job::text,'5dfe6762-b974-4ec4-a36c-2af7d3d342b0')
   AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='564 quality preparation TOP contains later work'; END IF;
 IF ctrl.state IS DISTINCT FROM 'queued' OR ctrl.state_version<>1 OR ctrl.lease_generation<>0 OR ctrl.attempt_count<>0
  OR ctrl.breaker_open OR ctrl.lease_owner IS NOT NULL OR ctrl.lease_expires_at IS NOT NULL
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=job_row.user_id AND j.epoch=job_row.epoch
   AND (j.payload_json->>'job_id'=target_job::text OR j.payload_json->>'writer_job_id'=target_job::text OR j.payload_json->'lease'->>'job_id'=target_job::text))
 THEN RAISE check_violation USING MESSAGE='564 exact unclaimed quality job required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Real material policy/evidence expiry, NOT the short-lived TOP origin expiry, bounds the new lease.
 SELECT min(LEAST(policy.retention_until,policy.expires_at,cap.retention_until,r.period_end,r.delegation_expires_at,evidence.expires_at)) INTO source_end
 FROM jsonb_array_elements(ctx->'request'->'materials') material
 CROSS JOIN LATERAL jsonb_array_elements(material->'binding'->'evidence') e
 JOIN rag_source_reviews review ON review.id=(e->>'source_review_id')::uuid
 JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
 JOIN rag_registered_source_captures cap ON cap.id=review.registered_capture_id AND cap.policy_id=policy.policy_id
 JOIN rag_source_admissions ad ON ad.review_id=review.id AND ad.receipt_handle=e->'binding'->>'admission_receipt_id'
 JOIN rag_budget_authority_roots r ON r.root_id=review.root_id AND r.root_id=policy.root_id
 LEFT JOIN rag_assessment_source_evidence evidence ON evidence.id=review.assessment_evidence_id;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=origin_id;
 IF source_end IS NULL OR origin_row.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 stamp:=clock_timestamp();
 deadline:=LEAST(ctrl.parent_deadline,stamp+interval '3600 seconds',batch_row.valid_until,source_end,
  (ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz+(ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF deadline IS NULL OR ctrl.available_at>stamp OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF deadline-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='564 full original7 quality margin required'; END IF;
 UPDATE tutor_item_supply_private_job_controls c SET state='leased',state_version=2,lease_generation=1,attempt_count=1,
  lease_owner='private.quality.db9b6e5721c04e198e9901ca1ddfa871',lease_expires_at=deadline,updated_at=stamp
  WHERE c.id=ctrl.id AND c.state='queued' AND c.state_version=1 AND c.lease_generation=0 AND c.attempt_count=0 RETURNING c.* INTO ctrl;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='564 exact unclaimed quality job required'; END IF;
 -- The control deferred trigger closes Q even when caller omits bind entirely.
 RETURN NEXT ctrl; RETURN;
END;$src$),
 ('private_native_quality_phase_bind(uuid,uuid,uuid,uuid)', 'private_native_quality_phase_bind(p_completion uuid,p_job uuid,p_batch uuid,p_origin uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
 binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 phase_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 mapping_row public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE;
 source_end timestamptz; stamp timestamptz; deadline timestamptz; identity uuid;
 target_job uuid; target_batch uuid; expected_body jsonb; ref_json jsonb; quality_deadline timestamptz;
BEGIN
 IF p_completion IS DISTINCT FROM 'db9b6e57-21c0-4e19-8e99-01ca1ddfa871'::uuid THEN RAISE check_violation USING MESSAGE='564 fixed committed B required'; END IF;
 IF item_supply_internal.private_native_quality_phase_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='564 exact installed quality receivers required'; END IF;
 -- Historical DATA only; private_native_epoch starts the canonical exposure/user/epoch lock domain.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON (p.track_id,p.user_id,p.revision_id)=(s.track_id,s.user_id,s.revision_id)
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Original562 locks original task/root/aux/approval/old controls, without demanding an unexpired old writer.
 SELECT d.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data('755b5f67-bee2-47c9-bc2f-ec7790b97f4d') d;
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb' FOR SHARE;
 SELECT j.payload_json INTO complete_body FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='755b5f67-bee2-47c9-bc2f-ec7790b97f4d' FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context'; ref_json:=ctx->'ref';
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id='c8057dcb-a110-45fa-ab0b-46cd91c99191';
 IF completion_row.id IS DISTINCT FROM 'db9b6e57-21c0-4e19-8e99-01ca1ddfa871'::uuid
  OR completion_row.payload_hash IS DISTINCT FROM '96caf0f71a8b97e7bcd0066e22f5fdb58f8082bda1f754cf9372321ea033b972'
  OR completion_row.payload_json->>'binding_id' IS DISTINCT FROM '755b5f67-bee2-47c9-bc2f-ec7790b97f4d'
  OR completion_row.payload_json->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb'
  OR completion_row.payload_json->>'writer_job_id' IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'
  OR completion_row.payload_json->>'artifact_id' IS DISTINCT FROM 'c8057dcb-a110-45fa-ab0b-46cd91c99191'
  OR completion_row.payload_json->>'candidate_id' IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'
  OR completion_row.payload_json->>'version_id' IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'
  OR completion_row.payload_json->>'checkpoint_id' IS DISTINCT FROM '60be139b-058f-4db7-aa9d-f68a332f89eb'
  OR complete_body->>'original_settlement_id' IS DISTINCT FROM 'b621b72c-48d0-4ab9-9e94-0f98a0df30d6'
  OR complete_body->>'bound_top_xid'=pg_current_xact_id()::text
  OR completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text
  OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR artifact.id IS NULL OR artifact.job_id IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'::uuid
  OR artifact.version_id IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'::uuid OR artifact.candidate_id IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'::uuid
  OR artifact.artifact_hash IS DISTINCT FROM completion_row.payload_json->>'artifact_hash'
  OR output_row.payload_json->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR ref_json->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  OR ref_json->>'pack_task_id' IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  OR ref_json->>'user_id' IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' OR ref_json->>'epoch' IS DISTINCT FROM '1'
  OR ref_json->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR ref_json->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
  OR ref_json->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c' OR ref_json->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ref_json->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
 THEN RAISE check_violation USING MESSAGE='564 fixed committed B required'; END IF;
 target_job:=p_job; target_batch:=p_batch; origin_id:=p_origin;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=target_job FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=target_job FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=target_batch FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871','UTF8')),'hex')
  OR ctrl.profile_snapshot_json->>'schema_version' IS DISTINCT FROM 'item_supply_job_snapshot_v1'
  OR item_supply_internal.snapshot_keys(ctrl.profile_snapshot_json,ARRAY['schema_version','profile','retry_policy']) IS DISTINCT FROM true
  OR ctrl.profile_snapshot_json->'profile'->>'profile_hash' IS DISTINCT FROM profile_row.profile_hash
  OR ctrl.profile_snapshot_json->'profile'->>'profile_key_hash' IS DISTINCT FROM profile_row.profile_key_hash
  OR ctrl.profile_snapshot_json->'profile'->'values' IS DISTINCT FROM profile_row.profile_json->'last_stable'
  OR ctrl.profile_snapshot_json->'profile'->>'profile_version' IS DISTINCT FROM profile_row.profile_json->>'version'
  OR ctrl.profile_snapshot_json->'retry_policy'->>'max_transient_attempts' IS DISTINCT FROM '1'
  OR ctrl.profile_snapshot_json->'profile'->'values'->>'request_timeout_ms' IS DISTINCT FROM '100000'
  OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM 'deepseek'
  OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM 'deepseek-flash'
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.quality_only.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-native-quality-only-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_committed_generation_new_quality_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR (ctrl.profile_snapshot_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'parent_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
  AND (j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' OR (j.payload_json->>'schema_version'='private_native_quality_phase_v1'
   AND j.payload_json->>'completion_id'='db9b6e57-21c0-4e19-8e99-01ca1ddfa871')))
 THEN RAISE check_violation USING MESSAGE='564 quality phase already allocated'; END IF;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=target_job;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND p.epoch=1 AND p.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND p.record_kind='phase' AND p.operation_key='private.phase.'||target_job::text;
 lease_json:=phase_row.payload_json->'lease';
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (target_job::text,'private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.quality.db9b6e5721c04e198e9901ca1ddfa871','1','2')
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'expires_at')::timestamptz IS DISTINCT FROM ctrl.lease_expires_at
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR ctrl.lease_owner IS DISTINCT FROM 'private.quality.db9b6e5721c04e198e9901ca1ddfa871' OR ctrl.state IS DISTINCT FROM 'leased'
  OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.breaker_open
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM ctrl.parent_deadline
  OR phase_row.intent_hash IS DISTINCT FROM completion_row.intent_hash
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',target_job,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',ref_json->'goal_scope_id','ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until')
  OR ((phase_row.payload_json->>'valid_until')::timestamptz=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,
   (lease_json->'profile'->>'bound_at')::timestamptz+(lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 -- Refresh only the assertion value. Stored binding/phase snapshots remain at state_version2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','6739d3c5-6619-44ce-970f-0ab1e49f3acc');
 IF ctrl.state_version<>2 OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job)
 THEN RAISE check_violation USING MESSAGE='564 exact first-claimed quality job required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND r.epoch=1 AND r.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND r.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND (r.reservation_key LIKE 'private.native.review.%' OR r.reservation_key LIKE 'review.%'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'job_id' IN(target_job::text,'5dfe6762-b974-4ec4-a36c-2af7d3d342b0')
   AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='564 quality preparation TOP contains later work'; END IF;
 IF (SELECT count(*) FROM tutor_item_supply_private_budget_windows w WHERE w.user_id=job_row.user_id AND w.epoch=job_row.epoch
  AND w.scope_id=job_row.scope_id AND w.root_id=job_row.root_id AND w.provider_key='deepseek' AND w.pool_key='enhancement'
  AND w.window_start<=(lease_json->'profile'->>'bound_at')::timestamptz AND w.window_end>=ctrl.parent_deadline)<>1
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Real material policy/evidence expiry, NOT the short-lived TOP origin expiry, bounds the new lease.
 SELECT min(LEAST(policy.retention_until,policy.expires_at,cap.retention_until,r.period_end,r.delegation_expires_at,evidence.expires_at)) INTO source_end
 FROM jsonb_array_elements(ctx->'request'->'materials') material
 CROSS JOIN LATERAL jsonb_array_elements(material->'binding'->'evidence') e
 JOIN rag_source_reviews review ON review.id=(e->>'source_review_id')::uuid
 JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
 JOIN rag_registered_source_captures cap ON cap.id=review.registered_capture_id AND cap.policy_id=policy.policy_id
 JOIN rag_source_admissions ad ON ad.review_id=review.id AND ad.receipt_handle=e->'binding'->>'admission_receipt_id'
 JOIN rag_budget_authority_roots r ON r.root_id=review.root_id AND r.root_id=policy.root_id
 LEFT JOIN rag_assessment_source_evidence evidence ON evidence.id=review.assessment_evidence_id;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=origin_id;
 IF source_end IS NULL OR origin_row.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',job_row.user_id,'epoch',job_row.epoch,
  'scope_id',job_row.scope_id,'job_id',target_job,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Final source/accounting/phase waits precede every authority clock. The TOP origin is not a frozen lease bound.
 stamp:=clock_timestamp();
 quality_deadline:=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
  (phase_row.payload_json->>'valid_until')::timestamptz);
 IF quality_deadline IS NULL OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=quality_deadline OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF quality_deadline-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='564 full original7 quality margin required'; END IF;
 body:=jsonb_build_object('bound_top_xid',pg_current_xact_id()::text);
 expected_body:=jsonb_build_object('schema_version','private_native_quality_phase_v1',
  'completion_id',completion_row.id,'completion_hash',completion_row.payload_hash,'persistence_binding_id','755b5f67-bee2-47c9-bc2f-ec7790b97f4d',
  'output_id',output_row.id,'output_hash',output_row.payload_hash,'artifact_id',artifact.id,'artifact_hash',artifact.artifact_hash,
  'version_id',artifact.version_id,'generation_request_hash',output_row.payload_json->>'request_hash',
  'generation_profile_hash',ctx->'request'->'profile'->'profile_hash','persistence_job_id','5dfe6762-b974-4ec4-a36c-2af7d3d342b0',
  'writer_job_id',target_job,'writer_profile_hash',lease_json->'profile'->'profile_hash','batch_id',target_batch,
  'ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until','bound_top_xid',body->'bound_top_xid');
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(gen_random_uuid(),'6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','private_status','private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871',completion_row.intent_hash,expected_body) RETURNING * INTO binding_row;
 RETURN NEXT binding_row; RETURN;
END;$src$),
 ('private_native_quality_phase_bound(uuid,uuid)', 'private_native_quality_phase_bound(p_binding uuid,p_origin uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
 binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 phase_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 mapping_row public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE;
 source_end timestamptz; stamp timestamptz; deadline timestamptz; identity uuid;
 target_job uuid; target_batch uuid; expected_body jsonb; ref_json jsonb; quality_deadline timestamptz;
BEGIN
 IF item_supply_internal.private_native_quality_phase_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='564 exact installed quality receivers required'; END IF;
 -- Locator read is deny-only: same full TOP, including a released savepoint, is never committed authority.
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_binding;
 IF binding_row.id IS NULL OR binding_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
 THEN RAISE check_violation USING MESSAGE='564 prior-TOP quality phase required'; END IF;
 -- Historical DATA only; private_native_epoch starts the canonical exposure/user/epoch lock domain.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON (p.track_id,p.user_id,p.revision_id)=(s.track_id,s.user_id,s.revision_id)
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Original562 locks original task/root/aux/approval/old controls, without demanding an unexpired old writer.
 SELECT d.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data('755b5f67-bee2-47c9-bc2f-ec7790b97f4d') d;
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb' FOR SHARE;
 SELECT j.payload_json INTO complete_body FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='755b5f67-bee2-47c9-bc2f-ec7790b97f4d' FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context'; ref_json:=ctx->'ref';
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id='c8057dcb-a110-45fa-ab0b-46cd91c99191';
 IF completion_row.id IS DISTINCT FROM 'db9b6e57-21c0-4e19-8e99-01ca1ddfa871'::uuid
  OR completion_row.payload_hash IS DISTINCT FROM '96caf0f71a8b97e7bcd0066e22f5fdb58f8082bda1f754cf9372321ea033b972'
  OR completion_row.payload_json->>'binding_id' IS DISTINCT FROM '755b5f67-bee2-47c9-bc2f-ec7790b97f4d'
  OR completion_row.payload_json->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb'
  OR completion_row.payload_json->>'writer_job_id' IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'
  OR completion_row.payload_json->>'artifact_id' IS DISTINCT FROM 'c8057dcb-a110-45fa-ab0b-46cd91c99191'
  OR completion_row.payload_json->>'candidate_id' IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'
  OR completion_row.payload_json->>'version_id' IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'
  OR completion_row.payload_json->>'checkpoint_id' IS DISTINCT FROM '60be139b-058f-4db7-aa9d-f68a332f89eb'
  OR complete_body->>'original_settlement_id' IS DISTINCT FROM 'b621b72c-48d0-4ab9-9e94-0f98a0df30d6'
  OR complete_body->>'bound_top_xid'=pg_current_xact_id()::text
  OR completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text
  OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR artifact.id IS NULL OR artifact.job_id IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'::uuid
  OR artifact.version_id IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'::uuid OR artifact.candidate_id IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'::uuid
  OR artifact.artifact_hash IS DISTINCT FROM completion_row.payload_json->>'artifact_hash'
  OR output_row.payload_json->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR ref_json->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  OR ref_json->>'pack_task_id' IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  OR ref_json->>'user_id' IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' OR ref_json->>'epoch' IS DISTINCT FROM '1'
  OR ref_json->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR ref_json->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
  OR ref_json->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c' OR ref_json->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ref_json->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
 THEN RAISE check_violation USING MESSAGE='564 fixed committed B required'; END IF;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j
  WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' AND j.record_kind='private_status' FOR SHARE;
 body:=binding_row.payload_json;
 IF binding_row.id IS DISTINCT FROM p_binding THEN RAISE check_violation USING MESSAGE='564 exact quality binding DATA required'; END IF;
 target_job:=(body->>'writer_job_id')::uuid; target_batch:=(body->>'batch_id')::uuid; origin_id:=p_origin;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=target_job FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=target_job FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=target_batch FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871','UTF8')),'hex')
  OR ctrl.profile_snapshot_json->>'schema_version' IS DISTINCT FROM 'item_supply_job_snapshot_v1'
  OR item_supply_internal.snapshot_keys(ctrl.profile_snapshot_json,ARRAY['schema_version','profile','retry_policy']) IS DISTINCT FROM true
  OR ctrl.profile_snapshot_json->'profile'->>'profile_hash' IS DISTINCT FROM profile_row.profile_hash
  OR ctrl.profile_snapshot_json->'profile'->>'profile_key_hash' IS DISTINCT FROM profile_row.profile_key_hash
  OR ctrl.profile_snapshot_json->'profile'->'values' IS DISTINCT FROM profile_row.profile_json->'last_stable'
  OR ctrl.profile_snapshot_json->'profile'->>'profile_version' IS DISTINCT FROM profile_row.profile_json->>'version'
  OR ctrl.profile_snapshot_json->'retry_policy'->>'max_transient_attempts' IS DISTINCT FROM '1'
  OR ctrl.profile_snapshot_json->'profile'->'values'->>'request_timeout_ms' IS DISTINCT FROM '100000'
  OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM 'deepseek'
  OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM 'deepseek-flash'
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.quality_only.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-native-quality-only-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_committed_generation_new_quality_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR (ctrl.profile_snapshot_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'parent_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=target_job;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND p.epoch=1 AND p.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND p.record_kind='phase' AND p.operation_key='private.phase.'||target_job::text;
 lease_json:=phase_row.payload_json->'lease';
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (target_job::text,'private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.quality.db9b6e5721c04e198e9901ca1ddfa871','1','2')
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'expires_at')::timestamptz IS DISTINCT FROM ctrl.lease_expires_at
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR ctrl.lease_owner IS DISTINCT FROM 'private.quality.db9b6e5721c04e198e9901ca1ddfa871' OR ctrl.state IS DISTINCT FROM 'leased'
  OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.breaker_open
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM ctrl.parent_deadline
  OR phase_row.intent_hash IS DISTINCT FROM completion_row.intent_hash
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',target_job,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',ref_json->'goal_scope_id','ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until')
  OR ((phase_row.payload_json->>'valid_until')::timestamptz=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,
   (lease_json->'profile'->>'bound_at')::timestamptz+(lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 -- Refresh only the assertion value. Stored binding/phase snapshots remain at state_version2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','6739d3c5-6619-44ce-970f-0ab1e49f3acc');
 expected_body:=jsonb_build_object('schema_version','private_native_quality_phase_v1',
  'completion_id',completion_row.id,'completion_hash',completion_row.payload_hash,'persistence_binding_id','755b5f67-bee2-47c9-bc2f-ec7790b97f4d',
  'output_id',output_row.id,'output_hash',output_row.payload_hash,'artifact_id',artifact.id,'artifact_hash',artifact.artifact_hash,
  'version_id',artifact.version_id,'generation_request_hash',output_row.payload_json->>'request_hash',
  'generation_profile_hash',ctx->'request'->'profile'->'profile_hash','persistence_job_id','5dfe6762-b974-4ec4-a36c-2af7d3d342b0',
  'writer_job_id',target_job,'writer_profile_hash',lease_json->'profile'->'profile_hash','batch_id',target_batch,
  'ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until','bound_top_xid',body->'bound_top_xid');
 IF body IS DISTINCT FROM expected_body
  OR binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871',completion_row.intent_hash)
  OR binding_row.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(body)
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
   AND (j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' OR (j.payload_json->>'schema_version'='private_native_quality_phase_v1'
    AND j.payload_json->>'completion_id'='db9b6e57-21c0-4e19-8e99-01ca1ddfa871')))<>1
 THEN RAISE check_violation USING MESSAGE='564 exact quality binding DATA required'; END IF;
 IF binding_row.created_at>(clock_timestamp()) OR binding_row.created_at<(lease_json->'profile'->>'bound_at')::timestamptz
  OR ctrl.lease_expires_at>binding_row.created_at+interval '3600 seconds'
 THEN RAISE check_violation USING MESSAGE='564 exact quality binding DATA required'; END IF;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job AND k.stage='generating' AND k.attempt=1;
 IF checkpoint.id IS NULL OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
  (job_row.user_id,job_row.epoch,job_row.scope_id,target_job,'generating',1,'completed',1,artifact.artifact_hash,'private_committed_generation_inherited')
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 IF ctrl.state_version<3 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF (SELECT count(*) FROM tutor_item_supply_private_budget_windows w WHERE w.user_id=job_row.user_id AND w.epoch=job_row.epoch
  AND w.scope_id=job_row.scope_id AND w.root_id=job_row.root_id AND w.provider_key='deepseek' AND w.pool_key='enhancement'
  AND w.window_start<=(lease_json->'profile'->>'bound_at')::timestamptz AND w.window_end>=ctrl.parent_deadline)<>1
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Real material policy/evidence expiry, NOT the short-lived TOP origin expiry, bounds the new lease.
 SELECT min(LEAST(policy.retention_until,policy.expires_at,cap.retention_until,r.period_end,r.delegation_expires_at,evidence.expires_at)) INTO source_end
 FROM jsonb_array_elements(ctx->'request'->'materials') material
 CROSS JOIN LATERAL jsonb_array_elements(material->'binding'->'evidence') e
 JOIN rag_source_reviews review ON review.id=(e->>'source_review_id')::uuid
 JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
 JOIN rag_registered_source_captures cap ON cap.id=review.registered_capture_id AND cap.policy_id=policy.policy_id
 JOIN rag_source_admissions ad ON ad.review_id=review.id AND ad.receipt_handle=e->'binding'->>'admission_receipt_id'
 JOIN rag_budget_authority_roots r ON r.root_id=review.root_id AND r.root_id=policy.root_id
 LEFT JOIN rag_assessment_source_evidence evidence ON evidence.id=review.assessment_evidence_id;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=origin_id;
 IF source_end IS NULL OR origin_row.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',job_row.user_id,'epoch',job_row.epoch,
  'scope_id',job_row.scope_id,'job_id',target_job,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Final source/accounting/phase waits precede every authority clock. The TOP origin is not a frozen lease bound.
 stamp:=clock_timestamp();
 quality_deadline:=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
  (phase_row.payload_json->>'valid_until')::timestamptz);
 IF quality_deadline IS NULL OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=quality_deadline OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Legal validation/review progress is allowed; initial no-work and 715s checks belong to Q/adoption/pre-IO, not every later write.
 RETURN NEXT binding_row; RETURN;
END;$src$),
 ('enforce_private_native_quality_phase_insert()', 'enforce_private_native_quality_phase_insert()', 'trigger', false, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
 binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 phase_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 mapping_row public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE;
 source_end timestamptz; stamp timestamptz; deadline timestamptz; identity uuid;
 target_job uuid; target_batch uuid; expected_body jsonb; ref_json jsonb; quality_deadline timestamptz;
BEGIN
 body:=NEW.payload_json;
 IF body->>'schema_version' IS DISTINCT FROM 'private_native_quality_phase_v1' AND NEW.operation_key IS DISTINCT FROM 'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' THEN RETURN NEW; END IF;
 IF item_supply_internal.private_native_quality_phase_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='564 exact installed quality receivers required'; END IF;
 -- Historical DATA only; private_native_epoch starts the canonical exposure/user/epoch lock domain.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON (p.track_id,p.user_id,p.revision_id)=(s.track_id,s.user_id,s.revision_id)
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Original562 locks original task/root/aux/approval/old controls, without demanding an unexpired old writer.
 SELECT d.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data('755b5f67-bee2-47c9-bc2f-ec7790b97f4d') d;
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb' FOR SHARE;
 SELECT j.payload_json INTO complete_body FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='755b5f67-bee2-47c9-bc2f-ec7790b97f4d' FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context'; ref_json:=ctx->'ref';
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id='c8057dcb-a110-45fa-ab0b-46cd91c99191';
 IF completion_row.id IS DISTINCT FROM 'db9b6e57-21c0-4e19-8e99-01ca1ddfa871'::uuid
  OR completion_row.payload_hash IS DISTINCT FROM '96caf0f71a8b97e7bcd0066e22f5fdb58f8082bda1f754cf9372321ea033b972'
  OR completion_row.payload_json->>'binding_id' IS DISTINCT FROM '755b5f67-bee2-47c9-bc2f-ec7790b97f4d'
  OR completion_row.payload_json->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb'
  OR completion_row.payload_json->>'writer_job_id' IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'
  OR completion_row.payload_json->>'artifact_id' IS DISTINCT FROM 'c8057dcb-a110-45fa-ab0b-46cd91c99191'
  OR completion_row.payload_json->>'candidate_id' IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'
  OR completion_row.payload_json->>'version_id' IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'
  OR completion_row.payload_json->>'checkpoint_id' IS DISTINCT FROM '60be139b-058f-4db7-aa9d-f68a332f89eb'
  OR complete_body->>'original_settlement_id' IS DISTINCT FROM 'b621b72c-48d0-4ab9-9e94-0f98a0df30d6'
  OR complete_body->>'bound_top_xid'=pg_current_xact_id()::text
  OR completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text
  OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR artifact.id IS NULL OR artifact.job_id IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'::uuid
  OR artifact.version_id IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'::uuid OR artifact.candidate_id IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'::uuid
  OR artifact.artifact_hash IS DISTINCT FROM completion_row.payload_json->>'artifact_hash'
  OR output_row.payload_json->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR ref_json->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  OR ref_json->>'pack_task_id' IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  OR ref_json->>'user_id' IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' OR ref_json->>'epoch' IS DISTINCT FROM '1'
  OR ref_json->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR ref_json->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
  OR ref_json->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c' OR ref_json->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ref_json->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
 THEN RAISE check_violation USING MESSAGE='564 fixed committed B required'; END IF;
 target_job:=(body->>'writer_job_id')::uuid; target_batch:=(body->>'batch_id')::uuid;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=target_job FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=target_job FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=target_batch FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871','UTF8')),'hex')
  OR ctrl.profile_snapshot_json->>'schema_version' IS DISTINCT FROM 'item_supply_job_snapshot_v1'
  OR item_supply_internal.snapshot_keys(ctrl.profile_snapshot_json,ARRAY['schema_version','profile','retry_policy']) IS DISTINCT FROM true
  OR ctrl.profile_snapshot_json->'profile'->>'profile_hash' IS DISTINCT FROM profile_row.profile_hash
  OR ctrl.profile_snapshot_json->'profile'->>'profile_key_hash' IS DISTINCT FROM profile_row.profile_key_hash
  OR ctrl.profile_snapshot_json->'profile'->'values' IS DISTINCT FROM profile_row.profile_json->'last_stable'
  OR ctrl.profile_snapshot_json->'profile'->>'profile_version' IS DISTINCT FROM profile_row.profile_json->>'version'
  OR ctrl.profile_snapshot_json->'retry_policy'->>'max_transient_attempts' IS DISTINCT FROM '1'
  OR ctrl.profile_snapshot_json->'profile'->'values'->>'request_timeout_ms' IS DISTINCT FROM '100000'
  OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM 'deepseek'
  OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM 'deepseek-flash'
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.quality_only.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-native-quality-only-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_committed_generation_new_quality_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR (ctrl.profile_snapshot_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'parent_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
  AND (j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' OR (j.payload_json->>'schema_version'='private_native_quality_phase_v1'
   AND j.payload_json->>'completion_id'='db9b6e57-21c0-4e19-8e99-01ca1ddfa871')))
 THEN RAISE check_violation USING MESSAGE='564 quality phase already allocated'; END IF;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=target_job;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND p.epoch=1 AND p.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND p.record_kind='phase' AND p.operation_key='private.phase.'||target_job::text;
 lease_json:=phase_row.payload_json->'lease';
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (target_job::text,'private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.quality.db9b6e5721c04e198e9901ca1ddfa871','1','2')
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'expires_at')::timestamptz IS DISTINCT FROM ctrl.lease_expires_at
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR ctrl.lease_owner IS DISTINCT FROM 'private.quality.db9b6e5721c04e198e9901ca1ddfa871' OR ctrl.state IS DISTINCT FROM 'leased'
  OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.breaker_open
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM ctrl.parent_deadline
  OR phase_row.intent_hash IS DISTINCT FROM completion_row.intent_hash
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',target_job,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',ref_json->'goal_scope_id','ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until')
  OR ((phase_row.payload_json->>'valid_until')::timestamptz=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,
   (lease_json->'profile'->>'bound_at')::timestamptz+(lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 -- Refresh only the assertion value. Stored binding/phase snapshots remain at state_version2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','6739d3c5-6619-44ce-970f-0ab1e49f3acc');
 IF ctrl.state_version<>2 OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job)
 THEN RAISE check_violation USING MESSAGE='564 exact first-claimed quality job required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND r.epoch=1 AND r.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND r.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND (r.reservation_key LIKE 'private.native.review.%' OR r.reservation_key LIKE 'review.%'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'job_id' IN(target_job::text,'5dfe6762-b974-4ec4-a36c-2af7d3d342b0')
   AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='564 quality preparation TOP contains later work'; END IF;
 IF (SELECT count(*) FROM tutor_item_supply_private_budget_windows w WHERE w.user_id=job_row.user_id AND w.epoch=job_row.epoch
  AND w.scope_id=job_row.scope_id AND w.root_id=job_row.root_id AND w.provider_key='deepseek' AND w.pool_key='enhancement'
  AND w.window_start<=(lease_json->'profile'->>'bound_at')::timestamptz AND w.window_end>=ctrl.parent_deadline)<>1
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 SELECT o.id INTO origin_id FROM tutor_item_supply_private_persistent_pack_journal o
  WHERE o.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND o.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND o.epoch=1 AND o.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
   AND o.record_kind='current_pack_source_origin' AND o.payload_json->>'capture_txid'=pg_current_xact_id()::text
  ORDER BY o.created_at DESC,o.id DESC LIMIT 1;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Real material policy/evidence expiry, NOT the short-lived TOP origin expiry, bounds the new lease.
 SELECT min(LEAST(policy.retention_until,policy.expires_at,cap.retention_until,r.period_end,r.delegation_expires_at,evidence.expires_at)) INTO source_end
 FROM jsonb_array_elements(ctx->'request'->'materials') material
 CROSS JOIN LATERAL jsonb_array_elements(material->'binding'->'evidence') e
 JOIN rag_source_reviews review ON review.id=(e->>'source_review_id')::uuid
 JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
 JOIN rag_registered_source_captures cap ON cap.id=review.registered_capture_id AND cap.policy_id=policy.policy_id
 JOIN rag_source_admissions ad ON ad.review_id=review.id AND ad.receipt_handle=e->'binding'->>'admission_receipt_id'
 JOIN rag_budget_authority_roots r ON r.root_id=review.root_id AND r.root_id=policy.root_id
 LEFT JOIN rag_assessment_source_evidence evidence ON evidence.id=review.assessment_evidence_id;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=origin_id;
 IF source_end IS NULL OR origin_row.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',job_row.user_id,'epoch',job_row.epoch,
  'scope_id',job_row.scope_id,'job_id',target_job,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Final source/accounting/phase waits precede every authority clock. The TOP origin is not a frozen lease bound.
 stamp:=clock_timestamp();
 quality_deadline:=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
  (phase_row.payload_json->>'valid_until')::timestamptz);
 IF quality_deadline IS NULL OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=quality_deadline OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF quality_deadline-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='564 full original7 quality margin required'; END IF;
 IF body->>'bound_top_xid' IS DISTINCT FROM pg_current_xact_id()::text THEN RAISE check_violation USING MESSAGE='564 server preparation TOP required'; END IF;
 -- A stored generated hash is available only AFTER BEFORE triggers. Validate its exact formula locally here; atomic/bound read the real stored hash.
 NEW.created_at:=stamp; binding_row:=NEW; binding_row.payload_hash:=item_supply_internal.snapshot_hash(body);
 expected_body:=jsonb_build_object('schema_version','private_native_quality_phase_v1',
  'completion_id',completion_row.id,'completion_hash',completion_row.payload_hash,'persistence_binding_id','755b5f67-bee2-47c9-bc2f-ec7790b97f4d',
  'output_id',output_row.id,'output_hash',output_row.payload_hash,'artifact_id',artifact.id,'artifact_hash',artifact.artifact_hash,
  'version_id',artifact.version_id,'generation_request_hash',output_row.payload_json->>'request_hash',
  'generation_profile_hash',ctx->'request'->'profile'->'profile_hash','persistence_job_id','5dfe6762-b974-4ec4-a36c-2af7d3d342b0',
  'writer_job_id',target_job,'writer_profile_hash',lease_json->'profile'->'profile_hash','batch_id',target_batch,
  'ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until','bound_top_xid',body->'bound_top_xid');
 IF body IS DISTINCT FROM expected_body
  OR binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871',completion_row.intent_hash)
  OR binding_row.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(body)
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
   AND (j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' OR (j.payload_json->>'schema_version'='private_native_quality_phase_v1'
    AND j.payload_json->>'completion_id'='db9b6e57-21c0-4e19-8e99-01ca1ddfa871')))<>0
 THEN RAISE check_violation USING MESSAGE='564 exact quality binding DATA required'; END IF;
 IF binding_row.created_at>(clock_timestamp()) OR binding_row.created_at<(lease_json->'profile'->>'bound_at')::timestamptz
  OR ctrl.lease_expires_at>binding_row.created_at+interval '3600 seconds'
 THEN RAISE check_violation USING MESSAGE='564 exact quality binding DATA required'; END IF;
 RETURN NEW;
END;$src$),
 ('enforce_private_native_quality_phase_atomic()', 'enforce_private_native_quality_phase_atomic()', 'trigger', false, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
 binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 phase_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 mapping_row public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE;
 source_end timestamptz; stamp timestamptz; deadline timestamptz; identity uuid;
 target_job uuid; target_batch uuid; expected_body jsonb; ref_json jsonb; quality_deadline timestamptz;
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_private_job_controls' THEN
  -- No WHEN deparser dependency: exact original first-claim edge only; all ordinary controls return unchanged.
  IF OLD.lease_generation<>0 OR NEW.lease_generation<=0 THEN RETURN NEW; END IF;
  SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=NEW.job_id;
  IF (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,job_row.job_key) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid,
    encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871','UTF8')),'hex')) THEN RETURN NEW; END IF;
  target_job:=NEW.job_id;
 ELSE
  body:=NEW.payload_json;
  IF body->>'schema_version' IS DISTINCT FROM 'private_native_quality_phase_v1' AND NEW.operation_key IS DISTINCT FROM 'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' THEN RETURN NEW; END IF;
  target_job:=(body->>'writer_job_id')::uuid;
 END IF;
 IF item_supply_internal.private_native_quality_phase_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='564 exact installed quality receivers required'; END IF;
 -- Historical DATA only; private_native_epoch starts the canonical exposure/user/epoch lock domain.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON (p.track_id,p.user_id,p.revision_id)=(s.track_id,s.user_id,s.revision_id)
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Original562 locks original task/root/aux/approval/old controls, without demanding an unexpired old writer.
 SELECT d.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data('755b5f67-bee2-47c9-bc2f-ec7790b97f4d') d;
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb' FOR SHARE;
 SELECT j.payload_json INTO complete_body FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='755b5f67-bee2-47c9-bc2f-ec7790b97f4d' FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context'; ref_json:=ctx->'ref';
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id='c8057dcb-a110-45fa-ab0b-46cd91c99191';
 IF completion_row.id IS DISTINCT FROM 'db9b6e57-21c0-4e19-8e99-01ca1ddfa871'::uuid
  OR completion_row.payload_hash IS DISTINCT FROM '96caf0f71a8b97e7bcd0066e22f5fdb58f8082bda1f754cf9372321ea033b972'
  OR completion_row.payload_json->>'binding_id' IS DISTINCT FROM '755b5f67-bee2-47c9-bc2f-ec7790b97f4d'
  OR completion_row.payload_json->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb'
  OR completion_row.payload_json->>'writer_job_id' IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'
  OR completion_row.payload_json->>'artifact_id' IS DISTINCT FROM 'c8057dcb-a110-45fa-ab0b-46cd91c99191'
  OR completion_row.payload_json->>'candidate_id' IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'
  OR completion_row.payload_json->>'version_id' IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'
  OR completion_row.payload_json->>'checkpoint_id' IS DISTINCT FROM '60be139b-058f-4db7-aa9d-f68a332f89eb'
  OR complete_body->>'original_settlement_id' IS DISTINCT FROM 'b621b72c-48d0-4ab9-9e94-0f98a0df30d6'
  OR complete_body->>'bound_top_xid'=pg_current_xact_id()::text
  OR completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text
  OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR artifact.id IS NULL OR artifact.job_id IS DISTINCT FROM '5dfe6762-b974-4ec4-a36c-2af7d3d342b0'::uuid
  OR artifact.version_id IS DISTINCT FROM '192c9f88-afa4-4470-b47e-9a966695430c'::uuid OR artifact.candidate_id IS DISTINCT FROM '05e16768-e4c5-4a6d-80db-7038af56ec2b'::uuid
  OR artifact.artifact_hash IS DISTINCT FROM completion_row.payload_json->>'artifact_hash'
  OR output_row.payload_json->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR ref_json->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  OR ref_json->>'pack_task_id' IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  OR ref_json->>'user_id' IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' OR ref_json->>'epoch' IS DISTINCT FROM '1'
  OR ref_json->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR ref_json->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
  OR ref_json->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c' OR ref_json->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ref_json->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
 THEN RAISE check_violation USING MESSAGE='564 fixed committed B required'; END IF;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j
  WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' AND j.record_kind='private_status' FOR SHARE;
 body:=binding_row.payload_json;
 IF binding_row.id IS NULL OR body->>'writer_job_id' IS DISTINCT FROM target_job::text
  OR body->>'bound_top_xid' IS DISTINCT FROM pg_current_xact_id()::text
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 target_batch:=(body->>'batch_id')::uuid;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=target_job FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=target_job FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=target_batch FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871','UTF8')),'hex')
  OR ctrl.profile_snapshot_json->>'schema_version' IS DISTINCT FROM 'item_supply_job_snapshot_v1'
  OR item_supply_internal.snapshot_keys(ctrl.profile_snapshot_json,ARRAY['schema_version','profile','retry_policy']) IS DISTINCT FROM true
  OR ctrl.profile_snapshot_json->'profile'->>'profile_hash' IS DISTINCT FROM profile_row.profile_hash
  OR ctrl.profile_snapshot_json->'profile'->>'profile_key_hash' IS DISTINCT FROM profile_row.profile_key_hash
  OR ctrl.profile_snapshot_json->'profile'->'values' IS DISTINCT FROM profile_row.profile_json->'last_stable'
  OR ctrl.profile_snapshot_json->'profile'->>'profile_version' IS DISTINCT FROM profile_row.profile_json->>'version'
  OR ctrl.profile_snapshot_json->'retry_policy'->>'max_transient_attempts' IS DISTINCT FROM '1'
  OR ctrl.profile_snapshot_json->'profile'->'values'->>'request_timeout_ms' IS DISTINCT FROM '100000'
  OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM 'deepseek'
  OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM 'deepseek-flash'
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.quality_only.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-native-quality-only-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_committed_generation_new_quality_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR (ctrl.profile_snapshot_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'parent_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=target_job;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND p.epoch=1 AND p.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND p.record_kind='phase' AND p.operation_key='private.phase.'||target_job::text;
 lease_json:=phase_row.payload_json->'lease';
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (target_job::text,'private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.quality.db9b6e5721c04e198e9901ca1ddfa871','1','2')
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'expires_at')::timestamptz IS DISTINCT FROM ctrl.lease_expires_at
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR ctrl.lease_owner IS DISTINCT FROM 'private.quality.db9b6e5721c04e198e9901ca1ddfa871' OR ctrl.state IS DISTINCT FROM 'leased'
  OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.breaker_open
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM ctrl.parent_deadline
  OR phase_row.intent_hash IS DISTINCT FROM completion_row.intent_hash
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',target_job,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',ref_json->'goal_scope_id','ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until')
  OR ((phase_row.payload_json->>'valid_until')::timestamptz=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,
   (lease_json->'profile'->>'bound_at')::timestamptz+(lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 -- Refresh only the assertion value. Stored binding/phase snapshots remain at state_version2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','6739d3c5-6619-44ce-970f-0ab1e49f3acc');
 expected_body:=jsonb_build_object('schema_version','private_native_quality_phase_v1',
  'completion_id',completion_row.id,'completion_hash',completion_row.payload_hash,'persistence_binding_id','755b5f67-bee2-47c9-bc2f-ec7790b97f4d',
  'output_id',output_row.id,'output_hash',output_row.payload_hash,'artifact_id',artifact.id,'artifact_hash',artifact.artifact_hash,
  'version_id',artifact.version_id,'generation_request_hash',output_row.payload_json->>'request_hash',
  'generation_profile_hash',ctx->'request'->'profile'->'profile_hash','persistence_job_id','5dfe6762-b974-4ec4-a36c-2af7d3d342b0',
  'writer_job_id',target_job,'writer_profile_hash',lease_json->'profile'->'profile_hash','batch_id',target_batch,
  'ref',ref_json,'lease',lease_json,'valid_until',phase_row.payload_json->'valid_until','bound_top_xid',body->'bound_top_xid');
 IF body IS DISTINCT FROM expected_body
  OR binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871',completion_row.intent_hash)
  OR binding_row.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(body)
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
   AND (j.operation_key='private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871' OR (j.payload_json->>'schema_version'='private_native_quality_phase_v1'
    AND j.payload_json->>'completion_id'='db9b6e57-21c0-4e19-8e99-01ca1ddfa871')))<>1
 THEN RAISE check_violation USING MESSAGE='564 exact quality binding DATA required'; END IF;
 IF binding_row.created_at>(clock_timestamp()) OR binding_row.created_at<(lease_json->'profile'->>'bound_at')::timestamptz
  OR ctrl.lease_expires_at>binding_row.created_at+interval '3600 seconds'
 THEN RAISE check_violation USING MESSAGE='564 exact quality binding DATA required'; END IF;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job AND k.stage='generating' AND k.attempt=1;
 IF checkpoint.id IS NULL OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
  (job_row.user_id,job_row.epoch,job_row.scope_id,target_job,'generating',1,'completed',1,artifact.artifact_hash,'private_committed_generation_inherited')
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 IF ctrl.state_version<>3 OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job AND k.id<>checkpoint.id)
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND r.epoch=1 AND r.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND r.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND (r.reservation_key LIKE 'private.native.review.%' OR r.reservation_key LIKE 'review.%'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'job_id' IN(target_job::text,'5dfe6762-b974-4ec4-a36c-2af7d3d342b0')
   AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='564 quality preparation TOP contains later work'; END IF;
 IF (SELECT count(*) FROM tutor_item_supply_private_budget_windows w WHERE w.user_id=job_row.user_id AND w.epoch=job_row.epoch
  AND w.scope_id=job_row.scope_id AND w.root_id=job_row.root_id AND w.provider_key='deepseek' AND w.pool_key='enhancement'
  AND w.window_start<=(lease_json->'profile'->>'bound_at')::timestamptz AND w.window_end>=ctrl.parent_deadline)<>1
 THEN RAISE check_violation USING MESSAGE='564 complete accounting phase and inherited checkpoint required before commit'; END IF;
 SELECT o.id INTO origin_id FROM tutor_item_supply_private_persistent_pack_journal o
  WHERE o.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND o.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND o.epoch=1 AND o.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
   AND o.record_kind='current_pack_source_origin' AND o.payload_json->>'capture_txid'=pg_current_xact_id()::text
  ORDER BY o.created_at DESC,o.id DESC LIMIT 1;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Real material policy/evidence expiry, NOT the short-lived TOP origin expiry, bounds the new lease.
 SELECT min(LEAST(policy.retention_until,policy.expires_at,cap.retention_until,r.period_end,r.delegation_expires_at,evidence.expires_at)) INTO source_end
 FROM jsonb_array_elements(ctx->'request'->'materials') material
 CROSS JOIN LATERAL jsonb_array_elements(material->'binding'->'evidence') e
 JOIN rag_source_reviews review ON review.id=(e->>'source_review_id')::uuid
 JOIN rag_registered_source_policies policy ON policy.policy_id=review.policy_id AND policy.source_handle=review.source_handle
 JOIN rag_registered_source_captures cap ON cap.id=review.registered_capture_id AND cap.policy_id=policy.policy_id
 JOIN rag_source_admissions ad ON ad.review_id=review.id AND ad.receipt_handle=e->'binding'->>'admission_receipt_id'
 JOIN rag_budget_authority_roots r ON r.root_id=review.root_id AND r.root_id=policy.root_id
 LEFT JOIN rag_assessment_source_evidence evidence ON evidence.id=review.assessment_evidence_id;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=origin_id;
 IF source_end IS NULL OR origin_row.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',job_row.user_id,'epoch',job_row.epoch,
  'scope_id',job_row.scope_id,'job_id',target_job,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 -- Final source/accounting/phase waits precede every authority clock. The TOP origin is not a frozen lease bound.
 stamp:=clock_timestamp();
 quality_deadline:=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
  (phase_row.payload_json->>'valid_until')::timestamptz);
 IF quality_deadline IS NULL OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=quality_deadline OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='564 current quality phase and SOURCE required'; END IF;
 IF quality_deadline-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='564 full original7 quality margin required'; END IF;
 RETURN NEW;
END;$src$),
 ('private_native_quality_phase_ready()', 'private_native_quality_phase_ready()', 'boolean', false, $src$DECLARE spec record; actual record; names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' OR item_supply_internal.private_generation_persistence_phase_ready() IS DISTINCT FROM true THEN RETURN false; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_native_quality_phase_first_claim(uuid,uuid,uuid,uuid)','private_native_quality_phase_first_claim(p_completion uuid,p_job uuid,p_batch uuid,p_origin uuid)','public.tutor_item_supply_private_job_controls',true,'4d7ab128610a75fb41254a3db01675dacb7bccf00138b10319bbffb0828555c5'),
 ('private_native_quality_phase_bind(uuid,uuid,uuid,uuid)','private_native_quality_phase_bind(p_completion uuid,p_job uuid,p_batch uuid,p_origin uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'c50a5a8f94340d342d1e01c7672dcdd45aa6e45fa6c38427b836d2dbf4486f21'),
 ('private_native_quality_phase_bound(uuid,uuid)','private_native_quality_phase_bound(p_binding uuid,p_origin uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'ace05fe31d457027b3933baa5c67edffca48ef73b09d0b6c8d234073a6df1f10'),
 ('enforce_private_native_quality_phase_insert()','enforce_private_native_quality_phase_insert()','trigger',false,'4c7cbe257ff3f0ee7565b7a88b4a51381cb0364a53a749409cfe2e60cc38f70a'),
 ('enforce_private_native_quality_phase_atomic()','enforce_private_native_quality_phase_atomic()','trigger',false,'2feb98ae10afb52138018f55db51d001c8468cf9af5a5ae46313bad55aab4c63'),
 ('private_native_quality_phase_ready()','private_native_quality_phase_ready()','boolean',false,NULL::text)
 ) AS expected(signature,header,result_type,is_set,body_sha) LOOP
  SELECT array_agg(split_part(btrim(a),' ',1) ORDER BY n) INTO names
   FROM unnest(string_to_array(substring(spec.header FROM '\((.*)\)$'),',')) WITH ORDINALITY args(a,n) WHERE btrim(a)<>'';
  SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.'||spec.signature);
  IF NOT FOUND OR actual.prosecdef IS DISTINCT FROM true OR actual.prokind<>'f'
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.prorettype IS DISTINCT FROM to_regtype(spec.result_type) OR actual.proargnames IS DISTINCT FROM names
   OR actual.pronargs IS DISTINCT FROM COALESCE(cardinality(names),0)
   OR actual.proretset IS DISTINCT FROM spec.is_set OR actual.provolatile<>'v' OR actual.proisstrict OR actual.proleakproof OR actual.proparallel<>'u'
   OR actual.procost<>100 OR actual.prorows IS DISTINCT FROM (CASE WHEN spec.is_set THEN 1000::real ELSE 0::real END)
   OR actual.prosupport<>0 OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL OR actual.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   OR (spec.body_sha IS NOT NULL AND encode(sha256(convert_to(actual.prosrc,'UTF8')),'hex') IS DISTINCT FROM spec.body_sha)
  THEN RETURN false; END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','a000_private_native_quality_phase_insert','enforce_private_native_quality_phase_insert',7,false),
  ('tutor_item_supply_private_persistent_pack_journal','private_native_quality_phase_atomic','enforce_private_native_quality_phase_atomic',5,true),
  ('tutor_item_supply_private_job_controls','private_native_quality_phase_claim_atomic','enforce_private_native_quality_phase_atomic',17,true)
 ) AS expected(table_name,trigger_name,function_name,trigger_type,deferred) LOOP
  SELECT t.* INTO actual FROM pg_trigger t WHERE t.tgrelid=to_regclass('public.'||tr.table_name) AND t.tgname=tr.trigger_name;
  IF NOT FOUND OR actual.tgfoid IS DISTINCT FROM to_regprocedure('item_supply_internal.'||tr.function_name||'()')
   OR actual.tgtype IS DISTINCT FROM tr.trigger_type OR actual.tgenabled<>'O' OR actual.tgisinternal
   OR actual.tgdeferrable IS DISTINCT FROM tr.deferred OR actual.tginitdeferred IS DISTINCT FROM tr.deferred
   OR actual.tgnargs<>0 OR actual.tgqual IS NOT NULL OR actual.tgattr::text<>'' OR actual.tgargs<>''::bytea
   OR actual.tgparentid<>0 OR actual.tgconstrrelid<>0 OR actual.tgconstrindid<>0
   OR actual.tgoldtable IS NOT NULL OR actual.tgnewtable IS NOT NULL
   OR (NOT tr.deferred AND actual.tgconstraint<>0)
   OR (tr.deferred AND NOT EXISTS(SELECT 1 FROM pg_constraint k WHERE k.oid=actual.tgconstraint AND k.contype='t'
    AND k.conname=tr.trigger_name AND k.conrelid=actual.tgrelid AND k.condeferrable AND k.condeferred AND k.convalidated)) THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END;$src$)
 ) AS definitions(signature,header,result_type,is_set,body) LOOP
  SELECT array_agg(split_part(btrim(argument),' ',1) ORDER BY ord) INTO expected_names
   FROM unnest(string_to_array(substring(spec.header FROM '\((.*)\)$'),',')) WITH ORDINALITY args(argument,ord) WHERE btrim(argument)<>'';
  SELECT p.* INTO prior FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.'||spec.signature);
  IF FOUND THEN
   IF prior.prosrc IS DISTINCT FROM spec.body OR prior.prosecdef IS DISTINCT FROM true OR prior.prokind<>'f'
   OR prior.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR prior.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR prior.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR prior.prorettype IS DISTINCT FROM to_regtype(spec.result_type) OR prior.proargnames IS DISTINCT FROM expected_names
   OR prior.pronargs IS DISTINCT FROM COALESCE(cardinality(expected_names),0)
   OR prior.proretset IS DISTINCT FROM spec.is_set OR prior.provolatile<>'v' OR prior.proisstrict OR prior.proleakproof OR prior.proparallel<>'u'
   OR prior.procost<>100 OR prior.prorows IS DISTINCT FROM (CASE WHEN spec.is_set THEN 1000::real ELSE 0::real END)
   OR prior.prosupport<>0 OR prior.provariadic<>0 OR prior.pronargdefaults<>0 OR prior.proargdefaults IS NOT NULL
   OR prior.proallargtypes IS NOT NULL OR prior.proargmodes IS NOT NULL OR prior.probin IS NOT NULL
   OR prior.prosqlbody IS NOT NULL OR prior.protrftypes IS NOT NULL OR prior.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   THEN RAISE check_violation USING MESSAGE='564 unexpected existing receiver definition/metadata: '||spec.signature; END IF;
  ELSE
   EXECUTE 'CREATE FUNCTION item_supply_internal.'||spec.header||' RETURNS '||CASE WHEN spec.is_set THEN 'SETOF ' ELSE '' END||spec.result_type||
    ' LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS '||quote_literal(spec.body);
   EXECUTE 'ALTER FUNCTION item_supply_internal.'||spec.signature||' OWNER TO aearn_b1d_runtime_20261001';
   EXECUTE 'REVOKE ALL ON FUNCTION item_supply_internal.'||spec.signature||' FROM PUBLIC';
  END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','a000_private_native_quality_phase_insert','enforce_private_native_quality_phase_insert',7,false,
   'CREATE TRIGGER a000_private_native_quality_phase_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_quality_phase_insert()'),
  ('tutor_item_supply_private_persistent_pack_journal','private_native_quality_phase_atomic','enforce_private_native_quality_phase_atomic',5,true,
   'CREATE CONSTRAINT TRIGGER private_native_quality_phase_atomic AFTER INSERT ON public.tutor_item_supply_private_persistent_pack_journal DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_quality_phase_atomic()'),
  ('tutor_item_supply_private_job_controls','private_native_quality_phase_claim_atomic','enforce_private_native_quality_phase_atomic',17,true,
   'CREATE CONSTRAINT TRIGGER private_native_quality_phase_claim_atomic AFTER UPDATE ON public.tutor_item_supply_private_job_controls DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_quality_phase_atomic()')
 ) AS triggers(table_name,trigger_name,function_name,trigger_type,deferred,ddl) LOOP
  SELECT t.* INTO prior FROM pg_trigger t WHERE t.tgrelid=to_regclass('public.'||tr.table_name) AND t.tgname=tr.trigger_name;
  IF FOUND THEN
   IF prior.tgfoid IS DISTINCT FROM to_regprocedure('item_supply_internal.'||tr.function_name||'()')
   OR prior.tgtype IS DISTINCT FROM tr.trigger_type OR prior.tgenabled<>'O' OR prior.tgisinternal
   OR prior.tgdeferrable IS DISTINCT FROM tr.deferred OR prior.tginitdeferred IS DISTINCT FROM tr.deferred
   OR prior.tgnargs<>0 OR prior.tgqual IS NOT NULL OR prior.tgattr::text<>'' OR prior.tgargs<>''::bytea
   OR prior.tgparentid<>0 OR prior.tgconstrrelid<>0 OR prior.tgconstrindid<>0
   OR prior.tgoldtable IS NOT NULL OR prior.tgnewtable IS NOT NULL
   OR (NOT tr.deferred AND prior.tgconstraint<>0)
   OR (tr.deferred AND NOT EXISTS(SELECT 1 FROM pg_constraint k WHERE k.oid=prior.tgconstraint AND k.contype='t'
    AND k.conname=tr.trigger_name AND k.conrelid=prior.tgrelid AND k.condeferrable AND k.condeferred AND k.convalidated)) THEN RAISE check_violation USING MESSAGE='564 unexpected existing receiver trigger: '||tr.trigger_name; END IF;
  ELSE EXECUTE tr.ddl; END IF;
 END LOOP;
END;
$install564$;
