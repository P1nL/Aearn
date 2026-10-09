-- P4/P5 private candidate and typed receipts; never publication authority.
-- Additive only. Caller owns the transaction. No learner score/progress writes.
CREATE OR REPLACE FUNCTION item_supply_internal.pipeline_generation_hash(source_payload jsonb, receipt_payload jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT item_supply_internal.snapshot_hash(jsonb_build_object('source',source_payload,'receipt',receipt_payload))
$$;

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_generation_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  job_id uuid NOT NULL, lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  candidate_id uuid NOT NULL, version_id uuid NOT NULL,
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  mode text NOT NULL CHECK(mode IN ('live','synthetic')),
  source_json jsonb NOT NULL CHECK(jsonb_typeof(source_json)='object' AND octet_length(source_json::text)<=1048576 AND (source_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_source_v1'),
  request_json jsonb NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=1048576 AND (request_json->>'schema_version') IS NOT DISTINCT FROM 'item_generation_request_v2'),
  receipt_json jsonb NOT NULL CHECK(jsonb_typeof(receipt_json)='object' AND octet_length(receipt_json::text)<=65536),
  artifact_hash text GENERATED ALWAYS AS (item_supply_internal.pipeline_generation_hash(source_json,receipt_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_key),
  UNIQUE(id,user_id,epoch,scope_id,job_id,version_id,content_hash),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(candidate_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_candidates(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,scope_id) ON DELETE RESTRICT
);

-- An early-development 460 is empty; never invent missing authorization data.
ALTER TABLE tutor_item_supply_private_generation_artifacts ADD COLUMN IF NOT EXISTS request_json jsonb NOT NULL;

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_pipeline_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL,
  job_id uuid NOT NULL, lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  generation_artifact_id uuid NOT NULL, version_id uuid NOT NULL,
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  artifact_kind text NOT NULL CHECK(artifact_kind IN ('validation','blind_solve','review_bundle','admission_evaluation')),
  schema_version text NOT NULL CHECK(length(schema_version) BETWEEN 1 AND 160),
  mode text NOT NULL CHECK(mode IN ('live','synthetic')),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576 AND (payload_json->>'schema_version') IS NOT DISTINCT FROM schema_version),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_kind,artifact_key),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,job_id,version_id,content_hash) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION enforce_item_supply_pipeline_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE control record; generation_facts record; version_facts record; scope_facts jsonb; scope_hash text; source_snapshot jsonb; expected_content text; expected_schema text;
BEGIN
  IF NEW.mode='synthetic' AND current_database()<>'aearn_b1b_fixture_20260930' THEN
    RAISE check_violation USING MESSAGE='synthetic pipeline outside fixture';
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

-- Retain the accepted purge capability and add new private children first.
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
REVOKE ALL ON FUNCTION enforce_item_supply_pipeline_artifact() FROM PUBLIC;

DO $$ DECLARE table_name text; BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_private_generation_artifacts','tutor_item_supply_private_pipeline_receipts'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_epoch ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_epoch BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch()',table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS supply_mutation ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''private'')',table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS supply_stage_authority ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_stage_authority BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_pipeline_artifact()',table_name);
  END LOOP;
END $$;
