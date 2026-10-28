-- PRIVATE production-v2 relation receiver: one exact existing-function prosrc patch.
-- Frozen <=574; no new objects, business writes, grants, replay or authority recovery.
DO $patch575$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old575$
DECLARE p jsonb;aux record;reserve record;settled record;request jsonb;report jsonb;pair jsonb;item jsonb;leftc jsonb;rightc jsonb;contents jsonb;bh text;
BEGIN
 p:=n.payload_json;
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'preparation_id')::uuid AND pack_task_id=n.pack_task_id
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND record_kind='private_attachment'
  AND payload_json->>'schema_version'='private_native_auxiliary_v1' AND xmin::text::bigint<>(txid_current()%4294967296);
 request:=aux.payload_json->'request';
 SELECT * INTO reserve FROM tutor_item_supply_private_reservations WHERE id=(p->>'reservation_id')::uuid AND user_id=n.user_id AND epoch=n.epoch
  AND scope_id=n.scope_id AND root_id=n.root_id AND job_id=n.job_id AND lease_generation=(p->'lease'->>'generation')::integer;
 SELECT * INTO settled FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=reserve.id AND user_id=n.user_id AND epoch=n.epoch
  AND settlement_key='private.relation.'||replace(aux.id::text,'-','') AND usage_state='unknown' AND xmin::text::bigint<>(txid_current()%4294967296);
 IF aux.id IS NULL OR reserve.id IS NULL OR settled.id IS NULL OR reserve.requests<>4
  OR request->>'schema_version' IS DISTINCT FROM 'private_native_relation_phase_v1'
  OR request->'ref' IS DISTINCT FROM p->'ref' OR request->'lease' IS DISTINCT FROM p->'lease'
  OR request->'payload' IS DISTINCT FROM (p-ARRAY['schema_version','reports','preparation_id','reservation_id','ref','lease'])||jsonb_build_object('schema_version','private_native_relation_preparation_v1')
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_relation_v1'
  OR jsonb_typeof(p->'reports') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'reports')<>4
  OR jsonb_typeof(p->'pairs') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'pairs') NOT BETWEEN 1 AND 120
  OR jsonb_typeof(p->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'items') NOT BETWEEN 2 AND 16
  OR (SELECT count(DISTINCT r->>'actor_id') FROM jsonb_array_elements(p->'reports') r)<>4
  OR (SELECT count(DISTINCT r->'run'->>'run_id') FROM jsonb_array_elements(p->'reports') r)<>4
  OR (SELECT array_agg(r->>'role' ORDER BY r->>'role') FROM jsonb_array_elements(p->'reports') r) IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','technical']::text[] THEN
  RAISE check_violation USING MESSAGE='524 relation needs committed original four-call preparation/settlement'; END IF;
 FOR pair IN SELECT value FROM jsonb_array_elements(p->'pairs') LOOP
  SELECT value->'content' INTO leftc FROM jsonb_array_elements(p->'items') WHERE value->>'version_id'=pair->>'left_version_id';
  SELECT value->'content' INTO rightc FROM jsonb_array_elements(p->'items') WHERE value->>'version_id'=pair->>'right_version_id';
  SELECT jsonb_agg(v ORDER BY item_supply_internal.snapshot_hash(v)) INTO contents FROM (VALUES(leftc),(rightc)) c(v);
  bh:=item_supply_internal.snapshot_hash(jsonb_build_object('policy_version','item_supply_type_evidence_v2','profile','kc','request_hash',p->>'request_hash','contents',contents));
  IF leftc IS NULL OR rightc IS NULL OR leftc->>'version_id'=rightc->>'version_id' OR pair->>'binding_hash' IS DISTINCT FROM bh THEN
   RAISE check_violation USING MESSAGE='524 relation exact actual pair binding required'; END IF;
 END LOOP;
 FOR report IN SELECT value FROM jsonb_array_elements(p->'reports') LOOP
  IF report->>'actor_id' IS DISTINCT FROM item_supply_internal.native_type_actor(report->'run'->'provider_identity'->>'identity')::text
   OR report->'run'->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
   OR report->'run'->>'prompt_version' IS DISTINCT FROM 'native-content-relation-v1'
   OR (report->'run'->>'max_output_tokens')::integer<>61440
   OR (report->'run'->>'timeout_seconds')::numeric*1000>(p->'lease'->'profile'->'values'->>'request_timeout_ms')::numeric
   OR (report->>'checked_at')::timestamptz>(aux.payload_json->>'valid_until')::timestamptz
   OR (report->>'valid_until')::timestamptz<>n.valid_until
   OR jsonb_array_length(report->'judgments')<>jsonb_array_length(p->'pairs')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'items') i WHERE i->'content'->>'author_id'=report->>'actor_id') THEN
   RAISE check_violation USING MESSAGE='524 relation original independent role/profile interval required'; END IF;
  FOR pair IN SELECT value FROM jsonb_array_elements(p->'pairs') LOOP
   IF (SELECT count(*) FROM jsonb_array_elements(report->'judgments') j WHERE j->>'binding_hash'=pair->>'binding_hash' AND j->>'conclusion' IN('nonredundant','uncertain','conflict'))<>1 THEN
    RAISE check_violation USING MESSAGE='524 relation every actual pair needs four-role judgment'; END IF;
  END LOOP;
 END LOOP;
END $old575$;

new_body constant text := $new575$
DECLARE p jsonb;aux record;reserve record;settled record;request jsonb;report jsonb;pair jsonb;item jsonb;leftc jsonb;rightc jsonb;contents jsonb;bh text;
BEGIN
 p:=n.payload_json;
 SELECT * INTO aux FROM tutor_item_supply_private_persistent_pack_journal WHERE id=(p->>'preparation_id')::uuid AND pack_task_id=n.pack_task_id
  AND user_id=n.user_id AND epoch=n.epoch AND scope_id=n.scope_id AND record_kind='private_attachment'
  AND payload_json->>'schema_version'='private_native_auxiliary_v1' AND xmin::text::bigint<>(txid_current()%4294967296);
 request:=aux.payload_json->'request';
 SELECT * INTO reserve FROM tutor_item_supply_private_reservations WHERE id=(p->>'reservation_id')::uuid AND user_id=n.user_id AND epoch=n.epoch
  AND scope_id=n.scope_id AND root_id=n.root_id AND job_id=n.job_id AND lease_generation=(p->'lease'->>'generation')::integer;
 SELECT * INTO settled FROM tutor_item_supply_private_runtime_settlements WHERE reservation_id=reserve.id AND user_id=n.user_id AND epoch=n.epoch
  AND settlement_key='private.relation.'||replace(aux.id::text,'-','') AND usage_state='unknown' AND xmin::text::bigint<>(txid_current()%4294967296);
 IF aux.id IS NULL OR reserve.id IS NULL OR settled.id IS NULL OR reserve.requests<>4
  OR request->>'schema_version' IS DISTINCT FROM 'private_native_relation_phase_v1'
  OR request->'ref' IS DISTINCT FROM p->'ref' OR request->'lease' IS DISTINCT FROM p->'lease'
  OR request->'payload' IS DISTINCT FROM (p-ARRAY['schema_version','reports','preparation_id','reservation_id','ref','lease'])||jsonb_build_object('schema_version','private_native_relation_preparation_v1')
  OR p->>'schema_version' IS DISTINCT FROM 'private_native_relation_v1'
  OR jsonb_typeof(p->'reports') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'reports')<>4
  OR jsonb_typeof(p->'pairs') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'pairs') NOT BETWEEN 1 AND 120
  OR jsonb_typeof(p->'items') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'items') NOT BETWEEN 2 AND 16
  OR (SELECT count(DISTINCT r->>'actor_id') FROM jsonb_array_elements(p->'reports') r)<>4
  OR (SELECT count(DISTINCT r->'run'->>'run_id') FROM jsonb_array_elements(p->'reports') r)<>4
  OR (SELECT array_agg(r->>'role' ORDER BY r->>'role') FROM jsonb_array_elements(p->'reports') r) IS DISTINCT FROM ARRAY['adversarial','ambiguity','curriculum','technical']::text[] THEN
  RAISE check_violation USING MESSAGE='524 relation needs committed original four-call preparation/settlement'; END IF;
 FOR pair IN SELECT value FROM jsonb_array_elements(p->'pairs') LOOP
  SELECT value->'content' INTO leftc FROM jsonb_array_elements(p->'items') WHERE value->>'version_id'=pair->>'left_version_id';
  SELECT value->'content' INTO rightc FROM jsonb_array_elements(p->'items') WHERE value->>'version_id'=pair->>'right_version_id';
  SELECT jsonb_agg(v ORDER BY item_supply_internal.snapshot_hash(v)) INTO contents FROM (VALUES(leftc),(rightc)) c(v);
  bh:=item_supply_internal.snapshot_hash(jsonb_build_object('policy_version','item_supply_type_evidence_v2','profile','kc','request_hash',p->>'request_hash','contents',contents));
  IF leftc IS NULL OR rightc IS NULL OR leftc->>'version_id'=rightc->>'version_id' OR pair->>'binding_hash' IS DISTINCT FROM bh THEN
   RAISE check_violation USING MESSAGE='524 relation exact actual pair binding required'; END IF;
 END LOOP;
 FOR report IN SELECT value FROM jsonb_array_elements(p->'reports') LOOP
  IF report->>'actor_id' IS DISTINCT FROM item_supply_internal.native_type_actor(report->'run'->'provider_identity'->>'identity')::text
   OR report->'run'->>'profile_hash' IS DISTINCT FROM p->'lease'->'profile'->>'profile_hash'
   OR report->'run'->>'prompt_version' IS DISTINCT FROM 'native-content-relation-production-v2'
   OR (report->'run'->>'max_output_tokens')::integer<>61440
   OR (report->'run'->>'timeout_seconds')::numeric*1000>(p->'lease'->'profile'->'values'->>'request_timeout_ms')::numeric
   OR (report->>'checked_at')::timestamptz>(aux.payload_json->>'valid_until')::timestamptz
   OR (report->>'valid_until')::timestamptz<>n.valid_until
   OR jsonb_array_length(report->'judgments')<>jsonb_array_length(p->'pairs')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(p->'items') i WHERE i->'content'->>'author_id'=report->>'actor_id') THEN
   RAISE check_violation USING MESSAGE='524 relation original independent role/profile interval required'; END IF;
  FOR pair IN SELECT value FROM jsonb_array_elements(p->'pairs') LOOP
   IF (SELECT count(*) FROM jsonb_array_elements(report->'judgments') j WHERE j->>'binding_hash'=pair->>'binding_hash' AND j->>'conclusion' IN('nonredundant','uncertain','conflict'))<>1 THEN
    RAISE check_violation USING MESSAGE='524 relation every actual pair needs four-role judgment'; END IF;
  END LOOP;
 END LOOP;
END $new575$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001' THEN
  RAISE check_violation USING MESSAGE='575 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.assert_private_native_relation(tutor_item_supply_private_native_quality_evidence)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'assert_private_native_relation' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM ('public.tutor_item_supply_private_native_quality_evidence'::regtype::oid::text)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['n']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[]
 THEN RAISE check_violation USING MESSAGE='575 original relation receiver identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='575 original relation receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='575 original relation receiver definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='575 relation receiver metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch575$;
