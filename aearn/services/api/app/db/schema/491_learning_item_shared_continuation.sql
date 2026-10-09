-- Explicit data-only continuation on the SAME cumulative root. No old deadline,
-- generation row, budget history, source grant or execution seal is renewed.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_candidate_continuations (
  job_id uuid PRIMARY KEY,
  root_id uuid NOT NULL,
  generation_artifact_id uuid NOT NULL,
  original_job_id uuid NOT NULL,
  original_lease_generation integer NOT NULL CHECK(original_lease_generation>0),
  item_id uuid NOT NULL, version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  operation_key text NOT NULL CHECK(operation_key ~ '^[a-z0-9][a-z0-9._:-]{0,79}$'),
  binding_json jsonb NOT NULL CHECK(jsonb_typeof(binding_json)='object' AND octet_length(binding_json::text)<=65536
    AND (binding_json->>'schema_version') IS NOT DISTINCT FROM 'shared_candidate_continuation_v1'),
  binding_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(binding_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK(job_id<>original_job_id),
  UNIQUE(root_id,generation_artifact_id,operation_key),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(generation_artifact_id,original_job_id,original_lease_generation,item_id,version_id,source_hash,content_hash)
    REFERENCES tutor_item_supply_shared_generation_artifacts(id,job_id,lease_generation,item_id,version_id,source_hash,content_hash) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION enforce_item_supply_shared_candidate_continuation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a record; c record; root_facts record; t timestamptz; snapshot jsonb; b jsonb:=NEW.binding_json;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared continuation B1d owner required';
  END IF;
  SELECT c1.*,j.root_id,j.parent_job_id,j.job_key,p.profile_hash,p.profile_json INTO c
    FROM tutor_item_supply_shared_job_controls c1 JOIN tutor_item_supply_shared_jobs j ON j.id=c1.job_id
    JOIN tutor_item_supply_parameter_profiles p ON p.id=c1.profile_id
    WHERE c1.job_id=NEW.job_id FOR UPDATE OF c1;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation job unavailable'; END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.parent_job_id IS NOT NULL
    OR c.lease_owner IS DISTINCT FROM b->'adoption_lease'->>'lease_owner'
    OR c.lease_generation::text IS DISTINCT FROM b->'adoption_lease'->>'generation'
    OR c.state_version::text IS DISTINCT FROM b->'adoption_lease'->>'state_version'
    OR c.lease_expires_at IS NULL OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM b->'adoption_lease'->'profile'
    OR c.profile_hash IS DISTINCT FROM snapshot->>'profile_hash'
    OR c.job_key IS DISTINCT FROM encode(digest(convert_to(NEW.root_id::text||chr(31)||
        'continue.'||replace(NEW.generation_artifact_id::text,'-','')||'.'||NEW.operation_key,'UTF8'),'sha256'),'hex') THEN
    RAISE check_violation USING MESSAGE='continuation current new-job lease mismatch';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id THEN
    RAISE check_violation USING MESSAGE='continuation must retain original canonical root';
  END IF;
  SELECT r.canonical_key,bp.blueprint_hash,o.provider_key INTO root_facts
    FROM tutor_item_supply_shared_budget_roots r JOIN tutor_item_supply_shared_blueprints bp ON bp.id=r.blueprint_id
    JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id WHERE r.id=NEW.root_id FOR SHARE OF r,bp,o;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='continuation root unavailable'; END IF;
  IF b->>'root_id' IS DISTINCT FROM NEW.root_id::text OR b->>'generation_artifact_id' IS DISTINCT FROM a.id::text
    OR b->>'original_job_id' IS DISTINCT FROM a.job_id::text
    OR b->>'original_lease_generation' IS DISTINCT FROM a.lease_generation::text
    OR b->>'candidate_id' IS DISTINCT FROM a.candidate_id::text OR b->>'item_id' IS DISTINCT FROM a.item_id::text
    OR b->>'version_id' IS DISTINCT FROM a.version_id::text OR b->>'source_hash' IS DISTINCT FROM a.source_hash
    OR b->>'content_hash' IS DISTINCT FROM a.content_hash OR b->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR b->>'target_id' IS DISTINCT FROM a.target_id OR b->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR b->>'operation_key' IS DISTINCT FROM NEW.operation_key
    OR b->>'canonical_root_key' IS DISTINCT FROM root_facts.canonical_key
    OR b->>'coverage_blueprint_hash' IS DISTINCT FROM root_facts.blueprint_hash
    OR b->>'scope_hash' IS DISTINCT FROM a.request_json->>'scope_hash'
    OR b->>'original_profile_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_hash'
    OR b->>'original_request_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json)
    OR b->>'material_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.request_json->'materials')
    OR b->>'source_receipt_set_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(a.receipt_json->'sources')
    OR b->'adoption_lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR b->'adoption_lease'->>'visibility' IS DISTINCT FROM 'public'
    OR b->'adoption_lease'->'owner_id' IS DISTINCT FROM 'null'::jsonb
    OR b->'adoption_lease'->'owner_epoch' IS DISTINCT FROM 'null'::jsonb
    OR snapshot->>'profile_key_hash' IS DISTINCT FROM a.request_json->'profile'->>'profile_key_hash'
    OR c.profile_json->'profile_key'->>'provider' IS DISTINCT FROM root_facts.provider_key
    OR a.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
    OR b->>'authority' IS DISTINCT FROM 'immutable_generation_data_only'
    OR b->'execution_authority_reusable' IS DISTINCT FROM 'false'::jsonb
    OR b->'publication_enabled' IS DISTINCT FROM 'false'::jsonb THEN
    RAISE check_violation USING MESSAGE='continuation immutable original binding mismatch';
  END IF;
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id
      AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash)
    OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=a.reservation_id
      AND s.settlement_key='generation.'||replace(a.candidate_id::text,'-','')) THEN
    RAISE check_violation USING MESSAGE='continuation requires complete settled original generation';
  END IF;
  IF EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts WHERE job_id=NEW.job_id)
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints WHERE job_id=NEW.job_id AND stage='generating')
    OR EXISTS(SELECT 1 FROM tutor_item_supply_shared_reservations WHERE job_id=NEW.job_id AND reservation_key LIKE 'gen.%') THEN
    RAISE check_violation USING MESSAGE='continuation cannot masquerade as new generation';
  END IF;
  RETURN NEW;
END $$;

-- Connected stage data boundary. Old rows remain immutable; only nullable
-- provenance columns/constraints are added. Source currency is rechecked by the
-- concrete C owner in resolve_generation before preparation/receipt/checkpoint.
ALTER TABLE tutor_item_supply_shared_pipeline_receipts ADD COLUMN IF NOT EXISTS continuation_binding_hash text;
ALTER TABLE tutor_item_supply_shared_validation_preparations ADD COLUMN IF NOT EXISTS continuation_binding_hash text;

CREATE OR REPLACE FUNCTION item_supply_internal.shared_continuation_generation_inherited(operation_job uuid)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT current_database()='aearn_b1d_sandbox_20261001' AND EXISTS(
    SELECT 1 FROM tutor_item_supply_shared_candidate_continuations x
    JOIN tutor_item_supply_shared_jobs j ON j.id=x.job_id AND j.root_id=x.root_id
    JOIN tutor_item_supply_shared_generation_artifacts a ON a.id=x.generation_artifact_id
      AND a.job_id=x.original_job_id AND a.lease_generation=x.original_lease_generation
      AND a.root_id=x.root_id AND a.item_id=x.item_id AND a.version_id=x.version_id
      AND a.source_hash=x.source_hash AND a.content_hash=x.content_hash
    JOIN tutor_item_supply_shared_budget_roots r ON r.id=x.root_id
    JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id
    JOIN tutor_item_supply_shared_job_controls c ON c.job_id=x.job_id
    JOIN tutor_item_supply_parameter_profiles p ON p.id=c.profile_id
    WHERE x.job_id=operation_job AND x.original_job_id<>x.job_id AND j.parent_job_id IS NULL
      AND c.state='leased' AND c.lease_expires_at>clock_timestamp() AND c.parent_deadline>clock_timestamp()
      AND x.binding_json->>'artifact_hash'=a.artifact_hash
      AND x.binding_json->>'canonical_root_key'=r.canonical_key
      AND x.binding_json->>'coverage_blueprint_hash'=b.blueprint_hash
      AND x.binding_json->>'original_request_hash'=item_supply_internal.snapshot_hash(a.request_json)
      AND x.binding_json->'adoption_lease'->'profile'->>'profile_hash'=p.profile_hash
      AND (CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
        THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END)=x.binding_json->'adoption_lease'->'profile'
      AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_checkpoints cp WHERE cp.job_id=a.job_id
        AND cp.lease_generation=a.lease_generation AND cp.stage='generating' AND cp.status='completed' AND cp.receipt_hash=a.artifact_hash)
      AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements s WHERE s.reservation_id=a.reservation_id
        AND s.settlement_key='generation.'||replace(a.candidate_id::text,'-',''))
  )
$$;
REVOKE ALL ON FUNCTION item_supply_internal.shared_continuation_generation_inherited(uuid) FROM PUBLIC;

-- Completion entrance only: BEFORE UPDATE still reads the stored leased control.
-- Preserve 450's ordinary/private seven-checkpoint branch and original lease gate.
-- A continuation additionally needs its exact adoption and all SIX actual stages;
-- no checkpoint is inserted and no completed/publication read gains a live-lease gate.
DO $$ DECLARE definition text; old_guard text; new_guard text; BEGIN
  definition:=pg_get_functiondef('enforce_item_supply_runtime_control()'::regprocedure);
  old_guard:='IF completed_count<>7 OR OLD.state<>''leased'' OR OLD.lease_expires_at<=clock_timestamp() THEN';
  new_guard:=$guard$IF (completed_count<>7 AND NOT (
      NOT namespace_private AND completed_count=6
      AND item_supply_internal.shared_continuation_generation_inherited(NEW.job_id) IS TRUE
      AND (SELECT count(DISTINCT cp.stage) FROM tutor_item_supply_shared_checkpoints cp
        WHERE cp.job_id=NEW.job_id AND cp.status='completed'
          AND cp.stage IN ('validating','reviewing','investigating','revising','simulating','admitting'))=6
    )) OR OLD.state<>'leased' OR OLD.lease_expires_at<=clock_timestamp() THEN$guard$;
  IF strpos(definition,new_guard)>0 THEN NULL;
  ELSIF strpos(definition,old_guard)=0 THEN
    RAISE check_violation USING MESSAGE='491 expected exact 450 completion guard transition';
  ELSE
    EXECUTE replace(definition,old_guard,new_guard);
  END IF;
END $$;

CREATE OR REPLACE FUNCTION item_supply_internal.shared_stage_original_matches(
  operation_job uuid, operation_generation integer, artifact_id uuid, adoption_hash text)
RETURNS boolean LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT EXISTS(SELECT 1 FROM tutor_item_supply_shared_generation_artifacts a
    JOIN tutor_item_supply_shared_jobs j ON j.id=operation_job AND j.root_id=a.root_id
    WHERE a.id=artifact_id AND (
      (a.job_id=operation_job AND a.lease_generation=operation_generation AND adoption_hash IS NULL
        AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=operation_job))
      OR (adoption_hash IS NOT NULL AND item_supply_internal.shared_continuation_generation_inherited(operation_job)
        AND EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations x
          WHERE x.job_id=operation_job AND x.generation_artifact_id=a.id AND x.binding_hash=adoption_hash
            AND x.original_job_id=a.job_id AND x.original_lease_generation=a.lease_generation))))
$$;
REVOKE ALL ON FUNCTION item_supply_internal.shared_stage_original_matches(uuid,integer,uuid,text) FROM PUBLIC;

-- Retain a real original-artifact FK and enforce ALL former composite fields
-- below. The cross-job alternative additionally needs the exact adoption hash.
DO $$ DECLARE tbl text; fk record; constraint_name text; BEGIN
  FOREACH tbl IN ARRAY ARRAY['tutor_item_supply_shared_pipeline_receipts','tutor_item_supply_shared_validation_preparations'] LOOP
    FOR fk IN SELECT conname FROM pg_constraint WHERE conrelid=tbl::regclass AND contype='f'
      AND confrelid='tutor_item_supply_shared_generation_artifacts'::regclass LOOP
      EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I',tbl,fk.conname);
    END LOOP;
    constraint_name:=CASE WHEN tbl='tutor_item_supply_shared_pipeline_receipts' THEN 'shared_receipt_original_artifact_fk'
      ELSE 'shared_validation_original_artifact_fk' END;
    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY(generation_artifact_id) REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT',tbl,constraint_name);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION enforce_item_supply_shared_stage_original() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a record; x record;
BEGIN
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR NEW.item_id<>a.item_id OR NEW.version_id<>a.version_id
    OR NEW.source_hash<>a.source_hash OR NEW.content_hash<>a.content_hash
    OR item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,
       NEW.generation_artifact_id,NEW.continuation_binding_hash) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared stage original coordinates or adoption mismatch';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_validation_preparations' THEN
    IF NEW.root_id<>a.root_id THEN RAISE check_violation USING MESSAGE='shared continuation root mismatch'; END IF;
    IF NEW.continuation_binding_hash IS NULL THEN
      IF NEW.payload_json ? 'continuation_binding_hash' THEN
        RAISE check_violation USING MESSAGE='unexpected continuation preparation binding';
      END IF;
    ELSE
      SELECT * INTO x FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=NEW.job_id;
      IF NEW.payload_json->>'continuation_binding_hash' IS DISTINCT FROM NEW.continuation_binding_hash
        OR NEW.payload_json->'inputs'->>'specification_hash' IS DISTINCT FROM x.binding_json->>'specification_hash' THEN
        RAISE check_violation USING MESSAGE='continued validation preparation binding mismatch';
      END IF;
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_stage_original() FROM PUBLIC;
DO $$ DECLARE tbl text; BEGIN
  FOREACH tbl IN ARRAY ARRAY['tutor_item_supply_shared_pipeline_receipts','tutor_item_supply_shared_validation_preparations'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_continuation_original ON %I',tbl);
    EXECUTE format('CREATE TRIGGER supply_continuation_original BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_stage_original()',tbl);
  END LOOP;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_candidate_continuation() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_shared_continuation ON tutor_item_supply_shared_candidate_continuations;
CREATE TRIGGER supply_shared_continuation BEFORE INSERT ON tutor_item_supply_shared_candidate_continuations
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_candidate_continuation();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_candidate_continuations;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_candidate_continuations
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');

CREATE OR REPLACE FUNCTION deny_item_supply_continuation_generation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_candidate_continuations WHERE job_id=NEW.job_id) THEN RETURN NEW; END IF;
  IF TG_TABLE_NAME='tutor_item_supply_shared_reservations' THEN
    IF NEW.reservation_key NOT LIKE 'gen.%' THEN RETURN NEW; END IF;
  ELSIF TG_TABLE_NAME='tutor_item_supply_shared_checkpoints' THEN
    IF NEW.stage<>'generating' THEN RETURN NEW; END IF;
  END IF;
  RAISE check_violation USING MESSAGE='continuation reuses data and cannot issue generation';
END $$;
REVOKE ALL ON FUNCTION deny_item_supply_continuation_generation() FROM PUBLIC;

-- Transition the one 489 receipt lookup, preserving every other author/live
-- lease/schema guard. Historical 489/490 source bytes and all old rows stay put.
-- Refuse an unexpected upstream function shape rather than weakening its guard.
DO $$ DECLARE definition text; old_lookup text; new_lookup text; BEGIN
  definition:=pg_get_functiondef('enforce_item_supply_shared_pipeline_artifact()'::regprocedure);
  old_lookup:='SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id'||chr(10)||'      AND job_id=NEW.job_id AND lease_generation=NEW.lease_generation;';
  new_lookup:='SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id AND item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,NEW.generation_artifact_id,NEW.continuation_binding_hash);';
  IF strpos(definition,new_lookup)>0 THEN NULL;
  ELSIF strpos(definition,old_lookup)=0 THEN
    RAISE check_violation USING MESSAGE='491 expected exact 489 receipt lookup transition';
  ELSE
    EXECUTE replace(definition,old_lookup,new_lookup);
  END IF;
END $$;
DO $$ DECLARE table_name text; BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_generation_artifacts','tutor_item_supply_shared_reservations','tutor_item_supply_shared_checkpoints'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_continuation_no_generation ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_continuation_no_generation BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION deny_item_supply_continuation_generation()',table_name);
  END LOOP;
END $$;
