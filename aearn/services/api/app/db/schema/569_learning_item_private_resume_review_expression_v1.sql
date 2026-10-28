-- C25: repair only the two typed lease operands in the original resume-review receiver.
-- Frozen <=568 untouched. Original catalog OID 5380233; same-OID prosrc replacement only.
-- No new objects/API/triggers/readiness patches or historical/current authority changes.
DO $patch569$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old569$
DECLARE ref jsonb:=p->'ref'; lease jsonb:=p->'lease'; peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 v public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;b public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 g public.tutor_item_supply_private_generation_artifacts%ROWTYPE;ph record;stamp timestamptz;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','lease','review_id','validation_id','blind_id','artifact_id']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_committed_review_resume_v1' THEN
  RAISE check_violation USING MESSAGE='527 exact PRIVATE review continuation frame required'; END IF;
 PERFORM item_supply_internal.private_native_epoch((ref->>'user_id')::uuid,(ref->>'epoch')::bigint);
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='phase'
  AND pack_task_id=(ref->>'pack_task_id')::uuid AND user_id=(ref->>'user_id')::uuid AND epoch=(ref->>'epoch')::integer
  AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=lease->>'job_id';
 IF ph.id IS NULL OR ph.payload_json->'ref' IS DISTINCT FROM ref
  OR (ph.payload_json->'lease'-'state_version') IS DISTINCT FROM (lease-'state_version') THEN
  RAISE check_violation USING MESSAGE='527 current concrete phase required'; END IF;
 PERFORM item_supply_internal.assert_private_native_phase(ph.payload_json,ph.user_id,ph.epoch,ph.scope_id,ph.pack_task_id);
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'review_id')::uuid AND kind='review'
  AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id AND pack_task_id=ph.pack_task_id
  AND slot_id=(ref->>'slot_id')::uuid AND root_id=(ref->>'root_id')::uuid AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO g FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'artifact_id')::uuid
  AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id AND version_id=peer.version_id AND mode='live'
  AND xmin::text::bigint<>(txid_current()%4294967296);
 -- Original source locks before private bank/current material locks.
 IF g.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',ref,'request',g.request_json,'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 current source for historical PRIVATE quality required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_versions WHERE id=g.version_id AND user_id=ph.user_id AND epoch=ph.epoch
  AND scope_id=ph.scope_id AND public_json=g.source_json->'public' AND private_json=g.source_json->'private' FOR SHARE;
 IF NOT FOUND OR peer.id IS NULL OR peer.payload_json->'ref' IS DISTINCT FROM ref
  OR peer.payload_json->>'artifact_id' IS DISTINCT FROM g.id::text
  OR peer.payload_json->'bundle'->'binding'->>'version_key' IS DISTINCT FROM g.version_id::text
  OR peer.payload_json->'bundle'->'binding'->>'source_hash' IS DISTINCT FROM g.source_hash
  OR peer.payload_json->'bundle'->'binding'->>'content_hash' IS DISTINCT FROM g.content_hash
  OR peer.checked_at>=peer.valid_until OR peer.created_at>=peer.valid_until THEN
  RAISE check_violation USING MESSAGE='527 actual lawful historical PRIVATE review required'; END IF;
 PERFORM item_supply_internal.assert_private_native_review_stage(peer);
 SELECT * INTO v FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'validation_id')::uuid AND kind='validation'
  AND user_id=peer.user_id AND epoch=peer.epoch AND scope_id=peer.scope_id AND pack_task_id=peer.pack_task_id
  AND slot_id=peer.slot_id AND root_id=peer.root_id AND version_id=peer.version_id AND job_id=peer.job_id
  AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO b FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'blind_id')::uuid AND kind='blind'
  AND user_id=peer.user_id AND epoch=peer.epoch AND scope_id=peer.scope_id AND pack_task_id=peer.pack_task_id
  AND slot_id=peer.slot_id AND root_id=peer.root_id AND version_id=peer.version_id AND job_id=peer.job_id
  AND xmin::text::bigint<>(txid_current()%4294967296);
 IF v.id IS NULL OR b.id IS NULL OR v.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
  OR (v.payload_json->>'source_hash',v.payload_json->>'content_hash') IS DISTINCT FROM (g.source_hash,g.content_hash)
  OR b.payload_json IS DISTINCT FROM peer.payload_json->'bundle'->'blind_solve'
  OR peer.payload_json->'bundle'->>'state' IS DISTINCT FROM 'completed'
  OR jsonb_array_length(peer.payload_json->'bundle'->'reports')<>6
  OR (SELECT array_agg(x->>'role' ORDER BY x->>'role') FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') x)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[] THEN
  RAISE check_violation USING MESSAGE='527 unchanged complete historical validation blind six-review required'; END IF;
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',g.request_json,
  'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 source changed after bank wait'; END IF;
 stamp:=clock_timestamp();
 IF stamp>=(ph.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='527 continuation phase stale after wait'; END IF;
END $old569$;
 new_body constant text := $new569$
DECLARE ref jsonb:=p->'ref'; lease jsonb:=p->'lease'; peer public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 v public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;b public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;
 g public.tutor_item_supply_private_generation_artifacts%ROWTYPE;ph record;stamp timestamptz;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','lease','review_id','validation_id','blind_id','artifact_id']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_committed_review_resume_v1' THEN
  RAISE check_violation USING MESSAGE='527 exact PRIVATE review continuation frame required'; END IF;
 PERFORM item_supply_internal.private_native_epoch((ref->>'user_id')::uuid,(ref->>'epoch')::bigint);
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='phase'
  AND pack_task_id=(ref->>'pack_task_id')::uuid AND user_id=(ref->>'user_id')::uuid AND epoch=(ref->>'epoch')::integer
  AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->>'job_id'=lease->>'job_id';
 IF ph.id IS NULL OR ph.payload_json->'ref' IS DISTINCT FROM ref
  OR ((ph.payload_json->'lease') - 'state_version'::text) IS DISTINCT FROM (lease - 'state_version'::text) THEN
  RAISE check_violation USING MESSAGE='527 current concrete phase required'; END IF;
 PERFORM item_supply_internal.assert_private_native_phase(ph.payload_json,ph.user_id,ph.epoch,ph.scope_id,ph.pack_task_id);
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'review_id')::uuid AND kind='review'
  AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id AND pack_task_id=ph.pack_task_id
  AND slot_id=(ref->>'slot_id')::uuid AND root_id=(ref->>'root_id')::uuid AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO g FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'artifact_id')::uuid
  AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id AND version_id=peer.version_id AND mode='live'
  AND xmin::text::bigint<>(txid_current()%4294967296);
 -- Original source locks before private bank/current material locks.
 IF g.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object(
  'ref',ref,'request',g.request_json,'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 current source for historical PRIVATE quality required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_versions WHERE id=g.version_id AND user_id=ph.user_id AND epoch=ph.epoch
  AND scope_id=ph.scope_id AND public_json=g.source_json->'public' AND private_json=g.source_json->'private' FOR SHARE;
 IF NOT FOUND OR peer.id IS NULL OR peer.payload_json->'ref' IS DISTINCT FROM ref
  OR peer.payload_json->>'artifact_id' IS DISTINCT FROM g.id::text
  OR peer.payload_json->'bundle'->'binding'->>'version_key' IS DISTINCT FROM g.version_id::text
  OR peer.payload_json->'bundle'->'binding'->>'source_hash' IS DISTINCT FROM g.source_hash
  OR peer.payload_json->'bundle'->'binding'->>'content_hash' IS DISTINCT FROM g.content_hash
  OR peer.checked_at>=peer.valid_until OR peer.created_at>=peer.valid_until THEN
  RAISE check_violation USING MESSAGE='527 actual lawful historical PRIVATE review required'; END IF;
 PERFORM item_supply_internal.assert_private_native_review_stage(peer);
 SELECT * INTO v FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'validation_id')::uuid AND kind='validation'
  AND user_id=peer.user_id AND epoch=peer.epoch AND scope_id=peer.scope_id AND pack_task_id=peer.pack_task_id
  AND slot_id=peer.slot_id AND root_id=peer.root_id AND version_id=peer.version_id AND job_id=peer.job_id
  AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO b FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'blind_id')::uuid AND kind='blind'
  AND user_id=peer.user_id AND epoch=peer.epoch AND scope_id=peer.scope_id AND pack_task_id=peer.pack_task_id
  AND slot_id=peer.slot_id AND root_id=peer.root_id AND version_id=peer.version_id AND job_id=peer.job_id
  AND xmin::text::bigint<>(txid_current()%4294967296);
 IF v.id IS NULL OR b.id IS NULL OR v.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
  OR (v.payload_json->>'source_hash',v.payload_json->>'content_hash') IS DISTINCT FROM (g.source_hash,g.content_hash)
  OR b.payload_json IS DISTINCT FROM peer.payload_json->'bundle'->'blind_solve'
  OR peer.payload_json->'bundle'->>'state' IS DISTINCT FROM 'completed'
  OR jsonb_array_length(peer.payload_json->'bundle'->'reports')<>6
  OR (SELECT array_agg(x->>'role' ORDER BY x->>'role') FROM jsonb_array_elements(peer.payload_json->'bundle'->'reports') x)
    IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','difficulty','security','technical']::text[] THEN
  RAISE check_violation USING MESSAGE='527 unchanged complete historical validation blind six-review required'; END IF;
 IF item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',g.request_json,
  'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 source changed after bank wait'; END IF;
 stamp:=clock_timestamp();
 IF stamp>=(ph.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='527 continuation phase stale after wait'; END IF;
END $new569$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='569 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.assert_private_native_resume_review(jsonb)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'assert_private_native_resume_review' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM '3802'::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['p']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='569 original resume review identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='569 original resume review body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='569 original resume review definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='569 resume review metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch569$;
