-- Narrow original491 persistent candidate-phase adoption. No new tables/helpers/authority.
-- All installed491/508-527 files remain immutable; all original491 legacy checks remain.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
 RAISE check_violation USING MESSAGE='528 B1d only'; END IF; END $$;

DO $upgrade528_continuation$
DECLARE actual record; verified record; definition text; source text;
 old_sha constant text:='0b85cb9554dca5332217cbc70d4d3f5cd6827b8c905c9c33a77795cbb3d85238'; new_sha constant text:='4747daa0a01ba9e3370d4fcc9405218c42ae98b1a1624a0217e615a06907cf80';
 reviewed_body constant text:=$body528_continuation$
DECLARE a record; c record; root_facts record; t timestamptz; snapshot jsonb; b jsonb:=NEW.binding_json;
  phase_row record; version_row record; private_header record; phase jsonb;
  stage_key text; persistent_permission boolean:=false;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared continuation B1d owner required';
  END IF;
  SELECT c1.*,j.root_id,j.parent_job_id,j.job_key,p.profile_hash,p.profile_json INTO c
    FROM tutor_item_supply_shared_job_controls c1 JOIN tutor_item_supply_shared_jobs j ON j.id=c1.job_id
    JOIN tutor_item_supply_parameter_profiles p ON p.id=c1.profile_id
    WHERE c1.job_id=NEW.job_id FOR UPDATE OF c1;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation job unavailable'; END IF;
  stage_key:='continue.'||replace(NEW.generation_artifact_id::text,'-','')||'.'||NEW.operation_key;
  IF NEW.operation_key LIKE 'persistent.%' AND c.job_key IS DISTINCT FROM encode(digest(convert_to(
      NEW.root_id::text||chr(31)||stage_key,'UTF8'),'sha256'),'hex') THEN
    -- Controlled ancestry wins BEFORE looking for any normal phase permission.
    PERFORM id FROM tutor_item_supply_shared_generation_artifacts
      WHERE id=NEW.generation_artifact_id AND root_id=NEW.root_id
        AND item_supply_internal.controlled_counterexample_held(job_id) IS FALSE FOR SHARE;
    IF NOT FOUND OR item_supply_internal.controlled_counterexample_held(NEW.job_id) IS DISTINCT FROM false
    THEN RAISE check_violation USING MESSAGE='528 controlled ancestry denied first'; END IF;
    IF current_setting('transaction_isolation')<>'read committed' OR current_setting('transaction_read_only')<>'off'
      OR item_supply_internal.snapshot_keys(b,ARRAY['schema_version','operation_key','root_id','canonical_root_key',
        'coverage_blueprint_hash','scope_hash','generation_artifact_id','original_job_id','original_lease_generation',
        'original_profile_hash','artifact_hash','original_request_hash','material_set_hash','source_receipt_set_hash',
        'candidate_id','item_id','version_id','source_hash','content_hash','target_id','target_definition_hash',
        'specification_hash','adoption_lease','authority','execution_authority_reusable','publication_enabled']) IS DISTINCT FROM true
      OR b->>'schema_version' IS DISTINCT FROM 'shared_candidate_continuation_v1'
    THEN RAISE check_violation USING MESSAGE='528 closed original binding and read-write phase required'; END IF;
    IF (SELECT count(*) FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.record_kind='phase' AND j.job_id=NEW.job_id AND j.root_id=NEW.root_id
        AND NEW.operation_key='persistent.'||replace(j.phase_id::text,'-',''))<>1
    THEN RAISE check_violation USING MESSAGE='528 unique original candidate phase required'; END IF;
    SELECT j.* INTO phase_row FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.record_kind='phase' AND j.job_id=NEW.job_id AND j.root_id=NEW.root_id
        AND NEW.operation_key='persistent.'||replace(j.phase_id::text,'-','') FOR SHARE;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='528 committed original candidate phase required'; END IF;
    phase:=phase_row.payload_json;
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
    IF phase->>'kind' IS DISTINCT FROM 'candidate' OR phase->>'job_id' IS DISTINCT FROM NEW.job_id::text
      OR phase->>'root_id' IS DISTINCT FROM NEW.root_id::text
      OR phase->>'phase_id' IS DISTINCT FROM phase_row.phase_id::text
      OR phase->>'public_task_id' IS DISTINCT FROM phase_row.public_task_id::text
      OR phase->'lease' IS DISTINCT FROM b->'adoption_lease'
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j
        WHERE j.phase_id=phase_row.phase_id AND j.record_kind='phase_result')
    THEN RAISE check_violation USING MESSAGE='528 exact active candidate phase lease required'; END IF;
    SELECT j.* INTO version_row FROM tutor_item_supply_shared_persistent_pack_journal j
      WHERE j.public_task_id=phase_row.public_task_id AND j.record_kind IN('version','qualified')
        AND j.payload_json->>'revision_id'=phase->>'revision_id'
      ORDER BY j.created_at DESC,j.id LIMIT 1 FOR SHARE;
    IF NOT FOUND OR version_row.root_id IS DISTINCT FROM NEW.root_id
      OR version_row.payload_json->>'artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
      OR version_row.payload_json->'public_slot_id' IS DISTINCT FROM phase->'public_slot_id'
      OR version_row.payload_json->>'root_id' IS DISTINCT FROM NEW.root_id::text
      OR b->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(version_row.payload_json->'specification')
      OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_persistent_pack_journal j
        WHERE j.public_task_id=phase_row.public_task_id AND j.record_kind IN('version','qualified')
          AND j.payload_json->'public_slot_id'=phase->'public_slot_id'
          AND (j.payload_json->>'revision_seq')::integer>(version_row.payload_json->>'revision_seq')::integer)
    THEN RAISE check_violation USING MESSAGE='528 exact current fixed-slot immutable artifact required'; END IF;
    IF (SELECT count(*) FROM tutor_item_supply_private_persistent_pack_journal j
      JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=j.pack_task_id
        AND attachment.user_id=j.user_id AND attachment.epoch=j.epoch AND attachment.scope_id=j.scope_id
        AND attachment.record_kind='phase'
        AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
        AND attachment.payload_json->>'phase_id'=phase_row.phase_id::text
        AND attachment.payload_json->>'public_task_id'=phase_row.public_task_id::text
      WHERE j.record_kind='task' AND j.id=j.pack_task_id
        AND j.payload_json->'ref'->>'public_task_id'=phase_row.public_task_id::text)<>1
    THEN RAISE check_violation USING MESSAGE='528 unique original private phase attachment required'; END IF;
    SELECT j.* INTO private_header FROM tutor_item_supply_private_persistent_pack_journal j
      JOIN tutor_item_supply_private_persistent_pack_journal attachment ON attachment.pack_task_id=j.pack_task_id
        AND attachment.user_id=j.user_id AND attachment.epoch=j.epoch AND attachment.scope_id=j.scope_id
        AND attachment.record_kind='phase'
        AND attachment.payload_json->>'schema_version'='persistent_private_phase_attachment_v1'
        AND attachment.payload_json->>'phase_id'=phase_row.phase_id::text
        AND attachment.payload_json->>'public_task_id'=phase_row.public_task_id::text
      WHERE j.record_kind='task' AND j.id=j.pack_task_id
        AND j.payload_json->'ref'->>'public_task_id'=phase_row.public_task_id::text FOR SHARE OF j,attachment;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='528 original private task attachment required'; END IF;
    PERFORM item_supply_internal.private_native_mapping_current(
      (private_header.payload_json->'ref'->>'mapping_receipt_id')::uuid,private_header.user_id,private_header.epoch::bigint);
    persistent_permission:=true;
    stage_key:='persistent.phase.'||replace(phase_row.phase_id::text,'-','');
  END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.parent_job_id IS NOT NULL
    OR c.lease_owner IS DISTINCT FROM b->'adoption_lease'->>'lease_owner'
    OR c.lease_generation::text IS DISTINCT FROM b->'adoption_lease'->>'generation'
    OR c.state_version::text IS DISTINCT FROM b->'adoption_lease'->>'state_version'
    OR c.lease_expires_at IS NULL OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM b->'adoption_lease'->'profile'
    OR c.profile_hash IS DISTINCT FROM snapshot->>'profile_hash'
    OR c.job_key IS DISTINCT FROM encode(digest(convert_to(NEW.root_id::text||chr(31)||
        stage_key,'UTF8'),'sha256'),'hex') THEN
    RAISE check_violation USING MESSAGE='continuation current new-job lease mismatch';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id THEN
    RAISE check_violation USING MESSAGE='continuation must retain original canonical root';
  END IF;
  SELECT r.canonical_key,bp.blueprint_hash,o.provider_key INTO root_facts
    FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_blueprints bp ON bp.id=r.blueprint_id
    JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id WHERE r.id=NEW.root_id FOR SHARE OF r,bp,o;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation root unavailable'; END IF;
  IF b->>'root_id' IS DISTINCT FROM NEW.root_id::text OR b->>'generation_artifact_id' IS DISTINCT FROM a.id::text
    OR b->>'original_job_id' IS DISTINCT FROM a.job_id::text
    OR b->>'original_lease_generation' IS DISTINCT FROM a.lease_generation::text
    OR b->>'candidate_id' IS DISTINCT FROM a.candidate_id::text OR b->>'item_id' IS DISTINCT FROM a.item_id::text
    OR b->>'version_id' IS DISTINCT FROM a.version_id::text OR b->>'source_hash' IS DISTINCT FROM a.source_hash
    OR b->>'content_hash' IS DISTINCT FROM a.content_hash OR b->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR b->>'target_id' IS DISTINCT FROM a.target_id OR b->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR b->>'operation_key' IS DISTINCT FROM NEW.operation_key
    OR b->>'canonical_root_key' IS DISTINCT FROM root_facts.canonical_key
    OR b->>'coverage_blueprint_hash' IS DISTINCT FROM root_facts.blueprint_hash
    OR b->>'scope_hash' IS DISTINCT FROM a.request_json->>'scope_hash'
    OR b->>'original_profile_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_hash'
    OR b->>'original_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json)
    OR b->>'material_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json->'materials')
    OR b->>'source_receipt_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.receipt_json->'sources')
    OR b->'adoption_lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR b->'adoption_lease'->>'visibility' IS DISTINCT FROM 'public'
    OR b->'adoption_lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb
    OR b->'adoption_lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR snapshot->>'profile_key_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_key_hash'
    OR c.profile_json->'profile_key'->>'provider' IS DISTINCT FROM root_facts.provider_key
    OR a.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
    OR b->>'authority' IS DISTINCT FROM 'immutable_generation_data_only'
    OR b->'execution_authority_reusable' IS DISTINCT FROM 'false'::jsonb
    OR b->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN
    RAISE check_violation USING MESSAGE='continuation immutable original binding mismatch';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id
      AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=a.reservation_id
      AND s.settlement_key='generation.'||replace(a.candidate_id::text,'-','')) THEN
    RAISE check_violation USING MESSAGE='continuation requires complete settled original generation';
  END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=NEW.job_id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=NEW.job_id AND stage='generating')
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=NEW.job_id AND reservation_key LIKE 'gen.%') THEN
    RAISE check_violation USING MESSAGE='continuation cannot masquerade as new generation';
  END IF;
  IF persistent_permission THEN
    -- No new author permissions: retain complete original491 checks above.
    -- Current source and all real phase deadlines are rechecked AFTER every wait.
    IF version_row.payload_json->'specification'->'blueprint' IS DISTINCT FROM a.request_json->'blueprint'
      OR version_row.payload_json->'specification'->'public_template' IS DISTINCT FROM a.request_json->'public_template'
      OR item_supply_internal.private_native_source_current(jsonb_build_object(
        'request',a.request_json,'ref',private_header.payload_json->'ref')) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='528 original fixed specification/current source required'; END IF;
    PERFORM item_supply_internal.assert_persistent_pack_phase(phase);
    t:=clock_timestamp();
    IF COALESCE(c.lease_expires_at>t,false) IS DISTINCT FROM true OR COALESCE(c.parent_deadline>t,false) IS DISTINCT FROM true
      OR COALESCE((phase->>'valid_until')::timestamptz>t,false) IS DISTINCT FROM true
    THEN RAISE check_violation USING MESSAGE='528 final acceptance deadline expired'; END IF;
  END IF;
  RETURN NEW;
END $body528_continuation$;
BEGIN
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
  WHERE p.oid=to_regprocedure('public.enforce_item_supply_shared_candidate_continuation()');
 IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql' OR actual.pronargs<>0
  OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset OR actual.proisstrict
  OR NOT actual.prosecdef OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.provariadic<>0 OR actual.pronargdefaults<>0 OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
 THEN RAISE check_violation USING MESSAGE='528 original continuation receiver attributes changed'; END IF;
 source:=replace(actual.prosrc,E'\r\n',E'\n');
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR encode(sha256(convert_to(reviewed_body,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='528 unknown original continuation receiver source'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1
 THEN RAISE check_violation USING MESSAGE='528 original continuation receiver framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,reviewed_body);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='528 original continuation attributes/owner/ACL not preserved'; END IF;
END $upgrade528_continuation$;

