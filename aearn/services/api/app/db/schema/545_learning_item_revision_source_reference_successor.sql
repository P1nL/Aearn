-- Original source-successor citations only; v1/v2 and historical rows are unchanged.
-- THREE existing receiver bodies only; no new objects, grants or history updates.
DO $$ BEGIN IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='545 original sandbox only'; END IF; END $$;

DO $receiver545_0$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='8073e7bd96c64337cc7f9d4b1b2138d6e6e0c350bc3f5246baded2415916d850'; new_sha constant text:='25044674cc353a88a66ca595ec21b4f39cb04b5208b1c6daebe50db5b9ea2c8e';
 expected_attrs constant jsonb:=$attrs545${"oid":"5390386","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"fresh_committed_revision_matches","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["p"],"proargtypes":["3802"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs545$::jsonb;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.fresh_committed_revision_matches(jsonb)');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='545 exact installed receiver metadata required'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='545 exact installed receiver body required'; END IF;
 repaired:=source;
 IF length(repaired)-length(replace(repaired,$old545_0$p->'context'->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'$old545_0$,''))<>length($old545_0$p->'context'->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'$old545_0$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_0$p->'context'->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'$old545_0$,$new545_0$p->'context'->>'schema_version' IS DISTINCT FROM (CASE WHEN e.payload_json ? 'source_successor_id'
   THEN 'native_revision_author_context_v3' ELSE 'native_revision_author_context_v2' END)$new545_0$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='545 exact source citation body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='545 original definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='545 original metadata/body preservation failed'; END IF;
END $receiver545_0$;

DO $receiver545_1$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='503f44abd9500e210eeaf6fbd2750cc86d0c7122d3d68fca972d6eb158d9e2d6'; new_sha constant text:='b11320c5f781e34f0b962e73b3d91ea313502fd6cd0da30acb84a0d3d20dfbe5';
 expected_attrs constant jsonb:=$attrs545${"oid":"5374836","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"enforce_native_revision_insert","prorows":0,"pronargs":0,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"2279","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":null,"proargtypes":[],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs545$::jsonb;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.enforce_native_revision_insert()');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='545 exact installed receiver metadata required'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='545 exact installed receiver body required'; END IF;
 repaired:=source;
 IF length(repaired)-length(replace(repaired,$old545_0$IF p->'context'->>'schema_version'='native_revision_author_context_v2' THEN$old545_0$,''))<>length($old545_0$IF p->'context'->>'schema_version'='native_revision_author_context_v2' THEN$old545_0$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_0$IF p->'context'->>'schema_version'='native_revision_author_context_v2' THEN$old545_0$,$new545_0$IF p->'context'->>'schema_version' IN('native_revision_author_context_v2','native_revision_author_context_v3') THEN$new545_0$);
 IF length(repaired)-length(replace(repaired,$old545_1$(CASE WHEN family_permission THEN 'native_revision_author_context_v2' ELSE 'native_revision_author_context_v1' END)$old545_1$,''))<>length($old545_1$(CASE WHEN family_permission THEN 'native_revision_author_context_v2' ELSE 'native_revision_author_context_v1' END)$old545_1$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_1$(CASE WHEN family_permission THEN 'native_revision_author_context_v2' ELSE 'native_revision_author_context_v1' END)$old545_1$,$new545_1$(CASE WHEN family_permission AND source_permission THEN 'native_revision_author_context_v3'
      WHEN family_permission THEN 'native_revision_author_context_v2' ELSE 'native_revision_author_context_v1' END)$new545_1$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='545 exact source citation body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='545 original definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='545 original metadata/body preservation failed'; END IF;
END $receiver545_1$;

-- Family body reconstructed byte-exactly against actual installed539 definition SHA;
-- old/new body and complete installed metadata are required, not inferred permissions.
DO $receiver545_2$
DECLARE actual record; verified record; source text; repaired text; definition text;
 old_sha constant text:='d26c59f1019cfcbdd2b1ac95bec4f3b60659f19c7600df2d7c2e31e432436cd0'; new_sha constant text:='9262b89bbabebedc7a91fa7e6636a463751dfbc24aae1d745cd5463e572405e1';
 expected_attrs constant jsonb:=$attrs545${"oid":"5380149","proacl":["aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001"],"probin":null,"procost":100,"prokind":"f","prolang":"13629","proname":"persistent_registered_family_revision_matches","prorows":0,"pronargs":1,"proowner":"5313402","proconfig":["search_path=pg_catalog, public, item_supply_internal, pg_temp"],"proretset":false,"prosecdef":true,"prorettype":"16","prosqlbody":null,"prosupport":"-","proargmodes":null,"proargnames":["p"],"proargtypes":["3802"],"proisstrict":false,"proparallel":"u","protrftypes":null,"provariadic":"0","provolatile":"v","proleakproof":false,"pronamespace":"5321183","proallargtypes":null,"proargdefaults":null,"pronargdefaults":0}$attrs545$::jsonb;
BEGIN
 SELECT p.* INTO actual FROM pg_proc p WHERE p.oid=to_regprocedure('item_supply_internal.persistent_registered_family_revision_matches(jsonb)');
 IF NOT FOUND OR (to_jsonb(actual)-'prosrc') IS DISTINCT FROM expected_attrs
 THEN RAISE check_violation USING MESSAGE='545 exact installed receiver metadata required'; END IF;
 source:=actual.prosrc;
 IF encode(sha256(convert_to(source,'UTF8')),'hex')=new_sha THEN RETURN; END IF;
 IF encode(sha256(convert_to(source,'UTF8')),'hex') IS DISTINCT FROM old_sha
 THEN RAISE check_violation USING MESSAGE='545 exact installed receiver body required'; END IF;
 repaired:=source;
 IF length(repaired)-length(replace(repaired,$old545_0$ c jsonb:=p->'context'; matched boolean:=false;$old545_0$,''))<>length($old545_0$ c jsonb:=p->'context'; matched boolean:=false;$old545_0$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_0$ c jsonb:=p->'context'; matched boolean:=false;$old545_0$,$new545_0$ source_permission boolean:=false; comparison_blueprint jsonb; comparison_public jsonb;
 expected_refs jsonb:='[]'::jsonb; citation_coordinate jsonb; citation_ref jsonb;
 c jsonb:=p->'context'; matched boolean:=false;$new545_0$);
 IF length(repaired)-length(replace(repaired,$old545_1$IF NOT FOUND OR item_supply_internal.snapshot_keys(c$old545_1$,''))<>length($old545_1$IF NOT FOUND OR item_supply_internal.snapshot_keys(c$old545_1$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_1$IF NOT FOUND OR item_supply_internal.snapshot_keys(c$old545_1$,$new545_1$IF NOT FOUND THEN RETURN false; END IF;
 source_permission:=item_supply_internal.revision_source_successor_matches(p);
 comparison_blueprint:=parent->'specification'->'blueprint';
 comparison_public:=parent->'specification'->'public_template';
 IF source_permission THEN
  -- Exact finite factory citation projection from the actual543-bound materials.
  FOR citation_coordinate IN SELECT value->'binding'->'evidence'->0 FROM jsonb_array_elements(req->'materials') LOOP
   citation_ref:=jsonb_build_object('source_id',citation_coordinate->'binding'->'source_handle',
    'source_version',citation_coordinate->'binding'->'document_revision',
    'locator',citation_coordinate->'chunk_id','content_hash',citation_coordinate->'binding'->'document_hash');
   IF EXISTS(SELECT 1 FROM jsonb_array_elements(expected_refs) AS refs(value)
    WHERE (refs.value->'source_id',refs.value->'source_version',refs.value->'locator')
      IS NOT DISTINCT FROM (citation_ref->'source_id',citation_ref->'source_version',citation_ref->'locator')
     AND refs.value IS DISTINCT FROM citation_ref) THEN RETURN false; END IF;
   IF NOT (expected_refs @> jsonb_build_array(citation_ref)) THEN expected_refs:=expected_refs||jsonb_build_array(citation_ref); END IF;
  END LOOP;
  IF expected_refs='[]'::jsonb OR spec->'blueprint'->'source_references' IS DISTINCT FROM expected_refs
   OR spec->'public_template'->'source_references' IS DISTINCT FROM expected_refs THEN RETURN false; END IF;
  comparison_blueprint:=jsonb_set(comparison_blueprint,'{source_references}',expected_refs,false);
  comparison_public:=jsonb_set(comparison_public,'{source_references}',expected_refs,false);
 END IF;
 IF item_supply_internal.snapshot_keys(c$new545_1$);
 IF length(repaired)-length(replace(repaired,$old545_2$c->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'$old545_2$,''))<>length($old545_2$c->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'$old545_2$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_2$c->>'schema_version' IS DISTINCT FROM 'native_revision_author_context_v2'$old545_2$,$new545_2$c->>'schema_version' IS DISTINCT FROM (CASE WHEN source_permission THEN 'native_revision_author_context_v3'
   ELSE 'native_revision_author_context_v2' END)$new545_2$);
 IF length(repaired)-length(replace(repaired,$old545_3$((parent->'specification'->'blueprint')-ARRAY['blueprint_key','version'])$old545_3$,''))<>length($old545_3$((parent->'specification'->'blueprint')-ARRAY['blueprint_key','version'])$old545_3$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_3$((parent->'specification'->'blueprint')-ARRAY['blueprint_key','version'])$old545_3$,$new545_3$(comparison_blueprint-ARRAY['blueprint_key','version'])$new545_3$);
 IF length(repaired)-length(replace(repaired,$old545_4$((parent->'specification'->'public_template')-ARRAY['item_key','version','title','content','instruction_markdown'])$old545_4$,''))<>length($old545_4$((parent->'specification'->'public_template')-ARRAY['item_key','version','title','content','instruction_markdown'])$old545_4$)
 THEN RAISE check_violation USING MESSAGE='545 exact source citation anchor required'; END IF;
 repaired:=replace(repaired,$old545_4$((parent->'specification'->'public_template')-ARRAY['item_key','version','title','content','instruction_markdown'])$old545_4$,$new545_4$(comparison_public-ARRAY['item_key','version','title','content','instruction_markdown'])$new545_4$);
 IF encode(sha256(convert_to(repaired,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='545 exact source citation body required'; END IF;
 definition:=pg_get_functiondef(actual.oid);
 IF length(definition)-length(replace(definition,source,''))<>length(source)
 THEN RAISE check_violation USING MESSAGE='545 original definition framing changed'; END IF;
 EXECUTE replace(definition,source,repaired);
 SELECT p.* INTO verified FROM pg_proc p WHERE p.oid=actual.oid;
 IF NOT FOUND OR (to_jsonb(verified)-'prosrc') IS DISTINCT FROM expected_attrs
  OR encode(sha256(convert_to(verified.prosrc,'UTF8')),'hex') IS DISTINCT FROM new_sha
 THEN RAISE check_violation USING MESSAGE='545 original metadata/body preservation failed'; END IF;
END $receiver545_2$;
