-- 582: executed PRIVATE KC local rowtype plus the exact direct birth dependency pin.
-- <=581 frozen. Only consumer local a type and its one existing birth pin change.
DO $rowtype582$
DECLARE
 actual pg_catalog.pg_proc%ROWTYPE;
 verified pg_catalog.pg_proc%ROWTYPE;
 definition text;
 old_body constant text := $old582$
DECLARE r record;b record;a record;el record;res record;pub record;m jsonb;creation jsonb;q jsonb;p jsonb;current_pub jsonb;selected jsonb;protected jsonb;t timestamptz;is_mvp boolean;
BEGIN
 SELECT * INTO r FROM tutor_item_supply_private_native_consumer_receipts WHERE id=rid;
 IF NOT FOUND OR r.txid<>txid_current() OR current_setting('transaction_isolation')<>'read committed' THEN RETURN false; END IF;
 PERFORM item_supply_internal.private_native_epoch(r.user_id,r.epoch);
 PERFORM item_supply_internal.native_exposure_lock(r.user_id,r.epoch);
 p:=r.payload_json;
 IF r.mode='create' THEN
  SELECT * INTO res FROM tutor_item_supply_private_native_assessment_reservations WHERE id=r.reservation_id;
  SELECT * INTO el FROM tutor_item_supply_private_native_eligibility WHERE id=r.eligibility_id;
  IF res.id IS NULL OR el.id IS NULL OR (res.user_id,res.epoch,res.scope_id,res.pack_task_id) IS DISTINCT FROM (r.user_id,r.epoch,r.scope_id,r.pack_task_id)
   OR (el.user_id,el.epoch,el.scope_id,el.pack_task_id,el.exposure_snapshot_id) IS DISTINCT FROM (r.user_id,r.epoch,r.scope_id,r.pack_task_id,r.exposure_snapshot_id)
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_creation_v1'
   OR p->>'mapping_id' IS DISTINCT FROM el.mapping_id::text OR res.payload_json->>'mapping_id' IS DISTINCT FROM el.mapping_id::text
   OR item_supply_internal.private_native_eligibility_current(el.id) IS DISTINCT FROM true THEN RETURN false; END IF;
  SELECT value INTO selected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') WHERE value->>'version_id'=r.version_id::text AND value->'member'->>'slot'=CASE WHEN p->'request'->>'purpose'='remediation' THEN 'remediation' ELSE 'practice' END;
  SELECT jsonb_agg(c->'type_evidence'->'content' ORDER BY c->>'version_id') INTO protected FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE c->'member'->>'slot'='assessment';
  IF selected IS NULL OR selected IS DISTINCT FROM p->'selected' OR p->'content' IS DISTINCT FROM selected->'type_evidence'->'content'
   OR protected IS DISTINCT FROM res.payload_json->'protected'
   OR p->>'pack_request_hash' IS DISTINCT FROM res.payload_json->>'pack_request_hash'
   OR p->>'pack_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(el.payload_json->'snapshot'->'request')
   OR EXISTS(SELECT 1 FROM jsonb_array_elements(el.payload_json->'snapshot'->'selected') c WHERE NOT EXISTS
      (SELECT 1 FROM jsonb_array_elements_text(res.payload_json->'versions') v WHERE v.value=c->>'version_id')) THEN RETURN false; END IF;
  creation:=p;q:=p->'request';
  IF (q->>'purpose'<>'knowledge_check' OR p->>'parent_artifact_id' IS NOT NULL) AND item_supply_internal.private_native_successor_creation_current(r.id) IS DISTINCT FROM true THEN RETURN false; END IF;
 ELSE
  IF r.mode NOT IN('current','cancel') OR r.action NOT IN('request_hint','request_direct_answer','respond','cancel')
   OR (r.mode='cancel') IS DISTINCT FROM (r.action='cancel')
   OR p->>'schema_version' IS DISTINCT FROM 'private_native_action_v1' OR p->>'action' IS DISTINCT FROM r.action
   OR p->>'artifact_id' IS DISTINCT FROM r.artifact_id::text OR p->>'artifact_version' IS DISTINCT FROM r.artifact_version::text THEN RETURN false; END IF;
  SELECT * INTO b FROM tutor_item_supply_private_native_artifact_bindings WHERE artifact_id=r.artifact_id AND user_id=r.user_id AND epoch=r.epoch AND version_id=r.version_id AND scope_id=r.scope_id AND pack_task_id=r.pack_task_id;
  IF NOT FOUND OR p->>'creation_receipt_id' IS DISTINCT FROM b.creation_receipt_id::text THEN RETURN false; END IF;
  SELECT payload_json INTO creation FROM tutor_item_supply_private_native_consumer_receipts WHERE id=b.creation_receipt_id AND mode='create';q:=creation->'request';
  -- Historical eligibility is policy DATA only; fresh action/source checks remain below.
  SELECT eligibility.* INTO el FROM tutor_item_supply_private_native_eligibility eligibility
   JOIN tutor_item_supply_private_native_consumer_receipts origin ON origin.eligibility_id=eligibility.id
   WHERE origin.id=b.creation_receipt_id AND origin.user_id=r.user_id AND origin.epoch=r.epoch
    AND eligibility.user_id=r.user_id AND eligibility.epoch=r.epoch;
  SELECT * INTO a FROM tutor_learning_artifacts WHERE id=r.artifact_id AND user_id=r.user_id AND version=r.artifact_version AND owner_kind='learning_item'
    AND owner_id=r.version_id AND artifact_kind='knowledge_check' AND state IN('pending','ready','active') AND active_attempt_id IS NULL;
  IF NOT FOUND OR item_supply_internal.native_consumer_frozen_artifact_matches(q,a) IS DISTINCT FROM true THEN RETURN false; END IF;
 END IF;
 is_mvp:=(el.payload_json->'snapshot'->>'schema_version'='pack_snapshot_mvp_v1' AND el.payload_json->'snapshot'->>'relation_validation'='not_asserted_for_mvp' AND el.payload_json->'snapshot'->'relationship_receipt_hashes'='[]'::jsonb AND el.payload_json->'relations'='[]'::jsonb) IS TRUE;
 m:=item_supply_internal.private_native_mapping_current((creation->>'mapping_id')::uuid,r.user_id,r.epoch);
 IF m IS NULL OR (q->>'user_id',q->>'owner_id',q->>'owner_kind',q->>'artifact_kind',q->>'purpose',q->>'knowledge_key',q->>'learning_track_id')
   IS DISTINCT FROM (r.user_id::text,r.version_id::text,'learning_item','knowledge_check',CASE WHEN creation->>'parent_artifact_id' IS NOT NULL AND q->>'purpose' IN('remediation','transfer_check') THEN q->>'purpose' ELSE 'knowledge_check' END,m->'frozen_node'->>'knowledge_key',m->'frozen_node'->>'track_id')
  OR (r.mode='create' AND q->>'turn_id' IS DISTINCT FROM r.run_id::text)
  OR item_supply_internal.native_consumer_teaching_request_current(q,(m->'frozen_node'->>'revision_id')::uuid) IS DISTINCT FROM true THEN RETURN false; END IF;
 IF r.mode='cancel' THEN
  -- Only exact still-owned original KC/CAS; no content/source/current-pack right.
  RETURN r.action='cancel' AND r.checked_at<=clock_timestamp() AND clock_timestamp()<r.valid_until;
 END IF;
 current_pub:=item_supply_internal.private_native_publication_current(r.version_id,r.user_id,r.epoch);
 SELECT * INTO pub FROM tutor_item_supply_private_native_publications WHERE id=(current_pub->>'publication_id')::uuid;
 IF pub.id IS NULL OR pub.pack_task_id<>r.pack_task_id OR pub.scope_id<>r.scope_id OR creation->'content' IS DISTINCT FROM pub.content_json
  OR q->>'owner_version' IS DISTINCT FROM pub.state_version::text
  OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(q->'source_references') x WHERE x->>'kind'='exercise_version'
    AND x->>'reference_id'=pub.exercise_version_id::text AND x->>'content_hash'=current_pub->>'exercise_content_hash') THEN RETURN false; END IF;
 IF r.mode='create' AND (item_supply_internal.private_native_eligibility_current(el.id) IS DISTINCT FROM true
  OR item_supply_internal.private_native_request_matches(q,pub.id) IS DISTINCT FROM true) THEN RETURN false; END IF;
 t:=clock_timestamp();
 RETURN r.checked_at<=t AND t<r.valid_until AND r.valid_until<=r.checked_at+(CASE WHEN is_mvp THEN interval '600 seconds' ELSE interval '30 seconds' END);
END $old582$;
 target_body text;
 birth_actual pg_catalog.pg_proc%ROWTYPE; birth_verified pg_catalog.pg_proc%ROWTYPE;
 birth_definition text; target_birth text;
 old_birth constant text := $birth582$
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
  ('item_supply_internal.private_native_consumer_current(uuid)','8bb09240c9e1b4befdeebcc4ffaa6c6ea36aea018b1365f8cc3070c423921e6e','plpgsql','pg_catalog.bool'::regtype,('pg_catalog.uuid'::regtype::oid::text)::oidvector,ARRAY['rid']::text[],false,true,'v'),
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
END $birth582$;
 expected_birth_attrs constant jsonb := $ba582${"oid":"5380112","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_private_native_binding_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"2200","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$ba582$::jsonb;
 old_consumer_pin constant text := $pinold582$8bb09240c9e1b4befdeebcc4ffaa6c6ea36aea018b1365f8cc3070c423921e6e$pinold582$;
 target_consumer_pin constant text := $pinnew582$67a52de8756643912152c92b0b6af706e5c20ad5a38dfeea46652e8ecf676401$pinnew582$;
 expected_attrs constant jsonb := $attrs582${"oid":"5380106","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"private_native_consumer_current","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["rid"],"proargtypes":["2950"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs582$::jsonb;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off' THEN
  RAISE check_violation USING MESSAGE='582 original isolated writable caller transaction required'; END IF;
 SELECT p.* INTO actual FROM pg_catalog.pg_proc p
  WHERE p.oid='item_supply_internal.private_native_consumer_current(uuid)'::regprocedure;
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs THEN
  RAISE check_violation USING MESSAGE='582 original receiver OID or attributes changed'; END IF;
 IF length(old_body)-length(replace(old_body,';a record;',''))<>length(';a record;') THEN
  RAISE check_violation USING MESSAGE='582 exactly one local Artifact record declaration required'; END IF;
 target_body:=replace(old_body,';a record;',';a public.tutor_learning_artifacts%ROWTYPE;');
 IF length(old_birth)-length(replace(old_birth,old_consumer_pin,''))<>length(old_consumer_pin) THEN
  RAISE check_violation USING MESSAGE='582 exact unique direct birth dependency pin required'; END IF;
 target_birth:=replace(old_birth,old_consumer_pin,target_consumer_pin);
 SELECT p.* INTO birth_actual FROM pg_catalog.pg_proc p
  WHERE p.oid='public.enforce_private_native_binding_insert()'::regprocedure;
 IF NOT FOUND OR (to_jsonb(birth_actual)-'prosrc') IS DISTINCT FROM expected_birth_attrs
  OR (birth_actual.prosrc IS DISTINCT FROM old_birth AND birth_actual.prosrc IS DISTINCT FROM target_birth) THEN
  RAISE check_violation USING MESSAGE='582 original direct birth dependency receiver changed'; END IF;
 IF actual.prosrc IS DISTINCT FROM target_body THEN
 IF actual.prosrc IS DISTINCT FROM old_body THEN
  RAISE check_violation USING MESSAGE='582 original receiver body changed'; END IF;
 definition:=pg_catalog.pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,old_body,''))<>length(old_body) THEN
  RAISE check_violation USING MESSAGE='582 exact original function definition required'; END IF;
 EXECUTE replace(definition,old_body,target_body);
 SELECT p.* INTO verified FROM pg_catalog.pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR verified.prosrc IS DISTINCT FROM target_body THEN
  RAISE check_violation USING MESSAGE='582 exact local rowtype and preserved receiver attributes required'; END IF;
 END IF;
 IF birth_actual.prosrc IS DISTINCT FROM target_birth THEN
  birth_definition:=pg_catalog.pg_get_functiondef(birth_actual.oid);
  IF length(birth_definition)-length(replace(birth_definition,old_birth,''))<>length(old_birth) THEN
   RAISE check_violation USING MESSAGE='582 exact original direct birth function definition required'; END IF;
  EXECUTE replace(birth_definition,old_birth,target_birth);
 END IF;
 SELECT p.* INTO birth_verified FROM pg_catalog.pg_proc p WHERE p.oid=birth_actual.oid;
 IF NOT FOUND OR (to_jsonb(birth_verified)-'prosrc') IS DISTINCT FROM expected_birth_attrs
  OR birth_verified.prosrc IS DISTINCT FROM target_birth THEN
  RAISE check_violation USING MESSAGE='582 exact direct birth pin and preserved receiver attributes required'; END IF;
 -- Existing birth protocol pin, not a new completion checksum.
 IF (SELECT encode(public.digest(p.prosrc,'sha256'),'hex') FROM pg_catalog.pg_proc p
     WHERE p.oid='item_supply_internal.private_native_consumer_current(uuid)'::regprocedure)
   IS DISTINCT FROM target_consumer_pin THEN
  RAISE check_violation USING MESSAGE='582 consumer to direct birth dependency pin mismatch'; END IF;
END;
$rowtype582$;
