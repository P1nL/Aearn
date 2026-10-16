-- Exact installed revision generation guard: compare against the frozen CHILD request.
-- Original candidate/root/request/substantive/deadline checks and metadata remain.
-- Caller owns sandbox installation serialization; no replay/restore authority.
DO $fix540$
DECLARE
 actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='6c1a9399d41d6b4d8974a61c73efa2282bb903bcceaa1eb69146445120dfa1fd';
 new_sha constant text:='f80b9d29e7ac425b840183f14d999cca8da0db71d2e22fad5877312376d621d4';
 expected_attrs constant jsonb:=$attrs540${"oid":"5374838","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_revision_generation_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs540$::jsonb;
 old_expression constant text:=$old540$NEW.source_json->'blueprint' IS DISTINCT FROM preparation_row.payload_json->'context'->'parent_source'->'blueprint'$old540$;
 new_expression constant text:=$new540$NEW.source_json->'blueprint' IS DISTINCT FROM preparation_row.payload_json->'request'->'blueprint'$new540$;
BEGIN
 IF current_database()<>'aearn_b1d_sandbox_20261001'
 THEN RAISE check_violation USING MESSAGE='540 B1d only'; END IF;
 SELECT p.* INTO actual FROM pg_proc p
 WHERE p.oid=to_regprocedure('item_supply_internal.enforce_revision_generation_insert()');
 IF NOT FOUND THEN RAISE check_violation USING MESSAGE='540 original receiver missing'; END IF;
 IF (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='540 original receiver OID/owner/ACL/attributes changed'; END IF;
 source:=actual.prosrc;
 -- Idempotent replay accepts only the fixed body AND exact original metadata.
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
  OR length(source)-length(replace(source,old_expression,''))<>length(old_expression)
 THEN RAISE check_violation USING MESSAGE='540 exact original receiver body/expression required'; END IF;
 repaired:=replace(source,old_expression,new_expression);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='540 exact frozen child blueprint repair required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='540 original definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='540 receiver metadata or fixed body changed'; END IF;
END $fix540$;
