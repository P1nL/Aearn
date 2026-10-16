-- Exact SQL450 cap CHECK correction, only explicit disabled non-model caps0.
-- Model/candidate/round caps remain positive; original resource-kind closed sets,
-- private ownership/FKs, all other checks and PRIVATE551 cap1 semantics stay intact.
-- Caller owns the isolated transaction; no row/window/usage update or commit.
DO $fix553$
DECLARE
 target record; actual record; verified record; cap_column record; resource_column record;
 table_id oid; definition text; new_columns smallint[];
 old_definition constant text := 'CHECK ((cap_amount > 0))';
 new_definition constant text := $new553$CHECK (((cap_amount > 0) OR ((cap_amount = 0) AND (resource_kind = ANY (ARRAY['execution_seconds'::text, 'fetches'::text])))))$new553$;
BEGIN
 -- Acquire only the two ALTER targets before inspecting their exact definitions,
 -- so a concurrent schema writer cannot change a check between guard and replace.
 LOCK TABLE public.tutor_item_supply_runtime_global_limits,
  public.tutor_item_supply_private_runtime_user_limits IN ACCESS EXCLUSIVE MODE;
 FOR target IN SELECT * FROM (VALUES
   ('tutor_item_supply_runtime_global_limits','tutor_item_supply_runtime_global_limits_cap_amount_check'),
   ('tutor_item_supply_private_runtime_user_limits','tutor_item_supply_private_runtime_user_limits_cap_amount_check')
  ) AS targets(table_name,constraint_name)
 LOOP
  table_id:=pg_catalog.to_regclass(format('public.%I',target.table_name));
  SELECT a.* INTO cap_column FROM pg_catalog.pg_attribute a
   WHERE a.attrelid=table_id AND a.attname='cap_amount' AND a.attnum>0 AND NOT a.attisdropped;
  IF NOT FOUND OR cap_column.atttypid IS DISTINCT FROM 'pg_catalog.int8'::regtype OR NOT cap_column.attnotnull
  THEN RAISE check_violation USING MESSAGE='553 original cap column identity changed'; END IF;
  SELECT a.* INTO resource_column FROM pg_catalog.pg_attribute a
   WHERE a.attrelid=table_id AND a.attname='resource_kind' AND a.attnum>0 AND NOT a.attisdropped;
  IF NOT FOUND OR resource_column.atttypid IS DISTINCT FROM 'pg_catalog.text'::regtype OR NOT resource_column.attnotnull
  THEN RAISE check_violation USING MESSAGE='553 original resource column identity changed'; END IF;
  new_columns:=ARRAY[LEAST(cap_column.attnum,resource_column.attnum),
   GREATEST(cap_column.attnum,resource_column.attnum)]::smallint[];
  SELECT c.* INTO actual FROM pg_catalog.pg_constraint c
   WHERE c.conrelid=table_id AND c.conname=target.constraint_name;
  IF NOT FOUND OR actual.contype<>'c' OR NOT actual.convalidated OR actual.connoinherit
   OR actual.condeferrable OR actual.condeferred OR NOT actual.conislocal
   OR actual.coninhcount<>0 OR actual.conparentid<>0
  THEN RAISE check_violation USING MESSAGE='553 original named validated cap CHECK changed'; END IF;
  definition:=pg_catalog.pg_get_constraintdef(actual.oid,false);
  IF definition IS NOT DISTINCT FROM new_definition THEN
   IF (SELECT array_agg(k ORDER BY k) FROM unnest(actual.conkey) AS keys(k)) IS DISTINCT FROM new_columns
   THEN RAISE check_violation USING MESSAGE='553 corrected cap CHECK column binding changed'; END IF;
   CONTINUE;
  END IF;
  IF definition IS DISTINCT FROM old_definition
   OR actual.conkey IS DISTINCT FROM ARRAY[cap_column.attnum]::smallint[]
  THEN RAISE check_violation USING MESSAGE='553 original cap CHECK definition/binding changed'; END IF;
  EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I',target.table_name,target.constraint_name);
  -- ADD CHECK is validated immediately, under the same caller transaction/lock.
  EXECUTE format('ALTER TABLE public.%I ADD CONSTRAINT %I %s',
   target.table_name,target.constraint_name,new_definition);
  SELECT c.* INTO verified FROM pg_catalog.pg_constraint c
   WHERE c.conrelid=table_id AND c.conname=target.constraint_name;
  IF NOT FOUND OR pg_catalog.pg_get_constraintdef(verified.oid,false) IS DISTINCT FROM new_definition
   OR (SELECT array_agg(k ORDER BY k) FROM unnest(verified.conkey) AS keys(k)) IS DISTINCT FROM new_columns
   OR (to_jsonb(verified)-ARRAY['oid','conbin','conkey']) IS DISTINCT FROM
      (to_jsonb(actual)-ARRAY['oid','conbin','conkey'])
  THEN RAISE check_violation USING MESSAGE='553 cap CHECK name/validation/metadata or corrected definition changed'; END IF;
 END LOOP;
END $fix553$;
