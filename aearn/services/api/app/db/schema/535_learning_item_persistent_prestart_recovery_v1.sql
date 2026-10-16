--535: one registered trusted-original-class prestart case; NOT HTTP=0 or UNKNOWN discharge.

--0 tables/columns; preserve all existing functions/triggers, append one receiver.

DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_user<>'aearn_b1d_runtime_20261001' THEN RAISE check_violation USING MESSAGE='535 exact B1d owner only'; END IF; END $$;

DO $old535$ DECLARE e record;a record; BEGIN FOR e IN SELECT * FROM (VALUES
('item_supply_internal.enforce_private_enhancement_intent_insert()','ef3585fc5071432277cc03a8c207d07f536727f9e8b073c3ddb93afe4465b2bf'),
('item_supply_internal.enforce_private_native_public_fallback_clearance()','a3e40645244c2cba9df9099d67e00994578e9c0b331f10c20f38934524728239'),
('item_supply_internal.enforce_private_native_relation_repair_insert()','4725f83326efa21fa59fbee4b7560326d013fbde4959f97dd707f9c09e1e1c83'),
('item_supply_internal.enforce_private_native_resume_insert()','a4b5f0991cfed813a660e0fb2d116ccceeb531d1beb8ed015a0f52cd95fbd68a'),
('public.enforce_item_supply_immutable()','99d2a974483a38163a65cfab06f7d3f0576641366b8ab03fa0fd3da0c386290d'),
('item_supply_internal.enforce_persistent_pack_journal_insert()','59cbbd4d9fcd1eca6f3db40e0733cc9ffdcdd2e77dc14b87bdf6c6d396617de8'),
('public.enforce_private_enhancement_wait_insert()','f5876734ac2df43069e10fe084356aeb826b99f4eb0106ed11608a1ed7815757'),
('public.enforce_private_native_base_union_insert()','446932c603d430a1fa7004182e0a19ee43afb9381a535131b1619c440d4b1c7d')
) AS p(signature,sha) LOOP SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure(e.signature); IF NOT FOUND OR encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM e.sha OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proisstrict OR a.proretset OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] THEN RAISE check_violation USING MESSAGE='535 existing private guard changed'; END IF; END LOOP; END $old535$;

DO $pre535$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_persistent_prestart_recovery(jsonb,uuid)'); IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM '8aa33e6c5344e0c5212f8817aae1706573d4d86a67e0041b158e504b27554b70' OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype OR a.proargnames IS DISTINCT FROM ARRAY['p','successor']::text[] OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0 OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0) THEN RAISE check_violation USING MESSAGE='535 existing recovery helper changed'; END IF; END $pre535$;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_persistent_prestart_recovery(p jsonb,successor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body535$
DECLARE h record; old_phase record; v record; co record; r record; expected record; fn record; mapping jsonb; attachment record; artifact record;
 stamp timestamptz:=clock_timestamp(); old_id uuid:='8c5b0671-54ec-4f64-9412-17cd8c286d58';
 old_job uuid:='0e0accec-81ae-4f0e-b550-f80d53446e79';
 case_root_id uuid:='7d4b85ba-a0ec-4348-ac11-3401c6bded47';
 public_id uuid:='9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c';
 case_revision_id uuid:='7ac04190-a21c-41f9-b121-353680e38fb9';
 logical_op text:='persistent.candidate.7ac04190a21c41f9b121353680e38fb9.repair';
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' OR current_setting('session_replication_role')<>'origin'
 THEN RAISE check_violation USING MESSAGE='535 original sandbox transaction required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('persistent-public-phase'),hashtext(public_id::text));
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','case_key','task_ref','failed_phase_id','failed_frame_hash',
  'failed_payload_hash','old_helper_hash','repaired_helper_hash','archived_review_hash','code_contract','checked_at','valid_until']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'persistent_prestart_proof_v1'
  OR p->>'case_key' IS DISTINCT FROM 'persistent_normal_prepare_json_precedence_v1'
  OR p->>'failed_phase_id' IS DISTINCT FROM old_id::text
  OR p->>'failed_frame_hash' IS DISTINCT FROM 'd1f8a528b05847766cf70e28129e2474b846487792e798b8d0cf5284309451ee'
  OR p->>'failed_payload_hash' IS DISTINCT FROM '7fa9a52ffaaa82ef7109e773a0dcb01fdcf2cddf4e1e259cb8409f55feb55129'
  OR p->>'old_helper_hash' IS DISTINCT FROM '1e4139459d5138c5af7f205a226b0747e27f9dcaaa846acce3a8a41dc66e9401'
  OR p->>'repaired_helper_hash' IS DISTINCT FROM 'ff5c3fbe5a46b010f34870d36cfe387e62f212748a1ae7c3694f5004eea0b87e'
  OR p->>'archived_review_hash' IS DISTINCT FROM 'db6e0ab123d07cb166c52a138395f690e075c49a1dd609c0a1037e7b8d8a3907'
  OR p->'code_contract' IS DISTINCT FROM jsonb_build_object(
   'persistent_pack_candidate.py','f87681ccaa20cd24cd95cfa5daf774a645c7501c00946f3e7de92d88c4cb8cfd',
   'native_review_investigation.py','cd3c4ca774efad8dd4450f924fcc6a09ec475389b742afc03e1e4faeb08fc83d',
   'shared_review.py','8f3dc93a12d3c89b4b1d565e75fe54bf1bb7a37fbc6dc96b858e8af6ed0606f8')
  OR COALESCE(p->>'checked_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
  OR COALESCE(p->>'valid_until' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
  OR COALESCE((p->>'checked_at')::timestamptz<=stamp AND stamp<(p->>'valid_until')::timestamptz
    AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '900 seconds',false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='535 exact registered case and bounded proof required'; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal
  WHERE id='6739d3c5-6619-44ce-970f-0ab1e49f3acc' AND pack_task_id=id AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR p->'task_ref' IS DISTINCT FROM h.payload_json->'ref'
  OR h.payload_json->'ref'->>'public_task_id' IS DISTINCT FROM public_id::text
 THEN RAISE check_violation USING MESSAGE='535 exact original PRIVATE task required'; END IF;
 PERFORM 1 FROM tutor_item_supply_user_epochs WHERE user_id=h.user_id AND epoch=h.epoch AND enabled FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='535 current original epoch required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_scopes WHERE id=h.scope_id AND user_id=h.user_id AND epoch=h.epoch FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE
  pack_task_id=h.id AND user_id=h.user_id AND epoch=h.epoch AND record_kind IN('pause','stop'))
 THEN RAISE check_violation USING MESSAGE='535 stopped or stale original scope'; END IF;
 -- Current exact receiver/immutable contracts; historical total-deny theorem is
 -- the registered one-case contract above, not caller attestations or raw logs.
 FOR expected IN SELECT * FROM (VALUES
 ('item_supply_internal.assert_persistent_normal_repair(jsonb)','ff5c3fbe5a46b010f34870d36cfe387e62f212748a1ae7c3694f5004eea0b87e'),
 ('item_supply_internal.enforce_shared_review_investigation_insert()','4623fa4db4a521346d34be436d14c53e1444273ee4968011e879e53494245f41'),
 ('public.enforce_item_supply_immutable()','99d2a974483a38163a65cfab06f7d3f0576641366b8ab03fa0fd3da0c386290d'),
 ('item_supply_internal.enforce_persistent_pack_journal_insert()','59cbbd4d9fcd1eca6f3db40e0733cc9ffdcdd2e77dc14b87bdf6c6d396617de8'),
 ('public.deny_item_supply_continuation_generation()','c53119562565c0fa1cc5f92c5cbb7e0bea467a0b4e50fc13a917104b9892961c'),
 ('public.enforce_item_supply_shared_execution_header()','0fa02716cb0daa895f6a140fe40ef2e9abde3543202c5ba5576088a304dcdd69'),
 ('item_supply_internal.public_normal_mapping_current(uuid,uuid,bigint)','f16fb7d1eb82deb33ce1492db4faa56c8ad43cfc3a4086df6665f637583e488d'),
 ('item_supply_internal.public_native_source_current(jsonb)','82dcdf136055421ab5c7f60f0606308abdb23d57214bfa83e0d22c92ad4447e2')
 ) AS pins(signature,sha) LOOP
  SELECT x.*,l.lanname INTO fn FROM pg_proc x JOIN pg_language l ON l.oid=x.prolang WHERE x.oid=to_regprocedure(expected.signature);
  IF NOT FOUND OR encode(sha256(convert_to(fn.prosrc,'UTF8')),'hex') IS DISTINCT FROM expected.sha
   OR fn.prokind<>'f' OR fn.lanname<>'plpgsql' OR NOT fn.prosecdef OR fn.proisstrict OR fn.proretset
   OR fn.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR fn.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
   OR fn.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  THEN RAISE check_violation USING MESSAGE='535 current original receiver fingerprint required'; END IF;
 END LOOP;
 FOR expected IN SELECT * FROM (VALUES
 ('tutor_item_supply_shared_persistent_pack_journal','persistent_journal_insert','item_supply_internal.enforce_persistent_pack_journal_insert()',7),
 ('tutor_item_supply_shared_persistent_pack_journal','persistent_journal_immutable','public.enforce_item_supply_immutable()',27),
 ('tutor_item_supply_shared_reservations','supply_continuation_no_generation','public.deny_item_supply_continuation_generation()',7),
 ('tutor_item_supply_shared_reservations','supply_mutation','public.enforce_item_supply_immutable()',27),
 ('tutor_item_supply_shared_reservations','supply_shared_execution_header','public.enforce_item_supply_shared_execution_header()',7),
 ('tutor_item_supply_shared_review_investigation_preparations','shared_review_investigation_insert','item_supply_internal.enforce_shared_review_investigation_insert()',7),
 ('tutor_item_supply_shared_review_investigation_preparations','shared_review_investigation_immutable','public.enforce_item_supply_immutable()',27),
 ('tutor_item_supply_shared_review_investigation_receipts','shared_review_investigation_insert','item_supply_internal.enforce_shared_review_investigation_insert()',7),
 ('tutor_item_supply_shared_review_investigation_receipts','shared_review_investigation_immutable','public.enforce_item_supply_immutable()',27)
 ) AS guards(tbl,trigger_name,signature,trigger_type) LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid=to_regclass('public.'||expected.tbl)
    AND tgname=expected.trigger_name AND tgenabled='O' AND tgfoid=to_regprocedure(expected.signature)
    AND tgtype=expected.trigger_type AND NOT tgisinternal AND tgqual IS NULL
    AND tgnargs=(CASE WHEN expected.trigger_type=27 THEN 1 ELSE 0 END)
    AND encode(tgargs,'hex')=(CASE WHEN expected.trigger_type=27 THEN '73686172656400' ELSE '' END))
  THEN RAISE check_violation USING MESSAGE='535 enabled original mandatory trigger required'; END IF;
 END LOOP;
 mapping:=item_supply_internal.public_normal_mapping_current((h.payload_json->'ref'->>'mapping_receipt_id')::uuid,h.user_id,h.epoch::bigint);
 IF mapping IS NULL THEN RAISE check_violation USING MESSAGE='535 current original source mapping required'; END IF;
 SELECT j.* INTO old_phase FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.phase_id=old_id AND record_kind='phase' FOR SHARE;
 IF NOT FOUND OR (old_phase.public_task_id,old_phase.root_id,old_phase.job_id,old_phase.operation_key,old_phase.payload_hash)
  IS DISTINCT FROM (public_id,case_root_id,old_job,logical_op||'.frame.1',p->>'failed_payload_hash')
  OR (old_phase.payload_json->>'frame_hash',old_phase.payload_json->>'revision_id',old_phase.payload_json->>'public_slot_id',old_phase.payload_json->>'kind')
  IS DISTINCT FROM (p->>'failed_frame_hash',case_revision_id::text,'e14de564-394a-5685-8e0a-07f2dd819a6c','candidate')
 THEN RAISE check_violation USING MESSAGE='535 original frozen phase identity required'; END IF;
 SELECT a.* INTO attachment FROM tutor_item_supply_private_persistent_pack_journal a
  WHERE a.record_kind='phase' AND a.payload_json=jsonb_build_object('schema_version','persistent_private_phase_attachment_v1',
    'phase_id',old_id::text,'public_task_id',public_id::text) FOR SHARE;
 IF NOT FOUND OR (attachment.pack_task_id,attachment.user_id,attachment.epoch,attachment.scope_id,attachment.intent_hash)
  IS DISTINCT FROM (h.id,h.user_id,h.epoch,h.scope_id,h.intent_hash)
  OR h.created_at>old_phase.created_at
  OR attachment.created_at>'2026-10-12T15:13:29.372423+08:00'::timestamptz
  OR (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal a WHERE a.record_kind='phase'
    AND a.payload_json=jsonb_build_object('schema_version','persistent_private_phase_attachment_v1',
      'phase_id',old_id::text,'public_task_id',public_id::text))<>1
 THEN RAISE check_violation USING MESSAGE='535 immutable historical PRIVATE attachment required'; END IF;
 IF (SELECT count(*) FROM tutor_item_supply_shared_persistent_pack_journal WHERE job_id=old_job)<>3
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.job_id=old_job AND (
    (j.phase_id,j.public_task_id,j.root_id,j.operation_key) IS DISTINCT FROM (old_id,public_id,case_root_id,logical_op||'.frame.1')
    OR (CASE j.record_kind
     WHEN 'phase' THEN j.payload_hash IS DISTINCT FROM '7fa9a52ffaaa82ef7109e773a0dcb01fdcf2cddf4e1e259cb8409f55feb55129'
     WHEN 'dispatch_started' THEN j.payload_hash IS DISTINCT FROM '1a1bb9e8e4b7d2a46d47b0ba2df4baa5986c4ac106a79e37c91c1ed3d42606da'
     WHEN 'phase_result' THEN j.payload_hash IS DISTINCT FROM '621416a63197703fdfc2fed51167f645c82cf91181cb00f4dfd581361b2a8965'
     ELSE true END)))
  OR item_supply_internal.controlled_counterexample_held(old_job) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='535 exact immutable UNKNOWN history and no controlled hold required'; END IF;
 SELECT * INTO co FROM tutor_item_supply_shared_job_controls WHERE job_id=old_job FOR SHARE;
 IF NOT FOUND OR co.state IS DISTINCT FROM 'leased' OR co.lease_generation IS DISTINCT FROM 1
  OR co.state_version IS DISTINCT FROM 2 OR co.lease_expires_at IS DISTINCT FROM (old_phase.payload_json->'lease'->>'expires_at')::timestamptz
  OR co.parent_deadline IS DISTINCT FROM (old_phase.payload_json->'lease'->>'parent_deadline')::timestamptz
  OR co.lease_owner IS DISTINCT FROM old_phase.payload_json->'lease'->>'lease_owner'
  OR co.attempt_count IS DISTINCT FROM 1 OR co.breaker_open IS DISTINCT FROM false
  OR (CASE WHEN co.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN co.profile_snapshot_json->'profile' ELSE co.profile_snapshot_json END) IS DISTINCT FROM old_phase.payload_json->'lease'->'profile'
  OR co.lease_expires_at>stamp OR co.parent_deadline>stamp
 THEN RAISE check_violation USING MESSAGE='535 original closed expired control required'; END IF;
 PERFORM 1 FROM tutor_item_supply_development_model_accounting_jobs WHERE job_id=old_job AND batch_id=(old_phase.payload_json->>'batch_id')::uuid FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='535 original accounting binding required'; END IF;
 SELECT j.* INTO v FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.public_task_id=public_id
  AND record_kind IN('version','qualified') AND j.payload_json->>'revision_id'=case_revision_id::text
  ORDER BY created_at DESC,id LIMIT 1 FOR SHARE;
 IF NOT FOUND OR v.root_id IS DISTINCT FROM case_root_id OR v.payload_json->>'public_slot_id' IS DISTINCT FROM old_phase.payload_json->>'public_slot_id'
  OR v.payload_json->>'artifact_id' IS NULL
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.public_task_id=public_id
   AND j.record_kind IN('version','qualified') AND j.payload_json->'public_slot_id'=v.payload_json->'public_slot_id'
   AND (j.payload_json->>'revision_seq')::integer>(v.payload_json->>'revision_seq')::integer)
 THEN RAISE check_violation USING MESSAGE='535 exact retained revision and artifact required'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_preparations WHERE job_id=old_job OR generation_artifact_id=(v.payload_json->>'artifact_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_receipts WHERE job_id=old_job OR generation_artifact_id=(v.payload_json->>'artifact_id')::uuid)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations rs WHERE rs.job_id=old_job OR
    (rs.root_id=old_phase.root_id AND rs.reservation_key LIKE 'investigate.'||replace(v.payload_json->>'artifact_id','-','')||'.%'))
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_job_events WHERE job_id=old_job)
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE
    record_kind IN('stage_started','stage_result') AND operation_key LIKE 'persistent.stage.'||replace(case_revision_id::text,'-','')||'.%')
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.record_kind='phase'
    AND (j.payload_json->>'revision_id'=case_revision_id::text OR (j.public_task_id=public_id AND
      (j.operation_key=logical_op OR j.operation_key LIKE logical_op||'.frame.%')))
    AND j.phase_id<>old_id AND (successor IS NULL OR j.phase_id<>successor))
 THEN RAISE check_violation USING MESSAGE='535 prior preparation reservation stage or alternate frame ambiguity'; END IF;
 IF successor IS NOT NULL THEN
  SELECT j.*,j.xmin::text::bigint AS row_xid INTO r FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.phase_id=successor AND record_kind='phase' FOR SHARE;
  IF NOT FOUND OR (r.public_task_id,r.root_id,r.operation_key,r.payload_json->>'revision_id',r.payload_json->>'public_slot_id',r.payload_json->>'kind')
   IS DISTINCT FROM (public_id,case_root_id,logical_op||'.frame.2',case_revision_id::text,old_phase.payload_json->>'public_slot_id','candidate')
   OR r.job_id=old_job OR r.phase_id=old_id OR r.row_xid<>(txid_current()%4294967296)
   OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=successor AND record_kind<>'phase')
  THEN RAISE check_violation USING MESSAGE='535 exact fresh same-operation successor required'; END IF;
  PERFORM item_supply_internal.assert_persistent_pack_phase(r.payload_json);
 END IF;
 -- The preparation allowance never extends a source or ordinary phase deadline.
 SELECT * INTO artifact FROM tutor_item_supply_shared_generation_artifacts WHERE id=(v.payload_json->>'artifact_id')::uuid FOR SHARE;
 IF NOT FOUND OR artifact.root_id IS DISTINCT FROM old_phase.root_id
  OR item_supply_internal.public_native_source_current(jsonb_build_object('request',artifact.request_json,'ref',h.payload_json->'ref')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='535 original artifact source must remain current'; END IF;
 stamp:=clock_timestamp();
 IF stamp>=(p->>'valid_until')::timestamptz
 THEN RAISE check_violation USING MESSAGE='535 bounded preparation proof expired after checks'; END IF;
 IF successor IS NOT NULL THEN
  IF stamp>=(r.payload_json->>'valid_until')::timestamptz
  THEN RAISE check_violation USING MESSAGE='535 original successor deadline expired after checks'; END IF;
 END IF;
END $body535$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_prestart_recovery(jsonb,uuid) FROM PUBLIC;

DO $pre535$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_persistent_prestart_insert()'); IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM '11130ef827795132720e1415b86d2871c3c24afb2605c74ca107871431702ab6' OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype OR a.proargnames IS DISTINCT FROM NULL::text[] OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0 OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0) THEN RAISE check_violation USING MESSAGE='535 existing recovery helper changed'; END IF; END $pre535$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_persistent_prestart_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body535$
DECLARE p jsonb:=NEW.payload_json; h record; proof record; next_phase record; key_base text;
BEGIN
 IF NEW.record_kind NOT IN('prestart_proof','prestart_binding') THEN RETURN NEW; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR (NEW.pack_task_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.intent_hash)
  IS DISTINCT FROM (h.id,h.user_id,h.epoch,h.scope_id,h.intent_hash)
  OR h.id IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid
 THEN RAISE check_violation USING MESSAGE='535 same PRIVATE original task namespace required'; END IF;
 key_base:='p7.prestart.'||replace(h.id::text,'-','')||'.8c5b067154ec4f64941217cd8c286d58';
 IF NEW.record_kind='prestart_proof' THEN
  IF NEW.operation_key IS DISTINCT FROM key_base||'.proof' OR p->'task_ref' IS DISTINCT FROM h.payload_json->'ref'
  THEN RAISE check_violation USING MESSAGE='535 canonical original proof key required'; END IF;
  PERFORM item_supply_internal.assert_persistent_prestart_recovery(p,NULL);
  IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=h.id
    AND user_id=h.user_id AND epoch=h.epoch AND record_kind='prestart_binding')
  THEN RAISE check_violation USING MESSAGE='535 original proof already consumed'; END IF;
 ELSE
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','proof_id','failed_phase_id','successor_phase_id','successor_frame_hash','txid']) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM 'persistent_prestart_binding_v1'
   OR p->>'failed_phase_id' IS DISTINCT FROM '8c5b0671-54ec-4f64-9412-17cd8c286d58'
   OR p->>'txid' IS DISTINCT FROM txid_current()::text
   OR NEW.operation_key IS DISTINCT FROM key_base||'.binding'
   OR COALESCE(p->>'proof_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
   OR COALESCE(p->>'successor_phase_id' ~ '^[0-9a-f-]{36}$',false) IS DISTINCT FROM true
  THEN RAISE check_violation USING MESSAGE='535 closed original binding key and transaction required'; END IF;
  SELECT * INTO proof FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'proof_id')::uuid
   AND pack_task_id=h.id AND user_id=h.user_id AND epoch=h.epoch AND scope_id=h.scope_id AND intent_hash=h.intent_hash
   AND record_kind='prestart_proof' AND operation_key=key_base||'.proof' FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='535 actual same-scope original proof required'; END IF;
  PERFORM item_supply_internal.assert_persistent_prestart_recovery(proof.payload_json,(p->>'successor_phase_id')::uuid);
  SELECT j.*,j.xmin::text::bigint AS row_xid INTO next_phase FROM tutor_item_supply_shared_persistent_pack_journal j
   WHERE j.phase_id=(p->>'successor_phase_id')::uuid AND j.record_kind='phase' FOR SHARE;
  IF NOT FOUND OR p->>'successor_frame_hash' IS DISTINCT FROM next_phase.payload_json->>'frame_hash'
   OR next_phase.row_xid<>(txid_current()%4294967296)
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal a WHERE a.pack_task_id=h.id
    AND a.user_id=h.user_id AND a.epoch=h.epoch AND a.scope_id=h.scope_id AND a.record_kind='phase'
    AND a.payload_json=jsonb_build_object('schema_version','persistent_private_phase_attachment_v1',
      'phase_id',p->>'successor_phase_id','public_task_id',next_phase.public_task_id::text))
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal b WHERE b.record_kind='prestart_binding'
    AND (b.payload_json->>'proof_id'=proof.id::text OR b.payload_json->>'successor_phase_id'=p->>'successor_phase_id'))
  THEN RAISE check_violation USING MESSAGE='535 fresh bound successor or one-use proof required'; END IF;
 END IF;
 RETURN NEW;
END $body535$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_persistent_prestart_insert() FROM PUBLIC;

DO $check535$ DECLARE d text; BEGIN
 SELECT pg_get_constraintdef(oid) INTO d FROM pg_constraint WHERE conrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass AND conname='tutor_item_supply_private_persistent_pack_jou_record_kind_check' AND contype='c' AND convalidated;
 IF d=$expected535$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text])))$expected535$ THEN
  ALTER TABLE tutor_item_supply_private_persistent_pack_journal DROP CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check;
  ALTER TABLE tutor_item_supply_private_persistent_pack_journal ADD CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check CHECK(record_kind IN('task','phase','pause','stop','private_attachment','private_status','prestart_proof','prestart_binding'));
 ELSIF d IS DISTINCT FROM $expected535$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text])))$expected535$ THEN RAISE check_violation USING MESSAGE='535 exact private kind CHECK required'; END IF;
END $check535$;

DO $trigger535$ DECLARE t record; BEGIN
 SELECT *,pg_get_triggerdef(oid) AS definition INTO t FROM pg_trigger WHERE tgrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass AND tgname='a001_persistent_prestart_insert';
 IF FOUND THEN
  IF t.definition IS DISTINCT FROM $expected535$CREATE TRIGGER a001_persistent_prestart_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW WHEN ((new.record_kind = ANY (ARRAY['prestart_proof'::text, 'prestart_binding'::text]))) EXECUTE FUNCTION item_supply_internal.enforce_persistent_prestart_insert()$expected535$ OR t.tgenabled<>'O' OR t.tgisinternal THEN RAISE check_violation USING MESSAGE='535 recovery trigger changed'; END IF;
 ELSE
  CREATE TRIGGER a001_persistent_prestart_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal FOR EACH ROW WHEN (NEW.record_kind IN('prestart_proof','prestart_binding')) EXECUTE FUNCTION item_supply_internal.enforce_persistent_prestart_insert();
 END IF;
END $trigger535$;
