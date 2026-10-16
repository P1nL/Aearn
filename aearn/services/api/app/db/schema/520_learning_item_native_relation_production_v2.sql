-- STAGED ONLY. Closed opt-in relation production-v2; legacy501 default preserved.
-- Caller owns transaction. No tables/rows/holds/grants/leases or old SQL changed.
-- Exact501 body plus two closed edits; unknown installed body/attributes reject.
DO $upgrade$
DECLARE
  actual record; verified record; source text; source_hash text; revised text; definition text;
  baseline_sha256 constant text := '5cc1858e2162073e3d5e93dbf5d68f2d639bdafedb52bc807d15ad10bff6cc4c';
  revised_sha256 constant text := '204c682ae3e58565e25f9f8099500f7a96f67ddc59b5fc08229bb404f1b0927b';
  old_protocol constant text := $old_protocol$       OR report->'run'->>'prompt_version' IS DISTINCT FROM 'native-content-relation-v1'$old_protocol$;
  new_protocol constant text := $new_protocol$       OR ((report->'run'->>'prompt_version'='native-content-relation-v1' AND NOT(p ? 'production_config'))
         OR (report->'run'->>'prompt_version'='native-content-relation-production-v2'
           AND p->'production_config'=$v2_config${"api_style":"responses","capture_provider_body":false,"max_http_attempts":1,"max_output_tokens":61440,"model":"deepseek-flash","prompt_version":"native-content-relation-production-v2","protocol":"production-v2","provider":"deepseek","reasoning_effort":"high","schema_hash":"3c556fc6484ca87c14b2e07306ca3c70cce8469848243b661a2fdec76ea7d5b5","temperature":null,"thinking_mode":"enabled","wire_schema_name":"native_content_relation_production_output_v2"}$v2_config$::jsonb
           AND NEW.payload_json->'production_config'=p->'production_config'
           AND NEW.payload_json->>'production_envelope_hash'=p->>'production_envelope_hash'
           AND COALESCE(p->>'production_envelope_hash','') ~ '^[0-9a-f]{64}$'
           AND report->'run'->'max_output_tokens'='61440'::jsonb
           AND (report->'run'->>'timeout_seconds')::numeric>0
           AND (report->'run'->>'timeout_seconds')::numeric*1000<=(p->'lease'->'profile'->'values'->>'request_timeout_ms')::numeric
           AND report->'run'->'provider_identity'->>'provider'='deepseek'
           AND report->'run'->'provider_identity'->>'model'='deepseek-flash')) IS DISTINCT FROM true$new_protocol$;
  old_frame constant text := $old_frame$ ELSE
   p:=NEW.payload_json;
   IF (p->>'evidence_valid_until')$old_frame$;
  new_frame constant text := $new_frame$ ELSE
   p:=NEW.payload_json;
   IF p ? 'production_config' THEN
     IF p->'production_config' IS DISTINCT FROM $v2_config${"api_style":"responses","capture_provider_body":false,"max_http_attempts":1,"max_output_tokens":61440,"model":"deepseek-flash","prompt_version":"native-content-relation-production-v2","protocol":"production-v2","provider":"deepseek","reasoning_effort":"high","schema_hash":"3c556fc6484ca87c14b2e07306ca3c70cce8469848243b661a2fdec76ea7d5b5","temperature":null,"thinking_mode":"enabled","wire_schema_name":"native_content_relation_production_output_v2"}$v2_config$::jsonb
       OR COALESCE(p->>'production_envelope_hash','') !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p->'role_envelope_hashes') IS DISTINCT FROM 'object'
       OR item_supply_internal.snapshot_keys(p->'role_envelope_hashes',ARRAY['curriculum','technical','ambiguity','adversarial']) IS DISTINCT FROM true
       OR EXISTS(SELECT 1 FROM jsonb_each(p->'role_envelope_hashes') h WHERE jsonb_typeof(h.value) IS DISTINCT FROM 'string' OR (h.value#>>'{}') !~ '^[0-9a-f]{64}$')
       OR item_supply_internal.snapshot_keys(p->'identities',ARRAY['curriculum','technical','ambiguity','adversarial']) IS DISTINCT FROM true
       OR jsonb_typeof(p->'resources'->'input_tokens') IS DISTINCT FROM 'number'
       OR COALESCE(p->'resources'->>'input_tokens','') !~ '^[0-9]+$'
       OR COALESCE((p->'resources'->>'input_tokens')::bigint,0) NOT BETWEEN 1 AND 1048576
       OR p->'resources' IS DISTINCT FROM jsonb_build_object('requests',4,'input_tokens',p->'resources'->'input_tokens',
         'output_tokens',245760,'execution_seconds',0,'fetches',0,'candidates',0,'revision_rounds',0,'investigation_rounds',0)
       OR EXISTS(SELECT 1 FROM jsonb_each(p->'identities') i WHERE i.value->>'provider' IS DISTINCT FROM 'deepseek' OR i.value->>'model' IS DISTINCT FROM 'deepseek-flash') THEN
       RAISE check_violation USING MESSAGE='520 relation production exact protocol resources required';
     END IF;
     FOR c IN SELECT jsonb_build_object('kind',key,'amount',value) FROM jsonb_each(p->'resources') LOOP
       IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
         WHERE ra.reservation_namespace='shared' AND ra.reservation_id=NEW.reservation_id
           AND ra.resource_kind=(c->>'kind') AND ra.reserved_amount=(c->>'amount')::bigint)
         OR EXISTS(SELECT 1 FROM tutor_item_supply_runtime_global_reservation_amounts ra
           WHERE ra.reservation_namespace='shared' AND ra.reservation_id=NEW.reservation_id
             AND ra.resource_kind=(c->>'kind') AND ra.reserved_amount<>(c->>'amount')::bigint) THEN
         RAISE check_violation USING MESSAGE='520 relation production original resource reservation required';
       END IF;
     END LOOP;
   END IF;
   IF (p->>'evidence_valid_until')$new_frame$;
BEGIN
  SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
    WHERE p.oid=to_regprocedure('public.enforce_native_type_evidence_insert()');
  IF NOT FOUND OR actual.prokind<>'f' OR actual.lanname<>'plpgsql'
    OR actual.pronargs<>0 OR actual.prorettype<>'pg_catalog.trigger'::regtype OR actual.proretset
    OR actual.proisstrict OR NOT actual.prosecdef OR actual.proleakproof
    OR actual.provolatile<>'v' OR actual.proparallel<>'u'
    OR actual.provariadic<>0 OR actual.pronargdefaults<>0
    OR actual.proargnames IS NOT NULL OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL
    OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
    OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0 THEN
    RAISE check_violation USING MESSAGE='520 relation guard attributes differ from reviewed501';
  END IF;
  source:=replace(actual.prosrc,E'\r\n',E'\n');
  source_hash:=encode(sha256(convert_to(source,'UTF8')),'hex');
  IF source_hash=revised_sha256 THEN RETURN; END IF; -- Replay still checks attributes.
  IF source_hash IS DISTINCT FROM baseline_sha256
    OR (length(source)-length(replace(source,old_protocol,'')))/length(old_protocol)<>1
    OR (length(source)-length(replace(source,old_frame,'')))/length(old_frame)<>1 THEN
    RAISE check_violation USING MESSAGE='520 unknown relation guard body or framing';
  END IF;
  revised:=replace(replace(source,old_protocol,new_protocol),old_frame,new_frame);
  IF encode(sha256(convert_to(revised,'UTF8')),'hex') IS DISTINCT FROM revised_sha256 THEN
    RAISE check_violation USING MESSAGE='520 unexpected relation guard revision';
  END IF;
  definition:=pg_get_functiondef(actual.oid);
  IF (length(definition)-length(replace(definition,actual.prosrc,'')))/length(actual.prosrc)<>1 THEN
    RAISE check_violation USING MESSAGE='520 relation guard definition framing mismatch';
  END IF;
  EXECUTE replace(definition,actual.prosrc,revised);
  SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
  IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
    OR encode(sha256(convert_to(replace(verified.prosrc,E'\r\n',E'\n'),'UTF8')),'hex') IS DISTINCT FROM revised_sha256 THEN
    RAISE check_violation USING MESSAGE='520 relation guard source or attributes not preserved';
  END IF;
END $upgrade$;

