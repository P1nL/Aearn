-- C22: one fixed spent C20 technical predecessor; one explicit successor on the same Artifact.
-- Nine new functions / three triggers / no old patch or new tables. Frozen <=565 untouched.
-- Caller owns Q0 TOP, no savepoint-as-commit authority. Scheduler remains failclosed.
DO $install566$
DECLARE spec record; prior record; expected_names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='566 isolated PRIVATE database required'; END IF;
 IF to_regprocedure('item_supply_internal.private_native_quality_successor_ready()') IS NULL AND (
  EXISTS(SELECT 1 FROM public.tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND (j.operation_key LIKE 'private.quality.successor.5c8e2c140fb845458b011170c96daf86%' OR j.payload_json->>'schema_version' IN('private_native_quality_successor_grant_v1','private_native_quality_successor_binding_v1')))
  OR EXISTS(SELECT 1 FROM public.tutor_item_supply_private_jobs j JOIN public.tutor_item_supply_private_job_controls c ON c.job_id=j.id WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND j.job_key=encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.successor.5c8e2c140fb845458b011170c96daf86','UTF8')),'hex') AND c.lease_generation>0))
 THEN RAISE check_violation USING MESSAGE='566 preexisting unguarded successor authority denied'; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_native_quality_successor_predecessor(uuid)', 'private_native_quality_successor_predecessor(p_predecessor uuid)', 'jsonb', false, $src$DECLARE capture jsonb; ctx jsonb; ref_json jsonb; complete_body jsonb; data jsonb; grant_data jsonb;
 completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 predecessor_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; preparation_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 successor_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; old_phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 old_control public.tutor_item_supply_private_job_controls%ROWTYPE;
 reservation_row public.tutor_item_supply_private_reservations%ROWTYPE;
 settlement_row public.tutor_item_supply_private_runtime_settlements%ROWTYPE;
 validation_row public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 successor_job uuid;
BEGIN
 IF p_predecessor IS DISTINCT FROM '5c8e2c14-0fb8-4545-8b01-1170c96daf86'::uuid THEN RAISE check_violation USING MESSAGE='566 fixed spent technical predecessor required'; END IF;
 -- Historical DATA only; private_native_epoch starts the canonical exposure/user/epoch lock domain.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON (p.track_id,p.user_id,p.revision_id)=(s.track_id,s.user_id,s.revision_id)
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='566 fixed spent technical predecessor required'; END IF;

 SELECT j.* INTO predecessor_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_predecessor FOR SHARE;
 SELECT j.* INTO preparation_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='0fd20bda-3806-4efe-8687-b0b7f0ca3712' FOR SHARE;
 SELECT j.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='3e58e588-7781-4341-9c45-b23eb6cde8a5' FOR SHARE;
 SELECT c.* INTO old_control FROM tutor_item_supply_private_job_controls c WHERE c.job_id='12ee8e9e-0225-4051-a584-cda3d8be8464' FOR UPDATE;
 SELECT j.* INTO old_phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.record_kind='phase' AND j.operation_key='private.phase.12ee8e9e-0225-4051-a584-cda3d8be8464' FOR SHARE;
 SELECT r.* INTO reservation_row FROM tutor_item_supply_private_reservations r WHERE r.id='04651060-9019-41ee-9981-bd61398478fb' FOR SHARE;
 SELECT s.* INTO settlement_row FROM tutor_item_supply_private_runtime_settlements s WHERE s.id='4417e9be-5d7b-4fc0-bdfe-70e53523f464' FOR SHARE;
 SELECT q.* INTO validation_row FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND q.job_id='12ee8e9e-0225-4051-a584-cda3d8be8464' AND q.kind='validation' AND q.payload_json=preparation_row.payload_json->'request'->'validation' FOR SHARE;
 IF predecessor_row.payload_hash IS DISTINCT FROM '5162355a10760c60edd0b73b7b57e0dedc4211e19d59b97d49f6109a999e748e'
  OR preparation_row.payload_hash IS DISTINCT FROM '04c4a5c3e24bb3c668ae773667a990d26c6a9e0914cf3826896f8446b0e7e951'
  OR started_row.payload_hash IS DISTINCT FROM 'e4ee5d982bfafeeacc6063d86cdd1ed9328c70e73b0d96f87d0efe45fd71691e'
  OR (predecessor_row.pack_task_id,predecessor_row.user_id,predecessor_row.epoch,predecessor_row.scope_id,predecessor_row.record_kind,predecessor_row.operation_key,predecessor_row.intent_hash) IS DISTINCT FROM
   (completion_row.pack_task_id,completion_row.user_id,completion_row.epoch,completion_row.scope_id,'private_status','private.quality.phase.db9b6e5721c04e198e9901ca1ddfa871',completion_row.intent_hash)
  OR (preparation_row.pack_task_id,preparation_row.user_id,preparation_row.epoch,preparation_row.scope_id,preparation_row.record_kind,preparation_row.intent_hash) IS DISTINCT FROM
   (predecessor_row.pack_task_id,predecessor_row.user_id,predecessor_row.epoch,predecessor_row.scope_id,'private_attachment',predecessor_row.intent_hash)
  OR (started_row.pack_task_id,started_row.user_id,started_row.epoch,started_row.scope_id,started_row.record_kind,started_row.intent_hash) IS DISTINCT FROM
   (predecessor_row.pack_task_id,predecessor_row.user_id,predecessor_row.epoch,predecessor_row.scope_id,'private_status',predecessor_row.intent_hash)
  OR old_control.id IS NULL OR old_phase.id IS NULL OR reservation_row.id IS NULL OR settlement_row.id IS NULL OR validation_row.id IS NULL
  OR predecessor_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
  OR predecessor_row.payload_json->'ref' IS DISTINCT FROM ref_json
  OR predecessor_row.payload_json->'lease' IS DISTINCT FROM old_phase.payload_json->'lease'
  OR old_control.profile_snapshot_json->'profile' IS DISTINCT FROM predecessor_row.payload_json->'lease'->'profile'
  OR old_control.profile_snapshot_json->'retry_policy' IS DISTINCT FROM predecessor_row.payload_json->'lease'->'retry_policy'
  OR (old_control.lease_owner,old_control.lease_generation,old_control.parent_deadline,old_control.lease_expires_at) IS DISTINCT FROM
   (predecessor_row.payload_json->'lease'->>'lease_owner',1,(predecessor_row.payload_json->'lease'->>'parent_deadline')::timestamptz,(predecessor_row.payload_json->'lease'->>'expires_at')::timestamptz)
  OR preparation_row.payload_json->>'job_id' IS DISTINCT FROM '12ee8e9e-0225-4051-a584-cda3d8be8464'
  OR preparation_row.payload_json->>'reservation_id' IS DISTINCT FROM reservation_row.id::text
  OR preparation_row.payload_json->'request'->>'artifact_id' IS DISTINCT FROM artifact.id::text
  OR preparation_row.payload_json->'request'->'ref' IS DISTINCT FROM ref_json
  OR (reservation_row.user_id,reservation_row.epoch,reservation_row.scope_id,reservation_row.root_id,reservation_row.job_id,reservation_row.lease_generation,reservation_row.requests) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid,'12ee8e9e-0225-4051-a584-cda3d8be8464'::uuid,1,7)
  OR reservation_row.reservation_key NOT LIKE 'private.native.review.%'
  OR (settlement_row.user_id,settlement_row.epoch,settlement_row.scope_id,settlement_row.reservation_id,settlement_row.sequence,settlement_row.settlement_key,settlement_row.usage_state) IS DISTINCT FROM
   (reservation_row.user_id,reservation_row.epoch,reservation_row.scope_id,reservation_row.id,1,'private.native.review.0fd20bda38064efe8687b0b7f0ca3712','unknown')
  OR settlement_row.cost_amount IS NOT NULL OR settlement_row.receipt_hash IS NOT NULL
  OR validation_row.version_id IS DISTINCT FROM artifact.version_id
  OR (SELECT count(*) FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id='12ee8e9e-0225-4051-a584-cda3d8be8464')<>1
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_runtime_settlements s WHERE s.reservation_id=reservation_row.id AND s.id<>settlement_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key=left(started_row.operation_key,length(started_row.operation_key)-8)||'.result')
 THEN RAISE check_violation USING MESSAGE='566 fixed spent technical predecessor required'; END IF;
 -- Only the actual stored successor may add this slot's new quality; historical absence is not a permanent veto.
 SELECT j.* INTO successor_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding' AND j.payload_json->>'schema_version'='private_native_quality_successor_binding_v1';
 successor_job:=(successor_row.payload_json->>'writer_job_id')::uuid;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND q.id<>validation_row.id AND (successor_job IS NULL OR q.job_id<>successor_job OR q.version_id<>artifact.version_id))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=p.quality_id AND q.job_id=successor_job AND q.version_id=artifact.version_id))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND r.epoch=1 AND r.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND r.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND (r.reservation_key LIKE 'private.native.review.%' OR r.reservation_key LIKE 'review.%') AND r.id<>reservation_row.id AND (successor_job IS NULL OR r.job_id<>successor_job))
 THEN RAISE check_violation USING MESSAGE='566 fixed spent technical predecessor required'; END IF;
 grant_data:=jsonb_build_object('schema_version','private_native_quality_successor_grant_v1',
  'predecessor_binding_id',predecessor_row.id,'predecessor_binding_hash',predecessor_row.payload_hash,'predecessor_job_id','12ee8e9e-0225-4051-a584-cda3d8be8464',
  'predecessor_preparation_id',preparation_row.id,'predecessor_preparation_hash',preparation_row.payload_hash,
  'predecessor_reservation_id',reservation_row.id,'predecessor_reservation_hash',item_supply_internal.snapshot_hash(to_jsonb(reservation_row)),
  'predecessor_settlement_id',settlement_row.id,'predecessor_settlement_hash',item_supply_internal.snapshot_hash(to_jsonb(settlement_row)),
  'predecessor_started_id',started_row.id,'predecessor_started_hash',started_row.payload_hash,
  'predecessor_validation_id',validation_row.id,'predecessor_validation_hash',validation_row.payload_hash,
  'completion_id',completion_row.id,'completion_hash',completion_row.payload_hash,'artifact_id',artifact.id,'artifact_hash',artifact.artifact_hash,'version_id',artifact.version_id,'ref',ref_json);
 RETURN jsonb_build_object('grant_data',grant_data,'completion',to_jsonb(completion_row),'output',to_jsonb(output_row),'capture',capture,'artifact',to_jsonb(artifact),'ref',ref_json);
END;$src$),
 ('private_native_quality_successor_frame(uuid,uuid,uuid,uuid)', 'private_native_quality_successor_frame(p_grant uuid,p_job uuid,p_batch uuid,p_origin uuid)', 'jsonb', false, $src$DECLARE data jsonb; capture jsonb; ctx jsonb; ref_json jsonb; lease_json jsonb; body jsonb; expected_body jsonb;
 grant_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; phase_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE; ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 mapping_row public.tutor_item_supply_private_development_model_accounting_jobs%ROWTYPE;
 artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE;
 preparation_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; reservation_row public.tutor_item_supply_private_reservations%ROWTYPE;
 validation_row public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 review_row public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 source_end timestamptz; stamp timestamptz; quality_deadline timestamptz; target_job uuid; target_batch uuid; origin_id uuid;
BEGIN
 data:=item_supply_internal.private_native_quality_successor_predecessor('5c8e2c14-0fb8-4545-8b01-1170c96daf86');
 SELECT j.* INTO grant_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_grant FOR SHARE;
 body:=grant_row.payload_json;
 IF grant_row.id IS NULL OR (grant_row.pack_task_id,grant_row.user_id,grant_row.epoch,grant_row.scope_id,grant_row.record_kind,grant_row.operation_key,grant_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.quality.successor.5c8e2c140fb845458b011170c96daf86.grant',data->'completion'->>'intent_hash')
  OR body IS DISTINCT FROM ((data->'grant_data')||jsonb_build_object('granted_top_xid',body->'granted_top_xid','granted_at',body->'granted_at'))
  OR jsonb_typeof(body->'granted_top_xid') IS DISTINCT FROM 'string' OR (body->>'granted_top_xid')::xid8::text IS DISTINCT FROM body->>'granted_top_xid'
  OR jsonb_typeof(body->'granted_at') IS DISTINCT FROM 'string' OR (body->>'granted_at')::timestamptz IS DISTINCT FROM grant_row.created_at
  OR grant_row.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(body)
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND (j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.grant' OR j.payload_json->>'schema_version'='private_native_quality_successor_grant_v1'))<>1
 THEN RAISE check_violation USING MESSAGE='566 fixed spent technical predecessor required'; END IF;
 capture:=data->'capture'; ctx:=capture->'context'; ref_json:=data->'ref';
 SELECT x.* INTO completion_row FROM jsonb_populate_record(NULL::public.tutor_item_supply_private_persistent_pack_journal,data->'completion') x;
 SELECT x.* INTO output_row FROM jsonb_populate_record(NULL::public.tutor_item_supply_private_persistent_pack_journal,data->'output') x;
 SELECT x.* INTO artifact FROM jsonb_populate_record(NULL::public.tutor_item_supply_private_generation_artifacts,data->'artifact') x;
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
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.successor.5c8e2c140fb845458b011170c96daf86','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.quality_successor.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-native-quality-successor-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_committed_quality_technical_successor_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR (ctrl.profile_snapshot_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
  OR COALESCE((ctrl.profile_snapshot_json->'profile'->'values'->>'parent_deadline_ms')::bigint BETWEEN 1 AND 6000000,false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;

 -- A generation0 frame precedes accounting; a generation1 frame requires the complete immutable initial phase.
 IF ctrl.lease_generation=1 THEN
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=target_job;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND p.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND p.epoch=1 AND p.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND p.record_kind='phase' AND p.operation_key='private.phase.'||target_job::text;
 lease_json:=phase_row.payload_json->'lease';
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (target_job::text,'private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.quality.successor.5c8e2c140fb845458b011170c96daf86','1','2')
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'expires_at')::timestamptz IS DISTINCT FROM ctrl.lease_expires_at
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR ctrl.lease_owner IS DISTINCT FROM 'private.quality.successor.5c8e2c140fb845458b011170c96daf86' OR ctrl.state IS DISTINCT FROM 'leased'
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
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 -- Refresh only the assertion value. Stored binding/phase snapshots remain at state_version2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','6739d3c5-6619-44ce-970f-0ab1e49f3acc');

  IF ctrl.state_version<2 OR (SELECT count(*) FROM tutor_item_supply_private_budget_windows w WHERE w.user_id=job_row.user_id AND w.epoch=job_row.epoch
   AND w.scope_id=job_row.scope_id AND w.root_id=job_row.root_id AND w.provider_key='deepseek' AND w.pool_key='enhancement'
   AND w.window_start<=(lease_json->'profile'->>'bound_at')::timestamptz AND w.window_end>=ctrl.parent_deadline)<>1
  THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 ELSIF ctrl.lease_generation<>0 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 -- Optional original Q1 facts: no new receiver or payload replaces the original7 proof.
 SELECT j.* INTO preparation_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='private_attachment' AND j.payload_json->>'schema_version'='private_native_auxiliary_v1' AND j.payload_json->>'job_id'=target_job::text AND j.payload_json->'request'->>'schema_version'='private_native_review_phase_v1' FOR SHARE;
 SELECT r.* INTO reservation_row FROM tutor_item_supply_private_reservations r WHERE r.id=(preparation_row.payload_json->>'reservation_id')::uuid FOR SHARE;
 SELECT q.* INTO validation_row FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job AND q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND q.kind='validation' FOR SHARE;
 SELECT q.* INTO review_row FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job AND q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND q.kind='review' FOR SHARE;
 IF (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.payload_json->>'job_id'=target_job::text AND j.payload_json->>'schema_version'='private_native_auxiliary_v1')>1
  OR (SELECT count(*) FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job AND q.kind='validation')>1
  OR (SELECT count(*) FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job AND q.kind='review')>1
 THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
 IF preparation_row.id IS NOT NULL AND (
  reservation_row.id IS NULL OR validation_row.id IS NULL
  OR (reservation_row.user_id,reservation_row.epoch,reservation_row.scope_id,reservation_row.root_id,reservation_row.job_id,reservation_row.lease_generation,reservation_row.requests) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,job_row.id,1,7)
  OR reservation_row.reservation_key NOT LIKE 'private.native.review.%'
  OR preparation_row.intent_hash IS DISTINCT FROM grant_row.intent_hash
  OR preparation_row.payload_json->'request'->>'artifact_id' IS DISTINCT FROM artifact.id::text
  OR preparation_row.payload_json->'request'->'ref' IS DISTINCT FROM ref_json
  OR ((preparation_row.payload_json->'request'->'lease') - 'state_version'::text) IS DISTINCT FROM ((lease_json) - 'state_version'::text)
  OR preparation_row.payload_json->'request'->'validation' IS DISTINCT FROM validation_row.payload_json
  OR validation_row.version_id IS DISTINCT FROM artifact.version_id
  OR (preparation_row.payload_json->'request'->'binding'->>'version_key',preparation_row.payload_json->'request'->'binding'->>'candidate_key',preparation_row.payload_json->'request'->'binding'->>'source_hash',preparation_row.payload_json->'request'->'binding'->>'content_hash',preparation_row.payload_json->'request'->'binding'->>'policy_hash',preparation_row.payload_json->'request'->'binding'->>'profile_hash') IS DISTINCT FROM
   (artifact.version_id::text,artifact.candidate_id::text,artifact.receipt_json->>'source_hash',artifact.receipt_json->>'content_hash',item_supply_internal.snapshot_hash(preparation_row.payload_json->'request'->'policy'),lease_json->'profile'->>'profile_hash')
 ) THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 IF ctrl.lease_generation=1 AND item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',job_row.user_id,'epoch',job_row.epoch,
  'scope_id',job_row.scope_id,'job_id',target_job,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 -- Final source/accounting/phase waits precede every authority clock. The TOP origin is not a frozen lease bound.
 stamp:=clock_timestamp();
 quality_deadline:=LEAST(COALESCE(ctrl.lease_expires_at,stamp+interval '3600 seconds'),ctrl.parent_deadline,batch_row.valid_until,source_end,
  (ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz+(ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF quality_deadline IS NULL OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=quality_deadline OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;

 expected_body:=jsonb_build_object('schema_version','private_native_quality_successor_binding_v1',
  'completion_id',completion_row.id,'completion_hash',completion_row.payload_hash,'persistence_binding_id','755b5f67-bee2-47c9-bc2f-ec7790b97f4d',
  'output_id',output_row.id,'output_hash',output_row.payload_hash,'artifact_id',artifact.id,'artifact_hash',artifact.artifact_hash,'version_id',artifact.version_id,
  'generation_request_hash',output_row.payload_json->>'request_hash','generation_profile_hash',ctx->'request'->'profile'->'profile_hash','persistence_job_id','5dfe6762-b974-4ec4-a36c-2af7d3d342b0',
  'writer_job_id',target_job,'writer_profile_hash',lease_json->'profile'->'profile_hash','batch_id',target_batch,'ref',ref_json,'lease',lease_json,
  'valid_until',phase_row.payload_json->'valid_until','bound_top_xid',grant_row.payload_json->'granted_top_xid','grant_id',grant_row.id,'grant_hash',grant_row.payload_hash,'predecessor_binding_id','5c8e2c14-0fb8-4545-8b01-1170c96daf86');
 RETURN jsonb_build_object('grant',to_jsonb(grant_row),'job',to_jsonb(job_row),'control',to_jsonb(ctrl),'phase',to_jsonb(phase_row),'expected_binding',expected_body,
  'preparation',to_jsonb(preparation_row),'reservation',to_jsonb(reservation_row),'validation',to_jsonb(validation_row),'review',to_jsonb(review_row),
  'deadline',quality_deadline,'checked_at',stamp,'ref',ref_json,'artifact_hash',artifact.artifact_hash);
END;$src$),
 ('private_native_quality_successor_grant(uuid,uuid)', 'private_native_quality_successor_grant(p_predecessor uuid,p_origin uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE data jsonb; capture jsonb; ctx jsonb; origin_id uuid:=p_origin; source_end timestamptz; stamp timestamptz; body jsonb;
 origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; grant_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 IF item_supply_internal.private_native_quality_successor_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='566 exact installed successor receivers required'; END IF;
 data:=item_supply_internal.private_native_quality_successor_predecessor(p_predecessor);
 -- The canonical predecessor locks precede every uniqueness/absence test.
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND (j.operation_key LIKE 'private.quality.successor.5c8e2c140fb845458b011170c96daf86%' OR j.payload_json->>'schema_version' IN('private_native_quality_successor_grant_v1','private_native_quality_successor_binding_v1')))
 THEN RAISE check_violation USING MESSAGE='566 successor grant already allocated'; END IF;
 capture:=data->'capture'; ctx:=capture->'context';
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);

 stamp:=clock_timestamp();
 IF stamp>=(origin_row.payload_json->>'valid_until')::timestamptz OR source_end-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 body:=(data->'grant_data')||jsonb_build_object('granted_top_xid',pg_current_xact_id()::text,'granted_at',stamp);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json,created_at)
 VALUES(gen_random_uuid(),'6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','private_status','private.quality.successor.5c8e2c140fb845458b011170c96daf86.grant',data->'completion'->>'intent_hash',body,stamp) RETURNING * INTO grant_row;
 RETURN NEXT grant_row; RETURN;
END;$src$),
 ('private_native_quality_successor_first_claim(uuid,uuid,uuid,uuid)', 'private_native_quality_successor_first_claim(p_grant uuid,p_job uuid,p_batch uuid,p_origin uuid)', 'public.tutor_item_supply_private_job_controls', true, $src$DECLARE frame jsonb; ctrl public.tutor_item_supply_private_job_controls%ROWTYPE; target_job uuid:=p_job; deadline timestamptz; stamp timestamptz;
BEGIN
 IF item_supply_internal.private_native_quality_successor_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='566 exact installed successor receivers required'; END IF;
 frame:=item_supply_internal.private_native_quality_successor_frame(p_grant,p_job,p_batch,p_origin);
 SELECT x.* INTO ctrl FROM jsonb_populate_record(NULL::public.tutor_item_supply_private_job_controls,frame->'control') x;
 IF frame->'grant'->'payload_json'->>'granted_top_xid' IS DISTINCT FROM pg_current_xact_id()::text
  OR ctrl.state IS DISTINCT FROM 'queued' OR ctrl.state_version<>1 OR ctrl.lease_generation<>0 OR ctrl.attempt_count<>0 OR ctrl.breaker_open OR ctrl.lease_owner IS NOT NULL OR ctrl.lease_expires_at IS NOT NULL
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=ctrl.user_id AND j.epoch=ctrl.epoch AND (j.payload_json->>'job_id'=target_job::text OR j.payload_json->>'writer_job_id'=target_job::text OR j.payload_json->'lease'->>'job_id'=target_job::text))
 THEN RAISE check_violation USING MESSAGE='566 exact unclaimed successor quality job required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.payload_json->>'job_id'=target_job::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 stamp:=clock_timestamp(); deadline:=(frame->>'deadline')::timestamptz;
 IF ctrl.available_at>stamp OR deadline-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 UPDATE tutor_item_supply_private_job_controls c SET state='leased',state_version=2,lease_generation=1,attempt_count=1,lease_owner='private.quality.successor.5c8e2c140fb845458b011170c96daf86',lease_expires_at=deadline,updated_at=stamp
  WHERE c.id=ctrl.id AND c.state='queued' AND c.state_version=1 AND c.lease_generation=0 AND c.attempt_count=0 RETURNING c.* INTO ctrl;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='566 exact unclaimed successor quality job required'; END IF;
 RETURN NEXT ctrl; RETURN;
END;$src$),
 ('private_native_quality_successor_bind(uuid,uuid,uuid,uuid)', 'private_native_quality_successor_bind(p_grant uuid,p_job uuid,p_batch uuid,p_origin uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE frame jsonb; body jsonb; target_job uuid:=p_job; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; stamp timestamptz;
BEGIN
 IF item_supply_internal.private_native_quality_successor_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='566 exact installed successor receivers required'; END IF;
 frame:=item_supply_internal.private_native_quality_successor_frame(p_grant,p_job,p_batch,p_origin);
 IF frame->'grant'->'payload_json'->>'granted_top_xid' IS DISTINCT FROM pg_current_xact_id()::text OR frame->'control'->>'state_version' IS DISTINCT FROM '2'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job)
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.payload_json->>'job_id'=target_job::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 stamp:=clock_timestamp();
 IF (frame->>'deadline')::timestamptz-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 body:=frame->'expected_binding';
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json,created_at)
 VALUES(gen_random_uuid(),'6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','private_status','private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding',frame->'grant'->>'intent_hash',body,stamp) RETURNING * INTO binding_row;
 RETURN NEXT binding_row; RETURN;
END;$src$),
 ('private_native_quality_successor_bound(uuid,uuid)', 'private_native_quality_successor_bound(p_binding uuid,p_origin uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE frame jsonb; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; target_job uuid; checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE;
BEGIN
 -- This locator grants nothing: reject same full TOP before any current lease/source checks.
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_binding;
 IF binding_row.id IS NULL OR binding_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
 THEN RAISE check_violation USING MESSAGE='566 prior-TOP successor quality phase required'; END IF;
 IF item_supply_internal.private_native_quality_successor_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='566 exact installed successor receivers required'; END IF;
 target_job:=(binding_row.payload_json->>'writer_job_id')::uuid;
 frame:=item_supply_internal.private_native_quality_successor_frame((binding_row.payload_json->>'grant_id')::uuid,target_job,(binding_row.payload_json->>'batch_id')::uuid,p_origin);
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding',frame->'grant'->>'intent_hash')
  OR binding_row.payload_json IS DISTINCT FROM frame->'expected_binding'
  OR binding_row.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(binding_row.payload_json)
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND (j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding' OR j.payload_json->>'schema_version'='private_native_quality_successor_binding_v1'))<>1
  OR binding_row.created_at<(frame->'control'->'profile_snapshot_json'->'profile'->>'bound_at')::timestamptz
  OR (binding_row.payload_json->'lease'->>'expires_at')::timestamptz>binding_row.created_at+interval '3600 seconds'
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job AND k.stage='generating' AND k.attempt=1;
 IF checkpoint.id IS NULL OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
  ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,target_job,'generating',1,'completed',1,frame->>'artifact_hash','private_committed_generation_inherited')
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 IF (frame->'control'->>'state_version')::integer<3 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 RETURN NEXT binding_row; RETURN;
END;$src$),
 ('enforce_private_native_quality_successor_insert()', 'enforce_private_native_quality_successor_insert()', 'trigger', false, $src$DECLARE data jsonb; frame jsonb; body jsonb:=NEW.payload_json; capture jsonb; ctx jsonb; origin_id uuid; source_end timestamptz; stamp timestamptz;
 origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; target_job uuid;
 review_row public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
BEGIN
 IF NEW.operation_key NOT LIKE 'private.quality.successor.5c8e2c140fb845458b011170c96daf86%' AND COALESCE(body->>'schema_version','') NOT IN('private_native_quality_successor_grant_v1','private_native_quality_successor_binding_v1')
  AND NOT (COALESCE(body->>'schema_version','')='private_native_stage_v1' AND EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding' AND j.payload_json->>'writer_job_id'=body->>'job_id'))
 THEN RETURN NEW; END IF;
 IF  (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.record_kind) IS DISTINCT FROM ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status') OR item_supply_internal.private_native_quality_successor_ready() IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
 IF NEW.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.grant' THEN
  data:=item_supply_internal.private_native_quality_successor_predecessor('5c8e2c14-0fb8-4545-8b01-1170c96daf86');
 SELECT o.id INTO origin_id FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND o.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND o.epoch=1 AND o.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND o.record_kind='current_pack_source_origin' AND o.payload_json->>'capture_txid'=pg_current_xact_id()::text ORDER BY o.created_at DESC,o.id DESC LIMIT 1;
  capture:=data->'capture'; ctx:=capture->'context';
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);

  stamp:=clock_timestamp();
  IF body IS DISTINCT FROM ((data->'grant_data')||jsonb_build_object('granted_top_xid',body->'granted_top_xid','granted_at',body->'granted_at'))
   OR body->>'granted_top_xid' IS DISTINCT FROM pg_current_xact_id()::text OR jsonb_typeof(body->'granted_at') IS DISTINCT FROM 'string'
   OR (body->>'granted_at')::timestamptz>stamp OR NEW.intent_hash IS DISTINCT FROM data->'completion'->>'intent_hash'
   OR source_end-stamp<=interval '715 seconds' OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
  THEN RAISE check_violation USING MESSAGE='566 fixed spent technical predecessor required'; END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND (j.operation_key LIKE 'private.quality.successor.5c8e2c140fb845458b011170c96daf86%' OR j.payload_json->>'schema_version' IN('private_native_quality_successor_grant_v1','private_native_quality_successor_binding_v1')))
  THEN RAISE check_violation USING MESSAGE='566 successor grant already allocated'; END IF;
  NEW.payload_json:=(data->'grant_data')||jsonb_build_object('granted_top_xid',pg_current_xact_id()::text,'granted_at',stamp); NEW.created_at:=stamp;
  RETURN NEW;
 END IF;
 SELECT o.id INTO origin_id FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND o.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND o.epoch=1 AND o.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND o.record_kind='current_pack_source_origin' AND o.payload_json->>'capture_txid'=pg_current_xact_id()::text ORDER BY o.created_at DESC,o.id DESC LIMIT 1;
 IF NEW.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding' THEN
  target_job:=(body->>'writer_job_id')::uuid;
  frame:=item_supply_internal.private_native_quality_successor_frame((body->>'grant_id')::uuid,target_job,(body->>'batch_id')::uuid,origin_id);
  IF body IS DISTINCT FROM frame->'expected_binding' OR body->>'bound_top_xid' IS DISTINCT FROM pg_current_xact_id()::text
   OR NEW.intent_hash IS DISTINCT FROM frame->'grant'->>'intent_hash' OR frame->'control'->>'state_version' IS DISTINCT FROM '2'
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job)
   OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND (j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding' OR j.payload_json->>'schema_version'='private_native_quality_successor_binding_v1'))<>0
  THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.payload_json->>'job_id'=target_job::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
  stamp:=clock_timestamp();
  IF (frame->>'deadline')::timestamptz-stamp<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
  NEW.created_at:=stamp; RETURN NEW;
 END IF;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding';
 PERFORM item_supply_internal.private_native_quality_successor_bound(binding_row.id,origin_id);
 target_job:=(binding_row.payload_json->>'writer_job_id')::uuid;
 frame:=item_supply_internal.private_native_quality_successor_frame((binding_row.payload_json->>'grant_id')::uuid,target_job,(binding_row.payload_json->>'batch_id')::uuid,origin_id);
 IF NEW.operation_key NOT IN('private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started','private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.result') THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=NEW.user_id AND j.epoch=NEW.epoch AND j.operation_key=NEW.operation_key)
 THEN RAISE check_violation USING MESSAGE='566 successor review already consumed'; END IF;
 IF frame->'preparation'->>'id' IS NULL OR frame->'validation'->>'id' IS NULL OR frame->'reservation'->>'id' IS NULL
  OR NEW.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_stage_v1','job_id',target_job,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','stage','review',
   'status',CASE WHEN NEW.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started' THEN 'started' ELSE 'committed' END,
   'subject_hash','86314cb3b81ef99fd59b6e62db7ec15a6d93186a7570aeed37fef4d004ab075a','receipt_id',NEW.payload_json->'receipt_id')
  OR NEW.intent_hash IS DISTINCT FROM frame->'grant'->>'intent_hash'
 THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
 IF NEW.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started' THEN
  IF NEW.payload_json->'receipt_id' IS DISTINCT FROM 'null'::jsonb OR frame->'review'->>'id' IS NOT NULL OR frame->'control'->>'state_version' IS DISTINCT FROM '4'
  THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
  IF (frame->>'deadline')::timestamptz-clock_timestamp()<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 ELSE
  IF NEW.operation_key IS DISTINCT FROM 'private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.result' OR NEW.payload_json->>'receipt_id' IS DISTINCT FROM frame->'review'->>'id'
   OR frame->'review'->>'id' IS NULL OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started' AND j.payload_json->>'job_id'=target_job::text)
  THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
  SELECT x.* INTO review_row FROM jsonb_populate_record(NULL::public.tutor_item_supply_private_native_quality_evidence,frame->'review') x;
  PERFORM item_supply_internal.assert_private_native_review_stage(review_row);
 END IF;
 NEW.created_at:=clock_timestamp(); RETURN NEW;
END;$src$),
 ('enforce_private_native_quality_successor_atomic()', 'enforce_private_native_quality_successor_atomic()', 'trigger', false, $src$DECLARE frame jsonb; grant_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; target_job uuid; origin_id uuid;
 checkpoint public.tutor_item_supply_private_checkpoints%ROWTYPE; review_row public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_private_job_controls' THEN
  IF OLD.lease_generation<>0 OR NEW.lease_generation<=0 THEN RETURN NEW; END IF;
  SELECT j.id INTO target_job FROM tutor_item_supply_private_jobs j WHERE j.id=NEW.job_id AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND j.job_key=encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.quality.successor.5c8e2c140fb845458b011170c96daf86','UTF8')),'hex');
  IF target_job IS NULL THEN RETURN NEW; END IF;
 ELSE
  IF NEW.operation_key NOT IN('private.quality.successor.5c8e2c140fb845458b011170c96daf86.grant','private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding','private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started','private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.result') THEN RETURN NEW; END IF;
 END IF;
 -- Serialise before missing-row checks; claim-only cannot evade the journal's deferred guard.
 PERFORM item_supply_internal.private_native_quality_successor_predecessor('5c8e2c14-0fb8-4545-8b01-1170c96daf86');
 SELECT j.* INTO grant_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.grant' FOR SHARE;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding' FOR SHARE;
 IF grant_row.id IS NULL OR binding_row.id IS NULL OR (target_job IS NOT NULL AND binding_row.payload_json->>'writer_job_id' IS DISTINCT FROM target_job::text)
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 target_job:=(binding_row.payload_json->>'writer_job_id')::uuid;
 SELECT o.id INTO origin_id FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND o.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND o.epoch=1 AND o.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND o.record_kind='current_pack_source_origin' AND o.payload_json->>'capture_txid'=pg_current_xact_id()::text ORDER BY o.created_at DESC,o.id DESC LIMIT 1;
 frame:=item_supply_internal.private_native_quality_successor_frame(grant_row.id,target_job,(binding_row.payload_json->>'batch_id')::uuid,origin_id);
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding',frame->'grant'->>'intent_hash')
  OR binding_row.payload_json IS DISTINCT FROM frame->'expected_binding'
  OR binding_row.payload_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(binding_row.payload_json)
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND (j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.binding' OR j.payload_json->>'schema_version'='private_native_quality_successor_binding_v1'))<>1
  OR binding_row.created_at<(frame->'control'->'profile_snapshot_json'->'profile'->>'bound_at')::timestamptz
  OR (binding_row.payload_json->'lease'->>'expires_at')::timestamptz>binding_row.created_at+interval '3600 seconds'
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job AND k.stage='generating' AND k.attempt=1;
 IF checkpoint.id IS NULL OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
  ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,target_job,'generating',1,'completed',1,frame->>'artifact_hash','private_committed_generation_inherited')
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 IF TG_TABLE_NAME='tutor_item_supply_private_persistent_pack_journal' THEN
  IF NEW.operation_key IN('private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started','private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.result') THEN
   PERFORM item_supply_internal.private_native_quality_successor_bound(binding_row.id,origin_id);
 IF frame->'preparation'->>'id' IS NULL OR frame->'validation'->>'id' IS NULL OR frame->'reservation'->>'id' IS NULL
  OR NEW.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_stage_v1','job_id',target_job,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','stage','review',
   'status',CASE WHEN NEW.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started' THEN 'started' ELSE 'committed' END,
   'subject_hash','86314cb3b81ef99fd59b6e62db7ec15a6d93186a7570aeed37fef4d004ab075a','receipt_id',NEW.payload_json->'receipt_id')
  OR NEW.intent_hash IS DISTINCT FROM frame->'grant'->>'intent_hash'
 THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
 IF NEW.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started' THEN
  IF NEW.payload_json->'receipt_id' IS DISTINCT FROM 'null'::jsonb OR frame->'review'->>'id' IS NOT NULL OR frame->'control'->>'state_version' IS DISTINCT FROM '4'
  THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
  IF (frame->>'deadline')::timestamptz-clock_timestamp()<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 ELSE
  IF NEW.operation_key IS DISTINCT FROM 'private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.result' OR NEW.payload_json->>'receipt_id' IS DISTINCT FROM frame->'review'->>'id'
   OR frame->'review'->>'id' IS NULL OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.operation_key='private.quality.successor.5c8e2c140fb845458b011170c96daf86.review.started' AND j.payload_json->>'job_id'=target_job::text)
  THEN RAISE check_violation USING MESSAGE='566 exact successor review stage required'; END IF;
  SELECT x.* INTO review_row FROM jsonb_populate_record(NULL::public.tutor_item_supply_private_native_quality_evidence,frame->'review') x;
  PERFORM item_supply_internal.assert_private_native_review_stage(review_row);
 END IF;
   RETURN NEW;
  END IF;
 END IF;
 IF grant_row.payload_json->>'granted_top_xid' IS DISTINCT FROM pg_current_xact_id()::text
  OR binding_row.payload_json->>'bound_top_xid' IS DISTINCT FROM pg_current_xact_id()::text
  OR frame->'control'->>'state_version' IS DISTINCT FROM '3'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=target_job AND k.id<>checkpoint.id)
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id WHERE q.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=target_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.payload_json->>'job_id'=target_job::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='566 complete successor Q0 required before commit'; END IF;
 IF (frame->>'deadline')::timestamptz-clock_timestamp()<=interval '715 seconds' THEN RAISE check_violation USING MESSAGE='566 current successor phase and SOURCE required'; END IF;
 RETURN NEW;
END;$src$),
 ('private_native_quality_successor_ready()', 'private_native_quality_successor_ready()', 'boolean', false, $src$DECLARE spec record; actual record; names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' OR item_supply_internal.private_native_quality_phase_ready() IS DISTINCT FROM true THEN RETURN false; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_native_quality_successor_predecessor(uuid)','private_native_quality_successor_predecessor(p_predecessor uuid)','jsonb',false,'14f8c2a30218951d6c2d0cdb868f7bc355af41d15eca5d97903afb87e7102ba8'),
 ('private_native_quality_successor_frame(uuid,uuid,uuid,uuid)','private_native_quality_successor_frame(p_grant uuid,p_job uuid,p_batch uuid,p_origin uuid)','jsonb',false,'01778ed02f0679f1416fbad97c3355fa9546359165f22c784b06f960d8411f98'),
 ('private_native_quality_successor_grant(uuid,uuid)','private_native_quality_successor_grant(p_predecessor uuid,p_origin uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'ea18764f5e0863ba57afdf256ba5d26cdc6a2951b41cc1c3d65a600b779d1e84'),
 ('private_native_quality_successor_first_claim(uuid,uuid,uuid,uuid)','private_native_quality_successor_first_claim(p_grant uuid,p_job uuid,p_batch uuid,p_origin uuid)','public.tutor_item_supply_private_job_controls',true,'7ec2208898a9cc719464e88f91d0a9ee53a91d08432c2da74537fc79a9365159'),
 ('private_native_quality_successor_bind(uuid,uuid,uuid,uuid)','private_native_quality_successor_bind(p_grant uuid,p_job uuid,p_batch uuid,p_origin uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'b3f87b17610c733148d29873ccb27d61c2302baa5a026772a8a98a290c629f34'),
 ('private_native_quality_successor_bound(uuid,uuid)','private_native_quality_successor_bound(p_binding uuid,p_origin uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'54c0a85270f89acff799d7dd5031e0a185d49d07806d1999d76ae25455c9e922'),
 ('enforce_private_native_quality_successor_insert()','enforce_private_native_quality_successor_insert()','trigger',false,'95c15d8ba72d03f39977fe10cdb6245cba29ce1ccaf3d15b8b7679adc89ea46f'),
 ('enforce_private_native_quality_successor_atomic()','enforce_private_native_quality_successor_atomic()','trigger',false,'d3761a07899451dc2296dddc4b0ad6b80ded9e6cc025f903377c914ecb91d9e1'),
 ('private_native_quality_phase_ready()','private_native_quality_phase_ready()','boolean',false,'66d880f57c3f790005c15ee8add55edd5e3388523e31e3dc6ce7f9010bc4809d'),
 ('enforce_private_native_quality_insert()','enforce_private_native_quality_insert()','trigger',false,'9552d64c69a87b268e451edab877b1fcf1bf10de8808fab4060dc329256a97e1'),
 ('assert_private_native_review_stage(tutor_item_supply_private_native_quality_evidence)','assert_private_native_review_stage(n tutor_item_supply_private_native_quality_evidence)','void',false,'b4b914a87823d4419ed0a4f20b25dad31a3fc11a859cab06a4eb0d9ec21002d8'),
 ('private_native_quality_successor_ready()','private_native_quality_successor_ready()','boolean',false,NULL::text)
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
  ('tutor_item_supply_private_persistent_pack_journal','a000_private_native_quality_successor_insert','enforce_private_native_quality_successor_insert',7,false),
  ('tutor_item_supply_private_persistent_pack_journal','private_native_quality_successor_atomic','enforce_private_native_quality_successor_atomic',5,true),
  ('tutor_item_supply_private_job_controls','private_native_quality_successor_claim_atomic','enforce_private_native_quality_successor_atomic',17,true)
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
   THEN RAISE check_violation USING MESSAGE='566 unexpected existing receiver definition/metadata: '||spec.signature; END IF;
  ELSE
   EXECUTE 'CREATE FUNCTION item_supply_internal.'||spec.header||' RETURNS '||CASE WHEN spec.is_set THEN 'SETOF ' ELSE '' END||spec.result_type||
    ' LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS '||quote_literal(spec.body);
   EXECUTE 'ALTER FUNCTION item_supply_internal.'||spec.signature||' OWNER TO aearn_b1d_runtime_20261001';
   EXECUTE 'REVOKE ALL ON FUNCTION item_supply_internal.'||spec.signature||' FROM PUBLIC';
  END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','a000_private_native_quality_successor_insert','enforce_private_native_quality_successor_insert',7,false,
   'CREATE TRIGGER a000_private_native_quality_successor_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_quality_successor_insert()'),
  ('tutor_item_supply_private_persistent_pack_journal','private_native_quality_successor_atomic','enforce_private_native_quality_successor_atomic',5,true,
   'CREATE CONSTRAINT TRIGGER private_native_quality_successor_atomic AFTER INSERT ON public.tutor_item_supply_private_persistent_pack_journal DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_quality_successor_atomic()'),
  ('tutor_item_supply_private_job_controls','private_native_quality_successor_claim_atomic','enforce_private_native_quality_successor_atomic',17,true,
   'CREATE CONSTRAINT TRIGGER private_native_quality_successor_claim_atomic AFTER UPDATE ON public.tutor_item_supply_private_job_controls DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_quality_successor_atomic()')
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
    AND k.conname=tr.trigger_name AND k.conrelid=prior.tgrelid AND k.condeferrable AND k.condeferred AND k.convalidated)) THEN RAISE check_violation USING MESSAGE='566 unexpected existing receiver trigger: '||tr.trigger_name; END IF;
  ELSE EXECUTE tr.ddl; END IF;
 END LOOP;
END;
$install566$;
