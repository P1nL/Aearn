-- One directly approved NEW PRIVATE first-slot author. No historical clearance.
-- Append-only original journal; <=554 definitions, old controls and UNKNOWN stay.
-- Install/replay only exact definitions and metadata; no checksum manifest.
DO $install555$
DECLARE spec record; prior record; expected_names text[]; tr record;
BEGIN
 FOR spec IN SELECT * FROM (VALUES
 ('private_initial_author_recovery_anchor(uuid,uuid,bigint,uuid)',
  'private_initial_author_recovery_anchor(p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)',
  'public.tutor_item_supply_private_persistent_pack_journal', $src$
DECLARE task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 IF (p_task,p_user,p_epoch,p_scope) IS DISTINCT FROM
  ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid)
 THEN RAISE check_violation USING MESSAGE='555 exact approved PRIVATE task required'; END IF;
 PERFORM item_supply_internal.private_native_epoch(p_user,p_epoch);
 SELECT journal.* INTO task_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_task AND journal.pack_task_id=p_task AND journal.record_kind='task'
  AND journal.user_id=p_user AND journal.epoch=p_epoch AND journal.scope_id=p_scope FOR SHARE;
 IF task_row.id IS NULL OR task_row.payload_json->>'enhancement' IS DISTINCT FROM 'prefer_private'
  OR task_row.payload_json->'ref'->>'mapping_receipt_id' IS DISTINCT FROM 'd8e34e01-3514-41a3-9bbd-55ee3e627134'
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(task_row.payload_json->'slots') member
   WHERE member->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
   AND member->>'logical_item_id'='7e9c4444-5b16-53c1-ad8b-39b402e5aa51' AND member->>'slot'='practice-1')
 THEN RAISE check_violation USING MESSAGE='555 original prefer_private task/slot required'; END IF;
 PERFORM root.id FROM tutor_item_supply_private_budget_roots root WHERE root.id='aaaf99e5-4530-4319-bb1a-0fe6d84020f9'
  AND root.user_id=p_user AND root.epoch=p_epoch AND root.scope_id=p_scope FOR SHARE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id='572bbd7c-98dd-4e39-ba2d-bda19807ae74' AND journal.pack_task_id=p_task AND journal.record_kind='phase'
  AND journal.payload_json->>'schema_version'='private_native_phase_v1'
  AND journal.payload_json->>'job_id'='487b12c4-f98a-41c9-a21b-abb9243a28dd'
  AND journal.payload_json->>'root_id'='aaaf99e5-4530-4319-bb1a-0fe6d84020f9')
 THEN RAISE check_violation USING MESSAGE='555 original same PRIVATE canonical root required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id='5ad70ab7-0441-456b-ae5e-156755a80911' AND journal.pack_task_id=p_task
  AND journal.record_kind='private_status' AND journal.payload_json->>'schema_version'='private_native_stage_v1'
  AND journal.payload_json->>'job_id'='487b12c4-f98a-41c9-a21b-abb9243a28dd'
  AND journal.payload_json->>'slot_id'='f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
  AND journal.payload_json->>'stage'='author' AND journal.payload_json->>'status'='started'
  AND journal.payload_json->>'subject_hash'='161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13')
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal aux
   JOIN tutor_item_supply_private_reservations reservation ON reservation.id=(aux.payload_json->>'reservation_id')::uuid
   JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.reservation_id=reservation.id
   WHERE aux.id='17458037-ad0c-46d8-8c3b-a621bee386f1' AND aux.pack_task_id=p_task
   AND aux.record_kind='private_attachment' AND aux.payload_json->>'schema_version'='private_native_auxiliary_v1'
   AND aux.payload_json->>'job_id'='487b12c4-f98a-41c9-a21b-abb9243a28dd'
   AND reservation.id='67683f85-409a-49d1-b055-67d26d4b70c0' AND reservation.job_id='487b12c4-f98a-41c9-a21b-abb9243a28dd'
   AND settlement.id='ee311d76-35f9-470b-a190-e25bca2fc69c' AND settlement.sequence=1
   AND settlement.settlement_key='generation.17458037ad0c46d88c3ba621bee386f1'
   AND settlement.usage_state='unknown' AND settlement.cost_amount IS NULL AND settlement.receipt_hash IS NULL
   AND settlement.xmin::text::bigint<>(txid_current()%4294967296))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_generation_artifacts artifact WHERE artifact.job_id='487b12c4-f98a-41c9-a21b-abb9243a28dd')
 THEN RAISE check_violation USING MESSAGE='555 retained old started/committed UNKNOWN required, not unspent clearance'; END IF;
 RETURN task_row;
END;
$src$),
 ('private_initial_author_recovery_source(uuid)', 'private_initial_author_recovery_source(p_origin uuid)', 'timestamptz', $src$
DECLARE origin_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT journal.* INTO origin_row FROM tutor_item_supply_private_persistent_pack_journal journal WHERE journal.id=p_origin;
 IF origin_row.pack_task_id IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid
  OR item_supply_internal.current_pack_source_origin_current(p_origin,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,
   'd8e34e01-3514-41a3-9bbd-55ee3e627134') IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='555 fresh same-TOP original SOURCE required'; END IF;
 RETURN (origin_row.payload_json->>'valid_until')::timestamptz;
END;
$src$),
 ('private_initial_author_recovery_bound(uuid,uuid,boolean)',
  'private_initial_author_recovery_bound(p_binding uuid,p_origin uuid,p_committed boolean)',
  'public.tutor_item_supply_private_persistent_pack_journal', $src$
DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 claim_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 aux_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 source_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 body jsonb; lease_json jsonb; stamp timestamptz; source_end timestamptz; reservation_row record;
BEGIN
 SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_binding AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.binding'
  AND journal.record_kind='private_status';
 IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='555 original recovery binding required'; END IF;
 PERFORM item_supply_internal.private_initial_author_recovery_anchor(binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id);
 body:=binding_row.payload_json; lease_json:=body->'lease';
 SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=(body->>'approval_id')::uuid AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.approval' FOR UPDATE;
 SELECT journal.* INTO claim_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=(body->>'claim_id')::uuid AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.claim';
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
 IF approval_row.id IS NULL OR claim_row.id IS NULL OR aux_row.id IS NULL OR ctrl.id IS NULL OR batch_row.id IS NULL OR reservation_row.id IS NULL
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
 THEN RAISE check_violation USING MESSAGE='555 exact original prepared/current lease/source/budget binding required'; END IF;
 IF p_committed AND (EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.id IN(binding_row.id,approval_row.id,claim_row.id) AND journal.xmin::text::bigint=(txid_current()%4294967296))
  OR item_supply_internal.private_pack_auxiliary_committed(binding_row.pack_task_id,aux_row.id) IS DISTINCT FROM true)
 THEN RAISE check_violation USING MESSAGE='555 prior-TOP committed original preparation required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 source_end:=LEAST(source_end,item_supply_internal.private_initial_author_recovery_source(p_origin));
 stamp:=clock_timestamp();
 IF stamp>=LEAST(source_end,ctrl.lease_expires_at,ctrl.parent_deadline,batch_row.valid_until,
  (body->>'valid_until')::timestamptz,(lease_json->>'expires_at')::timestamptz,
  (lease_json->'profile'->>'bound_at')::timestamptz+(lease_json->'profile'->'values'->>'stage_deadline_ms')::bigint*interval '1 millisecond')
 THEN RAISE check_violation USING MESSAGE='555 postwait current bound expired'; END IF;
 RETURN binding_row;
END;
$src$),
 ('private_initial_author_recovery_first_claim(uuid,uuid,uuid,uuid,text)',
  'private_initial_author_recovery_first_claim(p_approval uuid,p_job uuid,p_batch uuid,p_origin uuid,p_lease_owner text)',
  'public.tutor_item_supply_private_job_controls', $src$
DECLARE approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 job_row public.tutor_item_supply_private_jobs%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 profile_row public.tutor_item_supply_parameter_profiles%ROWTYPE;
 stamp timestamptz; source_end timestamptz; body jsonb;
BEGIN
 task_row:=item_supply_internal.private_initial_author_recovery_anchor('6739d3c5-6619-44ce-970f-0ab1e49f3acc','a65237a6-82d3-42ad-b4bb-a9e2f4d907fe',1,'cef6af15-84c0-466a-b330-3dc3235aa587');
 SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal WHERE journal.id=p_approval
  AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.approval' AND journal.pack_task_id=task_row.id FOR UPDATE;
 IF approval_row.id IS NULL OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id=task_row.id AND journal.operation_key IN('p7.private.initial-author.recovery.20261015.once1.claim','p7.private.initial-author.recovery.20261015.once1.binding','p7.private.initial-author.recovery.20261015.once1.consumed'))
 THEN RAISE check_violation USING MESSAGE='555 recovery already allocated, no second claim'; END IF;
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
  OR p_lease_owner IS DISTINCT FROM 'private.initial.author.recovery.'||replace(p_approval::text,'-','')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations reservation WHERE reservation.job_id=p_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_private_checkpoints checkpoint WHERE checkpoint.job_id=p_job)
  OR ctrl.parent_deadline>LEAST(source_end,batch_row.valid_until)
 THEN RAISE check_violation USING MESSAGE='555 fresh exact NEW first-claim profile/batch/control required'; END IF;
 PERFORM item_supply_internal.private_development_accounting_batch_current(batch_row);
 stamp:=clock_timestamp();
 IF ctrl.available_at>stamp OR stamp+interval '100 seconds'>=LEAST(source_end,batch_row.valid_until,ctrl.parent_deadline)
 THEN RAISE check_violation USING MESSAGE='555 first-claim remaining request bound insufficient'; END IF;
 UPDATE tutor_item_supply_private_job_controls control SET state='leased',state_version=control.state_version+1,
  lease_generation=1,attempt_count=1,lease_owner=p_lease_owner,lease_expires_at=LEAST(control.parent_deadline,stamp+interval '3600 seconds'),updated_at=stamp
  WHERE control.id=ctrl.id AND control.state_version=ctrl.state_version RETURNING control.* INTO ctrl;
 body:=jsonb_build_object('schema_version','private_initial_author_recovery_claim_v1','approval_id',p_approval,'job_id',p_job,
  'batch_id',p_batch,'window_id',batch_row.window_id,'profile_hash',profile_row.profile_hash,'lease_owner',p_lease_owner,
  'generation',1,'attempt_count',1,'parent_deadline',ctrl.parent_deadline,'source_origin_id',p_origin,'claimed_at',stamp);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
  VALUES(gen_random_uuid(),task_row.id,task_row.user_id,task_row.epoch,task_row.scope_id,'private_status',
   'p7.private.initial-author.recovery.20261015.once1.claim',task_row.intent_hash,body);
 RETURN ctrl;
END;
$src$),
 ('private_initial_author_recovery_consume(uuid,uuid)',
  'private_initial_author_recovery_consume(p_binding uuid,p_origin uuid)', 'uuid', $src$
DECLARE binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 identity uuid:=gen_random_uuid(); stamp timestamptz;
BEGIN
 binding_row:=item_supply_internal.private_initial_author_recovery_bound(p_binding,p_origin,true);
 SELECT journal.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id=binding_row.pack_task_id AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF started_row.id IS NULL OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id=binding_row.pack_task_id AND journal.operation_key IN
   ('p7.private.initial-author.recovery.20261015.once1.consumed','p7.private.initial-author.recovery.20261015.once1.failure','p7.private.initial-author.recovery.20261015.once1.author.result'))
 THEN RAISE check_violation USING MESSAGE='555 once-only committed original author dispatch required'; END IF;
 stamp:=clock_timestamp();
 IF stamp+((binding_row.payload_json->'request'->'profile'->'values'->>'request_timeout_ms')::bigint*interval '1 millisecond')
   >=LEAST((binding_row.payload_json->>'valid_until')::timestamptz,item_supply_internal.private_initial_author_recovery_source(p_origin))
 THEN RAISE check_violation USING MESSAGE='555 complete formal request no longer fits'; END IF;
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(identity,binding_row.pack_task_id,binding_row.user_id,binding_row.epoch,binding_row.scope_id,'private_status',
  'p7.private.initial-author.recovery.20261015.once1.consumed',binding_row.intent_hash,
  jsonb_build_object('schema_version','private_initial_author_recovery_consumed_v1','binding_id',binding_row.id,
   'job_id',binding_row.payload_json->'lease'->>'job_id','candidate_id',binding_row.payload_json->>'candidate_id',
   'reservation_id',binding_row.payload_json->>'reservation_id','started_id',started_row.id,'source_origin_id',p_origin,'consumed_at',stamp));
 RETURN identity;
END;
$src$),
 ('private_initial_author_failure_committed(uuid,uuid,uuid,bigint,uuid)',
  'private_initial_author_failure_committed(p_receipt uuid,p_task uuid,p_user uuid,p_epoch bigint,p_scope uuid)', 'boolean', $src$
DECLARE failure_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT journal.* INTO failure_row FROM tutor_item_supply_private_persistent_pack_journal journal WHERE journal.id=p_receipt
  AND journal.pack_task_id=p_task AND journal.user_id=p_user AND journal.epoch=p_epoch AND journal.scope_id=p_scope
  AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.failure'
  AND journal.payload_json->>'schema_version'='private_initial_author_failure_v1'
  AND journal.xmin::text::bigint<>(txid_current()%4294967296);
 IF failure_row.id IS NULL THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_initial_author_recovery_anchor(p_task,p_user,p_epoch,p_scope);
 RETURN EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal binding
  JOIN tutor_item_supply_private_persistent_pack_journal consumed ON consumed.id=(failure_row.payload_json->>'consumed_id')::uuid
  JOIN tutor_item_supply_private_persistent_pack_journal started ON started.id=(failure_row.payload_json->>'started_id')::uuid
  JOIN tutor_item_supply_private_reservations reservation ON reservation.id=(failure_row.payload_json->>'reservation_id')::uuid
  JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.id=(failure_row.payload_json->>'settlement_id')::uuid
  WHERE binding.id=(failure_row.payload_json->>'binding_id')::uuid AND binding.pack_task_id=p_task
  AND binding.operation_key='p7.private.initial-author.recovery.20261015.once1.binding'
  AND consumed.operation_key='p7.private.initial-author.recovery.20261015.once1.consumed'
  AND consumed.pack_task_id=p_task AND consumed.payload_json->>'binding_id'=binding.id::text
  AND consumed.payload_json->>'started_id'=started.id::text
  AND started.pack_task_id=p_task AND started.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started'
  AND failure_row.payload_json->>'candidate_id'=binding.payload_json->>'candidate_id'
  AND failure_row.payload_json->>'job_id'=binding.payload_json->'lease'->>'job_id'
  AND reservation.job_id=(binding.payload_json->'lease'->>'job_id')::uuid AND reservation.lease_generation=1
  AND settlement.reservation_id=reservation.id
  AND settlement.settlement_key='generation.'||replace(binding.payload_json->>'candidate_id','-','')
  AND consumed.xmin::text::bigint<>(txid_current()%4294967296) AND settlement.xmin::text::bigint<>(txid_current()%4294967296));
END;
$src$),
 ('private_initial_author_recovery_terminal(uuid)', 'private_initial_author_recovery_terminal(p_started uuid)', 'text', $src$
DECLARE started_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE; failure_id uuid;
BEGIN
 SELECT journal.* INTO started_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.id=p_started AND (journal.id='5ad70ab7-0441-456b-ae5e-156755a80911'
   OR journal.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started')
  AND journal.pack_task_id='6739d3c5-6619-44ce-970f-0ab1e49f3acc';
 IF started_row.id IS NULL THEN RETURN NULL; END IF;
 PERFORM item_supply_internal.private_initial_author_recovery_anchor(started_row.pack_task_id,started_row.user_id,started_row.epoch,started_row.scope_id);
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done
  JOIN tutor_item_supply_private_persistent_pack_journal binding ON binding.pack_task_id=done.pack_task_id
   AND binding.operation_key='p7.private.initial-author.recovery.20261015.once1.binding'
  JOIN tutor_item_supply_private_persistent_pack_journal consumed ON consumed.pack_task_id=done.pack_task_id
   AND consumed.operation_key='p7.private.initial-author.recovery.20261015.once1.consumed' AND consumed.payload_json->>'binding_id'=binding.id::text
  JOIN tutor_item_supply_private_generation_artifacts artifact ON artifact.id=(done.payload_json->>'receipt_id')::uuid
   AND artifact.job_id=(binding.payload_json->'lease'->>'job_id')::uuid AND artifact.request_json=binding.payload_json->'request'
  JOIN tutor_item_supply_private_runtime_settlements settlement ON settlement.reservation_id=(binding.payload_json->>'reservation_id')::uuid
   AND settlement.settlement_key='generation.'||replace(binding.payload_json->>'candidate_id','-','')
  WHERE done.pack_task_id=started_row.pack_task_id AND done.operation_key='p7.private.initial-author.recovery.20261015.once1.author.result'
  AND done.payload_json->>'status'='committed' AND artifact.mode='live'
  AND done.xmin::text::bigint<>(txid_current()%4294967296) AND artifact.xmin::text::bigint<>(txid_current()%4294967296)
  AND consumed.xmin::text::bigint<>(txid_current()%4294967296) AND settlement.xmin::text::bigint<>(txid_current()%4294967296)) THEN RETURN 'artifact'; END IF;
 SELECT journal.id INTO failure_id FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.pack_task_id=started_row.pack_task_id AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.failure';
 IF item_supply_internal.private_initial_author_failure_committed(failure_id,started_row.pack_task_id,started_row.user_id,started_row.epoch,started_row.scope_id)
 THEN RETURN 'failure'; END IF;
 RETURN NULL;
END;
$src$),
 ('enforce_private_initial_author_recovery_insert()', 'enforce_private_initial_author_recovery_insert()', 'trigger', $src$
DECLARE body jsonb:=NEW.payload_json; protocol text:=body->>'schema_version'; suffix text; stamp timestamptz;
 task_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 approval_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 binding_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 consumed_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 claim_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
 ctrl public.tutor_item_supply_private_job_controls%ROWTYPE;
 batch_row public.tutor_item_supply_private_development_model_accounting_batches%ROWTYPE;
 origin_id uuid; identity uuid; valid boolean;
BEGIN
 IF COALESCE(protocol NOT IN('private_initial_author_recovery_approval_v1','private_initial_author_recovery_claim_v1',
  'private_initial_author_recovery_binding_v1','private_initial_author_recovery_consumed_v1','private_initial_author_failure_v1'),true)
  AND NEW.operation_key NOT LIKE 'p7.private.initial-author.recovery.20261015.once1.%' THEN RETURN NEW; END IF;
 task_row:=item_supply_internal.private_initial_author_recovery_anchor(NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id);
 IF NEW.record_kind IS DISTINCT FROM 'private_status' OR NEW.intent_hash IS DISTINCT FROM task_row.intent_hash
 THEN RAISE check_violation USING MESSAGE='555 exact original PRIVATE journal namespace required'; END IF;
 stamp:=clock_timestamp();
 IF protocol='private_initial_author_recovery_approval_v1' THEN
  suffix:='approval';
  IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','authorization_key','old_started_id','old_job_id','old_candidate_id','slot_id','business_item_id','root_id','mapping_receipt_id','item_key','version','candidate_key','storage_version','issued_at']) IS DISTINCT FROM true
   OR body->>'authorization_key' IS DISTINCT FROM 'p7.private.initial-author.recovery.20261015.once1'
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
   OR (body->>'issued_at')::timestamptz>stamp
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates candidate WHERE candidate.user_id=NEW.user_id
    AND candidate.epoch=NEW.epoch AND candidate.candidate_key='private.native.7e9c44445b1653c1ad8b39b402e5aa51')
  THEN RAISE check_violation USING MESSAGE='555 exact directly approved NEW initial version required'; END IF;
 ELSE
  SELECT journal.* INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal journal
   WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.approval' FOR UPDATE;
  IF approval_row.id IS NULL THEN RAISE check_violation USING MESSAGE='555 original PRIVATE approval required'; END IF;
  IF protocol='private_initial_author_recovery_claim_v1' THEN
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
    OR body->>'lease_owner' IS DISTINCT FROM 'private.initial.author.recovery.'||replace(approval_row.id::text,'-','')
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
   THEN RAISE check_violation USING MESSAGE='555 exact new first-claimed unspent control required'; END IF;
  ELSIF protocol='private_initial_author_recovery_binding_v1' THEN
   suffix:='binding';
   SELECT journal.* INTO claim_row FROM tutor_item_supply_private_persistent_pack_journal journal
    WHERE journal.id=(body->>'claim_id')::uuid AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.claim';
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
    OR body->'ref'->'parent_version_id' IS DISTINCT FROM 'null'::jsonb
    OR (body->>'valid_until')::timestamptz>LEAST((body->'lease'->>'expires_at')::timestamptz,
     (body->'lease'->>'parent_deadline')::timestamptz,item_supply_internal.private_initial_author_recovery_source((body->>'source_origin_id')::uuid))
   THEN RAISE check_violation USING MESSAGE='555 exact one candidate/initial-version binding required'; END IF;
  ELSE
   SELECT journal.* INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal journal
    WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.binding';
   IF binding_row.id IS NULL THEN RAISE check_violation USING MESSAGE='555 exact original prepared binding required'; END IF;
   IF protocol='private_initial_author_recovery_consumed_v1' THEN
    suffix:='consumed'; origin_id:=(body->>'source_origin_id')::uuid;
    binding_row:=item_supply_internal.private_initial_author_recovery_bound(binding_row.id,origin_id,true);
    IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','binding_id','job_id','candidate_id','reservation_id','started_id','source_origin_id','consumed_at']) IS DISTINCT FROM true
     OR body->>'binding_id' IS DISTINCT FROM binding_row.id::text OR body->>'job_id' IS DISTINCT FROM binding_row.payload_json->'lease'->>'job_id'
     OR body->>'candidate_id' IS DISTINCT FROM binding_row.payload_json->>'candidate_id' OR body->>'reservation_id' IS DISTINCT FROM binding_row.payload_json->>'reservation_id'
     OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal started WHERE started.id=(body->>'started_id')::uuid
      AND started.pack_task_id=NEW.pack_task_id AND started.operation_key='p7.private.initial-author.recovery.20261015.once1.author.started'
      AND started.xmin::text::bigint<>(txid_current()%4294967296))
     OR clock_timestamp()+interval '100 seconds'>=LEAST((binding_row.payload_json->>'valid_until')::timestamptz,item_supply_internal.private_initial_author_recovery_source(origin_id))
    THEN RAISE check_violation USING MESSAGE='555 exact committed one-shot dispatch required'; END IF;
   ELSIF protocol='private_initial_author_failure_v1' THEN
    suffix:='failure'; origin_id:=(body->>'source_origin_id')::uuid;
    binding_row:=item_supply_internal.private_initial_author_recovery_bound(binding_row.id,origin_id,true);
    SELECT journal.* INTO consumed_row FROM tutor_item_supply_private_persistent_pack_journal journal
     WHERE journal.pack_task_id=NEW.pack_task_id AND journal.operation_key='p7.private.initial-author.recovery.20261015.once1.consumed'
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
     OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal done WHERE done.pack_task_id=NEW.pack_task_id AND done.operation_key='p7.private.initial-author.recovery.20261015.once1.author.result')
    THEN RAISE check_violation USING MESSAGE='555 forward original failure/committed independent settlement required'; END IF;
   ELSIF protocol='private_native_stage_v1' THEN
    IF body->>'status'='started' THEN suffix:='author.started'; ELSE suffix:='author.result'; END IF;
    SELECT journal.id INTO origin_id FROM tutor_item_supply_private_persistent_pack_journal journal WHERE journal.pack_task_id=NEW.pack_task_id
     AND journal.record_kind='current_pack_source_origin' AND journal.xmin::text::bigint=(txid_current()%4294967296)
     ORDER BY journal.created_at DESC,journal.id DESC LIMIT 1;
    binding_row:=item_supply_internal.private_initial_author_recovery_bound(binding_row.id,origin_id,false);
    IF item_supply_internal.snapshot_keys(body,ARRAY['schema_version','job_id','slot_id','stage','status','subject_hash','receipt_id']) IS DISTINCT FROM true
     OR body->>'job_id' IS DISTINCT FROM binding_row.payload_json->'lease'->>'job_id' OR body->>'slot_id' IS DISTINCT FROM 'f2b5a6dd-97d2-52dd-8962-68962f6ea76c'
     OR body->>'stage' IS DISTINCT FROM 'author' OR body->>'subject_hash' IS DISTINCT FROM '161078e42e8fef3ba4b9c984035baa2e431a50b31a18ac95614cc6820394af13'
     OR COALESCE(body->>'status' IN('started','committed'),false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='555 exact original author/v1 stage required'; END IF;
    IF suffix='author.started' THEN
     IF body->'receipt_id' IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='555 started is not a result'; END IF;
    ELSE
     IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal consumed
      WHERE consumed.pack_task_id=NEW.pack_task_id AND consumed.operation_key='p7.private.initial-author.recovery.20261015.once1.consumed'
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
      OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal failed WHERE failed.pack_task_id=NEW.pack_task_id AND failed.operation_key='p7.private.initial-author.recovery.20261015.once1.failure')
     THEN RAISE check_violation USING MESSAGE='555 genuine original artifact/consumed/settlement result required'; END IF;
    END IF;
   ELSE RAISE check_violation USING MESSAGE='555 closed recovery schema required';
   END IF;
  END IF;
 END IF;
 IF NEW.operation_key IS DISTINCT FROM 'p7.private.initial-author.recovery.20261015.once1.'||suffix
 THEN RAISE check_violation USING MESSAGE='555 fixed approval bucket, no renamed attempt'; END IF;
 RETURN NEW;
END;
$src$),
 ('enforce_private_initial_author_recovery_auxiliary()', 'enforce_private_initial_author_recovery_auxiliary()', 'trigger', $src$
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
$src$),
 ('enforce_private_initial_author_recovery_control()', 'enforce_private_initial_author_recovery_control()', 'trigger', $src$
DECLARE claim_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 SELECT journal.* INTO claim_row FROM tutor_item_supply_private_persistent_pack_journal journal
  WHERE journal.operation_key='p7.private.initial-author.recovery.20261015.once1.claim' AND journal.payload_json->>'job_id'=OLD.job_id::text;
 IF claim_row.id IS NULL THEN RETURN NEW; END IF;
 IF (NEW.job_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.profile_id,NEW.profile_snapshot_json,NEW.lease_owner,NEW.parent_deadline)
  IS DISTINCT FROM (OLD.job_id,OLD.user_id,OLD.epoch,OLD.scope_id,OLD.profile_id,OLD.profile_snapshot_json,OLD.lease_owner,OLD.parent_deadline)
  OR NEW.lease_generation<>1 OR NEW.attempt_count<>1
  OR NEW.parent_deadline IS DISTINCT FROM (claim_row.payload_json->>'parent_deadline')::timestamptz
  OR NEW.lease_expires_at>NEW.parent_deadline
 THEN RAISE check_violation USING MESSAGE='555 recovery job cannot be reclaimed/reprofiled/extended'; END IF;
 RETURN NEW;
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
    OR prior.procost<>100 OR prior.pronargdefaults<>0 OR prior.prolang<>(SELECT oid FROM pg_language WHERE lanname='plpgsql')
   THEN RAISE check_violation USING MESSAGE='555 unexpected existing receiver definition/metadata: '||spec.signature; END IF;
  ELSE
   EXECUTE 'CREATE FUNCTION item_supply_internal.'||spec.header||' RETURNS '||spec.result_type||
    ' LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS '||quote_literal(spec.body);
   EXECUTE 'ALTER FUNCTION item_supply_internal.'||spec.signature||' OWNER TO aearn_b1d_runtime_20261001';
   EXECUTE 'REVOKE ALL ON FUNCTION item_supply_internal.'||spec.signature||' FROM PUBLIC';
  END IF;
 END LOOP;
 FOR tr IN SELECT * FROM (VALUES
  ('tutor_item_supply_private_persistent_pack_journal','private_initial_author_recovery_insert','enforce_private_initial_author_recovery_insert',7,false,
   'CREATE TRIGGER private_initial_author_recovery_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_initial_author_recovery_insert()'),
  ('tutor_item_supply_private_persistent_pack_journal','private_initial_author_recovery_auxiliary','enforce_private_initial_author_recovery_auxiliary',5,true,
   'CREATE CONSTRAINT TRIGGER private_initial_author_recovery_auxiliary AFTER INSERT ON public.tutor_item_supply_private_persistent_pack_journal DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_initial_author_recovery_auxiliary()'),
  ('tutor_item_supply_private_job_controls','private_initial_author_recovery_control','enforce_private_initial_author_recovery_control',19,false,
   'CREATE TRIGGER private_initial_author_recovery_control BEFORE UPDATE ON public.tutor_item_supply_private_job_controls FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_initial_author_recovery_control()')
 ) AS triggers(table_name,trigger_name,function_name,trigger_type,deferred,ddl) LOOP
  SELECT trigger.* INTO prior FROM pg_trigger trigger WHERE trigger.tgrelid=to_regclass('public.'||tr.table_name) AND trigger.tgname=tr.trigger_name;
  IF FOUND THEN
   IF prior.tgfoid IS DISTINCT FROM to_regprocedure('item_supply_internal.'||tr.function_name||'()')
    OR prior.tgtype<>tr.trigger_type OR prior.tgenabled<>'O' OR prior.tgisinternal
    OR prior.tgdeferrable IS DISTINCT FROM tr.deferred OR prior.tginitdeferred IS DISTINCT FROM tr.deferred
    OR prior.tgnargs<>0 OR prior.tgqual IS NOT NULL OR prior.tgattr::text<>''
   THEN RAISE check_violation USING MESSAGE='555 unexpected existing receiver trigger: '||tr.trigger_name; END IF;
  ELSE EXECUTE tr.ddl; END IF;
 END LOOP;
END;
$install555$;
