-- C10: new current-pack observations have a 120-second upper bound.
-- Selected-forward only: predecessor is the exact final554 union body below.
-- Old rows/deadlines, all source/current gates, and independent529/521/PRIVATE
-- consumer/creator/publication/lease windows remain unchanged.
-- The isolated caller owns the transaction. No business data write or commit.
DO $ttl556$
DECLARE
 actual record; verified record; target record; original_check record; final_check record;
 checked_column record; until_column record; saved jsonb;
 table_id oid; bound_columns smallint[]; matches bigint; check_definition text; definition text;
 before_checks jsonb := '[]'::jsonb;
 old_check constant text := $oldcheck556$CHECK (((valid_until > checked_at) AND (valid_until <= (checked_at + '00:00:30'::interval))))$oldcheck556$;
 new_check constant text := $newcheck556$CHECK (((valid_until > checked_at) AND (valid_until <= (checked_at + '00:02:00'::interval))))$newcheck556$;
 old_body constant text := $old556$

DECLARE r record;el record;m jsonb;ex jsonb;p jsonb;s jsonb;c jsonb;other jsonb;original jsonb;proof record;t timestamptz;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_status';
 IF NOT FOUND THEN RETURN false; END IF;
 p:=r.payload_json;s:=p->'snapshot';
 IF COALESCE(p->>'schema_version' IN('private_native_base_union_v1','private_native_base_union_current_source_v2'),false) IS DISTINCT FROM true OR (p->>'txid')::bigint<>txid_current() THEN RETURN false; END IF;
 IF p->>'schema_version'='private_native_base_union_current_source_v2' THEN
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_eligibility_id','exposure_snapshot_id','snapshot','relations','checked_at','valid_until','txid','source_mode','current_source_origin_id']) IS DISTINCT FROM true
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(p->>'current_source_origin_id')::uuid
    AND j.pack_task_id=r.pack_task_id AND j.user_id=r.user_id AND j.epoch=r.epoch AND j.scope_id=r.scope_id AND j.record_kind='current_pack_source_origin') THEN RETURN false; END IF;
 ELSIF p ? 'source_mode' OR p ? 'current_source_origin_id' THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(r.user_id,r.epoch::bigint);
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid AND user_id=r.user_id AND epoch=r.epoch AND txid=txid_current();
 IF NOT FOUND THEN RETURN false; END IF;
 m:=item_supply_internal.private_native_mapping_current(el.mapping_receipt_id,r.user_id,r.epoch::bigint);
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);
 IF m IS NULL OR ex IS NULL OR s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_array_length(s->'selected')<>5 OR jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations')>16
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='remediation')<>1
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal task WHERE task.id=r.pack_task_id AND task.record_kind='task'
   AND task.user_id=r.user_id AND task.epoch=r.epoch AND task.scope_id=r.scope_id AND task.payload_json->'ref'->>'mapping_receipt_id'=el.mapping_receipt_id::text) THEN RETURN false; END IF;
 IF p->>'schema_version'='private_native_base_union_current_source_v2' THEN
  IF (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM jsonb_array_elements(s->'selected') x)
   IS DISTINCT FROM (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM tutor_item_supply_private_persistent_pack_journal j,
    LATERAL jsonb_array_elements(j.payload_json->'selected') x WHERE j.id=(p->>'current_source_origin_id')::uuid AND j.record_kind='current_pack_source_origin') THEN RETURN false; END IF;
 END IF;
 -- Complete source set FIRST, before any of the PUBLIC version bank locks.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  SELECT value INTO original FROM jsonb_array_elements(el.snapshot_json->'selected') WHERE value->>'version_id'=c->>'version_id';
  SELECT n.*,pe.state,pe.id AS peid INTO proof FROM tutor_learning_item_native_publication_proofs n
   JOIN tutor_learning_item_versions v ON v.id=n.version_id
   JOIN LATERAL(SELECT id,state,occurred_at FROM tutor_learning_item_publication_events WHERE version_id=v.id ORDER BY state_version DESC LIMIT 1) pe ON true
   WHERE n.id=(c->>'proof_id')::uuid AND n.version_id=(c->>'version_id')::uuid AND n.publication_event_id=pe.id AND pe.state='published'
    AND pe.occurred_at>=(n.proof_json->>'checked_at')::timestamptz AND pe.occurred_at<(n.proof_json->>'valid_until')::timestamptz FOR SHARE OF v;
  IF proof.id IS NULL OR original IS NULL OR (c->>'publication_id',c->>'materialization_id',c->>'proof_id',c->'type_evidence'->'content')
    IS DISTINCT FROM (original->>'publication_id',original->>'materialization_id',original->>'proof_id',original->'type_evidence'->'content')
   OR c->'owner_id' IS DISTINCT FROM 'null'::jsonb OR c->'epoch' IS DISTINCT FROM 'null'::jsonb OR c->'candidate'->>'visibility' IS DISTINCT FROM 'public'
   OR c->'candidate'->'scope' IS DISTINCT FROM original->'candidate'->'scope' OR c->'member' IS DISTINCT FROM original->'member' THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other) THEN RETURN false; END IF;
   -- Original501/502 already covers PUBLIC ledger pairs. Additional PRIVATE
   -- exposure requires a genuine PRIVATE four-role batch for THIS actual pair.
   IF other->>'item_handle' LIKE 'lip:v2:%' AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,r.user_id,r.epoch::bigint,r.pack_task_id) IS DISTINCT FROM true THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND (p->>'checked_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz
  AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '30 seconds';
END 
$old556$;
 new_body constant text := $new556$

DECLARE r record;el record;m jsonb;ex jsonb;p jsonb;s jsonb;c jsonb;other jsonb;original jsonb;proof record;t timestamptz;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_persistent_pack_journal WHERE id=rid AND record_kind='private_status';
 IF NOT FOUND THEN RETURN false; END IF;
 p:=r.payload_json;s:=p->'snapshot';
 IF COALESCE(p->>'schema_version' IN('private_native_base_union_v1','private_native_base_union_current_source_v2'),false) IS DISTINCT FROM true OR (p->>'txid')::bigint<>txid_current() THEN RETURN false; END IF;
 IF p->>'schema_version'='private_native_base_union_current_source_v2' THEN
  IF item_supply_internal.snapshot_keys(p,ARRAY['schema_version','public_eligibility_id','exposure_snapshot_id','snapshot','relations','checked_at','valid_until','txid','source_mode','current_source_origin_id']) IS DISTINCT FROM true
   OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal j WHERE j.id=(p->>'current_source_origin_id')::uuid
    AND j.pack_task_id=r.pack_task_id AND j.user_id=r.user_id AND j.epoch=r.epoch AND j.scope_id=r.scope_id AND j.record_kind='current_pack_source_origin') THEN RETURN false; END IF;
 ELSIF p ? 'source_mode' OR p ? 'current_source_origin_id' THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(r.user_id,r.epoch::bigint);
 SELECT * INTO el FROM tutor_item_supply_native_eligibility WHERE id=(p->>'public_eligibility_id')::uuid AND user_id=r.user_id AND epoch=r.epoch AND txid=txid_current();
 IF NOT FOUND THEN RETURN false; END IF;
 m:=item_supply_internal.private_native_mapping_current(el.mapping_receipt_id,r.user_id,r.epoch::bigint);
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);
 IF m IS NULL OR ex IS NULL OR s->>'schema_version' IS DISTINCT FROM 'pack_snapshot_v2' OR s->'request' IS DISTINCT FROM m->'pack_request'
  OR s->>'exposure_receipt_hash' IS DISTINCT FROM ex->>'completeness_receipt_hash' OR s->>'exposure_watermark' IS DISTINCT FROM ex->>'watermark'
  OR jsonb_array_length(s->'selected')<>5 OR jsonb_typeof(p->'relations') IS DISTINCT FROM 'array' OR jsonb_array_length(p->'relations')>16
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='practice')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='assessment')<>2
  OR (SELECT count(*) FROM jsonb_array_elements(s->'selected') selected_member WHERE selected_member->'member'->>'slot'='remediation')<>1
  OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_persistent_pack_journal task WHERE task.id=r.pack_task_id AND task.record_kind='task'
   AND task.user_id=r.user_id AND task.epoch=r.epoch AND task.scope_id=r.scope_id AND task.payload_json->'ref'->>'mapping_receipt_id'=el.mapping_receipt_id::text) THEN RETURN false; END IF;
 IF p->>'schema_version'='private_native_base_union_current_source_v2' THEN
  IF (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM jsonb_array_elements(s->'selected') x)
   IS DISTINCT FROM (SELECT jsonb_agg(x->>'version_id' ORDER BY x->>'version_id') FROM tutor_item_supply_private_persistent_pack_journal j,
    LATERAL jsonb_array_elements(j.payload_json->'selected') x WHERE j.id=(p->>'current_source_origin_id')::uuid AND j.record_kind='current_pack_source_origin') THEN RETURN false; END IF;
 END IF;
 -- Complete source set FIRST, before any of the PUBLIC version bank locks.
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') ORDER BY value->>'version_id' LOOP
  SELECT value INTO original FROM jsonb_array_elements(el.snapshot_json->'selected') WHERE value->>'version_id'=c->>'version_id';
  SELECT n.*,pe.state,pe.id AS peid INTO proof FROM tutor_learning_item_native_publication_proofs n
   JOIN tutor_learning_item_versions v ON v.id=n.version_id
   JOIN LATERAL(SELECT id,state,occurred_at FROM tutor_learning_item_publication_events WHERE version_id=v.id ORDER BY state_version DESC LIMIT 1) pe ON true
   WHERE n.id=(c->>'proof_id')::uuid AND n.version_id=(c->>'version_id')::uuid AND n.publication_event_id=pe.id AND pe.state='published'
    AND pe.occurred_at>=(n.proof_json->>'checked_at')::timestamptz AND pe.occurred_at<(n.proof_json->>'valid_until')::timestamptz FOR SHARE OF v;
  IF proof.id IS NULL OR original IS NULL OR (c->>'publication_id',c->>'materialization_id',c->>'proof_id',c->'type_evidence'->'content')
    IS DISTINCT FROM (original->>'publication_id',original->>'materialization_id',original->>'proof_id',original->'type_evidence'->'content')
   OR c->'owner_id' IS DISTINCT FROM 'null'::jsonb OR c->'epoch' IS DISTINCT FROM 'null'::jsonb OR c->'candidate'->>'visibility' IS DISTINCT FROM 'public'
   OR c->'candidate'->'scope' IS DISTINCT FROM original->'candidate'->'scope' OR c->'member' IS DISTINCT FROM original->'member' THEN RETURN false; END IF;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') WHERE value->'member'->>'slot'='assessment' LOOP
  FOR other IN SELECT value->'content' FROM jsonb_array_elements(ex->'records') LOOP
   IF item_supply_internal.private_native_clone(c->'type_evidence'->'content',other) THEN RETURN false; END IF;
   -- Original501/502 already covers PUBLIC ledger pairs. Additional PRIVATE
   -- exposure requires a genuine PRIVATE four-role batch for THIS actual pair.
   IF other->>'item_handle' LIKE 'lip:v2:%' AND item_supply_internal.private_native_relation_current(p->'relations',m,c->'type_evidence'->'content',other,r.user_id,r.epoch::bigint,r.pack_task_id) IS DISTINCT FROM true THEN RETURN false; END IF;
  END LOOP;
 END LOOP;
 FOR c IN SELECT value FROM jsonb_array_elements(s->'selected') LOOP
  IF item_supply_internal.native_consumer_source_context_current((c->>'proof_id')::uuid,p,r.user_id,r.epoch::bigint,el.mapping_receipt_id) IS DISTINCT FROM true THEN RETURN false; END IF;
 END LOOP;
 ex:=item_supply_internal.private_native_exposure_current((p->>'exposure_snapshot_id')::uuid,r.user_id,r.epoch::bigint);t:=clock_timestamp();
 RETURN ex IS NOT NULL AND el.checked_at<=t AND t<el.valid_until AND (p->>'checked_at')::timestamptz<=t AND t<(p->>'valid_until')::timestamptz
  AND (p->>'valid_until')::timestamptz<=(p->>'checked_at')::timestamptz+interval '120 seconds';
END 
$new556$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off'
 THEN RAISE check_violation USING MESSAGE='556 original isolated writable transaction required'; END IF;
 -- Stabilize only the two intended ALTER targets before all-object preflight.
 LOCK TABLE public.tutor_item_supply_type_exposure_snapshots,
  public.tutor_item_supply_private_native_exposure_snapshots IN ACCESS EXCLUSIVE MODE;

 SELECT p.*,l.lanname INTO actual FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang
 WHERE p.oid=pg_catalog.to_regprocedure('item_supply_internal.private_native_base_union_current(uuid)');
 IF NOT FOUND OR actual.pronamespace IS DISTINCT FROM 'item_supply_internal'::regnamespace
  OR actual.proname IS DISTINCT FROM 'private_native_base_union_current'
  OR actual.lanname IS DISTINCT FROM 'plpgsql' OR actual.prokind<>'f'
  OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
  OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR actual.pronargs<>1 OR actual.proargtypes IS DISTINCT FROM
   pg_catalog.format('%s','pg_catalog.uuid'::regtype::oid)::oidvector
  OR actual.proargnames IS DISTINCT FROM ARRAY['rid']
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0
  OR actual.pronargdefaults<>0 OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL
  OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='556 original base-union receiver identity/attributes changed'; END IF;
 -- Retain the actual owner and full ACL, never grant PUBLIC execution.
 IF EXISTS(SELECT 1 FROM pg_catalog.aclexplode(COALESCE(actual.proacl,
       pg_catalog.acldefault('f',actual.proowner))) AS privilege
     WHERE privilege.grantee=0 AND privilege.privilege_type='EXECUTE')
 THEN RAISE check_violation USING MESSAGE='556 original base-union receiver PUBLIC privilege changed'; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body AND actual.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='556 original base-union receiver body changed'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM old_body THEN
  definition:=pg_catalog.pg_get_functiondef(actual.oid);
  IF length(definition)-length(replace(definition,old_body,''))<>length(old_body)
  THEN RAISE check_violation USING MESSAGE='556 original base-union receiver definition framing changed'; END IF;
 END IF;

 FOR target IN SELECT * FROM (VALUES
   ('tutor_item_supply_type_exposure_snapshots',
    'tutor_item_supply_type_exposure_snapshots_check','type_exposure_ttl120_check'),
   ('tutor_item_supply_private_native_exposure_snapshots',
    'tutor_item_supply_private_native_exposure_snapshots_check','private_native_exposure_ttl120_check')
  ) AS targets(table_name,old_name,new_name)
 LOOP
  table_id:=pg_catalog.to_regclass(format('public.%I',target.table_name));
  SELECT a.* INTO checked_column FROM pg_catalog.pg_attribute a
   WHERE a.attrelid=table_id AND a.attname='checked_at' AND a.attnum>0 AND NOT a.attisdropped;
  IF NOT FOUND OR checked_column.atttypid IS DISTINCT FROM 'pg_catalog.timestamptz'::regtype OR NOT checked_column.attnotnull
  THEN RAISE check_violation USING MESSAGE='556 original checked_at column identity changed'; END IF;
  SELECT a.* INTO until_column FROM pg_catalog.pg_attribute a
   WHERE a.attrelid=table_id AND a.attname='valid_until' AND a.attnum>0 AND NOT a.attisdropped;
  IF NOT FOUND OR until_column.atttypid IS DISTINCT FROM 'pg_catalog.timestamptz'::regtype OR NOT until_column.attnotnull
  THEN RAISE check_violation USING MESSAGE='556 original valid_until column identity changed'; END IF;
  bound_columns:=ARRAY[LEAST(checked_column.attnum,until_column.attnum),
   GREATEST(checked_column.attnum,until_column.attnum)]::smallint[];
  SELECT count(*) INTO matches FROM pg_catalog.pg_constraint c
   WHERE c.conrelid=table_id AND (c.conname IN(target.old_name,target.new_name)
    OR (c.contype='c' AND (SELECT array_agg(k ORDER BY k) FROM unnest(c.conkey) AS keys(k))=bound_columns));
  IF matches<>1
  THEN RAISE check_violation USING MESSAGE='556 exactly one original or TTL120 CHECK required'; END IF;
  SELECT c.* INTO original_check FROM pg_catalog.pg_constraint c
   WHERE c.conrelid=table_id AND c.conname IN(target.old_name,target.new_name);
  IF NOT FOUND OR original_check.contype<>'c' OR NOT original_check.convalidated OR original_check.connoinherit
   OR original_check.condeferrable OR original_check.condeferred OR NOT original_check.conislocal
   OR original_check.coninhcount<>0 OR original_check.conparentid<>0
   OR (SELECT array_agg(k ORDER BY k) FROM unnest(original_check.conkey) AS keys(k)) IS DISTINCT FROM bound_columns
  THEN RAISE check_violation USING MESSAGE='556 original validated TTL CHECK attributes/binding changed'; END IF;
  check_definition:=pg_catalog.pg_get_constraintdef(original_check.oid,false);
  IF (original_check.conname=target.old_name AND check_definition IS DISTINCT FROM old_check)
   OR (original_check.conname=target.new_name AND check_definition IS DISTINCT FROM new_check)
  THEN RAISE check_violation USING MESSAGE='556 exact original or TTL120 CHECK definition required'; END IF;
  before_checks:=before_checks||jsonb_build_array(jsonb_build_object(
   'table_name',target.table_name,'old_name',target.old_name,'new_name',target.new_name,
   'columns',to_jsonb(bound_columns),'metadata',to_jsonb(original_check)));
 END LOOP;

 -- All three objects have passed BEFORE any DDL. Replay accepts only exact120.
 FOR saved IN SELECT value FROM jsonb_array_elements(before_checks) LOOP
  IF saved->'metadata'->>'conname'=saved->>'old_name' THEN
   EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I',saved->>'table_name',saved->>'old_name');
   EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s',saved->>'table_name',saved->>'new_name',new_check);
  END IF;
  SELECT c.* INTO final_check FROM pg_catalog.pg_constraint c
   WHERE c.conrelid=(saved->'metadata'->>'conrelid')::oid AND c.conname=saved->>'new_name';
  IF NOT FOUND OR pg_catalog.pg_get_constraintdef(final_check.oid,false) IS DISTINCT FROM new_check
   OR to_jsonb((SELECT array_agg(k ORDER BY k) FROM unnest(final_check.conkey) AS keys(k))) IS DISTINCT FROM saved->'columns'
   OR (to_jsonb(final_check)-ARRAY['oid','conname','conbin','conkey']) IS DISTINCT FROM
      ((saved->'metadata')-ARRAY['oid','conname','conbin','conkey'])
   OR EXISTS(SELECT 1 FROM pg_catalog.pg_constraint c
    WHERE c.conrelid=final_check.conrelid AND c.conname=saved->>'old_name')
  THEN RAISE check_violation USING MESSAGE='556 TTL120 CHECK definition/name/validation/metadata changed'; END IF;
 END LOOP;

 -- Recheck before replacement too; never replace an unrecognized concurrent body.
 SELECT p.*,l.lanname INTO verified FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR to_jsonb(verified) IS DISTINCT FROM to_jsonb(actual)
 THEN RAISE check_violation USING MESSAGE='556 base-union receiver changed during preflight'; END IF;
 IF actual.prosrc IS NOT DISTINCT FROM old_body THEN
  EXECUTE replace(definition,old_body,new_body);
 END IF;
 SELECT p.*,l.lanname INTO verified FROM pg_catalog.pg_proc p
 JOIN pg_catalog.pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR verified.prosrc IS DISTINCT FROM new_body
 THEN RAISE check_violation USING MESSAGE='556 base-union receiver metadata/OID/owner/ACL or TTL120 body changed'; END IF;
END $ttl556$;
