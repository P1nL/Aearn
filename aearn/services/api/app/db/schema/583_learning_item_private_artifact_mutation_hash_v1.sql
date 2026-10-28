-- 583: canonical PRIVATE owner mutation hash + exact existing birth dependency pin.
-- Requires the complete582 target pair. No rows/permissions/global guard are changed.
DO $mutation583$
DECLARE
 actual pg_catalog.pg_proc%ROWTYPE;
 verified pg_catalog.pg_proc%ROWTYPE;
 birth_actual pg_catalog.pg_proc%ROWTYPE;
 birth_verified pg_catalog.pg_proc%ROWTYPE;
 consumer_actual pg_catalog.pg_proc%ROWTYPE;
 definition text;birth_definition text;
 old_body constant text := $old583$
DECLARE r record;b record;creation jsonb;
BEGIN
 IF a.owner_kind<>'learning_item' OR a.artifact_kind<>'knowledge_check' OR a.active_attempt_id IS NOT NULL THEN RETURN false; END IF;
 IF prior IS NULL THEN
  SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE mode='create' AND user_id=a.user_id AND run_id=a.turn_id AND version_id=a.owner_id AND txid=txid_current();
  RETURN FOUND AND item_supply_internal.native_consumer_frozen_artifact_matches(r.payload_json->'request',a)
   AND r.payload_json->'request'->'presentation'=a.presentation_json AND r.payload_json->'request'->'allowed_actions'=a.allowed_actions_json
   AND r.payload_json->'request'->>'state'=a.state AND item_supply_internal.private_native_consumer_current(r.id);
 END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=a.id AND user_id=a.user_id AND version_id=a.owner_id;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(b.user_id,b.epoch);
 SELECT payload_json INTO creation FROM tutor_item_supply_private_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';
 IF item_supply_internal.native_consumer_frozen_artifact_matches(creation->'request',a) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF historical THEN RETURN true; END IF;
 IF a.version<>(prior->>'version')::integer+1 THEN RETURN false; END IF;
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE artifact_id=a.id AND artifact_version=(prior->>'version')::integer
  AND user_id=a.user_id AND epoch=b.epoch AND version_id=a.owner_id AND txid=txid_current()
  AND ((a.state='cancelled' AND mode='cancel' AND action='cancel') OR(a.state IN('active','completed') AND mode='current' AND action IN('request_hint','request_direct_answer','respond')))
  ORDER BY created_at DESC,id DESC LIMIT 1;
 IF NOT FOUND THEN RETURN false; END IF;
 IF r.mode='cancel' AND (to_jsonb(a)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json'])
  IS DISTINCT FROM (prior-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json']) THEN RETURN false; END IF;
 IF r.mode='current' AND ((r.action='respond' AND a.state<>'completed') OR(r.action<>'respond' AND a.state<>'active')) THEN RETURN false; END IF;
 IF r.mode='current' AND (to_jsonb(a)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json','presentation_json'])
  IS DISTINCT FROM (prior-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json','presentation_json']) THEN RETURN false; END IF;
 IF r.action='request_hint' AND ((a.presentation_json-'revealed_hint_levels') IS DISTINCT FROM (prior->'presentation_json'-'revealed_hint_levels')
  OR a.allowed_actions_json IS DISTINCT FROM prior->'allowed_actions_json') THEN RETURN false; END IF;
 RETURN item_supply_internal.private_native_consumer_current(r.id);
END $old583$;
 target_body constant text := $target583$
DECLARE r record;b record;creation jsonb;
BEGIN
 IF a.owner_kind<>'learning_item' OR a.artifact_kind<>'knowledge_check' OR a.active_attempt_id IS NOT NULL THEN RETURN false; END IF;
 IF (a.presentation_hash=item_supply_internal.snapshot_hash(a.presentation_json)) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF prior IS NULL THEN
  SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE mode='create' AND user_id=a.user_id AND run_id=a.turn_id AND version_id=a.owner_id AND txid=txid_current();
  RETURN FOUND AND item_supply_internal.native_consumer_frozen_artifact_matches(r.payload_json->'request',a)
   AND r.payload_json->'request'->'presentation'=a.presentation_json AND r.payload_json->'request'->'allowed_actions'=a.allowed_actions_json
   AND r.payload_json->'request'->>'state'=a.state AND item_supply_internal.private_native_consumer_current(r.id);
 END IF;
 IF ((prior->>'presentation_hash')=item_supply_internal.snapshot_hash(prior->'presentation_json')) IS DISTINCT FROM true THEN RETURN false; END IF;
 SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=a.id AND user_id=a.user_id AND version_id=a.owner_id;
 IF NOT FOUND THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(b.user_id,b.epoch);
 SELECT payload_json INTO creation FROM tutor_item_supply_private_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';
 IF item_supply_internal.native_consumer_frozen_artifact_matches(creation->'request',a) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF historical THEN RETURN true; END IF;
 IF a.version<>(prior->>'version')::integer+1 THEN RETURN false; END IF;
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE artifact_id=a.id AND artifact_version=(prior->>'version')::integer
  AND user_id=a.user_id AND epoch=b.epoch AND version_id=a.owner_id AND txid=txid_current()
  AND ((a.state='cancelled' AND mode='cancel' AND action='cancel') OR(a.state IN('active','completed') AND mode='current' AND action IN('request_hint','request_direct_answer','respond')))
  ORDER BY created_at DESC,id DESC LIMIT 1;
 IF NOT FOUND THEN RETURN false; END IF;
 IF r.mode='cancel' AND (to_jsonb(a)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json'])
  IS DISTINCT FROM (prior-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json']) THEN RETURN false; END IF;
 IF r.mode='current' AND ((r.action='respond' AND a.state<>'completed') OR(r.action<>'respond' AND a.state<>'active')) THEN RETURN false; END IF;
 IF r.mode='current' AND (to_jsonb(a)-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json','presentation_json','presentation_hash'])
  IS DISTINCT FROM (prior-ARRAY['state','version','terminal_at','updated_at','allowed_actions_json','presentation_json','presentation_hash']) THEN RETURN false; END IF;
 IF r.action='request_hint' AND ((a.presentation_json-'revealed_hint_levels'::text) IS DISTINCT FROM ((prior->'presentation_json')-'revealed_hint_levels'::text)
  OR a.allowed_actions_json IS DISTINCT FROM (prior->'allowed_actions_json')) THEN RETURN false; END IF;
 RETURN item_supply_internal.private_native_consumer_current(r.id);
END $target583$;
 expected_attrs constant jsonb := $attrs583${"oid":"5380111","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"private_native_artifact_owner_matches","prorows":0,"pronargs":3,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["a","prior","historical"],"proargtypes":["5318731","3802","16"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs583$::jsonb;
 old_birth constant text := $birth583$
DECLARE
 a public.tutor_learning_artifacts%ROWTYPE;
 r public.tutor_item_supply_private_native_consumer_receipts%ROWTYPE;
 el public.tutor_item_supply_private_native_eligibility%ROWTYPE;
 exposure public.tutor_item_supply_private_native_exposure_snapshots%ROWTYPE;
 public_exposure public.tutor_item_supply_type_exposure_snapshots%ROWTYPE;
 dep record;dependency pg_catalog.pg_proc%ROWTYPE;hook record;
 call_stack text;parent_stack text;t timestamptz;
 capture_frame constant text := $capture_frame580$SQL statement "INSERT INTO tutor_item_supply_private_native_artifact_bindings(artifact_id,user_id,epoch,scope_id,pack_task_id,version_id,creation_receipt_id)
  VALUES(NEW.id,NEW.user_id,r.epoch,r.scope_id,r.pack_task_id,r.version_id,r.id)"
PL/pgSQL function capture_private_native_artifact_binding() line 7 at SQL statement$capture_frame580$;
BEGIN
 -- Depth is only a graph-shape check; exact engine parent frame supplies provenance.
 IF TG_OP<>'INSERT' OR TG_WHEN<>'BEFORE' OR TG_LEVEL<>'ROW'
  OR TG_RELID<>'public.tutor_item_supply_private_native_artifact_bindings'::regclass
  OR TG_NAME<>'private_native_binding_insert' OR pg_trigger_depth()<>2 THEN
  RAISE check_violation USING MESSAGE='580 original binding birth hook required'; END IF;
 GET DIAGNOSTICS call_stack = PG_CONTEXT;
 IF split_part(call_stack,E'\n',1) !~ '^PL/pgSQL function enforce_private_native_binding_insert[(][)] line [0-9]+ at GET DIAGNOSTICS$' THEN
  RAISE check_violation USING MESSAGE='580 original binding engine frame required'; END IF;
 parent_stack:=substring(call_stack FROM position(E'\n' IN call_stack)+1);
 IF left(parent_stack,length(capture_frame)) IS DISTINCT FROM capture_frame
  OR substring(parent_stack FROM length(capture_frame)+1 FOR 1) NOT IN ('',E'\n') THEN
  RAISE check_violation USING MESSAGE='580 original direct Artifact capture required'; END IF;
 -- Fixed direct birth dependencies only; no dynamic dependency discovery.
 FOR dep IN SELECT * FROM (VALUES
  ('public.enforce_tutor_learning_artifact_owner_scope()','70a066f41f2bf240c2214cf728742f9bcd4a7b58954dd8e6e16d154b99591a0c','plpgsql','pg_catalog.trigger'::regtype,''::oidvector,NULL::text[],false,false,'v'),
  ('public.capture_private_native_artifact_binding()','3bb468e4dfc52e252c5626aab6fd08b382af39982f3c18618aaf292c215bb776','plpgsql','pg_catalog.trigger'::regtype,''::oidvector,NULL::text[],false,true,'v'),
  ('item_supply_internal.private_native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean)','14c96fe603680b56993592500073360a44091281230737fbd72914f5cde792b1','plpgsql','pg_catalog.bool'::regtype,('public.tutor_learning_artifacts'::regtype::oid::text||' '||'pg_catalog.jsonb'::regtype::oid::text||' '||'pg_catalog.bool'::regtype::oid::text)::oidvector,ARRAY['a','prior','historical']::text[],false,true,'v'),
  ('item_supply_internal.native_consumer_frozen_artifact_matches(jsonb,tutor_learning_artifacts)','cc79716be4f599fbe03faaf6c20835ddf82e409655c6cf3c80b3064ba1564e6b','sql','pg_catalog.bool'::regtype,('pg_catalog.jsonb'::regtype::oid::text||' '||'public.tutor_learning_artifacts'::regtype::oid::text)::oidvector,ARRAY['q','a']::text[],true,true,'i'),
  ('item_supply_internal.capture_private_native_exposure_origin()','f8cf5b7e14e4ef115a12ef399a9d272bfc735677397e6ed0d3c452b15e764ea8','plpgsql','pg_catalog.trigger'::regtype,''::oidvector,NULL::text[],false,true,'v'),
  ('item_supply_internal.private_native_consumer_current(uuid)','67a52de8756643912152c92b0b6af706e5c20ad5a38dfeea46652e8ecf676401','plpgsql','pg_catalog.bool'::regtype,('pg_catalog.uuid'::regtype::oid::text)::oidvector,ARRAY['rid']::text[],false,true,'v'),
  ('item_supply_internal.private_native_exposure_current(uuid,uuid,bigint)','dfcc950a6c22b46dcdc99aac198658b39f91acf12ec2081ff938b0f151aad5be','plpgsql','pg_catalog.jsonb'::regtype,('pg_catalog.uuid'::regtype::oid::text||' '||'pg_catalog.uuid'::regtype::oid::text||' '||'pg_catalog.int8'::regtype::oid::text)::oidvector,ARRAY['sid','u','e']::text[],false,true,'v')
 ) AS expected(signature,body_hash,language_name,result_type,arg_types,arg_names,is_strict,is_definer,volatility)
 LOOP
  SELECT p.* INTO dependency FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure(dep.signature);
  IF NOT FOUND OR dependency.pronamespace IS DISTINCT FROM split_part(dep.signature,'.',1)::regnamespace
   OR dependency.proname IS DISTINCT FROM split_part(split_part(dep.signature,'.',2),'(',1)
   OR dependency.prokind<>'f' OR dependency.proretset OR dependency.proleakproof
   OR dependency.prolang IS DISTINCT FROM (SELECT oid FROM pg_catalog.pg_language WHERE lanname=dep.language_name)
   OR dependency.prorettype IS DISTINCT FROM dep.result_type OR dependency.proargtypes IS DISTINCT FROM dep.arg_types
   OR dependency.pronargs IS DISTINCT FROM COALESCE(cardinality(string_to_array(NULLIF(dep.arg_types::text,''),' ')),0)
   OR dependency.proargnames IS DISTINCT FROM dep.arg_names
   OR dependency.proisstrict IS DISTINCT FROM dep.is_strict OR dependency.prosecdef IS DISTINCT FROM dep.is_definer
   OR dependency.provolatile IS DISTINCT FROM dep.volatility::"char" OR dependency.proparallel<>'u'
   OR dependency.proallargtypes IS NOT NULL OR dependency.proargmodes IS NOT NULL OR dependency.provariadic<>0
   OR dependency.pronargdefaults<>0 OR dependency.proargdefaults IS NOT NULL OR dependency.probin IS NOT NULL
   OR dependency.prosqlbody IS NOT NULL OR dependency.protrftypes IS NOT NULL
   OR dependency.procost<>100 OR dependency.prorows<>0 OR dependency.prosupport<>0
   OR dependency.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR dependency.proacl IS DISTINCT FROM (CASE WHEN dep.is_definer
     THEN ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] ELSE NULL::aclitem[] END)
   OR dependency.proconfig IS DISTINCT FROM (CASE WHEN dep.is_definer
     THEN ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] ELSE NULL::text[] END)
   OR encode(public.digest(convert_to(replace(dependency.prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') IS DISTINCT FROM dep.body_hash
  THEN RAISE check_violation USING MESSAGE='580 original direct birth dependency changed'; END IF;
 END LOOP;
 FOR hook IN SELECT * FROM (VALUES
  ('public.tutor_learning_artifacts','trg_tutor_learning_artifacts_owner_scope','public.enforce_tutor_learning_artifact_owner_scope()',23),
  ('public.tutor_learning_artifacts','a000_private_native_artifact_binding_capture','public.capture_private_native_artifact_binding()',5),
  ('public.tutor_item_supply_private_native_artifact_bindings','private_native_binding_insert','public.enforce_private_native_binding_insert()',7),
  ('public.tutor_item_supply_private_native_artifact_bindings','a001_private_native_exposure_capture','item_supply_internal.capture_private_native_exposure_origin()',5)
 ) AS expected(table_name,trigger_name,signature,trigger_type)
 LOOP
  IF (SELECT count(*) FROM pg_catalog.pg_trigger tr
   WHERE tr.tgrelid=pg_catalog.to_regclass(hook.table_name) AND tr.tgname=hook.trigger_name
    AND tr.tgfoid=pg_catalog.to_regprocedure(hook.signature) AND tr.tgtype=hook.trigger_type
    AND tr.tgenabled='O' AND NOT tr.tgisinternal AND NOT tr.tgdeferrable AND NOT tr.tginitdeferred
    AND tr.tgnargs=0 AND tr.tgargs=''::bytea AND tr.tgattr::text='' AND tr.tgqual IS NULL
    AND tr.tgparentid=0 AND tr.tgconstraint=0 AND tr.tgconstrrelid=0 AND tr.tgconstrindid=0
    AND tr.tgoldtable IS NULL AND tr.tgnewtable IS NULL)<>1 THEN
   RAISE check_violation USING MESSAGE='580 original four birth hooks changed'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM pg_catalog.pg_trigger WHERE tgfoid='public.capture_private_native_artifact_binding()'::regprocedure)<>1 THEN
  RAISE check_violation USING MESSAGE='580 original Artifact capture attachment changed'; END IF;

 SELECT * INTO a FROM public.tutor_learning_artifacts WHERE id=NEW.artifact_id AND user_id=NEW.user_id AND owner_id=NEW.version_id;
 SELECT * INTO r FROM public.tutor_item_supply_private_native_consumer_receipts WHERE id=NEW.creation_receipt_id AND mode='create';
 IF a.id IS NULL OR r.id IS NULL OR a.version IS DISTINCT FROM 1
  OR (SELECT count(*) FROM public.tutor_item_supply_private_native_consumer_receipts
   WHERE mode='create' AND user_id=a.user_id AND run_id=a.turn_id AND version_id=a.owner_id AND txid=txid_current())<>1
  OR (r.user_id,r.epoch,r.scope_id,r.pack_task_id,r.version_id,r.run_id) IS DISTINCT FROM (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.pack_task_id,NEW.version_id,a.turn_id)
  OR r.txid IS DISTINCT FROM txid_current() OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR r.payload_json->>'schema_version' IS DISTINCT FROM 'private_native_creation_v1'
  OR a.owner_kind IS DISTINCT FROM 'learning_item' OR a.artifact_kind IS DISTINCT FROM 'knowledge_check'
  OR a.artifact_schema_version IS DISTINCT FROM 'tutor_learning_artifact_v1'
  OR a.active_attempt_id IS NOT NULL OR a.terminal_at IS NOT NULL
  OR a.presentation_kind IS DISTINCT FROM 'knowledge_check_v1'
  OR a.presentation_json->>'type' IS DISTINCT FROM a.presentation_kind
  OR item_supply_internal.native_consumer_frozen_artifact_matches(r.payload_json->'request',a) IS DISTINCT FROM true
  OR r.payload_json->'request'->'presentation' IS DISTINCT FROM a.presentation_json
  OR r.payload_json->'request'->'allowed_actions' IS DISTINCT FROM a.allowed_actions_json
  OR r.payload_json->'request'->>'state' IS DISTINCT FROM a.state
  OR a.presentation_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.presentation_json) THEN
  RAISE check_violation USING MESSAGE='580 exact original PRIVATE Artifact birth required'; END IF;
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO el FROM public.tutor_item_supply_private_native_eligibility WHERE id=r.eligibility_id;
 SELECT * INTO exposure FROM public.tutor_item_supply_private_native_exposure_snapshots WHERE id=r.exposure_snapshot_id;
 SELECT * INTO public_exposure FROM public.tutor_item_supply_type_exposure_snapshots WHERE id=exposure.public_snapshot_id;
 t:=clock_timestamp();
 IF el.id IS NULL OR exposure.id IS NULL OR public_exposure.id IS NULL
  OR (el.user_id,el.epoch,el.scope_id,el.pack_task_id,el.exposure_snapshot_id) IS DISTINCT FROM (r.user_id,r.epoch,r.scope_id,r.pack_task_id,r.exposure_snapshot_id)
  OR el.txid IS DISTINCT FROM txid_current()
  OR (exposure.user_id,exposure.epoch) IS DISTINCT FROM (r.user_id,r.epoch)
  OR (public_exposure.user_id,public_exposure.epoch) IS DISTINCT FROM (r.user_id,r.epoch)
  OR r.checked_at>t OR t>=r.valid_until OR r.valid_until>el.valid_until
  OR el.checked_at>t OR t>=el.valid_until OR el.valid_until>exposure.valid_until
  OR exposure.checked_at>t OR t>=exposure.valid_until OR exposure.valid_until>public_exposure.valid_until
  OR public_exposure.checked_at>t OR t>=public_exposure.valid_until THEN
  RAISE check_violation USING MESSAGE='580 original same-TOP birth epoch/window required'; END IF;
 -- Original BEFORE already ran full current/global historical-unbound checks on THIS INSERT.
 -- Do not reenter that graph while its own new binding is still absent.
 RETURN NEW;
END $birth583$;
 target_birth constant text := $birthtarget583$
DECLARE
 a public.tutor_learning_artifacts%ROWTYPE;
 r public.tutor_item_supply_private_native_consumer_receipts%ROWTYPE;
 el public.tutor_item_supply_private_native_eligibility%ROWTYPE;
 exposure public.tutor_item_supply_private_native_exposure_snapshots%ROWTYPE;
 public_exposure public.tutor_item_supply_type_exposure_snapshots%ROWTYPE;
 dep record;dependency pg_catalog.pg_proc%ROWTYPE;hook record;
 call_stack text;parent_stack text;t timestamptz;
 capture_frame constant text := $capture_frame580$SQL statement "INSERT INTO tutor_item_supply_private_native_artifact_bindings(artifact_id,user_id,epoch,scope_id,pack_task_id,version_id,creation_receipt_id)
  VALUES(NEW.id,NEW.user_id,r.epoch,r.scope_id,r.pack_task_id,r.version_id,r.id)"
PL/pgSQL function capture_private_native_artifact_binding() line 7 at SQL statement$capture_frame580$;
BEGIN
 -- Depth is only a graph-shape check; exact engine parent frame supplies provenance.
 IF TG_OP<>'INSERT' OR TG_WHEN<>'BEFORE' OR TG_LEVEL<>'ROW'
  OR TG_RELID<>'public.tutor_item_supply_private_native_artifact_bindings'::regclass
  OR TG_NAME<>'private_native_binding_insert' OR pg_trigger_depth()<>2 THEN
  RAISE check_violation USING MESSAGE='580 original binding birth hook required'; END IF;
 GET DIAGNOSTICS call_stack = PG_CONTEXT;
 IF split_part(call_stack,E'\n',1) !~ '^PL/pgSQL function enforce_private_native_binding_insert[(][)] line [0-9]+ at GET DIAGNOSTICS$' THEN
  RAISE check_violation USING MESSAGE='580 original binding engine frame required'; END IF;
 parent_stack:=substring(call_stack FROM position(E'\n' IN call_stack)+1);
 IF left(parent_stack,length(capture_frame)) IS DISTINCT FROM capture_frame
  OR substring(parent_stack FROM length(capture_frame)+1 FOR 1) NOT IN ('',E'\n') THEN
  RAISE check_violation USING MESSAGE='580 original direct Artifact capture required'; END IF;
 -- Fixed direct birth dependencies only; no dynamic dependency discovery.
 FOR dep IN SELECT * FROM (VALUES
  ('public.enforce_tutor_learning_artifact_owner_scope()','70a066f41f2bf240c2214cf728742f9bcd4a7b58954dd8e6e16d154b99591a0c','plpgsql','pg_catalog.trigger'::regtype,''::oidvector,NULL::text[],false,false,'v'),
  ('public.capture_private_native_artifact_binding()','3bb468e4dfc52e252c5626aab6fd08b382af39982f3c18618aaf292c215bb776','plpgsql','pg_catalog.trigger'::regtype,''::oidvector,NULL::text[],false,true,'v'),
  ('item_supply_internal.private_native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean)','9d4b2fe3d4a5bae22ec38aa0db57dd6fa6cb4499a750d593b144ca29a1eb56af','plpgsql','pg_catalog.bool'::regtype,('public.tutor_learning_artifacts'::regtype::oid::text||' '||'pg_catalog.jsonb'::regtype::oid::text||' '||'pg_catalog.bool'::regtype::oid::text)::oidvector,ARRAY['a','prior','historical']::text[],false,true,'v'),
  ('item_supply_internal.native_consumer_frozen_artifact_matches(jsonb,tutor_learning_artifacts)','cc79716be4f599fbe03faaf6c20835ddf82e409655c6cf3c80b3064ba1564e6b','sql','pg_catalog.bool'::regtype,('pg_catalog.jsonb'::regtype::oid::text||' '||'public.tutor_learning_artifacts'::regtype::oid::text)::oidvector,ARRAY['q','a']::text[],true,true,'i'),
  ('item_supply_internal.capture_private_native_exposure_origin()','f8cf5b7e14e4ef115a12ef399a9d272bfc735677397e6ed0d3c452b15e764ea8','plpgsql','pg_catalog.trigger'::regtype,''::oidvector,NULL::text[],false,true,'v'),
  ('item_supply_internal.private_native_consumer_current(uuid)','67a52de8756643912152c92b0b6af706e5c20ad5a38dfeea46652e8ecf676401','plpgsql','pg_catalog.bool'::regtype,('pg_catalog.uuid'::regtype::oid::text)::oidvector,ARRAY['rid']::text[],false,true,'v'),
  ('item_supply_internal.private_native_exposure_current(uuid,uuid,bigint)','dfcc950a6c22b46dcdc99aac198658b39f91acf12ec2081ff938b0f151aad5be','plpgsql','pg_catalog.jsonb'::regtype,('pg_catalog.uuid'::regtype::oid::text||' '||'pg_catalog.uuid'::regtype::oid::text||' '||'pg_catalog.int8'::regtype::oid::text)::oidvector,ARRAY['sid','u','e']::text[],false,true,'v')
 ) AS expected(signature,body_hash,language_name,result_type,arg_types,arg_names,is_strict,is_definer,volatility)
 LOOP
  SELECT p.* INTO dependency FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure(dep.signature);
  IF NOT FOUND OR dependency.pronamespace IS DISTINCT FROM split_part(dep.signature,'.',1)::regnamespace
   OR dependency.proname IS DISTINCT FROM split_part(split_part(dep.signature,'.',2),'(',1)
   OR dependency.prokind<>'f' OR dependency.proretset OR dependency.proleakproof
   OR dependency.prolang IS DISTINCT FROM (SELECT oid FROM pg_catalog.pg_language WHERE lanname=dep.language_name)
   OR dependency.prorettype IS DISTINCT FROM dep.result_type OR dependency.proargtypes IS DISTINCT FROM dep.arg_types
   OR dependency.pronargs IS DISTINCT FROM COALESCE(cardinality(string_to_array(NULLIF(dep.arg_types::text,''),' ')),0)
   OR dependency.proargnames IS DISTINCT FROM dep.arg_names
   OR dependency.proisstrict IS DISTINCT FROM dep.is_strict OR dependency.prosecdef IS DISTINCT FROM dep.is_definer
   OR dependency.provolatile IS DISTINCT FROM dep.volatility::"char" OR dependency.proparallel<>'u'
   OR dependency.proallargtypes IS NOT NULL OR dependency.proargmodes IS NOT NULL OR dependency.provariadic<>0
   OR dependency.pronargdefaults<>0 OR dependency.proargdefaults IS NOT NULL OR dependency.probin IS NOT NULL
   OR dependency.prosqlbody IS NOT NULL OR dependency.protrftypes IS NOT NULL
   OR dependency.procost<>100 OR dependency.prorows<>0 OR dependency.prosupport<>0
   OR dependency.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
   OR dependency.proacl IS DISTINCT FROM (CASE WHEN dep.is_definer
     THEN ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[] ELSE NULL::aclitem[] END)
   OR dependency.proconfig IS DISTINCT FROM (CASE WHEN dep.is_definer
     THEN ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] ELSE NULL::text[] END)
   OR encode(public.digest(convert_to(replace(dependency.prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') IS DISTINCT FROM dep.body_hash
  THEN RAISE check_violation USING MESSAGE='580 original direct birth dependency changed'; END IF;
 END LOOP;
 FOR hook IN SELECT * FROM (VALUES
  ('public.tutor_learning_artifacts','trg_tutor_learning_artifacts_owner_scope','public.enforce_tutor_learning_artifact_owner_scope()',23),
  ('public.tutor_learning_artifacts','a000_private_native_artifact_binding_capture','public.capture_private_native_artifact_binding()',5),
  ('public.tutor_item_supply_private_native_artifact_bindings','private_native_binding_insert','public.enforce_private_native_binding_insert()',7),
  ('public.tutor_item_supply_private_native_artifact_bindings','a001_private_native_exposure_capture','item_supply_internal.capture_private_native_exposure_origin()',5)
 ) AS expected(table_name,trigger_name,signature,trigger_type)
 LOOP
  IF (SELECT count(*) FROM pg_catalog.pg_trigger tr
   WHERE tr.tgrelid=pg_catalog.to_regclass(hook.table_name) AND tr.tgname=hook.trigger_name
    AND tr.tgfoid=pg_catalog.to_regprocedure(hook.signature) AND tr.tgtype=hook.trigger_type
    AND tr.tgenabled='O' AND NOT tr.tgisinternal AND NOT tr.tgdeferrable AND NOT tr.tginitdeferred
    AND tr.tgnargs=0 AND tr.tgargs=''::bytea AND tr.tgattr::text='' AND tr.tgqual IS NULL
    AND tr.tgparentid=0 AND tr.tgconstraint=0 AND tr.tgconstrrelid=0 AND tr.tgconstrindid=0
    AND tr.tgoldtable IS NULL AND tr.tgnewtable IS NULL)<>1 THEN
   RAISE check_violation USING MESSAGE='580 original four birth hooks changed'; END IF;
 END LOOP;
 IF (SELECT count(*) FROM pg_catalog.pg_trigger WHERE tgfoid='public.capture_private_native_artifact_binding()'::regprocedure)<>1 THEN
  RAISE check_violation USING MESSAGE='580 original Artifact capture attachment changed'; END IF;

 SELECT * INTO a FROM public.tutor_learning_artifacts WHERE id=NEW.artifact_id AND user_id=NEW.user_id AND owner_id=NEW.version_id;
 SELECT * INTO r FROM public.tutor_item_supply_private_native_consumer_receipts WHERE id=NEW.creation_receipt_id AND mode='create';
 IF a.id IS NULL OR r.id IS NULL OR a.version IS DISTINCT FROM 1
  OR (SELECT count(*) FROM public.tutor_item_supply_private_native_consumer_receipts
   WHERE mode='create' AND user_id=a.user_id AND run_id=a.turn_id AND version_id=a.owner_id AND txid=txid_current())<>1
  OR (r.user_id,r.epoch,r.scope_id,r.pack_task_id,r.version_id,r.run_id) IS DISTINCT FROM (NEW.user_id,NEW.epoch,NEW.scope_id,NEW.pack_task_id,NEW.version_id,a.turn_id)
  OR r.txid IS DISTINCT FROM txid_current() OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR r.payload_json->>'schema_version' IS DISTINCT FROM 'private_native_creation_v1'
  OR a.owner_kind IS DISTINCT FROM 'learning_item' OR a.artifact_kind IS DISTINCT FROM 'knowledge_check'
  OR a.artifact_schema_version IS DISTINCT FROM 'tutor_learning_artifact_v1'
  OR a.active_attempt_id IS NOT NULL OR a.terminal_at IS NOT NULL
  OR a.presentation_kind IS DISTINCT FROM 'knowledge_check_v1'
  OR a.presentation_json->>'type' IS DISTINCT FROM a.presentation_kind
  OR item_supply_internal.native_consumer_frozen_artifact_matches(r.payload_json->'request',a) IS DISTINCT FROM true
  OR r.payload_json->'request'->'presentation' IS DISTINCT FROM a.presentation_json
  OR r.payload_json->'request'->'allowed_actions' IS DISTINCT FROM a.allowed_actions_json
  OR r.payload_json->'request'->>'state' IS DISTINCT FROM a.state
  OR a.presentation_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.presentation_json) THEN
  RAISE check_violation USING MESSAGE='580 exact original PRIVATE Artifact birth required'; END IF;
 PERFORM item_supply_internal.private_native_epoch(NEW.user_id,NEW.epoch);
 SELECT * INTO el FROM public.tutor_item_supply_private_native_eligibility WHERE id=r.eligibility_id;
 SELECT * INTO exposure FROM public.tutor_item_supply_private_native_exposure_snapshots WHERE id=r.exposure_snapshot_id;
 SELECT * INTO public_exposure FROM public.tutor_item_supply_type_exposure_snapshots WHERE id=exposure.public_snapshot_id;
 t:=clock_timestamp();
 IF el.id IS NULL OR exposure.id IS NULL OR public_exposure.id IS NULL
  OR (el.user_id,el.epoch,el.scope_id,el.pack_task_id,el.exposure_snapshot_id) IS DISTINCT FROM (r.user_id,r.epoch,r.scope_id,r.pack_task_id,r.exposure_snapshot_id)
  OR el.txid IS DISTINCT FROM txid_current()
  OR (exposure.user_id,exposure.epoch) IS DISTINCT FROM (r.user_id,r.epoch)
  OR (public_exposure.user_id,public_exposure.epoch) IS DISTINCT FROM (r.user_id,r.epoch)
  OR r.checked_at>t OR t>=r.valid_until OR r.valid_until>el.valid_until
  OR el.checked_at>t OR t>=el.valid_until OR el.valid_until>exposure.valid_until
  OR exposure.checked_at>t OR t>=exposure.valid_until OR exposure.valid_until>public_exposure.valid_until
  OR public_exposure.checked_at>t OR t>=public_exposure.valid_until THEN
  RAISE check_violation USING MESSAGE='580 original same-TOP birth epoch/window required'; END IF;
 -- Original BEFORE already ran full current/global historical-unbound checks on THIS INSERT.
 -- Do not reenter that graph while its own new binding is still absent.
 RETURN NEW;
END $birthtarget583$;
 expected_birth_attrs constant jsonb := $ba583${"oid":"5380112","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_private_native_binding_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"2200","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$ba583$::jsonb;
 expected_consumer_attrs constant jsonb := $ca583${"oid":"5380106","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"private_native_consumer_current","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["rid"],"proargtypes":["2950"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$ca583$::jsonb;
 old_helper_pin constant text := '14c96fe603680b56993592500073360a44091281230737fbd72914f5cde792b1';
 target_helper_pin constant text := '9d4b2fe3d4a5bae22ec38aa0db57dd6fa6cb4499a750d593b144ca29a1eb56af';
 typed_consumer_pin constant text := '67a52de8756643912152c92b0b6af706e5c20ad5a38dfeea46652e8ecf676401';
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off' THEN
  RAISE check_violation USING MESSAGE='583 original isolated writable caller transaction required'; END IF;
 -- Prove582's typed consumer and complete birth target before either mutation.
 SELECT p.* INTO consumer_actual FROM pg_catalog.pg_proc p
  WHERE p.oid='item_supply_internal.private_native_consumer_current(uuid)'::regprocedure;
 IF NOT FOUND OR (to_jsonb(consumer_actual)-'prosrc') IS DISTINCT FROM expected_consumer_attrs
  OR encode(public.digest(convert_to(replace(consumer_actual.prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') IS DISTINCT FROM typed_consumer_pin THEN
  RAISE check_violation USING MESSAGE='583 exact582 typed consumer and original attributes required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p
  WHERE p.oid='item_supply_internal.private_native_artifact_owner_matches(tutor_learning_artifacts,jsonb,boolean)'::regprocedure;
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs THEN
  RAISE check_violation USING MESSAGE='583 original owner helper OID or attributes changed'; END IF;
 SELECT p.* INTO birth_actual FROM pg_catalog.pg_proc p
  WHERE p.oid='public.enforce_private_native_binding_insert()'::regprocedure;
 IF NOT FOUND OR (to_jsonb(birth_actual)-'prosrc') IS DISTINCT FROM expected_birth_attrs THEN
  RAISE check_violation USING MESSAGE='583 original birth receiver OID or attributes changed'; END IF;
 IF actual.prosrc IS DISTINCT FROM old_body AND actual.prosrc IS DISTINCT FROM target_body THEN
  RAISE check_violation USING MESSAGE='583 original owner helper body changed'; END IF;
 IF birth_actual.prosrc IS DISTINCT FROM old_birth AND birth_actual.prosrc IS DISTINCT FROM target_birth THEN
  RAISE check_violation USING MESSAGE='583 exact582 birth target or583 target required'; END IF;
 IF NOT ((actual.prosrc IS NOT DISTINCT FROM old_body AND birth_actual.prosrc IS NOT DISTINCT FROM old_birth)
   OR (actual.prosrc IS NOT DISTINCT FROM target_body AND birth_actual.prosrc IS NOT DISTINCT FROM target_birth)) THEN
  RAISE check_violation USING MESSAGE='583 complete original pair or exact target replay required'; END IF;
 IF length(old_birth)-length(replace(old_birth,old_helper_pin,''))<>length(old_helper_pin)
  OR target_birth IS DISTINCT FROM replace(old_birth,old_helper_pin,target_helper_pin)
  OR encode(public.digest(convert_to(replace(old_body,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') IS DISTINCT FROM old_helper_pin
  OR encode(public.digest(convert_to(replace(target_body,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') IS DISTINCT FROM target_helper_pin THEN
  RAISE check_violation USING MESSAGE='583 exact existing helper to birth protocol pin required'; END IF;
 -- All bodies/attributes/pins have passed. Exact-new replay executes no DDL.
 IF actual.prosrc IS DISTINCT FROM target_body THEN
  definition:=pg_catalog.pg_get_functiondef(actual.oid);
  IF length(definition)-length(replace(definition,old_body,''))<>length(old_body) THEN
   RAISE check_violation USING MESSAGE='583 exact original owner helper definition required'; END IF;
  EXECUTE replace(definition,old_body,target_body);
 END IF;
 IF birth_actual.prosrc IS DISTINCT FROM target_birth THEN
  birth_definition:=pg_catalog.pg_get_functiondef(birth_actual.oid);
  IF length(birth_definition)-length(replace(birth_definition,old_birth,''))<>length(old_birth) THEN
   RAISE check_violation USING MESSAGE='583 exact original birth receiver definition required'; END IF;
  EXECUTE replace(birth_definition,old_birth,target_birth);
 END IF;
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR verified.prosrc IS DISTINCT FROM target_body
  OR encode(public.digest(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8'),'sha256'),'hex') IS DISTINCT FROM target_helper_pin THEN
  RAISE check_violation USING MESSAGE='583 exact canonical owner helper and preserved attributes required'; END IF;
 SELECT p.* INTO birth_verified FROM pg_catalog.pg_proc p WHERE p.oid=birth_actual.oid;
 IF NOT FOUND OR (to_jsonb(birth_verified)-'prosrc') IS DISTINCT FROM expected_birth_attrs
  OR birth_verified.prosrc IS DISTINCT FROM target_birth THEN
  RAISE check_violation USING MESSAGE='583 exact birth helper pin and preserved attributes required'; END IF;
END;
$mutation583$;

