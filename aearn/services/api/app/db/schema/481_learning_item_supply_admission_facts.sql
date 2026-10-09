-- Bounded pre-admission facts, distinct from P7 published inventory and model JSON.
CREATE TABLE IF NOT EXISTS tutor_item_supply_private_admission_facts (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, job_id uuid NOT NULL,
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  lease_owner text NOT NULL,
  generation_artifact_id uuid NOT NULL, version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=1048576
    AND (payload_json->>'schema_version') IS NOT DISTINCT FROM 'issued_admission_facts_v1'
    AND (payload_json->>'publication_enabled') IS NOT DISTINCT FROM 'false'
    AND (payload_json->'coverage'->>'schema_version') IS NOT DISTINCT FROM 'pre_admission_coverage_receipt_v1'
    AND (payload_json->'ambiguity'->>'schema_version') IS NOT DISTINCT FROM 'task_ambiguity_receipt_v1'
    AND (payload_json->'coverage'->>'coverage_kind') IS NOT DISTINCT FROM 'candidate_target_mapping_not_inventory'),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(job_id,user_id,epoch,scope_id) REFERENCES tutor_item_supply_private_jobs(id,user_id,epoch,scope_id) ON DELETE RESTRICT,
  -- Only the existing reset-permit protected parent can remove this child.
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,job_id,version_id,content_hash)
    ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_item_supply_admission_facts_owner
  ON tutor_item_supply_private_admission_facts(user_id,epoch,scope_id,generation_artifact_id);

CREATE OR REPLACE FUNCTION enforce_item_supply_admission_facts() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE control record; artifact record;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NOT EXISTS(
    SELECT 1 FROM users WHERE id=NEW.user_id AND deleted_at IS NULL
      AND display_name=('sandbox.p6.'||NEW.user_id::text)) THEN
    RAISE check_violation USING MESSAGE='admission facts isolated actor required';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_private_job_controls
    WHERE job_id=NEW.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
  IF NOT FOUND OR control.lease_generation<>NEW.lease_generation OR control.state_version<>NEW.lease_state_version
    OR control.lease_owner<>NEW.lease_owner
    OR control.state NOT IN ('leased','reviewing','simulating','admitting')
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp()
    OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='admission facts lease stale';
  END IF;
  SELECT * INTO artifact FROM tutor_item_supply_private_generation_artifacts
    WHERE id=NEW.generation_artifact_id AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND scope_id=NEW.scope_id AND job_id=NEW.job_id AND version_id=NEW.version_id FOR SHARE;
  IF NOT FOUND OR artifact.mode<>'live' OR artifact.source_hash<>NEW.source_hash OR artifact.content_hash<>NEW.content_hash
    OR NEW.payload_json->>'receipt_id' IS DISTINCT FROM NEW.id::text
    OR NEW.payload_json->>'user_id' IS DISTINCT FROM NEW.user_id::text
    OR NEW.payload_json->>'epoch' IS DISTINCT FROM NEW.epoch::text
    OR NEW.payload_json->>'scope_id' IS DISTINCT FROM NEW.scope_id::text
    OR NEW.payload_json->>'generation_artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
    OR NEW.payload_json->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR NEW.payload_json->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR NEW.payload_json->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
    OR NEW.payload_json->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
    OR NEW.payload_json->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
    OR NEW.payload_json->'evidence'->'binding'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR NEW.payload_json->'evidence'->'binding'->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR NEW.payload_json->'coverage'->'binding'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR NEW.payload_json->'coverage'->'binding'->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR NEW.payload_json->'coverage'->'binding'->>'candidate_key' IS DISTINCT FROM artifact.candidate_id::text
    OR NEW.payload_json->'coverage'->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
    OR NEW.payload_json->'evidence'->'binding' IS DISTINCT FROM NEW.payload_json->'coverage'->'binding'
    OR (NEW.payload_json->'coverage'->>'valid_until')::timestamptz<=clock_timestamp()
    OR (NEW.payload_json->'coverage'->>'valid_until')::timestamptz>LEAST(control.lease_expires_at,control.parent_deadline) THEN
    RAISE check_violation USING MESSAGE='admission facts exact binding stale';
  END IF;
  -- SQL identity is not execution authenticity: concrete owner re-verifies real
  -- seals/scorer/source/current target before a live commit can consume this row.
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_admission_facts() FROM PUBLIC;
DROP TRIGGER IF EXISTS trg_item_supply_admission_facts_epoch ON tutor_item_supply_private_admission_facts;
CREATE TRIGGER trg_item_supply_admission_facts_epoch BEFORE INSERT OR UPDATE OR DELETE
  ON tutor_item_supply_private_admission_facts FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch();
DROP TRIGGER IF EXISTS trg_item_supply_admission_facts_insert ON tutor_item_supply_private_admission_facts;
CREATE TRIGGER trg_item_supply_admission_facts_insert BEFORE INSERT
  ON tutor_item_supply_private_admission_facts FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_admission_facts();
DROP TRIGGER IF EXISTS trg_item_supply_admission_facts_immutable ON tutor_item_supply_private_admission_facts;
CREATE TRIGGER trg_item_supply_admission_facts_immutable BEFORE UPDATE OR DELETE
  ON tutor_item_supply_private_admission_facts FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('private');
