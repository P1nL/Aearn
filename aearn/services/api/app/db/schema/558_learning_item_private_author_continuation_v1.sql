-- C14: append-only successors of the fixed genuine initial-author failure.
-- Historical failure proofs do NOT revalidate expired lease/SOURCE; only NEW attempts do.
-- One deterministic successor per committed failure, original registry/runtime/quality owners.
-- Caller owns transaction; no old row/SQL/TTL/history rewriting and no PUBLIC grant.
DO $install558$
DECLARE spec record; prior record; expected_names text[]; tr record;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='558 original isolated writable transaction required'; END IF;
 FOR spec IN SELECT * FROM (VALUES
 ('private_initial_author_continuation_failure_committed(uuid,uuid,uuid,bigint,uuid)', 'private_initial_author_continuation_failure_committed(p_receipt uuid,p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)', 'boolean', $src$
DECLARE failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; attempt_key text;
BEGIN
 SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_receipt AND journal.pack_task_id=p_task AND journal.user_id=p_user AND journal.epoch=p_epoch AND journal.scope_id=p_scope
  AND journal.record_kind='private_status' AND journal.payload_json->>'schema_version'='private_initial_author_continuation_failure_v1'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF failure_row.id IS NULL THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_initial_author_recovery_anchor(p_task,p_user,p_epoch,p_scope);
 SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=(failure_row.payload_json->>'binding_id')::uuid AND journal.pack_task_id=p_task
  AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF binding_row.id IS NULL THEN RETURN false; END IF;
 -- Historical identity/committed lineage only: NEVER call bound/source/current lease here.
 approval_row:=item_supply_internal.private_initial_author_continuation_approval((binding_row.payload_json->>'approval_id')::uuid);
 attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(approval_row.payload_json->>'predecessor_failure_id','-','');
 IF (approval_row.pack_task_id,approval_row.user_id,approval_row.epoch,approval_row.scope_id) IS DISTINCT FROM (p_task,p_user,p_epoch,p_scope)
  OR binding_row.operation_key IS DISTINCT FROM attempt_key||'.binding' OR failure_row.operation_key IS DISTINCT FROM attempt_key||'.failure'
  OR item_supply_internal.snapshot_keys(failure_row.payload_json,ARRAY['schema_version','binding_id','consumed_id','started_id','job_id','candidate_id','reservation_id','settlement_id','state','safe_reason','receipt','source_origin_id','recorded_at']) IS DISTINCT FROM true
  OR COALESCE(failure_row.payload_json->>'state' IN('blocked','failed'),false) IS DISTINCT FROM true
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact WHERE artifact.job_id=(binding_row.payload_json->'lease'->>'job_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done WHERE done.pack_task_id=p_task AND done.operation_key=attempt_key||'.author.result')
 THEN RETURN false; END IF;
 RETURN EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal consumed
  JOIN tutor_item_supply_private_persistent_pack_journal started ON started.id=(failure_row.payload_json->>'started_id')::uuid
  JOIN tutor_item_supply_private_persistent_pack_journal claim ON claim.id=(binding_row.payload_json->>'claim_id')::uuid
  JOIN tutor_item_supply_private_persistent_pack_journal aux ON aux.id=(binding_row.payload_json->>'preparation_id')::uuid
  JOIN tutor_item_supply_private_reservations reservation ON reservation.id=(failure_row.payload_json->>'reservation_id')::uuid
  JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.id=(failure_row.payload_json->>'settlement_id')::uuid
  WHERE consumed.id=(failure_row.payload_json->>'consumed_id')::uuid AND consumed.pack_task_id=p_task
  AND consumed.operation_key=attempt_key||'.consumed' AND consumed.payload_json->>'schema_version'='private_initial_author_continuation_consumed_v1'
  AND consumed.payload_json->>'binding_id'=binding_row.id::text AND consumed.payload_json->>'started_id'=started.id::text
  AND consumed.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
  AND consumed.payload_json->>'candidate_id'=binding_row.payload_json->>'candidate_id'
  AND consumed.payload_json->>'reservation_id'=reservation.id::text
  AND started.pack_task_id=p_task AND started.operation_key=attempt_key||'.author.started'
  AND started.payload_json->>'schema_version'='private_native_stage_v1' AND started.payload_json->>'status'='started'
  AND started.payload_json->>'stage'='author' AND started.payload_json->>'receipt_id' IS NULL
  AND started.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  AND started.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
  AND started.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
  AND claim.pack_task_id=p_task AND claim.operation_key=attempt_key||'.claim'
  AND claim.payload_json->>'approval_id'=approval_row.id::text AND claim.payload_json->>'job_id'=reservation.job_id::text
  AND aux.pack_task_id=p_task AND aux.record_kind='private_attachment' AND aux.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND aux.id::text=binding_row.payload_json->>'candidate_id' AND aux.payload_json->>'reservation_id'=reservation.id::text
  AND aux.payload_json->>'job_id'=reservation.job_id::text AND aux.payload_json->'request'->>'schema_version'='private_native_initial_author_v1'
  AND aux.payload_json->'request'->'request'=binding_row.payload_json->'request' AND aux.payload_json->'request'->'ref'=binding_row.payload_json->'ref'
  AND failure_row.payload_json->>'candidate_id'=binding_row.payload_json->>'candidate_id'
  AND failure_row.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
  AND reservation.job_id=(binding_row.payload_json->'lease'->>'job_id')::uuid AND reservation.lease_generation=1
  AND reservation.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  AND settlement.reservation_id=reservation.id AND settlement.sequence=1
  AND settlement.settlement_key='generation.'||replace(binding_row.payload_json->>'candidate_id','-','')
  AND consumed.xmin::text::bigint<>(txid_current()%4294967296) AND started.xmin::text::bigint<>(txid_current()%4294967296)
  AND claim.xmin::text::bigint<>(txid_current()%4294967296) AND aux.xmin::text::bigint<>(txid_current()%4294967296)
  AND EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal approval
   WHERE approval.id=approval_row.id AND approval.xmin::text::bigint<>(txid_current()%4294967296))
  AND settlement.xmin::text::bigint<>(txid_current()%4294967296));
END;
$src$),
 ('private_initial_author_continuation_predecessor(uuid,uuid,uuid,bigint,uuid)', 'private_initial_author_continuation_predecessor(p_receipt uuid,p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', $src$
DECLARE failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
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
$src$),
 ('private_initial_author_continuation_approval(uuid)', 'private_initial_author_continuation_approval(p_approval uuid)', 'public.tutor_item_supply_private_persistent_pack_journal', $src$
DECLARE approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; body jsonb; stamp timestamptz; predecessor_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 PERFORM item_supply_internal.private_initial_author_recovery_anchor('6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587');
 SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_approval AND journal.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND journal.record_kind='private_status' FOR UPDATE;
 IF approval_row.id IS NULL THEN RAISE check_violation USING MESSAGE='558 exact continuation approval required'; END IF;
 body:=approval_row.payload_json; stamp:=clock_timestamp();
 IF body->>'schema_version' IS DISTINCT FROM 'private_initial_author_continuation_approval_v1'
  OR (approval_row.user_id,approval_row.epoch,approval_row.scope_id) IS DISTINCT FROM
   ('a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid)
  OR item_supply_internal.snapshot_keys(body,ARRAY['schema_version','authorization_key','predecessor_failure_id','old_started_id','old_job_id','old_candidate_id','slot_id','business_item_id','root_id','mapping_receipt_id','item_key','version','candidate_key','storage_version','issued_at']) IS DISTINCT FROM true
   OR body->>'authorization_key' IS DISTINCT FROM 'p7.private.initial-author.continuation.20261016'
   OR body->>'old_started_id' IS DISTINCT FROM '5ad70ab7-0441-456b-ae5e-156755a80911'
   OR body->>'old_job_id' IS DISTINCT FROM '487b12c4-f98a-41c9-a21b-abb9243a28dd'
   OR body->>'old_candidate_id' IS DISTINCT FROM '17458037-ad0c-46d8-8c3b-a621bee386f1'
   OR body->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   OR body->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
   OR body->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
   OR body->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
   OR body->>'item_key' IS DISTINCT FROM 'private-native.7e9c44445b1653c1ad8b39b402e5aa51'
   OR body->>'candidate_key' IS DISTINCT FROM 'private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   OR body->>'version' IS DISTINCT FROM 'v1' OR body->'storage_version' IS DISTINCT FROM '1'::jsonb
   OR jsonb_typeof(body->'issued_at') IS DISTINCT FROM 'string'
   OR jsonb_typeof(body->'predecessor_failure_id') IS DISTINCT FROM 'string'
   OR (body->>'predecessor_failure_id')::uuid::text IS DISTINCT FROM body->>'predecessor_failure_id'
   OR (body->>'issued_at')::timestamptz>stamp
  OR approval_row.operation_key IS DISTINCT FROM 'p7.private.initial-author.continuation.20261016.'||replace(body->>'predecessor_failure_id','-','')||'.approval'
 THEN RAISE check_violation USING MESSAGE='558 exact approved predecessor/initial scope required'; END IF;
 predecessor_row:=item_supply_internal.private_initial_author_continuation_predecessor((body->>'predecessor_failure_id')::uuid,
  approval_row.pack_task_id,approval_row.user_id,approval_row.epoch,approval_row.scope_id);
 RETURN approval_row;
END;
$src$),
 ('private_initial_author_continuation_bound(uuid,uuid,boolean)', 'private_initial_author_continuation_bound(p_binding uuid,p_origin uuid,p_committed boolean)', 'public.tutor_item_supply_private_persistent_pack_journal', $src$
DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 claim_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 aux_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 source_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 attempt_key text; body jsonb; lease_json jsonb; stamp timestamptz; source_end timestamptz; reservation_row record;
BEGIN
 SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_binding AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1'
  AND journal.record_kind='private_status';
 IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='558 original recovery binding required'; END IF;
 PERFORM item_supply_internal.private_initial_author_recovery_anchor(binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id);
 body:=binding_row.payload_json; lease_json:=body->'lease';
 approval_row:=item_supply_internal.private_initial_author_continuation_approval((body->>'approval_id')::uuid);
 attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(approval_row.payload_json->>'predecessor_failure_id','-','');
 IF binding_row.operation_key IS DISTINCT FROM attempt_key||'.binding' THEN RAISE check_violation USING MESSAGE='558 exact predecessor binding bucket required'; END IF;
 SELECT journal.* INTO claim_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=(body->>'claim_id')::uuid AND journal.operation_key=attempt_key||'.claim';
 SELECT journal.* INTO aux_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=(body->>'preparation_id')::uuid AND journal.pack_task_id=binding_row.pack_task_id AND journal.record_kind='private_attachment';
 SELECT control.* INTO ctrl FROM tutor_item_supply_private_job_controls control WHERE control.job_id=(lease_json->>'job_id')::uuid FOR UPDATE;
 SELECT batch.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches batch
  JOIN tutor_item_supply_private_development_model_accounting_jobs mapping ON mapping.batch_id=batch.id
  WHERE mapping.job_id=ctrl.job_id AND mapping.user_id=binding_row.user_id AND mapping.epoch=binding_row.epoch
  AND mapping.scope_id=binding_row.scope_id AND mapping.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  AND mapping.lease_generation=ctrl.lease_generation AND mapping.lease_owner=ctrl.lease_owner
  AND mapping.profile_hash=lease_json->'profile'->>'profile_hash';
 SELECT reservation.* INTO reservation_row FROM tutor_item_supply_private_reservations reservation
  WHERE reservation.id=(body->>'reservation_id')::uuid AND reservation.job_id=ctrl.job_id AND reservation.lease_generation=1;
 source_end:=item_supply_internal.private_initial_author_recovery_source(p_origin);
 SELECT journal.* INTO source_row FROM tutor_item_supply_private_persistent_pack_journal journal WHERE journal.id=p_origin;
 IF (approval_row.pack_task_id,approval_row.user_id,approval_row.epoch,approval_row.scope_id) IS DISTINCT FROM
     (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id)
  OR approval_row.id IS NULL OR claim_row.id IS NULL OR aux_row.id IS NULL OR ctrl.id IS NULL OR batch_row.id IS NULL OR reservation_row.id IS NULL
  OR (claim_row.pack_task_id,claim_row.user_id,claim_row.epoch,claim_row.scope_id) IS DISTINCT FROM
     (binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id)
  OR claim_row.payload_json->>'approval_id' IS DISTINCT FROM approval_row.id::text
  OR claim_row.payload_json->>'job_id' IS DISTINCT FROM ctrl.job_id::text OR claim_row.payload_json->>'batch_id' IS DISTINCT FROM batch_row.id::text
  OR body->>'candidate_id' IS DISTINCT FROM body->>'preparation_id'
  OR aux_row.payload_json->>'job_id' IS DISTINCT FROM ctrl.job_id::text
  OR aux_row.payload_json->>'reservation_id' IS DISTINCT FROM body->>'reservation_id'
  OR aux_row.payload_json->'request'->>'schema_version' IS DISTINCT FROM 'private_native_initial_author_v1'
  OR aux_row.payload_json->'request'->'ref' IS DISTINCT FROM body->'ref'
  OR aux_row.payload_json->'request'->'request' IS DISTINCT FROM body->'request'
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal phase
   WHERE phase.pack_task_id=binding_row.pack_task_id AND phase.record_kind='phase'
   AND phase.payload_json->>'schema_version'='private_native_phase_v1'
   AND phase.payload_json->>'job_id'=ctrl.job_id::text AND phase.payload_json->'ref'=body->'ref' AND phase.payload_json->'lease'=lease_json)
  OR reservation_row.window_id IS DISTINCT FROM batch_row.window_id
  OR body->'request'->>'candidate_id' IS DISTINCT FROM body->>'candidate_id'
  OR body->'request'->>'item_key' IS DISTINCT FROM 'private-native.7e9c44445b1653c1ad8b39b402e5aa51'
  OR body->'request'->>'version' IS DISTINCT FROM 'v1' OR body->'request'->'profile' IS DISTINCT FROM lease_json->'profile'
  OR body->'request'->'limits'->>'max_input_bytes' IS DISTINCT FROM '262144'
  OR body->'request'->'limits'->>'max_output_tokens' IS DISTINCT FROM '61440'
  OR body->'request'->'limits'->>'max_output_bytes' IS DISTINCT FROM '262144'
  OR source_row.payload_json->'public_materials' IS DISTINCT FROM body->'request'->'materials'
  OR jsonb_array_length(body->'sources') IS DISTINCT FROM jsonb_array_length(body->'request'->'materials')
  OR (SELECT jsonb_agg(value-'checked_at_iso' ORDER BY ord) FROM jsonb_array_elements(body->'sources') WITH ORDINALITY AS receipt(value,ord))
    IS DISTINCT FROM (SELECT jsonb_agg(value-'checked_at_iso' ORDER BY ord) FROM jsonb_array_elements(source_row.payload_json->'public_receipts') WITH ORDINALITY AS receipt(value,ord))
  OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.breaker_open
  OR ctrl.lease_owner IS DISTINCT FROM lease_json->>'lease_owner' OR ctrl.state_version<(lease_json->>'state_version')::bigint
  OR ctrl.parent_deadline IS DISTINCT FROM (lease_json->>'parent_deadline')::timestamptz
  OR ctrl.profile_snapshot_json->'profile' IS DISTINCT FROM lease_json->'profile'
  OR ctrl.profile_snapshot_json->'retry_policy' IS DISTINCT FROM lease_json->'retry_policy'
  OR item_supply_internal.private_pack_slot_current(binding_row.pack_task_id,'f2b5a6dd-97d2-52dd-8962-68962f6ea76c',
   '7e9c4444-5b16-53c1-ad8b-39b402e5aa51','aaaf99e5-4530-4319-bb1a-0fe6d84020f9',binding_row.user_id,binding_row.epoch::bigint,binding_row.scope_id,ctrl.job_id) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='558 exact original prepared/current lease/source/budget binding required'; END IF;
 IF p_committed AND (EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.id IN(binding_row.id,approval_row.id,claim_row.id) AND journal.xmin::text::bigint=(txid_current()%4294967296))
  OR item_supply_internal.private_pack_auxiliary_committed(binding_row.pack_task_id,aux_row.id) IS DISTINCT FROM true)
 THEN RAISE check_violation USING MESSAGE='558 prior-TOP committed original preparation required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 source_end:=LEAST(source_end,item_supply_internal.private_initial_author_recovery_source(p_origin));
 stamp:=clock_timestamp();
 IF stamp>=LEAST(source_end,ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,
  (body->>'valid_until')::timestamptz,(lease_json->>'expires_at')::timestamptz,
  (lease_json->'profile'->>'bound_at')::timestamptz+(lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='558 postwait current bound expired'; END IF;
 RETURN binding_row;
END;
$src$),
 ('private_initial_author_continuation_first_claim(uuid,uuid,uuid,uuid,text)', 'private_initial_author_continuation_first_claim(p_approval uuid,p_job uuid,p_batch uuid,p_origin uuid,p_lease_owner text)', 'public.tutor_item_supply_private_job_controls', $src$
DECLARE approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 stamp timestamptz; source_end timestamptz; body jsonb; attempt_key text;
BEGIN
 task_row:=item_supply_internal.private_initial_author_recovery_anchor('6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587');
 approval_row:=item_supply_internal.private_initial_author_continuation_approval(p_approval);
 attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(approval_row.payload_json->>'predecessor_failure_id','-','');
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact
   WHERE artifact.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND artifact.epoch=1
   AND artifact.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
   AND artifact.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates candidate WHERE candidate.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
   AND candidate.epoch=1 AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
 THEN RAISE check_violation USING MESSAGE='558 initial artifact already exists, use original quality/revision'; END IF;
 IF approval_row.id IS NULL OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id=task_row.id AND journal.operation_key IN(attempt_key||'.claim',attempt_key||'.binding',attempt_key||'.consumed'))
 THEN RAISE check_violation USING MESSAGE='558 recovery already allocated, no second claim'; END IF;
 SELECT job.* INTO job_row FROM tutor_item_supply_private_jobs job WHERE job.id=p_job;
 SELECT control.* INTO ctrl FROM tutor_item_supply_private_job_controls control WHERE control.job_id=p_job FOR UPDATE;
 SELECT batch.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches batch WHERE batch.id=p_batch;
 SELECT profile.* INTO profile_row FROM tutor_item_supply_parameter_profiles profile WHERE profile.id=ctrl.profile_id;
 source_end:=item_supply_internal.private_initial_author_recovery_source(p_origin);
 IF job_row.id IS NULL OR ctrl.id IS NULL OR batch_row.id IS NULL OR profile_row.id IS NULL
  OR (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id) IS DISTINCT FROM
   (task_row.user_id,task_row.epoch,task_row.scope_id,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
  OR job_row.parent_job_id IS NOT NULL
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_jobs job WHERE job.id=p_job AND job.xmin::text::bigint=(txid_current()%4294967296))
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_job_controls control WHERE control.id=ctrl.id AND control.xmin::text::bigint=(txid_current()%4294967296))
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_parameter_profiles profile WHERE profile.id=profile_row.id AND profile.xmin::text::bigint=(txid_current()%4294967296))
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_batches batch WHERE batch.id=p_batch AND batch.xmin::text::bigint=(txid_current()%4294967296))
  OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM (job_row.user_id,job_row.epoch,job_row.scope_id,job_row.root_id)
  OR ctrl.state IS DISTINCT FROM 'queued' OR ctrl.lease_generation<>0 OR ctrl.attempt_count<>0 OR ctrl.breaker_open
  OR ctrl.profile_snapshot_json->'retry_policy'->>'max_transient_attempts' IS DISTINCT FROM '1'
  OR ctrl.profile_snapshot_json->'profile'->>'profile_hash' IS DISTINCT FROM profile_row.profile_hash
  OR ctrl.profile_snapshot_json->'profile'->'values'->>'request_timeout_ms' IS DISTINCT FROM '100000'
  OR profile_row.profile_json->'profile_key'->>'provider' IS DISTINCT FROM 'deepseek'
  OR profile_row.profile_json->'profile_key'->>'model_version' IS DISTINCT FROM 'deepseek-flash'
  OR p_lease_owner IS DISTINCT FROM 'private.initial.author.continuation.'||replace(p_approval::text,'-','')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations reservation WHERE reservation.job_id=p_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints checkpoint WHERE checkpoint.job_id=p_job)
  OR ctrl.parent_deadline>LEAST(source_end,batch_row.valid_until)
 THEN RAISE check_violation USING MESSAGE='558 fresh exact NEW first-claim profile/batch/control required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 stamp:=clock_timestamp();
 IF ctrl.available_at>stamp OR stamp+interval '100 seconds'>=LEAST(source_end,batch_row.valid_until,ctrl.parent_deadline)
 THEN RAISE check_violation USING MESSAGE='558 first-claim remaining request bound insufficient'; END IF;
 UPDATE tutor_item_supply_private_job_controls control SET state='leased',state_version=control.state_version+1,
  lease_generation=1,attempt_count=1,lease_owner=p_lease_owner,lease_expires_at=LEAST(control.parent_deadline,stamp+interval '3600 seconds'),updated_at=stamp
  WHERE control.id=ctrl.id AND control.state_version=ctrl.state_version RETURNING control.* INTO ctrl;
 body:=jsonb_build_object('schema_version','private_initial_author_continuation_claim_v1','approval_id',p_approval,'job_id',p_job,
  'batch_id',p_batch,'window_id',batch_row.window_id,'profile_hash',profile_row.profile_hash,'lease_owner',p_lease_owner,
  'generation',1,'attempt_count',1,'parent_deadline',ctrl.parent_deadline,'source_origin_id',p_origin,'claimed_at',stamp);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
  VALUES(gen_random_uuid(),task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id,'private_status',
   attempt_key||'.claim',task_row.intent_hash,body);
 RETURN ctrl;
END;
$src$),
 ('private_initial_author_continuation_consume(uuid,uuid)', 'private_initial_author_continuation_consume(p_binding uuid,p_origin uuid)', 'uuid', $src$
DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 identity uuid:=gen_random_uuid(); stamp timestamptz; attempt_key text; approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 binding_row:=item_supply_internal.private_initial_author_continuation_bound(p_binding,p_origin,true);
 approval_row:=item_supply_internal.private_initial_author_continuation_approval((binding_row.payload_json->>'approval_id')::uuid);
 attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(approval_row.payload_json->>'predecessor_failure_id','-','');
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact
   WHERE artifact.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND artifact.epoch=1
   AND artifact.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
   AND artifact.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates candidate WHERE candidate.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
   AND candidate.epoch=1 AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
 THEN RAISE check_violation USING MESSAGE='558 initial artifact already exists, use original quality/revision'; END IF;
 SELECT journal.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id=binding_row.pack_task_id AND journal.operation_key=attempt_key||'.author.started'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF started_row.id IS NULL OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id=binding_row.pack_task_id AND journal.operation_key IN
   (attempt_key||'.consumed',attempt_key||'.failure',attempt_key||'.author.result'))
 THEN RAISE check_violation USING MESSAGE='558 once-only committed original author dispatch required'; END IF;
 stamp:=clock_timestamp();
 IF stamp+((binding_row.payload_json->'request'->'profile'->'values'->>'request_timeout_ms')::bigint*interval '1 millisecond')
   >=LEAST((binding_row.payload_json->>'valid_until')::timestamptz,item_supply_internal.private_initial_author_recovery_source(p_origin))
 THEN RAISE check_violation USING MESSAGE='558 complete formal request no longer fits'; END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,'private_status',
  attempt_key||'.consumed',binding_row.intent_hash,
  jsonb_build_object('schema_version','private_initial_author_continuation_consumed_v1','binding_id',binding_row.id,
   'job_id',binding_row.payload_json->'lease'->>'job_id','candidate_id',binding_row.payload_json->>'candidate_id',
   'reservation_id',binding_row.payload_json->>'reservation_id','started_id',started_row.id,'source_origin_id',p_origin,'consumed_at',stamp));
 RETURN identity;
END;
$src$),
 ('enforce_private_initial_author_continuation_insert()', 'enforce_private_initial_author_continuation_insert()', 'trigger', $src$
DECLARE body jsonb:=NEW.payload_json; protocol text:=body->>'schema_version'; suffix text; attempt_key text; predecessor_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; stamp timestamptz;
 task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 consumed_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 claim_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 origin_id uuid; identity uuid; valid boolean;
BEGIN
 IF COALESCE(protocol NOT IN('private_initial_author_continuation_approval_v1','private_initial_author_continuation_claim_v1',
  'private_initial_author_continuation_binding_v1','private_initial_author_continuation_consumed_v1','private_initial_author_continuation_failure_v1'),true)
  AND NEW.operation_key NOT LIKE 'p7.private.initial-author.continuation.20261016.%' THEN RETURN NEW; END IF;
 attempt_key:=regexp_replace(NEW.operation_key,'\.(approval|claim|binding|consumed|failure|author\.started|author\.result)$','');
 task_row:=item_supply_internal.private_initial_author_recovery_anchor(NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id);
 IF NEW.record_kind IS DISTINCT FROM 'private_status' OR NEW.intent_hash IS DISTINCT FROM task_row.intent_hash
 THEN RAISE check_violation USING MESSAGE='558 exact original PRIVATE journal namespace required'; END IF;
 stamp:=clock_timestamp();
 IF protocol='private_initial_author_continuation_approval_v1' THEN
  suffix:='approval';
  IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','authorization_key','predecessor_failure_id','old_started_id','old_job_id','old_candidate_id','slot_id','business_item_id','root_id','mapping_receipt_id','item_key','version','candidate_key','storage_version','issued_at']) IS DISTINCT FROM true
   OR body->>'authorization_key' IS DISTINCT FROM 'p7.private.initial-author.continuation.20261016'
   OR body->>'old_started_id' IS DISTINCT FROM '5ad70ab7-0441-456b-ae5e-156755a80911'
   OR body->>'old_job_id' IS DISTINCT FROM '487b12c4-f98a-41c9-a21b-abb9243a28dd'
   OR body->>'old_candidate_id' IS DISTINCT FROM '17458037-ad0c-46d8-8c3b-a621bee386f1'
   OR body->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   OR body->>'business_item_id' IS DISTINCT FROM '7e9c4444-5b16-53c1-ad8b-39b402e5aa51'
   OR body->>'root_id' IS DISTINCT FROM 'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
   OR body->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
   OR body->>'item_key' IS DISTINCT FROM 'private-native.7e9c44445b1653c1ad8b39b402e5aa51'
   OR body->>'candidate_key' IS DISTINCT FROM 'private.native.7e9c44445b1653c1ad8b39b402e5aa51'
   OR body->>'version' IS DISTINCT FROM 'v1' OR body->'storage_version' IS DISTINCT FROM '1'::jsonb
   OR jsonb_typeof(body->'issued_at') IS DISTINCT FROM 'string'
   OR jsonb_typeof(body->'predecessor_failure_id') IS DISTINCT FROM 'string'
   OR (body->>'predecessor_failure_id')::uuid::text IS DISTINCT FROM body->>'predecessor_failure_id'
   OR (body->>'issued_at')::timestamptz>stamp
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates candidate WHERE candidate.user_id=NEW.user_id
    AND candidate.epoch=NEW.epoch AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
  THEN RAISE check_violation USING MESSAGE='558 exact directly approved NEW initial version required'; END IF;
  predecessor_row:=item_supply_internal.private_initial_author_continuation_predecessor((body->>'predecessor_failure_id')::uuid,NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id);
  attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(predecessor_row.id::text,'-','');
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact
   WHERE artifact.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND artifact.epoch=1
   AND artifact.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
   AND artifact.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates candidate WHERE candidate.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
   AND candidate.epoch=1 AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
  THEN RAISE check_violation USING MESSAGE='558 initial artifact already exists, use original quality/revision'; END IF;
 ELSE
  SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key=attempt_key||'.approval' FOR UPDATE;
  IF approval_row.id IS NULL THEN RAISE check_violation USING MESSAGE='558 original PRIVATE approval required'; END IF;
  approval_row:=item_supply_internal.private_initial_author_continuation_approval(approval_row.id);
  IF protocol='private_initial_author_continuation_claim_v1' THEN
   suffix:='claim';
   SELECT control.* INTO ctrl FROM tutor_item_supply_private_job_controls control WHERE control.job_id=(body->>'job_id')::uuid FOR UPDATE;
   SELECT batch.* INTO batch_row FROM tutor_item_supply_private_development_model_accounting_batches batch WHERE batch.id=(body->>'batch_id')::uuid;
   PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
   PERFORM item_supply_internal.private_initial_author_recovery_source((body->>'source_origin_id')::uuid);
   IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','approval_id','job_id','batch_id','window_id','profile_hash','lease_owner','generation','attempt_count','parent_deadline','source_origin_id','claimed_at']) IS DISTINCT FROM true
    OR body->>'approval_id' IS DISTINCT FROM approval_row.id::text OR ctrl.id IS NULL OR batch_row.id IS NULL
    OR (ctrl.user_id,ctrl.epoch,ctrl.scope_id) IS DISTINCT FROM (NEW.user_id,NEW.epoch,NEW.scope_id)
    OR ctrl.lease_generation<>1 OR ctrl.attempt_count<>1 OR ctrl.state IS DISTINCT FROM 'leased' OR ctrl.breaker_open
    OR ctrl.lease_owner IS DISTINCT FROM body->>'lease_owner' OR body->'generation' IS DISTINCT FROM '1'::jsonb OR body->'attempt_count' IS DISTINCT FROM '1'::jsonb
    OR body->>'lease_owner' IS DISTINCT FROM 'private.initial.author.continuation.'||replace(approval_row.id::text,'-','')
    OR (batch_row.user_id,batch_row.epoch,batch_row.scope_id,batch_row.root_id) IS DISTINCT FROM
     (NEW.user_id,NEW.epoch::bigint,NEW.scope_id,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9'::uuid)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_development_model_accounting_batches batch
     WHERE batch.id=batch_row.id AND batch.xmin::text::bigint=(txid_current()%4294967296))
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_job_controls control WHERE control.id=ctrl.id
     AND control.xmin::text::bigint=(txid_current()%4294967296))
    OR ctrl.parent_deadline>LEAST(batch_row.valid_until,item_supply_internal.private_initial_author_recovery_source((body->>'source_origin_id')::uuid))
    OR ctrl.profile_snapshot_json->'retry_policy'->>'max_transient_attempts' IS DISTINCT FROM '1'
    OR ctrl.profile_snapshot_json->'profile'->'values'->>'request_timeout_ms' IS DISTINCT FROM '100000'
    OR body->>'window_id' IS DISTINCT FROM batch_row.window_id::text OR (body->>'parent_deadline')::timestamptz IS DISTINCT FROM ctrl.parent_deadline
    OR body->>'profile_hash' IS DISTINCT FROM ctrl.profile_snapshot_json->'profile'->>'profile_hash'
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_jobs job WHERE job.id=ctrl.job_id AND job.root_id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
     AND job.parent_job_id IS NULL AND job.xmin::text::bigint=(txid_current()%4294967296))
    OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations reservation WHERE reservation.job_id=ctrl.job_id)
    OR clock_timestamp()>=LEAST(ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until)
   THEN RAISE check_violation USING MESSAGE='558 exact new first-claimed unspent control required'; END IF;
  ELSIF protocol='private_initial_author_continuation_binding_v1' THEN
   suffix:='binding';
   SELECT journal.* INTO claim_row FROM tutor_item_supply_private_persistent_pack_journal journal
    WHERE journal.id=(body->>'claim_id')::uuid AND journal.operation_key=attempt_key||'.claim';
   PERFORM item_supply_internal.private_initial_author_recovery_source((body->>'source_origin_id')::uuid);
   IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','approval_id','claim_id','candidate_id','preparation_id','reservation_id','ref','lease','request','sources','item_key','version','candidate_key','storage_version','source_origin_id','valid_until']) IS DISTINCT FROM true
    OR body->>'approval_id' IS DISTINCT FROM approval_row.id::text OR claim_row.id IS NULL OR claim_row.pack_task_id<>NEW.pack_task_id
    OR body->'lease'->>'job_id' IS DISTINCT FROM claim_row.payload_json->>'job_id'
    OR body->>'candidate_id' IS DISTINCT FROM body->>'preparation_id' OR body->>'candidate_id'='17458037-ad0c-46d8-8c3b-a621bee386f1'
    OR body->>'item_key' IS DISTINCT FROM approval_row.payload_json->>'item_key' OR body->>'version' IS DISTINCT FROM 'v1'
    OR body->>'candidate_key' IS DISTINCT FROM approval_row.payload_json->>'candidate_key' OR body->'storage_version' IS DISTINCT FROM '1'::jsonb
    OR body->'ref'->>'slot_id' IS DISTINCT FROM approval_row.payload_json->>'slot_id'
    OR body->'ref'->>'business_item_id' IS DISTINCT FROM approval_row.payload_json->>'business_item_id'
    OR body->'ref'->>'root_id' IS DISTINCT FROM approval_row.payload_json->>'root_id'
    OR body->'ref'->>'pack_task_id' IS DISTINCT FROM NEW.pack_task_id::text
    OR body->'ref'->>'user_id' IS DISTINCT FROM NEW.user_id::text OR body->'ref'->>'epoch' IS DISTINCT FROM NEW.epoch::text
    OR body->'ref'->>'scope_id' IS DISTINCT FROM NEW.scope_id::text
    OR body->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
    OR body->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
    OR (body->>'valid_until')::timestamptz>LEAST((body->'lease'->>'expires_at')::timestamptz,
     (body->'lease'->>'parent_deadline')::timestamptz,item_supply_internal.private_initial_author_recovery_source((body->>'source_origin_id')::uuid))
   THEN RAISE check_violation USING MESSAGE='558 exact one candidate/initial-version binding required'; END IF;
  ELSE
   SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
    WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key=attempt_key||'.binding';
   IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='558 exact original prepared binding required'; END IF;
   IF protocol='private_initial_author_continuation_consumed_v1' THEN
    suffix:='consumed'; origin_id:=(body->>'source_origin_id')::uuid;
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact
   WHERE artifact.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe' AND artifact.epoch=1
   AND artifact.scope_id='cef6af15-84c0-466a-b330-3dc3235aa587'
   AND artifact.request_json->>'item_key'='private-native.7e9c44445b1653c1ad8b39b402e5aa51')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates candidate WHERE candidate.user_id='a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'
   AND candidate.epoch=1 AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
     OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done WHERE done.pack_task_id=NEW.pack_task_id
      AND done.operation_key IN(attempt_key||'.consumed',attempt_key||'.failure',attempt_key||'.author.result'))
    THEN RAISE check_violation USING MESSAGE='558 once-only committed original author dispatch required'; END IF;
    binding_row:=item_supply_internal.private_initial_author_continuation_bound(binding_row.id,origin_id,true);
    IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','binding_id','job_id','candidate_id','reservation_id','started_id','source_origin_id','consumed_at']) IS DISTINCT FROM true
     OR body->>'binding_id' IS DISTINCT FROM binding_row.id::text OR body->>'job_id' IS DISTINCT FROM binding_row.payload_json->'lease'->>'job_id'
     OR body->>'candidate_id' IS DISTINCT FROM binding_row.payload_json->>'candidate_id' OR body->>'reservation_id' IS DISTINCT FROM binding_row.payload_json->>'reservation_id'
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal started WHERE started.id=(body->>'started_id')::uuid
      AND started.pack_task_id=NEW.pack_task_id AND started.operation_key=attempt_key||'.author.started'
      AND started.xmin::text::bigint<>(txid_current()%4294967296))
     OR clock_timestamp()+interval '100 seconds'>=LEAST((binding_row.payload_json->>'valid_until')::timestamptz,item_supply_internal.private_initial_author_recovery_source(origin_id))
    THEN RAISE check_violation USING MESSAGE='558 exact committed one-shot dispatch required'; END IF;
   ELSIF protocol='private_initial_author_continuation_failure_v1' THEN
    suffix:='failure'; origin_id:=(body->>'source_origin_id')::uuid;
    IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed WHERE failed.pack_task_id=NEW.pack_task_id
     AND failed.operation_key=attempt_key||'.failure') THEN RAISE check_violation USING MESSAGE='558 failure already recorded'; END IF;
    binding_row:=item_supply_internal.private_initial_author_continuation_bound(binding_row.id,origin_id,true);
    SELECT journal.* INTO consumed_row FROM tutor_item_supply_private_persistent_pack_journal journal
     WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key=attempt_key||'.consumed'
     AND journal.xmin::text::bigint<>(txid_current()%4294967296);
    IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','binding_id','consumed_id','started_id','job_id','candidate_id','reservation_id','settlement_id','state','safe_reason','receipt','source_origin_id','recorded_at']) IS DISTINCT FROM true
     OR consumed_row.id IS NULL OR body->>'consumed_id' IS DISTINCT FROM consumed_row.id::text
     OR body->>'binding_id' IS DISTINCT FROM binding_row.id::text OR consumed_row.payload_json->>'binding_id' IS DISTINCT FROM binding_row.id::text
     OR body->>'started_id' IS DISTINCT FROM consumed_row.payload_json->>'started_id'
     OR body->>'job_id' IS DISTINCT FROM binding_row.payload_json->'lease'->>'job_id'
     OR body->>'candidate_id' IS DISTINCT FROM binding_row.payload_json->>'candidate_id'
     OR body->>'reservation_id' IS DISTINCT FROM binding_row.payload_json->>'reservation_id'
     OR COALESCE(body->>'state' IN('blocked','failed'),false) IS DISTINCT FROM true
     OR COALESCE(body->>'safe_reason' IN('generation_disabled','invalid_request','source_unavailable','source_mismatch','privacy_denied','input_limit','deadline_exhausted','provider_failed','invalid_candidate','candidate_mismatch','output_limit'),false) IS DISTINCT FROM true
     OR (body->'receipt'<>'null'::jsonb AND (body->'receipt'->>'candidate_id' IS DISTINCT FROM body->>'candidate_id'
      OR body->'receipt'->>'scope_hash' IS DISTINCT FROM binding_row.payload_json->'request'->>'scope_hash'
      OR body->'receipt'->'sources' IS DISTINCT FROM binding_row.payload_json->'sources'
      OR body->'receipt'->'provider'->>'request_attempt_bound' IS DISTINCT FROM '1'
      OR body->'receipt'->'provider'->>'provider' IS DISTINCT FROM 'deepseek'
      OR body->'receipt'->'provider'->>'configured_model' IS DISTINCT FROM 'deepseek-flash'
      OR body->'receipt'->'provider'->>'mode' IS DISTINCT FROM 'provider'))
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_runtime_settlements settlement
      WHERE settlement.id=(body->>'settlement_id')::uuid AND settlement.reservation_id=(body->>'reservation_id')::uuid
      AND settlement.settlement_key='generation.'||replace(body->>'candidate_id','-','')
      AND settlement.xmin::text::bigint<>(txid_current()%4294967296))
     OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact WHERE artifact.job_id=(body->>'job_id')::uuid)
     OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done WHERE done.pack_task_id=NEW.pack_task_id AND done.operation_key=attempt_key||'.author.result')
    THEN RAISE check_violation USING MESSAGE='558 forward original failure/committed independent settlement required'; END IF;
   ELSIF protocol='private_native_stage_v1' THEN
    IF body->>'status'='started' THEN suffix:='author.started'; ELSE suffix:='author.result'; END IF;
    SELECT journal.id INTO origin_id FROM tutor_item_supply_private_persistent_pack_journal journal WHERE journal.pack_task_id=NEW.pack_task_id
     AND journal.record_kind='current_pack_source_origin' AND journal.xmin::text::bigint=(txid_current()%4294967296)
     ORDER BY journal.created_at DESC,journal.id DESC LIMIT 1;
    binding_row:=item_supply_internal.private_initial_author_continuation_bound(binding_row.id,origin_id,false);
    IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','job_id','slot_id','stage','status','subject_hash','receipt_id']) IS DISTINCT FROM true
     OR body->>'job_id' IS DISTINCT FROM binding_row.payload_json->'lease'->>'job_id' OR body->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
     OR body->>'stage' IS DISTINCT FROM 'author' OR body->>'subject_hash' IS DISTINCT FROM '161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
     OR COALESCE(body->>'status' IN('started','committed'),false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='558 exact original author/v1 stage required'; END IF;
    IF suffix='author.started' THEN
     IF body->'receipt_id' IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='558 started is not a result'; END IF;
    ELSE
     IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal consumed
      WHERE consumed.pack_task_id=NEW.pack_task_id AND consumed.operation_key=attempt_key||'.consumed'
      AND consumed.payload_json->>'binding_id'=binding_row.id::text AND consumed.xmin::text::bigint<>(txid_current()%4294967296))
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact
       JOIN tutor_item_supply_private_candidates candidate ON candidate.id=artifact.candidate_id
       JOIN tutor_item_supply_private_versions version ON version.id=artifact.version_id AND version.candidate_id=candidate.id
       JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.reservation_id=(binding_row.payload_json->>'reservation_id')::uuid
       WHERE artifact.id=(body->>'receipt_id')::uuid AND artifact.job_id=(body->>'job_id')::uuid AND artifact.lease_generation=1 AND artifact.mode='live'
       AND artifact.request_json=binding_row.payload_json->'request' AND version.version=1
       AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51'
       AND settlement.settlement_key='generation.'||replace(binding_row.payload_json->>'candidate_id','-','')
       AND settlement.xmin::text::bigint<>(txid_current()%4294967296))
      OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed WHERE failed.pack_task_id=NEW.pack_task_id AND failed.operation_key=attempt_key||'.failure')
     THEN RAISE check_violation USING MESSAGE='558 genuine original artifact/consumed/settlement result required'; END IF;
    END IF;
   ELSE RAISE check_violation USING MESSAGE='558 closed recovery schema required';
   END IF;
  END IF;
 END IF;
 IF NEW.operation_key IS DISTINCT FROM attempt_key||'.'||suffix
 THEN RAISE check_violation USING MESSAGE='558 fixed approval bucket, no renamed attempt'; END IF;
 RETURN NEW;
END;
$src$),
 ('enforce_private_initial_author_continuation_control()', 'enforce_private_initial_author_continuation_control()', 'trigger', $src$
DECLARE claim_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT journal.* INTO claim_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc'
   AND journal.payload_json->>'schema_version'='private_initial_author_continuation_claim_v1' AND journal.payload_json->>'job_id'=OLD.job_id::text;
 IF claim_row.id IS NULL THEN RETURN NEW; END IF;
 PERFORM item_supply_internal.private_initial_author_continuation_approval((claim_row.payload_json->>'approval_id')::uuid);
 IF (NEW.job_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.profile_id,NEW.profile_snapshot_json,NEW.lease_owner,NEW.parent_deadline)
  IS DISTINCT FROM (OLD.job_id,OLD.user_id,OLD.epoch,OLD.scope_id,OLD.profile_id,OLD.profile_snapshot_json,OLD.lease_owner,OLD.parent_deadline)
  OR NEW.lease_generation<>1 OR NEW.attempt_count<>1
  OR NEW.parent_deadline IS DISTINCT FROM (claim_row.payload_json->>'parent_deadline')::timestamptz
  OR NEW.lease_expires_at>NEW.parent_deadline
 THEN RAISE check_violation USING MESSAGE='558 recovery job cannot be reclaimed/reprofiled/extended'; END IF;
 RETURN NEW;
END;
$src$),
 ('private_initial_author_continuation_auxiliary(uuid)', 'private_initial_author_continuation_auxiliary(p_binding uuid)', 'boolean', $src$
DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; attempt_key text;
BEGIN
 binding_row:=item_supply_internal.private_initial_author_continuation_bound(p_binding,
  (SELECT journal.payload_json->>'source_origin_id' FROM tutor_item_supply_private_persistent_pack_journal journal WHERE journal.id=p_binding)::uuid,false);
 approval_row:=item_supply_internal.private_initial_author_continuation_approval((binding_row.payload_json->>'approval_id')::uuid);
 attempt_key:='p7.private.initial-author.continuation.20261016.'||replace(approval_row.payload_json->>'predecessor_failure_id','-','');
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal started
  WHERE started.pack_task_id=binding_row.pack_task_id AND started.operation_key=attempt_key||'.author.started'
  AND started.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
  AND started.payload_json->>'schema_version'='private_native_stage_v1' AND started.payload_json->>'stage'='author' AND started.payload_json->>'status'='started')
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal aux
   WHERE aux.pack_task_id=binding_row.pack_task_id AND aux.record_kind='private_attachment'
   AND aux.payload_json->>'schema_version'='private_native_auxiliary_v1'
   AND aux.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND aux.payload_json->'request'->>'schema_version'='private_native_initial_author_v1')<>1
 THEN RAISE check_violation USING MESSAGE='558 complete original once-only preparation/stage required'; END IF;
 RETURN true;
END;
$src$),
 ('private_initial_author_continuation_terminal(uuid)', 'private_initial_author_continuation_terminal(p_started uuid)', 'text', $src$
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
   IF known_ancestor THEN RETURN 'failure'; ELSE RETURN NULL; END IF;
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
  IF failure_row.id IS NULL THEN RETURN NULL; END IF;
  failure_row:=item_supply_internal.private_initial_author_continuation_predecessor(failure_row.id,requested.pack_task_id,requested.user_id,requested.epoch,requested.scope_id);
 END LOOP;
END;
$src$)
 ) AS definitions(signature,header,result_type,body) LOOP
  SELECT array_agg(split_part(btrim(argument),' ',1) ORDER BY ord) INTO expected_names
   FROM unnest(string_to_array(substring(spec.header FROM '\((.*)\)$'),',')) WITH ORDINALITY AS args(argument,ord)
   WHERE btrim(argument)<>'';
  SELECT proc.* INTO prior FROM pg_proc proc WHERE proc.oid=to_regprocedure('item_supply_internal.'||spec.signature);
  IF FOUND THEN
   IF prior.prosrc IS DISTINCT FROM spec.body OR prior.prosecdef IS DISTINCT FROM true OR prior.prokind<>'f'
    OR prior.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
    OR prior.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
    OR prior.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
    OR prior.prorettype IS DISTINCT FROM to_regtype(spec.result_type) OR prior.proargnames IS DISTINCT FROM expected_names
    OR prior.provolatile<>'v' OR prior.proretset OR prior.proisstrict OR prior.proleakproof OR prior.proparallel<>'u'
    OR prior.procost<>100 OR prior.prorows<>0 OR prior.prosupport<>0 OR prior.provariadic<>0
    OR prior.pronargdefaults<>0 OR prior.proargdefaults IS NOT NULL OR prior.proallargtypes IS NOT NULL OR prior.proargmodes IS NOT NULL
    OR prior.probin IS NOT NULL OR prior.prosqlbody IS NOT NULL OR prior.protrftypes IS NOT NULL
    OR prior.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   THEN RAISE check_violation USING MESSAGE='558 unexpected existing receiver definition/metadata: '||spec.signature; END IF;
  ELSE
   EXECUTE 'CREATE FUNCTION item_supply_internal.'||spec.header||' RETURNS '||spec.result_type||
    ' LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS '||quote_literal(spec.body);
   EXECUTE 'ALTER FUNCTION item_supply_internal.'||spec.signature||' OWNER TO aearn_b1d_runtime_20261001';
   EXECUTE 'REVOKE ALL ON FUNCTION item_supply_internal.'||spec.signature||' FROM PUBLIC';
  END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','private_initial_author_continuation_insert','enforce_private_initial_author_continuation_insert',7,false,
   'CREATE TRIGGER private_initial_author_continuation_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_initial_author_continuation_insert()'),
  ('tutor_item_supply_private_job_controls','private_initial_author_continuation_control','enforce_private_initial_author_continuation_control',19,false,
   'CREATE TRIGGER private_initial_author_continuation_control BEFORE UPDATE ON public.tutor_item_supply_private_job_controls FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_initial_author_continuation_control()')
 ) AS triggers(table_name,trigger_name,function_name,trigger_type,deferred,ddl) LOOP
  SELECT trigger.* INTO prior FROM pg_trigger trigger WHERE trigger.tgrelid=to_regclass('public.'||tr.table_name) AND trigger.tgname=tr.trigger_name;
  IF FOUND THEN
   IF prior.tgfoid IS DISTINCT FROM to_regprocedure('item_supply_internal.'||tr.function_name||'()')
    OR prior.tgtype<>tr.trigger_type OR prior.tgenabled<>'O' OR prior.tgisinternal
    OR prior.tgdeferrable IS DISTINCT FROM tr.deferred OR prior.tginitdeferred IS DISTINCT FROM tr.deferred
    OR prior.tgnargs<>0 OR prior.tgqual IS NOT NULL OR prior.tgattr::text<>'' OR prior.tgargs<>''::bytea
    OR prior.tgparentid<>0 OR prior.tgconstrrelid<>0 OR prior.tgconstrindid<>0 OR prior.tgconstraint<>0
    OR prior.tgoldtable IS NOT NULL OR prior.tgnewtable IS NOT NULL
   THEN RAISE check_violation USING MESSAGE='558 unexpected existing receiver trigger: '||tr.trigger_name; END IF;
  ELSE EXECUTE tr.ddl; END IF;
 END LOOP;
END;
$install558$;

-- The ONLY old receiver changed: exact555 body -> exact early continuation dispatch.
DO $patchaux558$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldaux558$
DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; candidate_text text;
BEGIN
 IF NEW.payload_json->>'schema_version'='private_initial_author_recovery_binding_v1' THEN
  binding_row:=NEW;
 ELSIF NEW.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND NEW.payload_json->'request'->>'schema_version'='private_native_initial_author_v1'
  AND NEW.payload_json->'request'->'ref'->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' THEN
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.binding';
 ELSE RETURN NEW; END IF;
 IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='555 explicit PRIVATE recovery binding required before author commit'; END IF;
 binding_row:=item_supply_internal.private_initial_author_recovery_bound(binding_row.id,(binding_row.payload_json->>'source_origin_id')::uuid,false);
 candidate_text:=binding_row.payload_json->>'candidate_id';
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal started
  WHERE started.pack_task_id=binding_row.pack_task_id AND started.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started'
  AND started.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id')
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal aux
   WHERE aux.pack_task_id=binding_row.pack_task_id AND aux.record_kind='private_attachment'
   AND aux.payload_json->>'schema_version'='private_native_auxiliary_v1'
   AND aux.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND aux.payload_json->'request'->>'schema_version'='private_native_initial_author_v1')<>1
  OR (NEW.payload_json->>'schema_version'='private_native_auxiliary_v1' AND NEW.id::text IS DISTINCT FROM candidate_text)
 THEN RAISE check_violation USING MESSAGE='555 complete original once-only preparation/stage required'; END IF;
 RETURN NEW;
END;
$oldaux558$;
 new_body constant text := $newaux558$
DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; candidate_text text;
BEGIN
 -- Only real continuation binding/candidate rows enter the new full receiver.
 IF NEW.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1' THEN
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.id=NEW.id AND journal.pack_task_id=NEW.pack_task_id
   AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1';
  IF binding_row.id IS NULL OR item_supply_internal.private_initial_author_continuation_auxiliary(binding_row.id) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='558 complete existing continuation binding required'; END IF;
  RETURN NEW;
 ELSIF NEW.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND NEW.payload_json->'request'->>'schema_version'='private_native_initial_author_v1' THEN
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=NEW.pack_task_id AND journal.payload_json->>'schema_version'='private_initial_author_continuation_binding_v1'
   AND journal.payload_json->>'candidate_id'=NEW.id::text AND journal.payload_json->>'preparation_id'=NEW.id::text;
  IF binding_row.id IS NOT NULL THEN
   IF item_supply_internal.private_initial_author_continuation_auxiliary(binding_row.id) IS DISTINCT FROM true
   THEN RAISE check_violation USING MESSAGE='558 complete existing continuation auxiliary required'; END IF;
   RETURN NEW;
  END IF;
 END IF;
 IF NEW.payload_json->>'schema_version'='private_initial_author_recovery_binding_v1' THEN
  binding_row:=NEW;
 ELSIF NEW.payload_json->>'schema_version'='private_native_auxiliary_v1'
  AND NEW.payload_json->'request'->>'schema_version'='private_native_initial_author_v1'
  AND NEW.payload_json->'request'->'ref'->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c' THEN
  SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.binding';
 ELSE RETURN NEW; END IF;
 IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='555 explicit PRIVATE recovery binding required before author commit'; END IF;
 binding_row:=item_supply_internal.private_initial_author_recovery_bound(binding_row.id,(binding_row.payload_json->>'source_origin_id')::uuid,false);
 candidate_text:=binding_row.payload_json->>'candidate_id';
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal started
  WHERE started.pack_task_id=binding_row.pack_task_id AND started.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started'
  AND started.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id')
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal aux
   WHERE aux.pack_task_id=binding_row.pack_task_id AND aux.record_kind='private_attachment'
   AND aux.payload_json->>'schema_version'='private_native_auxiliary_v1'
   AND aux.payload_json->>'job_id'=binding_row.payload_json->'lease'->>'job_id'
   AND aux.payload_json->'request'->>'schema_version'='private_native_initial_author_v1')<>1
  OR (NEW.payload_json->>'schema_version'='private_native_auxiliary_v1' AND NEW.id::text IS DISTINCT FROM candidate_text)
 THEN RAISE check_violation USING MESSAGE='555 complete original once-only preparation/stage required'; END IF;
 RETURN NEW;
END;
$newaux558$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.enforce_private_initial_author_recovery_auxiliary()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'enforce_private_initial_author_recovery_auxiliary'
  OR actual.lanname IS DISTINCT FROM 'plpgsql' OR actual.prokind<>'f'
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype
  OR actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='558 original 555 auxiliary identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='558 original 555 auxiliary body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='558 original 555 auxiliary framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.*,l.lanname INTO verified FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='558 auxiliary metadata/OID/owner/ACL/body changed'; END IF;
END;
$patchaux558$;
