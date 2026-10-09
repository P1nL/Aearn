-- B1d-only native PUBLIC validation staging. No private scope, second job/budget,
-- bank publication, formal Attempt, admission facts or seal rehydration.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_validation_preparations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL, root_id uuid NOT NULL,
  lease_owner text NOT NULL, lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
  generation_artifact_id uuid NOT NULL, item_id uuid NOT NULL, version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  reservation_key text CHECK(reservation_key ~ '^shared[.]execution[.][0-9a-f]{32}$'),
  resources_json jsonb,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,generation_artifact_id), UNIQUE(job_id,reservation_key),
  CHECK((resources_json IS NULL)=(reservation_key IS NULL)),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(generation_artifact_id,job_id,lease_generation,item_id,version_id,source_hash,content_hash)
    REFERENCES tutor_item_supply_shared_generation_artifacts(id,job_id,lease_generation,item_id,version_id,source_hash,content_hash) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_validation_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  preparation_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_validation_preparations(id) ON DELETE RESTRICT,
  reservation_id uuid REFERENCES tutor_item_supply_shared_reservations(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION item_supply_internal.shared_validation_current(p tutor_item_supply_shared_validation_preparations)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE c record; t timestamptz; snapshot jsonb;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RETURN false; END IF;
  SELECT c1.*,j.root_id,pr.profile_hash INTO c FROM tutor_item_supply_shared_job_controls c1
    JOIN tutor_item_supply_shared_jobs j ON j.id=c1.job_id
    JOIN tutor_item_supply_parameter_profiles pr ON pr.id=c1.profile_id
    WHERE c1.job_id=p.job_id FOR SHARE OF c1;
  t:=clock_timestamp();
  IF NOT FOUND THEN RETURN false; END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  RETURN c.state='leased' AND c.root_id=p.root_id AND c.profile_hash=p.profile_hash
    AND c.lease_owner=p.lease_owner AND c.lease_generation=p.lease_generation AND c.state_version=p.lease_state_version
    AND c.lease_expires_at>t AND c.parent_deadline>t
    AND snapshot=p.payload_json->'lease'->'profile'
    AND (p.resources_json IS NULL OR (p.resources_json->>'execution_seconds')::bigint*1000
      <=(snapshot->'values'->>'stage_deadline_ms')::bigint);
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.shared_validation_current(tutor_item_supply_shared_validation_preparations) FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_shared_validation_preparation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE a record; p jsonb:=NEW.payload_json; r jsonb:=NEW.resources_json;
BEGIN
  IF item_supply_internal.shared_validation_current(NEW) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared validation current lease required';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id OR p->>'artifact_id' IS DISTINCT FROM a.id::text
    OR p->>'artifact_hash' IS DISTINCT FROM a.artifact_hash OR p->'request' IS DISTINCT FROM a.request_json
    OR p->>'source_hash' IS DISTINCT FROM a.source_hash OR p->>'content_hash' IS DISTINCT FROM a.content_hash
    OR p->'lease'->>'visibility' IS DISTINCT FROM 'public'
    OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
    OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
    OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
    OR p->'inputs'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'inputs'->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR p->'inputs'->>'target_id' IS DISTINCT FROM a.target_id
    OR p->'inputs'->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR p->'inputs'->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'spec')
    OR p->'spec'->'public_template' IS DISTINCT FROM a.request_json->'public_template'
    OR p->'spec'->'blueprint' IS DISTINCT FROM a.request_json->'blueprint'
    OR p->'resources' IS DISTINCT FROM COALESCE(r,'null'::jsonb) THEN
    RAISE check_violation USING MESSAGE='shared validation artifact identity mismatch';
  END IF;
  IF r IS NULL THEN
    IF a.target_id<>'python-kc-binding-v1' OR p->'inputs'->'probe_plan' IS DISTINCT FROM 'null'::jsonb
      OR p->'inputs'->'static_facts'->>'execution_status' IS DISTINCT FROM 'not_run_static'
      OR p->'inputs'->'static_facts'->'validation'->>'mode' IS DISTINCT FROM 'static' THEN
      RAISE check_violation USING MESSAGE='shared static validation shape required';
    END IF;
  ELSE
    IF a.target_id='python-kc-binding-v1' OR NEW.reservation_key IS DISTINCT FROM ('shared.execution.'||replace(NEW.id::text,'-',''))
      OR jsonb_typeof(r) IS DISTINCT FROM 'object' OR (r->>'execution_seconds') !~ '^[1-9][0-9]{0,7}$'
      OR (r->>'execution_seconds')::bigint NOT BETWEEN 1 AND 31536000
      OR r-'execution_seconds' IS DISTINCT FROM '{"requests":0,"input_tokens":0,"output_tokens":0,"fetches":0,"candidates":0,"revision_rounds":0,"investigation_rounds":0}'::jsonb
      OR jsonb_typeof(p->'inputs'->'probe_plan') IS DISTINCT FROM 'object'
      OR p->'inputs'->'static_facts' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE check_violation USING MESSAGE='shared execution-only resource shape required';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_validation_preparation() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_shared_validation_prepare ON tutor_item_supply_shared_validation_preparations;
CREATE TRIGGER supply_shared_validation_prepare BEFORE INSERT ON tutor_item_supply_shared_validation_preparations
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_validation_preparation();

-- Existing provider reservations retain their positive headers. Only this exact
-- shared preparation can admit execution-only zero HTTP/token headers.
ALTER TABLE tutor_item_supply_shared_reservations DROP CONSTRAINT IF EXISTS tutor_item_supply_shared_reservations_requests_check;
ALTER TABLE tutor_item_supply_shared_reservations ADD CONSTRAINT tutor_item_supply_shared_reservations_requests_check CHECK(requests>=0);
ALTER TABLE tutor_item_supply_shared_reservations DROP CONSTRAINT IF EXISTS tutor_item_supply_shared_reservations_tokens_check;
ALTER TABLE tutor_item_supply_shared_reservations ADD CONSTRAINT tutor_item_supply_shared_reservations_tokens_check CHECK(tokens>=0);
CREATE OR REPLACE FUNCTION enforce_item_supply_shared_execution_header() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p tutor_item_supply_shared_validation_preparations;
BEGIN
  IF NEW.requests>0 AND NEW.tokens>0 THEN RETURN NEW; END IF;
  SELECT * INTO p FROM tutor_item_supply_shared_validation_preparations WHERE job_id=NEW.job_id
    AND root_id=NEW.root_id AND lease_generation=NEW.lease_generation AND reservation_key=NEW.reservation_key;
  IF NOT FOUND OR p.resources_json IS NULL OR NEW.requests<>0 OR NEW.tokens<>0 OR NEW.resources<>0
    OR item_supply_internal.shared_validation_current(p) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='zero header requires current shared execution preparation';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_execution_header() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_shared_execution_header ON tutor_item_supply_shared_reservations;
CREATE TRIGGER supply_shared_execution_header BEFORE INSERT ON tutor_item_supply_shared_reservations
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_execution_header();

CREATE OR REPLACE FUNCTION enforce_item_supply_shared_execution_allocation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record; p tutor_item_supply_shared_validation_preparations;
BEGIN
  IF NEW.reservation_namespace<>'shared' THEN RETURN NEW; END IF;
  SELECT * INTO r FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id;
  IF NOT FOUND OR r.requests>0 OR r.tokens>0 THEN RETURN NEW; END IF;
  SELECT * INTO p FROM tutor_item_supply_shared_validation_preparations WHERE job_id=r.job_id AND reservation_key=r.reservation_key;
  IF NOT FOUND OR item_supply_internal.shared_validation_current(p) IS DISTINCT FROM true
    OR NEW.reserved_amount IS DISTINCT FROM (p.resources_json->>NEW.resource_kind)::bigint THEN
    RAISE check_violation USING MESSAGE='shared execution allocation mismatch';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_execution_allocation() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_shared_execution_allocation ON tutor_item_supply_runtime_global_reservation_amounts;
CREATE TRIGGER supply_shared_execution_allocation BEFORE INSERT ON tutor_item_supply_runtime_global_reservation_amounts
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_execution_allocation();

CREATE OR REPLACE FUNCTION enforce_item_supply_shared_validation_evidence() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p tutor_item_supply_shared_validation_preparations; r record; s record;
  v jsonb:=NEW.payload_json->'validation'; terminals jsonb:=NEW.payload_json->'terminals'; terminal jsonb;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared validation B1d only';
  END IF;
  SELECT * INTO p FROM tutor_item_supply_shared_validation_preparations WHERE id=NEW.preparation_id;
  IF NOT FOUND OR NEW.payload_json->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR jsonb_typeof(terminals) IS DISTINCT FROM 'array' THEN
    RAISE check_violation USING MESSAGE='shared validation evidence shape invalid';
  END IF;
  IF p.resources_json IS NULL THEN
    IF NEW.reservation_id IS NOT NULL OR terminals<>'[]'::jsonb
      OR NEW.payload_json->'actual' IS DISTINCT FROM 'null'::jsonb
      OR v IS DISTINCT FROM p.payload_json->'inputs'->'static_facts'->'validation'
      OR item_supply_internal.shared_validation_current(p) IS DISTINCT FROM true THEN
      RAISE check_violation USING MESSAGE='static evidence cannot manufacture execution';
    END IF;
  ELSE
    -- Settlement survives a lost live lease/source. It is never a commit fence.
    SELECT * INTO r FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id
      AND job_id=p.job_id AND root_id=p.root_id AND lease_generation=p.lease_generation AND reservation_key=p.reservation_key;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared execution reservation unavailable'; END IF;
    SELECT * INTO s FROM tutor_item_supply_shared_runtime_settlements WHERE reservation_id=r.id
      AND settlement_key=p.reservation_key ORDER BY sequence DESC LIMIT 1;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared execution settlement required'; END IF;
    IF v='null'::jsonb THEN
      IF s.usage_state<>'unknown' OR NEW.payload_json->'actual' IS DISTINCT FROM 'null'::jsonb OR terminals<>'[]'::jsonb THEN
        RAISE check_violation USING MESSAGE='unknown execution usage must stay unknown';
      END IF;
    ELSE
      IF s.usage_state<>'known' OR jsonb_typeof(v) IS DISTINCT FROM 'object'
        OR v->>'schema_version' IS DISTINCT FROM 'candidate_validation_v2'
        OR v->>'source_hash' IS DISTINCT FROM p.source_hash OR v->>'content_hash' IS DISTINCT FROM p.content_hash
        OR v->>'mode' IS DISTINCT FROM 'live'
        OR v->'execution_evidence'->>'mode' IS DISTINCT FROM 'live'
        OR v->'execution_evidence'->>'isolation' IS DISTINCT FROM 'approved_os_boundary'
        OR jsonb_array_length(terminals) NOT BETWEEN 1 AND 32
        OR s.receipt_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object('receipts',terminals)) THEN
        RAISE check_violation USING MESSAGE='shared execution terminal evidence mismatch';
      END IF;
      FOR terminal IN SELECT value FROM jsonb_array_elements(terminals) LOOP
        IF terminal->>'run_id' IS DISTINCT FROM v->'execution_evidence'->>'run_id'
          OR terminal->>'mode' IS DISTINCT FROM 'live'
          OR terminal->>'isolation' IS DISTINCT FROM 'approved_os_boundary'
          OR terminal->>'lock_fingerprint' IS DISTINCT FROM p.payload_json->'spec'->'coverage_blueprint'->'scope'->>'runtime_profile_hash' THEN
          RAISE check_violation USING MESSAGE='shared execution runtime identity mismatch';
        END IF;
      END LOOP;
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_validation_evidence() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_shared_validation_evidence ON tutor_item_supply_shared_validation_evidence;
CREATE TRIGGER supply_shared_validation_evidence BEFORE INSERT ON tutor_item_supply_shared_validation_evidence
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_validation_evidence();

DO $$ DECLARE table_name text; BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_validation_preparations','tutor_item_supply_shared_validation_evidence'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_mutation ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''shared'')',table_name);
  END LOOP;
END $$;
