-- C24: known initial-generation inheritance for four approved PRIVATE fixed slots only.
-- Frozen <=566 untouched. One exact prosrc patch; no new objects/ABI/readiness patches.
-- Historical committed output is DATA, not author/review dispatch permission or a renewed old lease.
DO $patch567$
DECLARE actual record; verified record; definition text;
 old_body constant text := $old567$
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
END $old567$;
 new_body constant text := $new567$
DECLARE ref jsonb:=p->'ref';lease jsonb:=p->'lease';ph record;old_phase record;g record;control record;
 data jsonb; preparation uuid; output_row public.tutor_item_supply_private_persistent_pack_journal%ROWTYPE;
BEGIN
 IF item_supply_internal.snapshot_keys(p,ARRAY['ref','lease','artifact_id']) IS DISTINCT FROM true THEN
  RAISE check_violation USING MESSAGE='527 exact inherited PRIVATE generation coordinates required'; END IF;
 SELECT * INTO ph FROM tutor_item_supply_private_persistent_pack_journal WHERE record_kind='phase'
  AND pack_task_id=(ref->>'pack_task_id')::uuid AND user_id=(ref->>'user_id')::uuid AND epoch=(ref->>'epoch')::integer
  AND scope_id=(ref->>'scope_id')::uuid AND payload_json->>'job_id'=lease->>'job_id'
  AND payload_json->>'schema_version'='private_native_phase_v1' AND payload_json->'ref'=ref;
 IF ph.id IS NULL OR ((ph.payload_json->'lease') - 'state_version'::text) IS DISTINCT FROM (lease - 'state_version'::text) THEN
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
  OR g.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider' THEN
  RAISE check_violation USING MESSAGE='527 actual same fixed-slot historical generation/settlement required'; END IF;
 IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_runtime_settlements s
   JOIN tutor_item_supply_private_reservations r ON r.id=s.reservation_id AND r.user_id=s.user_id AND r.epoch=s.epoch
   WHERE r.job_id=g.job_id AND r.root_id=(ref->>'root_id')::uuid AND r.user_id=ph.user_id AND r.epoch=ph.epoch
    AND r.scope_id=ph.scope_id AND s.usage_state='unknown' AND s.xmin::text::bigint<>(txid_current()%4294967296)) THEN
  -- Only these four declared initial slots gain a historical known-output proof.
  -- Legacy UNKNOWN proof above, current phase/source fences and C22 remain unchanged.
  IF (ph.pack_task_id,ph.user_id,ph.epoch,ph.scope_id,ref->>'root_id',ref->>'mapping_receipt_id') IS DISTINCT FROM
   ('6739d3c5-6619-44ce-970f-0ab1e49f3acc'::uuid,'a65237a6-82d3-42ad-b4bb-a9e2f4d907fe'::uuid,1::bigint,
    'cef6af15-84c0-466a-b330-3dc3235aa587'::uuid,'aaaf99e5-4530-4319-bb1a-0fe6d84020f9','d8e34e01-3514-41a3-9bbd-55ee3e627134')
   OR ref->'parent_version_id' IS DISTINCT FROM 'null'::jsonb OR g.request_json->>'version' IS DISTINCT FROM 'v1'
   OR NOT EXISTS(SELECT 1 FROM (VALUES
    ('50df2afa-158c-586e-83c7-60bb99ea4307','2e1251b9-efd2-5624-930f-174f726c35ea'),
    ('6789a8fc-2139-5f0b-8958-f5375b906053','d112ecff-7ba2-5b50-ac59-4663c55c221f'),
    ('da9dd580-db9b-5f23-a53b-090d08bbf96a','da88ec68-27ee-5d24-9609-0adb69e236d1'),
    ('64c6228a-80b4-5ad4-99c0-94cfeefb33c0','16fede98-38e4-5174-8c7a-680ee5511a4c')) allowed(slot_id,business_item_id)
    WHERE allowed.slot_id=ref->>'slot_id' AND allowed.business_item_id=ref->>'business_item_id') THEN
   RAISE check_violation USING MESSAGE='527 actual same fixed-slot historical generation/settlement required'; END IF;
  preparation:=(g.request_json->>'candidate_id')::uuid;
  data:=item_supply_internal.private_generation_durability_attempt(preparation);
  SELECT out_j.* INTO output_row FROM tutor_item_supply_private_persistent_pack_journal out_j
   WHERE out_j.pack_task_id=ph.pack_task_id AND out_j.user_id=ph.user_id AND out_j.epoch=ph.epoch AND out_j.scope_id=ph.scope_id
    AND out_j.record_kind='private_status' AND out_j.operation_key='private.generation.output.'||replace(preparation::text,'-','');
  IF output_row.id IS NULL OR data->'settlement'->>'usage_state' IS DISTINCT FROM 'known'
   OR data->'settlement'->>'receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(g.receipt_json->'provider')
   OR data->'control'->>'job_id' IS DISTINCT FROM g.job_id::text OR data->'phase'->>'id' IS DISTINCT FROM old_phase.id::text
   OR data->'aux'->'payload_json'->'request'->'ref' IS DISTINCT FROM ref
   OR data->'aux'->'payload_json'->'request'->'request' IS DISTINCT FROM g.request_json
   OR output_row.payload_json->'capture'->'context'->'ref' IS DISTINCT FROM ref
   OR output_row.payload_json->'capture'->'context'->'request' IS DISTINCT FROM g.request_json
   OR output_row.payload_json->'capture'->'context'->'lease' IS DISTINCT FROM old_phase.payload_json->'lease'
   OR output_row.payload_json->'capture'->'context'->'lease'->>'job_id' IS DISTINCT FROM g.job_id::text
   OR output_row.payload_json->'capture'->'context'->'lease'->>'generation' IS DISTINCT FROM g.lease_generation::text
   OR output_row.payload_json->'capture'->'context'->'lease'->>'state_version' IS DISTINCT FROM g.lease_state_version::text
   OR output_row.payload_json->'capture'->'result'->'source' IS DISTINCT FROM g.source_json
   OR output_row.payload_json->'capture'->'result'->'receipt' IS DISTINCT FROM g.receipt_json THEN
   RAISE check_violation USING MESSAGE='567 exact committed known initial generation output required'; END IF;
  -- Uses the original complete immutable capture protocol and full TOP commit fence.
  IF item_supply_internal.private_generation_output_committed(preparation,output_row.payload_json->'capture') IS DISTINCT FROM output_row.id THEN
   RAISE check_violation USING MESSAGE='567 exact committed known initial generation output required'; END IF;
 END IF;
 PERFORM 1 FROM tutor_item_supply_private_versions WHERE id=g.version_id AND user_id=ph.user_id AND epoch=ph.epoch
  AND scope_id=ph.scope_id AND public_json=g.source_json->'public' AND private_json=g.source_json->'private' FOR SHARE;
 IF NOT FOUND OR item_supply_internal.private_native_source_current(jsonb_build_object('ref',ref,'request',g.request_json,
  'source_receipts',g.receipt_json->'sources')) IS DISTINCT FROM true OR clock_timestamp()>=(ph.payload_json->>'valid_until')::timestamptz THEN
  RAISE check_violation USING MESSAGE='527 inherited generation changed after wait'; END IF;
 RETURN g.artifact_hash;
END $new567$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='567 original isolated writable transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_native_inherit_generation(jsonb)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_native_inherit_generation' OR actual.prokind<>'f'
  OR actual.prolang<>(SELECT oid FROM pg_catalog.pg_language WHERE lanname='plpgsql')
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.text'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM '3802'::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['p']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='567 original generation inheritance identity/attributes changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM new_body THEN RETURN; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body
 THEN RAISE check_violation USING MESSAGE='567 original generation inheritance body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
 THEN RAISE check_violation USING MESSAGE='567 original generation inheritance definition framing changed'; END IF;
 EXECUTE replace(definition,old_body,new_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='567 generation inheritance metadata/OID/owner/ACL or body changed'; END IF;
END;
$patch567$;
