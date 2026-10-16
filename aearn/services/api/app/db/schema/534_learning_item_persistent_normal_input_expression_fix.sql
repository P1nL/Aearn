-- Exact installed530 receiver: parentheses-only JSONB subtraction fix.
-- No recovery authority, history/accounting mutation, new object or grant.
-- Caller owns the isolated sandbox transaction and installation serialization.
DO $fix534$
DECLARE
 actual record; verified record; source text; repaired text; definition text;
 old_sha constant text := '1e4139459d5138c5af7f205a226b0747e27f9dcaaa846acce3a8a41dc66e9401';
 new_sha constant text := 'ff5c3fbe5a46b010f34870d36cfe387e62f212748a1ae7c3694f5004eea0b87e';
 old_expression constant text := $old534$(req->'review_input'-ARRAY['schema_version','binding','role','source','validation_receipt','validation_receipt_hash','scoring_descriptor'])$old534$;
 new_expression constant text := $new534$((req->'review_input')-ARRAY['schema_version','binding','role','source','validation_receipt','validation_receipt_hash','scoring_descriptor'])$new534$;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='534 B1d only'; END IF;
 SELECT p.*,l.lanname INTO actual FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang
 WHERE p.oid=to_regprocedure('item_supply_internal.assert_persistent_normal_repair(jsonb)');
 IF NOT FOUND OR actual.oid<>5380146 OR actual.proowner<>5313402
  OR actual.proowner IS DISTINCT FROM 'aearn_b1d_runtime_20261001'::regrole
  OR actual.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
  OR actual.lanname<>'plpgsql' OR actual.prokind<>'f' OR actual.proretset OR actual.proisstrict OR NOT actual.prosecdef
  OR actual.proleakproof OR actual.provolatile<>'v' OR actual.proparallel<>'u'
  OR actual.prorettype IS DISTINCT FROM 'pg_catalog.void'::regtype
  OR actual.pronargs<>1 OR actual.proargnames IS DISTINCT FROM ARRAY['p']::text[]
  OR actual.proallargtypes IS NOT NULL OR actual.proargmodes IS NOT NULL OR actual.provariadic<>0 OR actual.pronargdefaults<>0
  OR actual.proargdefaults IS NOT NULL OR actual.probin IS NOT NULL OR actual.prosqlbody IS NOT NULL
  OR actual.procost<>100 OR actual.prorows<>0 OR actual.prosupport<>0
  OR actual.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']
 THEN RAISE check_violation USING MESSAGE='534 original receiver identity/authority attributes changed'; END IF;
 source:=actual.prosrc;
 -- Replay accepts the exact fixed body only AFTER the same attribute checks.
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR length(source)-length(replace(source,old_expression,''))<>length(old_expression)
 THEN RAISE check_violation USING MESSAGE='534 original receiver source/expression changed'; END IF;
 repaired:=replace(source,old_expression,new_expression);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='534 exact parentheses repair hash required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,actual.prosrc,''))<>length(actual.prosrc)
 THEN RAISE check_violation USING MESSAGE='534 original receiver definition framing changed'; END IF;
 EXECUTE replace(definition,actual.prosrc,repaired);
 SELECT p.*,l.lanname INTO verified FROM pg_proc p JOIN pg_language l ON l.oid=p.prolang WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM (to_jsonb(actual)-'prosrc')
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='534 receiver metadata/owner/ACL or fixed body changed'; END IF;
END $fix534$;
