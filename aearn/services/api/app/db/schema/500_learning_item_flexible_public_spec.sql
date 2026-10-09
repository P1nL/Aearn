-- New finite V3 presentation fence only. No rows, tables, leases, source
-- permissions, publication authority or historical schema bytes are changed.
CREATE OR REPLACE FUNCTION item_supply_internal.shared_public_template_matches(
  request_payload jsonb, source_public jsonb, target_id text
) RETURNS boolean LANGUAGE plpgsql IMMUTABLE
SET search_path=pg_catalog,pg_temp AS $helper$
DECLARE blueprint jsonb; template jsonb; payload jsonb; field_name text;
  expected_instruction text; actual_instruction text;
  core_start CONSTANT text := '### finite-public-task-v3:start';
  core_end CONSTANT text := '### finite-public-task-v3:end';
BEGIN
  -- Not STRICT: SQL NULL, JSON null, absent templates and malformed envelopes
  -- return false rather than SQL NULL (or the old optional-template bypass).
  IF jsonb_typeof(request_payload) IS DISTINCT FROM 'object'
    OR jsonb_typeof(source_public) IS DISTINCT FROM 'object'
    OR (target_id IN ('python-state-update-v1','python-kc-binding-v1','sqlite-predicate-order-v1')) IS DISTINCT FROM true THEN
    RETURN false;
  END IF;
  blueprint:=request_payload->'blueprint';
  template:=request_payload->'public_template';
  IF jsonb_typeof(blueprint) IS DISTINCT FROM 'object'
    OR blueprint->>'schema_version' IS DISTINCT FROM 'learning_item_blueprint_v1'
    OR jsonb_typeof(blueprint->'version') IS DISTINCT FROM 'string'
    OR length(blueprint->>'version') NOT BETWEEN 1 AND 160
    OR jsonb_typeof(template) IS DISTINCT FROM 'object' THEN
    RETURN false;
  END IF;
  FOREACH payload IN ARRAY ARRAY[template,source_public] LOOP
    FOREACH field_name IN ARRAY ARRAY['schema_version','item_key','version','kind',
      'purpose','difficulty','title','instruction_markdown'] LOOP
      IF jsonb_typeof(payload->field_name) IS DISTINCT FROM 'string'
        OR length(payload->>field_name)=0 THEN RETURN false; END IF;
    END LOOP;
    IF payload->>'schema_version' IS DISTINCT FROM 'learning_item_public_v1'
      OR payload->'item_key' IS DISTINCT FROM request_payload->'item_key'
      OR payload->'version' IS DISTINCT FROM request_payload->'version'
      OR payload->'kind' IS DISTINCT FROM blueprint->'item_kind'
      OR payload->'purpose' IS DISTINCT FROM blueprint->'purpose'
      OR payload->>'kind' IS DISTINCT FROM (CASE target_id
        WHEN 'python-state-update-v1' THEN 'code'
        WHEN 'python-kc-binding-v1' THEN 'knowledge_check' ELSE 'sql' END)
      OR length(payload->>'item_key')>160 OR length(payload->>'version')>160
      OR length(payload->>'title')>240 OR length(payload->>'instruction_markdown')>8000
      OR payload->>'difficulty' NOT IN ('D1','D2','D3','D4','D5')
      OR jsonb_typeof(payload->'allowed_interactions') IS DISTINCT FROM 'array'
      OR jsonb_typeof(payload->'source_references') IS DISTINCT FROM 'array'
      OR jsonb_typeof(payload->'content') IS DISTINCT FROM 'object'
      OR jsonb_typeof(payload->'content'->'type') IS DISTINCT FROM 'string'
      OR (payload ? 'hints' AND jsonb_typeof(payload->'hints') IS DISTINCT FROM 'array')
      OR (payload ? 'remediation_item_key' AND jsonb_typeof(payload->'remediation_item_key') NOT IN ('null','string')) THEN
      RETURN false;
    END IF;
    -- Array lengths are evaluated only after the separate type fence above.
    IF jsonb_array_length(payload->'allowed_interactions') NOT BETWEEN 1 AND 6
      OR jsonb_array_length(payload->'source_references') NOT BETWEEN 1 AND 12
      OR (payload->'kind' IN ('"code"'::jsonb,'"knowledge_check"'::jsonb)
        AND payload->'content'->'type' IS DISTINCT FROM payload->'kind')
      OR (payload->>'kind'='sql' AND payload->'content'->>'type' NOT IN ('sql','sql_v2')) THEN
      RETURN false;
    END IF;
  END LOOP;
  -- The request blueprint, not a source-only field, selects the new contract.
  -- 489 still binds actual blueprint==request, target/control/root and hashes.
  IF blueprint->>'version'='finite-public-spec-v3' THEN
    expected_instruction:=template->>'instruction_markdown';
    actual_instruction:=source_public->>'instruction_markdown';
    -- Presentation may surround the canonical task, never replace, edit or
    -- duplicate it. Same markers/count semantics as the V3 Python field fence.
    IF left(expected_instruction,length(core_start)) IS DISTINCT FROM core_start
      OR right(expected_instruction,length(core_end)) IS DISTINCT FROM core_end
      OR (length(expected_instruction)-length(replace(expected_instruction,core_start,'')))/length(core_start)<>1
      OR (length(expected_instruction)-length(replace(expected_instruction,core_end,'')))/length(core_end)<>1
      OR (length(actual_instruction)-length(replace(actual_instruction,core_start,'')))/length(core_start)<>1
      OR (length(actual_instruction)-length(replace(actual_instruction,core_end,'')))/length(core_end)<>1
      OR (length(actual_instruction)-length(replace(actual_instruction,expected_instruction,'')))/length(expected_instruction)<>1 THEN
      RETURN false;
    END IF;
    RETURN (template - ARRAY['title','instruction_markdown']) =
      (source_public - ARRAY['title','instruction_markdown']);
  END IF;
  -- V1/V2 and unknown versions retain complete public-template equality.
  RETURN template=source_public;
END $helper$;
REVOKE ALL ON FUNCTION item_supply_internal.shared_public_template_matches(jsonb,jsonb,text) FROM PUBLIC;

-- Pin the complete effective 489 body after the exact 491 original-generation
-- lookup transition. Any additional upstream mutation requires a reviewed new
-- migration, not a best-effort partial rewrite. prosrc includes its LF framing.
DO $migration$
DECLARE function_oid oid; body text; definition text; revised_body text;
  baseline_md5 CONSTANT text := '61e922b19614a40c5e53a65995ab5793';
  revised_md5 CONSTANT text := '07047f3dd91453ee9942cf951a3fc499';
  old_clause CONSTANT text := '(NEW.request_json->>''public_template'' IS NOT NULL AND NEW.request_json->''public_template'' IS DISTINCT FROM NEW.source_json->''public'')';
  new_clause CONSTANT text := 'item_supply_internal.shared_public_template_matches(NEW.request_json,NEW.source_json->''public'',NEW.target_id) IS DISTINCT FROM true';
BEGIN
  function_oid:=to_regprocedure('public.enforce_item_supply_shared_pipeline_artifact()');
  IF function_oid IS NULL THEN
    RAISE check_violation USING MESSAGE='500 requires the effective 489+491 shared pipeline guard';
  END IF;
  SELECT p.prosrc INTO body FROM pg_proc p WHERE p.oid=function_oid
    AND p.prorettype='pg_catalog.trigger'::regtype AND p.prosecdef
    AND p.prolang=(SELECT oid FROM pg_language WHERE lanname='plpgsql')
    AND p.proconfig=ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp'];
  IF NOT FOUND THEN
    RAISE check_violation USING MESSAGE='500 unexpected shared pipeline function attributes';
  END IF;
  IF md5(body)=revised_md5 THEN
    RETURN; -- Applying 500 alone again leaves the effective guard unchanged.
  END IF;
  IF md5(body) IS DISTINCT FROM baseline_md5
    OR (length(body)-length(replace(body,old_clause,'')))/length(old_clause)<>1 THEN
    RAISE check_violation USING MESSAGE='500 unexpected 489+491 shared pipeline prosrc baseline';
  END IF;
  revised_body:=replace(body,old_clause,new_clause);
  IF md5(revised_body) IS DISTINCT FROM revised_md5 THEN
    RAISE check_violation USING MESSAGE='500 unexpected revised shared pipeline prosrc';
  END IF;
  definition:=pg_get_functiondef(function_oid);
  IF (length(definition)-length(replace(definition,old_clause,'')))/length(old_clause)<>1 THEN
    RAISE check_violation USING MESSAGE='500 expected one public-template clause';
  END IF;
  EXECUTE replace(definition,old_clause,new_clause);
  IF (SELECT md5(prosrc) FROM pg_proc WHERE oid=function_oid) IS DISTINCT FROM revised_md5 THEN
    RAISE check_violation USING MESSAGE='500 shared pipeline prosrc verification failed';
  END IF;
END $migration$;
