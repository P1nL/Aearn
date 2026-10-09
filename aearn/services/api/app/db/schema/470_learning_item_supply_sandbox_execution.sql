-- P6 private disposable sandbox only. No public runtime or learning authority.
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_execution_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  job_id uuid NOT NULL, root_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version integer NOT NULL CHECK(lease_state_version>0),
  lease_owner text NOT NULL, profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
  generation_artifact_id uuid NOT NULL, version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  actor_namespace text NOT NULL CHECK(actor_namespace=('sandbox.p6.'||user_id::text)),
  reservation_key text NOT NULL CHECK(reservation_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  resources_json jsonb NOT NULL CHECK(jsonb_typeof(resources_json)='object'),
  intent_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(resources_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,reservation_key), UNIQUE(id,user_id,epoch,scope_id),
  FOREIGN KEY(job_id,user_id,epoch,root_id,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,root_id,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,job_id,version_id,content_hash) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_sandbox_runs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, intent_id uuid NOT NULL,
  reservation_id uuid NOT NULL, origin text NOT NULL CHECK(origin IN ('simulation','deterministic_probe')),
  run_json jsonb NOT NULL CHECK(jsonb_typeof(run_json)='object' AND run_json->>'schema_version'='sandbox_run_v2'),
  terminal_json jsonb NOT NULL CHECK(jsonb_typeof(terminal_json)='object' AND octet_length(terminal_json::text)<=1048576),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(terminal_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(intent_id), UNIQUE(id,user_id,epoch,scope_id,origin),
  FOREIGN KEY(intent_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_execution_intents(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_reservations(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_sandbox_observations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  source_run uuid NOT NULL, origin text NOT NULL CHECK(origin IN ('simulation','deterministic_probe')),
  scenario text NOT NULL CHECK(scenario ~ '^[a-z][a-z0-9_]{0,79}$'), attempt integer NOT NULL CHECK(attempt BETWEEN 1 AND 1000000),
  observation_json jsonb NOT NULL CHECK(jsonb_typeof(observation_json)='object' AND octet_length(observation_json::text)<=131072),
  observation_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(observation_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(source_run,scenario,attempt),
  FOREIGN KEY(source_run,user_id,epoch,scope_id,origin) REFERENCES tutor_item_supply_private_sandbox_runs(id,user_id,epoch,scope_id,origin) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION item_supply_internal.check_execution_intent(intent_id uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE i record; c record; a record; t timestamptz;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RETURN false; END IF;
  SELECT * INTO i FROM tutor_item_supply_private_execution_intents WHERE id=intent_id;
  IF NOT FOUND THEN RETURN false; END IF;
  SELECT c1.*,j.root_id,p.profile_hash INTO c FROM tutor_item_supply_private_job_controls c1
    JOIN tutor_item_supply_private_jobs j ON j.id=c1.job_id AND j.user_id=c1.user_id AND j.epoch=c1.epoch AND j.scope_id=c1.scope_id
    JOIN tutor_item_supply_parameter_profiles p ON p.id=c1.profile_id
    WHERE c1.job_id=i.job_id AND c1.user_id=i.user_id AND c1.epoch=i.epoch AND c1.scope_id=i.scope_id FOR SHARE OF c1;
  t:=clock_timestamp();
  IF NOT FOUND OR c.state<>'leased' OR c.lease_generation<>i.lease_generation OR c.state_version<>i.lease_state_version
    OR c.lease_owner<>i.lease_owner OR c.root_id<>i.root_id OR c.profile_hash<>i.profile_hash
    OR c.lease_expires_at<=t OR c.parent_deadline<=t THEN RETURN false; END IF;
  SELECT source_hash,content_hash INTO a FROM tutor_item_supply_private_generation_artifacts
    WHERE id=i.generation_artifact_id AND user_id=i.user_id AND epoch=i.epoch AND scope_id=i.scope_id
      AND job_id=i.job_id AND lease_generation=i.lease_generation AND version_id=i.version_id;
  IF NOT FOUND OR a.source_hash<>i.source_hash OR a.content_hash<>i.content_hash THEN RETURN false; END IF;
  RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.check_execution_intent(uuid) FROM PUBLIC;

CREATE OR REPLACE FUNCTION enforce_item_supply_execution_intent() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE c record; a record; t timestamptz; r jsonb:=NEW.resources_json;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='sandbox database required'; END IF;
  IF NOT EXISTS(SELECT 1 FROM users WHERE id=NEW.user_id AND display_name=NEW.actor_namespace AND deleted_at IS NULL) THEN
    RAISE check_violation USING MESSAGE='synthetic sandbox actor required';
  END IF;
  IF NOT item_supply_internal.snapshot_keys(r,ARRAY['requests','input_tokens','output_tokens','execution_seconds','fetches','candidates','revision_rounds','investigation_rounds'])
    OR (SELECT count(*) FROM jsonb_object_keys(r))<>8
    OR r->'requests' IS DISTINCT FROM '0'::jsonb OR r->'input_tokens' IS DISTINCT FROM '0'::jsonb OR r->'output_tokens' IS DISTINCT FROM '0'::jsonb
    OR r->'fetches' IS DISTINCT FROM '0'::jsonb OR r->'candidates' IS DISTINCT FROM '0'::jsonb
    OR r->'revision_rounds' IS DISTINCT FROM '0'::jsonb OR r->'investigation_rounds' IS DISTINCT FROM '0'::jsonb
    OR jsonb_typeof(r->'execution_seconds') IS DISTINCT FROM 'number'
    OR (r->>'execution_seconds') !~ '^[1-9][0-9]{0,7}$' THEN
    RAISE check_violation USING MESSAGE='execution-only resource shape required';
  END IF;
  SELECT c1.*,j.root_id,p.profile_hash INTO c FROM tutor_item_supply_private_job_controls c1
    JOIN tutor_item_supply_private_jobs j ON j.id=c1.job_id AND j.user_id=c1.user_id AND j.epoch=c1.epoch AND j.scope_id=c1.scope_id
    JOIN tutor_item_supply_parameter_profiles p ON p.id=c1.profile_id
    WHERE c1.job_id=NEW.job_id AND c1.user_id=NEW.user_id AND c1.epoch=NEW.epoch AND c1.scope_id=NEW.scope_id FOR SHARE OF c1;
  t:=clock_timestamp();
  IF NOT FOUND OR c.state<>'leased' OR c.lease_generation<>NEW.lease_generation OR c.state_version<>NEW.lease_state_version
    OR c.lease_owner<>NEW.lease_owner OR c.root_id<>NEW.root_id OR c.profile_hash<>NEW.profile_hash
    OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR (c.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms') IS NULL
    OR (r->>'execution_seconds')::bigint*1000 > (c.profile_snapshot_json->'profile'->'values'->>'stage_deadline_ms')::bigint THEN
    RAISE check_violation USING MESSAGE='execution intent lease mismatch';
  END IF;
  SELECT source_hash,content_hash INTO a FROM tutor_item_supply_private_generation_artifacts
    WHERE id=NEW.generation_artifact_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id
      AND job_id=NEW.job_id AND lease_generation=NEW.lease_generation AND version_id=NEW.version_id;
  IF NOT FOUND OR a.source_hash<>NEW.source_hash OR a.content_hash<>NEW.content_hash THEN
    RAISE check_violation USING MESSAGE='execution intent artifact mismatch';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_execution_intent() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_execution_authority ON tutor_item_supply_private_execution_intents;
CREATE TRIGGER supply_execution_authority BEFORE INSERT ON tutor_item_supply_private_execution_intents FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_execution_intent();

-- Only private execution intents admit zero headers. Shared CHECKs are untouched.
ALTER TABLE tutor_item_supply_private_reservations DROP CONSTRAINT IF EXISTS tutor_item_supply_private_reservations_requests_check;
ALTER TABLE tutor_item_supply_private_reservations ADD CONSTRAINT tutor_item_supply_private_reservations_requests_check CHECK(requests>=0);
ALTER TABLE tutor_item_supply_private_reservations DROP CONSTRAINT IF EXISTS tutor_item_supply_private_reservations_tokens_check;
ALTER TABLE tutor_item_supply_private_reservations ADD CONSTRAINT tutor_item_supply_private_reservations_tokens_check CHECK(tokens>=0);
CREATE OR REPLACE FUNCTION enforce_item_supply_execution_header() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE i record;
BEGIN
  IF NEW.requests>0 AND NEW.tokens>0 THEN RETURN NEW; END IF;
  SELECT * INTO i FROM tutor_item_supply_private_execution_intents
    WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND job_id=NEW.job_id
      AND root_id=NEW.root_id AND lease_generation=NEW.lease_generation AND reservation_key=NEW.reservation_key;
  IF NOT FOUND OR NEW.requests<>0 OR NEW.tokens<>0 OR NEW.resources<>0
    OR NOT item_supply_internal.check_execution_intent(i.id) THEN
    RAISE check_violation USING MESSAGE='zero header requires current private execution intent';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_execution_header() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_execution_header ON tutor_item_supply_private_reservations;
CREATE TRIGGER supply_execution_header BEFORE INSERT ON tutor_item_supply_private_reservations FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_execution_header();

CREATE OR REPLACE FUNCTION enforce_item_supply_execution_allocation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record; i record;
BEGIN
  IF TG_TABLE_NAME='tutor_item_supply_runtime_global_reservation_amounts' THEN
    IF NEW.reservation_namespace<>'private' THEN RETURN NEW; END IF;
  END IF;
  SELECT * INTO r FROM tutor_item_supply_private_reservations WHERE id=NEW.reservation_id;
  IF NOT FOUND OR r.requests>0 OR r.tokens>0 THEN RETURN NEW; END IF;
  SELECT * INTO i FROM tutor_item_supply_private_execution_intents WHERE job_id=r.job_id AND reservation_key=r.reservation_key;
  IF NOT FOUND OR NOT item_supply_internal.check_execution_intent(i.id)
    OR NEW.reserved_amount IS DISTINCT FROM (i.resources_json->>NEW.resource_kind)::bigint THEN
    RAISE check_violation USING MESSAGE='execution resource allocation mismatch';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_execution_allocation() FROM PUBLIC;
DO $$ DECLARE table_name text; BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_private_runtime_reservation_amounts','tutor_item_supply_runtime_global_reservation_amounts'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_execution_allocation ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_execution_allocation BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_execution_allocation()',table_name);
  END LOOP;
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_private_execution_intents','tutor_item_supply_private_sandbox_runs','tutor_item_supply_private_sandbox_observations'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_epoch ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch()',table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS supply_mutation ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''private'')',table_name);
  END LOOP;
END $$;

CREATE OR REPLACE FUNCTION enforce_item_supply_sandbox_terminal() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE i record; r record; value jsonb; terminal jsonb;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RAISE check_violation USING MESSAGE='sandbox database required'; END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_sandbox_runs' THEN
    SELECT * INTO i FROM tutor_item_supply_private_execution_intents WHERE id=NEW.intent_id
      AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_reservations
      WHERE id=NEW.reservation_id AND job_id=i.job_id AND lease_generation=i.lease_generation
        AND reservation_key=i.reservation_key AND user_id=i.user_id AND epoch=i.epoch AND scope_id=i.scope_id)
      OR NEW.run_json->>'source_run' IS DISTINCT FROM NEW.id::text
      OR NEW.run_json->>'namespace' IS DISTINCT FROM i.actor_namespace
      OR NEW.run_json->>'tenant_id' IS DISTINCT FROM i.user_id::text
      OR NEW.run_json->>'origin' IS DISTINCT FROM NEW.origin
      OR NEW.run_json->>'content_hash' IS DISTINCT FROM i.content_hash
      OR NEW.run_json->>'profile_hash' IS DISTINCT FROM i.profile_hash
      OR NEW.run_json->>'scope_hash' IS DISTINCT FROM (SELECT scope_hash FROM tutor_item_supply_private_scopes WHERE id=i.scope_id)
      OR NEW.run_json->>'actor_id' IS NULL OR NEW.run_json->>'actor_id'=i.user_id::text
      OR NEW.run_json->'collector_identity' IS DISTINCT FROM 'null'::jsonb
      OR NEW.run_json->'session_id' IS DISTINCT FROM 'null'::jsonb
      OR jsonb_typeof(NEW.terminal_json->'terminals') IS DISTINCT FROM 'array' THEN
      RAISE check_violation USING MESSAGE='sandbox run identity mismatch';
    END IF;
    FOR value IN SELECT * FROM jsonb_array_elements(NEW.terminal_json->'terminals') LOOP
      IF value->>'schema_version' IS DISTINCT FROM 'sandbox_terminal_receipt_v2'
        OR value->>'source_run' IS DISTINCT FROM NEW.id::text OR value->>'origin' IS DISTINCT FROM NEW.origin
        OR value->>'run_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.run_json)
        OR value->>'authority_kind' NOT IN ('sandbox_executor','sandbox_provider','sandbox_scenario') THEN
        RAISE check_violation USING MESSAGE='sandbox terminal provenance mismatch';
      END IF;
    END LOOP;
  ELSE
    SELECT * INTO r FROM tutor_item_supply_private_sandbox_runs WHERE id=NEW.source_run
      AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND origin=NEW.origin;
    terminal:=NEW.observation_json->'terminal_receipt';
    IF NOT FOUND OR NEW.observation_json->>'schema_version' IS DISTINCT FROM 'sandbox_observation_v2'
      OR NEW.observation_json->'run' IS DISTINCT FROM r.run_json
      OR NEW.observation_json->'collector_receipt' IS DISTINCT FROM 'null'::jsonb
      OR terminal->>'scenario' IS DISTINCT FROM NEW.scenario OR terminal->>'attempt' IS DISTINCT FROM NEW.attempt::text
      OR terminal->>'schema_version' IS DISTINCT FROM 'sandbox_terminal_receipt_v2'
      OR terminal->>'source_run' IS DISTINCT FROM NEW.source_run::text
      OR terminal->>'origin' IS DISTINCT FROM NEW.origin
      OR terminal->>'run_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(r.run_json)
      OR NOT (EXISTS(SELECT 1 FROM jsonb_array_elements(r.terminal_json->'terminals') AS t WHERE t=terminal)
        OR (terminal->>'authority_kind'='sandbox_executor' AND EXISTS(
          SELECT 1 FROM jsonb_array_elements(r.terminal_json->'executor_receipts') AS e
          WHERE terminal->>'evidence_hash'=item_supply_internal.snapshot_hash(e)))) THEN
      RAISE check_violation USING MESSAGE='sandbox observation terminal mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_sandbox_terminal() FROM PUBLIC;
DO $$ DECLARE table_name text; BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_private_sandbox_runs','tutor_item_supply_private_sandbox_observations'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_sandbox_terminal ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_sandbox_terminal BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_sandbox_terminal()',table_name);
  END LOOP;
END $$;

-- Same maintenance capability; new children precede existing parents.
CREATE OR REPLACE FUNCTION purge_item_supply_private(target_user uuid, deleting boolean DEFAULT false)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE new_epoch bigint;
BEGIN
  PERFORM 1 FROM users WHERE id=target_user AND deleted_at IS NULL FOR UPDATE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='supply user unavailable'; END IF;
  INSERT INTO tutor_item_supply_user_epochs(user_id) VALUES(target_user) ON CONFLICT DO NOTHING;
  INSERT INTO item_supply_internal.reset_permits VALUES(txid_current(),target_user);
  UPDATE tutor_item_supply_user_epochs SET epoch=epoch+1,enabled=NOT deleting,updated_at=now() WHERE user_id=target_user RETURNING epoch INTO new_epoch;
  UPDATE tutor_item_supply_private_job_controls SET state='cancelled',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL WHERE user_id=target_user AND state NOT IN ('completed','cancelled','superseded');
  UPDATE tutor_item_supply_private_jobs SET state='cancelled',state_version=state_version+1,lease_owner=NULL,lease_expires_at=NULL,terminal_at=now() WHERE user_id=target_user AND state NOT IN ('completed','failed','cancelled');
  UPDATE tutor_item_supply_private_bindings SET state='invalidated',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  UPDATE tutor_item_supply_private_subscriptions SET state='cancelled',state_version=state_version+1 WHERE user_id=target_user AND state='active';
  DELETE FROM tutor_item_supply_private_sandbox_observations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_sandbox_runs WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_execution_intents WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_pipeline_receipts WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_generation_artifacts WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_runtime_settlement_amounts WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_runtime_settlements WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_runtime_reservation_amounts WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_checkpoints WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_job_controls WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_obligations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_runtime_user_limits WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_subscriptions WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_result_items WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_bindings WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_cache WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_results WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_demands WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_publication_refs WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_admissions WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_proofs WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_observations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_evidence WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_usage_events WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_reservations WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_job_events WHERE user_id=target_user;
  LOOP
    DELETE FROM tutor_item_supply_private_jobs j WHERE j.user_id=target_user AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_jobs c WHERE c.parent_job_id=j.id);
    EXIT WHEN NOT FOUND;
  END LOOP;
  DELETE FROM tutor_item_supply_private_budget_windows WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_budget_roots WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_staging WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_versions WHERE user_id=target_user;
  LOOP
    DELETE FROM tutor_item_supply_private_candidates c WHERE c.user_id=target_user AND NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_candidates child WHERE child.parent_candidate_id=c.id);
    EXIT WHEN NOT FOUND;
  END LOOP;
  DELETE FROM tutor_item_supply_private_materials WHERE user_id=target_user;
  DELETE FROM tutor_item_supply_private_scopes WHERE user_id=target_user;
  DELETE FROM item_supply_internal.reset_permits WHERE transaction_id=txid_current() AND user_id=target_user;
  RETURN new_epoch;
END $$;
REVOKE ALL ON FUNCTION purge_item_supply_private(uuid,boolean) FROM PUBLIC;

-- Preserve P4 artifact fences; add only exact isolated P6 synthetic namespace.
CREATE OR REPLACE FUNCTION enforce_item_supply_pipeline_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE control record; generation_facts record; version_facts record; scope_facts jsonb; scope_hash text; source_snapshot jsonb; expected_content text; expected_schema text;
BEGIN
  IF NEW.mode='synthetic' AND current_database() NOT IN ('aearn_b1b_fixture_20260930','aearn_b1d_sandbox_20261001') THEN
    RAISE check_violation USING MESSAGE='synthetic pipeline outside fixture';
  END IF;
  IF current_database()='aearn_b1d_sandbox_20261001' AND NOT EXISTS(
    SELECT 1 FROM users WHERE id=NEW.user_id AND display_name=('sandbox.p6.'||NEW.user_id::text) AND deleted_at IS NULL) THEN
    RAISE check_violation USING MESSAGE='synthetic sandbox actor required';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_private_job_controls
    WHERE job_id=NEW.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
  IF NOT FOUND OR control.lease_generation<>NEW.lease_generation OR control.state_version<>NEW.lease_state_version
    OR control.state NOT IN ('leased','generating','validating','reviewing','investigating','revising','simulating','admitting')
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp() OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale pipeline artifact lease';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_generation_artifacts' THEN
    source_snapshot:=NEW.source_json;
    SELECT public_json,private_json,candidate_id INTO version_facts FROM tutor_item_supply_private_versions
      WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    SELECT snapshot_json,tutor_item_supply_private_scopes.scope_hash INTO scope_facts,scope_hash FROM tutor_item_supply_private_scopes
      WHERE id=NEW.scope_id AND user_id=NEW.user_id AND epoch=NEW.epoch;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',source_snapshot->'public'->>'item_key','version',source_snapshot->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(source_snapshot->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(source_snapshot->'public'),
      'private_hash',item_supply_internal.snapshot_hash(source_snapshot->'private')));
    IF version_facts.candidate_id IS DISTINCT FROM NEW.candidate_id
      OR version_facts.public_json IS DISTINCT FROM source_snapshot->'public'
      OR version_facts.private_json IS DISTINCT FROM source_snapshot->'private'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(source_snapshot)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM scope_hash
      OR (NEW.mode='live' AND (
        NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
        OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array'
        OR jsonb_array_length(NEW.receipt_json->'sources')=0
        OR EXISTS(SELECT 1 FROM jsonb_array_elements(NEW.receipt_json->'sources') AS s
                  WHERE s->>'mode' IS DISTINCT FROM 'current_authority')))
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.receipt_json->>'candidate_id'
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM NEW.receipt_json->>'scope_hash'
      OR NEW.request_json->'blueprint' IS DISTINCT FROM source_snapshot->'blueprint'
      OR source_snapshot->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope_facts->>'knowledge_key'
      OR source_snapshot->'blueprint'->>'language_id' IS DISTINCT FROM scope_facts->>'language_id'
      OR source_snapshot->'blueprint'->>'item_kind' IS DISTINCT FROM scope_facts->>'item_kind'
      OR source_snapshot->'blueprint'->>'purpose' IS DISTINCT FROM scope_facts->>'purpose' THEN
      RAISE check_violation USING MESSAGE='pipeline source identity mismatch';
    END IF;
  ELSE
    SELECT source_hash,mode,candidate_id,version_id INTO generation_facts
      FROM tutor_item_supply_private_generation_artifacts
      WHERE id=NEW.generation_artifact_id AND user_id=NEW.user_id AND epoch=NEW.epoch
        AND scope_id=NEW.scope_id AND job_id=NEW.job_id AND version_id=NEW.version_id
        AND content_hash=NEW.content_hash;
    IF NOT FOUND OR generation_facts.mode IS DISTINCT FROM NEW.mode THEN
      RAISE check_violation USING MESSAGE='pipeline generation identity mismatch';
    END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN 'item_supply_review_bundle_v2'
      WHEN 'admission_evaluation' THEN 'item_supply_admission_evaluation_v2' END;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',NEW.payload_json->'binding'->>'content_hash') IS DISTINCT FROM NEW.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',NEW.payload_json->'binding'->>'source_hash') IS DISTINCT FROM generation_facts.source_hash
      OR (NEW.payload_json ? 'binding' AND (
        NEW.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM generation_facts.candidate_id::text
        OR NEW.payload_json->'binding'->>'version_key' IS DISTINCT FROM generation_facts.version_id::text))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='pipeline receipt identity mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;


REVOKE ALL ON FUNCTION enforce_item_supply_pipeline_artifact() FROM PUBLIC;
