-- C21: exact two-operand precedence repair on the installed native PRIVATE quality guard.
-- Frozen <=564 untouched. One prosrc patch, no new objects/readiness patches or row writes.
-- Does not recover/replay the lost paid review, mint a phase, or authorize provider IO.
DO $patch565$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old565$
DECLARE ph record;v record;a record;p jsonb:=NEW.payload_json;ref jsonb;b jsonb;rr jsonb;stage record;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal
  WHERE pack_task_id=NEW.pack_task_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1'
  AND payload_json->>'job_id'=NEW.job_id::text;
 ref:=ph.payload_json->'ref';
 IF ph.id IS NULL OR ref->>'slot_id' IS DISTINCT FROM NEW.slot_id::text OR ref->>'root_id' IS DISTINCT FROM NEW.root_id::text
  OR item_supply_internal.private_pack_slot_current(NEW.pack_task_id,NEW.slot_id,(ref->>'business_item_id')::uuid,
   NEW.root_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality requires current original private fixed-slot phase'; END IF;
 SELECT g.* INTO a FROM tutor_item_supply_private_generation_artifacts g JOIN tutor_item_supply_private_jobs j
  ON j.id=g.job_id AND j.user_id=g.user_id AND j.epoch=g.epoch
  WHERE g.version_id=NEW.version_id AND g.user_id=NEW.user_id AND g.epoch=NEW.epoch
  AND g.scope_id=NEW.scope_id AND j.root_id=NEW.root_id;
 -- Source locks BEFORE the existing private-version bank lock. Even direct SQL
 -- may not invert the original C/source→bank order on a native path.
 IF a.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',ref,'request',a.request_json,'source_receipts',a.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality current source before bank required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_versions WHERE id=NEW.version_id AND user_id=NEW.user_id
  AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR SHARE;
 IF v.id IS NULL OR a.id IS NULL OR a.mode IS DISTINCT FROM 'live' OR a.source_json->'public' IS DISTINCT FROM v.public_json
  OR a.source_json->'private' IS DISTINCT FROM v.private_json OR a.version_id IS DISTINCT FROM v.id OR a.candidate_id IS DISTINCT FROM v.candidate_id THEN
  RAISE check_violation USING MESSAGE='524 actual original private generation/version required'; END IF;
 IF NEW.kind='validation' THEN
  IF p->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2'
   OR p->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR p->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash' THEN
   RAISE check_violation USING MESSAGE='524 original candidate validation required'; END IF;
 ELSIF NEW.kind='blind' THEN
  IF p->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR p->'binding'->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR p->'binding'->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR p->'run'->'provider_identity'->>'identity' IS NULL THEN
   RAISE check_violation USING MESSAGE='524 original bound blind run required'; END IF;
 ELSIF NEW.kind IN('review','admission') THEN
  IF p->'ref' IS DISTINCT FROM ref OR (p->'lease'-'state_version') IS DISTINCT FROM (ph.payload_json->'lease'-'state_version') THEN
   RAISE check_violation USING MESSAGE='524 PRIVATE review/ref/lease binding required'; END IF;
  b:=p->'bundle';
  IF b->>'mode' IS DISTINCT FROM 'peer_blind' OR b->>'state' IS DISTINCT FROM 'completed'
   OR b->>'publication_enabled' IS DISTINCT FROM 'false' OR jsonb_array_length(b->'reports') IS DISTINCT FROM 6
   OR b->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR b->'binding'->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR b->'binding'->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR (SELECT count(DISTINCT r->>'role') FROM jsonb_array_elements(b->'reports') r)<>6
   OR (SELECT array_agg(r->>'role' ORDER BY r->>'role') FROM jsonb_array_elements(b->'reports') r)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
   OR (SELECT count(DISTINCT r->'run'->'provider_identity'->>'identity') FROM jsonb_array_elements(b->'reports') r)<>6
   OR (SELECT count(DISTINCT r->'run'->>'run_id') FROM jsonb_array_elements(b->'reports') r)<>6 THEN
   RAISE check_violation USING MESSAGE='524 full independent six-peer bundle required'; END IF;
  FOR rr IN SELECT value FROM jsonb_array_elements(b->'reports') LOOP
   IF rr->'binding' IS DISTINCT FROM b->'binding'
    OR rr->'run'->'provider_identity'->>'identity' IN(b->>'author_identity',b->'blind_solve'->'run'->'provider_identity'->>'identity')
    OR rr->'run'->>'run_id'=b->'blind_solve'->'run'->>'run_id' THEN
    RAISE check_violation USING MESSAGE='524 peer/author/blind independence required'; END IF;
  END LOOP;
  IF NEW.kind='admission' THEN
   IF p->>'schema_version' IS DISTINCT FROM 'private_native_quality_v1' OR p->>'receipt_id' IS DISTINCT FROM NEW.id::text
    OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text
    OR p->'source'->'public' IS DISTINCT FROM a.source_json->'public' OR p->'source'->'private' IS DISTINCT FROM a.source_json->'private'
    OR p->'request' IS DISTINCT FROM a.request_json OR p->'source_receipts' IS DISTINCT FROM a.receipt_json->'sources'
    OR p->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR p->'evaluation'->>'publication_enabled' IS DISTINCT FROM 'false'
    OR p->'evaluation'->'binding' IS DISTINCT FROM b->'binding' OR p->'evidence'->'binding' IS DISTINCT FROM b->'binding'
    OR item_supply_internal.private_native_source_current(p) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='524 original private full-risk/current-source admission required'; END IF;
   FOR stage IN SELECT * FROM (VALUES ('validation',p->>'validation_receipt_id',p->'validation'),
    ('blind',p->>'blind_receipt_id',b->'blind_solve')) x(kind,id,payload) LOOP
    PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=stage.id::uuid
     AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id AND q.pack_task_id=NEW.pack_task_id
     AND q.slot_id=NEW.slot_id AND q.version_id=NEW.version_id AND q.kind=stage.kind AND q.payload_json=stage.payload
     AND q.xmin::text::bigint<>(txid_current()%4294967296);
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 committed exact private validation/blind required'; END IF;
   END LOOP;
   PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'review_receipt_id')::uuid
    AND q.kind='review' AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id
    AND q.pack_task_id=NEW.pack_task_id AND q.slot_id=NEW.slot_id AND q.version_id=NEW.version_id
    AND q.payload_json->'bundle'=b AND q.payload_json->'spec'=p->'spec' AND q.payload_json->'ambiguity'=p->'ambiguity'
    AND q.xmin::text::bigint<>(txid_current()%4294967296);
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 committed exact private six-peer review required'; END IF;
   IF ref->>'parent_version_id' IS NOT NULL THEN
    PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'normal_readmission_id')::uuid
     AND q.kind='normal' AND q.version_id=NEW.version_id AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch
     AND q.scope_id=NEW.scope_id AND q.pack_task_id=NEW.pack_task_id AND q.slot_id=NEW.slot_id
     AND q.payload_json->>'parent_version_id'=ref->>'parent_version_id'
     AND q.payload_json->>'child_artifact_id'=p->>'generation_artifact_id'
     AND q.payload_json->>'validation_id'=p->>'validation_receipt_id'
     AND q.payload_json->>'blind_id'=p->>'blind_receipt_id' AND q.payload_json->>'review_id'=p->>'review_receipt_id'
     AND q.payload_json->'evaluation'=p->'evaluation' AND q.payload_json->'evidence'=p->'evidence'
     AND q.payload_json->'machine_hashes'=p->'machine_hashes'
     AND q.payload_json->>'clause_proof_hash'=p->>'clause_proof_hash';
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 independent PRIVATE normal child re-admission required'; END IF;
   ELSIF p->>'normal_readmission_id' IS NOT NULL THEN
    RAISE check_violation USING MESSAGE='524 PRIVATE normal cannot relabel initial version'; END IF;
  END IF;
 ELSIF NEW.kind IN('investigation','normal','relation') THEN
  IF p->'ref' IS DISTINCT FROM ref THEN RAISE check_violation USING MESSAGE='524 private auxiliary exact ref required'; END IF;
  -- Dedicated type-specific receipts must be issued only after a committed
  -- original reservation and bounded PRIVATE phase, not JSON capability restore.
  IF NEW.kind='investigation' THEN PERFORM item_supply_internal.assert_private_native_investigation(NEW); END IF;
  IF NEW.kind='normal' THEN PERFORM item_supply_internal.assert_private_native_normal(NEW); END IF;
  IF NEW.kind='relation' THEN PERFORM item_supply_internal.assert_private_native_relation(NEW); END IF;
 END IF;
 IF NEW.kind IN('blind','review') THEN PERFORM item_supply_internal.assert_private_native_review_stage(NEW); END IF;
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',a.request_json,
  'source_receipts',a.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality source stale after native bank wait'; END IF;
 stamp:=clock_timestamp();
 IF NEW.checked_at>stamp OR NEW.valid_until<=stamp
  OR (NEW.kind<>'relation' AND NEW.valid_until>(ph.payload_json->>'valid_until')::timestamptz)
  OR (NEW.kind='relation' AND NEW.valid_until>NEW.checked_at+interval '7 days') THEN
  RAISE check_violation USING MESSAGE='524 quality stale after lock wait'; END IF;
 RETURN NEW;
END $old565$;
 new_body constant text := $new565$
DECLARE ph record;v record;a record;p jsonb:=NEW.payload_json;ref jsonb;b jsonb;rr jsonb;stage record;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal
  WHERE pack_task_id=NEW.pack_task_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id
  AND record_kind='phase' AND payload_json->>'schema_version'='private_native_phase_v1'
  AND payload_json->>'job_id'=NEW.job_id::text;
 ref:=ph.payload_json->'ref';
 IF ph.id IS NULL OR ref->>'slot_id' IS DISTINCT FROM NEW.slot_id::text OR ref->>'root_id' IS DISTINCT FROM NEW.root_id::text
  OR item_supply_internal.private_pack_slot_current(NEW.pack_task_id,NEW.slot_id,(ref->>'business_item_id')::uuid,
   NEW.root_id,NEW.user_id,NEW.epoch,NEW.scope_id,NEW.job_id) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality requires current original private fixed-slot phase'; END IF;
 SELECT g.* INTO a FROM tutor_item_supply_private_generation_artifacts g JOIN tutor_item_supply_private_jobs j
  ON j.id=g.job_id AND j.user_id=g.user_id AND j.epoch=g.epoch
  WHERE g.version_id=NEW.version_id AND g.user_id=NEW.user_id AND g.epoch=NEW.epoch
  AND g.scope_id=NEW.scope_id AND j.root_id=NEW.root_id;
 -- Source locks BEFORE the existing private-version bank lock. Even direct SQL
 -- may not invert the original C/source→bank order on a native path.
 IF a.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',ref,'request',a.request_json,'source_receipts',a.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality current source before bank required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_versions WHERE id=NEW.version_id AND user_id=NEW.user_id
  AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR SHARE;
 IF v.id IS NULL OR a.id IS NULL OR a.mode IS DISTINCT FROM 'live' OR a.source_json->'public' IS DISTINCT FROM v.public_json
  OR a.source_json->'private' IS DISTINCT FROM v.private_json OR a.version_id IS DISTINCT FROM v.id OR a.candidate_id IS DISTINCT FROM v.candidate_id THEN
  RAISE check_violation USING MESSAGE='524 actual original private generation/version required'; END IF;
 IF NEW.kind='validation' THEN
  IF p->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2'
   OR p->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR p->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash' THEN
   RAISE check_violation USING MESSAGE='524 original candidate validation required'; END IF;
 ELSIF NEW.kind='blind' THEN
  IF p->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR p->'binding'->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR p->'binding'->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR p->'run'->'provider_identity'->>'identity' IS NULL THEN
   RAISE check_violation USING MESSAGE='524 original bound blind run required'; END IF;
 ELSIF NEW.kind IN('review','admission') THEN
  IF p->'ref' IS DISTINCT FROM ref OR ((p->'lease') - 'state_version'::text) IS DISTINCT FROM ((ph.payload_json->'lease') - 'state_version'::text) THEN
   RAISE check_violation USING MESSAGE='524 PRIVATE review/ref/lease binding required'; END IF;
  b:=p->'bundle';
  IF b->>'mode' IS DISTINCT FROM 'peer_blind' OR b->>'state' IS DISTINCT FROM 'completed'
   OR b->>'publication_enabled' IS DISTINCT FROM 'false' OR jsonb_array_length(b->'reports') IS DISTINCT FROM 6
   OR b->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
   OR b->'binding'->>'source_hash' IS DISTINCT FROM a.receipt_json->>'source_hash'
   OR b->'binding'->>'content_hash' IS DISTINCT FROM a.receipt_json->>'content_hash'
   OR (SELECT count(DISTINCT r->>'role') FROM jsonb_array_elements(b->'reports') r)<>6
   OR (SELECT array_agg(r->>'role' ORDER BY r->>'role') FROM jsonb_array_elements(b->'reports') r)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[]
   OR (SELECT count(DISTINCT r->'run'->'provider_identity'->>'identity') FROM jsonb_array_elements(b->'reports') r)<>6
   OR (SELECT count(DISTINCT r->'run'->>'run_id') FROM jsonb_array_elements(b->'reports') r)<>6 THEN
   RAISE check_violation USING MESSAGE='524 full independent six-peer bundle required'; END IF;
  FOR rr IN SELECT value FROM jsonb_array_elements(b->'reports') LOOP
   IF rr->'binding' IS DISTINCT FROM b->'binding'
    OR rr->'run'->'provider_identity'->>'identity' IN(b->>'author_identity',b->'blind_solve'->'run'->'provider_identity'->>'identity')
    OR rr->'run'->>'run_id'=b->'blind_solve'->'run'->>'run_id' THEN
    RAISE check_violation USING MESSAGE='524 peer/author/blind independence required'; END IF;
  END LOOP;
  IF NEW.kind='admission' THEN
   IF p->>'schema_version' IS DISTINCT FROM 'private_native_quality_v1' OR p->>'receipt_id' IS DISTINCT FROM NEW.id::text
    OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text
    OR p->'source'->'public' IS DISTINCT FROM a.source_json->'public' OR p->'source'->'private' IS DISTINCT FROM a.source_json->'private'
    OR p->'request' IS DISTINCT FROM a.request_json OR p->'source_receipts' IS DISTINCT FROM a.receipt_json->'sources'
    OR p->'evaluation'->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR p->'evaluation'->>'publication_enabled' IS DISTINCT FROM 'false'
    OR p->'evaluation'->'binding' IS DISTINCT FROM b->'binding' OR p->'evidence'->'binding' IS DISTINCT FROM b->'binding'
    OR item_supply_internal.private_native_source_current(p) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='524 original private full-risk/current-source admission required'; END IF;
   FOR stage IN SELECT * FROM (VALUES ('validation',p->>'validation_receipt_id',p->'validation'),
    ('blind',p->>'blind_receipt_id',b->'blind_solve')) x(kind,id,payload) LOOP
    PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=stage.id::uuid
     AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id AND q.pack_task_id=NEW.pack_task_id
     AND q.slot_id=NEW.slot_id AND q.version_id=NEW.version_id AND q.kind=stage.kind AND q.payload_json=stage.payload
     AND q.xmin::text::bigint<>(txid_current()%4294967296);
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 committed exact private validation/blind required'; END IF;
   END LOOP;
   PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'review_receipt_id')::uuid
    AND q.kind='review' AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch AND q.scope_id=NEW.scope_id
    AND q.pack_task_id=NEW.pack_task_id AND q.slot_id=NEW.slot_id AND q.version_id=NEW.version_id
    AND q.payload_json->'bundle'=b AND q.payload_json->'spec'=p->'spec' AND q.payload_json->'ambiguity'=p->'ambiguity'
    AND q.xmin::text::bigint<>(txid_current()%4294967296);
   IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 committed exact private six-peer review required'; END IF;
   IF ref->>'parent_version_id' IS NOT NULL THEN
    PERFORM 1 FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id=(p->>'normal_readmission_id')::uuid
     AND q.kind='normal' AND q.version_id=NEW.version_id AND q.user_id=NEW.user_id AND q.epoch=NEW.epoch
     AND q.scope_id=NEW.scope_id AND q.pack_task_id=NEW.pack_task_id AND q.slot_id=NEW.slot_id
     AND q.payload_json->>'parent_version_id'=ref->>'parent_version_id'
     AND q.payload_json->>'child_artifact_id'=p->>'generation_artifact_id'
     AND q.payload_json->>'validation_id'=p->>'validation_receipt_id'
     AND q.payload_json->>'blind_id'=p->>'blind_receipt_id' AND q.payload_json->>'review_id'=p->>'review_receipt_id'
     AND q.payload_json->'evaluation'=p->'evaluation' AND q.payload_json->'evidence'=p->'evidence'
     AND q.payload_json->'machine_hashes'=p->'machine_hashes'
     AND q.payload_json->>'clause_proof_hash'=p->>'clause_proof_hash';
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 independent PRIVATE normal child re-admission required'; END IF;
   ELSIF p->>'normal_readmission_id' IS NOT NULL THEN
    RAISE check_violation USING MESSAGE='524 PRIVATE normal cannot relabel initial version'; END IF;
  END IF;
 ELSIF NEW.kind IN('investigation','normal','relation') THEN
  IF p->'ref' IS DISTINCT FROM ref THEN RAISE check_violation USING MESSAGE='524 private auxiliary exact ref required'; END IF;
  -- Dedicated type-specific receipts must be issued only after a committed
  -- original reservation and bounded PRIVATE phase, not JSON capability restore.
  IF NEW.kind='investigation' THEN PERFORM item_supply_internal.assert_private_native_investigation(NEW); END IF;
  IF NEW.kind='normal' THEN PERFORM item_supply_internal.assert_private_native_normal(NEW); END IF;
  IF NEW.kind='relation' THEN PERFORM item_supply_internal.assert_private_native_relation(NEW); END IF;
 END IF;
 IF NEW.kind IN('blind','review') THEN PERFORM item_supply_internal.assert_private_native_review_stage(NEW); END IF;
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',a.request_json,
  'source_receipts',a.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 quality source stale after native bank wait'; END IF;
 stamp:=clock_timestamp();
 IF NEW.checked_at>stamp OR NEW.valid_until<=stamp
  OR (NEW.kind<>'relation' AND NEW.valid_until>(ph.payload_json->>'valid_until')::timestamptz)
  OR (NEW.kind='relation' AND NEW.valid_until>NEW.checked_at+interval '7 days') THEN
  RAISE check_violation USING MESSAGE='524 quality stale after lock wait'; END IF;
 RETURN NEW;
END $new565$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='565 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.enforce_private_native_quality_insert()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'enforce_private_native_quality_insert' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype
  OR actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector
  OR actual.proargnames IS DISTINCT FROM NULL::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='565 original quality receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='565 original quality receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='565 original quality receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='565 quality receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch565$;
