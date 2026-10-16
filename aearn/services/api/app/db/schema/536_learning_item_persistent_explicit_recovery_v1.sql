--536 explicit human-approved NEW attempt, not proof of historical zero HTTP.
-- Preserve both UNKNOWNs, original receipts/reservations and all535 facts.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_user<>'aearn_b1d_runtime_20261001' THEN RAISE check_violation USING MESSAGE='536 exact sandbox owner required'; END IF; END $$;

DO $guard536$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.assert_persistent_explicit_recovery(jsonb,uuid)'); IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM 'ada943c596eab4b5f50296ffd1f8972cf57ac3e0ef3e400c8b3e76e9c8093d3c' OR a.proargnames IS DISTINCT FROM ARRAY['p','successor']::text[] OR a.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0 OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0) THEN RAISE check_violation USING MESSAGE='536 unexpected existing receiver'; END IF; END $guard536$;
CREATE OR REPLACE FUNCTION item_supply_internal.assert_persistent_explicit_recovery(p jsonb,successor uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body536$
DECLARE case_task constant uuid:='6739d3c5-6619-44ce-970f-0ab1e49f3acc';
 case_public constant uuid:='9378a05f-b33e-5fc9-9bd7-6f073c2e6c8c';
 case_root constant uuid:='7d4b85ba-a0ec-4348-ac11-3401c6bded47';
 case_revision constant text:='7ac04190-a21c-41f9-b121-353680e38fb9';
 case_operation constant text:='persistent.candidate.7ac04190a21c41f9b121353680e38fb9.repair';
 case_stage constant text:='persistent.stage.7ac04190a21c41f9b121353680e38fb9.investigation';
 old_jobs uuid[]:=ARRAY['0e0accec-81ae-4f0e-b550-f80d53446e79','6bf48d8d-c32a-4ae7-b3a4-68adceae15c2']::uuid[];
 h record; expected record; actual_hash text; actual_count bigint; phase_row record; binding_row record; approval_row record;
 a record; stamp timestamptz; bound boolean:=false;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001' OR current_setting('transaction_isolation')<>'read committed'
  OR current_setting('transaction_read_only')<>'off' OR current_setting('session_replication_role')<>'origin'
  OR current_setting('TimeZone')<>'Asia/Shanghai'
 THEN RAISE check_violation USING MESSAGE='536 exact original sandbox transaction and snapshot timezone required'; END IF;
 PERFORM pg_advisory_xact_lock(hashtext('persistent-public-phase'),hashtext(case_public::text));
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','case_key','authorization_sha256','basis','task_ref',
  'failed_phase_id','retained_unknown_phase_ids','logical_stage_key','attempt_key','checked_at','valid_until']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'persistent_explicit_recovery_approval_v1'
  OR p->>'case_key' IS DISTINCT FROM 'explicit_stage_started_release_20261012'
  OR p->>'authorization_sha256' IS DISTINCT FROM '65e73bab11b2179ae8fb0543f360e6f9b812657496813f0626acc14d286dde43'
  OR p->>'basis' IS DISTINCT FROM 'new_attempt_despite_retained_uncertainty'
  OR p->>'failed_phase_id' IS DISTINCT FROM '92f71c9e-94fd-4d7f-8bf9-9a15a920bcee'
  OR p->'retained_unknown_phase_ids' IS DISTINCT FROM '["8c5b0671-54ec-4f64-9412-17cd8c286d58","92f71c9e-94fd-4d7f-8bf9-9a15a920bcee"]'::jsonb
  OR p->>'logical_stage_key' IS DISTINCT FROM case_stage
  OR p->>'attempt_key' IS DISTINCT FROM case_stage||'.explicit_release_20261012'
  OR COALESCE(p->>'checked_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
  OR COALESCE(p->>'valid_until' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$',false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='536 only registered explicit new-attempt authorization'; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal WHERE id=case_task AND pack_task_id=id AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR h.payload_hash IS DISTINCT FROM '07e42ce62c1714e093f0e7d5e3ad1928a5da617c8597cfcebce51e7f7ea6b976'
  OR h.payload_json->'ref' IS DISTINCT FROM p->'task_ref'
 THEN RAISE check_violation USING MESSAGE='536 exact original PRIVATE identity required'; END IF;
 PERFORM 1 FROM tutor_item_supply_user_epochs WHERE user_id=h.user_id AND epoch=h.epoch AND enabled FOR SHARE;
 IF NOT FOUND OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=h.id
  AND user_id=h.user_id AND epoch=h.epoch AND record_kind IN('pause','stop'))
 THEN RAISE check_violation USING MESSAGE='536 stopped or stale original epoch'; END IF;
 -- Pin real old rows, including both UNKNOWNs and consumed535 facts. Closed
 -- table names below are server constants; callers cannot supply SQL identifiers.
 FOR expected IN SELECT * FROM (VALUES
('tutor_item_supply_shared_jobs','0e0accec-81ae-4f0e-b550-f80d53446e79'::uuid,'7d8f0640f0173b71675299d04375f0c5'),
('tutor_item_supply_shared_jobs','6bf48d8d-c32a-4ae7-b3a4-68adceae15c2'::uuid,'ef16dee9b76413dc1c5a663e08a617d2'),
('tutor_item_supply_shared_job_controls','34ff556a-7283-4c14-adba-e8e41bb16b3f'::uuid,'654485f95e87212b668f79b616e71248'),
('tutor_item_supply_shared_job_controls','5723d294-e387-4aba-8484-a4358334eba8'::uuid,'3653103336a528da80050cb4d5b8f731'),
('tutor_item_supply_shared_persistent_pack_journal','00507276-272e-4604-8c58-d6f92a1f12de'::uuid,'b0b5b533242d098e1df24ca33ee72dfd'),
('tutor_item_supply_shared_persistent_pack_journal','29bf0021-a7c4-442a-8a44-d69cc831068b'::uuid,'2985daee390b0ffaaf4a96f4f473c05e'),
('tutor_item_supply_shared_persistent_pack_journal','58236c04-6829-48d6-b265-28a3b8c232de'::uuid,'eb5ae085ce6bdf173301411da380d94f'),
('tutor_item_supply_shared_persistent_pack_journal','8746c1dc-65df-4b93-9c00-ba85ae6f24d6'::uuid,'7676fc7cd19ddca05e2c5e59c29b9394'),
('tutor_item_supply_shared_persistent_pack_journal','87507322-435e-448f-8393-4fb16b1ef561'::uuid,'d34bd27b069e4e5101b489a20cd38bee'),
('tutor_item_supply_shared_persistent_pack_journal','bbd5759b-0d56-4f15-aaff-64b9f9f0732c'::uuid,'05e4509266070310fd5554337b0eefc6'),
('tutor_item_supply_shared_persistent_pack_journal','d1956189-c610-4a35-aff9-68016b2757c2'::uuid,'c5ce455ce0e7f62ee8b6d54adaeeb303'),
('tutor_item_supply_shared_review_investigation_preparations','471344bd-5d96-408c-b828-57c45a53c267'::uuid,'621a4dfecd3e6897dcb660a012709e92'),
('tutor_item_supply_shared_reservations','366e4d24-108a-4dc9-b130-4b30c4c34ffe'::uuid,'fd6af8db47b6e3ad457f5effc0937211')
 ) AS pins(tbl,row_id,digest) LOOP
  EXECUTE format('SELECT md5(to_jsonb(t)::text) FROM public.%I t WHERE id=$1 FOR SHARE',expected.tbl)
   INTO actual_hash USING expected.row_id;
  IF actual_hash IS DISTINCT FROM expected.digest THEN RAISE check_violation USING MESSAGE='536 frozen original row changed'; END IF;
 END LOOP;
 FOR expected IN SELECT * FROM (VALUES
 ('tutor_item_supply_shared_jobs','id',2),('tutor_item_supply_shared_job_controls','job_id',2),
 ('tutor_item_supply_shared_persistent_pack_journal','job_id',7),
 ('tutor_item_supply_shared_review_investigation_preparations','job_id',1),
 ('tutor_item_supply_shared_review_investigation_receipts','job_id',0),
 ('tutor_item_supply_shared_reservations','job_id',1),('tutor_item_supply_shared_runtime_settlements','job_id',0)
 ) AS counts(tbl,col,n) LOOP
  IF expected.tbl='tutor_item_supply_shared_runtime_settlements' THEN
   SELECT count(*) INTO actual_count FROM public.tutor_item_supply_shared_runtime_settlements s
    JOIN public.tutor_item_supply_shared_reservations r ON r.id=s.reservation_id WHERE r.job_id=ANY(old_jobs);
  ELSE
   EXECUTE format('SELECT count(*) FROM public.%I WHERE %I=ANY($1)',expected.tbl,expected.col) INTO actual_count USING old_jobs;
  END IF;
  IF actual_count IS DISTINCT FROM expected.n::bigint THEN RAISE check_violation USING MESSAGE='536 new old-case evidence requires separate review'; END IF;
 END LOOP;
 FOR expected IN SELECT * FROM (VALUES
('4c3979f1-eb90-4f84-b036-344f026dc20b'::uuid,'prestart_binding','6cb11d40416d57c0c144e821efa77c097fe2f1f07e5c05f5f63190e120643bcc'),
('4a4dcaf7-de04-4c7c-869b-80cc8cac2758'::uuid,'prestart_proof','7373bd119461bf1bc2ca530f246fe050807690034551d3ee1feeb3a02b8588ce'),
('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'task','07e42ce62c1714e093f0e7d5e3ad1928a5da617c8597cfcebce51e7f7ea6b976')
 ) AS pins(row_id,kind,digest) LOOP
  PERFORM 1 FROM tutor_item_supply_private_persistent_pack_journal WHERE id=expected.row_id AND record_kind=expected.kind
   AND payload_hash=expected.digest AND pack_task_id=h.id AND user_id=h.user_id AND epoch=h.epoch AND scope_id=h.scope_id FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='536 retained original535 facts required'; END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_job_controls WHERE job_id=ANY(old_jobs)
   AND (lease_expires_at>clock_timestamp() OR parent_deadline>clock_timestamp()))
  OR item_supply_internal.controlled_counterexample_held(old_jobs[1]) IS DISTINCT FROM false
  OR item_supply_internal.controlled_counterexample_held(old_jobs[2]) IS DISTINCT FROM false
 THEN RAISE check_violation USING MESSAGE='536 old lease remains untouched or controlled hold denied'; END IF;
 IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j WHERE j.record_kind='phase'
  AND (j.payload_json->>'revision_id'=case_revision OR (j.public_task_id=case_public AND j.operation_key LIKE case_operation||'.frame.%'))
  AND j.phase_id NOT IN('8c5b0671-54ec-4f64-9412-17cd8c286d58','92f71c9e-94fd-4d7f-8bf9-9a15a920bcee')
  AND (successor IS NULL OR j.phase_id<>successor))
 THEN RAISE check_violation USING MESSAGE='536 unexpected same-operation frame'; END IF;
 SELECT * INTO binding_row FROM tutor_item_supply_private_persistent_pack_journal WHERE pack_task_id=h.id
  AND user_id=h.user_id AND epoch=h.epoch AND record_kind='explicit_recovery_binding' FOR SHARE;
 IF FOUND THEN
  IF successor IS NULL OR binding_row.payload_json->>'successor_phase_id' IS DISTINCT FROM successor::text
  THEN RAISE check_violation USING MESSAGE='explicit_recovery_already_bound'; END IF;
  SELECT * INTO approval_row FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(binding_row.payload_json->>'approval_id')::uuid
   AND pack_task_id=h.id AND user_id=h.user_id AND epoch=h.epoch AND scope_id=h.scope_id AND record_kind='explicit_recovery_approval' FOR SHARE;
  IF NOT FOUND OR approval_row.payload_json IS DISTINCT FROM p
  THEN RAISE check_violation USING MESSAGE='536 bound approval identity mismatch'; END IF;
  bound:=true;
 END IF;
 IF successor IS NOT NULL THEN
  SELECT j.*,j.xmin::text::bigint AS row_xid INTO phase_row FROM tutor_item_supply_shared_persistent_pack_journal j
   WHERE j.phase_id=successor AND j.record_kind='phase' FOR SHARE;
  IF NOT FOUND OR (phase_row.public_task_id,phase_row.root_id,phase_row.operation_key,
    phase_row.payload_json->>'revision_id',phase_row.payload_json->>'public_slot_id',phase_row.payload_json->>'kind')
   IS DISTINCT FROM (case_public,case_root,case_operation||'.frame.3',case_revision,'e14de564-394a-5685-8e0a-07f2dd819a6c','candidate')
   OR phase_row.job_id=ANY(old_jobs) OR (NOT bound AND phase_row.row_xid<>(txid_current()%4294967296))
  THEN RAISE check_violation USING MESSAGE='536 exact fresh original frame3 required'; END IF;
  PERFORM item_supply_internal.assert_persistent_pack_phase(phase_row.payload_json);
 END IF;
 -- Original current source checks apply independently of the human approval.
 SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id='a6433494-8167-4f2b-ad39-82a20ce62cde' FOR SHARE;
 IF NOT FOUND OR a.root_id IS DISTINCT FROM case_root
  OR item_supply_internal.public_native_source_current(jsonb_build_object('request',a.request_json,'ref',h.payload_json->'ref')) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='536 current original source required'; END IF;
 stamp:=clock_timestamp();
 IF NOT bound AND COALESCE((p->>'checked_at')::timestamptz<=stamp AND stamp<(p->>'valid_until')::timestamptz
   AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '900 seconds',false) IS DISTINCT FROM true
 THEN RAISE check_violation USING MESSAGE='536 explicit allocation approval expired'; END IF;
 IF successor IS NOT NULL THEN
  IF stamp>=(phase_row.payload_json->>'valid_until')::timestamptz
  THEN RAISE check_violation USING MESSAGE='536 ordinary successor deadline expired'; END IF;
 END IF;
END $body536$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_persistent_explicit_recovery(jsonb,uuid) FROM PUBLIC;

DO $guard536$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_persistent_explicit_insert()'); IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM '0b006b0065efa42bc12a70650e5ae19757e947ecd6c42bec7e2fe494cecb2e2c' OR a.proargnames IS DISTINCT FROM NULL::text[] OR a.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0 OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0) THEN RAISE check_violation USING MESSAGE='536 unexpected existing receiver'; END IF; END $guard536$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_persistent_explicit_insert() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body536$
DECLARE p jsonb:=NEW.payload_json; h record; approval record; next_phase record;
 key_base constant text:='p7.explicit.6739d3c5661944ce970f0ab1e49f3acc.92f71c9e94fd4d7f8bf99a15a920bcee';
 logical_stage constant text:='persistent.stage.7ac04190a21c41f9b121353680e38fb9.investigation';
BEGIN
 IF NEW.record_kind NOT IN('explicit_recovery_approval','explicit_recovery_binding') THEN RETURN NEW; END IF;
 SELECT * INTO h FROM tutor_item_supply_private_persistent_pack_journal WHERE id=NEW.pack_task_id AND record_kind='task' FOR SHARE;
 IF NOT FOUND OR h.id IS DISTINCT FROM '6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid
  OR (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.intent_hash) IS DISTINCT FROM (h.user_id,h.epoch,h.scope_id,h.intent_hash)
 THEN RAISE check_violation USING MESSAGE='536 original PRIVATE namespace required'; END IF;
 IF NEW.record_kind='explicit_recovery_approval' THEN
  IF NEW.operation_key IS DISTINCT FROM key_base||'.approval' OR p->'task_ref' IS DISTINCT FROM h.payload_json->'ref'
  THEN RAISE check_violation USING MESSAGE='536 canonical approval key required'; END IF;
  PERFORM item_supply_internal.assert_persistent_explicit_recovery(p,NULL);
 ELSE
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','approval_id','failed_phase_id','successor_phase_id',
    'successor_frame_hash','logical_stage_key','attempt_key','txid']) IS DISTINCT FROM true
   OR p->>'schema_version' IS DISTINCT FROM 'persistent_explicit_recovery_binding_v1'
   OR p->>'failed_phase_id' IS DISTINCT FROM '92f71c9e-94fd-4d7f-8bf9-9a15a920bcee'
   OR p->>'logical_stage_key' IS DISTINCT FROM logical_stage
   OR p->>'attempt_key' IS DISTINCT FROM logical_stage||'.explicit_release_20261012'
   OR p->>'txid' IS DISTINCT FROM txid_current()::text OR NEW.operation_key IS DISTINCT FROM key_base||'.binding'
  THEN RAISE check_violation USING MESSAGE='536 canonical one-use binding required'; END IF;
  SELECT * INTO approval FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'approval_id')::uuid
   AND pack_task_id=h.id AND user_id=h.user_id AND epoch=h.epoch AND scope_id=h.scope_id AND intent_hash=h.intent_hash
   AND record_kind='explicit_recovery_approval' AND operation_key=key_base||'.approval' FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='536 actual original approval required'; END IF;
  PERFORM item_supply_internal.assert_persistent_explicit_recovery(approval.payload_json,(p->>'successor_phase_id')::uuid);
  SELECT j.*,j.xmin::text::bigint AS row_xid INTO next_phase FROM tutor_item_supply_shared_persistent_pack_journal j
   WHERE j.phase_id=(p->>'successor_phase_id')::uuid AND j.record_kind='phase' FOR SHARE;
  IF NOT FOUND OR next_phase.row_xid<>(txid_current()%4294967296)
   OR p->>'successor_frame_hash' IS DISTINCT FROM next_phase.payload_json->>'frame_hash'
   OR EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal b WHERE b.record_kind='explicit_recovery_binding'
     AND (b.payload_json->>'approval_id'=approval.id::text OR b.payload_json->>'successor_phase_id'=p->>'successor_phase_id'))
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal a WHERE a.record_kind='phase'
     AND a.pack_task_id=h.id AND a.user_id=h.user_id AND a.epoch=h.epoch AND a.scope_id=h.scope_id
     AND a.payload_json=jsonb_build_object('schema_version','persistent_private_phase_attachment_v1',
       'phase_id',p->>'successor_phase_id','public_task_id',next_phase.public_task_id::text))
  THEN RAISE check_violation USING MESSAGE='536 exact unspent approval and new phase attachment required'; END IF;
 END IF;
 RETURN NEW;
END $body536$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_persistent_explicit_insert() FROM PUBLIC;

DO $guard536$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_persistent_explicit_stage()'); IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM '747bccb205b98f5e1358044fd0f83e64979e3ef2b9eb5a6de16d39f96296ac75' OR a.proargnames IS DISTINCT FROM NULL::text[] OR a.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0 OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0) THEN RAISE check_violation USING MESSAGE='536 unexpected existing receiver'; END IF; END $guard536$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_persistent_explicit_stage() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body536$
DECLARE b record; a record; prep record; receipt record;
 attempt_key constant text:='persistent.stage.7ac04190a21c41f9b121353680e38fb9.investigation.explicit_release_20261012';
BEGIN
 IF NEW.record_kind NOT IN('stage_started','stage_result') THEN RETURN NEW; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='explicit_recovery_binding'
  AND payload_json->>'successor_phase_id'=NEW.phase_id::text FOR SHARE;
 IF NOT FOUND THEN
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j
    WHERE j.record_kind='phase' AND j.phase_id=NEW.phase_id
     AND j.operation_key='persistent.candidate.7ac04190a21c41f9b121353680e38fb9.repair.frame.3')
   OR left(NEW.operation_key,length('persistent.stage.7ac04190a21c41f9b121353680e38fb9.investigation.'))
    ='persistent.stage.7ac04190a21c41f9b121353680e38fb9.investigation.'
  THEN RAISE check_violation USING MESSAGE='536 unbound registered investigation attempt denied'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.payload_json->>'stage' IS DISTINCT FROM 'investigation' AND NEW.operation_key<>attempt_key THEN RETURN NEW; END IF;
 IF NEW.operation_key IS DISTINCT FROM attempt_key OR NEW.payload_json->>'operation_key' IS DISTINCT FROM attempt_key
  OR NEW.payload_json->>'stage' IS DISTINCT FROM 'investigation'
 THEN RAISE check_violation USING MESSAGE='536 exact authorized investigation attempt identity required'; END IF;
 SELECT * INTO a FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(b.payload_json->>'approval_id')::uuid
  AND record_kind='explicit_recovery_approval' AND pack_task_id=b.pack_task_id AND user_id=b.user_id AND epoch=b.epoch AND scope_id=b.scope_id FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='536 actual bound approval required'; END IF;
 PERFORM item_supply_internal.assert_persistent_explicit_recovery(a.payload_json,NEW.phase_id);
 SELECT * INTO prep FROM tutor_item_supply_shared_review_investigation_preparations WHERE job_id=NEW.job_id
  AND root_id=NEW.root_id AND review_receipt_id='260eb494-d08b-43a3-b05e-ac4b54c1f5eb'
  AND payload_json->'persistent_frame'->'phase'->>'phase_id'=NEW.phase_id::text FOR SHARE;
 IF NOT FOUND OR prep.id='471344bd-5d96-408c-b828-57c45a53c267'::uuid
 THEN RAISE check_violation USING MESSAGE='536 new original investigation preparation required'; END IF;
 IF NEW.record_kind='stage_started' THEN
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE operation_key=attempt_key AND record_kind IN('stage_started','stage_result'))
  THEN RAISE check_violation USING MESSAGE='536 investigation attempt once consumed'; END IF;
 ELSE
  PERFORM 1 FROM tutor_item_supply_shared_persistent_pack_journal WHERE phase_id=NEW.phase_id AND job_id=NEW.job_id
   AND operation_key=attempt_key AND record_kind='stage_started' FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='536 same-attempt stage start required'; END IF;
  SELECT * INTO receipt FROM tutor_item_supply_shared_review_investigation_receipts WHERE id=(NEW.payload_json->>'receipt_id')::uuid FOR SHARE;
  IF NOT FOUND OR (receipt.preparation_id,receipt.job_id,receipt.root_id,receipt.reservation_id)
   IS DISTINCT FROM (prep.id,NEW.job_id,NEW.root_id,prep.reservation_id)
  THEN RAISE check_violation USING MESSAGE='536 result must reference new original attempt receipt'; END IF;
 END IF;
 RETURN NEW;
END $body536$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_persistent_explicit_stage() FROM PUBLIC;

DO $guard536$ DECLARE a record; BEGIN SELECT p.*,l.lanname INTO a FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=to_regprocedure('item_supply_internal.enforce_persistent_explicit_preparation()'); IF FOUND AND (encode(sha256(convert_to(a.prosrc,'UTF8')),'hex') IS DISTINCT FROM '5d3098447a1c47bd5f1f1897ab4be55ba35bf4c9a0dc05e476440f15fcb6ce28' OR a.proargnames IS DISTINCT FROM NULL::text[] OR a.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype OR a.lanname<>'plpgsql' OR a.prokind<>'f' OR NOT a.prosecdef OR a.proretset OR a.proisstrict OR a.proleakproof OR a.provolatile<>'v' OR a.proparallel<>'u' OR a.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole OR a.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] OR a.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'] OR a.proallargtypes IS NOT NULL OR a.proargmodes IS NOT NULL OR a.provariadic<>0 OR a.pronargdefaults<>0 OR a.procost<>100 OR a.prorows<>0 OR a.prosupport<>0) THEN RAISE check_violation USING MESSAGE='536 unexpected existing receiver'; END IF; END $guard536$;
CREATE OR REPLACE FUNCTION item_supply_internal.enforce_persistent_explicit_preparation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $body536$
DECLARE b record; a record; phase_row record;
 frame_op constant text:='persistent.candidate.7ac04190a21c41f9b121353680e38fb9.repair.frame.3';
BEGIN
 SELECT * INTO b FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='explicit_recovery_binding'
  AND payload_json->>'successor_phase_id'=NEW.payload_json->'persistent_frame'->'phase'->>'phase_id' FOR SHARE;
 IF NOT FOUND THEN
  IF NEW.payload_json->'persistent_frame'->'phase'->>'operation_key'=frame_op THEN RAISE check_violation USING MESSAGE='536 forged second bucket denied'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO a FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(b.payload_json->>'approval_id')::uuid
  AND record_kind='explicit_recovery_approval' AND pack_task_id=b.pack_task_id AND user_id=b.user_id AND epoch=b.epoch AND scope_id=b.scope_id FOR SHARE;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='536 original bound approval required'; END IF;
 PERFORM item_supply_internal.assert_persistent_explicit_recovery(a.payload_json,(b.payload_json->>'successor_phase_id')::uuid);
 SELECT * INTO phase_row FROM tutor_item_supply_shared_persistent_pack_journal WHERE record_kind='phase'
  AND phase_id=(b.payload_json->>'successor_phase_id')::uuid FOR SHARE;
 IF NOT FOUND OR (NEW.job_id,NEW.root_id,NEW.review_receipt_id,NEW.generation_artifact_id)
  IS DISTINCT FROM (phase_row.job_id,phase_row.root_id,'260eb494-d08b-43a3-b05e-ac4b54c1f5eb'::uuid,'a6433494-8167-4f2b-ad39-82a20ce62cde'::uuid)
  OR NEW.payload_json->'persistent_frame'->'phase' IS DISTINCT FROM phase_row.payload_json
  OR phase_row.operation_key IS DISTINCT FROM frame_op OR NEW.reservation_id='366e4d24-108a-4dc9-b130-4b30c4c34ffe'::uuid
  OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_review_investigation_preparations WHERE review_receipt_id=NEW.review_receipt_id
    AND id<>'471344bd-5d96-408c-b828-57c45a53c267'::uuid)
 THEN RAISE check_violation USING MESSAGE='536 only one exact newly bound original preparation'; END IF;
 RETURN NEW;
END $body536$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_persistent_explicit_preparation() FROM PUBLIC;

DO $kinds536$ DECLARE d text; BEGIN
 SELECT pg_get_constraintdef(oid) INTO d FROM pg_constraint WHERE conrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass AND conname='tutor_item_supply_private_persistent_pack_jou_record_kind_check' AND contype='c' AND convalidated;
 IF d=$expected536$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text])))$expected536$ THEN
  ALTER TABLE tutor_item_supply_private_persistent_pack_journal DROP CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check;
  ALTER TABLE tutor_item_supply_private_persistent_pack_journal ADD CONSTRAINT tutor_item_supply_private_persistent_pack_jou_record_kind_check CHECK(record_kind IN('task','phase','pause','stop','private_attachment','private_status','prestart_proof','prestart_binding','explicit_recovery_approval','explicit_recovery_binding'));
 ELSIF d IS DISTINCT FROM $expected536$CHECK ((record_kind = ANY (ARRAY['task'::text, 'phase'::text, 'pause'::text, 'stop'::text, 'private_attachment'::text, 'private_status'::text, 'prestart_proof'::text, 'prestart_binding'::text, 'explicit_recovery_approval'::text, 'explicit_recovery_binding'::text])))$expected536$ THEN RAISE check_violation USING MESSAGE='536 exact private kind successor required'; END IF;
END $kinds536$;

DO $trigger536$ DECLARE t record; BEGIN SELECT *,pg_get_triggerdef(oid) AS definition INTO t FROM pg_trigger WHERE tgrelid='public.tutor_item_supply_private_persistent_pack_journal'::regclass AND tgname='a002_persistent_explicit_insert'; IF FOUND THEN IF t.definition IS DISTINCT FROM $expected536$CREATE TRIGGER a002_persistent_explicit_insert BEFORE INSERT ON public.tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_persistent_explicit_insert()$expected536$ OR t.tgenabled<>'O' OR t.tgisinternal THEN RAISE check_violation USING MESSAGE='536 existing attempt trigger changed'; END IF; ELSE CREATE TRIGGER a002_persistent_explicit_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_persistent_explicit_insert(); END IF; END $trigger536$;

DO $trigger536$ DECLARE t record; BEGIN SELECT *,pg_get_triggerdef(oid) AS definition INTO t FROM pg_trigger WHERE tgrelid='public.tutor_item_supply_shared_persistent_pack_journal'::regclass AND tgname='a002_persistent_explicit_stage'; IF FOUND THEN IF t.definition IS DISTINCT FROM $expected536$CREATE TRIGGER a002_persistent_explicit_stage BEFORE INSERT ON public.tutor_item_supply_shared_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_persistent_explicit_stage()$expected536$ OR t.tgenabled<>'O' OR t.tgisinternal THEN RAISE check_violation USING MESSAGE='536 existing attempt trigger changed'; END IF; ELSE CREATE TRIGGER a002_persistent_explicit_stage BEFORE INSERT ON tutor_item_supply_shared_persistent_pack_journal FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_persistent_explicit_stage(); END IF; END $trigger536$;

DO $trigger536$ DECLARE t record; BEGIN SELECT *,pg_get_triggerdef(oid) AS definition INTO t FROM pg_trigger WHERE tgrelid='public.tutor_item_supply_shared_review_investigation_preparations'::regclass AND tgname='a002_persistent_explicit_preparation'; IF FOUND THEN IF t.definition IS DISTINCT FROM $expected536$CREATE TRIGGER a002_persistent_explicit_preparation BEFORE INSERT ON public.tutor_item_supply_shared_review_investigation_preparations FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_persistent_explicit_preparation()$expected536$ OR t.tgenabled<>'O' OR t.tgisinternal THEN RAISE check_violation USING MESSAGE='536 existing attempt trigger changed'; END IF; ELSE CREATE TRIGGER a002_persistent_explicit_preparation BEFORE INSERT ON tutor_item_supply_shared_review_investigation_preparations FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_persistent_explicit_preparation(); END IF; END $trigger536$;

-- Main first compiles under TOP rollback and reads normalized pg_get_indexdef.
-- Pending exact new-index fingerprint is an intentional fail-closed replay gate.
DO $index536$ DECLARE c record; i record; BEGIN
 SELECT * INTO c FROM pg_constraint WHERE conrelid='public.tutor_item_supply_shared_review_investigation_preparations'::regclass
  AND conname='tutor_item_supply_shared_review_investiga_review_receipt_id_key';
 IF FOUND THEN
  IF pg_get_constraintdef(c.oid) IS DISTINCT FROM 'UNIQUE (review_receipt_id)' OR c.contype<>'u'
   OR encode(sha256(convert_to(pg_get_indexdef(c.conindid),'UTF8')),'hex') IS DISTINCT FROM '5404f06393a6c0527d57e97ba5b26dd145178d29e0477b90afcd8c7926586166'
   OR EXISTS(SELECT 1 FROM pg_constraint WHERE contype='f' AND conindid=c.conindid)
  THEN RAISE check_violation USING MESSAGE='536 exact unused single-review unique required'; END IF;
  IF to_regclass('public.shared_investigation_explicit_review_once') IS NOT NULL THEN RAISE check_violation USING MESSAGE='536 unexpected replacement index alongside old constraint'; END IF;
  ALTER TABLE tutor_item_supply_shared_review_investigation_preparations DROP CONSTRAINT tutor_item_supply_shared_review_investiga_review_receipt_id_key;
  CREATE UNIQUE INDEX shared_investigation_explicit_review_once ON tutor_item_supply_shared_review_investigation_preparations
   (review_receipt_id,(CASE WHEN review_receipt_id='260eb494-d08b-43a3-b05e-ac4b54c1f5eb'::uuid
     AND payload_json->'persistent_frame'->'phase'->>'operation_key'='persistent.candidate.7ac04190a21c41f9b121353680e38fb9.repair.frame.3'
     THEN 1 ELSE 0 END));
 ELSE
  SELECT *,pg_get_indexdef(indexrelid) AS definition INTO i FROM pg_index WHERE indexrelid=to_regclass('public.shared_investigation_explicit_review_once');
  IF NOT FOUND OR NOT i.indisunique OR NOT i.indisvalid OR NOT i.indisready
    OR encode(sha256(convert_to(i.definition,'UTF8')),'hex') IS DISTINCT FROM '939954c16fabee278964a0b6866c9f3e8b8bf36f7ccf83ec6856701aead09e42'
  THEN RAISE check_violation USING MESSAGE='536 reviewed normalized replacement index required'; END IF;
 END IF;
END $index536$;
