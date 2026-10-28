-- Exact runtime 42702 repair: disambiguate only the selected-slot count alias.
-- Frozen <=577. The complete predecessor is 576's $new_eligibility576$ body.
-- One existing function, unchanged semantics/OID/metadata; no other objects or rows.
-- Original isolated caller owns transaction and installer serialization.
DO $patch578$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old578$
DECLARE el record; p jsonb;s jsonb;m jsonb;ex jsonb;c jsonb;other jsonb;pc jsonb;pub record;q record;role jsonb;t timestamptz;is_mvp boolean;
BEGIN
 SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=eid;
 IF NOT FOUND OR el.txid<>txid_current() THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(el.user_id,el.epoch);
 m:=item_supply_internal.private_native_mapping_current(el.mapping_id,el.user_id,el.epoch);
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);
 p:=el.payload_json;s:=p->'snapshot';
 is_mvp:=(s->>'schema_version'='pack_snapshot_mvp_v1'
  AND s->>'relation_validation'='not_asserted_for_mvp'
  AND s->'relationship_receipt_hashes'='[]'::jsonb
  AND p->'relations'='[]'::jsonb) IS TRUE;
 IF m IS NULL OR ex IS NULL OR p->>'schema_version' IS DISTINCT FROM 'private_native_eligibility_v1'
  OR (p->>'mapping_id',p->>'exposure_id') IS DISTINCT FROM (el.mapping_id::text,el.exposure_snapshot_id::text)
  OR (s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp) OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR p->>'inputs_hash' IS DISTINCT FROM s->>'inputs_hash' OR s->>'authority_status' IS DISTINCT FROM 'trusted_caller_computation_only'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_typeof(s->'selected') IS DISTINCT FROM 'array' OR jsonb_array_length(s->'selected')<>5
  OR jsonb_typeof(p->'versions') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'versions')<>5
  OR (NOT is_mvp AND (jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations') NOT BETWEEN 1 AND 16))
  OR (SELECT count(DISTINCT v) FROM jsonb_array_elements_text(p->'versions') v)<>5
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='remediation')<>1 THEN RETURN false; END IF;
 -- Acquire ALL original source fences before ANY selected-version bank lock.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=(c->>'proof_id')::uuid AND kind='admission'
   AND user_id=el.user_id AND epoch=el.epoch AND scope_id=el.scope_id AND pack_task_id=el.pack_task_id AND version_id=(c->>'version_id')::uuid;
  IF NOT FOUND OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  pc:=item_supply_internal.private_native_publication_current((c->>'version_id')::uuid,el.user_id,el.epoch);
  SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE id=(c->>'publication_id')::uuid AND payload_json=pc;
  SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=pub.quality_id;
  SELECT value INTO role FROM jsonb_array_elements(m->'pack_request'->'demands') WHERE value->>'slot'=c->'member'->>'slot';
  IF pub.id IS NULL OR q.id IS NULL OR role IS NULL OR q.pack_task_id<>el.pack_task_id OR q.scope_id<>el.scope_id
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(p->'versions') v WHERE v.value=c->>'version_id')
   OR (c->>'owner_id',c->>'epoch',c->>'storage_scope_id',c->>'proof_id',c->>'materialization_id') IS DISTINCT FROM
     (el.user_id::text,el.epoch::text,role->>'storage_scope_id',q.id::text,pc->>'materialization_id')
   OR c->>'original_publication_hash' IS DISTINCT FROM pub.payload_hash
   OR c->>'original_materialization_hash' IS DISTINCT FROM pc->>'materialization_hash'
   OR c->>'original_proof_hash' IS DISTINCT FROM q.payload_json->>'clause_proof_hash'
   OR c->'type_evidence'->'content' IS DISTINCT FROM pub.content_json
   OR c->'type_evidence'->>'profile' IS DISTINCT FROM 'kc'
   OR c->'type_evidence'->>'course_mapping_hash' IS DISTINCT FROM m->>'mapping_hash'
   OR c->'type_evidence'->>'objective_hash' IS DISTINCT FROM role->'demand'->>'objective_hash'
   OR c->'type_evidence'->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(role->'demand'->'scope')
   OR c->'candidate'->'scope' IS DISTINCT FROM role->'demand'->'scope'
   OR c->'candidate'->>'visibility' IS DISTINCT FROM 'private'
   OR c->'candidate'->>'owner_ref' IS DISTINCT FROM role->'demand'->'scope'->>'owner_ref'
   OR c->'candidate'->>'item_handle' IS DISTINCT FROM pc->>'item_handle'
   OR c->'candidate'->>'content_hash' IS DISTINCT FROM pc->>'content_hash'
   OR c->'member'->>'slot' IS DISTINCT FROM q.payload_json->'ref'->>'slot'
   OR c->'member'->>'candidate_content_hash' IS DISTINCT FROM pc->>'content_hash'
OR c->'member'->>'actual_public_task_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(q.payload_json->'source'->'public')
   OR c->'member'->>'course_mapping_hash' IS DISTINCT FROM m->>'mapping_hash'
   OR (c->>'valid_until')::timestamptz<el.valid_until THEN RETURN false; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT q.slot_id) FROM tutor_item_supply_private_native_quality_evidence q WHERE q.id IN
   (SELECT (c->>'proof_id')::uuid FROM jsonb_array_elements(s->'selected') c))<>5 THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(s->'selected') WHERE value->>'version_id'<>c->>'version_id'
    UNION SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other)
    OR (NOT is_mvp AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,el.user_id,el.epoch,el.pack_task_id) IS DISTINCT FROM true) THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 -- Lock waits must not carry an old clock/source/exposure observation forward.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  SELECT payload_json INTO pc FROM tutor_item_supply_private_native_quality_evidence WHERE id=(c->>'proof_id')::uuid;
  IF item_supply_internal.private_native_source_current(pc) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND el.valid_until<=el.checked_at+interval '30 seconds'
  AND (s->>'checked_at')::timestamptz=el.checked_at AND (s->>'valid_until')::timestamptz=el.valid_until;
END $old578$;
 new_body constant text := $new578$
DECLARE el record; p jsonb;s jsonb;m jsonb;ex jsonb;c jsonb;other jsonb;pc jsonb;pub record;q record;role jsonb;t timestamptz;is_mvp boolean;
BEGIN
 SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=eid;
 IF NOT FOUND OR el.txid<>txid_current() THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(el.user_id,el.epoch);
 m:=item_supply_internal.private_native_mapping_current(el.mapping_id,el.user_id,el.epoch);
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);
 p:=el.payload_json;s:=p->'snapshot';
 is_mvp:=(s->>'schema_version'='pack_snapshot_mvp_v1'
  AND s->>'relation_validation'='not_asserted_for_mvp'
  AND s->'relationship_receipt_hashes'='[]'::jsonb
  AND p->'relations'='[]'::jsonb) IS TRUE;
 IF m IS NULL OR ex IS NULL OR p->>'schema_version' IS DISTINCT FROM 'private_native_eligibility_v1'
  OR (p->>'mapping_id',p->>'exposure_id') IS DISTINCT FROM (el.mapping_id::text,el.exposure_snapshot_id::text)
  OR (s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' AND NOT is_mvp) OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR p->>'inputs_hash' IS DISTINCT FROM s->>'inputs_hash' OR s->>'authority_status' IS DISTINCT FROM 'trusted_caller_computation_only'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_typeof(s->'selected') IS DISTINCT FROM 'array' OR jsonb_array_length(s->'selected')<>5
  OR jsonb_typeof(p->'versions') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'versions')<>5
  OR (NOT is_mvp AND (jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations') NOT BETWEEN 1 AND 16))
  OR (SELECT count(DISTINCT v) FROM jsonb_array_elements_text(p->'versions') v)<>5
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') x WHERE x->'member'->>'slot'='remediation')<>1 THEN RETURN false; END IF;
 -- Acquire ALL original source fences before ANY selected-version bank lock.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=(c->>'proof_id')::uuid AND kind='admission'
   AND user_id=el.user_id AND epoch=el.epoch AND scope_id=el.scope_id AND pack_task_id=el.pack_task_id AND version_id=(c->>'version_id')::uuid;
  IF NOT FOUND OR item_supply_internal.private_native_source_current(q.payload_json) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  pc:=item_supply_internal.private_native_publication_current((c->>'version_id')::uuid,el.user_id,el.epoch);
  SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE id=(c->>'publication_id')::uuid AND payload_json=pc;
  SELECT * INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=pub.quality_id;
  SELECT value INTO role FROM jsonb_array_elements(m->'pack_request'->'demands') WHERE value->>'slot'=c->'member'->>'slot';
  IF pub.id IS NULL OR q.id IS NULL OR role IS NULL OR q.pack_task_id<>el.pack_task_id OR q.scope_id<>el.scope_id
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(p->'versions') v WHERE v.value=c->>'version_id')
   OR (c->>'owner_id',c->>'epoch',c->>'storage_scope_id',c->>'proof_id',c->>'materialization_id') IS DISTINCT FROM
     (el.user_id::text,el.epoch::text,role->>'storage_scope_id',q.id::text,pc->>'materialization_id')
   OR c->>'original_publication_hash' IS DISTINCT FROM pub.payload_hash
   OR c->>'original_materialization_hash' IS DISTINCT FROM pc->>'materialization_hash'
   OR c->>'original_proof_hash' IS DISTINCT FROM q.payload_json->>'clause_proof_hash'
   OR c->'type_evidence'->'content' IS DISTINCT FROM pub.content_json
   OR c->'type_evidence'->>'profile' IS DISTINCT FROM 'kc'
   OR c->'type_evidence'->>'course_mapping_hash' IS DISTINCT FROM m->>'mapping_hash'
   OR c->'type_evidence'->>'objective_hash' IS DISTINCT FROM role->'demand'->>'objective_hash'
   OR c->'type_evidence'->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(role->'demand'->'scope')
   OR c->'candidate'->'scope' IS DISTINCT FROM role->'demand'->'scope'
   OR c->'candidate'->>'visibility' IS DISTINCT FROM 'private'
   OR c->'candidate'->>'owner_ref' IS DISTINCT FROM role->'demand'->'scope'->>'owner_ref'
   OR c->'candidate'->>'item_handle' IS DISTINCT FROM pc->>'item_handle'
   OR c->'candidate'->>'content_hash' IS DISTINCT FROM pc->>'content_hash'
   OR c->'member'->>'slot' IS DISTINCT FROM q.payload_json->'ref'->>'slot'
   OR c->'member'->>'candidate_content_hash' IS DISTINCT FROM pc->>'content_hash'
OR c->'member'->>'actual_public_task_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(q.payload_json->'source'->'public')
   OR c->'member'->>'course_mapping_hash' IS DISTINCT FROM m->>'mapping_hash'
   OR (c->>'valid_until')::timestamptz<el.valid_until THEN RETURN false; END IF;
 END LOOP;
 IF (SELECT count(DISTINCT slot_evidence.slot_id) FROM tutor_item_supply_private_native_quality_evidence slot_evidence WHERE slot_evidence.id IN
   (SELECT (selected_proof.value->>'proof_id')::uuid FROM jsonb_array_elements(s->'selected') AS selected_proof(value)))<>5 THEN RETURN false; END IF;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'type_evidence'->'content' FROM jsonb_array_elements(s->'selected') WHERE value->>'version_id'<>c->>'version_id'
    UNION SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other)
    OR (NOT is_mvp AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,el.user_id,el.epoch,el.pack_task_id) IS DISTINCT FROM true) THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 -- Lock waits must not carry an old clock/source/exposure observation forward.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  SELECT payload_json INTO pc FROM tutor_item_supply_private_native_quality_evidence WHERE id=(c->>'proof_id')::uuid;
  IF item_supply_internal.private_native_source_current(pc) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current(el.exposure_snapshot_id,el.user_id,el.epoch);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND el.valid_until<=el.checked_at+interval '30 seconds'
  AND (s->>'checked_at')::timestamptz=el.checked_at AND (s->>'valid_until')::timestamptz=el.valid_until;
END $new578$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001' THEN
  RAISE check_violation USING MESSAGE='578 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p
  WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_native_eligibility_current(uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_native_eligibility_current' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM ('pg_catalog.uuid'::regtype::oid::text)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['eid']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
 THEN RAISE check_violation USING MESSAGE='578 original eligibility receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='578 original eligibility receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='578 original eligibility receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='578 eligibility receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch578$;
