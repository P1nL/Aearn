-- A2 prospective PRIVATE continuation. Zero tables. Requires reviewed524/526.
-- Original response writer, separate domain FKs. PUBLIC FK is retained unchanged;
-- only an exact current PRIVATE consumer can use the alternate PRIVATE columns.
ALTER TABLE tutor_knowledge_check_response_receipts ADD COLUMN IF NOT EXISTS private_native_version_id uuid;
ALTER TABLE tutor_knowledge_check_response_receipts ADD COLUMN IF NOT EXISTS private_native_epoch bigint;
ALTER TABLE tutor_knowledge_check_response_receipts ADD COLUMN IF NOT EXISTS private_native_scope_id uuid;
ALTER TABLE tutor_knowledge_check_response_receipts ALTER COLUMN learning_item_version_id DROP NOT NULL;
DO $private_kc_response_fks$
BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_knowledge_check_response_receipts'::regclass AND conname='chk_private_native_kc_response_domain') THEN
  ALTER TABLE tutor_knowledge_check_response_receipts ADD CONSTRAINT chk_private_native_kc_response_domain CHECK(
   (learning_item_version_id IS NOT NULL AND num_nonnulls(private_native_version_id,private_native_epoch,private_native_scope_id)=0)
   OR (learning_item_version_id IS NULL AND num_nonnulls(private_native_version_id,private_native_epoch,private_native_scope_id)=3 AND private_native_epoch>=1));
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_constraint WHERE conrelid='tutor_knowledge_check_response_receipts'::regclass AND conname='fk_private_native_kc_response_version') THEN
  ALTER TABLE tutor_knowledge_check_response_receipts ADD CONSTRAINT fk_private_native_kc_response_version
   FOREIGN KEY(private_native_version_id,user_id,private_native_epoch,private_native_scope_id)
   REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,scope_id) ON DELETE RESTRICT;
 END IF;
END $private_kc_response_fks$;
-- Historical quality DATA never changes its producer, runs, deadline or mode.
CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_resume_review(p jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
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
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_resume_review(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_resume_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.payload_json->>'schema_version'='private_native_committed_review_resume_v1' THEN
  IF NEW.record_kind<>'private_attachment' OR NEW.pack_task_id::text IS DISTINCT FROM NEW.payload_json->'ref'->>'pack_task_id'
   OR NEW.user_id::text IS DISTINCT FROM NEW.payload_json->'ref'->>'user_id'
   OR NEW.epoch::text IS DISTINCT FROM NEW.payload_json->'ref'->>'epoch'
   OR NEW.scope_id::text IS DISTINCT FROM NEW.payload_json->'ref'->>'scope_id' THEN
   RAISE check_violation USING MESSAGE='527 PRIVATE continuation journal coordinates required'; END IF;
  PERFORM item_supply_internal.assert_private_native_resume_review(NEW.payload_json);
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_resume_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_resume_insert ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER a000_private_native_resume_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_resume_insert();

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_resume_review(rid uuid,p jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE task record;
BEGIN
 SELECT * INTO task FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->'ref'->>'pack_task_id')::uuid
  AND record_kind='task' AND user_id=(p->'ref'->>'user_id')::uuid AND epoch=(p->'ref'->>'epoch')::integer
  AND scope_id=(p->'ref'->>'scope_id')::uuid;
 IF task.id IS NULL THEN RAISE check_violation USING MESSAGE='527 same existing PRIVATE task required'; END IF;
 PERFORM item_supply_internal.assert_private_native_resume_review(p);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(rid,task.id,task.user_id,task.epoch,task.scope_id,'private_attachment','private.resume.'||replace(rid::text,'-',''),task.intent_hash,p);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_resume_review(uuid,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_resume_current(rid uuid,job uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_attachment'
  AND payload_json->>'schema_version'='private_native_committed_review_resume_v1' AND payload_json->'lease'->>'job_id'=job::text;
 IF r.id IS NULL THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_private_native_resume_review(r.payload_json);
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_resume_current(uuid,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_review_evidence_job(current_job uuid,review_id uuid) RETURNS uuid
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record; original_job uuid;
BEGIN
 FOR r IN SELECT * FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='private_attachment'
  AND payload_json->>'schema_version'='private_native_committed_review_resume_v1'
  AND payload_json->'lease'->>'job_id'=current_job::text AND payload_json->>'review_id'=review_id::text LOOP
  IF item_supply_internal.private_native_resume_current(r.id,current_job) THEN
   SELECT job_id INTO original_job FROM tutor_item_supply_private_native_quality_evidence WHERE id=review_id AND kind='review'
    AND user_id=r.user_id AND epoch=r.epoch AND pack_task_id=r.pack_task_id AND scope_id=r.scope_id;
   IF original_job IS NOT NULL THEN RETURN original_job; END IF;
  END IF;
 END LOOP;
 RETURN current_job; -- original524 branch unchanged without exact fresh issuer.
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_review_evidence_job(uuid,uuid) FROM PUBLIC;

-- Exact524 helper frame: historical child evidence remains bound to its ORIGINAL
-- producer job; only the independently checked current continuation authorizes reuse.
DO $upgrade_resume_normal$
DECLARE f record;old_hash text:='1b8d19f38f69435383d326abfa10957f8fca0362ff900f97f4e58bba90f8d737';
 new_hash text:='f3a13450a89d1f6faf9968efeb6f1fcfd54a8f5d234159b2fc5a26076464ccd4';definition text;
BEGIN
 SELECT p.*,l.lanname,encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') AS body_hash INTO f
 FROM pg_proc p JOIN pg_namespace ns ON ns.oid=p.pronamespace JOIN pg_language l ON l.oid=p.prolang
 WHERE ns.nspname='item_supply_internal' AND p.proname='assert_private_native_normal'
 AND p.pronargs=1 AND p.proargtypes[0]='tutor_item_supply_private_native_quality_evidence'::regtype;
 IF f.oid IS NULL OR f.lanname<>'plpgsql' OR NOT f.prosecdef OR f.provolatile<>'v' OR f.proisstrict
  OR f.prorettype<>'void'::regtype OR f.prokind<>'f' OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
  RAISE check_violation USING MESSAGE='527 original524 normal receiver attributes changed'; END IF;
 IF f.body_hash=new_hash THEN RETURN; END IF;
 IF f.body_hash<>old_hash THEN RAISE check_violation USING MESSAGE='527 original524 normal receiver fingerprint changed'; END IF;
 definition:=replace(pg_get_functiondef(f.oid),E'\r\n',E'\n');
 IF (length(definition)-length(replace(definition,'AND job_id=n.job_id AND xmin::text::bigint<>','')))/length('AND job_id=n.job_id AND xmin::text::bigint<>')<>3 THEN
  RAISE check_violation USING MESSAGE='527 exact three original evidence job frames required'; END IF;
 EXECUTE replace(definition,'AND job_id=n.job_id AND xmin::text::bigint<>',
  'AND job_id=item_supply_internal.private_native_review_evidence_job(n.job_id,(p->>''review_id'')::uuid) AND xmin::text::bigint<>');
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=f.oid AND encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex')=new_hash) THEN
  RAISE check_violation USING MESSAGE='527 resulting normal receiver fingerprint mismatch'; END IF;
END $upgrade_resume_normal$;

-- Historical investigation is DATA, not the expired producer's current grant.
-- Preserve every original524 dispute/reference/run/settlement check. Only the
-- temporal assertion becomes checked-at/created-at evidence, surrounded by the
-- exact fresh continuation issuer. The original insertion receiver is untouched.
DO $derive_historical_private_investigation$
DECLARE f record;existing record;body text;old_frame text:=$old_investigation_time$ IF n.checked_at>stamp OR stamp>=n.valid_until OR stamp>=(aux.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='524 PRIVATE investigation late after receipt waits'; END IF;$old_investigation_time$;new_frame text:=$historical_investigation_time$ IF n.checked_at>stamp OR n.checked_at>=n.valid_until OR n.created_at>=n.valid_until
  OR n.created_at<aux.created_at OR n.checked_at>=(aux.payload_json->>'valid_until')::timestamptz
  OR n.created_at>=(aux.payload_json->>'valid_until')::timestamptz
  OR n.job_id::text IS DISTINCT FROM p->'lease'->>'job_id' THEN
  RAISE check_violation USING MESSAGE='527 PRIVATE investigation was not lawful within original producer phase'; END IF;
 IF n.kind<>'investigation' OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence actual
  WHERE actual.id=n.id AND actual.kind='investigation' AND to_jsonb(actual)=to_jsonb(n)
  AND actual.xmin::text::bigint<>(txid_current()%4294967296)) OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal continuation WHERE continuation.id=resume
  AND continuation.record_kind='private_attachment' AND continuation.user_id=n.user_id AND continuation.epoch=n.epoch
  AND continuation.scope_id=n.scope_id AND continuation.pack_task_id=n.pack_task_id
  AND continuation.payload_json->>'schema_version'='private_native_committed_review_resume_v1'
  AND continuation.payload_json->'ref' IS NOT DISTINCT FROM n.payload_json->'ref'
  AND continuation.payload_json->>'review_id'=n.payload_json->>'parent_review_id'
  AND item_supply_internal.private_native_resume_current(continuation.id,(continuation.payload_json->'lease'->>'job_id')::uuid)) THEN
  RAISE check_violation USING MESSAGE='527 exact fresh PRIVATE investigation continuation required'; END IF;$historical_investigation_time$;fresh_gate text:=$fresh_investigation_gate$ IF n.kind<>'investigation' OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_native_quality_evidence actual
  WHERE actual.id=n.id AND actual.kind='investigation' AND to_jsonb(actual)=to_jsonb(n)
  AND actual.xmin::text::bigint<>(txid_current()%4294967296)) OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal continuation WHERE continuation.id=resume
  AND continuation.record_kind='private_attachment' AND continuation.user_id=n.user_id AND continuation.epoch=n.epoch
  AND continuation.scope_id=n.scope_id AND continuation.pack_task_id=n.pack_task_id
  AND continuation.payload_json->>'schema_version'='private_native_committed_review_resume_v1'
  AND continuation.payload_json->'ref' IS NOT DISTINCT FROM n.payload_json->'ref'
  AND continuation.payload_json->>'review_id'=n.payload_json->>'parent_review_id'
  AND item_supply_internal.private_native_resume_current(continuation.id,(continuation.payload_json->'lease'->>'job_id')::uuid)) THEN
  RAISE check_violation USING MESSAGE='527 exact fresh PRIVATE investigation continuation required'; END IF;$fresh_investigation_gate$;
BEGIN
 SELECT p.*,l.lanname,encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') AS body_hash INTO f
 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid='item_supply_internal.assert_private_native_investigation(tutor_item_supply_private_native_quality_evidence)'::regprocedure;
 IF f.lanname<>'plpgsql' OR NOT f.prosecdef OR f.provolatile<>'v' OR f.proisstrict OR f.prokind<>'f'
  OR f.prorettype<>'void'::regtype OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  OR f.body_hash<>'cd9b5d4fffe345612ab197eaa9bc42fa781fc1d37bd48ad58131d797215b372e' THEN
  RAISE check_violation USING MESSAGE='527 exact frozen investigation receiver required'; END IF;
 SELECT p.*,l.lanname,encode(sha256(convert_to(replace(p.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') AS body_hash INTO existing
 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid=to_regprocedure('item_supply_internal.assert_private_native_historical_investigation(tutor_item_supply_private_native_quality_evidence,uuid)');
 IF existing.oid IS NOT NULL AND (existing.lanname<>'plpgsql' OR NOT existing.prosecdef OR existing.provolatile<>'v'
  OR existing.proisstrict OR existing.prokind<>'f' OR existing.prorettype<>'void'::regtype
  OR existing.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
  OR existing.body_hash<>'49d8d824d22601fba1aad9170a324e6251285318e61b232261b556cf69f95957') THEN
  RAISE check_violation USING MESSAGE='527 historical investigation receiver fingerprint changed'; END IF;
 body:=replace(f.prosrc,E'\r\n',E'\n');
 IF (length(body)-length(replace(body,old_frame,'')))/length(old_frame)<>1
  OR (length(body)-length(replace(body,E'\nBEGIN\n','')))/length(E'\nBEGIN\n')<>1 THEN
  RAISE check_violation USING MESSAGE='527 original investigation temporal frame changed'; END IF;
 body:=replace(replace(body,E'\nBEGIN\n',E'\nBEGIN\n'||fresh_gate||E'\n'),old_frame,new_frame);
 IF encode(sha256(convert_to(body,'UTF8')),'hex')<>'49d8d824d22601fba1aad9170a324e6251285318e61b232261b556cf69f95957' THEN
  RAISE check_violation USING MESSAGE='527 exact derived investigation body required'; END IF;
 EXECUTE format('CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_historical_investigation(n tutor_item_supply_private_native_quality_evidence,resume uuid) RETURNS void LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS %L',body);
END $derive_historical_private_investigation$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_historical_investigation(tutor_item_supply_private_native_quality_evidence,uuid) FROM PUBLIC;


CREATE OR REPLACE FUNCTION item_supply_internal.private_native_resume_investigation(iid uuid,resume uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;i public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;peer record;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=resume AND record_kind='private_attachment'
  AND payload_json->>'schema_version'='private_native_committed_review_resume_v1';
 IF r.id IS NULL OR item_supply_internal.private_native_resume_current(r.id,(r.payload_json->'lease'->>'job_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT * INTO i FROM tutor_item_supply_private_native_quality_evidence WHERE id=iid AND kind='investigation'
  AND user_id=r.user_id AND epoch=r.epoch AND scope_id=r.scope_id AND pack_task_id=r.pack_task_id
  AND slot_id=(r.payload_json->'ref'->>'slot_id')::uuid AND root_id=(r.payload_json->'ref'->>'root_id')::uuid
  AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO peer FROM tutor_item_supply_private_native_quality_evidence WHERE id=(r.payload_json->>'review_id')::uuid;
 IF i.id IS NULL OR i.payload_json->'ref' IS DISTINCT FROM r.payload_json->'ref'
  OR i.payload_json->>'parent_review_id' IS DISTINCT FROM peer.id::text
  OR i.payload_json->>'parent_review_hash' IS DISTINCT FROM peer.payload_hash
  OR i.version_id<>peer.version_id OR i.checked_at>=i.valid_until OR i.created_at>=i.valid_until THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_private_native_historical_investigation(i,resume);
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_resume_investigation(uuid,uuid) FROM PUBLIC;

-- Scheduling inheritance only. Original historical artifact is DATA, never an
-- old writer/lease or an execution/score/admission capability.
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_inherit_generation(p jsonb) RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE ref jsonb:=p->'ref';lease jsonb:=p->'lease';ph record;old_phase record;g record;control record;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['ref','lease','artifact_id']) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 exact inherited PRIVATE generation coordinates required'; END IF;
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='phase'
  AND pack_task_id=(ref->>'pack_task_id')::uuid AND user_id=(ref->>'user_id')::uuid AND epoch=(ref->>'epoch')::integer
  AND scope_id=(ref->>'scope_id')::uuid AND payload_json->>'job_id'=lease->>'job_id'
  AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->'ref'=ref;
 IF ph.id IS NULL OR (ph.payload_json->'lease'-'state_version') IS DISTINCT FROM (lease-'state_version') THEN
  RAISE check_violation USING MESSAGE='527 original fresh PRIVATE inheritance phase required'; END IF;
 PERFORM item_supply_internal.assert_private_native_phase(ph.payload_json,ph.user_id,ph.epoch,ph.scope_id,ph.pack_task_id);
 SELECT * INTO g FROM tutor_item_supply_private_generation_artifacts WHERE id=(p->>'artifact_id')::uuid
  AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id AND mode='live'
  AND xmin::text::bigint<>(txid_current()%4294967296);
 IF g.id IS NULL OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',g.request_json,
  'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 inherited generation source/current required'; END IF;
 SELECT * INTO old_phase FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='phase'
  AND pack_task_id=ph.pack_task_id AND user_id=ph.user_id AND epoch=ph.epoch AND scope_id=ph.scope_id
  AND payload_json->>'job_id'=g.job_id::text AND payload_json->'ref'=ref
  AND payload_json->>'schema_version'='private_native_phase_v1' AND xmin::text::bigint<>(txid_current()%4294967296);
 SELECT * INTO control FROM tutor_item_supply_private_job_controls WHERE job_id=g.job_id AND user_id=ph.user_id AND epoch=ph.epoch;
 IF old_phase.id IS NULL OR control.job_id IS NULL OR control.parent_deadline<=g.created_at
  OR g.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_runtime_settlements s
   JOIN tutor_item_supply_private_reservations r ON r.id=s.reservation_id AND r.user_id=s.user_id AND r.epoch=s.epoch
   WHERE r.job_id=g.job_id AND r.root_id=(ref->>'root_id')::uuid AND r.user_id=ph.user_id AND r.epoch=ph.epoch
    AND r.scope_id=ph.scope_id AND s.usage_state='unknown' AND s.xmin::text::bigint<>(txid_current()%4294967296)) THEN
  RAISE check_violation USING MESSAGE='527 actual same fixed-slot historical generation/settlement required'; END IF;
 PERFORM 1 FROM tutor_item_supply_private_versions WHERE id=g.version_id AND user_id=ph.user_id AND epoch=ph.epoch
  AND scope_id=ph.scope_id AND public_json=g.source_json->'public' AND private_json=g.source_json->'private' FOR SHARE;
 IF NOT FOUND OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',g.request_json,
  'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true OR clock_timestamp()>=(ph.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='527 inherited generation changed after wait'; END IF;
 RETURN g.artifact_hash;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_inherit_generation(jsonb) FROM PUBLIC;

-- Ordinary KC successors only; no assessment, Gate, Attempt or progression right.
CREATE OR REPLACE FUNCTION item_supply_internal.private_native_successor_candidate(parent uuid,eligibility uuid,target uuid,purpose text,allow_run uuid DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE b record;cr record;el record;res record;a record;pp jsonb;tp jsonb;pq jsonb;tq jsonb;member jsonb;mapping jsonb;
BEGIN
 IF purpose NOT IN('remediation','transfer_check') THEN RETURN false; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=parent;
 SELECT * INTO cr FROM tutor_item_supply_private_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';
 SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=eligibility AND txid=txid_current();
 SELECT * INTO res FROM tutor_item_supply_private_native_assessment_reservations WHERE id=cr.reservation_id;
 IF b.artifact_id IS NULL OR cr.id IS NULL OR res.id IS NULL OR el.id IS NULL
  OR (el.user_id,el.epoch,el.scope_id,el.pack_task_id) IS DISTINCT FROM (b.user_id,b.epoch,b.scope_id,b.pack_task_id)
  OR el.mapping_id::text IS DISTINCT FROM cr.payload_json->>'mapping_id' OR target=b.version_id
  OR item_supply_internal.private_native_eligibility_current(el.id) IS DISTINCT FROM true THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(b.user_id,b.epoch);
 mapping:=item_supply_internal.private_native_mapping_current(el.mapping_id,b.user_id,b.epoch);
 SELECT * INTO a FROM tutor_learning_artifacts WHERE id=parent AND user_id=b.user_id AND owner_kind='learning_item'
  AND owner_id=b.version_id AND artifact_kind='knowledge_check' AND active_attempt_id IS NULL;
 IF a.id IS NULL OR mapping IS NULL OR a.knowledge_key IS DISTINCT FROM mapping->'frozen_node'->>'knowledge_key'
  OR a.learning_track_id::text IS DISTINCT FROM mapping->'frozen_node'->>'track_id' THEN RETURN false; END IF;
 SELECT value INTO member FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') WHERE value->>'version_id'=target::text
  AND value->'member'->>'slot'=CASE WHEN purpose='remediation' THEN 'remediation' ELSE 'practice' END;
 IF member IS NULL OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(res.payload_json->'versions') v WHERE v.value=target::text)
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE NOT EXISTS
    (SELECT 1 FROM jsonb_array_elements_text(res.payload_json->'versions') v WHERE v.value=c->>'version_id')) THEN RETURN false; END IF;
 pp:=item_supply_internal.private_native_publication_current(b.version_id,b.user_id,b.epoch);
 tp:=item_supply_internal.private_native_publication_current(target,b.user_id,b.epoch);
 SELECT payload_json INTO pq FROM tutor_item_supply_private_native_quality_evidence WHERE id=(pp->>'quality_id')::uuid;
 SELECT payload_json INTO tq FROM tutor_item_supply_private_native_quality_evidence WHERE id=(tp->>'quality_id')::uuid;
 IF pp IS NULL OR tp IS NULL OR pq IS NULL OR tq IS NULL OR tq->'ref'->>'pack_task_id'<>b.pack_task_id::text
  OR tq->'source'->'public'->>'kind'<>'knowledge_check'
  OR (tq->'source'->'public'->>'knowledge_key',tq->'source'->'public'->>'language_id') IS DISTINCT FROM
    (pq->'source'->'public'->>'knowledge_key',pq->'source'->'public'->>'language_id')
  OR item_supply_internal.private_native_clone((SELECT content_json FROM tutor_item_supply_private_native_publications WHERE id=(pp->>'publication_id')::uuid),
    (SELECT content_json FROM tutor_item_supply_private_native_publications WHERE id=(tp->>'publication_id')::uuid)) THEN RETURN false; END IF;
 IF purpose='remediation' THEN
  IF pq->'source'->'public'->>'remediation_item_key' IS NULL
   OR pq->'source'->'public'->>'remediation_item_key' IS DISTINCT FROM tq->'source'->'public'->>'item_key'
   OR COALESCE(pq->'source'->'blueprint'->'remediation_policy'->>'first_failure','') NOT IN('hint_then_remediate','explain_then_remediate')
   OR (tq->'source'->'public'->>'difficulty') NOT IN(pq->'source'->'public'->>'difficulty',
       'D'||greatest(1,substring(pq->'source'->'public'->>'difficulty' FROM 2)::integer-1)::text) THEN RETURN false; END IF;
 ELSIF tq->'source'->'public'->>'difficulty' IS DISTINCT FROM pq->'source'->'public'->>'difficulty' THEN RETURN false;
 END IF;
 RETURN NOT EXISTS(SELECT 1 FROM tutor_learning_artifacts used WHERE used.user_id=b.user_id AND used.learning_track_id=a.learning_track_id
  AND used.knowledge_key=a.knowledge_key AND used.owner_kind='learning_item' AND used.owner_id=target
  AND (allow_run IS NULL OR used.turn_id IS DISTINCT FROM allow_run));
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_candidate(uuid,uuid,uuid,text,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_successor_selected(action_receipt uuid,eligibility uuid,target uuid,purpose text) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;a record;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE id=action_receipt AND mode='current'
  AND action IN('respond','request_direct_answer') AND txid=txid_current();
 IF r.id IS NULL OR item_supply_internal.private_native_consumer_current(r.id) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT * INTO a FROM tutor_learning_artifacts WHERE id=r.artifact_id AND user_id=r.user_id AND version=r.artifact_version;
 IF a.id IS NULL OR (r.action='request_direct_answer' AND purpose<>'transfer_check')
  OR (purpose='remediation' AND a.purpose<>'knowledge_check')
  OR (purpose='transfer_check' AND r.action='respond' AND a.purpose<>'remediation') THEN RETURN false; END IF;
 RETURN item_supply_internal.private_native_successor_candidate(r.artifact_id,eligibility,target,purpose);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_selected(uuid,uuid,uuid,text) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_successor_delivery_current(parent uuid,eligibility uuid,target uuid,purpose text,allow_run uuid DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a record;b record;r record;field text;
BEGIN
 IF item_supply_internal.private_native_successor_candidate(parent,eligibility,target,purpose,allow_run) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=parent;
 SELECT * INTO a FROM tutor_learning_artifacts WHERE id=parent AND user_id=b.user_id AND state='completed'
  AND artifact_kind='knowledge_check' AND owner_kind='learning_item' AND owner_id=b.version_id AND active_attempt_id IS NULL;
 SELECT * INTO r FROM tutor_knowledge_check_response_receipts WHERE id=(a.presentation_json->>'response_receipt_id')::uuid
  AND artifact_id=a.id AND user_id=a.user_id AND private_native_version_id=a.owner_id AND private_native_epoch=b.epoch
  AND private_native_scope_id=b.scope_id AND artifact_version=a.version-1
  AND learning_track_id=a.learning_track_id AND knowledge_key=a.knowledge_key AND outcome='incorrect';
 field:=CASE WHEN purpose='remediation' THEN 'remediation_handle' ELSE 'transfer_handle' END;
 RETURN a.id IS NOT NULL AND r.id IS NOT NULL AND a.presentation_json->>'outcome'='incorrect'
  AND a.presentation_json->>field='lip:v2:'||target::text
  AND ((purpose='remediation' AND a.purpose='knowledge_check' AND r.response_kind<>'direct_answer')
   OR (purpose='transfer_check' AND (r.response_kind='direct_answer' OR a.purpose='remediation')));
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_delivery_current(uuid,uuid,uuid,text,uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_successor_creation_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;b record;a record;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE id=rid AND mode='create' AND txid=txid_current();
 IF r.id IS NULL OR r.payload_json->>'parent_artifact_id' IS NULL
  OR r.payload_json->'request'->>'purpose' NOT IN('remediation','transfer_check') THEN RETURN false; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=(r.payload_json->>'parent_artifact_id')::uuid
  AND user_id=r.user_id AND epoch=r.epoch AND scope_id=r.scope_id AND pack_task_id=r.pack_task_id;
 SELECT * INTO a FROM tutor_learning_artifacts WHERE id=b.artifact_id AND user_id=r.user_id;
 IF b.artifact_id IS NULL OR a.learning_track_id::text IS DISTINCT FROM r.payload_json->'request'->>'learning_track_id'
  OR a.knowledge_key IS DISTINCT FROM r.payload_json->'request'->>'knowledge_key' THEN RETURN false; END IF;
 RETURN item_supply_internal.private_native_successor_delivery_current(b.artifact_id,r.eligibility_id,r.version_id,r.payload_json->'request'->>'purpose',r.run_id);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_successor_creation_current(uuid) FROM PUBLIC;

DO $upgrade_private_native_consumer_current$
DECLARE f record;definition text;
BEGIN
 SELECT p.*,l.lanname,encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') AS body_hash INTO f
 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid='item_supply_internal.private_native_consumer_current(uuid)'::regprocedure;
 IF f.lanname<>'plpgsql' OR NOT f.prosecdef OR f.provolatile<>'v' OR f.proisstrict OR f.prokind<>'f' OR f.prorettype<>'boolean'::regtype
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
  RAISE check_violation USING MESSAGE='527 private_native_consumer_current receiver attributes changed'; END IF;
 IF f.body_hash='a65bfa77c31c37315b71d9e6728b04716bdaf892f00a8892b3d2544a2244f4d5' THEN RETURN; END IF;
 IF f.body_hash<>'d15865e10d2a92dcd31519104f0eaeb34dc0f9273fabe60e17f528a76a8819d7' THEN RAISE check_violation USING MESSAGE='527 private_native_consumer_current receiver fingerprint changed'; END IF;
 definition:=replace(pg_get_functiondef(f.oid),E'\r\n',E'\n');
 IF position($old0$WHERE value->>'version_id'=r.version_id::text AND value->'member'->>'slot'='practice';$old0$ IN definition)=0 THEN RAISE check_violation USING MESSAGE='527 exact private_native_consumer_current frame absent'; END IF;
 definition:=replace(definition,$old0$WHERE value->>'version_id'=r.version_id::text AND value->'member'->>'slot'='practice';$old0$,$new0$WHERE value->>'version_id'=r.version_id::text AND value->'member'->>'slot'=CASE WHEN p->'request'->>'purpose'='remediation' THEN 'remediation' ELSE 'practice' END;$new0$);
 IF position($old1$'learning_item','knowledge_check','knowledge_check',m->'frozen_node'->>'knowledge_key'$old1$ IN definition)=0 THEN RAISE check_violation USING MESSAGE='527 exact private_native_consumer_current frame absent'; END IF;
 definition:=replace(definition,$old1$'learning_item','knowledge_check','knowledge_check',m->'frozen_node'->>'knowledge_key'$old1$,$new1$'learning_item','knowledge_check',CASE WHEN creation->>'parent_artifact_id' IS NOT NULL AND q->>'purpose' IN('remediation','transfer_check') THEN q->>'purpose' ELSE 'knowledge_check' END,m->'frozen_node'->>'knowledge_key'$new1$);
 IF position($old2$  creation:=p;q:=p->'request';$old2$ IN definition)=0 THEN RAISE check_violation USING MESSAGE='527 exact private_native_consumer_current frame absent'; END IF;
 definition:=replace(definition,$old2$  creation:=p;q:=p->'request';$old2$,$new2$  creation:=p;q:=p->'request';
  IF (q->>'purpose'<>'knowledge_check' OR p->>'parent_artifact_id' IS NOT NULL) AND item_supply_internal.private_native_successor_creation_current(r.id) IS DISTINCT FROM true THEN RETURN false; END IF;$new2$);
 EXECUTE definition;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=f.oid AND encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex')='a65bfa77c31c37315b71d9e6728b04716bdaf892f00a8892b3d2544a2244f4d5') THEN
  RAISE check_violation USING MESSAGE='527 private_native_consumer_current resulting receiver fingerprint changed'; END IF;
END $upgrade_private_native_consumer_current$;

-- Final exact request/purpose upgrade appears once below.

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_relation_actual_content(v uuid,u uuid,e bigint) RETURNS jsonb
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb;c jsonb;r record;
BEGIN
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_versions WHERE id=v AND user_id=u AND epoch=e) THEN
  p:=item_supply_internal.private_native_publication_current(v,u,e);
  SELECT content_json INTO c FROM tutor_item_supply_private_native_publications WHERE id=(p->>'publication_id')::uuid AND user_id=u AND epoch=e;
  RETURN c;
 END IF;
 -- PUBLIC counterpart is restricted to a fresh original same-user eligibility;
 -- it is NOT arbitrary catalog browsing or a private label on a PUBLIC version.
 FOR r IN SELECT * FROM tutor_item_supply_native_eligibility WHERE user_id=u AND epoch=e AND txid=txid_current()
  AND valid_until>clock_timestamp() LOOP
  SELECT x->'type_evidence'->'content' INTO c FROM jsonb_array_elements(r.snapshot_json->'selected') x WHERE x->>'version_id'=v::text;
  IF c IS NOT NULL THEN RETURN c; END IF;
 END LOOP;
 RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_relation_actual_content(uuid,uuid,bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.assert_private_native_relation_repair(p jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE ref jsonb:=p->'ref';u uuid:=(ref->>'user_id')::uuid;e bigint:=(ref->>'epoch')::bigint;
 parent jsonb;q jsonb;leftc jsonb;rightc jsonb;n public.tutor_item_supply_private_native_quality_evidence%ROWTYPE;pair jsonb;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','ref','parent_version_id','left_version_id','right_version_id','relation_receipt_id']) IS DISTINCT FROM true
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_relation_repair_required_v1'
  OR p->>'parent_version_id' NOT IN(p->>'left_version_id',p->>'right_version_id')
  OR p->>'left_version_id'=p->>'right_version_id' THEN
  RAISE check_violation USING MESSAGE='527 exact actual same-slot relation repair subject required'; END IF;
 PERFORM item_supply_internal.private_native_epoch(u,e);
 parent:=item_supply_internal.private_native_publication_current((p->>'parent_version_id')::uuid,u,e);
 SELECT payload_json INTO q FROM tutor_item_supply_private_native_quality_evidence WHERE id=(parent->>'quality_id')::uuid;
 IF q IS NULL OR q->'ref' IS DISTINCT FROM ref OR ref->>'slot'<>'assessment'
  OR item_supply_internal.private_native_task_enhancement((ref->>'pack_task_id')::uuid,u,e,(ref->>'scope_id')::uuid) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 current qualified same private assessment slot/root required'; END IF;
 leftc:=item_supply_internal.private_native_relation_actual_content((p->>'left_version_id')::uuid,u,e);
 rightc:=item_supply_internal.private_native_relation_actual_content((p->>'right_version_id')::uuid,u,e);
 IF leftc IS NULL OR rightc IS NULL THEN RAISE check_violation USING MESSAGE='527 actual relation counterpart current authority required'; END IF;
 IF p->>'relation_receipt_id' IS NULL THEN
  IF item_supply_internal.private_native_clone(leftc,rightc) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='527 machine clone is not a fabricated peer finding'; END IF;
 ELSE
  SELECT * INTO n FROM tutor_item_supply_private_native_quality_evidence WHERE id=(p->>'relation_receipt_id')::uuid AND kind='relation'
   AND user_id=u AND epoch=e AND pack_task_id=(ref->>'pack_task_id')::uuid AND scope_id=(ref->>'scope_id')::uuid
   AND checked_at<valid_until AND xmin::text::bigint<>(txid_current()%4294967296);
  IF n.id IS NULL THEN RAISE check_violation USING MESSAGE='527 original committed complete four-role failure required'; END IF;
  PERFORM item_supply_internal.assert_private_native_relation(n);
  SELECT x INTO pair FROM jsonb_array_elements(n.payload_json->'pairs') x WHERE
   (x->>'left_version_id',x->>'right_version_id') IN((p->>'left_version_id',p->>'right_version_id'),(p->>'right_version_id',p->>'left_version_id'));
  IF pair IS NULL OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(n.payload_json->'items') i WHERE i->'content'=leftc)
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(n.payload_json->'items') i WHERE i->'content'=rightc)
   OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(n.payload_json->'reports') r,jsonb_array_elements(r->'judgments') j
      WHERE j->>'binding_hash'=pair->>'binding_hash' AND j->>'conclusion' IN('conflict','uncertain')) THEN
   RAISE check_violation USING MESSAGE='527 exact failed pair actual content/role verdict required'; END IF;
 END IF;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.assert_private_native_relation_repair(jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_relation_repair_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.record_kind='private_status' AND NEW.payload_json->>'schema_version'='private_native_relation_repair_required_v1' THEN
  IF (NEW.pack_task_id::text,NEW.user_id::text,NEW.epoch::text,NEW.scope_id::text) IS DISTINCT FROM
    (NEW.payload_json->'ref'->>'pack_task_id',NEW.payload_json->'ref'->>'user_id',NEW.payload_json->'ref'->>'epoch',NEW.payload_json->'ref'->>'scope_id') THEN
   RAISE check_violation USING MESSAGE='527 relation repair journal coordinates changed'; END IF;
  PERFORM item_supply_internal.assert_private_native_relation_repair(NEW.payload_json);
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_relation_repair_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_relation_repair_insert ON tutor_item_supply_private_persistent_pack_journal;
CREATE TRIGGER a000_private_native_relation_repair_insert BEFORE INSERT ON tutor_item_supply_private_persistent_pack_journal
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_relation_repair_insert();

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_request_relation_repair(rid uuid,p jsonb) RETURNS void
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE t record;
BEGIN
 SELECT * INTO t FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->'ref'->>'pack_task_id')::uuid
  AND user_id=(p->'ref'->>'user_id')::uuid AND epoch=(p->'ref'->>'epoch')::integer AND scope_id=(p->'ref'->>'scope_id')::uuid AND record_kind='task';
 IF t.id IS NULL THEN RAISE check_violation USING MESSAGE='527 original same-task relation repair required'; END IF;
 PERFORM item_supply_internal.assert_private_native_relation_repair(p);
 INSERT INTO tutor_item_supply_private_persistent_pack_journal(id,pack_task_id,user_id,epoch,scope_id,record_kind,operation_key,intent_hash,payload_json)
 VALUES(rid,t.id,t.user_id,t.epoch,t.scope_id,'private_status','private.relation.repair.'||replace((p->>'parent_version_id'),'-',''),t.intent_hash,p);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_request_relation_repair(uuid,jsonb) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.private_native_relation_repair_current(rid uuid) RETURNS boolean
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_status'
  AND payload_json->>'schema_version'='private_native_relation_repair_required_v1';
 IF r.id IS NULL THEN RETURN false; END IF;
 PERFORM item_supply_internal.assert_private_native_relation_repair(r.payload_json);
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.private_native_relation_repair_current(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_repair_head_selection() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal r,jsonb_array_elements(NEW.payload_json->'snapshot'->'selected') s
  WHERE r.user_id=NEW.user_id AND r.epoch=NEW.epoch AND r.pack_task_id=NEW.pack_task_id AND r.record_kind='private_status'
   AND r.payload_json->>'schema_version'='private_native_relation_repair_required_v1' AND r.payload_json->>'parent_version_id'=s->>'version_id') THEN
  RAISE check_violation USING MESSAGE='527 failed relation head needs real same-slot substantive child'; END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_repair_head_selection() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_repair_head_selection ON tutor_item_supply_private_native_eligibility;
CREATE TRIGGER a000_private_native_repair_head_selection BEFORE INSERT ON tutor_item_supply_private_native_eligibility
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_repair_head_selection();

-- PRIVATE KC domain columns/FKs are established at the start of this fragment.

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_kc_response_insert() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE b record;r record;
BEGIN
 IF NEW.private_native_version_id IS NULL THEN RETURN NEW; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=NEW.artifact_id
  AND user_id=NEW.user_id AND epoch=NEW.private_native_epoch AND scope_id=NEW.private_native_scope_id AND version_id=NEW.private_native_version_id;
 IF b.artifact_id IS NULL OR NEW.learning_item_version_id IS NOT NULL THEN
  RAISE check_violation USING MESSAGE='527 PRIVATE KC response exact native Artifact binding required'; END IF;
 FOR r IN SELECT id FROM tutor_item_supply_private_native_consumer_receipts WHERE artifact_id=NEW.artifact_id AND user_id=NEW.user_id
  AND epoch=b.epoch AND scope_id=b.scope_id AND pack_task_id=b.pack_task_id AND version_id=b.version_id
  AND artifact_version=NEW.artifact_version AND mode='current' AND txid=txid_current()
  AND action=CASE WHEN NEW.response_kind='direct_answer' THEN 'request_direct_answer' ELSE 'respond' END LOOP
  IF item_supply_internal.private_native_consumer_current(r.id) THEN RETURN NEW; END IF;
 END LOOP;
 RAISE check_violation USING MESSAGE='527 PRIVATE KC response current exact action issuer required';
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_kc_response_insert() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_kc_response_insert ON tutor_knowledge_check_response_receipts;
CREATE TRIGGER a000_private_native_kc_response_insert BEFORE INSERT ON tutor_knowledge_check_response_receipts
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_kc_response_insert();

CREATE OR REPLACE FUNCTION item_supply_internal.purge_private_native_kc_on_epoch() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
 IF NEW.epoch IS DISTINCT FROM OLD.epoch THEN
  IF item_supply_internal.permitted(OLD.user_id) IS DISTINCT FROM true THEN
   RAISE check_violation USING MESSAGE='527 real maintenance owner required for PRIVATE KC purge'; END IF;
  DELETE FROM tutor_knowledge_check_response_receipts WHERE user_id=OLD.user_id AND private_native_epoch=OLD.epoch;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.purge_private_native_kc_on_epoch() FROM PUBLIC;
DROP TRIGGER IF EXISTS a0000_private_native_kc_epoch_purge ON tutor_item_supply_user_epochs;
CREATE TRIGGER a0000_private_native_kc_epoch_purge AFTER UPDATE OF epoch ON tutor_item_supply_user_epochs
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.purge_private_native_kc_on_epoch();

-- Exact180 legacy immutable body stays unchanged AFTER the isolated PRIVATE
-- branch. A private row cannot use the historical GUC deletion exception.
DO $upgrade_private_kc_immutable$
DECLARE f record;definition text;
BEGIN
 SELECT p.*,l.lanname,encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') AS body_hash INTO f
 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid='enforce_tutor_knowledge_check_receipt_immutable()'::regprocedure;
 IF f.lanname<>'plpgsql' OR f.prosecdef OR f.provolatile<>'v' OR f.proisstrict OR f.prokind<>'f'
  OR f.prorettype<>'trigger'::regtype OR f.proconfig IS NOT NULL THEN
  RAISE check_violation USING MESSAGE='527 original KC immutable receiver attributes changed'; END IF;
 IF f.body_hash='0b6a31ab799ccb0dfa0f6ecdae2247fb981fd9e8f0ec63cde8e259ba7dce3dcb' THEN RETURN; END IF;
 IF f.body_hash<>'6bcf34ad46dd3eb5a9cfd32b1b4eecaa8bcbc531085cea9b74abdbf598539e50' THEN RAISE check_violation USING MESSAGE='527 original KC immutable receiver fingerprint changed'; END IF;
 definition:=replace(pg_get_functiondef(f.oid),E'\r\n',E'\n');
 EXECUTE replace(definition,E'\nBEGIN\n',$private_frame$
BEGIN
  IF TG_TABLE_NAME='tutor_knowledge_check_response_receipts' AND (to_jsonb(OLD)->>'private_native_version_id') IS NOT NULL THEN
    IF TG_OP='DELETE' AND item_supply_internal.permitted(OLD.user_id)
      AND EXISTS(SELECT 1 FROM tutor_item_supply_user_epochs ep WHERE ep.user_id=OLD.user_id
        AND ep.epoch=(to_jsonb(OLD)->>'private_native_epoch')::bigint+1) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'PRIVATE KC receipts require original epoch maintenance owner' USING ERRCODE='23514';
  END IF;
$private_frame$);
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=f.oid AND encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex')='0b6a31ab799ccb0dfa0f6ecdae2247fb981fd9e8f0ec63cde8e259ba7dce3dcb') THEN
  RAISE check_violation USING MESSAGE='527 resulting KC immutable receiver fingerprint changed'; END IF;
END $upgrade_private_kc_immutable$;

CREATE OR REPLACE FUNCTION item_supply_internal.enforce_private_native_active_selection() RETURNS trigger
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE prior record;new_versions jsonb;old_versions jsonb;
BEGIN
 SELECT jsonb_agg(v ORDER BY v) INTO new_versions FROM jsonb_array_elements_text(NEW.payload_json->'versions') v;
 FOR prior IN SELECT DISTINCT reserved.payload_json FROM tutor_item_supply_private_native_artifact_bindings b
  JOIN tutor_learning_artifacts a ON a.id=b.artifact_id AND a.user_id=b.user_id
  JOIN tutor_item_supply_private_native_consumer_receipts cr ON cr.id=b.creation_receipt_id
  JOIN tutor_item_supply_private_native_assessment_reservations reserved ON reserved.id=cr.reservation_id
  WHERE b.user_id=NEW.user_id AND b.epoch=NEW.epoch AND b.pack_task_id=NEW.pack_task_id
   AND (a.state IN('pending','ready','active') OR a.active_attempt_id IS NOT NULL) LOOP
  SELECT jsonb_agg(v ORDER BY v) INTO old_versions FROM jsonb_array_elements_text(prior.payload_json->'versions') v;
  IF new_versions IS DISTINCT FROM old_versions THEN
   RAISE check_violation USING MESSAGE='527 active original PRIVATE consumer cannot replace its selected group'; END IF;
 END LOOP;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.enforce_private_native_active_selection() FROM PUBLIC;
DROP TRIGGER IF EXISTS a000_private_native_active_selection ON tutor_item_supply_private_native_assessment_reservations;
CREATE TRIGGER a000_private_native_active_selection BEFORE INSERT ON tutor_item_supply_private_native_assessment_reservations
 FOR EACH ROW EXECUTE FUNCTION item_supply_internal.enforce_private_native_active_selection();

DO $upgrade_private_native_request_matches$
DECLARE f record;definition text;
BEGIN
 SELECT p.*,l.lanname,encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex') AS body_hash INTO f
 FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid='item_supply_internal.private_native_request_matches(jsonb,uuid)'::regprocedure;
 IF f.lanname<>'plpgsql' OR NOT f.prosecdef OR f.provolatile<>'s' OR f.proisstrict OR f.prokind<>'f' OR f.prorettype<>'boolean'::regtype
  OR f.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
  RAISE check_violation USING MESSAGE='527 private_native_request_matches receiver attributes changed'; END IF;
 IF f.body_hash='cf8b0b579bf912914c4a1aeb854dcf6e7d5e4b90dba698b4d35fbbb93440afe6' THEN RETURN; END IF;
 IF f.body_hash<>'1cf6c288f5e2937996e176077dbb542051a6486b6abbce16a1dfefe36590d271' THEN RAISE check_violation USING MESSAGE='527 private_native_request_matches receiver fingerprint changed'; END IF;
 definition:=replace(pg_get_functiondef(f.oid),E'\r\n',E'\n');
 IF position($old0$ IF v IS NULL OR v->>'kind'<>'knowledge_check' OR v->>'purpose'<>'knowledge_check' THEN RETURN false; END IF;$old0$ IN definition)=0 THEN RAISE check_violation USING MESSAGE='527 exact private_native_request_matches frame absent'; END IF;
 definition:=replace(definition,$old0$ IF v IS NULL OR v->>'kind'<>'knowledge_check' OR v->>'purpose'<>'knowledge_check' THEN RETURN false; END IF;$old0$,$new0$ IF v IS NULL OR v->>'kind'<>'knowledge_check' OR (v->>'purpose' IS DISTINCT FROM 'knowledge_check' AND NOT (v->>'purpose'='remediation' AND q->>'purpose'='remediation')) THEN RETURN false; END IF;$new0$);
 IF position($old1$ (v->>'title',v->>'instruction_markdown',v->>'difficulty','knowledge_check','knowledge_check','true')$old1$ IN definition)=0 THEN RAISE check_violation USING MESSAGE='527 exact private_native_request_matches frame absent'; END IF;
 definition:=replace(definition,$old1$ (v->>'title',v->>'instruction_markdown',v->>'difficulty','knowledge_check','knowledge_check','true')$old1$,$new1$ (v->>'title',v->>'instruction_markdown',v->>'difficulty',CASE WHEN q->>'purpose' IN('remediation','transfer_check') AND EXISTS(SELECT 1 FROM tutor_item_supply_private_native_consumer_receipts r WHERE r.mode='create' AND r.txid=txid_current() AND r.run_id::text=q->>'turn_id' AND r.payload_json->'request'=q AND r.payload_json->>'parent_artifact_id' IS NOT NULL) THEN q->>'purpose' ELSE 'knowledge_check' END,'knowledge_check','true')$new1$);
 EXECUTE definition;
 IF NOT EXISTS(SELECT 1 FROM pg_proc WHERE oid=f.oid AND encode(sha256(convert_to(replace(prosrc,E'\r\n',E'\n'),'UTF8')),'hex')='cf8b0b579bf912914c4a1aeb854dcf6e7d5e4b90dba698b4d35fbbb93440afe6') THEN
  RAISE check_violation USING MESSAGE='527 private_native_request_matches resulting receiver fingerprint changed'; END IF;
END $upgrade_private_native_request_matches$;











