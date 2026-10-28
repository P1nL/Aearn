-- 581: accept only the existing canonical PRIVATE handle at the original receipt CHECK.
-- NULL/PUBLIC and all authority/sibling/birth contracts are unchanged; <=580 frozen.
DO $handle581$
DECLARE
 actual pg_catalog.pg_constraint%ROWTYPE;
 verified pg_catalog.pg_constraint%ROWTYPE;
 definition text;
 old_definition constant text := $old581$CHECK (((artifact_handle IS NULL) OR (artifact_handle ~ '^li:[0-9a-f]{64}$'::text)))$old581$;
 target_definition constant text := $target581$CHECK (((artifact_handle IS NULL) OR (artifact_handle ~ '^li:[0-9a-f]{64}$'::text) OR (artifact_handle ~ '^lip:v2:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'::text)))$target581$;
BEGIN
 IF current_database() IS DISTINCT FROM 'aearn_b1d_sandbox_20261001'
  OR current_user IS DISTINCT FROM 'aearn_b1d_runtime_20261001'
  OR current_setting('transaction_isolation') IS DISTINCT FROM 'read committed'
  OR current_setting('transaction_read_only') IS DISTINCT FROM 'off' THEN
  RAISE check_violation USING MESSAGE='581 original isolated writable caller transaction required'; END IF;
 LOCK TABLE public.tutor_teaching_action_receipts IN ACCESS EXCLUSIVE MODE;
 IF (SELECT count(*) FROM pg_catalog.pg_constraint c
  WHERE c.conrelid='public.tutor_teaching_action_receipts'::regclass
   AND c.conname='chk_tutor_teaching_action_receipts_artifact_handle')<>1 THEN
  RAISE check_violation USING MESSAGE='581 unique original handle CHECK required'; END IF;
 SELECT c.* INTO actual FROM pg_catalog.pg_constraint c
  WHERE c.conrelid='public.tutor_teaching_action_receipts'::regclass
   AND c.conname='chk_tutor_teaching_action_receipts_artifact_handle';
 IF NOT FOUND OR actual.connamespace IS DISTINCT FROM 'public'::regnamespace
  OR actual.contype<>'c' OR NOT actual.convalidated OR actual.condeferrable OR actual.condeferred
  OR actual.conkey IS DISTINCT FROM ARRAY[23]::smallint[]
  OR actual.contypid<>0 OR actual.conindid<>0 OR actual.conparentid<>0
  OR NOT actual.conislocal OR actual.coninhcount<>0 OR actual.connoinherit
  OR COALESCE((to_jsonb(actual)->>'conenforced')::boolean,true) IS DISTINCT FROM true
  OR NOT EXISTS (SELECT 1 FROM pg_catalog.pg_attribute a
   WHERE a.attrelid=actual.conrelid AND a.attnum=23 AND a.attname='artifact_handle'
    AND a.atttypid='pg_catalog.text'::regtype AND NOT a.attisdropped AND NOT a.attnotnull) THEN
  RAISE check_violation USING MESSAGE='581 original handle CHECK attributes changed'; END IF;
 definition:=pg_catalog.pg_get_constraintdef(actual.oid,false);
 -- Complete attributes precede exact-target replay; unknown definitions never mutate.
 IF definition IS NOT DISTINCT FROM target_definition THEN RETURN; END IF;
 IF definition IS DISTINCT FROM old_definition THEN
  RAISE check_violation USING MESSAGE='581 original handle CHECK definition changed'; END IF;
 ALTER TABLE public.tutor_teaching_action_receipts
  DROP CONSTRAINT chk_tutor_teaching_action_receipts_artifact_handle;
 ALTER TABLE public.tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_artifact_handle CHECK (
   artifact_handle IS NULL OR artifact_handle ~ '^li:[0-9a-f]{64}$'
   OR artifact_handle ~ '^lip:v2:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
  );
 SELECT c.* INTO verified FROM pg_catalog.pg_constraint c
  WHERE c.conrelid=actual.conrelid AND c.conname=actual.conname;
 IF NOT FOUND OR verified.oid=actual.oid
  OR (to_jsonb(verified)-ARRAY['oid','conbin']) IS DISTINCT FROM (to_jsonb(actual)-ARRAY['oid','conbin'])
  OR pg_catalog.pg_get_constraintdef(verified.oid,false) IS DISTINCT FROM target_definition THEN
  RAISE check_violation USING MESSAGE='581 exact target handle CHECK or preserved attributes failed'; END IF;
END;
$handle581$;
