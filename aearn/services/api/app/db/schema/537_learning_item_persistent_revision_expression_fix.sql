-- Exact installed family receiver: four parentheses-only JSONB subtraction fixes.
-- No recovery/replay authority, history mutation, new object or grant.
-- Caller owns the isolated sandbox transaction and installation serialization.
DO $fix537$
DECLARE
 actual record; verified record; source text; repaired text; definition text; i integer;
 old_sha constant text := '8df23b08aee40c277a320efa8df047d279250944d89157342349253aad83026b';
 new_sha constant text := '9a2376a15e47517a2229da3456184e2e497d9cd736dc6f7856533bf81e2e84b6';
 old_expressions constant text[] := ARRAY[
  $old537$(spec->'blueprint'-ARRAY['blueprint_key','version'])$old537$,
  $old537$(parent->'specification'->'blueprint'-ARRAY['blueprint_key','version'])$old537$,
  $old537$(spec->'public_template'-ARRAY['item_key','version','title','content','instruction_markdown'])$old537$,
  $old537$(parent->'specification'->'public_template'-ARRAY['item_key','version','title','content','instruction_markdown'])$old537$];
 new_expressions constant text[] := ARRAY[
  $new537$((spec->'blueprint')-ARRAY['blueprint_key','version'])$new537$,
  $new537$((parent->'specification'->'blueprint')-ARRAY['blueprint_key','version'])$new537$,
  $new537$((spec->'public_template')-ARRAY['item_key','version','title','content','instruction_markdown'])$new537$,
  $new537$((parent->'specification'->'public_template')-ARRAY['item_key','version','title','content','instruction_markdown'])$new537$];
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='537 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid=to_regprocedure('item_supply_internal.persistent_registered_family_revision_matches(jsonb)');
 IF NOT FOUND OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef
  OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.bool'::regtype
  OR actual.pronargs<>1 OR actual.proargnames IS DISTINCT FROM ARRAY['p']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0
  OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL OR actual.prosqlbody IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='537 original receiver identity/authority attributes changed'; END IF;
 source:=actual.prosrc;
 -- Replay accepts the exact fixed body only AFTER the same attribute checks.
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='537 original receiver source changed'; END IF;
 repaired:=source;
 FOR i IN 1..4 LOOP
  IF length(source)-length(replace(source,old_expressions[i],''))<>length(old_expressions[i])
  THEN RAISE check_violation USING MESSAGE='537 original receiver expression changed'; END IF;
  repaired:=replace(repaired,old_expressions[i],new_expressions[i]);
 END LOOP;
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='537 exact parentheses repair hash required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,actual.prosrc,''))<>length(actual.prosrc)
 THEN RAISE check_violation USING MESSAGE='537 original receiver definition framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,repaired);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='537 receiver metadata/OID/owner/ACL or fixed body changed'; END IF;
END $fix537$;
