-- C18: one fixed committed generation output, one independent persistence/quality writer.
-- Selected forward fragment only. Frozen <=561 SQL and original author evidence are untouched.
-- Caller owns TOP A/B/C. No author, resettlement, gap, retry/restart API, or bootstrap.
DO $install562$
DECLARE spec record; prior record; expected_names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='562 isolated PRIVATE database required'; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_generation_persistence_phase_completed_data(uuid)', 'private_generation_persistence_phase_completed_data(p_binding uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
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
BEGIN
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='562 current original namespace and active plan required'; END IF;
 -- Historical paid output: acquire original task/root/aux/approval/old-control locks before absence decisions.
 d:=item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb'
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id,j.record_kind,j.operation_key)=
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.generation.output.d55f63a980434d748a1c0862660aed30') FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context';
 IF output_row.id IS NULL OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR d->'control'->>'job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'known'
  OR d->'binding'->'payload_json'->>'schema_version' IS DISTINCT FROM 'private_initial_author_continuation_binding_v1'
  OR ctx->'ref' IS DISTINCT FROM d->'binding'->'payload_json'->'ref'
  OR ctx->'request' IS DISTINCT FROM d->'binding'->'payload_json'->'request'
  OR ctx->'lease' IS DISTINCT FROM d->'binding'->'payload_json'->'lease'
  OR ctx->'ref'->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  OR ctx->'ref'->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ctx->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR ctx->>'mode' IS DISTINCT FROM 'live' OR capture->'result'->>'state' IS DISTINCT FROM 'staged'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
   WHERE failed.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND failed.operation_key=replace(d->'binding'->>'operation_key','.binding','.failure'))
 THEN RAISE check_violation USING MESSAGE='562 fixed durable output required'; END IF;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_binding FOR SHARE;
 body:=binding_row.payload_json; lease_json:=body->'lease';
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.persistence.phase.f4519c6641304e34b05364dba6214dcb',d->'task'->>'intent_hash')
  OR item_supply_internal.snapshot_keys(body,ARRAY['schema_version','output_id','preparation_id','output_hash','original_binding_id','original_started_id','original_consumed_id','original_settlement_id','generation_job_id','generation_request_hash','generation_profile_hash','ref','writer_job_id','batch_id','lease','source_origin_id','bound_top_xid','bound_at','valid_until']) IS DISTINCT FROM true
  OR body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_phase_v1'
  OR body->>'output_id' IS DISTINCT FROM output_row.id::text OR body->>'preparation_id' IS DISTINCT FROM 'd55f63a9-8043-4d74-8a1c-0862660aed30'
  OR body->>'output_hash' IS DISTINCT FROM output_row.payload_hash
  OR body->'original_binding_id' IS DISTINCT FROM d->'binding'->'id'
  OR body->'original_started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'original_consumed_id' IS DISTINCT FROM d->'consumed'->'id'
  OR body->'original_settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'generation_job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR body->>'generation_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR body->'generation_profile_hash' IS DISTINCT FROM ctx->'request'->'profile'->'profile_hash'
  OR body->'ref' IS DISTINCT FROM ctx->'ref'
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (body->>'writer_job_id','private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.persistence.f4519c6641304e34b05364dba6214dcb','1','2')
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (body->>'bound_at')::timestamptz IS NULL OR (body->>'bound_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=(body->>'writer_job_id')::uuid FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=job_row.id FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=(body->>'batch_id')::uuid FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.persistence.phase.f4519c6641304e34b05364dba6214dcb','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.persistence_quality.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-durable-persistence-quality-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_durable_output_new_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->>'parent_deadline')::timestamptz>batch_row.valid_until
  OR (lease_json->>'expires_at')::timestamptz>(body->>'bound_at')::timestamptz+interval '3600 seconds'
  OR (body->>'bound_at')::timestamptz>=(body->>'valid_until')::timestamptz
  OR (body->>'valid_until')::timestamptz IS DISTINCT FROM LEAST((lease_json->>'expires_at')::timestamptz,
   (lease_json->>'parent_deadline')::timestamptz,(lease_json->'profile'->>'bound_at')::timestamptz+
   (lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding profile and batch required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM body->>'bound_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(body->>'bound_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(body->>'bound_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical binding SOURCE origin required'; END IF;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=job_row.id;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id=binding_row.pack_task_id AND p.user_id=binding_row.user_id AND p.epoch=binding_row.epoch
  AND p.scope_id=binding_row.scope_id AND p.record_kind='phase' AND p.operation_key='private.phase.'||job_row.id::text;
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',job_row.id,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',body->'ref'->'goal_scope_id','ref',body->'ref','lease',lease_json,
   'valid_until',phase_row.payload_json->'valid_until')
  OR (phase_row.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM (body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 complete accounting and slot phase required before commit'; END IF;
 SELECT j.* INTO completion_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=binding_row.pack_task_id
  AND j.operation_key=binding_row.operation_key||'.complete' AND j.record_kind='private_status';
 complete_body:=completion_row.payload_json;
 IF completion_row.id IS NULL OR (completion_row.pack_task_id,completion_row.user_id,completion_row.epoch,completion_row.scope_id,completion_row.record_kind,completion_row.operation_key,completion_row.intent_hash) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,'private_status',binding_row.operation_key||'.complete',binding_row.intent_hash)
  OR item_supply_internal.snapshot_keys(complete_body,ARRAY['schema_version','binding_id','output_id','writer_job_id','artifact_id','artifact_hash','candidate_id','version_id','checkpoint_id','source_origin_id','completed_top_xid','completed_at']) IS DISTINCT FROM true
  OR complete_body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_complete_v1'
  OR complete_body->>'binding_id' IS DISTINCT FROM binding_row.id::text
  OR complete_body->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb' OR complete_body->>'writer_job_id' IS DISTINCT FROM job_row.id::text
  OR jsonb_typeof(complete_body->'completed_top_xid') IS DISTINCT FROM 'string'
  OR (complete_body->>'completed_top_xid')::xid8::text IS DISTINCT FROM complete_body->>'completed_top_xid'
  OR complete_body->>'completed_top_xid'=body->>'bound_top_xid'
  OR (complete_body->>'completed_at')::timestamptz IS NULL OR (complete_body->>'completed_at')::timestamptz>clock_timestamp()
  OR (complete_body->>'completed_at')::timestamptz<(body->>'bound_at')::timestamptz
  OR (complete_body->>'completed_at')::timestamptz>=(body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact persistence completion DATA required'; END IF;
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id=(complete_body->>'artifact_id')::uuid;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.id=(complete_body->>'checkpoint_id')::uuid;
 IF artifact.id IS NULL OR checkpoint.id IS NULL
  OR (artifact.user_id,artifact.epoch,artifact.scope_id,artifact.job_id,artifact.lease_generation,artifact.lease_state_version,artifact.mode,artifact.artifact_key) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,1,2,'live','generation.d55f63a980434d748a1c0862660aed30')
  OR artifact.request_json IS DISTINCT FROM ctx->'request'
  OR artifact.source_json IS DISTINCT FROM capture->'result'->'source'
  OR artifact.receipt_json IS DISTINCT FROM capture->'result'->'receipt'
  OR artifact.source_hash IS DISTINCT FROM artifact.receipt_json->>'source_hash'
  OR artifact.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(artifact.source_json)
  OR artifact.content_hash IS DISTINCT FROM artifact.receipt_json->>'content_hash'
  OR artifact.artifact_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('source',artifact.source_json,'receipt',artifact.receipt_json))
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates c JOIN tutor_item_supply_private_versions v
   ON v.candidate_id=c.id AND v.user_id=c.user_id AND v.epoch=c.epoch AND v.scope_id=c.scope_id
   WHERE c.id=artifact.candidate_id AND (c.user_id,c.epoch,c.scope_id)=(artifact.user_id,artifact.epoch,artifact.scope_id)
   AND c.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   AND v.id=artifact.version_id AND v.version=1 AND v.public_json=artifact.source_json->'public' AND v.private_json=artifact.source_json->'private')
  OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,'generating',1,'completed',1,artifact.artifact_hash,'candidate_staged')
 THEN RAISE check_violation USING MESSAGE='562 exact actual artifact and generating checkpoint required'; END IF;
 IF complete_body->>'artifact_hash' IS DISTINCT FROM artifact.artifact_hash
  OR complete_body->>'candidate_id' IS DISTINCT FROM artifact.candidate_id::text OR complete_body->>'version_id' IS DISTINCT FROM artifact.version_id::text
 THEN RAISE check_violation USING MESSAGE='562 exact persistence completion artifact identity required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(complete_body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM complete_body->>'completed_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(complete_body->>'completed_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(complete_body->>'completed_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical completion SOURCE origin required'; END IF;
 -- Immutable provenance only. No current writer/SOURCE check and no implicit prior-TOP authority.
 RETURN NEXT completion_row; RETURN;
END;$src$),
 ('private_generation_persistence_phase_bound(uuid,uuid)', 'private_generation_persistence_phase_bound(p_binding uuid,p_origin uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
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
BEGIN
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='562 current original namespace and active plan required'; END IF;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_binding AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb'
  AND j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' FOR SHARE;
 IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 IF binding_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
 THEN RAISE check_violation USING MESSAGE='562 prior-TOP persistence binding required'; END IF;
 -- Historical paid output: acquire original task/root/aux/approval/old-control locks before absence decisions.
 d:=item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb'
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id,j.record_kind,j.operation_key)=
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.generation.output.d55f63a980434d748a1c0862660aed30') FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context';
 IF output_row.id IS NULL OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR d->'control'->>'job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'known'
  OR d->'binding'->'payload_json'->>'schema_version' IS DISTINCT FROM 'private_initial_author_continuation_binding_v1'
  OR ctx->'ref' IS DISTINCT FROM d->'binding'->'payload_json'->'ref'
  OR ctx->'request' IS DISTINCT FROM d->'binding'->'payload_json'->'request'
  OR ctx->'lease' IS DISTINCT FROM d->'binding'->'payload_json'->'lease'
  OR ctx->'ref'->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  OR ctx->'ref'->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ctx->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR ctx->>'mode' IS DISTINCT FROM 'live' OR capture->'result'->>'state' IS DISTINCT FROM 'staged'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
   WHERE failed.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND failed.operation_key=replace(d->'binding'->>'operation_key','.binding','.failure'))
 THEN RAISE check_violation USING MESSAGE='562 fixed durable output required'; END IF;
 body:=binding_row.payload_json; lease_json:=body->'lease';
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.persistence.phase.f4519c6641304e34b05364dba6214dcb',d->'task'->>'intent_hash')
  OR item_supply_internal.snapshot_keys(body,ARRAY['schema_version','output_id','preparation_id','output_hash','original_binding_id','original_started_id','original_consumed_id','original_settlement_id','generation_job_id','generation_request_hash','generation_profile_hash','ref','writer_job_id','batch_id','lease','source_origin_id','bound_top_xid','bound_at','valid_until']) IS DISTINCT FROM true
  OR body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_phase_v1'
  OR body->>'output_id' IS DISTINCT FROM output_row.id::text OR body->>'preparation_id' IS DISTINCT FROM 'd55f63a9-8043-4d74-8a1c-0862660aed30'
  OR body->>'output_hash' IS DISTINCT FROM output_row.payload_hash
  OR body->'original_binding_id' IS DISTINCT FROM d->'binding'->'id'
  OR body->'original_started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'original_consumed_id' IS DISTINCT FROM d->'consumed'->'id'
  OR body->'original_settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'generation_job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR body->>'generation_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR body->'generation_profile_hash' IS DISTINCT FROM ctx->'request'->'profile'->'profile_hash'
  OR body->'ref' IS DISTINCT FROM ctx->'ref'
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (body->>'writer_job_id','private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.persistence.f4519c6641304e34b05364dba6214dcb','1','2')
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (body->>'bound_at')::timestamptz IS NULL OR (body->>'bound_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=(body->>'writer_job_id')::uuid FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=job_row.id FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=(body->>'batch_id')::uuid FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.persistence.phase.f4519c6641304e34b05364dba6214dcb','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.persistence_quality.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-durable-persistence-quality-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_durable_output_new_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->>'parent_deadline')::timestamptz>batch_row.valid_until
  OR (lease_json->>'expires_at')::timestamptz>(body->>'bound_at')::timestamptz+interval '3600 seconds'
  OR (body->>'bound_at')::timestamptz>=(body->>'valid_until')::timestamptz
  OR (body->>'valid_until')::timestamptz IS DISTINCT FROM LEAST((lease_json->>'expires_at')::timestamptz,
   (lease_json->>'parent_deadline')::timestamptz,(lease_json->'profile'->>'bound_at')::timestamptz+
   (lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding profile and batch required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM body->>'bound_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(body->>'bound_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(body->>'bound_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical binding SOURCE origin required'; END IF;
 origin_id:=p_origin;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=job_row.id;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id=binding_row.pack_task_id AND p.user_id=binding_row.user_id AND p.epoch=binding_row.epoch
  AND p.scope_id=binding_row.scope_id AND p.record_kind='phase' AND p.operation_key='private.phase.'||job_row.id::text;
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',job_row.id,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',body->'ref'->'goal_scope_id','ref',body->'ref','lease',lease_json,
   'valid_until',phase_row.payload_json->'valid_until')
  OR (phase_row.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM (body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 complete accounting and slot phase required before commit'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF ctrl.state IS DISTINCT FROM 'leased' OR ctrl.breaker_open OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1
  OR ctrl.state_version<2 OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.lease_expires_at IS DISTINCT FROM (lease_json->>'expires_at')::timestamptz
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- Only the in-memory assertion receives refreshed state_version; immutable phase/binding snapshots stay at 2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.pack_task_id);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',binding_row.user_id,'epoch',binding_row.epoch,
  'scope_id',binding_row.scope_id,'job_id',job_row.id,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- No entry-time clock can authorize work after lock waits.
 stamp:=clock_timestamp();
 IF ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
   (body->>'valid_until')::timestamptz,(origin_row.payload_json->>'valid_until')::timestamptz)
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 RETURN NEXT binding_row; RETURN;
END;$src$),
 ('private_generation_persistence_phase_first_claim(uuid,uuid,uuid,uuid)', 'private_generation_persistence_phase_first_claim(p_output uuid,p_job uuid,p_batch uuid,p_origin uuid)', 'public.tutor_item_supply_private_job_controls', true, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
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
BEGIN
 IF p_output IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb'::uuid THEN RAISE check_violation USING MESSAGE='562 fixed durable output required'; END IF;
 IF item_supply_internal.private_generation_persistence_phase_ready() IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE='562 exact installed persistence receivers required'; END IF;
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='562 current original namespace and active plan required'; END IF;
 -- Historical paid output: acquire original task/root/aux/approval/old-control locks before absence decisions.
 d:=item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb'
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id,j.record_kind,j.operation_key)=
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.generation.output.d55f63a980434d748a1c0862660aed30') FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context';
 IF output_row.id IS NULL OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR d->'control'->>'job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'known'
  OR d->'binding'->'payload_json'->>'schema_version' IS DISTINCT FROM 'private_initial_author_continuation_binding_v1'
  OR ctx->'ref' IS DISTINCT FROM d->'binding'->'payload_json'->'ref'
  OR ctx->'request' IS DISTINCT FROM d->'binding'->'payload_json'->'request'
  OR ctx->'lease' IS DISTINCT FROM d->'binding'->'payload_json'->'lease'
  OR ctx->'ref'->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  OR ctx->'ref'->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ctx->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR ctx->>'mode' IS DISTINCT FROM 'live' OR capture->'result'->>'state' IS DISTINCT FROM 'staged'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
   WHERE failed.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND failed.operation_key=replace(d->'binding'->>'operation_key','.binding','.failure'))
 THEN RAISE check_violation USING MESSAGE='562 fixed durable output required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1
  AND (j.operation_key IN('private.persistence.phase.f4519c6641304e34b05364dba6214dcb','private.persistence.phase.f4519c6641304e34b05364dba6214dcb.complete') OR (j.payload_json->>'output_id'='f4519c66-4130-4e34-b053-64dba6214dcb'
   AND j.payload_json->>'schema_version' IN('private_generation_persistence_phase_v1','private_generation_persistence_complete_v1'))))
 THEN RAISE check_violation USING MESSAGE='562 persistence phase already bound'; END IF;
 IF (d->'control'->>'lease_expires_at')::timestamptz>clock_timestamp()
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND a.epoch=1 AND a.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates c WHERE c.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND c.epoch=1 AND c.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
 THEN RAISE check_violation USING MESSAGE='562 fixed expired author without initial artifact required'; END IF;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=p_job FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=p_job FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=p_batch FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.persistence.phase.f4519c6641304e34b05364dba6214dcb','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.persistence_quality.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-durable-persistence-quality-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_durable_output_new_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true OR ctrl.state IS DISTINCT FROM 'queued' OR ctrl.state_version<>1
  OR ctrl.lease_generation<>0 OR ctrl.attempt_count<>0 OR ctrl.breaker_open OR ctrl.lease_owner IS NOT NULL OR ctrl.lease_expires_at IS NOT NULL
  OR (ctrl.profile_snapshot_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR  EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=p_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=job_row.user_id AND j.epoch=job_row.epoch
   AND (j.payload_json->>'job_id'=p_job::text OR j.payload_json->>'writer_job_id'=p_job::text OR j.payload_json->'lease'->>'job_id'=p_job::text))
 THEN RAISE check_violation USING MESSAGE='562 exact unclaimed persistence job required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 origin_id:=p_origin;
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 PERFORM item_supply_internal.private_native_mapping_current('d8e34e01-3514-41a3-9bbd-55ee3e627134','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 stamp:=clock_timestamp();
 deadline:=LEAST(ctrl.parent_deadline,stamp+interval '3600 seconds',batch_row.valid_until,source_end,
  (ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz+(ctrl.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond');
 IF ctrl.available_at>stamp OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end) OR deadline IS NULL
  OR stamp+interval '100 seconds'>=deadline OR stamp>=(origin_row.payload_json->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 UPDATE tutor_item_supply_private_job_controls c SET state='leased',state_version=2,lease_generation=1,attempt_count=1,
  lease_owner='private.persistence.f4519c6641304e34b05364dba6214dcb',lease_expires_at=deadline,updated_at=stamp
  WHERE c.id=ctrl.id AND c.state='queued' AND c.state_version=1 AND c.lease_generation=0 AND c.attempt_count=0 RETURNING c.* INTO ctrl;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='562 exact unclaimed persistence job required'; END IF;
 lease_json:=jsonb_build_object('job_id',ctrl.job_id,'visibility','private','owner_id',ctrl.user_id,'owner_epoch',ctrl.epoch,
  'lease_owner',ctrl.lease_owner,'generation',ctrl.lease_generation,'state_version',ctrl.state_version,
  'expires_at',(to_char(ctrl.lease_expires_at,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM ctrl.lease_expires_at)::bigint%1000000=0 THEN '' ELSE '.'||to_char(ctrl.lease_expires_at,'US') END||CASE WHEN extract(timezone FROM ctrl.lease_expires_at)=0 THEN 'Z' ELSE to_char(ctrl.lease_expires_at,'TZH:TZM') END),'parent_deadline',(to_char(ctrl.parent_deadline,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM ctrl.parent_deadline)::bigint%1000000=0 THEN '' ELSE '.'||to_char(ctrl.parent_deadline,'US') END||CASE WHEN extract(timezone FROM ctrl.parent_deadline)=0 THEN 'Z' ELSE to_char(ctrl.parent_deadline,'TZH:TZM') END),
  'profile',ctrl.profile_snapshot_json->'profile','retry_policy',ctrl.profile_snapshot_json->'retry_policy');
 body:=jsonb_build_object('schema_version','private_generation_persistence_phase_v1','output_id',output_row.id,
  'preparation_id','d55f63a9-8043-4d74-8a1c-0862660aed30','output_hash',output_row.payload_hash,'original_binding_id',d->'binding'->'id',
  'original_started_id',d->'started'->'id','original_consumed_id',d->'consumed'->'id','original_settlement_id',d->'settlement'->'id',
  'generation_job_id','c9442831-e8d6-43b6-9367-b94875c60f36','generation_request_hash',item_supply_internal.snapshot_hash(ctx->'request'),
  'generation_profile_hash',ctx->'request'->'profile'->'profile_hash','ref',ctx->'ref','writer_job_id',p_job,'batch_id',p_batch,
  'lease',lease_json,'source_origin_id',p_origin,'bound_top_xid',pg_current_xact_id()::text,'bound_at',stamp,'valid_until',deadline);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(gen_random_uuid(),'6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','private_status','private.persistence.phase.f4519c6641304e34b05364dba6214dcb',d->'task'->>'intent_hash',body);
 -- Original551 bind_job MUST precede original524 phase; deferred A enforces both before commit.
 RETURN NEXT ctrl; RETURN;
END;$src$),
 ('private_generation_persistence_phase_complete(uuid,uuid,uuid)', 'private_generation_persistence_phase_complete(p_binding uuid,p_artifact uuid,p_origin uuid)', 'uuid', false, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
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
BEGIN
 SELECT b.* INTO binding_row FROM item_supply_internal.private_generation_persistence_phase_bound(p_binding,p_origin) b;
 SELECT j.* INTO completion_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=binding_row.pack_task_id
  AND j.operation_key=binding_row.operation_key||'.complete' AND j.record_kind='private_status';
 IF completion_row.id IS NOT NULL THEN
  SELECT c.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data(p_binding) c;
  IF completion_row.payload_json->>'artifact_id' IS DISTINCT FROM p_artifact::text THEN RAISE check_violation USING MESSAGE='562 conflicting persistence completion required artifact'; END IF;
  RETURN completion_row.id; -- Exact readback; no marker renewal or first-B restriction on later quality.
 END IF;
 -- Historical paid output: acquire original task/root/aux/approval/old-control locks before absence decisions.
 d:=item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb'
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id,j.record_kind,j.operation_key)=
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.generation.output.d55f63a980434d748a1c0862660aed30') FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context';
 IF output_row.id IS NULL OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR d->'control'->>'job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'known'
  OR d->'binding'->'payload_json'->>'schema_version' IS DISTINCT FROM 'private_initial_author_continuation_binding_v1'
  OR ctx->'ref' IS DISTINCT FROM d->'binding'->'payload_json'->'ref'
  OR ctx->'request' IS DISTINCT FROM d->'binding'->'payload_json'->'request'
  OR ctx->'lease' IS DISTINCT FROM d->'binding'->'payload_json'->'lease'
  OR ctx->'ref'->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  OR ctx->'ref'->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ctx->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR ctx->>'mode' IS DISTINCT FROM 'live' OR capture->'result'->>'state' IS DISTINCT FROM 'staged'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
   WHERE failed.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND failed.operation_key=replace(d->'binding'->>'operation_key','.binding','.failure'))
 THEN RAISE check_violation USING MESSAGE='562 fixed durable output required'; END IF;
 body:=binding_row.payload_json; lease_json:=body->'lease';
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.persistence.phase.f4519c6641304e34b05364dba6214dcb',d->'task'->>'intent_hash')
  OR item_supply_internal.snapshot_keys(body,ARRAY['schema_version','output_id','preparation_id','output_hash','original_binding_id','original_started_id','original_consumed_id','original_settlement_id','generation_job_id','generation_request_hash','generation_profile_hash','ref','writer_job_id','batch_id','lease','source_origin_id','bound_top_xid','bound_at','valid_until']) IS DISTINCT FROM true
  OR body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_phase_v1'
  OR body->>'output_id' IS DISTINCT FROM output_row.id::text OR body->>'preparation_id' IS DISTINCT FROM 'd55f63a9-8043-4d74-8a1c-0862660aed30'
  OR body->>'output_hash' IS DISTINCT FROM output_row.payload_hash
  OR body->'original_binding_id' IS DISTINCT FROM d->'binding'->'id'
  OR body->'original_started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'original_consumed_id' IS DISTINCT FROM d->'consumed'->'id'
  OR body->'original_settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'generation_job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR body->>'generation_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR body->'generation_profile_hash' IS DISTINCT FROM ctx->'request'->'profile'->'profile_hash'
  OR body->'ref' IS DISTINCT FROM ctx->'ref'
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (body->>'writer_job_id','private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.persistence.f4519c6641304e34b05364dba6214dcb','1','2')
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (body->>'bound_at')::timestamptz IS NULL OR (body->>'bound_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=(body->>'writer_job_id')::uuid FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=job_row.id FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=(body->>'batch_id')::uuid FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.persistence.phase.f4519c6641304e34b05364dba6214dcb','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.persistence_quality.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-durable-persistence-quality-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_durable_output_new_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->>'parent_deadline')::timestamptz>batch_row.valid_until
  OR (lease_json->>'expires_at')::timestamptz>(body->>'bound_at')::timestamptz+interval '3600 seconds'
  OR (body->>'bound_at')::timestamptz>=(body->>'valid_until')::timestamptz
  OR (body->>'valid_until')::timestamptz IS DISTINCT FROM LEAST((lease_json->>'expires_at')::timestamptz,
   (lease_json->>'parent_deadline')::timestamptz,(lease_json->'profile'->>'bound_at')::timestamptz+
   (lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding profile and batch required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM body->>'bound_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(body->>'bound_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(body->>'bound_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical binding SOURCE origin required'; END IF;
 origin_id:=p_origin;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=job_row.id;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id=binding_row.pack_task_id AND p.user_id=binding_row.user_id AND p.epoch=binding_row.epoch
  AND p.scope_id=binding_row.scope_id AND p.record_kind='phase' AND p.operation_key='private.phase.'||job_row.id::text;
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',job_row.id,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',body->'ref'->'goal_scope_id','ref',body->'ref','lease',lease_json,
   'valid_until',phase_row.payload_json->'valid_until')
  OR (phase_row.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM (body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 complete accounting and slot phase required before commit'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF ctrl.state IS DISTINCT FROM 'leased' OR ctrl.breaker_open OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1
  OR ctrl.state_version<2 OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.lease_expires_at IS DISTINCT FROM (lease_json->>'expires_at')::timestamptz
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- Only the in-memory assertion receives refreshed state_version; immutable phase/binding snapshots stay at 2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.pack_task_id);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',binding_row.user_id,'epoch',binding_row.epoch,
  'scope_id',binding_row.scope_id,'job_id',job_row.id,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- No entry-time clock can authorize work after lock waits.
 stamp:=clock_timestamp();
 IF ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
   (body->>'valid_until')::timestamptz,(origin_row.payload_json->>'valid_until')::timestamptz)
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id=p_artifact;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=job_row.id AND k.stage='generating' AND k.attempt=1;
 IF artifact.id IS NULL OR checkpoint.id IS NULL
  OR (artifact.user_id,artifact.epoch,artifact.scope_id,artifact.job_id,artifact.lease_generation,artifact.lease_state_version,artifact.mode,artifact.artifact_key) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,1,2,'live','generation.d55f63a980434d748a1c0862660aed30')
  OR artifact.request_json IS DISTINCT FROM ctx->'request'
  OR artifact.source_json IS DISTINCT FROM capture->'result'->'source'
  OR artifact.receipt_json IS DISTINCT FROM capture->'result'->'receipt'
  OR artifact.source_hash IS DISTINCT FROM artifact.receipt_json->>'source_hash'
  OR artifact.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(artifact.source_json)
  OR artifact.content_hash IS DISTINCT FROM artifact.receipt_json->>'content_hash'
  OR artifact.artifact_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('source',artifact.source_json,'receipt',artifact.receipt_json))
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates c JOIN tutor_item_supply_private_versions v
   ON v.candidate_id=c.id AND v.user_id=c.user_id AND v.epoch=c.epoch AND v.scope_id=c.scope_id
   WHERE c.id=artifact.candidate_id AND (c.user_id,c.epoch,c.scope_id)=(artifact.user_id,artifact.epoch,artifact.scope_id)
   AND c.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   AND v.id=artifact.version_id AND v.version=1 AND v.public_json=artifact.source_json->'public' AND v.private_json=artifact.source_json->'private')
  OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,'generating',1,'completed',1,artifact.artifact_hash,'candidate_staged')
 THEN RAISE check_violation USING MESSAGE='562 exact actual artifact and generating checkpoint required'; END IF;
 IF ctrl.state_version<>3
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=job_row.id AND k.id<>checkpoint.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'job_id'=job_row.id::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='562 persistence TOP must contain no quality work'; END IF;
 identity:=gen_random_uuid();
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,'private_status',binding_row.operation_key||'.complete',binding_row.intent_hash,
  jsonb_build_object('schema_version','private_generation_persistence_complete_v1','binding_id',binding_row.id,'output_id',output_row.id,
   'writer_job_id',job_row.id,'artifact_id',artifact.id,'artifact_hash',artifact.artifact_hash,'candidate_id',artifact.candidate_id,'version_id',artifact.version_id,
   'checkpoint_id',checkpoint.id,'source_origin_id',p_origin,'completed_top_xid',pg_current_xact_id()::text,'completed_at',clock_timestamp()));
 RETURN identity;
END;$src$),
 ('private_generation_persistence_phase_committed(uuid,uuid)', 'private_generation_persistence_phase_committed(p_binding uuid,p_origin uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', true, $src$DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='562 current original namespace and active plan required'; END IF;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_binding
  AND j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb' AND j.record_kind='private_status';
 IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 IF binding_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text THEN RAISE check_violation USING MESSAGE='562 prior-TOP persistence binding required'; END IF;
 SELECT j.* INTO completion_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=binding_row.pack_task_id
  AND j.user_id=binding_row.user_id AND j.epoch=binding_row.epoch AND j.scope_id=binding_row.scope_id
  AND j.operation_key=binding_row.operation_key||'.complete' AND j.record_kind='private_status';
 IF completion_row.id IS NULL THEN RAISE check_violation USING MESSAGE='562 exact persistence completion DATA required'; END IF;
 IF completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text THEN RAISE check_violation USING MESSAGE='562 prior-TOP persistence completion required'; END IF;
 SELECT c.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data(p_binding) c;
 PERFORM 1 FROM item_supply_internal.private_generation_persistence_phase_bound(p_binding,p_origin);
 RETURN NEXT completion_row; RETURN;
END;$src$),
 ('enforce_private_generation_persistence_phase_insert()', 'enforce_private_generation_persistence_phase_insert()', 'trigger', false, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
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
 protocol text:=NEW.payload_json->>'schema_version';
BEGIN
 IF COALESCE(protocol NOT IN('private_generation_persistence_phase_v1','private_generation_persistence_complete_v1'),true)
  AND NEW.operation_key NOT IN('private.persistence.phase.f4519c6641304e34b05364dba6214dcb','private.persistence.phase.f4519c6641304e34b05364dba6214dcb.complete') THEN RETURN NEW; END IF;
 IF protocol IS NULL OR protocol NOT IN('private_generation_persistence_phase_v1','private_generation_persistence_complete_v1')
 THEN RAISE check_violation USING MESSAGE='562 closed persistence journal schema required'; END IF;
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='562 current original namespace and active plan required'; END IF;
 -- Historical paid output: acquire original task/root/aux/approval/old-control locks before absence decisions.
 d:=item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb'
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id,j.record_kind,j.operation_key)=
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.generation.output.d55f63a980434d748a1c0862660aed30') FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context';
 IF output_row.id IS NULL OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR d->'control'->>'job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'known'
  OR d->'binding'->'payload_json'->>'schema_version' IS DISTINCT FROM 'private_initial_author_continuation_binding_v1'
  OR ctx->'ref' IS DISTINCT FROM d->'binding'->'payload_json'->'ref'
  OR ctx->'request' IS DISTINCT FROM d->'binding'->'payload_json'->'request'
  OR ctx->'lease' IS DISTINCT FROM d->'binding'->'payload_json'->'lease'
  OR ctx->'ref'->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  OR ctx->'ref'->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ctx->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR ctx->>'mode' IS DISTINCT FROM 'live' OR capture->'result'->>'state' IS DISTINCT FROM 'staged'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
   WHERE failed.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND failed.operation_key=replace(d->'binding'->>'operation_key','.binding','.failure'))
 THEN RAISE check_violation USING MESSAGE='562 fixed durable output required'; END IF;
 IF protocol='private_generation_persistence_phase_v1' THEN
  IF NEW.payload_json->'bound_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)
  THEN RAISE check_violation USING MESSAGE='562 SQL current TOP binding marker required'; END IF;
  binding_row:=NEW;
 body:=binding_row.payload_json; lease_json:=body->'lease';
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.persistence.phase.f4519c6641304e34b05364dba6214dcb',d->'task'->>'intent_hash')
  OR item_supply_internal.snapshot_keys(body,ARRAY['schema_version','output_id','preparation_id','output_hash','original_binding_id','original_started_id','original_consumed_id','original_settlement_id','generation_job_id','generation_request_hash','generation_profile_hash','ref','writer_job_id','batch_id','lease','source_origin_id','bound_top_xid','bound_at','valid_until']) IS DISTINCT FROM true
  OR body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_phase_v1'
  OR body->>'output_id' IS DISTINCT FROM output_row.id::text OR body->>'preparation_id' IS DISTINCT FROM 'd55f63a9-8043-4d74-8a1c-0862660aed30'
  OR body->>'output_hash' IS DISTINCT FROM output_row.payload_hash
  OR body->'original_binding_id' IS DISTINCT FROM d->'binding'->'id'
  OR body->'original_started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'original_consumed_id' IS DISTINCT FROM d->'consumed'->'id'
  OR body->'original_settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'generation_job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR body->>'generation_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR body->'generation_profile_hash' IS DISTINCT FROM ctx->'request'->'profile'->'profile_hash'
  OR body->'ref' IS DISTINCT FROM ctx->'ref'
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (body->>'writer_job_id','private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.persistence.f4519c6641304e34b05364dba6214dcb','1','2')
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (body->>'bound_at')::timestamptz IS NULL OR (body->>'bound_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=(body->>'writer_job_id')::uuid FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=job_row.id FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=(body->>'batch_id')::uuid FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.persistence.phase.f4519c6641304e34b05364dba6214dcb','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.persistence_quality.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-durable-persistence-quality-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_durable_output_new_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->>'parent_deadline')::timestamptz>batch_row.valid_until
  OR (lease_json->>'expires_at')::timestamptz>(body->>'bound_at')::timestamptz+interval '3600 seconds'
  OR (body->>'bound_at')::timestamptz>=(body->>'valid_until')::timestamptz
  OR (body->>'valid_until')::timestamptz IS DISTINCT FROM LEAST((lease_json->>'expires_at')::timestamptz,
   (lease_json->>'parent_deadline')::timestamptz,(lease_json->'profile'->>'bound_at')::timestamptz+
   (lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding profile and batch required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM body->>'bound_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(body->>'bound_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(body->>'bound_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical binding SOURCE origin required'; END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=NEW.user_id AND j.epoch=NEW.epoch
    AND (j.operation_key IN('private.persistence.phase.f4519c6641304e34b05364dba6214dcb','private.persistence.phase.f4519c6641304e34b05364dba6214dcb.complete') OR (j.payload_json->>'output_id'='f4519c66-4130-4e34-b053-64dba6214dcb'
     AND j.payload_json->>'schema_version' IN('private_generation_persistence_phase_v1','private_generation_persistence_complete_v1'))))
  THEN RAISE check_violation USING MESSAGE='562 persistence phase already bound'; END IF;
  IF ctrl.state IS DISTINCT FROM 'leased' OR ctrl.breaker_open OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.state_version<>2
   OR lease_json IS DISTINCT FROM jsonb_build_object('job_id',ctrl.job_id,'visibility','private','owner_id',ctrl.user_id,'owner_epoch',ctrl.epoch,
  'lease_owner',ctrl.lease_owner,'generation',ctrl.lease_generation,'state_version',ctrl.state_version,
  'expires_at',(to_char(ctrl.lease_expires_at,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM ctrl.lease_expires_at)::bigint%1000000=0 THEN '' ELSE '.'||to_char(ctrl.lease_expires_at,'US') END||CASE WHEN extract(timezone FROM ctrl.lease_expires_at)=0 THEN 'Z' ELSE to_char(ctrl.lease_expires_at,'TZH:TZM') END),'parent_deadline',(to_char(ctrl.parent_deadline,'YYYY-MM-DD"T"HH24:MI:SS')||CASE WHEN extract(microseconds FROM ctrl.parent_deadline)::bigint%1000000=0 THEN '' ELSE '.'||to_char(ctrl.parent_deadline,'US') END||CASE WHEN extract(timezone FROM ctrl.parent_deadline)=0 THEN 'Z' ELSE to_char(ctrl.parent_deadline,'TZH:TZM') END),
  'profile',ctrl.profile_snapshot_json->'profile','retry_policy',ctrl.profile_snapshot_json->'retry_policy')
   OR ((body->>'bound_at')::timestamptz>=(lease_json->'profile'->>'bound_at')::timestamptz) IS DISTINCT FROM true
   OR (d->'control'->>'lease_expires_at')::timestamptz>clock_timestamp()
   OR  EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=job_row.id)
   OR  EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND a.epoch=1
   AND a.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates c WHERE c.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND c.epoch=1
   AND c.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=job_row.id)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=job_row.user_id AND j.epoch=job_row.epoch
    AND (j.payload_json->>'job_id'=job_row.id::text OR j.payload_json->>'writer_job_id'=job_row.id::text OR j.payload_json->'lease'->>'job_id'=job_row.id::text))
  THEN RAISE check_violation USING MESSAGE='562 exact first-claimed unspent persistence job required'; END IF;
  PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
  origin_id:=(body->>'source_origin_id')::uuid;
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
  stamp:=clock_timestamp();
  IF (body->>'bound_at')::timestamptz>stamp
   OR ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end) OR stamp>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,source_end,batch_row.valid_until,
   (body->>'valid_until')::timestamptz,(origin_row.payload_json->>'valid_until')::timestamptz)
  THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
  -- 450 sets control.updated_at to TOP-start now(); it is not the actual binding clock.
  -- Validate the supplied SQL claim time above, then persist this guard's own postwait clock.
  NEW.payload_json:=jsonb_set(NEW.payload_json,'{bound_at}',to_jsonb(stamp));
 ELSE
  complete_body:=NEW.payload_json;
  IF complete_body->'completed_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)
  THEN RAISE check_violation USING MESSAGE='562 SQL current TOP completion marker required'; END IF;
  SELECT b.* INTO binding_row FROM item_supply_internal.private_generation_persistence_phase_bound((complete_body->>'binding_id')::uuid,(complete_body->>'source_origin_id')::uuid) b;
 body:=binding_row.payload_json; lease_json:=body->'lease';
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.persistence.phase.f4519c6641304e34b05364dba6214dcb',d->'task'->>'intent_hash')
  OR item_supply_internal.snapshot_keys(body,ARRAY['schema_version','output_id','preparation_id','output_hash','original_binding_id','original_started_id','original_consumed_id','original_settlement_id','generation_job_id','generation_request_hash','generation_profile_hash','ref','writer_job_id','batch_id','lease','source_origin_id','bound_top_xid','bound_at','valid_until']) IS DISTINCT FROM true
  OR body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_phase_v1'
  OR body->>'output_id' IS DISTINCT FROM output_row.id::text OR body->>'preparation_id' IS DISTINCT FROM 'd55f63a9-8043-4d74-8a1c-0862660aed30'
  OR body->>'output_hash' IS DISTINCT FROM output_row.payload_hash
  OR body->'original_binding_id' IS DISTINCT FROM d->'binding'->'id'
  OR body->'original_started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'original_consumed_id' IS DISTINCT FROM d->'consumed'->'id'
  OR body->'original_settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'generation_job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR body->>'generation_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR body->'generation_profile_hash' IS DISTINCT FROM ctx->'request'->'profile'->'profile_hash'
  OR body->'ref' IS DISTINCT FROM ctx->'ref'
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (body->>'writer_job_id','private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.persistence.f4519c6641304e34b05364dba6214dcb','1','2')
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (body->>'bound_at')::timestamptz IS NULL OR (body->>'bound_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=(body->>'writer_job_id')::uuid FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=job_row.id FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=(body->>'batch_id')::uuid FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.persistence.phase.f4519c6641304e34b05364dba6214dcb','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.persistence_quality.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-durable-persistence-quality-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_durable_output_new_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->>'parent_deadline')::timestamptz>batch_row.valid_until
  OR (lease_json->>'expires_at')::timestamptz>(body->>'bound_at')::timestamptz+interval '3600 seconds'
  OR (body->>'bound_at')::timestamptz>=(body->>'valid_until')::timestamptz
  OR (body->>'valid_until')::timestamptz IS DISTINCT FROM LEAST((lease_json->>'expires_at')::timestamptz,
   (lease_json->>'parent_deadline')::timestamptz,(lease_json->'profile'->>'bound_at')::timestamptz+
   (lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding profile and batch required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM body->>'bound_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(body->>'bound_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(body->>'bound_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical binding SOURCE origin required'; END IF;
  completion_row:=NEW;
 complete_body:=completion_row.payload_json;
 IF completion_row.id IS NULL OR (completion_row.pack_task_id,completion_row.user_id,completion_row.epoch,completion_row.scope_id,completion_row.record_kind,completion_row.operation_key,completion_row.intent_hash) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,'private_status',binding_row.operation_key||'.complete',binding_row.intent_hash)
  OR item_supply_internal.snapshot_keys(complete_body,ARRAY['schema_version','binding_id','output_id','writer_job_id','artifact_id','artifact_hash','candidate_id','version_id','checkpoint_id','source_origin_id','completed_top_xid','completed_at']) IS DISTINCT FROM true
  OR complete_body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_complete_v1'
  OR complete_body->>'binding_id' IS DISTINCT FROM binding_row.id::text
  OR complete_body->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb' OR complete_body->>'writer_job_id' IS DISTINCT FROM job_row.id::text
  OR jsonb_typeof(complete_body->'completed_top_xid') IS DISTINCT FROM 'string'
  OR (complete_body->>'completed_top_xid')::xid8::text IS DISTINCT FROM complete_body->>'completed_top_xid'
  OR complete_body->>'completed_top_xid'=body->>'bound_top_xid'
  OR (complete_body->>'completed_at')::timestamptz IS NULL OR (complete_body->>'completed_at')::timestamptz>clock_timestamp()
  OR (complete_body->>'completed_at')::timestamptz<(body->>'bound_at')::timestamptz
  OR (complete_body->>'completed_at')::timestamptz>=(body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact persistence completion DATA required'; END IF;
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id=(complete_body->>'artifact_id')::uuid;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.id=(complete_body->>'checkpoint_id')::uuid;
 IF artifact.id IS NULL OR checkpoint.id IS NULL
  OR (artifact.user_id,artifact.epoch,artifact.scope_id,artifact.job_id,artifact.lease_generation,artifact.lease_state_version,artifact.mode,artifact.artifact_key) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,1,2,'live','generation.d55f63a980434d748a1c0862660aed30')
  OR artifact.request_json IS DISTINCT FROM ctx->'request'
  OR artifact.source_json IS DISTINCT FROM capture->'result'->'source'
  OR artifact.receipt_json IS DISTINCT FROM capture->'result'->'receipt'
  OR artifact.source_hash IS DISTINCT FROM artifact.receipt_json->>'source_hash'
  OR artifact.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(artifact.source_json)
  OR artifact.content_hash IS DISTINCT FROM artifact.receipt_json->>'content_hash'
  OR artifact.artifact_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('source',artifact.source_json,'receipt',artifact.receipt_json))
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates c JOIN tutor_item_supply_private_versions v
   ON v.candidate_id=c.id AND v.user_id=c.user_id AND v.epoch=c.epoch AND v.scope_id=c.scope_id
   WHERE c.id=artifact.candidate_id AND (c.user_id,c.epoch,c.scope_id)=(artifact.user_id,artifact.epoch,artifact.scope_id)
   AND c.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   AND v.id=artifact.version_id AND v.version=1 AND v.public_json=artifact.source_json->'public' AND v.private_json=artifact.source_json->'private')
  OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,'generating',1,'completed',1,artifact.artifact_hash,'candidate_staged')
 THEN RAISE check_violation USING MESSAGE='562 exact actual artifact and generating checkpoint required'; END IF;
 IF complete_body->>'artifact_hash' IS DISTINCT FROM artifact.artifact_hash
  OR complete_body->>'candidate_id' IS DISTINCT FROM artifact.candidate_id::text OR complete_body->>'version_id' IS DISTINCT FROM artifact.version_id::text
 THEN RAISE check_violation USING MESSAGE='562 exact persistence completion artifact identity required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(complete_body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM complete_body->>'completed_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(complete_body->>'completed_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(complete_body->>'completed_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical completion SOURCE origin required'; END IF;
  origin_id:=(complete_body->>'source_origin_id')::uuid;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=job_row.id;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id=binding_row.pack_task_id AND p.user_id=binding_row.user_id AND p.epoch=binding_row.epoch
  AND p.scope_id=binding_row.scope_id AND p.record_kind='phase' AND p.operation_key='private.phase.'||job_row.id::text;
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',job_row.id,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',body->'ref'->'goal_scope_id','ref',body->'ref','lease',lease_json,
   'valid_until',phase_row.payload_json->'valid_until')
  OR (phase_row.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM (body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 complete accounting and slot phase required before commit'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF ctrl.state IS DISTINCT FROM 'leased' OR ctrl.breaker_open OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1
  OR ctrl.state_version<2 OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.lease_expires_at IS DISTINCT FROM (lease_json->>'expires_at')::timestamptz
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- Only the in-memory assertion receives refreshed state_version; immutable phase/binding snapshots stay at 2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.pack_task_id);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',binding_row.user_id,'epoch',binding_row.epoch,
  'scope_id',binding_row.scope_id,'job_id',job_row.id,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- No entry-time clock can authorize work after lock waits.
 stamp:=clock_timestamp();
 IF ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
   (body->>'valid_until')::timestamptz,(origin_row.payload_json->>'valid_until')::timestamptz)
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 IF ctrl.state_version<>3
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=job_row.id AND k.id<>checkpoint.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'job_id'=job_row.id::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='562 persistence TOP must contain no quality work'; END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.user_id=NEW.user_id AND j.epoch=NEW.epoch
   AND j.operation_key=NEW.operation_key AND j.record_kind='private_status')
  THEN RAISE check_violation USING MESSAGE='562 persistence completion already exists'; END IF;
 END IF;
 RETURN NEW;
END;$src$),
 ('enforce_private_generation_persistence_phase_atomic()', 'enforce_private_generation_persistence_phase_atomic()', 'trigger', false, $src$DECLARE d jsonb; capture jsonb; ctx jsonb; body jsonb; lease_json jsonb; complete_body jsonb; origin_id uuid;
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
 event_id uuid:=NEW.id; is_binding boolean:=false;
BEGIN
 IF TG_TABLE_NAME='tutor_item_supply_private_persistent_pack_journal' THEN
  IF COALESCE(NEW.payload_json->>'schema_version' NOT IN('private_generation_persistence_phase_v1','private_generation_persistence_complete_v1'),true) THEN RETURN NEW; END IF;
  is_binding:=NEW.payload_json->>'schema_version'='private_generation_persistence_phase_v1';
  identity:=CASE WHEN is_binding THEN NEW.id ELSE (NEW.payload_json->>'binding_id')::uuid END;
 ELSIF TG_TABLE_NAME='tutor_item_supply_private_generation_artifacts' THEN
  IF NEW.mode IS DISTINCT FROM 'live' OR NEW.user_id IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid OR NEW.epoch<>1
   OR NEW.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid THEN RETURN NEW; END IF;
  -- Select only this new writer's actual initial INSERT; other phases/child revisions are unchanged.
  SELECT j.id INTO identity FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb' AND j.record_kind='private_status'
   AND j.payload_json->>'schema_version'='private_generation_persistence_phase_v1' AND j.payload_json->>'writer_job_id'=NEW.job_id::text;
  IF identity IS NULL THEN RETURN NEW; END IF;
 ELSE RAISE check_violation USING MESSAGE='562 unexpected atomic trigger table'; END IF;
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND OR current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='562 current original namespace and active plan required'; END IF;
 -- Historical paid output: acquire original task/root/aux/approval/old-control locks before absence decisions.
 d:=item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb'
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id,j.record_kind,j.operation_key)=
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.generation.output.d55f63a980434d748a1c0862660aed30') FOR SHARE;
 capture:=output_row.payload_json->'capture'; ctx:=capture->'context';
 IF output_row.id IS NULL OR item_supply_internal.private_generation_output_committed('d55f63a9-8043-4d74-8a1c-0862660aed30',capture) IS DISTINCT FROM output_row.id
  OR d->'control'->>'job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'known'
  OR d->'binding'->'payload_json'->>'schema_version' IS DISTINCT FROM 'private_initial_author_continuation_binding_v1'
  OR ctx->'ref' IS DISTINCT FROM d->'binding'->'payload_json'->'ref'
  OR ctx->'request' IS DISTINCT FROM d->'binding'->'payload_json'->'request'
  OR ctx->'lease' IS DISTINCT FROM d->'binding'->'payload_json'->'lease'
  OR ctx->'ref'->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  OR ctx->'ref'->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
  OR ctx->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR ctx->>'mode' IS DISTINCT FROM 'live' OR capture->'result'->>'state' IS DISTINCT FROM 'staged'
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
   WHERE failed.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND failed.operation_key=replace(d->'binding'->>'operation_key','.binding','.failure'))
 THEN RAISE check_violation USING MESSAGE='562 fixed durable output required'; END IF;
 SELECT j.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=identity FOR SHARE;
 body:=binding_row.payload_json; lease_json:=body->'lease';
 IF binding_row.id IS NULL OR (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.record_kind,binding_row.operation_key,binding_row.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status','private.persistence.phase.f4519c6641304e34b05364dba6214dcb',d->'task'->>'intent_hash')
  OR item_supply_internal.snapshot_keys(body,ARRAY['schema_version','output_id','preparation_id','output_hash','original_binding_id','original_started_id','original_consumed_id','original_settlement_id','generation_job_id','generation_request_hash','generation_profile_hash','ref','writer_job_id','batch_id','lease','source_origin_id','bound_top_xid','bound_at','valid_until']) IS DISTINCT FROM true
  OR body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_phase_v1'
  OR body->>'output_id' IS DISTINCT FROM output_row.id::text OR body->>'preparation_id' IS DISTINCT FROM 'd55f63a9-8043-4d74-8a1c-0862660aed30'
  OR body->>'output_hash' IS DISTINCT FROM output_row.payload_hash
  OR body->'original_binding_id' IS DISTINCT FROM d->'binding'->'id'
  OR body->'original_started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'original_consumed_id' IS DISTINCT FROM d->'consumed'->'id'
  OR body->'original_settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'generation_job_id' IS DISTINCT FROM 'c9442831-e8d6-43b6-9367-b94875c60f36'
  OR body->>'generation_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(ctx->'request')
  OR body->'generation_profile_hash' IS DISTINCT FROM ctx->'request'->'profile'->'profile_hash'
  OR body->'ref' IS DISTINCT FROM ctx->'ref'
  OR item_supply_internal.snapshot_keys(lease_json,ARRAY['job_id','visibility','owner_id','owner_epoch','lease_owner','generation','state_version','expires_at','parent_deadline','profile','retry_policy']) IS DISTINCT FROM true
  OR (lease_json->>'job_id',lease_json->>'visibility',lease_json->>'owner_id',lease_json->>'owner_epoch',lease_json->>'lease_owner',lease_json->>'generation',lease_json->>'state_version') IS DISTINCT FROM
   (body->>'writer_job_id','private','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe','1','private.persistence.f4519c6641304e34b05364dba6214dcb','1','2')
  OR jsonb_typeof(body->'bound_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'bound_top_xid')::xid8::text IS DISTINCT FROM body->>'bound_top_xid'
  OR (body->>'bound_at')::timestamptz IS NULL OR (body->>'bound_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding DATA required'; END IF;
 SELECT j.* INTO job_row FROM tutor_item_supply_private_jobs j WHERE j.id=(body->>'writer_job_id')::uuid FOR SHARE;
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=job_row.id FOR UPDATE;
 SELECT p.* INTO profile_row FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id FOR SHARE;
 SELECT b.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches b WHERE b.id=(body->>'batch_id')::uuid FOR SHARE;
 IF job_row.id IS NULL OR ctrl.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id)
  OR job_row.id='c9442831-e8d6-43b6-9367-b94875c60f36' OR job_row.parent_job_id IS NOT NULL
  OR job_row.job_key IS DISTINCT FROM encode(sha256(convert_to('aaaf99e5-4530-4319-bb1a-0fe6d84020f9'||chr(31)||'private.persistence.phase.f4519c6641304e34b05364dba6214dcb','UTF8')),'hex')
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
  OR profile_row.profile_json->'profile_key'->>'agent_role' IS DISTINCT FROM 'native.private.persistent.persistence_quality.python-kc-binding-v1'
  OR profile_row.profile_json->'profile_key'->>'prompt_version' IS DISTINCT FROM 'private-durable-persistence-quality-v1'
  OR profile_row.profile_json->>'change_reason' IS DISTINCT FROM 'private_durable_output_new_phase_v1'
  OR profile_row.profile_json->>'state' IS DISTINCT FROM 'frozen'
  OR batch_row.id IS NULL OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ((ctrl.profile_snapshot_json->'profile'->>'bound_at')::timestamptz>=batch_row.started_at) IS DISTINCT FROM true
  OR lease_json->'profile' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'
  OR lease_json->'retry_policy' IS DISTINCT FROM ctrl.profile_snapshot_json->'retry_policy'
  OR (lease_json->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->'profile'->>'parent_deadline_at')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
  OR (lease_json->>'parent_deadline')::timestamptz>batch_row.valid_until
  OR (lease_json->>'expires_at')::timestamptz>(body->>'bound_at')::timestamptz+interval '3600 seconds'
  OR (body->>'bound_at')::timestamptz>=(body->>'valid_until')::timestamptz
  OR (body->>'valid_until')::timestamptz IS DISTINCT FROM LEAST((lease_json->>'expires_at')::timestamptz,
   (lease_json->>'parent_deadline')::timestamptz,(lease_json->'profile'->>'bound_at')::timestamptz+
   (lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='562 exact persistence binding profile and batch required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM body->>'bound_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(body->>'bound_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(body->>'bound_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical binding SOURCE origin required'; END IF;
 IF is_binding THEN
  IF body->>'bound_top_xid' IS DISTINCT FROM pg_current_xact_id()::text
  THEN RAISE check_violation USING MESSAGE='562 SQL current TOP binding marker required'; END IF;
  origin_id:=(body->>'source_origin_id')::uuid;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=job_row.id;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id=binding_row.pack_task_id AND p.user_id=binding_row.user_id AND p.epoch=binding_row.epoch
  AND p.scope_id=binding_row.scope_id AND p.record_kind='phase' AND p.operation_key='private.phase.'||job_row.id::text;
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',job_row.id,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',body->'ref'->'goal_scope_id','ref',body->'ref','lease',lease_json,
   'valid_until',phase_row.payload_json->'valid_until')
  OR (phase_row.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM (body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 complete accounting and slot phase required before commit'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF ctrl.state IS DISTINCT FROM 'leased' OR ctrl.breaker_open OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1
  OR ctrl.state_version<2 OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.lease_expires_at IS DISTINCT FROM (lease_json->>'expires_at')::timestamptz
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- Only the in-memory assertion receives refreshed state_version; immutable phase/binding snapshots stay at 2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.pack_task_id);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',binding_row.user_id,'epoch',binding_row.epoch,
  'scope_id',binding_row.scope_id,'job_id',job_row.id,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- No entry-time clock can authorize work after lock waits.
 stamp:=clock_timestamp();
 IF ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
   (body->>'valid_until')::timestamptz,(origin_row.payload_json->>'valid_until')::timestamptz)
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
  IF ctrl.state_version<>2 OR  EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=job_row.id)
   OR  EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND a.epoch=1
   AND a.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates c WHERE c.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND c.epoch=1
   AND c.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND q.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=binding_row.pack_task_id
    AND (j.operation_key=binding_row.operation_key||'.complete'
     OR (j.payload_json->>'job_id'=job_row.id::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))))
  THEN RAISE check_violation USING MESSAGE='562 persistence preparation TOP must contain no work'; END IF;
 ELSE
  IF body->>'bound_top_xid'=pg_current_xact_id()::text
  THEN RAISE check_violation USING MESSAGE='562 prior-TOP persistence binding required'; END IF;
  SELECT j.* INTO completion_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=binding_row.pack_task_id
   AND j.operation_key=binding_row.operation_key||'.complete' AND j.record_kind='private_status';
  IF completion_row.id IS NULL OR completion_row.payload_json->>'completed_top_xid' IS DISTINCT FROM pg_current_xact_id()::text
   OR (TG_TABLE_NAME='tutor_item_supply_private_persistent_pack_journal' AND completion_row.id IS DISTINCT FROM event_id)
   OR (TG_TABLE_NAME='tutor_item_supply_private_generation_artifacts' AND completion_row.payload_json->>'artifact_id' IS DISTINCT FROM event_id::text)
  THEN RAISE check_violation USING MESSAGE='562 same-TOP artifact checkpoint completion required before commit'; END IF;
  PERFORM 1 FROM item_supply_internal.private_generation_persistence_phase_completed_data(binding_row.id);
 complete_body:=completion_row.payload_json;
 IF completion_row.id IS NULL OR (completion_row.pack_task_id,completion_row.user_id,completion_row.epoch,completion_row.scope_id,completion_row.record_kind,completion_row.operation_key,completion_row.intent_hash) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,'private_status',binding_row.operation_key||'.complete',binding_row.intent_hash)
  OR item_supply_internal.snapshot_keys(complete_body,ARRAY['schema_version','binding_id','output_id','writer_job_id','artifact_id','artifact_hash','candidate_id','version_id','checkpoint_id','source_origin_id','completed_top_xid','completed_at']) IS DISTINCT FROM true
  OR complete_body->>'schema_version' IS DISTINCT FROM 'private_generation_persistence_complete_v1'
  OR complete_body->>'binding_id' IS DISTINCT FROM binding_row.id::text
  OR complete_body->>'output_id' IS DISTINCT FROM 'f4519c66-4130-4e34-b053-64dba6214dcb' OR complete_body->>'writer_job_id' IS DISTINCT FROM job_row.id::text
  OR jsonb_typeof(complete_body->'completed_top_xid') IS DISTINCT FROM 'string'
  OR (complete_body->>'completed_top_xid')::xid8::text IS DISTINCT FROM complete_body->>'completed_top_xid'
  OR complete_body->>'completed_top_xid'=body->>'bound_top_xid'
  OR (complete_body->>'completed_at')::timestamptz IS NULL OR (complete_body->>'completed_at')::timestamptz>clock_timestamp()
  OR (complete_body->>'completed_at')::timestamptz<(body->>'bound_at')::timestamptz
  OR (complete_body->>'completed_at')::timestamptz>=(body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact persistence completion DATA required'; END IF;
 SELECT a.* INTO artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id=(complete_body->>'artifact_id')::uuid;
 SELECT k.* INTO checkpoint FROM tutor_item_supply_private_checkpoints k WHERE k.id=(complete_body->>'checkpoint_id')::uuid;
 IF artifact.id IS NULL OR checkpoint.id IS NULL
  OR (artifact.user_id,artifact.epoch,artifact.scope_id,artifact.job_id,artifact.lease_generation,artifact.lease_state_version,artifact.mode,artifact.artifact_key) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,1,2,'live','generation.d55f63a980434d748a1c0862660aed30')
  OR artifact.request_json IS DISTINCT FROM ctx->'request'
  OR artifact.source_json IS DISTINCT FROM capture->'result'->'source'
  OR artifact.receipt_json IS DISTINCT FROM capture->'result'->'receipt'
  OR artifact.source_hash IS DISTINCT FROM artifact.receipt_json->>'source_hash'
  OR artifact.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(artifact.source_json)
  OR artifact.content_hash IS DISTINCT FROM artifact.receipt_json->>'content_hash'
  OR artifact.artifact_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('source',artifact.source_json,'receipt',artifact.receipt_json))
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates c JOIN tutor_item_supply_private_versions v
   ON v.candidate_id=c.id AND v.user_id=c.user_id AND v.epoch=c.epoch AND v.scope_id=c.scope_id
   WHERE c.id=artifact.candidate_id AND (c.user_id,c.epoch,c.scope_id)=(artifact.user_id,artifact.epoch,artifact.scope_id)
   AND c.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   AND v.id=artifact.version_id AND v.version=1 AND v.public_json=artifact.source_json->'public' AND v.private_json=artifact.source_json->'private')
  OR (checkpoint.user_id,checkpoint.epoch,checkpoint.scope_id,checkpoint.job_id,checkpoint.stage,checkpoint.attempt,checkpoint.status,checkpoint.lease_generation,checkpoint.receipt_hash,checkpoint.safe_reason) IS DISTINCT FROM
   (binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,job_row.id,'generating',1,'completed',1,artifact.artifact_hash,'candidate_staged')
 THEN RAISE check_violation USING MESSAGE='562 exact actual artifact and generating checkpoint required'; END IF;
 IF complete_body->>'artifact_hash' IS DISTINCT FROM artifact.artifact_hash
  OR complete_body->>'candidate_id' IS DISTINCT FROM artifact.candidate_id::text OR complete_body->>'version_id' IS DISTINCT FROM artifact.version_id::text
 THEN RAISE check_violation USING MESSAGE='562 exact persistence completion artifact identity required'; END IF;
 SELECT o.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal o WHERE o.id=(complete_body->>'source_origin_id')::uuid;
 IF origin_row.id IS NULL OR (origin_row.pack_task_id,origin_row.user_id,origin_row.epoch,origin_row.scope_id,origin_row.record_kind) IS DISTINCT FROM
   (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,'current_pack_source_origin')
  OR origin_row.payload_json->>'capture_txid' IS DISTINCT FROM complete_body->>'completed_top_xid'
  OR (origin_row.payload_json->>'issued_at')::timestamptz>(complete_body->>'completed_at')::timestamptz
  OR (origin_row.payload_json->>'valid_until')::timestamptz<=(complete_body->>'completed_at')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 exact historical completion SOURCE origin required'; END IF;
  origin_id:=(complete_body->>'source_origin_id')::uuid;
 SELECT m.* INTO mapping_row FROM tutor_item_supply_private_development_model_accounting_jobs m WHERE m.job_id=job_row.id;
 SELECT p.* INTO phase_row FROM tutor_item_supply_private_persistent_pack_journal p
  WHERE p.pack_task_id=binding_row.pack_task_id AND p.user_id=binding_row.user_id AND p.epoch=binding_row.epoch
  AND p.scope_id=binding_row.scope_id AND p.record_kind='phase' AND p.operation_key='private.phase.'||job_row.id::text;
 IF mapping_row.id IS NULL OR phase_row.id IS NULL
  OR (mapping_row.user_id,mapping_row.epoch,mapping_row.scope_id,mapping_row.root_id,mapping_row.batch_id,mapping_row.window_id) IS DISTINCT FROM
   (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id,batch_row.id,batch_row.window_id)
  OR mapping_row.parent_job_id IS NOT NULL OR mapping_row.lease_generation<>1 OR mapping_row.lease_state_version<>2
  OR mapping_row.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR mapping_row.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
  OR mapping_row.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR phase_row.payload_json IS DISTINCT FROM jsonb_build_object('schema_version','private_native_phase_v1',
   'root_id','aaaf99e5-4530-4319-bb1a-0fe6d84020f9','job_id',job_row.id,'slot_id','f2b5a6dd-97d2-52dd-8962-68962f6ea76c','business_item_id','7e9c4444-5b16-53c1-ad8b-39b402e5aa51',
   'goal_scope_id',body->'ref'->'goal_scope_id','ref',body->'ref','lease',lease_json,
   'valid_until',phase_row.payload_json->'valid_until')
  OR (phase_row.payload_json->>'valid_until')::timestamptz IS DISTINCT FROM (body->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 complete accounting and slot phase required before commit'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 IF ctrl.state IS DISTINCT FROM 'leased' OR ctrl.breaker_open OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1
  OR ctrl.state_version<2 OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.lease_expires_at IS DISTINCT FROM (lease_json->>'expires_at')::timestamptz
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- Only the in-memory assertion receives refreshed state_version; immutable phase/binding snapshots stay at 2.
 PERFORM item_supply_internal.assert_private_native_phase(jsonb_set(phase_row.payload_json,'{lease,state_version}',to_jsonb(ctrl.state_version)),
  binding_row.user_id,binding_row.epoch,binding_row.scope_id,binding_row.pack_task_id);
 IF item_supply_internal.current_pack_source_origin_current(origin_id,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'d8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
  OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ctx->'ref','request',ctx->'request',
   'source_receipts',capture->'result'->'receipt'->'sources')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 IF item_supply_internal.private_native_generation_goal_current(jsonb_build_object('user_id',binding_row.user_id,'epoch',binding_row.epoch,
  'scope_id',binding_row.scope_id,'job_id',job_row.id,'mode','live','request_json',ctx->'request',
  'source_json',capture->'result'->'source','receipt_json',capture->'result'->'receipt')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 -- No entry-time clock can authorize work after lock waits.
 stamp:=clock_timestamp();
 IF ctrl.parent_deadline>LEAST(batch_row.valid_until,source_end)
  OR stamp>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,source_end,
   (body->>'valid_until')::timestamptz,(origin_row.payload_json->>'valid_until')::timestamptz)
 THEN RAISE check_violation USING MESSAGE='562 current persistence writer and source required'; END IF;
 IF ctrl.state_version<>3
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations r WHERE r.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints k WHERE k.job_id=job_row.id AND k.id<>checkpoint.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_pipeline_receipts p WHERE p.job_id=job_row.id)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'job_id'=job_row.id::text AND j.payload_json->>'schema_version' IN('private_native_auxiliary_v1','private_native_stage_v1'))
 THEN RAISE check_violation USING MESSAGE='562 persistence TOP must contain no quality work'; END IF;
 END IF;
 RETURN NEW;
END;$src$),
 ('private_generation_persistence_phase_ready()', 'private_generation_persistence_phase_ready()', 'boolean', false, $src$DECLARE spec record; actual record; names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' OR item_supply_internal.private_generation_durability_ready() IS DISTINCT FROM true THEN RETURN false; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_generation_persistence_phase_completed_data(uuid)','private_generation_persistence_phase_completed_data(p_binding uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'221baee4c174a64fcb8dbde766bd2b57b4b86d5c7da1ed528df6fb886b249338'),
 ('private_generation_persistence_phase_bound(uuid,uuid)','private_generation_persistence_phase_bound(p_binding uuid,p_origin uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'4519600aeff6fe79a6d61d4be65afbcb23f299e606c9c19bdeda85221ecc2a89'),
 ('private_generation_persistence_phase_first_claim(uuid,uuid,uuid,uuid)','private_generation_persistence_phase_first_claim(p_output uuid,p_job uuid,p_batch uuid,p_origin uuid)','public.tutor_item_supply_private_job_controls',true,'8e9602b86217f4c05690db8f7961e298722930cd2642137b609f4bb9ee5ef1e7'),
 ('private_generation_persistence_phase_complete(uuid,uuid,uuid)','private_generation_persistence_phase_complete(p_binding uuid,p_artifact uuid,p_origin uuid)','uuid',false,'b0a56a7adff4224a8b5250d42ae463c1a18b5450b317c814b1b66c1093a1d827'),
 ('private_generation_persistence_phase_committed(uuid,uuid)','private_generation_persistence_phase_committed(p_binding uuid,p_origin uuid)','public.tutor_item_supply_private_persistent_pack_journal',true,'8dd8953cb187ccc08fc118cacfdb9b3a5b4dac1a7d34783cbbac63c28b3c40d7'),
 ('enforce_private_generation_persistence_phase_insert()','enforce_private_generation_persistence_phase_insert()','trigger',false,'a8b8db5904071f0f36391a3c01362decc3961a79d152350d6ce532265ad59584'),
 ('enforce_private_generation_persistence_phase_atomic()','enforce_private_generation_persistence_phase_atomic()','trigger',false,'72090595026c9b2f5825c90e176d51fdc3260b281aea4f1dfc0cbfb35ae4e70b'),
 ('private_generation_persistence_phase_ready()','private_generation_persistence_phase_ready()','boolean',false,NULL::text)
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
  ('tutor_item_supply_private_persistent_pack_journal','a000_private_generation_persistence_phase_insert','enforce_private_generation_persistence_phase_insert',7,false),
  ('tutor_item_supply_private_persistent_pack_journal','private_generation_persistence_phase_atomic','enforce_private_generation_persistence_phase_atomic',5,true),
  ('tutor_item_supply_private_generation_artifacts','private_generation_persistence_artifact_atomic','enforce_private_generation_persistence_phase_atomic',5,true)
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
   THEN RAISE check_violation USING MESSAGE='562 unexpected existing receiver definition/metadata: '||spec.signature; END IF;
  ELSE
   EXECUTE 'CREATE FUNCTION item_supply_internal.'||spec.header||' RETURNS '||CASE WHEN spec.is_set THEN 'SETOF ' ELSE '' END||spec.result_type||
    ' LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS '||quote_literal(spec.body);
   EXECUTE 'ALTER FUNCTION item_supply_internal.'||spec.signature||' OWNER TO aearn_b1d_runtime_20261001';
   EXECUTE 'REVOKE ALL ON FUNCTION item_supply_internal.'||spec.signature||' FROM PUBLIC';
  END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','a000_private_generation_persistence_phase_insert','enforce_private_generation_persistence_phase_insert',7,false,
   'CREATE TRIGGER a000_private_generation_persistence_phase_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_generation_persistence_phase_insert()'),
  ('tutor_item_supply_private_persistent_pack_journal','private_generation_persistence_phase_atomic','enforce_private_generation_persistence_phase_atomic',5,true,
   'CREATE CONSTRAINT TRIGGER private_generation_persistence_phase_atomic AFTER INSERT ON public.tutor_item_supply_private_persistent_pack_journal DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_generation_persistence_phase_atomic()'),
  ('tutor_item_supply_private_generation_artifacts','private_generation_persistence_artifact_atomic','enforce_private_generation_persistence_phase_atomic',5,true,
   'CREATE CONSTRAINT TRIGGER private_generation_persistence_artifact_atomic AFTER INSERT ON public.tutor_item_supply_private_generation_artifacts DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_generation_persistence_phase_atomic()')
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
    AND k.conname=tr.trigger_name AND k.conrelid=prior.tgrelid AND k.condeferrable AND k.condeferred AND k.convalidated)) THEN RAISE check_violation USING MESSAGE='562 unexpected existing receiver trigger: '||tr.trigger_name; END IF;
  ELSE EXECUTE tr.ddl; END IF;
 END LOOP;
END;
$install562$;

DO $patchart562$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldart562$
DECLARE output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; output_id uuid; p_preparation uuid;
BEGIN
 IF NEW.mode IS DISTINCT FROM 'live' OR NEW.user_id IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid OR NEW.epoch<>1
  OR NEW.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid THEN RETURN NEW; END IF;
 -- Inherited/idempotent staging of an already existing exact generation is not a new author.
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE
  (a.user_id,a.epoch,a.scope_id,a.job_id,a.lease_generation,a.artifact_key,a.candidate_id,a.version_id,a.mode,a.source_hash,a.content_hash,a.request_json,a.source_json,a.receipt_json)=
  (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id,NEW.lease_generation,NEW.artifact_key,NEW.candidate_id,NEW.version_id,NEW.mode,NEW.source_hash,NEW.content_hash,NEW.request_json,NEW.source_json,NEW.receipt_json)) THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal phase WHERE phase.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND phase.user_id=NEW.user_id AND phase.epoch=NEW.epoch AND phase.scope_id=NEW.scope_id AND phase.record_kind='phase'
  AND phase.payload_json->>'schema_version'='private_native_phase_v1' AND phase.payload_json->>'job_id'=NEW.job_id::text
  AND phase.payload_json->'ref'->'parent_version_id'='null'::jsonb) THEN RETURN NEW; END IF;
 p_preparation:=(NEW.request_json->>'candidate_id')::uuid;
 -- Establish the common lock domain before inspecting output/gap rows.
 PERFORM item_supply_internal.private_generation_durability_attempt(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.operation_key='private.generation.output.'||replace(p_preparation::text,'-','');
 output_id:=item_supply_internal.private_generation_output_committed(p_preparation,output_row.payload_json->'capture');
 IF output_id IS NULL OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM NEW.request_json
  OR output_row.payload_json->'capture'->'context'->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
  OR output_row.payload_json->'capture'->'context'->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
  OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM NEW.source_json
  OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
 THEN RAISE check_violation USING MESSAGE='560 exact separately committed output required before original artifact'; END IF;
 RETURN NEW; -- Original559 current goal/source/control/content and all later guards remain.
END;
$oldart562$;
 new_body constant text := $newart562$
DECLARE output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; output_id uuid; p_preparation uuid;
 bridge_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; origin_id uuid; origin_count bigint;
BEGIN
 IF NEW.mode IS DISTINCT FROM 'live' OR NEW.user_id IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid OR NEW.epoch<>1
  OR NEW.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid THEN RETURN NEW; END IF;
 -- Inherited/idempotent staging of an already existing exact generation is not a new author.
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE
  (a.user_id,a.epoch,a.scope_id,a.job_id,a.lease_generation,a.artifact_key,a.candidate_id,a.version_id,a.mode,a.source_hash,a.content_hash,a.request_json,a.source_json,a.receipt_json)=
  (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id,NEW.lease_generation,NEW.artifact_key,NEW.candidate_id,NEW.version_id,NEW.mode,NEW.source_hash,NEW.content_hash,NEW.request_json,NEW.source_json,NEW.receipt_json)) THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal phase WHERE phase.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND phase.user_id=NEW.user_id AND phase.epoch=NEW.epoch AND phase.scope_id=NEW.scope_id AND phase.record_kind='phase'
  AND phase.payload_json->>'schema_version'='private_native_phase_v1' AND phase.payload_json->>'job_id'=NEW.job_id::text
  AND phase.payload_json->'ref'->'parent_version_id'='null'::jsonb) THEN RETURN NEW; END IF;
 -- C18: this one separately committed output may use its one committed new writer, not a recovered author.
 SELECT j.* INTO bridge_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.user_id=NEW.user_id AND j.epoch=NEW.epoch AND j.scope_id=NEW.scope_id AND j.record_kind='private_status'
  AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb' AND j.payload_json->>'schema_version'='private_generation_persistence_phase_v1'
  AND j.payload_json->>'writer_job_id'=NEW.job_id::text;
 IF bridge_row.id IS NOT NULL THEN
  PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
  PERFORM item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
  IF bridge_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
  THEN RAISE check_violation USING MESSAGE='562 prior-TOP persistence binding required'; END IF;
  SELECT count(*),(array_agg(o.id ORDER BY o.id))[1] INTO origin_count,origin_id FROM tutor_item_supply_private_persistent_pack_journal o
   WHERE o.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND o.user_id=NEW.user_id AND o.epoch=NEW.epoch AND o.scope_id=NEW.scope_id
   AND o.record_kind='current_pack_source_origin' AND o.payload_json->>'capture_txid'=pg_current_xact_id()::text
   AND item_supply_internal.current_pack_source_origin_current(o.id,NEW.user_id,NEW.epoch,'d8e34e01-3514-41a3-9bbd-55ee3e627134');
  IF origin_count<>1 THEN RAISE check_violation USING MESSAGE='562 one actual same-TOP SOURCE origin required'; END IF;
  SELECT b.* INTO bridge_row FROM item_supply_internal.private_generation_persistence_phase_bound(bridge_row.id,origin_id) b;
  SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb';
  IF bridge_row.payload_json->>'output_id' IS DISTINCT FROM output_row.id::text
   OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM NEW.request_json
   OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM NEW.source_json
   OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
   OR bridge_row.payload_json->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
   OR bridge_row.payload_json->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
   OR NEW.lease_state_version<>2 OR NEW.artifact_key IS DISTINCT FROM 'generation.d55f63a980434d748a1c0862660aed30'
  THEN RAISE check_violation USING MESSAGE='562 exact output to persistence writer artifact required'; END IF;
  RETURN NEW; -- Original559 still checks actual candidate/version, full source/goal, control CAS and final clock.
 END IF;
 p_preparation:=(NEW.request_json->>'candidate_id')::uuid;
 -- Establish the common lock domain before inspecting output/gap rows.
 PERFORM item_supply_internal.private_generation_durability_attempt(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.operation_key='private.generation.output.'||replace(p_preparation::text,'-','');
 output_id:=item_supply_internal.private_generation_output_committed(p_preparation,output_row.payload_json->'capture');
 IF output_id IS NULL OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM NEW.request_json
  OR output_row.payload_json->'capture'->'context'->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
  OR output_row.payload_json->'capture'->'context'->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
  OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM NEW.source_json
  OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
 THEN RAISE check_violation USING MESSAGE='560 exact separately committed output required before original artifact'; END IF;
 RETURN NEW; -- Original559 current goal/source/control/content and all later guards remain.
END;
$newart562$;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_private_generation_durability_artifact()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'enforce_private_generation_durability_artifact' OR actual.prosecdef IS DISTINCT FROM true OR actual.prokind<>'f'
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.prorettype IS DISTINCT FROM to_regtype('pg_catalog.trigger') OR actual.proargnames IS DISTINCT FROM NULL::text[]
   OR actual.pronargs IS DISTINCT FROM COALESCE(cardinality(NULL::text[]),0)
   OR actual.proretset IS DISTINCT FROM false OR actual.provolatile<>'v' OR actual.proisstrict OR actual.proleakproof OR actual.proparallel<>'u'
   OR actual.procost<>100 OR actual.prorows IS DISTINCT FROM (CASE WHEN false THEN 1000::real ELSE 0::real END)
   OR actual.prosupport<>0 OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL OR actual.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 THEN RAISE check_violation USING MESSAGE='562 original art receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body THEN RAISE check_violation USING MESSAGE='562 original art receiver body changed'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='562 original art receiver framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc') OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='562 art receiver metadata/OID/owner/ACL/body changed'; END IF;
END;
$patchart562$;

DO $patchterm562$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldterm562$
DECLARE requested public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 head_artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 attempt_key text; known_ancestor boolean:=false;
BEGIN
 SELECT journal.* INTO requested FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_started AND journal.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND journal.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND journal.epoch=1 AND journal.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND journal.record_kind='private_status' AND journal.payload_json->>'schema_version'='private_native_stage_v1'
  AND journal.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND journal.payload_json->>'stage'='author'
  AND journal.payload_json->>'status'='started' AND journal.payload_json->'receipt_id'='null'::jsonb
  AND journal.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF requested.id IS NULL THEN RETURN NULL; END IF;
 failure_row:=item_supply_internal.private_initial_author_continuation_predecessor('df0a6e8c-287a-4814-98f1-5deeb59347a3',requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 known_ancestor:=requested.id='5ad70ab7-0441-456b-ae5e-156755a80911'
  OR (requested.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started' AND requested.id::text=failure_row.payload_json->>'started_id');
 LOOP
  -- Follow the sole deterministic successor, never timestamp ordering or arbitrary started rows.
  attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(failure_row.id::text,'-','');
  SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.approval'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF approval_row.id IS NULL THEN
   IF known_ancestor THEN
    IF failure_row.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' THEN RETURN 'technical_gap'; END IF;
    RETURN 'failure';
   ELSE RETURN NULL; END IF;
  END IF;
  approval_row:=item_supply_internal.private_initial_author_continuation_approval(approval_row.id);
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.binding'
   AND journal.payload_json->>'approval_id'=approval_row.id::text AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  SELECT journal.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.author.started'
   AND journal.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF binding_row.id IS NULL OR started_row.id IS NULL THEN RETURN NULL; END IF;
  known_ancestor:=known_ancestor OR requested.id=started_row.id;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done
   JOIN tutor_item_supply_private_persistent_pack_journal consumed ON consumed.pack_task_id=done.pack_task_id
    AND consumed.operation_key=attempt_key||'.consumed' AND consumed.payload_json->>'binding_id'=binding_row.id::text
    AND consumed.payload_json->>'started_id'=started_row.id::text
   JOIN tutor_item_supply_private_generation_artifacts artifact ON artifact.id=(done.payload_json->>'receipt_id')::uuid
    AND artifact.job_id=(binding_row.payload_json->'lease'->>'job_id')::uuid AND artifact.request_json=binding_row.payload_json->'request'
    AND artifact.lease_generation=1 AND artifact.mode='live'
   JOIN tutor_item_supply_private_candidates candidate ON candidate.id=artifact.candidate_id
    AND candidate.user_id=requested.user_id AND candidate.epoch=requested.epoch AND candidate.scope_id=requested.scope_id
    AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   JOIN tutor_item_supply_private_versions version ON version.id=artifact.version_id AND version.candidate_id=candidate.id AND version.version=1
   JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.reservation_id=(binding_row.payload_json->>'reservation_id')::uuid
    AND settlement.settlement_key='generation.'||replace(binding_row.payload_json->>'candidate_id','-','') AND settlement.sequence=1
   WHERE done.pack_task_id=requested.pack_task_id AND done.operation_key=attempt_key||'.author.result'
   AND done.payload_json->>'schema_version'='private_native_stage_v1' AND done.payload_json->>'stage'='author'
   AND done.payload_json->>'status'='committed' AND done.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND done.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   AND done.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
   AND consumed.payload_json->>'candidate_id'=binding_row.payload_json->>'candidate_id'
   AND consumed.payload_json->>'job_id'=artifact.job_id::text AND consumed.payload_json->>'reservation_id'=settlement.reservation_id::text
   AND done.xmin::text::bigint<>(txid_current()%4294967296) AND artifact.xmin::text::bigint<>(txid_current()%4294967296)
   AND consumed.xmin::text::bigint<>(txid_current()%4294967296) AND settlement.xmin::text::bigint<>(txid_current()%4294967296))
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
    WHERE failed.pack_task_id=requested.pack_task_id AND failed.operation_key=attempt_key||'.failure')
  THEN
   IF NOT known_ancestor THEN RETURN NULL; END IF;
   SELECT artifact.* INTO head_artifact FROM tutor_item_supply_private_generation_artifacts artifact
    JOIN tutor_item_supply_private_persistent_pack_journal done ON done.pack_task_id=requested.pack_task_id
     AND done.operation_key=attempt_key||'.author.result' AND artifact.id=(done.payload_json->>'receipt_id')::uuid;
   -- Durable terminal quality is DATA, not a restored live work capability.
   -- Bind the original full validation/blind/six-role review to THIS head artifact/spec/ref.
   SELECT review.* INTO peer FROM tutor_item_supply_private_native_quality_evidence review
    JOIN tutor_item_supply_private_native_quality_evidence validation ON validation.kind='validation'
     AND (validation.user_id,validation.epoch,validation.scope_id,validation.pack_task_id,validation.slot_id,validation.root_id,validation.version_id,validation.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND validation.payload_json->>'state'='machine_verified'
     AND validation.payload_json->>'source_hash'=head_artifact.source_hash AND validation.payload_json->>'content_hash'=head_artifact.content_hash
     AND validation.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_native_quality_evidence blind ON blind.kind='blind'
     AND (blind.user_id,blind.epoch,blind.scope_id,blind.pack_task_id,blind.slot_id,blind.root_id,blind.version_id,blind.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND blind.payload_json=review.payload_json->'bundle'->'blind_solve' AND blind.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_persistent_pack_journal review_done ON review_done.pack_task_id=review.pack_task_id
     AND review_done.user_id=review.user_id AND review_done.epoch=review.epoch AND review_done.scope_id=review.scope_id
     AND review_done.record_kind='private_status' AND review_done.payload_json->>'schema_version'='private_native_stage_v1'
     AND review_done.payload_json->>'stage'='review' AND review_done.payload_json->>'status'='committed'
     AND review_done.payload_json->>'slot_id'=review.slot_id::text AND review_done.payload_json->>'job_id'=review.job_id::text
     AND review_done.payload_json->>'receipt_id'=review.id::text AND review_done.xmin::text::bigint<>(txid_current()%4294967296)
    WHERE review.kind='review' AND review.user_id=requested.user_id AND review.epoch=requested.epoch AND review.scope_id=requested.scope_id
    AND review.pack_task_id=requested.pack_task_id AND review.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
    AND review.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND review.version_id=head_artifact.version_id
    AND review.payload_json->>'schema_version'='private_native_review_v1' AND review.payload_json->>'artifact_id'=head_artifact.id::text
    AND review.payload_json->'ref'=binding_row.payload_json->'ref'
    AND review.payload_json->'spec'->'public_template'=head_artifact.request_json->'public_template'
    AND review.payload_json->'spec'->'blueprint'=head_artifact.request_json->'blueprint'
    AND review.payload_json->'bundle'->>'state'='completed' AND review.payload_json->'bundle'->>'mode'='peer_blind'
    AND review.payload_json->'bundle'->'binding'->>'version_key'=head_artifact.version_id::text
    AND review.payload_json->'bundle'->'binding'->>'source_hash'=head_artifact.source_hash
    AND review.payload_json->'bundle'->'binding'->>'content_hash'=head_artifact.content_hash
    AND jsonb_array_length(review.payload_json->'bundle'->'reports')=6
    AND (SELECT array_agg(report->>'role' ORDER BY report->>'role') FROM jsonb_array_elements(review.payload_json->'bundle'->'reports') report)
     =ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
    AND review.checked_at<review.valid_until AND review.created_at<review.valid_until
    AND review.xmin::text::bigint<>(txid_current()%4294967296);
   IF peer.id IS NOT NULL THEN
    -- Original timeless receiver verifies committed exact original7 preparation,
    -- validation, reservation, settlement and review policy/spec/artifact binding.
    PERFORM item_supply_internal.assert_private_native_review_stage(peer);
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications publication
     JOIN tutor_item_supply_private_native_quality_evidence quality ON quality.id=publication.quality_id AND quality.kind='admission'
      AND (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)=
          (publication.user_id,publication.epoch,publication.scope_id,publication.pack_task_id,publication.slot_id,publication.root_id,publication.version_id)
      AND quality.payload_json->>'schema_version'='private_native_quality_v1'
      AND quality.payload_json->>'receipt_id'=quality.id::text AND quality.payload_json->>'version_id'=head_artifact.version_id::text
      AND quality.payload_json->>'generation_artifact_id'=head_artifact.id::text AND quality.payload_json->>'review_receipt_id'=peer.id::text
      AND quality.payload_json->'ref'=peer.payload_json->'ref' AND quality.payload_json->'spec'=peer.payload_json->'spec'
      AND quality.payload_json->'bundle'=peer.payload_json->'bundle' AND quality.payload_json->'source'=head_artifact.source_json
      AND quality.payload_json->'request'=head_artifact.request_json AND quality.payload_json->'source_receipts'=head_artifact.receipt_json->'sources'
      AND quality.payload_json->'evaluation'->>'disposition'='eligible_internal' AND quality.payload_json->'evaluation'->'publication_enabled'='false'::jsonb
      AND quality.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_validation ON admitted_validation.id=(quality.payload_json->>'validation_receipt_id')::uuid
      AND admitted_validation.kind='validation' AND admitted_validation.payload_json=quality.payload_json->'validation'
      AND (admitted_validation.user_id,admitted_validation.epoch,admitted_validation.scope_id,admitted_validation.pack_task_id,admitted_validation.slot_id,admitted_validation.root_id,admitted_validation.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_validation.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_blind ON admitted_blind.id=(quality.payload_json->>'blind_receipt_id')::uuid
      AND admitted_blind.kind='blind' AND admitted_blind.payload_json=peer.payload_json->'bundle'->'blind_solve'
      AND (admitted_blind.user_id,admitted_blind.epoch,admitted_blind.scope_id,admitted_blind.pack_task_id,admitted_blind.slot_id,admitted_blind.root_id,admitted_blind.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_blind.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_versions version ON version.id=publication.version_id AND version.user_id=publication.user_id AND version.epoch=publication.epoch
      AND version.public_json=head_artifact.source_json->'public' AND version.private_json=head_artifact.source_json->'private'
     JOIN tutor_exercise_versions exercise ON exercise.id=publication.exercise_version_id AND exercise.source_kind='registered_author'
      AND exercise.content_hash=publication.payload_json->>'exercise_content_hash'
      AND exercise.exercise_key=head_artifact.source_json->'public'->>'item_key' AND exercise.version=head_artifact.source_json->'public'->>'version'
     JOIN tutor_exercise_private_rubrics rubric ON rubric.exercise_version_id=exercise.id AND rubric.rubric_hash=publication.payload_json->>'rubric_hash'
     WHERE publication.pack_task_id=requested.pack_task_id AND publication.user_id=requested.user_id AND publication.epoch=requested.epoch
     AND publication.scope_id=requested.scope_id AND publication.slot_id=peer.slot_id AND publication.root_id=peer.root_id
     AND publication.version_id=head_artifact.version_id AND publication.state='published'
     AND publication.payload_json->>'schema_version'='private_native_publication_v1'
     AND publication.payload_json->>'publication_id'=publication.id::text AND publication.payload_json->>'quality_id'=quality.id::text
     AND publication.payload_json->>'quality_hash'=quality.payload_hash AND publication.payload_json->'ref'=quality.payload_json->'ref'
     AND publication.payload_json->>'source_hash'=item_supply_internal.snapshot_hash(quality.payload_json->'source')
     AND publication.payload_json->>'content_hash'=peer.payload_json->'bundle'->'binding'->>'content_hash'
     AND publication.payload_json->>'item_handle'=version.handle AND publication.content_json->>'item_handle'=version.handle
     AND publication.xmin::text::bigint<>(txid_current()%4294967296)
     AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications successor
      WHERE successor.version_id=publication.version_id AND successor.user_id=publication.user_id AND successor.epoch=publication.epoch
      AND successor.state_version>publication.state_version)) THEN RETURN 'published'; END IF;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') report
     WHERE report->>'verdict'<>'approved' OR EXISTS(SELECT 1 FROM jsonb_array_elements(report->'findings') finding
      WHERE finding->>'blocking'='true' OR finding->>'severity' IN('major','critical')
      OR finding->>'safe_code' IN('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit')))
    THEN RETURN 'review_failed'; END IF;
   END IF;
   RETURN 'artifact';
  END IF;
  SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.failure';
  IF failure_row.id IS NULL AND binding_row.id='af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid THEN
   SELECT j.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal j
    WHERE j.pack_task_id=requested.pack_task_id AND j.operation_key='private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'
    AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1'
    AND j.payload_json->>'binding_id'=binding_row.id::text;
  END IF;
  IF failure_row.id IS NULL THEN RETURN NULL; END IF;
  failure_row:=item_supply_internal.private_initial_author_continuation_predecessor(failure_row.id,requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 END LOOP;
END;
$oldterm562$;
 new_body constant text := $newterm562$
DECLARE requested public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 head_artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 attempt_key text; known_ancestor boolean:=false; bridge_head boolean:=false;
 bridge_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT journal.* INTO requested FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_started AND journal.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND journal.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND journal.epoch=1 AND journal.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND journal.record_kind='private_status' AND journal.payload_json->>'schema_version'='private_native_stage_v1'
  AND journal.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND journal.payload_json->>'stage'='author'
  AND journal.payload_json->>'status'='started' AND journal.payload_json->'receipt_id'='null'::jsonb
  AND journal.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF requested.id IS NULL THEN RETURN NULL; END IF;
 failure_row:=item_supply_internal.private_initial_author_continuation_predecessor('df0a6e8c-287a-4814-98f1-5deeb59347a3',requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 known_ancestor:=requested.id='5ad70ab7-0441-456b-ae5e-156755a80911'
  OR (requested.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started' AND requested.id::text=failure_row.payload_json->>'started_id');
 LOOP
  -- Follow the sole deterministic successor, never timestamp ordering or arbitrary started rows.
  attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(failure_row.id::text,'-','');
  SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.approval'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF approval_row.id IS NULL THEN
   IF known_ancestor THEN
    IF failure_row.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' THEN RETURN 'technical_gap'; END IF;
    RETURN 'failure';
   ELSE RETURN NULL; END IF;
  END IF;
  approval_row:=item_supply_internal.private_initial_author_continuation_approval(approval_row.id);
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.binding'
   AND journal.payload_json->>'approval_id'=approval_row.id::text AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  SELECT journal.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.author.started'
   AND journal.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF binding_row.id IS NULL OR started_row.id IS NULL THEN RETURN NULL; END IF;
  known_ancestor:=known_ancestor OR requested.id=started_row.id;
  -- C18 completion is immutable provenance; it is NOT fresh-current work permission.
  bridge_head:=false;
  IF binding_row.payload_json->>'preparation_id'='d55f63a9-8043-4d74-8a1c-0862660aed30'
   AND binding_row.payload_json->'lease'->>'job_id'='c9442831-e8d6-43b6-9367-b94875c60f36' THEN
   SELECT j.* INTO bridge_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=requested.pack_task_id
    AND j.user_id=requested.user_id AND j.epoch=requested.epoch AND j.scope_id=requested.scope_id AND j.record_kind='private_status'
    AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb' AND j.payload_json->>'output_id'='f4519c66-4130-4e34-b053-64dba6214dcb'
    AND j.payload_json->>'original_binding_id'=binding_row.id::text AND j.payload_json->>'original_started_id'=started_row.id::text;
   SELECT j.* INTO completion_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=requested.pack_task_id
    AND j.user_id=requested.user_id AND j.epoch=requested.epoch AND j.scope_id=requested.scope_id AND j.record_kind='private_status'
    AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb.complete' AND j.payload_json->>'binding_id'=bridge_row.id::text;
   IF bridge_row.id IS NOT NULL AND completion_row.id IS NOT NULL THEN
    IF NOT known_ancestor OR bridge_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
     OR completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text THEN RETURN NULL; END IF;
    SELECT c.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data(bridge_row.id) c;
    SELECT a.* INTO head_artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id=(completion_row.payload_json->>'artifact_id')::uuid;
    bridge_head:=true;
   END IF;
  END IF;
  IF bridge_head OR (EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done
   JOIN tutor_item_supply_private_persistent_pack_journal consumed ON consumed.pack_task_id=done.pack_task_id
    AND consumed.operation_key=attempt_key||'.consumed' AND consumed.payload_json->>'binding_id'=binding_row.id::text
    AND consumed.payload_json->>'started_id'=started_row.id::text
   JOIN tutor_item_supply_private_generation_artifacts artifact ON artifact.id=(done.payload_json->>'receipt_id')::uuid
    AND artifact.job_id=(binding_row.payload_json->'lease'->>'job_id')::uuid AND artifact.request_json=binding_row.payload_json->'request'
    AND artifact.lease_generation=1 AND artifact.mode='live'
   JOIN tutor_item_supply_private_candidates candidate ON candidate.id=artifact.candidate_id
    AND candidate.user_id=requested.user_id AND candidate.epoch=requested.epoch AND candidate.scope_id=requested.scope_id
    AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   JOIN tutor_item_supply_private_versions version ON version.id=artifact.version_id AND version.candidate_id=candidate.id AND version.version=1
   JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.reservation_id=(binding_row.payload_json->>'reservation_id')::uuid
    AND settlement.settlement_key='generation.'||replace(binding_row.payload_json->>'candidate_id','-','') AND settlement.sequence=1
   WHERE done.pack_task_id=requested.pack_task_id AND done.operation_key=attempt_key||'.author.result'
   AND done.payload_json->>'schema_version'='private_native_stage_v1' AND done.payload_json->>'stage'='author'
   AND done.payload_json->>'status'='committed' AND done.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND done.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   AND done.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
   AND consumed.payload_json->>'candidate_id'=binding_row.payload_json->>'candidate_id'
   AND consumed.payload_json->>'job_id'=artifact.job_id::text AND consumed.payload_json->>'reservation_id'=settlement.reservation_id::text
   AND done.xmin::text::bigint<>(txid_current()%4294967296) AND artifact.xmin::text::bigint<>(txid_current()%4294967296)
   AND consumed.xmin::text::bigint<>(txid_current()%4294967296) AND settlement.xmin::text::bigint<>(txid_current()%4294967296))
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
    WHERE failed.pack_task_id=requested.pack_task_id AND failed.operation_key=attempt_key||'.failure'))
  THEN
   IF NOT known_ancestor THEN RETURN NULL; END IF;
   IF NOT bridge_head THEN
   SELECT artifact.* INTO head_artifact FROM tutor_item_supply_private_generation_artifacts artifact
    JOIN tutor_item_supply_private_persistent_pack_journal done ON done.pack_task_id=requested.pack_task_id
     AND done.operation_key=attempt_key||'.author.result' AND artifact.id=(done.payload_json->>'receipt_id')::uuid;
   END IF;
   -- Durable terminal quality is DATA, not a restored live work capability.
   -- Bind the original full validation/blind/six-role review to THIS head artifact/spec/ref.
   SELECT review.* INTO peer FROM tutor_item_supply_private_native_quality_evidence review
    JOIN tutor_item_supply_private_native_quality_evidence validation ON validation.kind='validation'
     AND (validation.user_id,validation.epoch,validation.scope_id,validation.pack_task_id,validation.slot_id,validation.root_id,validation.version_id,validation.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND validation.payload_json->>'state'='machine_verified'
     AND validation.payload_json->>'source_hash'=head_artifact.source_hash AND validation.payload_json->>'content_hash'=head_artifact.content_hash
     AND validation.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_native_quality_evidence blind ON blind.kind='blind'
     AND (blind.user_id,blind.epoch,blind.scope_id,blind.pack_task_id,blind.slot_id,blind.root_id,blind.version_id,blind.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND blind.payload_json=review.payload_json->'bundle'->'blind_solve' AND blind.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_persistent_pack_journal review_done ON review_done.pack_task_id=review.pack_task_id
     AND review_done.user_id=review.user_id AND review_done.epoch=review.epoch AND review_done.scope_id=review.scope_id
     AND review_done.record_kind='private_status' AND review_done.payload_json->>'schema_version'='private_native_stage_v1'
     AND review_done.payload_json->>'stage'='review' AND review_done.payload_json->>'status'='committed'
     AND review_done.payload_json->>'slot_id'=review.slot_id::text AND review_done.payload_json->>'job_id'=review.job_id::text
     AND review_done.payload_json->>'receipt_id'=review.id::text AND review_done.xmin::text::bigint<>(txid_current()%4294967296)
    WHERE review.kind='review' AND review.user_id=requested.user_id AND review.epoch=requested.epoch AND review.scope_id=requested.scope_id
    AND review.pack_task_id=requested.pack_task_id AND review.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
    AND review.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND review.version_id=head_artifact.version_id
    AND review.payload_json->>'schema_version'='private_native_review_v1' AND review.payload_json->>'artifact_id'=head_artifact.id::text
    AND review.payload_json->'ref'=binding_row.payload_json->'ref'
    AND review.payload_json->'spec'->'public_template'=head_artifact.request_json->'public_template'
    AND review.payload_json->'spec'->'blueprint'=head_artifact.request_json->'blueprint'
    AND review.payload_json->'bundle'->>'state'='completed' AND review.payload_json->'bundle'->>'mode'='peer_blind'
    AND review.payload_json->'bundle'->'binding'->>'version_key'=head_artifact.version_id::text
    AND review.payload_json->'bundle'->'binding'->>'source_hash'=head_artifact.source_hash
    AND review.payload_json->'bundle'->'binding'->>'content_hash'=head_artifact.content_hash
    AND jsonb_array_length(review.payload_json->'bundle'->'reports')=6
    AND (SELECT array_agg(report->>'role' ORDER BY report->>'role') FROM jsonb_array_elements(review.payload_json->'bundle'->'reports') report)
     =ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
    AND review.checked_at<review.valid_until AND review.created_at<review.valid_until
    AND review.xmin::text::bigint<>(txid_current()%4294967296);
   IF peer.id IS NOT NULL THEN
    -- Original timeless receiver verifies committed exact original7 preparation,
    -- validation, reservation, settlement and review policy/spec/artifact binding.
    PERFORM item_supply_internal.assert_private_native_review_stage(peer);
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications publication
     JOIN tutor_item_supply_private_native_quality_evidence quality ON quality.id=publication.quality_id AND quality.kind='admission'
      AND (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)=
          (publication.user_id,publication.epoch,publication.scope_id,publication.pack_task_id,publication.slot_id,publication.root_id,publication.version_id)
      AND quality.payload_json->>'schema_version'='private_native_quality_v1'
      AND quality.payload_json->>'receipt_id'=quality.id::text AND quality.payload_json->>'version_id'=head_artifact.version_id::text
      AND quality.payload_json->>'generation_artifact_id'=head_artifact.id::text AND quality.payload_json->>'review_receipt_id'=peer.id::text
      AND quality.payload_json->'ref'=peer.payload_json->'ref' AND quality.payload_json->'spec'=peer.payload_json->'spec'
      AND quality.payload_json->'bundle'=peer.payload_json->'bundle' AND quality.payload_json->'source'=head_artifact.source_json
      AND quality.payload_json->'request'=head_artifact.request_json AND quality.payload_json->'source_receipts'=head_artifact.receipt_json->'sources'
      AND quality.payload_json->'evaluation'->>'disposition'='eligible_internal' AND quality.payload_json->'evaluation'->'publication_enabled'='false'::jsonb
      AND quality.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_validation ON admitted_validation.id=(quality.payload_json->>'validation_receipt_id')::uuid
      AND admitted_validation.kind='validation' AND admitted_validation.payload_json=quality.payload_json->'validation'
      AND (admitted_validation.user_id,admitted_validation.epoch,admitted_validation.scope_id,admitted_validation.pack_task_id,admitted_validation.slot_id,admitted_validation.root_id,admitted_validation.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_validation.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_blind ON admitted_blind.id=(quality.payload_json->>'blind_receipt_id')::uuid
      AND admitted_blind.kind='blind' AND admitted_blind.payload_json=peer.payload_json->'bundle'->'blind_solve'
      AND (admitted_blind.user_id,admitted_blind.epoch,admitted_blind.scope_id,admitted_blind.pack_task_id,admitted_blind.slot_id,admitted_blind.root_id,admitted_blind.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_blind.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_versions version ON version.id=publication.version_id AND version.user_id=publication.user_id AND version.epoch=publication.epoch
      AND version.public_json=head_artifact.source_json->'public' AND version.private_json=head_artifact.source_json->'private'
     JOIN tutor_exercise_versions exercise ON exercise.id=publication.exercise_version_id AND exercise.source_kind='registered_author'
      AND exercise.content_hash=publication.payload_json->>'exercise_content_hash'
      AND exercise.exercise_key=head_artifact.source_json->'public'->>'item_key' AND exercise.version=head_artifact.source_json->'public'->>'version'
     JOIN tutor_exercise_private_rubrics rubric ON rubric.exercise_version_id=exercise.id AND rubric.rubric_hash=publication.payload_json->>'rubric_hash'
     WHERE publication.pack_task_id=requested.pack_task_id AND publication.user_id=requested.user_id AND publication.epoch=requested.epoch
     AND publication.scope_id=requested.scope_id AND publication.slot_id=peer.slot_id AND publication.root_id=peer.root_id
     AND publication.version_id=head_artifact.version_id AND publication.state='published'
     AND publication.payload_json->>'schema_version'='private_native_publication_v1'
     AND publication.payload_json->>'publication_id'=publication.id::text AND publication.payload_json->>'quality_id'=quality.id::text
     AND publication.payload_json->>'quality_hash'=quality.payload_hash AND publication.payload_json->'ref'=quality.payload_json->'ref'
     AND publication.payload_json->>'source_hash'=item_supply_internal.snapshot_hash(quality.payload_json->'source')
     AND publication.payload_json->>'content_hash'=peer.payload_json->'bundle'->'binding'->>'content_hash'
     AND publication.payload_json->>'item_handle'=version.handle AND publication.content_json->>'item_handle'=version.handle
     AND publication.xmin::text::bigint<>(txid_current()%4294967296)
     AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications successor
      WHERE successor.version_id=publication.version_id AND successor.user_id=publication.user_id AND successor.epoch=publication.epoch
      AND successor.state_version>publication.state_version)) THEN RETURN 'published'; END IF;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') report
     WHERE report->>'verdict'<>'approved' OR EXISTS(SELECT 1 FROM jsonb_array_elements(report->'findings') finding
      WHERE finding->>'blocking'='true' OR finding->>'severity' IN('major','critical')
      OR finding->>'safe_code' IN('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit')))
    THEN RETURN 'review_failed'; END IF;
   END IF;
   RETURN 'artifact';
  END IF;
  SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.failure';
  IF failure_row.id IS NULL AND binding_row.id='af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid THEN
   SELECT j.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal j
    WHERE j.pack_task_id=requested.pack_task_id AND j.operation_key='private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'
    AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1'
    AND j.payload_json->>'binding_id'=binding_row.id::text;
  END IF;
  IF failure_row.id IS NULL THEN RETURN NULL; END IF;
  failure_row:=item_supply_internal.private_initial_author_continuation_predecessor(failure_row.id,requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 END LOOP;
END;
$newterm562$;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.private_initial_author_continuation_terminal(uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_initial_author_continuation_terminal' OR actual.prosecdef IS DISTINCT FROM true OR actual.prokind<>'f'
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.prorettype IS DISTINCT FROM to_regtype('pg_catalog.text') OR actual.proargnames IS DISTINCT FROM ARRAY['p_started']::text[]
   OR actual.pronargs IS DISTINCT FROM COALESCE(cardinality(ARRAY['p_started']::text[]),0)
   OR actual.proretset IS DISTINCT FROM false OR actual.provolatile<>'v' OR actual.proisstrict OR actual.proleakproof OR actual.proparallel<>'u'
   OR actual.procost<>100 OR actual.prorows IS DISTINCT FROM (CASE WHEN false THEN 1000::real ELSE 0::real END)
   OR actual.prosupport<>0 OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL OR actual.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 THEN RAISE check_violation USING MESSAGE='562 original term receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body THEN RAISE check_violation USING MESSAGE='562 original term receiver body changed'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='562 original term receiver framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc') OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='562 term receiver metadata/OID/owner/ACL/body changed'; END IF;
END;
$patchterm562$;

DO $patchready562$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldready562$
DECLARE spec record; actual record; names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' THEN RETURN false; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_generation_durability_attempt(uuid)','private_generation_durability_attempt(p_preparation uuid)','jsonb',$expected560$
DECLARE task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 binding public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; approval public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; claim public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 started public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; consumed public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE; reservation public.tutor_item_supply_private_reservations%ROWTYPE;
 settlement public.tutor_item_supply_private_runtime_settlements%ROWTYPE; profile public.tutor_item_supply_parameter_profiles%ROWTYPE;
 ref jsonb; lease_json jsonb; request jsonb; attempt_key text; amounts jsonb; stamp timestamptz;
BEGIN
 -- One original same-user lock domain shared by capture and the fixed technical gap.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='560 current original namespace/active plan required'; END IF;
 SELECT j.* INTO task_row FROM tutor_item_supply_private_persistent_pack_journal j
  WHERE j.id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.pack_task_id=j.id AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='task' FOR SHARE;
 IF task_row.id IS NULL OR task_row.payload_json->>'enhancement' IS DISTINCT FROM 'prefer_private'
  OR task_row.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
 THEN RAISE check_violation USING MESSAGE='560 original PRIVATE task required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_budget_roots r WHERE r.id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND r.user_id=task_row.user_id
  AND r.epoch=task_row.epoch AND r.scope_id=task_row.scope_id FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='560 original canonical root required'; END IF;
 SELECT j.* INTO aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_preparation
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='private_attachment' AND j.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND j.payload_json->'request'->>'schema_version'='private_native_initial_author_v1' FOR UPDATE;
 IF aux.id IS NULL THEN RAISE check_violation USING MESSAGE='560 original initial-author preparation required'; END IF;
 ref:=aux.payload_json->'request'->'ref'; request:=aux.payload_json->'request'->'request';
 SELECT j.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
  AND j.user_id=task_row.user_id AND j.epoch=1 AND j.scope_id=task_row.scope_id AND j.record_kind='phase'
  AND j.operation_key='private.phase.'||(aux.payload_json->>'job_id') AND j.payload_json->>'schema_version'='private_native_phase_v1';
 lease_json:=phase.payload_json->'lease';
 IF phase.id IS NULL OR phase.payload_json->'ref' IS DISTINCT FROM ref
  OR (ref->>'pack_task_id',ref->>'user_id',ref->>'epoch',ref->>'scope_id',ref->>'root_id',ref->>'mapping_receipt_id') IS DISTINCT FROM
   (task_row.id::text,task_row.user_id::text,'1',task_row.scope_id::text,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9','d8e34e01-3514-41a3-9bbd-55ee3e627134')
  OR ref->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR request->>'candidate_id' IS DISTINCT FROM aux.id::text OR request->>'version' IS DISTINCT FROM 'v1'
  OR request->>'item_key' IS DISTINCT FROM 'private-native.'||replace(ref->>'business_item_id','-','')
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(task_row.payload_json->'slots') s
   WHERE s->>'slot_id'=ref->>'slot_id' AND s->>'logical_item_id'=ref->>'business_item_id')
 THEN RAISE check_violation USING MESSAGE='560 exact original committed initial preparation/ref/request required'; END IF;
 SELECT j.* INTO binding FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
  AND j.payload_json->>'schema_version' IN('private_initial_author_recovery_binding_v1','private_initial_author_continuation_binding_v1')
  AND j.user_id=task_row.user_id AND j.epoch=task_row.epoch AND j.scope_id=task_row.scope_id
  AND j.payload_json->>'preparation_id'=aux.id::text AND j.payload_json->>'candidate_id'=aux.id::text FOR UPDATE;
 IF binding.id IS NOT NULL THEN
  SELECT j.* INTO approval FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(binding.payload_json->>'approval_id')::uuid FOR UPDATE;
  SELECT j.* INTO claim FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(binding.payload_json->>'claim_id')::uuid FOR SHARE;
  attempt_key:=left(binding.operation_key,length(binding.operation_key)-length('.binding'));
  IF binding.operation_key IS DISTINCT FROM attempt_key||'.binding' OR approval.operation_key IS DISTINCT FROM attempt_key||'.approval'
   OR claim.operation_key IS DISTINCT FROM attempt_key||'.claim'
   OR (approval.pack_task_id,approval.user_id,approval.epoch,approval.scope_id) IS DISTINCT FROM (task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
   OR (claim.pack_task_id,claim.user_id,claim.epoch,claim.scope_id) IS DISTINCT FROM (task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
   OR binding.payload_json->'ref' IS DISTINCT FROM ref OR binding.payload_json->'request' IS DISTINCT FROM request
   OR binding.payload_json->'lease' IS DISTINCT FROM lease_json
   OR binding.payload_json->>'reservation_id' IS DISTINCT FROM aux.payload_json->>'reservation_id'
   OR claim.payload_json->>'approval_id' IS DISTINCT FROM approval.id::text
   OR claim.payload_json->>'job_id' IS DISTINCT FROM aux.payload_json->>'job_id'
  THEN RAISE check_violation USING MESSAGE='560 exact original approval/claim/binding required'; END IF;
  IF binding.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1' THEN
   PERFORM item_supply_internal.private_initial_author_continuation_approval(approval.id);
  ELSIF attempt_key IS DISTINCT FROM 'p7.private.initial-author.recovery.20261015.once1' THEN
   RAISE check_violation USING MESSAGE='560 closed original recovery namespace required';
  END IF;
  SELECT j.* INTO consumed FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
   AND j.user_id=task_row.user_id AND j.epoch=task_row.epoch AND j.scope_id=task_row.scope_id AND j.record_kind='private_status'
   AND j.payload_json->>'schema_version' IN('private_initial_author_recovery_consumed_v1','private_initial_author_continuation_consumed_v1')
   AND j.operation_key=attempt_key||'.consumed' AND j.payload_json->>'binding_id'=binding.id::text;
  attempt_key:=attempt_key||'.author';
 ELSE
  attempt_key:='private.stage.'||replace(ref->>'business_item_id','-','')||'.author.'||item_supply_internal.snapshot_hash('"v1"'::jsonb);
 END IF;
 SELECT j.* INTO started FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
  AND j.user_id=task_row.user_id AND j.epoch=task_row.epoch AND j.scope_id=task_row.scope_id
  AND j.operation_key=attempt_key||'.started' AND j.record_kind='private_status'
  AND j.payload_json->>'schema_version'='private_native_stage_v1' AND j.payload_json->>'stage'='author'
  AND j.payload_json->>'status'='started' AND j.payload_json->'receipt_id'='null'::jsonb
  AND j.payload_json->>'slot_id'=ref->>'slot_id' AND j.payload_json->>'job_id'=aux.payload_json->>'job_id'
  AND j.payload_json->>'subject_hash'=item_supply_internal.snapshot_hash('"v1"'::jsonb);
 IF started.id IS NULL OR (binding.id IS NOT NULL AND (consumed.id IS NULL
  OR consumed.payload_json->>'started_id' IS DISTINCT FROM started.id::text
  OR consumed.payload_json->>'candidate_id' IS DISTINCT FROM aux.id::text
  OR consumed.payload_json->>'job_id' IS DISTINCT FROM aux.payload_json->>'job_id'
  OR consumed.payload_json->>'reservation_id' IS DISTINCT FROM aux.payload_json->>'reservation_id'))
 THEN RAISE check_violation USING MESSAGE='560 original dispatched once/consume required'; END IF;
 -- No absence decision occurs before this original control lock.
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=(aux.payload_json->>'job_id')::uuid
  AND c.user_id=task_row.user_id AND c.epoch=1 AND c.scope_id=task_row.scope_id FOR UPDATE;
 SELECT p.* INTO profile FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id;
 SELECT r.* INTO reservation FROM tutor_item_supply_private_reservations r WHERE r.id=(aux.payload_json->>'reservation_id')::uuid
  AND r.user_id=task_row.user_id AND r.epoch=1 AND r.scope_id=task_row.scope_id AND r.job_id=ctrl.job_id AND r.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' FOR SHARE;
 SELECT s.* INTO settlement FROM tutor_item_supply_private_runtime_settlements s WHERE s.reservation_id=reservation.id
  AND s.user_id=task_row.user_id AND s.epoch=1 AND s.scope_id=task_row.scope_id
  AND s.settlement_key='generation.'||replace(aux.id::text,'-','') AND s.sequence=1 FOR SHARE;
 IF ctrl.id IS NULL OR profile.id IS NULL OR reservation.id IS NULL OR settlement.id IS NULL
  OR ctrl.lease_generation IS DISTINCT FROM (lease_json->>'generation')::integer
  OR reservation.lease_generation IS DISTINCT FROM ctrl.lease_generation
  OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR ctrl.profile_snapshot_json->'profile' IS DISTINCT FROM lease_json->'profile'
  OR ctrl.profile_snapshot_json->'retry_policy' IS DISTINCT FROM lease_json->'retry_policy'
  OR request->'profile' IS DISTINCT FROM lease_json->'profile'
  OR profile.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
 THEN RAISE check_violation USING MESSAGE='560 historical prepared control/profile/reservation/settlement identity required'; END IF;
 SELECT jsonb_object_agg(a.resource_kind,a.actual_amount) INTO amounts FROM tutor_item_supply_private_runtime_settlement_amounts a WHERE a.settlement_id=settlement.id;
 stamp:=clock_timestamp();
 IF p_preparation='eeebd057-3e04-4a61-8979-201446e20221' THEN
  IF binding.id IS DISTINCT FROM 'af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid OR consumed.id IS DISTINCT FROM 'b4866afd-d59f-4aef-bec3-1b1279fbaa14'::uuid
   OR ref->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   OR ref->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
   OR approval.payload_json->>'predecessor_failure_id' IS DISTINCT FROM 'df0a6e8c-287a-4814-98f1-5deeb59347a3'
   OR ctrl.job_id IS DISTINCT FROM '80f8f576-166e-48ea-aaa7-f78809da38b8'::uuid
   OR settlement.id IS DISTINCT FROM '55e11576-7b38-4f04-bee5-90ff5e6df51d'::uuid
   OR reservation.id IS DISTINCT FROM '4e0ec381-f9e4-4c11-b391-cedbc2480e04'::uuid
   OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.breaker_open OR ctrl.state IS DISTINCT FROM 'leased' OR ctrl.state_version<>2
   OR (lease_json->>'expires_at')::timestamptz IS DISTINCT FROM ctrl.lease_expires_at
   OR ctrl.lease_expires_at IS DISTINCT FROM '2026-10-16 03:05:23.278164+08'::timestamptz
   OR ctrl.parent_deadline IS DISTINCT FROM '2026-10-16 03:45:22.951952+08'::timestamptz
   OR ctrl.lease_expires_at>stamp OR settlement.usage_state IS DISTINCT FROM 'known' OR settlement.cost_amount IS NOT NULL
   OR settlement.receipt_hash IS DISTINCT FROM '8c7ae3625382be3e25a2d4980e09ee3259b03463ba63b642d76cc85847dc468f'
   OR amounts IS DISTINCT FROM '{"requests":1,"candidates":1,"input_tokens":12916,"output_tokens":2082,"execution_seconds":0,"fetches":0,"revision_rounds":0,"investigation_rounds":0}'::jsonb
  THEN RAISE check_violation USING MESSAGE='560 fixed naturally expired known-paid C14 identity required'; END IF;
 END IF;
 RETURN jsonb_build_object('task',to_jsonb(task_row),'aux',to_jsonb(aux),'phase',to_jsonb(phase),'binding',CASE WHEN binding.id IS NULL THEN jsonb_build_object('id',NULL) ELSE to_jsonb(binding) END,
  'approval',to_jsonb(approval),'started',to_jsonb(started),'consumed',CASE WHEN consumed.id IS NULL THEN jsonb_build_object('id',NULL) ELSE to_jsonb(consumed) END,'control',to_jsonb(ctrl),
  'reservation',to_jsonb(reservation),'settlement',to_jsonb(settlement),'amounts',amounts,
  'producer_binding',jsonb_build_array(profile.profile_json->'profile_key'->>'provider',profile.profile_json->'profile_key'->>'model_version'));
END;
$expected560$),
 ('private_initial_author_persistence_gap_issue(uuid,uuid,bigint,uuid,uuid)','private_initial_author_persistence_gap_issue(p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid,p_binding uuid)','uuid',$expected560$
DECLARE d jsonb; identity uuid:=gen_random_uuid(); stamp timestamptz;
BEGIN
 IF p_binding IS DISTINCT FROM 'af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid THEN RAISE check_violation USING MESSAGE='560 fixed C14 gap binding required'; END IF;
 IF (p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid)
 THEN RAISE check_violation USING MESSAGE='560 exact gap issuance namespace required'; END IF;
 d:=item_supply_internal.private_generation_durability_attempt('eeebd057-3e04-4a61-8979-201446e20221');
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=p_task
   AND j.operation_key IN('private.generation.output.eeebd0573e044a618979201446e20221','private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'))
 THEN RAISE check_violation USING MESSAGE='560 durable product/output or prior technical gap already exists'; END IF;
 stamp:=clock_timestamp();
 IF (d->'control'->>'lease_expires_at')::timestamptz>stamp THEN RAISE check_violation USING MESSAGE='560 C14 lease not naturally expired'; END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,p_task,p_user,p_epoch,p_scope,'private_status','private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6',d->'task'->>'intent_hash',
  jsonb_build_object('schema_version','private_initial_author_persistence_gap_v1',
  'binding_id','af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6','preparation_id','eeebd057-3e04-4a61-8979-201446e20221','job_id',d->'control'->>'job_id',
  'started_id',d->'started'->>'id','consumed_id',d->'consumed'->>'id','reservation_id',d->'reservation'->>'id',
  'settlement_id',d->'settlement'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
  'provider_receipt_hash',d->'settlement'->>'receipt_hash','disposition','expired_consumed_no_durable_output',
  'issued_top_xid',pg_current_xact_id()::text,'issued_at',stamp));
 RETURN identity;
END;
$expected560$),
 ('private_initial_author_persistence_gap_committed(uuid,uuid,uuid,bigint,uuid)','private_initial_author_persistence_gap_committed(p_receipt uuid,p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)','public.tutor_item_supply_private_persistent_pack_journal',$expected560$
DECLARE d jsonb; gap public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; body jsonb;
BEGIN
 IF (p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid)
 THEN RAISE check_violation USING MESSAGE='560 exact gap namespace required'; END IF;
 d:=item_supply_internal.private_generation_durability_attempt('eeebd057-3e04-4a61-8979-201446e20221');
 SELECT j.* INTO gap FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_receipt
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(p_task,p_user,p_epoch,p_scope) AND j.record_kind='private_status'
  AND j.operation_key='private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6' FOR SHARE;
 body:=gap.payload_json;
 IF gap.id IS NULL OR body IS DISTINCT FROM jsonb_build_object('schema_version','private_initial_author_persistence_gap_v1',
  'binding_id','af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6','preparation_id','eeebd057-3e04-4a61-8979-201446e20221','job_id',d->'control'->>'job_id',
  'started_id',d->'started'->>'id','consumed_id',d->'consumed'->>'id','reservation_id',d->'reservation'->>'id',
  'settlement_id',d->'settlement'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
  'provider_receipt_hash',d->'settlement'->>'receipt_hash','disposition','expired_consumed_no_durable_output',
  'issued_top_xid',body->>'issued_top_xid','issued_at',body->'issued_at')
  OR jsonb_typeof(body->'issued_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'issued_top_xid')::xid8::text IS DISTINCT FROM body->>'issued_top_xid'
  OR (body->>'issued_at')::timestamptz IS NULL OR (body->>'issued_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='560 exact technical gap record required'; END IF;
 IF body->>'issued_top_xid'=pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='560 technical gap requires a different committed TOP';
 END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=p_task
   AND j.operation_key='private.generation.output.eeebd0573e044a618979201446e20221')
 THEN RAISE check_violation USING MESSAGE='560 historical C14 paid/no-output facts changed'; END IF;
 RETURN gap;
END;
$expected560$),
 ('private_generation_output_capture(uuid,jsonb)','private_generation_output_capture(p_preparation uuid,p_capture jsonb)','uuid',$expected560$
DECLARE d jsonb; existing public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; identity uuid:=gen_random_uuid(); stamp timestamptz; output_key text;
BEGIN
 d:=item_supply_internal.private_generation_durability_attempt(p_preparation);
 IF p_preparation='eeebd057-3e04-4a61-8979-201446e20221' OR d->'control'->>'job_id' IN('487b12c4-f98a-41c9-a21b-abb9243a28dd','6691f9a2-073a-4fbc-8783-09d6ef0ca8d5')
 THEN RAISE check_violation USING MESSAGE='560 historical author output cannot be backfilled'; END IF;
 output_key:='private.generation.output.'||replace(p_preparation::text,'-','');
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' AND j.payload_json->>'preparation_id'=p_preparation::text)
 THEN RAISE check_violation USING MESSAGE='560 technical gap forbids output capture'; END IF;
 SELECT j.* INTO existing FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.operation_key=output_key FOR SHARE;
 IF existing.id IS NOT NULL THEN
  IF existing.payload_json->>'schema_version' IS DISTINCT FROM 'private_generation_output_v1' OR existing.payload_json->'capture' IS DISTINCT FROM p_capture
  THEN RAISE check_violation USING MESSAGE='560 original sealed output/context conflict'; END IF;
  RETURN existing.id;
 END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid) THEN RAISE check_violation USING MESSAGE='560 capture must precede artifact/checkpoint/quality'; END IF;
 stamp:=clock_timestamp();
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,'6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','private_status',output_key,d->'task'->>'intent_hash',
  jsonb_build_object('schema_version','private_generation_output_v1','preparation_id',p_preparation,'binding_id',d->'binding'->'id',
   'started_id',d->'started'->'id','consumed_id',d->'consumed'->'id','settlement_id',d->'settlement'->'id',
   'request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
   'capture',p_capture,'captured_top_xid',pg_current_xact_id()::text,'captured_at',stamp));
 RETURN identity;
END;
$expected560$),
 ('private_generation_output_committed(uuid,jsonb)','private_generation_output_committed(p_preparation uuid,p_capture jsonb)','uuid',$expected560$
DECLARE d jsonb; output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; body jsonb;
BEGIN
 d:=item_supply_internal.private_generation_durability_attempt(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='private_status'
  AND j.operation_key='private.generation.output.'||replace(p_preparation::text,'-','') FOR SHARE;
 body:=output_row.payload_json;
 IF output_row.id IS NULL OR body->>'schema_version' IS DISTINCT FROM 'private_generation_output_v1'
  OR body->>'preparation_id' IS DISTINCT FROM p_preparation::text OR body->'capture' IS DISTINCT FROM p_capture
  OR body->'binding_id' IS DISTINCT FROM d->'binding'->'id' OR body->'started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'consumed_id' IS DISTINCT FROM d->'consumed'->'id' OR body->'settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request')
  OR jsonb_typeof(body->'captured_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'captured_top_xid')::xid8::text IS DISTINCT FROM body->>'captured_top_xid'
  OR (body->>'captured_at')::timestamptz IS NULL OR (body->>'captured_at')::timestamptz>clock_timestamp()
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' AND j.payload_json->>'preparation_id'=p_preparation::text)
 THEN RAISE check_violation USING MESSAGE='560 exact original sealed output record required'; END IF;
 IF body->>'captured_top_xid'=pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='560 output requires a different committed TOP';
 END IF;
 RETURN output_row.id;
END;
$expected560$),
 ('enforce_private_generation_durability_insert()','enforce_private_generation_durability_insert()','trigger',$expected560$
DECLARE body jsonb:=NEW.payload_json; protocol text:=body->>'schema_version'; d jsonb; capture jsonb; ctx jsonb;
 result jsonb; source jsonb; receipt jsonb; provider jsonb; request jsonb; expected_content text; stamp timestamptz; known boolean;
BEGIN
 IF COALESCE(protocol NOT IN('private_generation_output_v1','private_initial_author_persistence_gap_v1'),true)
  AND NEW.operation_key NOT LIKE 'private.generation.output.%' AND NEW.operation_key NOT LIKE 'private.generation.gap.%' THEN RETURN NEW; END IF;
 IF protocol NOT IN('private_generation_output_v1','private_initial_author_persistence_gap_v1') OR protocol IS NULL
 THEN RAISE check_violation USING MESSAGE='560 closed durability journal schema required'; END IF;
 d:=item_supply_internal.private_generation_durability_attempt((body->>'preparation_id')::uuid);
 IF (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.record_kind,NEW.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status',d->'task'->>'intent_hash')
 THEN RAISE check_violation USING MESSAGE='560 exact original durability namespace required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid) THEN RAISE check_violation USING MESSAGE='560 durable product already exists before journal append'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=NEW.pack_task_id
  AND (j.operation_key=NEW.operation_key OR (j.payload_json->>'preparation_id'=body->>'preparation_id'
   AND j.payload_json->>'schema_version' IN('private_generation_output_v1','private_initial_author_persistence_gap_v1'))))
 THEN RAISE check_violation USING MESSAGE='560 output/gap exclusive immutable attempt already recorded'; END IF;
 stamp:=clock_timestamp();
 IF protocol='private_initial_author_persistence_gap_v1' THEN
  IF NEW.operation_key IS DISTINCT FROM 'private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'
   OR body->>'preparation_id' IS DISTINCT FROM 'eeebd057-3e04-4a61-8979-201446e20221'
   OR body IS DISTINCT FROM jsonb_build_object('schema_version','private_initial_author_persistence_gap_v1',
  'binding_id','af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6','preparation_id','eeebd057-3e04-4a61-8979-201446e20221','job_id',d->'control'->>'job_id',
  'started_id',d->'started'->>'id','consumed_id',d->'consumed'->>'id','reservation_id',d->'reservation'->>'id',
  'settlement_id',d->'settlement'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
  'provider_receipt_hash',d->'settlement'->>'receipt_hash','disposition','expired_consumed_no_durable_output',
  'issued_top_xid',pg_current_xact_id()::text,'issued_at',body->'issued_at')
   OR jsonb_typeof(body->'issued_top_xid') IS DISTINCT FROM 'string'
   OR (body->>'issued_at')::timestamptz IS NULL OR (body->>'issued_at')::timestamptz>stamp
   OR (d->'control'->>'lease_expires_at')::timestamptz>stamp
  THEN RAISE check_violation USING MESSAGE='560 exact server-TOP naturally expired fixed technical gap required'; END IF;
  RETURN NEW;
 END IF;
 IF body->>'preparation_id'='eeebd057-3e04-4a61-8979-201446e20221' OR d->'control'->>'job_id' IN('487b12c4-f98a-41c9-a21b-abb9243a28dd','6691f9a2-073a-4fbc-8783-09d6ef0ca8d5')
 THEN RAISE check_violation USING MESSAGE='560 historical author output cannot be backfilled'; END IF;
 IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','preparation_id','binding_id','started_id','consumed_id','settlement_id','request_hash','capture','captured_top_xid','captured_at']) IS DISTINCT FROM true
  OR NEW.operation_key IS DISTINCT FROM 'private.generation.output.'||replace(body->>'preparation_id','-','')
  OR body->'binding_id' IS DISTINCT FROM d->'binding'->'id' OR body->'started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'consumed_id' IS DISTINCT FROM d->'consumed'->'id' OR body->'settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request')
  OR body->'captured_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)
  OR (body->>'captured_at')::timestamptz IS NULL OR (body->>'captured_at')::timestamptz>stamp
 THEN RAISE check_violation USING MESSAGE='560 exact original output refs/server TOP required'; END IF;
 capture:=body->'capture'; ctx:=capture->'context'; result:=capture->'result'; request:=ctx->'request';
 source:=result->'source'; receipt:=result->'receipt'; provider:=receipt->'provider';
 IF item_supply_internal.snapshot_keys(capture,ARRAY['schema_version','context','result']) IS DISTINCT FROM true
  OR capture->>'schema_version' IS DISTINCT FROM 'private_generation_capture_v1'
  OR item_supply_internal.snapshot_keys(ctx,ARRAY['ref','lease','scope_id','request','reservation_id','sources','attempt_bound','mode','producer_binding']) IS DISTINCT FROM true
  OR ctx->'ref' IS DISTINCT FROM d->'aux'->'payload_json'->'request'->'ref'
  OR ctx->'lease' IS DISTINCT FROM d->'phase'->'payload_json'->'lease'
  OR ctx->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR request IS DISTINCT FROM d->'aux'->'payload_json'->'request'->'request'
  OR ctx->'reservation_id' IS DISTINCT FROM d->'reservation'->'id'
  OR ctx->'attempt_bound' IS DISTINCT FROM '1'::jsonb OR ctx->>'mode' IS DISTINCT FROM 'live'
  OR ctx->'producer_binding' IS DISTINCT FROM d->'producer_binding'
  OR item_supply_internal.snapshot_keys(result,ARRAY['state','source','receipt','safe_reason']) IS DISTINCT FROM true
  OR result->>'state' IS DISTINCT FROM 'staged' OR result->>'safe_reason' IS DISTINCT FROM 'staged'
  OR item_supply_internal.snapshot_keys(source,ARRAY['schema_version','blueprint','public','private']) IS DISTINCT FROM true
  OR source->>'schema_version' IS DISTINCT FROM 'learning_item_source_v1'
  OR source->'blueprint' IS DISTINCT FROM request->'blueprint'
  OR (source->'public'->>'item_key',source->'public'->>'version') IS DISTINCT FROM (request->>'item_key',request->>'version')
  OR (source->'private'->>'item_key',source->'private'->>'version',source->'private'->>'kind') IS DISTINCT FROM
     (source->'public'->>'item_key',source->'public'->>'version',source->'public'->>'kind')
  OR item_supply_internal.snapshot_keys(receipt,ARRAY['schema_version','candidate_id','scope_hash','source_hash','content_hash','provider','sources']) IS DISTINCT FROM true
  OR receipt->>'schema_version' IS DISTINCT FROM 'item_generation_receipt_v2'
  OR receipt->>'candidate_id' IS DISTINCT FROM body->>'preparation_id' OR receipt->>'scope_hash' IS DISTINCT FROM request->>'scope_hash'
  OR receipt->'sources' IS DISTINCT FROM ctx->'sources'
  OR (d->'binding'->>'id' IS NOT NULL AND ctx->'sources' IS DISTINCT FROM d->'binding'->'payload_json'->'sources')
  OR item_supply_internal.snapshot_keys(provider,ARRAY['provider','provider_version','configured_model','model','prompt_version','role','run_id','request_attempt_bound','actual_requests','usage','mode']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(provider->'usage',ARRAY['state','input_tokens','cached_input_tokens','output_tokens','total_tokens','reasoning_tokens','cost']) IS DISTINCT FROM true
  OR provider->>'mode' IS DISTINCT FROM 'provider' OR provider->>'role' IS DISTINCT FROM 'item_author'
  OR provider->'request_attempt_bound' IS DISTINCT FROM '1'::jsonb
  OR (provider->'actual_requests'<>'null'::jsonb AND provider->'actual_requests' IS DISTINCT FROM '1'::jsonb)
  OR jsonb_build_array(provider->>'provider',provider->>'configured_model') IS DISTINCT FROM ctx->'producer_binding'
  OR provider->>'model' IS DISTINCT FROM provider->>'configured_model'
 THEN RAISE check_violation USING MESSAGE='560 full original sealed context/staged source/receipt identity required'; END IF;
 expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object('item_key',source->'public'->>'item_key','version',source->'public'->>'version',
  'blueprint_hash',item_supply_internal.snapshot_hash(source->'blueprint'),'public_hash',item_supply_internal.snapshot_hash(source->'public'),
  'private_hash',item_supply_internal.snapshot_hash(source->'private')));
 IF receipt->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(source) OR receipt->>'content_hash' IS DISTINCT FROM expected_content
  OR jsonb_typeof(ctx->'sources') IS DISTINCT FROM 'array' OR jsonb_array_length(ctx->'sources') NOT BETWEEN 1 AND 12
  OR jsonb_array_length(ctx->'sources') IS DISTINCT FROM jsonb_array_length(request->'materials')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(ctx->'sources') WITH ORDINALITY s(value,n)
   JOIN jsonb_array_elements(request->'materials') WITH ORDINALITY m(value,n) ON m.n=s.n
   WHERE item_supply_internal.snapshot_keys(s.value,ARRAY['material_digest','binding_digest','corpus_version_id','active_generation','checked_at_iso','claim_receipt_hashes','mode']) IS DISTINCT FROM true
    OR s.value->>'mode' IS DISTINCT FROM 'current_authority'
    OR s.value->>'binding_digest' IS DISTINCT FROM m.value->'binding'->>'binding_digest'
    OR s.value->>'corpus_version_id' IS DISTINCT FROM m.value->'binding'->'evidence'->0->>'corpus_version_id'
    OR s.value->'active_generation' IS DISTINCT FROM m.value->'binding'->'evidence'->0->'active_generation'
    OR s.value->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('binding',m.value->'binding',
      'access_request',m.value->'access_request','exact_claims',m.value->'exact_claims',
      'excerpt_hash',encode(sha256(convert_to(m.value->>'excerpt','UTF8')),'hex'))))
 THEN RAISE check_violation USING MESSAGE='560 complete original source/content/material hashes required'; END IF;
 known:=provider->'usage'->>'state'='known' AND provider->>'actual_requests' IS NOT NULL
  AND provider->'usage'->>'input_tokens' IS NOT NULL AND provider->'usage'->>'output_tokens' IS NOT NULL;
 IF d->'settlement'->'cost_amount' IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='560 original null cost must be retained'; END IF;
 IF known THEN
  IF d->'settlement'->>'usage_state' IS DISTINCT FROM 'known' OR d->'settlement'->>'receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(provider)
   OR d->'amounts' IS DISTINCT FROM jsonb_build_object('requests',(provider->>'actual_requests')::bigint,'candidates',1,
    'input_tokens',(provider->'usage'->>'input_tokens')::bigint,'output_tokens',(provider->'usage'->>'output_tokens')::bigint,
    'execution_seconds',0,'fetches',0,'revision_rounds',0,'investigation_rounds',0)
  THEN RAISE check_violation USING MESSAGE='560 exact known original provider/settlement amounts required'; END IF;
 ELSE
  IF COALESCE(provider->'usage'->>'state' IN('known','unknown'),false) IS DISTINCT FROM true
   OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'unknown' OR d->'settlement'->'receipt_hash' IS DISTINCT FROM 'null'::jsonb
   OR d->'amounts' IS DISTINCT FROM 'null'::jsonb
  THEN RAISE check_violation USING MESSAGE='560 UNKNOWN/null original settlement must be retained'; END IF;
 END IF;
 -- Final DB clock, not a current grant for the expired author/source.
 IF (body->>'captured_at')::timestamptz>clock_timestamp() THEN RAISE check_violation USING MESSAGE='560 future capture timestamp'; END IF;
 RETURN NEW;
END;
$expected560$),
 ('enforce_private_generation_durability_artifact()','enforce_private_generation_durability_artifact()','trigger',$expected560$
DECLARE output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; output_id uuid; p_preparation uuid;
BEGIN
 IF NEW.mode IS DISTINCT FROM 'live' OR NEW.user_id IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid OR NEW.epoch<>1
  OR NEW.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid THEN RETURN NEW; END IF;
 -- Inherited/idempotent staging of an already existing exact generation is not a new author.
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE
  (a.user_id,a.epoch,a.scope_id,a.job_id,a.lease_generation,a.artifact_key,a.candidate_id,a.version_id,a.mode,a.source_hash,a.content_hash,a.request_json,a.source_json,a.receipt_json)=
  (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id,NEW.lease_generation,NEW.artifact_key,NEW.candidate_id,NEW.version_id,NEW.mode,NEW.source_hash,NEW.content_hash,NEW.request_json,NEW.source_json,NEW.receipt_json)) THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal phase WHERE phase.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND phase.user_id=NEW.user_id AND phase.epoch=NEW.epoch AND phase.scope_id=NEW.scope_id AND phase.record_kind='phase'
  AND phase.payload_json->>'schema_version'='private_native_phase_v1' AND phase.payload_json->>'job_id'=NEW.job_id::text
  AND phase.payload_json->'ref'->'parent_version_id'='null'::jsonb) THEN RETURN NEW; END IF;
 p_preparation:=(NEW.request_json->>'candidate_id')::uuid;
 -- Establish the common lock domain before inspecting output/gap rows.
 PERFORM item_supply_internal.private_generation_durability_attempt(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.operation_key='private.generation.output.'||replace(p_preparation::text,'-','');
 output_id:=item_supply_internal.private_generation_output_committed(p_preparation,output_row.payload_json->'capture');
 IF output_id IS NULL OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM NEW.request_json
  OR output_row.payload_json->'capture'->'context'->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
  OR output_row.payload_json->'capture'->'context'->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
  OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM NEW.source_json
  OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
 THEN RAISE check_violation USING MESSAGE='560 exact separately committed output required before original artifact'; END IF;
 RETURN NEW; -- Original559 current goal/source/control/content and all later guards remain.
END;
$expected560$),
 ('private_initial_author_continuation_predecessor(uuid,uuid,uuid,bigint,uuid)','private_initial_author_continuation_predecessor(p_receipt uuid,p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)','public.tutor_item_supply_private_persistent_pack_journal',$expected560$
DECLARE failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_receipt
  AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1') THEN
  RETURN item_supply_internal.private_initial_author_persistence_gap_committed(p_receipt,p_task,p_user,p_epoch,p_scope);
 END IF;
 PERFORM item_supply_internal.private_initial_author_recovery_anchor(p_task,p_user,p_epoch,p_scope);
 SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_receipt AND journal.pack_task_id=p_task AND journal.user_id=p_user AND journal.epoch=p_epoch AND journal.scope_id=p_scope
  AND journal.record_kind='private_status' AND journal.xmin::text::bigint<>(txid_current()%4294967296) FOR UPDATE;
 IF failure_row.id IS NULL THEN RAISE check_violation USING MESSAGE='558 prior-TOP genuine predecessor failure required'; END IF;
 IF p_receipt='df0a6e8c-287a-4814-98f1-5deeb59347a3' THEN
  IF item_supply_internal.private_initial_author_failure_committed(p_receipt,p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM true
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact WHERE artifact.job_id='6691f9a2-073a-4fbc-8783-09d6ef0ca8d5')
  THEN RAISE check_violation USING MESSAGE='558 original committed 555 failure required'; END IF;
 ELSE
  IF item_supply_internal.private_initial_author_continuation_failure_committed(p_receipt,p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='558 committed same-authorization failure lineage required'; END IF;
 END IF;
 RETURN failure_row;
END;
$expected560$),
 ('private_initial_author_continuation_terminal(uuid)','private_initial_author_continuation_terminal(p_started uuid)','text',$expected560$
DECLARE requested public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 head_artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 attempt_key text; known_ancestor boolean:=false;
BEGIN
 SELECT journal.* INTO requested FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_started AND journal.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND journal.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND journal.epoch=1 AND journal.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND journal.record_kind='private_status' AND journal.payload_json->>'schema_version'='private_native_stage_v1'
  AND journal.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND journal.payload_json->>'stage'='author'
  AND journal.payload_json->>'status'='started' AND journal.payload_json->'receipt_id'='null'::jsonb
  AND journal.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF requested.id IS NULL THEN RETURN NULL; END IF;
 failure_row:=item_supply_internal.private_initial_author_continuation_predecessor('df0a6e8c-287a-4814-98f1-5deeb59347a3',requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 known_ancestor:=requested.id='5ad70ab7-0441-456b-ae5e-156755a80911'
  OR (requested.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started' AND requested.id::text=failure_row.payload_json->>'started_id');
 LOOP
  -- Follow the sole deterministic successor, never timestamp ordering or arbitrary started rows.
  attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(failure_row.id::text,'-','');
  SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.approval'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF approval_row.id IS NULL THEN
   IF known_ancestor THEN
    IF failure_row.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' THEN RETURN 'technical_gap'; END IF;
    RETURN 'failure';
   ELSE RETURN NULL; END IF;
  END IF;
  approval_row:=item_supply_internal.private_initial_author_continuation_approval(approval_row.id);
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.binding'
   AND journal.payload_json->>'approval_id'=approval_row.id::text AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  SELECT journal.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.author.started'
   AND journal.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF binding_row.id IS NULL OR started_row.id IS NULL THEN RETURN NULL; END IF;
  known_ancestor:=known_ancestor OR requested.id=started_row.id;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done
   JOIN tutor_item_supply_private_persistent_pack_journal consumed ON consumed.pack_task_id=done.pack_task_id
    AND consumed.operation_key=attempt_key||'.consumed' AND consumed.payload_json->>'binding_id'=binding_row.id::text
    AND consumed.payload_json->>'started_id'=started_row.id::text
   JOIN tutor_item_supply_private_generation_artifacts artifact ON artifact.id=(done.payload_json->>'receipt_id')::uuid
    AND artifact.job_id=(binding_row.payload_json->'lease'->>'job_id')::uuid AND artifact.request_json=binding_row.payload_json->'request'
    AND artifact.lease_generation=1 AND artifact.mode='live'
   JOIN tutor_item_supply_private_candidates candidate ON candidate.id=artifact.candidate_id
    AND candidate.user_id=requested.user_id AND candidate.epoch=requested.epoch AND candidate.scope_id=requested.scope_id
    AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   JOIN tutor_item_supply_private_versions version ON version.id=artifact.version_id AND version.candidate_id=candidate.id AND version.version=1
   JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.reservation_id=(binding_row.payload_json->>'reservation_id')::uuid
    AND settlement.settlement_key='generation.'||replace(binding_row.payload_json->>'candidate_id','-','') AND settlement.sequence=1
   WHERE done.pack_task_id=requested.pack_task_id AND done.operation_key=attempt_key||'.author.result'
   AND done.payload_json->>'schema_version'='private_native_stage_v1' AND done.payload_json->>'stage'='author'
   AND done.payload_json->>'status'='committed' AND done.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND done.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   AND done.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
   AND consumed.payload_json->>'candidate_id'=binding_row.payload_json->>'candidate_id'
   AND consumed.payload_json->>'job_id'=artifact.job_id::text AND consumed.payload_json->>'reservation_id'=settlement.reservation_id::text
   AND done.xmin::text::bigint<>(txid_current()%4294967296) AND artifact.xmin::text::bigint<>(txid_current()%4294967296)
   AND consumed.xmin::text::bigint<>(txid_current()%4294967296) AND settlement.xmin::text::bigint<>(txid_current()%4294967296))
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
    WHERE failed.pack_task_id=requested.pack_task_id AND failed.operation_key=attempt_key||'.failure')
  THEN
   IF NOT known_ancestor THEN RETURN NULL; END IF;
   SELECT artifact.* INTO head_artifact FROM tutor_item_supply_private_generation_artifacts artifact
    JOIN tutor_item_supply_private_persistent_pack_journal done ON done.pack_task_id=requested.pack_task_id
     AND done.operation_key=attempt_key||'.author.result' AND artifact.id=(done.payload_json->>'receipt_id')::uuid;
   -- Durable terminal quality is DATA, not a restored live work capability.
   -- Bind the original full validation/blind/six-role review to THIS head artifact/spec/ref.
   SELECT review.* INTO peer FROM tutor_item_supply_private_native_quality_evidence review
    JOIN tutor_item_supply_private_native_quality_evidence validation ON validation.kind='validation'
     AND (validation.user_id,validation.epoch,validation.scope_id,validation.pack_task_id,validation.slot_id,validation.root_id,validation.version_id,validation.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND validation.payload_json->>'state'='machine_verified'
     AND validation.payload_json->>'source_hash'=head_artifact.source_hash AND validation.payload_json->>'content_hash'=head_artifact.content_hash
     AND validation.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_native_quality_evidence blind ON blind.kind='blind'
     AND (blind.user_id,blind.epoch,blind.scope_id,blind.pack_task_id,blind.slot_id,blind.root_id,blind.version_id,blind.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND blind.payload_json=review.payload_json->'bundle'->'blind_solve' AND blind.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_persistent_pack_journal review_done ON review_done.pack_task_id=review.pack_task_id
     AND review_done.user_id=review.user_id AND review_done.epoch=review.epoch AND review_done.scope_id=review.scope_id
     AND review_done.record_kind='private_status' AND review_done.payload_json->>'schema_version'='private_native_stage_v1'
     AND review_done.payload_json->>'stage'='review' AND review_done.payload_json->>'status'='committed'
     AND review_done.payload_json->>'slot_id'=review.slot_id::text AND review_done.payload_json->>'job_id'=review.job_id::text
     AND review_done.payload_json->>'receipt_id'=review.id::text AND review_done.xmin::text::bigint<>(txid_current()%4294967296)
    WHERE review.kind='review' AND review.user_id=requested.user_id AND review.epoch=requested.epoch AND review.scope_id=requested.scope_id
    AND review.pack_task_id=requested.pack_task_id AND review.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
    AND review.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND review.version_id=head_artifact.version_id
    AND review.payload_json->>'schema_version'='private_native_review_v1' AND review.payload_json->>'artifact_id'=head_artifact.id::text
    AND review.payload_json->'ref'=binding_row.payload_json->'ref'
    AND review.payload_json->'spec'->'public_template'=head_artifact.request_json->'public_template'
    AND review.payload_json->'spec'->'blueprint'=head_artifact.request_json->'blueprint'
    AND review.payload_json->'bundle'->>'state'='completed' AND review.payload_json->'bundle'->>'mode'='peer_blind'
    AND review.payload_json->'bundle'->'binding'->>'version_key'=head_artifact.version_id::text
    AND review.payload_json->'bundle'->'binding'->>'source_hash'=head_artifact.source_hash
    AND review.payload_json->'bundle'->'binding'->>'content_hash'=head_artifact.content_hash
    AND jsonb_array_length(review.payload_json->'bundle'->'reports')=6
    AND (SELECT array_agg(report->>'role' ORDER BY report->>'role') FROM jsonb_array_elements(review.payload_json->'bundle'->'reports') report)
     =ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
    AND review.checked_at<review.valid_until AND review.created_at<review.valid_until
    AND review.xmin::text::bigint<>(txid_current()%4294967296);
   IF peer.id IS NOT NULL THEN
    -- Original timeless receiver verifies committed exact original7 preparation,
    -- validation, reservation, settlement and review policy/spec/artifact binding.
    PERFORM item_supply_internal.assert_private_native_review_stage(peer);
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications publication
     JOIN tutor_item_supply_private_native_quality_evidence quality ON quality.id=publication.quality_id AND quality.kind='admission'
      AND (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)=
          (publication.user_id,publication.epoch,publication.scope_id,publication.pack_task_id,publication.slot_id,publication.root_id,publication.version_id)
      AND quality.payload_json->>'schema_version'='private_native_quality_v1'
      AND quality.payload_json->>'receipt_id'=quality.id::text AND quality.payload_json->>'version_id'=head_artifact.version_id::text
      AND quality.payload_json->>'generation_artifact_id'=head_artifact.id::text AND quality.payload_json->>'review_receipt_id'=peer.id::text
      AND quality.payload_json->'ref'=peer.payload_json->'ref' AND quality.payload_json->'spec'=peer.payload_json->'spec'
      AND quality.payload_json->'bundle'=peer.payload_json->'bundle' AND quality.payload_json->'source'=head_artifact.source_json
      AND quality.payload_json->'request'=head_artifact.request_json AND quality.payload_json->'source_receipts'=head_artifact.receipt_json->'sources'
      AND quality.payload_json->'evaluation'->>'disposition'='eligible_internal' AND quality.payload_json->'evaluation'->'publication_enabled'='false'::jsonb
      AND quality.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_validation ON admitted_validation.id=(quality.payload_json->>'validation_receipt_id')::uuid
      AND admitted_validation.kind='validation' AND admitted_validation.payload_json=quality.payload_json->'validation'
      AND (admitted_validation.user_id,admitted_validation.epoch,admitted_validation.scope_id,admitted_validation.pack_task_id,admitted_validation.slot_id,admitted_validation.root_id,admitted_validation.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_validation.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_blind ON admitted_blind.id=(quality.payload_json->>'blind_receipt_id')::uuid
      AND admitted_blind.kind='blind' AND admitted_blind.payload_json=peer.payload_json->'bundle'->'blind_solve'
      AND (admitted_blind.user_id,admitted_blind.epoch,admitted_blind.scope_id,admitted_blind.pack_task_id,admitted_blind.slot_id,admitted_blind.root_id,admitted_blind.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_blind.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_versions version ON version.id=publication.version_id AND version.user_id=publication.user_id AND version.epoch=publication.epoch
      AND version.public_json=head_artifact.source_json->'public' AND version.private_json=head_artifact.source_json->'private'
     JOIN tutor_exercise_versions exercise ON exercise.id=publication.exercise_version_id AND exercise.source_kind='registered_author'
      AND exercise.content_hash=publication.payload_json->>'exercise_content_hash'
      AND exercise.exercise_key=head_artifact.source_json->'public'->>'item_key' AND exercise.version=head_artifact.source_json->'public'->>'version'
     JOIN tutor_exercise_private_rubrics rubric ON rubric.exercise_version_id=exercise.id AND rubric.rubric_hash=publication.payload_json->>'rubric_hash'
     WHERE publication.pack_task_id=requested.pack_task_id AND publication.user_id=requested.user_id AND publication.epoch=requested.epoch
     AND publication.scope_id=requested.scope_id AND publication.slot_id=peer.slot_id AND publication.root_id=peer.root_id
     AND publication.version_id=head_artifact.version_id AND publication.state='published'
     AND publication.payload_json->>'schema_version'='private_native_publication_v1'
     AND publication.payload_json->>'publication_id'=publication.id::text AND publication.payload_json->>'quality_id'=quality.id::text
     AND publication.payload_json->>'quality_hash'=quality.payload_hash AND publication.payload_json->'ref'=quality.payload_json->'ref'
     AND publication.payload_json->>'source_hash'=item_supply_internal.snapshot_hash(quality.payload_json->'source')
     AND publication.payload_json->>'content_hash'=peer.payload_json->'bundle'->'binding'->>'content_hash'
     AND publication.payload_json->>'item_handle'=version.handle AND publication.content_json->>'item_handle'=version.handle
     AND publication.xmin::text::bigint<>(txid_current()%4294967296)
     AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications successor
      WHERE successor.version_id=publication.version_id AND successor.user_id=publication.user_id AND successor.epoch=publication.epoch
      AND successor.state_version>publication.state_version)) THEN RETURN 'published'; END IF;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') report
     WHERE report->>'verdict'<>'approved' OR EXISTS(SELECT 1 FROM jsonb_array_elements(report->'findings') finding
      WHERE finding->>'blocking'='true' OR finding->>'severity' IN('major','critical')
      OR finding->>'safe_code' IN('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit')))
    THEN RETURN 'review_failed'; END IF;
   END IF;
   RETURN 'artifact';
  END IF;
  SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.failure';
  IF failure_row.id IS NULL AND binding_row.id='af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid THEN
   SELECT j.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal j
    WHERE j.pack_task_id=requested.pack_task_id AND j.operation_key='private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'
    AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1'
    AND j.payload_json->>'binding_id'=binding_row.id::text;
  END IF;
  IF failure_row.id IS NULL THEN RETURN NULL; END IF;
  failure_row:=item_supply_internal.private_initial_author_continuation_predecessor(failure_row.id,requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 END LOOP;
END;
$expected560$)
 ) AS expected(signature,header,result_type,body) LOOP
  SELECT array_agg(split_part(btrim(a),' ',1) ORDER BY n) INTO names
   FROM unnest(string_to_array(substring(spec.header FROM '\((.*)\)$'),',')) WITH ORDINALITY args(a,n) WHERE btrim(a)<>'';
  SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.'||spec.signature);
  IF NOT FOUND OR actual.prosrc IS DISTINCT FROM spec.body OR NOT actual.prosecdef OR actual.prokind<>'f'
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.prorettype IS DISTINCT FROM to_regtype(spec.result_type) OR actual.proargnames IS DISTINCT FROM names
   OR actual.provolatile<>'v' OR actual.proretset OR actual.proisstrict OR actual.proleakproof OR actual.proparallel<>'u'
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0 OR actual.provariadic<>0
   OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
   OR actual.probin IS NOT NULL OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
   OR actual.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql') THEN RETURN false; END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','private_generation_durability_insert','enforce_private_generation_durability_insert'),
  ('tutor_item_supply_private_generation_artifacts','private_generation_durability_artifact','enforce_private_generation_durability_artifact')
 ) AS expected(table_name,trigger_name,function_name) LOOP
  SELECT t.* INTO actual FROM pg_trigger t WHERE t.tgrelid=to_regclass('public.'||tr.table_name) AND t.tgname=tr.trigger_name;
  IF NOT FOUND OR actual.tgfoid IS DISTINCT FROM to_regprocedure('item_supply_internal.'||tr.function_name||'()')
   OR actual.tgtype<>7 OR actual.tgenabled<>'O' OR actual.tgisinternal OR actual.tgdeferrable OR actual.tginitdeferred
   OR actual.tgnargs<>0 OR actual.tgqual IS NOT NULL OR actual.tgattr::text<>'' OR actual.tgargs<>''::bytea
   OR actual.tgparentid<>0 OR actual.tgconstrrelid<>0 OR actual.tgconstrindid<>0 OR actual.tgconstraint<>0
   OR actual.tgoldtable IS NOT NULL OR actual.tgnewtable IS NOT NULL THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END;
$oldready562$;
 new_body constant text := $newready562$
DECLARE spec record; actual record; names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001' THEN RETURN false; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_generation_durability_attempt(uuid)','private_generation_durability_attempt(p_preparation uuid)','jsonb',$expected560$
DECLARE task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; aux public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; phase public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 binding public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; approval public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; claim public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 started public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; consumed public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE; reservation public.tutor_item_supply_private_reservations%ROWTYPE;
 settlement public.tutor_item_supply_private_runtime_settlements%ROWTYPE; profile public.tutor_item_supply_parameter_profiles%ROWTYPE;
 ref jsonb; lease_json jsonb; request jsonb; attempt_key text; amounts jsonb; stamp timestamptz;
BEGIN
 -- One original same-user lock domain shared by capture and the fixed technical gap.
 PERFORM item_supply_internal.private_native_epoch('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1);
 PERFORM 1 FROM tutor_item_supply_private_scopes s JOIN tutor_track_active_plans p
  ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
  WHERE s.id='cef6af15-84c0-466a-b330-3dc3235aa587' AND s.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND s.epoch=1 FOR SHARE OF s,p;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='560 current original namespace/active plan required'; END IF;
 SELECT j.* INTO task_row FROM tutor_item_supply_private_persistent_pack_journal j
  WHERE j.id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.pack_task_id=j.id AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='task' FOR SHARE;
 IF task_row.id IS NULL OR task_row.payload_json->>'enhancement' IS DISTINCT FROM 'prefer_private'
  OR task_row.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
 THEN RAISE check_violation USING MESSAGE='560 original PRIVATE task required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_budget_roots r WHERE r.id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND r.user_id=task_row.user_id
  AND r.epoch=task_row.epoch AND r.scope_id=task_row.scope_id FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='560 original canonical root required'; END IF;
 SELECT j.* INTO aux FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_preparation
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
  AND j.record_kind='private_attachment' AND j.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND j.payload_json->'request'->>'schema_version'='private_native_initial_author_v1' FOR UPDATE;
 IF aux.id IS NULL THEN RAISE check_violation USING MESSAGE='560 original initial-author preparation required'; END IF;
 ref:=aux.payload_json->'request'->'ref'; request:=aux.payload_json->'request'->'request';
 SELECT j.* INTO phase FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
  AND j.user_id=task_row.user_id AND j.epoch=1 AND j.scope_id=task_row.scope_id AND j.record_kind='phase'
  AND j.operation_key='private.phase.'||(aux.payload_json->>'job_id') AND j.payload_json->>'schema_version'='private_native_phase_v1';
 lease_json:=phase.payload_json->'lease';
 IF phase.id IS NULL OR phase.payload_json->'ref' IS DISTINCT FROM ref
  OR (ref->>'pack_task_id',ref->>'user_id',ref->>'epoch',ref->>'scope_id',ref->>'root_id',ref->>'mapping_receipt_id') IS DISTINCT FROM
   (task_row.id::text,task_row.user_id::text,'1',task_row.scope_id::text,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9','d8e34e01-3514-41a3-9bbd-55ee3e627134')
  OR ref->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
  OR request->>'candidate_id' IS DISTINCT FROM aux.id::text OR request->>'version' IS DISTINCT FROM 'v1'
  OR request->>'item_key' IS DISTINCT FROM 'private-native.'||replace(ref->>'business_item_id','-','')
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(task_row.payload_json->'slots') s
   WHERE s->>'slot_id'=ref->>'slot_id' AND s->>'logical_item_id'=ref->>'business_item_id')
 THEN RAISE check_violation USING MESSAGE='560 exact original committed initial preparation/ref/request required'; END IF;
 SELECT j.* INTO binding FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
  AND j.payload_json->>'schema_version' IN('private_initial_author_recovery_binding_v1','private_initial_author_continuation_binding_v1')
  AND j.user_id=task_row.user_id AND j.epoch=task_row.epoch AND j.scope_id=task_row.scope_id
  AND j.payload_json->>'preparation_id'=aux.id::text AND j.payload_json->>'candidate_id'=aux.id::text FOR UPDATE;
 IF binding.id IS NOT NULL THEN
  SELECT j.* INTO approval FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(binding.payload_json->>'approval_id')::uuid FOR UPDATE;
  SELECT j.* INTO claim FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(binding.payload_json->>'claim_id')::uuid FOR SHARE;
  attempt_key:=left(binding.operation_key,length(binding.operation_key)-length('.binding'));
  IF binding.operation_key IS DISTINCT FROM attempt_key||'.binding' OR approval.operation_key IS DISTINCT FROM attempt_key||'.approval'
   OR claim.operation_key IS DISTINCT FROM attempt_key||'.claim'
   OR (approval.pack_task_id,approval.user_id,approval.epoch,approval.scope_id) IS DISTINCT FROM (task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
   OR (claim.pack_task_id,claim.user_id,claim.epoch,claim.scope_id) IS DISTINCT FROM (task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id)
   OR binding.payload_json->'ref' IS DISTINCT FROM ref OR binding.payload_json->'request' IS DISTINCT FROM request
   OR binding.payload_json->'lease' IS DISTINCT FROM lease_json
   OR binding.payload_json->>'reservation_id' IS DISTINCT FROM aux.payload_json->>'reservation_id'
   OR claim.payload_json->>'approval_id' IS DISTINCT FROM approval.id::text
   OR claim.payload_json->>'job_id' IS DISTINCT FROM aux.payload_json->>'job_id'
  THEN RAISE check_violation USING MESSAGE='560 exact original approval/claim/binding required'; END IF;
  IF binding.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1' THEN
   PERFORM item_supply_internal.private_initial_author_continuation_approval(approval.id);
  ELSIF attempt_key IS DISTINCT FROM 'p7.private.initial-author.recovery.20261015.once1' THEN
   RAISE check_violation USING MESSAGE='560 closed original recovery namespace required';
  END IF;
  SELECT j.* INTO consumed FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
   AND j.user_id=task_row.user_id AND j.epoch=task_row.epoch AND j.scope_id=task_row.scope_id AND j.record_kind='private_status'
   AND j.payload_json->>'schema_version' IN('private_initial_author_recovery_consumed_v1','private_initial_author_continuation_consumed_v1')
   AND j.operation_key=attempt_key||'.consumed' AND j.payload_json->>'binding_id'=binding.id::text;
  attempt_key:=attempt_key||'.author';
 ELSE
  attempt_key:='private.stage.'||replace(ref->>'business_item_id','-','')||'.author.'||item_supply_internal.snapshot_hash('"v1"'::jsonb);
 END IF;
 SELECT j.* INTO started FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=task_row.id
  AND j.user_id=task_row.user_id AND j.epoch=task_row.epoch AND j.scope_id=task_row.scope_id
  AND j.operation_key=attempt_key||'.started' AND j.record_kind='private_status'
  AND j.payload_json->>'schema_version'='private_native_stage_v1' AND j.payload_json->>'stage'='author'
  AND j.payload_json->>'status'='started' AND j.payload_json->'receipt_id'='null'::jsonb
  AND j.payload_json->>'slot_id'=ref->>'slot_id' AND j.payload_json->>'job_id'=aux.payload_json->>'job_id'
  AND j.payload_json->>'subject_hash'=item_supply_internal.snapshot_hash('"v1"'::jsonb);
 IF started.id IS NULL OR (binding.id IS NOT NULL AND (consumed.id IS NULL
  OR consumed.payload_json->>'started_id' IS DISTINCT FROM started.id::text
  OR consumed.payload_json->>'candidate_id' IS DISTINCT FROM aux.id::text
  OR consumed.payload_json->>'job_id' IS DISTINCT FROM aux.payload_json->>'job_id'
  OR consumed.payload_json->>'reservation_id' IS DISTINCT FROM aux.payload_json->>'reservation_id'))
 THEN RAISE check_violation USING MESSAGE='560 original dispatched once/consume required'; END IF;
 -- No absence decision occurs before this original control lock.
 SELECT c.* INTO ctrl FROM tutor_item_supply_private_job_controls c WHERE c.job_id=(aux.payload_json->>'job_id')::uuid
  AND c.user_id=task_row.user_id AND c.epoch=1 AND c.scope_id=task_row.scope_id FOR UPDATE;
 SELECT p.* INTO profile FROM tutor_item_supply_parameter_profiles p WHERE p.id=ctrl.profile_id;
 SELECT r.* INTO reservation FROM tutor_item_supply_private_reservations r WHERE r.id=(aux.payload_json->>'reservation_id')::uuid
  AND r.user_id=task_row.user_id AND r.epoch=1 AND r.scope_id=task_row.scope_id AND r.job_id=ctrl.job_id AND r.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' FOR SHARE;
 SELECT s.* INTO settlement FROM tutor_item_supply_private_runtime_settlements s WHERE s.reservation_id=reservation.id
  AND s.user_id=task_row.user_id AND s.epoch=1 AND s.scope_id=task_row.scope_id
  AND s.settlement_key='generation.'||replace(aux.id::text,'-','') AND s.sequence=1 FOR SHARE;
 IF ctrl.id IS NULL OR profile.id IS NULL OR reservation.id IS NULL OR settlement.id IS NULL
  OR ctrl.lease_generation IS DISTINCT FROM (lease_json->>'generation')::integer
  OR reservation.lease_generation IS DISTINCT FROM ctrl.lease_generation
  OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner'
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR ctrl.profile_snapshot_json->'profile' IS DISTINCT FROM lease_json->'profile'
  OR ctrl.profile_snapshot_json->'retry_policy' IS DISTINCT FROM lease_json->'retry_policy'
  OR request->'profile' IS DISTINCT FROM lease_json->'profile'
  OR profile.profile_hash IS DISTINCT FROM lease_json->'profile'->>'profile_hash'
 THEN RAISE check_violation USING MESSAGE='560 historical prepared control/profile/reservation/settlement identity required'; END IF;
 SELECT jsonb_object_agg(a.resource_kind,a.actual_amount) INTO amounts FROM tutor_item_supply_private_runtime_settlement_amounts a WHERE a.settlement_id=settlement.id;
 stamp:=clock_timestamp();
 IF p_preparation='eeebd057-3e04-4a61-8979-201446e20221' THEN
  IF binding.id IS DISTINCT FROM 'af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid OR consumed.id IS DISTINCT FROM 'b4866afd-d59f-4aef-bec3-1b1279fbaa14'::uuid
   OR ref->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   OR ref->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
   OR approval.payload_json->>'predecessor_failure_id' IS DISTINCT FROM 'df0a6e8c-287a-4814-98f1-5deeb59347a3'
   OR ctrl.job_id IS DISTINCT FROM '80f8f576-166e-48ea-aaa7-f78809da38b8'::uuid
   OR settlement.id IS DISTINCT FROM '55e11576-7b38-4f04-bee5-90ff5e6df51d'::uuid
   OR reservation.id IS DISTINCT FROM '4e0ec381-f9e4-4c11-b391-cedbc2480e04'::uuid
   OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.breaker_open OR ctrl.state IS DISTINCT FROM 'leased' OR ctrl.state_version<>2
   OR (lease_json->>'expires_at')::timestamptz IS DISTINCT FROM ctrl.lease_expires_at
   OR ctrl.lease_expires_at IS DISTINCT FROM '2026-10-16 03:05:23.278164+08'::timestamptz
   OR ctrl.parent_deadline IS DISTINCT FROM '2026-10-16 03:45:22.951952+08'::timestamptz
   OR ctrl.lease_expires_at>stamp OR settlement.usage_state IS DISTINCT FROM 'known' OR settlement.cost_amount IS NOT NULL
   OR settlement.receipt_hash IS DISTINCT FROM '8c7ae3625382be3e25a2d4980e09ee3259b03463ba63b642d76cc85847dc468f'
   OR amounts IS DISTINCT FROM '{"requests":1,"candidates":1,"input_tokens":12916,"output_tokens":2082,"execution_seconds":0,"fetches":0,"revision_rounds":0,"investigation_rounds":0}'::jsonb
  THEN RAISE check_violation USING MESSAGE='560 fixed naturally expired known-paid C14 identity required'; END IF;
 END IF;
 RETURN jsonb_build_object('task',to_jsonb(task_row),'aux',to_jsonb(aux),'phase',to_jsonb(phase),'binding',CASE WHEN binding.id IS NULL THEN jsonb_build_object('id',NULL) ELSE to_jsonb(binding) END,
  'approval',to_jsonb(approval),'started',to_jsonb(started),'consumed',CASE WHEN consumed.id IS NULL THEN jsonb_build_object('id',NULL) ELSE to_jsonb(consumed) END,'control',to_jsonb(ctrl),
  'reservation',to_jsonb(reservation),'settlement',to_jsonb(settlement),'amounts',amounts,
  'producer_binding',jsonb_build_array(profile.profile_json->'profile_key'->>'provider',profile.profile_json->'profile_key'->>'model_version'));
END;
$expected560$),
 ('private_initial_author_persistence_gap_issue(uuid,uuid,bigint,uuid,uuid)','private_initial_author_persistence_gap_issue(p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid,p_binding uuid)','uuid',$expected560$
DECLARE d jsonb; identity uuid:=gen_random_uuid(); stamp timestamptz;
BEGIN
 IF p_binding IS DISTINCT FROM 'af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid THEN RAISE check_violation USING MESSAGE='560 fixed C14 gap binding required'; END IF;
 IF (p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid)
 THEN RAISE check_violation USING MESSAGE='560 exact gap issuance namespace required'; END IF;
 d:=item_supply_internal.private_generation_durability_attempt('eeebd057-3e04-4a61-8979-201446e20221');
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=p_task
   AND j.operation_key IN('private.generation.output.eeebd0573e044a618979201446e20221','private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'))
 THEN RAISE check_violation USING MESSAGE='560 durable product/output or prior technical gap already exists'; END IF;
 stamp:=clock_timestamp();
 IF (d->'control'->>'lease_expires_at')::timestamptz>stamp THEN RAISE check_violation USING MESSAGE='560 C14 lease not naturally expired'; END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,p_task,p_user,p_epoch,p_scope,'private_status','private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6',d->'task'->>'intent_hash',
  jsonb_build_object('schema_version','private_initial_author_persistence_gap_v1',
  'binding_id','af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6','preparation_id','eeebd057-3e04-4a61-8979-201446e20221','job_id',d->'control'->>'job_id',
  'started_id',d->'started'->>'id','consumed_id',d->'consumed'->>'id','reservation_id',d->'reservation'->>'id',
  'settlement_id',d->'settlement'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
  'provider_receipt_hash',d->'settlement'->>'receipt_hash','disposition','expired_consumed_no_durable_output',
  'issued_top_xid',pg_current_xact_id()::text,'issued_at',stamp));
 RETURN identity;
END;
$expected560$),
 ('private_initial_author_persistence_gap_committed(uuid,uuid,uuid,bigint,uuid)','private_initial_author_persistence_gap_committed(p_receipt uuid,p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)','public.tutor_item_supply_private_persistent_pack_journal',$expected560$
DECLARE d jsonb; gap public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; body jsonb;
BEGIN
 IF (p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid)
 THEN RAISE check_violation USING MESSAGE='560 exact gap namespace required'; END IF;
 d:=item_supply_internal.private_generation_durability_attempt('eeebd057-3e04-4a61-8979-201446e20221');
 SELECT j.* INTO gap FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_receipt
  AND (j.pack_task_id,j.user_id,j.epoch,j.scope_id)=(p_task,p_user,p_epoch,p_scope) AND j.record_kind='private_status'
  AND j.operation_key='private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6' FOR SHARE;
 body:=gap.payload_json;
 IF gap.id IS NULL OR body IS DISTINCT FROM jsonb_build_object('schema_version','private_initial_author_persistence_gap_v1',
  'binding_id','af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6','preparation_id','eeebd057-3e04-4a61-8979-201446e20221','job_id',d->'control'->>'job_id',
  'started_id',d->'started'->>'id','consumed_id',d->'consumed'->>'id','reservation_id',d->'reservation'->>'id',
  'settlement_id',d->'settlement'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
  'provider_receipt_hash',d->'settlement'->>'receipt_hash','disposition','expired_consumed_no_durable_output',
  'issued_top_xid',body->>'issued_top_xid','issued_at',body->'issued_at')
  OR jsonb_typeof(body->'issued_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'issued_top_xid')::xid8::text IS DISTINCT FROM body->>'issued_top_xid'
  OR (body->>'issued_at')::timestamptz IS NULL OR (body->>'issued_at')::timestamptz>clock_timestamp()
 THEN RAISE check_violation USING MESSAGE='560 exact technical gap record required'; END IF;
 IF body->>'issued_top_xid'=pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='560 technical gap requires a different committed TOP';
 END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=p_task
   AND j.operation_key='private.generation.output.eeebd0573e044a618979201446e20221')
 THEN RAISE check_violation USING MESSAGE='560 historical C14 paid/no-output facts changed'; END IF;
 RETURN gap;
END;
$expected560$),
 ('private_generation_output_capture(uuid,jsonb)','private_generation_output_capture(p_preparation uuid,p_capture jsonb)','uuid',$expected560$
DECLARE d jsonb; existing public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; identity uuid:=gen_random_uuid(); stamp timestamptz; output_key text;
BEGIN
 d:=item_supply_internal.private_generation_durability_attempt(p_preparation);
 IF p_preparation='eeebd057-3e04-4a61-8979-201446e20221' OR d->'control'->>'job_id' IN('487b12c4-f98a-41c9-a21b-abb9243a28dd','6691f9a2-073a-4fbc-8783-09d6ef0ca8d5')
 THEN RAISE check_violation USING MESSAGE='560 historical author output cannot be backfilled'; END IF;
 output_key:='private.generation.output.'||replace(p_preparation::text,'-','');
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' AND j.payload_json->>'preparation_id'=p_preparation::text)
 THEN RAISE check_violation USING MESSAGE='560 technical gap forbids output capture'; END IF;
 SELECT j.* INTO existing FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND j.operation_key=output_key FOR SHARE;
 IF existing.id IS NOT NULL THEN
  IF existing.payload_json->>'schema_version' IS DISTINCT FROM 'private_generation_output_v1' OR existing.payload_json->'capture' IS DISTINCT FROM p_capture
  THEN RAISE check_violation USING MESSAGE='560 original sealed output/context conflict'; END IF;
  RETURN existing.id;
 END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid) THEN RAISE check_violation USING MESSAGE='560 capture must precede artifact/checkpoint/quality'; END IF;
 stamp:=clock_timestamp();
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,'6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587','private_status',output_key,d->'task'->>'intent_hash',
  jsonb_build_object('schema_version','private_generation_output_v1','preparation_id',p_preparation,'binding_id',d->'binding'->'id',
   'started_id',d->'started'->'id','consumed_id',d->'consumed'->'id','settlement_id',d->'settlement'->'id',
   'request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
   'capture',p_capture,'captured_top_xid',pg_current_xact_id()::text,'captured_at',stamp));
 RETURN identity;
END;
$expected560$),
 ('private_generation_output_committed(uuid,jsonb)','private_generation_output_committed(p_preparation uuid,p_capture jsonb)','uuid',$expected560$
DECLARE d jsonb; output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; body jsonb;
BEGIN
 d:=item_supply_internal.private_generation_durability_attempt(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND j.epoch=1 AND j.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587' AND j.record_kind='private_status'
  AND j.operation_key='private.generation.output.'||replace(p_preparation::text,'-','') FOR SHARE;
 body:=output_row.payload_json;
 IF output_row.id IS NULL OR body->>'schema_version' IS DISTINCT FROM 'private_generation_output_v1'
  OR body->>'preparation_id' IS DISTINCT FROM p_preparation::text OR body->'capture' IS DISTINCT FROM p_capture
  OR body->'binding_id' IS DISTINCT FROM d->'binding'->'id' OR body->'started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'consumed_id' IS DISTINCT FROM d->'consumed'->'id' OR body->'settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request')
  OR jsonb_typeof(body->'captured_top_xid') IS DISTINCT FROM 'string'
  OR (body->>'captured_top_xid')::xid8::text IS DISTINCT FROM body->>'captured_top_xid'
  OR (body->>'captured_at')::timestamptz IS NULL OR (body->>'captured_at')::timestamptz>clock_timestamp()
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' AND j.payload_json->>'preparation_id'=p_preparation::text)
 THEN RAISE check_violation USING MESSAGE='560 exact original sealed output record required'; END IF;
 IF body->>'captured_top_xid'=pg_current_xact_id()::text THEN
  RAISE check_violation USING MESSAGE='560 output requires a different committed TOP';
 END IF;
 RETURN output_row.id;
END;
$expected560$),
 ('enforce_private_generation_durability_insert()','enforce_private_generation_durability_insert()','trigger',$expected560$
DECLARE body jsonb:=NEW.payload_json; protocol text:=body->>'schema_version'; d jsonb; capture jsonb; ctx jsonb;
 result jsonb; source jsonb; receipt jsonb; provider jsonb; request jsonb; expected_content text; stamp timestamptz; known boolean;
BEGIN
 IF COALESCE(protocol NOT IN('private_generation_output_v1','private_initial_author_persistence_gap_v1'),true)
  AND NEW.operation_key NOT LIKE 'private.generation.output.%' AND NEW.operation_key NOT LIKE 'private.generation.gap.%' THEN RETURN NEW; END IF;
 IF protocol NOT IN('private_generation_output_v1','private_initial_author_persistence_gap_v1') OR protocol IS NULL
 THEN RAISE check_violation USING MESSAGE='560 closed durability journal schema required'; END IF;
 d:=item_supply_internal.private_generation_durability_attempt((body->>'preparation_id')::uuid);
 IF (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.record_kind,NEW.intent_hash) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'private_status',d->'task'->>'intent_hash')
 THEN RAISE check_violation USING MESSAGE='560 exact original durability namespace required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE a.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints c WHERE c.job_id=(d->'control'->>'job_id')::uuid AND c.stage='generating' AND c.status='completed')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND j.operation_key=replace(d->'started'->>'operation_key','.started','.result'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.job_id=(d->'control'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications p JOIN tutor_item_supply_private_native_quality_evidence q ON q.id=p.quality_id
   WHERE q.job_id=(d->'control'->>'job_id')::uuid) THEN RAISE check_violation USING MESSAGE='560 durable product already exists before journal append'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=NEW.pack_task_id
  AND (j.operation_key=NEW.operation_key OR (j.payload_json->>'preparation_id'=body->>'preparation_id'
   AND j.payload_json->>'schema_version' IN('private_generation_output_v1','private_initial_author_persistence_gap_v1'))))
 THEN RAISE check_violation USING MESSAGE='560 output/gap exclusive immutable attempt already recorded'; END IF;
 stamp:=clock_timestamp();
 IF protocol='private_initial_author_persistence_gap_v1' THEN
  IF NEW.operation_key IS DISTINCT FROM 'private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'
   OR body->>'preparation_id' IS DISTINCT FROM 'eeebd057-3e04-4a61-8979-201446e20221'
   OR body IS DISTINCT FROM jsonb_build_object('schema_version','private_initial_author_persistence_gap_v1',
  'binding_id','af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6','preparation_id','eeebd057-3e04-4a61-8979-201446e20221','job_id',d->'control'->>'job_id',
  'started_id',d->'started'->>'id','consumed_id',d->'consumed'->>'id','reservation_id',d->'reservation'->>'id',
  'settlement_id',d->'settlement'->>'id','request_hash',item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request'),
  'provider_receipt_hash',d->'settlement'->>'receipt_hash','disposition','expired_consumed_no_durable_output',
  'issued_top_xid',pg_current_xact_id()::text,'issued_at',body->'issued_at')
   OR jsonb_typeof(body->'issued_top_xid') IS DISTINCT FROM 'string'
   OR (body->>'issued_at')::timestamptz IS NULL OR (body->>'issued_at')::timestamptz>stamp
   OR (d->'control'->>'lease_expires_at')::timestamptz>stamp
  THEN RAISE check_violation USING MESSAGE='560 exact server-TOP naturally expired fixed technical gap required'; END IF;
  RETURN NEW;
 END IF;
 IF body->>'preparation_id'='eeebd057-3e04-4a61-8979-201446e20221' OR d->'control'->>'job_id' IN('487b12c4-f98a-41c9-a21b-abb9243a28dd','6691f9a2-073a-4fbc-8783-09d6ef0ca8d5')
 THEN RAISE check_violation USING MESSAGE='560 historical author output cannot be backfilled'; END IF;
 IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','preparation_id','binding_id','started_id','consumed_id','settlement_id','request_hash','capture','captured_top_xid','captured_at']) IS DISTINCT FROM true
  OR NEW.operation_key IS DISTINCT FROM 'private.generation.output.'||replace(body->>'preparation_id','-','')
  OR body->'binding_id' IS DISTINCT FROM d->'binding'->'id' OR body->'started_id' IS DISTINCT FROM d->'started'->'id'
  OR body->'consumed_id' IS DISTINCT FROM d->'consumed'->'id' OR body->'settlement_id' IS DISTINCT FROM d->'settlement'->'id'
  OR body->>'request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(d->'aux'->'payload_json'->'request'->'request')
  OR body->'captured_top_xid' IS DISTINCT FROM to_jsonb(pg_current_xact_id()::text)
  OR (body->>'captured_at')::timestamptz IS NULL OR (body->>'captured_at')::timestamptz>stamp
 THEN RAISE check_violation USING MESSAGE='560 exact original output refs/server TOP required'; END IF;
 capture:=body->'capture'; ctx:=capture->'context'; result:=capture->'result'; request:=ctx->'request';
 source:=result->'source'; receipt:=result->'receipt'; provider:=receipt->'provider';
 IF item_supply_internal.snapshot_keys(capture,ARRAY['schema_version','context','result']) IS DISTINCT FROM true
  OR capture->>'schema_version' IS DISTINCT FROM 'private_generation_capture_v1'
  OR item_supply_internal.snapshot_keys(ctx,ARRAY['ref','lease','scope_id','request','reservation_id','sources','attempt_bound','mode','producer_binding']) IS DISTINCT FROM true
  OR ctx->'ref' IS DISTINCT FROM d->'aux'->'payload_json'->'request'->'ref'
  OR ctx->'lease' IS DISTINCT FROM d->'phase'->'payload_json'->'lease'
  OR ctx->>'scope_id' IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587' OR request IS DISTINCT FROM d->'aux'->'payload_json'->'request'->'request'
  OR ctx->'reservation_id' IS DISTINCT FROM d->'reservation'->'id'
  OR ctx->'attempt_bound' IS DISTINCT FROM '1'::jsonb OR ctx->>'mode' IS DISTINCT FROM 'live'
  OR ctx->'producer_binding' IS DISTINCT FROM d->'producer_binding'
  OR item_supply_internal.snapshot_keys(result,ARRAY['state','source','receipt','safe_reason']) IS DISTINCT FROM true
  OR result->>'state' IS DISTINCT FROM 'staged' OR result->>'safe_reason' IS DISTINCT FROM 'staged'
  OR item_supply_internal.snapshot_keys(source,ARRAY['schema_version','blueprint','public','private']) IS DISTINCT FROM true
  OR source->>'schema_version' IS DISTINCT FROM 'learning_item_source_v1'
  OR source->'blueprint' IS DISTINCT FROM request->'blueprint'
  OR (source->'public'->>'item_key',source->'public'->>'version') IS DISTINCT FROM (request->>'item_key',request->>'version')
  OR (source->'private'->>'item_key',source->'private'->>'version',source->'private'->>'kind') IS DISTINCT FROM
     (source->'public'->>'item_key',source->'public'->>'version',source->'public'->>'kind')
  OR item_supply_internal.snapshot_keys(receipt,ARRAY['schema_version','candidate_id','scope_hash','source_hash','content_hash','provider','sources']) IS DISTINCT FROM true
  OR receipt->>'schema_version' IS DISTINCT FROM 'item_generation_receipt_v2'
  OR receipt->>'candidate_id' IS DISTINCT FROM body->>'preparation_id' OR receipt->>'scope_hash' IS DISTINCT FROM request->>'scope_hash'
  OR receipt->'sources' IS DISTINCT FROM ctx->'sources'
  OR (d->'binding'->>'id' IS NOT NULL AND ctx->'sources' IS DISTINCT FROM d->'binding'->'payload_json'->'sources')
  OR item_supply_internal.snapshot_keys(provider,ARRAY['provider','provider_version','configured_model','model','prompt_version','role','run_id','request_attempt_bound','actual_requests','usage','mode']) IS DISTINCT FROM true
  OR item_supply_internal.snapshot_keys(provider->'usage',ARRAY['state','input_tokens','cached_input_tokens','output_tokens','total_tokens','reasoning_tokens','cost']) IS DISTINCT FROM true
  OR provider->>'mode' IS DISTINCT FROM 'provider' OR provider->>'role' IS DISTINCT FROM 'item_author'
  OR provider->'request_attempt_bound' IS DISTINCT FROM '1'::jsonb
  OR (provider->'actual_requests'<>'null'::jsonb AND provider->'actual_requests' IS DISTINCT FROM '1'::jsonb)
  OR jsonb_build_array(provider->>'provider',provider->>'configured_model') IS DISTINCT FROM ctx->'producer_binding'
  OR provider->>'model' IS DISTINCT FROM provider->>'configured_model'
 THEN RAISE check_violation USING MESSAGE='560 full original sealed context/staged source/receipt identity required'; END IF;
 expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object('item_key',source->'public'->>'item_key','version',source->'public'->>'version',
  'blueprint_hash',item_supply_internal.snapshot_hash(source->'blueprint'),'public_hash',item_supply_internal.snapshot_hash(source->'public'),
  'private_hash',item_supply_internal.snapshot_hash(source->'private')));
 IF receipt->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(source) OR receipt->>'content_hash' IS DISTINCT FROM expected_content
  OR jsonb_typeof(ctx->'sources') IS DISTINCT FROM 'array' OR jsonb_array_length(ctx->'sources') NOT BETWEEN 1 AND 12
  OR jsonb_array_length(ctx->'sources') IS DISTINCT FROM jsonb_array_length(request->'materials')
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(ctx->'sources') WITH ORDINALITY s(value,n)
   JOIN jsonb_array_elements(request->'materials') WITH ORDINALITY m(value,n) ON m.n=s.n
   WHERE item_supply_internal.snapshot_keys(s.value,ARRAY['material_digest','binding_digest','corpus_version_id','active_generation','checked_at_iso','claim_receipt_hashes','mode']) IS DISTINCT FROM true
    OR s.value->>'mode' IS DISTINCT FROM 'current_authority'
    OR s.value->>'binding_digest' IS DISTINCT FROM m.value->'binding'->>'binding_digest'
    OR s.value->>'corpus_version_id' IS DISTINCT FROM m.value->'binding'->'evidence'->0->>'corpus_version_id'
    OR s.value->'active_generation' IS DISTINCT FROM m.value->'binding'->'evidence'->0->'active_generation'
    OR s.value->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('binding',m.value->'binding',
      'access_request',m.value->'access_request','exact_claims',m.value->'exact_claims',
      'excerpt_hash',encode(sha256(convert_to(m.value->>'excerpt','UTF8')),'hex'))))
 THEN RAISE check_violation USING MESSAGE='560 complete original source/content/material hashes required'; END IF;
 known:=provider->'usage'->>'state'='known' AND provider->>'actual_requests' IS NOT NULL
  AND provider->'usage'->>'input_tokens' IS NOT NULL AND provider->'usage'->>'output_tokens' IS NOT NULL;
 IF d->'settlement'->'cost_amount' IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='560 original null cost must be retained'; END IF;
 IF known THEN
  IF d->'settlement'->>'usage_state' IS DISTINCT FROM 'known' OR d->'settlement'->>'receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(provider)
   OR d->'amounts' IS DISTINCT FROM jsonb_build_object('requests',(provider->>'actual_requests')::bigint,'candidates',1,
    'input_tokens',(provider->'usage'->>'input_tokens')::bigint,'output_tokens',(provider->'usage'->>'output_tokens')::bigint,
    'execution_seconds',0,'fetches',0,'revision_rounds',0,'investigation_rounds',0)
  THEN RAISE check_violation USING MESSAGE='560 exact known original provider/settlement amounts required'; END IF;
 ELSE
  IF COALESCE(provider->'usage'->>'state' IN('known','unknown'),false) IS DISTINCT FROM true
   OR d->'settlement'->>'usage_state' IS DISTINCT FROM 'unknown' OR d->'settlement'->'receipt_hash' IS DISTINCT FROM 'null'::jsonb
   OR d->'amounts' IS DISTINCT FROM 'null'::jsonb
  THEN RAISE check_violation USING MESSAGE='560 UNKNOWN/null original settlement must be retained'; END IF;
 END IF;
 -- Final DB clock, not a current grant for the expired author/source.
 IF (body->>'captured_at')::timestamptz>clock_timestamp() THEN RAISE check_violation USING MESSAGE='560 future capture timestamp'; END IF;
 RETURN NEW;
END;
$expected560$),
 ('enforce_private_generation_durability_artifact()','enforce_private_generation_durability_artifact()','trigger',$expected560$
DECLARE output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; output_id uuid; p_preparation uuid;
 bridge_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; origin_id uuid; origin_count bigint;
BEGIN
 IF NEW.mode IS DISTINCT FROM 'live' OR NEW.user_id IS DISTINCT FROM 'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid OR NEW.epoch<>1
  OR NEW.scope_id IS DISTINCT FROM 'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid THEN RETURN NEW; END IF;
 -- Inherited/idempotent staging of an already existing exact generation is not a new author.
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts a WHERE
  (a.user_id,a.epoch,a.scope_id,a.job_id,a.lease_generation,a.artifact_key,a.candidate_id,a.version_id,a.mode,a.source_hash,a.content_hash,a.request_json,a.source_json,a.receipt_json)=
  (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id,NEW.lease_generation,NEW.artifact_key,NEW.candidate_id,NEW.version_id,NEW.mode,NEW.source_hash,NEW.content_hash,NEW.request_json,NEW.source_json,NEW.receipt_json)) THEN RETURN NEW; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal phase WHERE phase.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND phase.user_id=NEW.user_id AND phase.epoch=NEW.epoch AND phase.scope_id=NEW.scope_id AND phase.record_kind='phase'
  AND phase.payload_json->>'schema_version'='private_native_phase_v1' AND phase.payload_json->>'job_id'=NEW.job_id::text
  AND phase.payload_json->'ref'->'parent_version_id'='null'::jsonb) THEN RETURN NEW; END IF;
 -- C18: this one separately committed output may use its one committed new writer, not a recovered author.
 SELECT j.* INTO bridge_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.user_id=NEW.user_id AND j.epoch=NEW.epoch AND j.scope_id=NEW.scope_id AND j.record_kind='private_status'
  AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb' AND j.payload_json->>'schema_version'='private_generation_persistence_phase_v1'
  AND j.payload_json->>'writer_job_id'=NEW.job_id::text;
 IF bridge_row.id IS NOT NULL THEN
  PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
  PERFORM item_supply_internal.private_generation_durability_attempt('d55f63a9-8043-4d74-8a1c-0862660aed30');
  IF bridge_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
  THEN RAISE check_violation USING MESSAGE='562 prior-TOP persistence binding required'; END IF;
  SELECT count(*),(array_agg(o.id ORDER BY o.id))[1] INTO origin_count,origin_id FROM tutor_item_supply_private_persistent_pack_journal o
   WHERE o.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND o.user_id=NEW.user_id AND o.epoch=NEW.epoch AND o.scope_id=NEW.scope_id
   AND o.record_kind='current_pack_source_origin' AND o.payload_json->>'capture_txid'=pg_current_xact_id()::text
   AND item_supply_internal.current_pack_source_origin_current(o.id,NEW.user_id,NEW.epoch,'d8e34e01-3514-41a3-9bbd-55ee3e627134');
  IF origin_count<>1 THEN RAISE check_violation USING MESSAGE='562 one actual same-TOP SOURCE origin required'; END IF;
  SELECT b.* INTO bridge_row FROM item_supply_internal.private_generation_persistence_phase_bound(bridge_row.id,origin_id) b;
  SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id='f4519c66-4130-4e34-b053-64dba6214dcb';
  IF bridge_row.payload_json->>'output_id' IS DISTINCT FROM output_row.id::text
   OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM NEW.request_json
   OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM NEW.source_json
   OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
   OR bridge_row.payload_json->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
   OR bridge_row.payload_json->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
   OR NEW.lease_state_version<>2 OR NEW.artifact_key IS DISTINCT FROM 'generation.d55f63a980434d748a1c0862660aed30'
  THEN RAISE check_violation USING MESSAGE='562 exact output to persistence writer artifact required'; END IF;
  RETURN NEW; -- Original559 still checks actual candidate/version, full source/goal, control CAS and final clock.
 END IF;
 p_preparation:=(NEW.request_json->>'candidate_id')::uuid;
 -- Establish the common lock domain before inspecting output/gap rows.
 PERFORM item_supply_internal.private_generation_durability_attempt(p_preparation);
 SELECT j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND j.operation_key='private.generation.output.'||replace(p_preparation::text,'-','');
 output_id:=item_supply_internal.private_generation_output_committed(p_preparation,output_row.payload_json->'capture');
 IF output_id IS NULL OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM NEW.request_json
  OR output_row.payload_json->'capture'->'context'->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
  OR output_row.payload_json->'capture'->'context'->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
  OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM NEW.source_json
  OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM NEW.receipt_json
 THEN RAISE check_violation USING MESSAGE='560 exact separately committed output required before original artifact'; END IF;
 RETURN NEW; -- Original559 current goal/source/control/content and all later guards remain.
END;
$expected560$),
 ('private_initial_author_continuation_predecessor(uuid,uuid,uuid,bigint,uuid)','private_initial_author_continuation_predecessor(p_receipt uuid,p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)','public.tutor_item_supply_private_persistent_pack_journal',$expected560$
DECLARE failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=p_receipt
  AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1') THEN
  RETURN item_supply_internal.private_initial_author_persistence_gap_committed(p_receipt,p_task,p_user,p_epoch,p_scope);
 END IF;
 PERFORM item_supply_internal.private_initial_author_recovery_anchor(p_task,p_user,p_epoch,p_scope);
 SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_receipt AND journal.pack_task_id=p_task AND journal.user_id=p_user AND journal.epoch=p_epoch AND journal.scope_id=p_scope
  AND journal.record_kind='private_status' AND journal.xmin::text::bigint<>(txid_current()%4294967296) FOR UPDATE;
 IF failure_row.id IS NULL THEN RAISE check_violation USING MESSAGE='558 prior-TOP genuine predecessor failure required'; END IF;
 IF p_receipt='df0a6e8c-287a-4814-98f1-5deeb59347a3' THEN
  IF item_supply_internal.private_initial_author_failure_committed(p_receipt,p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM true
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact WHERE artifact.job_id='6691f9a2-073a-4fbc-8783-09d6ef0ca8d5')
  THEN RAISE check_violation USING MESSAGE='558 original committed 555 failure required'; END IF;
 ELSE
  IF item_supply_internal.private_initial_author_continuation_failure_committed(p_receipt,p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='558 committed same-authorization failure lineage required'; END IF;
 END IF;
 RETURN failure_row;
END;
$expected560$),
 ('private_initial_author_continuation_terminal(uuid)','private_initial_author_continuation_terminal(p_started uuid)','text',$expected560$
DECLARE requested public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 head_artifact public.tutor_item_supply_private_generation_artifacts%ROWTYPE;
 peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 attempt_key text; known_ancestor boolean:=false; bridge_head boolean:=false;
 bridge_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; completion_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT journal.* INTO requested FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_started AND journal.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
  AND journal.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND journal.epoch=1 AND journal.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
  AND journal.record_kind='private_status' AND journal.payload_json->>'schema_version'='private_native_stage_v1'
  AND journal.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' AND journal.payload_json->>'stage'='author'
  AND journal.payload_json->>'status'='started' AND journal.payload_json->'receipt_id'='null'::jsonb
  AND journal.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF requested.id IS NULL THEN RETURN NULL; END IF;
 failure_row:=item_supply_internal.private_initial_author_continuation_predecessor('df0a6e8c-287a-4814-98f1-5deeb59347a3',requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 known_ancestor:=requested.id='5ad70ab7-0441-456b-ae5e-156755a80911'
  OR (requested.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started' AND requested.id::text=failure_row.payload_json->>'started_id');
 LOOP
  -- Follow the sole deterministic successor, never timestamp ordering or arbitrary started rows.
  attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(failure_row.id::text,'-','');
  SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.approval'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF approval_row.id IS NULL THEN
   IF known_ancestor THEN
    IF failure_row.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1' THEN RETURN 'technical_gap'; END IF;
    RETURN 'failure';
   ELSE RETURN NULL; END IF;
  END IF;
  approval_row:=item_supply_internal.private_initial_author_continuation_approval(approval_row.id);
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.binding'
   AND journal.payload_json->>'approval_id'=approval_row.id::text AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  SELECT journal.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.author.started'
   AND journal.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND journal.xmin::text::bigint<>(txid_current()%4294967296);
  IF binding_row.id IS NULL OR started_row.id IS NULL THEN RETURN NULL; END IF;
  known_ancestor:=known_ancestor OR requested.id=started_row.id;
  -- C18 completion is immutable provenance; it is NOT fresh-current work permission.
  bridge_head:=false;
  IF binding_row.payload_json->>'preparation_id'='d55f63a9-8043-4d74-8a1c-0862660aed30'
   AND binding_row.payload_json->'lease'->>'job_id'='c9442831-e8d6-43b6-9367-b94875c60f36' THEN
   SELECT j.* INTO bridge_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=requested.pack_task_id
    AND j.user_id=requested.user_id AND j.epoch=requested.epoch AND j.scope_id=requested.scope_id AND j.record_kind='private_status'
    AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb' AND j.payload_json->>'output_id'='f4519c66-4130-4e34-b053-64dba6214dcb'
    AND j.payload_json->>'original_binding_id'=binding_row.id::text AND j.payload_json->>'original_started_id'=started_row.id::text;
   SELECT j.* INTO completion_row FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.pack_task_id=requested.pack_task_id
    AND j.user_id=requested.user_id AND j.epoch=requested.epoch AND j.scope_id=requested.scope_id AND j.record_kind='private_status'
    AND j.operation_key='private.persistence.phase.f4519c6641304e34b05364dba6214dcb.complete' AND j.payload_json->>'binding_id'=bridge_row.id::text;
   IF bridge_row.id IS NOT NULL AND completion_row.id IS NOT NULL THEN
    IF NOT known_ancestor OR bridge_row.payload_json->>'bound_top_xid'=pg_current_xact_id()::text
     OR completion_row.payload_json->>'completed_top_xid'=pg_current_xact_id()::text THEN RETURN NULL; END IF;
    SELECT c.* INTO completion_row FROM item_supply_internal.private_generation_persistence_phase_completed_data(bridge_row.id) c;
    SELECT a.* INTO head_artifact FROM tutor_item_supply_private_generation_artifacts a WHERE a.id=(completion_row.payload_json->>'artifact_id')::uuid;
    bridge_head:=true;
   END IF;
  END IF;
  IF bridge_head OR (EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done
   JOIN tutor_item_supply_private_persistent_pack_journal consumed ON consumed.pack_task_id=done.pack_task_id
    AND consumed.operation_key=attempt_key||'.consumed' AND consumed.payload_json->>'binding_id'=binding_row.id::text
    AND consumed.payload_json->>'started_id'=started_row.id::text
   JOIN tutor_item_supply_private_generation_artifacts artifact ON artifact.id=(done.payload_json->>'receipt_id')::uuid
    AND artifact.job_id=(binding_row.payload_json->'lease'->>'job_id')::uuid AND artifact.request_json=binding_row.payload_json->'request'
    AND artifact.lease_generation=1 AND artifact.mode='live'
   JOIN tutor_item_supply_private_candidates candidate ON candidate.id=artifact.candidate_id
    AND candidate.user_id=requested.user_id AND candidate.epoch=requested.epoch AND candidate.scope_id=requested.scope_id
    AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   JOIN tutor_item_supply_private_versions version ON version.id=artifact.version_id AND version.candidate_id=candidate.id AND version.version=1
   JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.reservation_id=(binding_row.payload_json->>'reservation_id')::uuid
    AND settlement.settlement_key='generation.'||replace(binding_row.payload_json->>'candidate_id','-','') AND settlement.sequence=1
   WHERE done.pack_task_id=requested.pack_task_id AND done.operation_key=attempt_key||'.author.result'
   AND done.payload_json->>'schema_version'='private_native_stage_v1' AND done.payload_json->>'stage'='author'
   AND done.payload_json->>'status'='committed' AND done.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND done.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   AND done.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
   AND consumed.payload_json->>'candidate_id'=binding_row.payload_json->>'candidate_id'
   AND consumed.payload_json->>'job_id'=artifact.job_id::text AND consumed.payload_json->>'reservation_id'=settlement.reservation_id::text
   AND done.xmin::text::bigint<>(txid_current()%4294967296) AND artifact.xmin::text::bigint<>(txid_current()%4294967296)
   AND consumed.xmin::text::bigint<>(txid_current()%4294967296) AND settlement.xmin::text::bigint<>(txid_current()%4294967296))
   AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed
    WHERE failed.pack_task_id=requested.pack_task_id AND failed.operation_key=attempt_key||'.failure'))
  THEN
   IF NOT known_ancestor THEN RETURN NULL; END IF;
   IF NOT bridge_head THEN
   SELECT artifact.* INTO head_artifact FROM tutor_item_supply_private_generation_artifacts artifact
    JOIN tutor_item_supply_private_persistent_pack_journal done ON done.pack_task_id=requested.pack_task_id
     AND done.operation_key=attempt_key||'.author.result' AND artifact.id=(done.payload_json->>'receipt_id')::uuid;
   END IF;
   -- Durable terminal quality is DATA, not a restored live work capability.
   -- Bind the original full validation/blind/six-role review to THIS head artifact/spec/ref.
   SELECT review.* INTO peer FROM tutor_item_supply_private_native_quality_evidence review
    JOIN tutor_item_supply_private_native_quality_evidence validation ON validation.kind='validation'
     AND (validation.user_id,validation.epoch,validation.scope_id,validation.pack_task_id,validation.slot_id,validation.root_id,validation.version_id,validation.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND validation.payload_json->>'state'='machine_verified'
     AND validation.payload_json->>'source_hash'=head_artifact.source_hash AND validation.payload_json->>'content_hash'=head_artifact.content_hash
     AND validation.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_native_quality_evidence blind ON blind.kind='blind'
     AND (blind.user_id,blind.epoch,blind.scope_id,blind.pack_task_id,blind.slot_id,blind.root_id,blind.version_id,blind.job_id)=
         (review.user_id,review.epoch,review.scope_id,review.pack_task_id,review.slot_id,review.root_id,review.version_id,review.job_id)
     AND blind.payload_json=review.payload_json->'bundle'->'blind_solve' AND blind.xmin::text::bigint<>(txid_current()%4294967296)
    JOIN tutor_item_supply_private_persistent_pack_journal review_done ON review_done.pack_task_id=review.pack_task_id
     AND review_done.user_id=review.user_id AND review_done.epoch=review.epoch AND review_done.scope_id=review.scope_id
     AND review_done.record_kind='private_status' AND review_done.payload_json->>'schema_version'='private_native_stage_v1'
     AND review_done.payload_json->>'stage'='review' AND review_done.payload_json->>'status'='committed'
     AND review_done.payload_json->>'slot_id'=review.slot_id::text AND review_done.payload_json->>'job_id'=review.job_id::text
     AND review_done.payload_json->>'receipt_id'=review.id::text AND review_done.xmin::text::bigint<>(txid_current()%4294967296)
    WHERE review.kind='review' AND review.user_id=requested.user_id AND review.epoch=requested.epoch AND review.scope_id=requested.scope_id
    AND review.pack_task_id=requested.pack_task_id AND review.slot_id='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
    AND review.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9' AND review.version_id=head_artifact.version_id
    AND review.payload_json->>'schema_version'='private_native_review_v1' AND review.payload_json->>'artifact_id'=head_artifact.id::text
    AND review.payload_json->'ref'=binding_row.payload_json->'ref'
    AND review.payload_json->'spec'->'public_template'=head_artifact.request_json->'public_template'
    AND review.payload_json->'spec'->'blueprint'=head_artifact.request_json->'blueprint'
    AND review.payload_json->'bundle'->>'state'='completed' AND review.payload_json->'bundle'->>'mode'='peer_blind'
    AND review.payload_json->'bundle'->'binding'->>'version_key'=head_artifact.version_id::text
    AND review.payload_json->'bundle'->'binding'->>'source_hash'=head_artifact.source_hash
    AND review.payload_json->'bundle'->'binding'->>'content_hash'=head_artifact.content_hash
    AND jsonb_array_length(review.payload_json->'bundle'->'reports')=6
    AND (SELECT array_agg(report->>'role' ORDER BY report->>'role') FROM jsonb_array_elements(review.payload_json->'bundle'->'reports') report)
     =ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
    AND review.checked_at<review.valid_until AND review.created_at<review.valid_until
    AND review.xmin::text::bigint<>(txid_current()%4294967296);
   IF peer.id IS NOT NULL THEN
    -- Original timeless receiver verifies committed exact original7 preparation,
    -- validation, reservation, settlement and review policy/spec/artifact binding.
    PERFORM item_supply_internal.assert_private_native_review_stage(peer);
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications publication
     JOIN tutor_item_supply_private_native_quality_evidence quality ON quality.id=publication.quality_id AND quality.kind='admission'
      AND (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)=
          (publication.user_id,publication.epoch,publication.scope_id,publication.pack_task_id,publication.slot_id,publication.root_id,publication.version_id)
      AND quality.payload_json->>'schema_version'='private_native_quality_v1'
      AND quality.payload_json->>'receipt_id'=quality.id::text AND quality.payload_json->>'version_id'=head_artifact.version_id::text
      AND quality.payload_json->>'generation_artifact_id'=head_artifact.id::text AND quality.payload_json->>'review_receipt_id'=peer.id::text
      AND quality.payload_json->'ref'=peer.payload_json->'ref' AND quality.payload_json->'spec'=peer.payload_json->'spec'
      AND quality.payload_json->'bundle'=peer.payload_json->'bundle' AND quality.payload_json->'source'=head_artifact.source_json
      AND quality.payload_json->'request'=head_artifact.request_json AND quality.payload_json->'source_receipts'=head_artifact.receipt_json->'sources'
      AND quality.payload_json->'evaluation'->>'disposition'='eligible_internal' AND quality.payload_json->'evaluation'->'publication_enabled'='false'::jsonb
      AND quality.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_validation ON admitted_validation.id=(quality.payload_json->>'validation_receipt_id')::uuid
      AND admitted_validation.kind='validation' AND admitted_validation.payload_json=quality.payload_json->'validation'
      AND (admitted_validation.user_id,admitted_validation.epoch,admitted_validation.scope_id,admitted_validation.pack_task_id,admitted_validation.slot_id,admitted_validation.root_id,admitted_validation.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_validation.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_native_quality_evidence admitted_blind ON admitted_blind.id=(quality.payload_json->>'blind_receipt_id')::uuid
      AND admitted_blind.kind='blind' AND admitted_blind.payload_json=peer.payload_json->'bundle'->'blind_solve'
      AND (admitted_blind.user_id,admitted_blind.epoch,admitted_blind.scope_id,admitted_blind.pack_task_id,admitted_blind.slot_id,admitted_blind.root_id,admitted_blind.version_id)=
          (quality.user_id,quality.epoch,quality.scope_id,quality.pack_task_id,quality.slot_id,quality.root_id,quality.version_id)
      AND admitted_blind.xmin::text::bigint<>(txid_current()%4294967296)
     JOIN tutor_item_supply_private_versions version ON version.id=publication.version_id AND version.user_id=publication.user_id AND version.epoch=publication.epoch
      AND version.public_json=head_artifact.source_json->'public' AND version.private_json=head_artifact.source_json->'private'
     JOIN tutor_exercise_versions exercise ON exercise.id=publication.exercise_version_id AND exercise.source_kind='registered_author'
      AND exercise.content_hash=publication.payload_json->>'exercise_content_hash'
      AND exercise.exercise_key=head_artifact.source_json->'public'->>'item_key' AND exercise.version=head_artifact.source_json->'public'->>'version'
     JOIN tutor_exercise_private_rubrics rubric ON rubric.exercise_version_id=exercise.id AND rubric.rubric_hash=publication.payload_json->>'rubric_hash'
     WHERE publication.pack_task_id=requested.pack_task_id AND publication.user_id=requested.user_id AND publication.epoch=requested.epoch
     AND publication.scope_id=requested.scope_id AND publication.slot_id=peer.slot_id AND publication.root_id=peer.root_id
     AND publication.version_id=head_artifact.version_id AND publication.state='published'
     AND publication.payload_json->>'schema_version'='private_native_publication_v1'
     AND publication.payload_json->>'publication_id'=publication.id::text AND publication.payload_json->>'quality_id'=quality.id::text
     AND publication.payload_json->>'quality_hash'=quality.payload_hash AND publication.payload_json->'ref'=quality.payload_json->'ref'
     AND publication.payload_json->>'source_hash'=item_supply_internal.snapshot_hash(quality.payload_json->'source')
     AND publication.payload_json->>'content_hash'=peer.payload_json->'bundle'->'binding'->>'content_hash'
     AND publication.payload_json->>'item_handle'=version.handle AND publication.content_json->>'item_handle'=version.handle
     AND publication.xmin::text::bigint<>(txid_current()%4294967296)
     AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_publications successor
      WHERE successor.version_id=publication.version_id AND successor.user_id=publication.user_id AND successor.epoch=publication.epoch
      AND successor.state_version>publication.state_version)) THEN RETURN 'published'; END IF;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') report
     WHERE report->>'verdict'<>'approved' OR EXISTS(SELECT 1 FROM jsonb_array_elements(report->'findings') finding
      WHERE finding->>'blocking'='true' OR finding->>'severity' IN('major','critical')
      OR finding->>'safe_code' IN('deterministic_failure','security','unique_answer','rubric_mismatch','data_leakage','adversarial_exploit')))
    THEN RETURN 'review_failed'; END IF;
   END IF;
   RETURN 'artifact';
  END IF;
  SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=requested.pack_task_id AND journal.operation_key=attempt_key||'.failure';
  IF failure_row.id IS NULL AND binding_row.id='af059dcf-4f2c-4ed2-80d2-b5c109dcf1a6'::uuid THEN
   SELECT j.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal j
    WHERE j.pack_task_id=requested.pack_task_id AND j.operation_key='private.generation.gap.af059dcf4f2c4ed280d2b5c109dcf1a6'
    AND j.payload_json->>'schema_version'='private_initial_author_persistence_gap_v1'
    AND j.payload_json->>'binding_id'=binding_row.id::text;
  END IF;
  IF failure_row.id IS NULL THEN RETURN NULL; END IF;
  failure_row:=item_supply_internal.private_initial_author_continuation_predecessor(failure_row.id,requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 END LOOP;
END;
$expected560$)
 ) AS expected(signature,header,result_type,body) LOOP
  SELECT array_agg(split_part(btrim(a),' ',1) ORDER BY n) INTO names
   FROM unnest(string_to_array(substring(spec.header FROM '\((.*)\)$'),',')) WITH ORDINALITY args(a,n) WHERE btrim(a)<>'';
  SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.'||spec.signature);
  IF NOT FOUND OR actual.prosrc IS DISTINCT FROM spec.body OR NOT actual.prosecdef OR actual.prokind<>'f'
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.prorettype IS DISTINCT FROM to_regtype(spec.result_type) OR actual.proargnames IS DISTINCT FROM names
   OR actual.provolatile<>'v' OR actual.proretset OR actual.proisstrict OR actual.proleakproof OR actual.proparallel<>'u'
   OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0 OR actual.provariadic<>0
   OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
   OR actual.probin IS NOT NULL OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
   OR actual.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql') THEN RETURN false; END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','private_generation_durability_insert','enforce_private_generation_durability_insert'),
  ('tutor_item_supply_private_generation_artifacts','private_generation_durability_artifact','enforce_private_generation_durability_artifact')
 ) AS expected(table_name,trigger_name,function_name) LOOP
  SELECT t.* INTO actual FROM pg_trigger t WHERE t.tgrelid=to_regclass('public.'||tr.table_name) AND t.tgname=tr.trigger_name;
  IF NOT FOUND OR actual.tgfoid IS DISTINCT FROM to_regprocedure('item_supply_internal.'||tr.function_name||'()')
   OR actual.tgtype<>7 OR actual.tgenabled<>'O' OR actual.tgisinternal OR actual.tgdeferrable OR actual.tginitdeferred
   OR actual.tgnargs<>0 OR actual.tgqual IS NOT NULL OR actual.tgattr::text<>'' OR actual.tgargs<>''::bytea
   OR actual.tgparentid<>0 OR actual.tgconstrrelid<>0 OR actual.tgconstrindid<>0 OR actual.tgconstraint<>0
   OR actual.tgoldtable IS NOT NULL OR actual.tgnewtable IS NOT NULL THEN RETURN false; END IF;
 END LOOP;
 RETURN true;
END;
$newready562$;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.private_generation_durability_ready()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_generation_durability_ready' OR actual.prosecdef IS DISTINCT FROM true OR actual.prokind<>'f'
   OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
   OR actual.prorettype IS DISTINCT FROM to_regtype('pg_catalog.bool') OR actual.proargnames IS DISTINCT FROM NULL::text[]
   OR actual.pronargs IS DISTINCT FROM COALESCE(cardinality(NULL::text[]),0)
   OR actual.proretset IS DISTINCT FROM false OR actual.provolatile<>'v' OR actual.proisstrict OR actual.proleakproof OR actual.proparallel<>'u'
   OR actual.procost<>100 OR actual.prorows IS DISTINCT FROM (CASE WHEN false THEN 1000::real ELSE 0::real END)
   OR actual.prosupport<>0 OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL
   OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.probin IS NOT NULL
   OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL OR actual.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
 THEN RAISE check_violation USING MESSAGE='562 original ready receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body THEN RAISE check_violation USING MESSAGE='562 original ready receiver body changed'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='562 original ready receiver framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc') OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='562 ready receiver metadata/OID/owner/ACL/body changed'; END IF;
END;
$patchready562$;
