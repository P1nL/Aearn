-- 595: one RHS grouping repair in the original 593 closure receiver only.
-- Main's real A candidate raised boolean -> unknown at this expression.
-- <=594 are frozen. Preserve containment direction and every authority fence.
-- Caller owns the TOP: install595 + original A close_execution atomically.
DO $repair595$
DECLARE
  signature constant text := 'item_supply_internal.enforce_persistent_pack_journal_insert()';
  baseline_md5 constant text := 'b93a8df0a058a710ebc93c0b526f86d9';
  revised_md5 constant text := '0564209bcca1c5d8f20b215d46e2f12d';
  old_needle constant text := $old595$@> dp_phase.payload_json->'candidate_version_ids'$old595$;
  new_needle constant text := $new595$@> (dp_phase.payload_json->'candidate_version_ids')$new595$;
  original pg_catalog.pg_proc%ROWTYPE;
  revised pg_catalog.pg_proc%ROWTYPE;
  source text;
  repaired_source text;
  definition text;
BEGIN
  SELECT p.* INTO original FROM pg_catalog.pg_proc p WHERE p.oid=to_regprocedure(signature);
  IF current_database()<>'aearn_b1d_sandbox_20261001'
    OR original.oid IS NULL OR NOT original.prosecdef OR original.prokind<>'f'
    OR original.proowner IS DISTINCT FROM to_regrole('aearn_b1d_runtime_20261001')::oid
    OR original.proacl IS DISTINCT FROM ARRAY['aearn_b1d_runtime_20261001=X/aearn_b1d_runtime_20261001']::aclitem[]
    OR original.provolatile IS DISTINCT FROM 'v'::"char"
    OR original.proparallel IS DISTINCT FROM 'u'::"char"
    OR original.proisstrict IS DISTINCT FROM false
    OR original.proconfig IS DISTINCT FROM ARRAY['search_path=pg_catalog, public, item_supply_internal, pg_temp']::text[] THEN
    RAISE check_violation USING MESSAGE='595 original receiver attributes required';
  END IF;
  source:=original.prosrc;
  IF md5(source)=revised_md5 THEN
    IF (length(source)-length(replace(source,new_needle,'')))/length(new_needle)<>1
      OR strpos(source,old_needle)<>0
      OR md5(replace(source,new_needle,old_needle)) IS DISTINCT FROM baseline_md5 THEN
      RAISE check_violation USING MESSAGE='595 exact revised receiver required for replay';
    END IF;
    RETURN;
  END IF;
  IF md5(source) IS DISTINCT FROM baseline_md5
    OR (length(source)-length(replace(source,old_needle,'')))/length(old_needle)<>1
    OR strpos(source,new_needle)<>0 THEN
    RAISE check_violation USING MESSAGE='595 unknown original receiver body';
  END IF;
  repaired_source:=replace(source,old_needle,new_needle);
  IF md5(repaired_source) IS DISTINCT FROM revised_md5 THEN
    RAISE check_violation USING MESSAGE='595 unexpected RHS grouping repair';
  END IF;
  definition:=pg_get_functiondef(original.oid);
  IF (length(definition)-length(replace(definition,source,'')))/length(source)<>1 THEN
    RAISE check_violation USING MESSAGE='595 original receiver body framing mismatch';
  END IF;
  EXECUTE replace(definition,source,repaired_source);
  SELECT p.* INTO revised FROM pg_catalog.pg_proc p WHERE p.oid=original.oid;
  IF md5(revised.prosrc) IS DISTINCT FROM revised_md5
    OR (to_jsonb(revised)-'prosrc') IS DISTINCT FROM (to_jsonb(original)-'prosrc') THEN
    RAISE check_violation USING MESSAGE='595 receiver body or original metadata changed';
  END IF;
END $repair595$;
