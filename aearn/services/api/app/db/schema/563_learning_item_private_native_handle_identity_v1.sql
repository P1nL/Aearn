-- C19: distinguish opaque private storage locators from canonical native version handles.
-- Exact five deployed-prosrc patches only; no new objects, aliases, row changes, or bootstrap.
-- Run this selected fragment in the caller-owned atomic writable READ COMMITTED transaction.

DO $patchquality563$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldquality563$
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
  OR a.source_json->'private' IS DISTINCT FROM v.private_json OR v.handle IS DISTINCT FROM 'lip:v2:'||NEW.version_id::text THEN
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
END $oldquality563$;
 new_body constant text := $newquality563$
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
END $newquality563$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='563 original isolated writable transaction required'; END IF;
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
 THEN RAISE check_violation USING MESSAGE='563 original quality receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='563 original quality receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='563 original quality receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='563 quality receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patchquality563$;

DO $patchpub563$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldpub563$
DECLARE q record;v record;prev record;p jsonb:=NEW.payload_json;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=NEW.quality_id AND kind='admission'
  AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND pack_task_id=NEW.pack_task_id
  AND slot_id=NEW.slot_id AND root_id=NEW.root_id AND version_id=NEW.version_id;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 exact private original admission required'; END IF;
 IF NEW.state='published' AND item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 PRIVATE source before bank required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_versions WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR UPDATE;
 SELECT * INTO prev FROM tutor_item_supply_private_native_publications WHERE version_id=NEW.version_id
  AND user_id=NEW.user_id AND epoch=NEW.epoch ORDER BY state_version DESC LIMIT 1;
 IF prev.id IS NULL THEN
  IF NEW.state IS DISTINCT FROM 'published' OR NEW.state_version<>1 OR NEW.predecessor_id IS NOT NULL
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_publication_v1' OR p->>'publication_id' IS DISTINCT FROM NEW.id::text
   OR p->>'quality_id' IS DISTINCT FROM q.id::text OR p->>'quality_hash' IS DISTINCT FROM q.payload_hash
   OR p->'ref' IS DISTINCT FROM q.payload_json->'ref' OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
   OR p->>'item_handle' IS DISTINCT FROM v.handle OR p->>'exercise_version_id' IS DISTINCT FROM NEW.exercise_version_id::text
   OR p->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(q.payload_json->'source')
   OR p->>'content_hash' IS DISTINCT FROM q.payload_json->'bundle'->'binding'->>'content_hash'
   OR NEW.content_json->>'item_handle' IS DISTINCT FROM v.handle
   OR NEW.content_json->>'version_id' IS DISTINCT FROM NEW.version_id::text
   OR NEW.content_json->>'content_hash' IS DISTINCT FROM p->>'content_hash'
   OR NEW.content_json->>'actual_public_task_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(v.public_json)
   OR NEW.content_json->>'actual_fixture_hash' IS DISTINCT FROM q.payload_json->'ambiguity'->'plan'->>'instance_hash'
   OR split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2) NOT IN('trace','diagnose','repair','counterexample')
   OR NEW.content_json->>'decision_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'domain','decision','semantics',jsonb_build_object('version','native-finite-semantic-v1','profile','kc',
       'decision',split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2))))
   OR NEW.content_json->>'answer_leakage_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'domain','contextual-solution','semantics',jsonb_build_object('version','native-finite-semantic-v1','profile','kc',
       'decision',split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2))))
   OR NEW.content_json->>'author_id' IS DISTINCT FROM item_supply_internal.native_type_actor(q.payload_json->'bundle'->>'author_identity')::text
   OR v.public_json IS DISTINCT FROM q.payload_json->'source'->'public' OR v.private_json IS DISTINCT FROM q.payload_json->'source'->'private'
   OR item_supply_internal.private_pack_slot_current(NEW.pack_task_id,NEW.slot_id,
    (q.payload_json->'ref'->>'business_item_id')::uuid,NEW.root_id,NEW.user_id,NEW.epoch,NEW.scope_id,q.job_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='524 exact live original private publication required'; END IF;
  PERFORM 1 FROM tutor_exercise_versions x JOIN tutor_exercise_private_rubrics r ON r.exercise_version_id=x.id
   WHERE x.id=NEW.exercise_version_id AND x.source_kind='registered_author'
   AND x.content_hash=p->>'exercise_content_hash' AND r.rubric_hash=p->>'rubric_hash'
   AND x.exercise_key=q.payload_json->'source'->'public'->>'item_key'
   AND x.version=q.payload_json->'source'->'public'->>'version';
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 actual original private materialization required'; END IF;
  stamp:=clock_timestamp();
  IF (p->>'checked_at')::timestamptz>stamp OR stamp>=q.valid_until
   OR (p->>'producer_valid_until')::timestamptz IS DISTINCT FROM q.valid_until
   OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='524 private publication stale after wait'; END IF;
 ELSE
  IF NEW.state NOT IN('quarantined','retired') OR prev.state<>'published' OR NEW.state_version<>prev.state_version+1
   OR NEW.predecessor_id IS DISTINCT FROM prev.id OR NEW.quality_id IS DISTINCT FROM prev.quality_id
   OR NEW.payload_json IS DISTINCT FROM prev.payload_json OR NEW.exercise_version_id IS DISTINCT FROM prev.exercise_version_id
   OR NEW.content_json IS DISTINCT FROM prev.content_json THEN
   RAISE check_violation USING MESSAGE='524 immutable private publication terminal CAS required'; END IF;
 END IF;
 RETURN NEW;
END $oldpub563$;
 new_body constant text := $newpub563$
DECLARE q record;v record;prev record;p jsonb:=NEW.payload_json;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=NEW.quality_id AND kind='admission'
  AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND pack_task_id=NEW.pack_task_id
  AND slot_id=NEW.slot_id AND root_id=NEW.root_id AND version_id=NEW.version_id;
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 exact private original admission required'; END IF;
 IF NEW.state='published' AND item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 PRIVATE source before bank required'; END IF;
 SELECT * INTO v FROM tutor_item_supply_private_versions WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch FOR UPDATE;
 SELECT * INTO prev FROM tutor_item_supply_private_native_publications WHERE version_id=NEW.version_id
  AND user_id=NEW.user_id AND epoch=NEW.epoch ORDER BY state_version DESC LIMIT 1;
 IF prev.id IS NULL THEN
  IF NEW.state IS DISTINCT FROM 'published' OR NEW.state_version<>1 OR NEW.predecessor_id IS NOT NULL
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_publication_v1' OR p->>'publication_id' IS DISTINCT FROM NEW.id::text
   OR p->>'quality_id' IS DISTINCT FROM q.id::text OR p->>'quality_hash' IS DISTINCT FROM q.payload_hash
   OR p->'ref' IS DISTINCT FROM q.payload_json->'ref' OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
   OR p->>'item_handle' IS DISTINCT FROM ('lip:v2:'||v.id::text) OR p->>'exercise_version_id' IS DISTINCT FROM NEW.exercise_version_id::text
   OR p->>'source_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(q.payload_json->'source')
   OR p->>'content_hash' IS DISTINCT FROM q.payload_json->'bundle'->'binding'->>'content_hash'
   OR NEW.content_json->>'item_handle' IS DISTINCT FROM ('lip:v2:'||v.id::text)
   OR NEW.content_json->>'version_id' IS DISTINCT FROM NEW.version_id::text
   OR NEW.content_json->>'content_hash' IS DISTINCT FROM p->>'content_hash'
   OR NEW.content_json->>'actual_public_task_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(v.public_json)
   OR NEW.content_json->>'actual_fixture_hash' IS DISTINCT FROM q.payload_json->'ambiguity'->'plan'->>'instance_hash'
   OR split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2) NOT IN('trace','diagnose','repair','counterexample')
   OR NEW.content_json->>'decision_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'domain','decision','semantics',jsonb_build_object('version','native-finite-semantic-v1','profile','kc',
       'decision',split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2))))
   OR NEW.content_json->>'answer_leakage_signature' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'domain','contextual-solution','semantics',jsonb_build_object('version','native-finite-semantic-v1','profile','kc',
       'decision',split_part(q.payload_json->'spec'->'allocation'->>'family_id',':',2))))
   OR NEW.content_json->>'author_id' IS DISTINCT FROM item_supply_internal.native_type_actor(q.payload_json->'bundle'->>'author_identity')::text
   OR v.public_json IS DISTINCT FROM q.payload_json->'source'->'public' OR v.private_json IS DISTINCT FROM q.payload_json->'source'->'private'
   OR item_supply_internal.private_pack_slot_current(NEW.pack_task_id,NEW.slot_id,
    (q.payload_json->'ref'->>'business_item_id')::uuid,NEW.root_id,NEW.user_id,NEW.epoch,NEW.scope_id,q.job_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='524 exact live original private publication required'; END IF;
  PERFORM 1 FROM tutor_exercise_versions x JOIN tutor_exercise_private_rubrics r ON r.exercise_version_id=x.id
   WHERE x.id=NEW.exercise_version_id AND x.source_kind='registered_author'
   AND x.content_hash=p->>'exercise_content_hash' AND r.rubric_hash=p->>'rubric_hash'
   AND x.exercise_key=q.payload_json->'source'->'public'->>'item_key'
   AND x.version=q.payload_json->'source'->'public'->>'version';
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 actual original private materialization required'; END IF;
  stamp:=clock_timestamp();
  IF (p->>'checked_at')::timestamptz>stamp OR stamp>=q.valid_until
   OR (p->>'producer_valid_until')::timestamptz IS DISTINCT FROM q.valid_until
   OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='524 private publication stale after wait'; END IF;
 ELSE
  IF NEW.state NOT IN('quarantined','retired') OR prev.state<>'published' OR NEW.state_version<>prev.state_version+1
   OR NEW.predecessor_id IS DISTINCT FROM prev.id OR NEW.quality_id IS DISTINCT FROM prev.quality_id
   OR NEW.payload_json IS DISTINCT FROM prev.payload_json OR NEW.exercise_version_id IS DISTINCT FROM prev.exercise_version_id
   OR NEW.content_json IS DISTINCT FROM prev.content_json THEN
   RAISE check_violation USING MESSAGE='524 immutable private publication terminal CAS required'; END IF;
 END IF;
 RETURN NEW;
END $newpub563$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='563 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.enforce_private_native_publication_insert()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'enforce_private_native_publication_insert' OR actual.prokind<>'f'
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
 THEN RAISE check_violation USING MESSAGE='563 original pub receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='563 original pub receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='563 original pub receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='563 pub receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patchpub563$;

DO $patchcurrent563$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldcurrent563$
DECLARE pub record;q record;latest record;version record;mat jsonb;mapping jsonb;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE version_id=v AND user_id=u AND epoch=e
 AND state='published' ORDER BY state_version LIMIT 1;
 SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=pub.quality_id AND user_id=u AND epoch=e AND kind='admission';
 IF pub.id IS NULL OR q.id IS NULL OR q.payload_json->>'schema_version'<>'private_native_quality_v1'
  OR pub.payload_json->>'quality_hash'<>q.payload_hash
  OR NOT(q.checked_at<=(pub.payload_json->>'checked_at')::timestamptz AND (pub.payload_json->>'checked_at')::timestamptz<q.valid_until)
  OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 private historical quality/current source required'; END IF;
 -- Old producer is HISTORY, not a current lease requirement.
 SELECT * INTO version FROM tutor_item_supply_private_versions WHERE id=v AND user_id=u AND epoch=e FOR SHARE;
 SELECT * INTO latest FROM tutor_item_supply_private_native_publications WHERE version_id=v AND user_id=u AND epoch=e ORDER BY state_version DESC LIMIT 1;
 IF latest.state IS DISTINCT FROM 'published' OR latest.id IS DISTINCT FROM pub.id
  OR version.handle IS DISTINCT FROM pub.payload_json->>'item_handle'
  OR version.public_json IS DISTINCT FROM q.payload_json->'source'->'public'
  OR version.private_json IS DISTINCT FROM q.payload_json->'source'->'private' THEN
  RAISE check_violation USING MESSAGE='524 private content retired or identity changed'; END IF;
 PERFORM 1 FROM tutor_exercise_versions x JOIN tutor_exercise_private_rubrics r ON r.exercise_version_id=x.id
 WHERE x.id=pub.exercise_version_id AND x.source_kind='registered_author'
 AND x.content_hash=pub.payload_json->>'exercise_content_hash' AND r.rubric_hash=pub.payload_json->>'rubric_hash';
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 actual original exercise/rubric missing'; END IF;
 mapping:=item_supply_internal.private_native_mapping_current((q.payload_json->'ref'->>'mapping_receipt_id')::uuid,u,e);
 IF mapping->>'target_definition_hash' IS DISTINCT FROM q.payload_json->'spec'->>'target_definition_hash'
  OR q.payload_json->'source'->'blueprint'->>'knowledge_key' IS DISTINCT FROM 'finite.'||(mapping->>'target_id')
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(mapping->'pack_request'->'demands') d
    WHERE d->>'slot'=q.payload_json->'ref'->>'slot' AND d->>'storage_scope_id'=q.payload_json->'ref'->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 private exact finite goal bridge required'; END IF;
 IF item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 source stale after bank wait'; END IF;
 RETURN pub.payload_json;
END $oldcurrent563$;
 new_body constant text := $newcurrent563$
DECLARE pub record;q record;latest record;version record;mat jsonb;mapping jsonb;stamp timestamptz;
BEGIN
 PERFORM item_supply_internal.private_native_epoch(u,e);
 SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE version_id=v AND user_id=u AND epoch=e
 AND state='published' ORDER BY state_version LIMIT 1;
 SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=pub.quality_id AND user_id=u AND epoch=e AND kind='admission';
 IF pub.id IS NULL OR q.id IS NULL OR q.payload_json->>'schema_version'<>'private_native_quality_v1'
  OR pub.payload_json->>'quality_hash'<>q.payload_hash
  OR NOT(q.checked_at<=(pub.payload_json->>'checked_at')::timestamptz AND (pub.payload_json->>'checked_at')::timestamptz<q.valid_until)
  OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 private historical quality/current source required'; END IF;
 -- Old producer is HISTORY, not a current lease requirement.
 SELECT * INTO version FROM tutor_item_supply_private_versions WHERE id=v AND user_id=u AND epoch=e FOR SHARE;
 SELECT * INTO latest FROM tutor_item_supply_private_native_publications WHERE version_id=v AND user_id=u AND epoch=e ORDER BY state_version DESC LIMIT 1;
 IF latest.state IS DISTINCT FROM 'published' OR latest.id IS DISTINCT FROM pub.id
  OR ('lip:v2:'||version.id::text) IS DISTINCT FROM pub.payload_json->>'item_handle'
  OR version.public_json IS DISTINCT FROM q.payload_json->'source'->'public'
  OR version.private_json IS DISTINCT FROM q.payload_json->'source'->'private' THEN
  RAISE check_violation USING MESSAGE='524 private content retired or identity changed'; END IF;
 PERFORM 1 FROM tutor_exercise_versions x JOIN tutor_exercise_private_rubrics r ON r.exercise_version_id=x.id
 WHERE x.id=pub.exercise_version_id AND x.source_kind='registered_author'
 AND x.content_hash=pub.payload_json->>'exercise_content_hash' AND r.rubric_hash=pub.payload_json->>'rubric_hash';
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='524 actual original exercise/rubric missing'; END IF;
 mapping:=item_supply_internal.private_native_mapping_current((q.payload_json->'ref'->>'mapping_receipt_id')::uuid,u,e);
 IF mapping->>'target_definition_hash' IS DISTINCT FROM q.payload_json->'spec'->>'target_definition_hash'
  OR q.payload_json->'source'->'blueprint'->>'knowledge_key' IS DISTINCT FROM 'finite.'||(mapping->>'target_id')
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(mapping->'pack_request'->'demands') d
    WHERE d->>'slot'=q.payload_json->'ref'->>'slot' AND d->>'storage_scope_id'=q.payload_json->'ref'->>'goal_scope_id') THEN
  RAISE check_violation USING MESSAGE='524 private exact finite goal bridge required'; END IF;
 IF item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='524 source stale after bank wait'; END IF;
 RETURN pub.payload_json;
END $newcurrent563$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='563 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_native_publication_current(uuid,uuid,bigint)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_native_publication_current' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.jsonb'::regtype
  OR actual.pronargs<>3 OR actual.proargtypes IS DISTINCT FROM ('pg_catalog.uuid'::regtype::oid::text||' '||'pg_catalog.uuid'::regtype::oid::text||' '||'pg_catalog.int8'::regtype::oid::text)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['v','u','e']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='563 original current receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='563 original current receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='563 original current receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='563 current receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patchcurrent563$;

DO $patchterm563$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldterm563$
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
$oldterm563$;
 new_body constant text := $newterm563$
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
     AND publication.payload_json->>'item_handle'=('lip:v2:'||version.id::text) AND publication.content_json->>'item_handle'=('lip:v2:'||version.id::text)
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
$newterm563$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='563 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_initial_author_continuation_terminal(uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_initial_author_continuation_terminal' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.text'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM ('pg_catalog.uuid'::regtype::oid::text)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['p_started']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='563 original term receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='563 original term receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='563 original term receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='563 term receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patchterm563$;

DO $patchready563$
DECLARE actual record; verified record; definition text;
 old_body constant text := $oldready563$
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
$oldready563$;
 new_body constant text := $newready563$
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
     AND publication.payload_json->>'item_handle'=('lip:v2:'||version.id::text) AND publication.content_json->>'item_handle'=('lip:v2:'||version.id::text)
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
$newready563$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='563 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_generation_durability_ready()');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_generation_durability_ready' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector
  OR actual.proargnames IS DISTINCT FROM NULL::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='563 original ready receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='563 original ready receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='563 original ready receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='563 ready receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patchready563$;
