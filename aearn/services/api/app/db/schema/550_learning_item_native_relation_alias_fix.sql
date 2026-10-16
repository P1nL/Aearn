-- Exact installed native relation receiver: two query-local aliases only.
-- No new capability, source policy, root/phase/lease, author separation or request-hash change.
-- Caller owns the isolated sandbox transaction and installation serialization.
DO $fix550$
DECLARE
 actual record; verified record; source text; repaired text; definition text; i integer;
 old_sha constant text := '55c745fb1cfef2ff22dd9db4b95252a58771f3d942901f04549e654ba735c2af';
 new_sha constant text := '70194b777ae1860df750c87e62b278360601842d98c6c9a4011defeba02dbb51';
 old_expressions constant text[] := ARRAY[
  $old550$jsonb_array_elements(p->'contents') c WHERE c->>'author_id'=actor$old550$,
  $old550$jsonb_array_elements(p->'contents') c
       WHERE c->>'version_id'=NEW.anchor_version_id::text$old550$
 ];
 new_expressions constant text[] := ARRAY[
  $new550$jsonb_array_elements(p->'contents') AS content_author(value) WHERE content_author.value->>'author_id'=actor$new550$,
  $new550$jsonb_array_elements(p->'contents') AS content_anchor(value)
       WHERE content_anchor.value->>'version_id'=NEW.anchor_version_id::text$new550$
 ];
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='550 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid=to_regprocedure('public.enforce_native_type_evidence_insert()');
 IF NOT FOUND OR actual.oid<>5357713 OR actual.proowner<>5313402 OR actual.prolang<>13629 OR actual.pronamespace<>2200
  OR actual.proname IS DISTINCT FROM 'enforce_native_type_evidence_insert'
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef
  OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.trigger'::regtype
  OR actual.pronargs<>0 OR actual.proargtypes IS DISTINCT FROM ''::oidvector OR actual.proargnames IS NOT NULL
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0
  OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL OR actual.prosqlbody IS NOT NULL OR actual.protrftypes IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='550 original receiver identity/authority attributes changed'; END IF;
 source:=actual.prosrc;
 -- Exact replay is allowed only after all original metadata checks.
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='550 original receiver source changed'; END IF;
 repaired:=source;
 FOR i IN 1..2 LOOP
  IF length(source)-length(replace(source,old_expressions[i],''))<>length(old_expressions[i])
  THEN RAISE check_violation USING MESSAGE='550 original receiver alias occurrence changed'; END IF;
  repaired:=replace(repaired,old_expressions[i],new_expressions[i]);
 END LOOP;
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='550 exact query-local alias repair hash required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,actual.prosrc,''))<>length(actual.prosrc)
 THEN RAISE check_violation USING MESSAGE='550 original receiver definition framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,repaired);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='550 receiver metadata/OID/owner/ACL or fixed body changed'; END IF;
END $fix550$;
