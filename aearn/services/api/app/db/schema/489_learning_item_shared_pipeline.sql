-- Native public generation staging only. Shared confidential answers/rubrics are
-- NOT learner-private provenance or published bank content. No reset/export hook.
CREATE OR REPLACE FUNCTION item_supply_internal.shared_generation_hash(source_payload jsonb, receipt_payload jsonb, request_payload jsonb)
RETURNS text LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  SELECT item_supply_internal.snapshot_hash(jsonb_build_object('source',source_payload,'receipt',receipt_payload,'request',request_payload))
$$;

-- Same UUIDv5 namespace/identity as learning_item_uuid. No bank row is created.
CREATE OR REPLACE FUNCTION item_supply_internal.shared_future_item_uuid(kind text, identity text)
RETURNS uuid LANGUAGE sql IMMUTABLE STRICT SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
  WITH hashed AS (SELECT substring(digest(decode('6ba7b8119dad11d180b400c04fd430c8','hex') ||
    convert_to('aearn:learning-item-bank:' || kind || ':' || identity,'UTF8'),'sha1') FROM 1 FOR 16) AS bytes)
  SELECT encode(set_byte(set_byte(bytes,6,(get_byte(bytes,6) & 15) | 80),8,(get_byte(bytes,8) & 63) | 128),'hex')::uuid FROM hashed
$$;

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_generation_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  root_id uuid NOT NULL REFERENCES tutor_item_supply_shared_budget_roots(id) ON DELETE RESTRICT,
  blueprint_id uuid NOT NULL REFERENCES tutor_item_supply_shared_blueprints(id) ON DELETE RESTRICT,
  job_id uuid NOT NULL, lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  reservation_id uuid NOT NULL,
  candidate_id uuid NOT NULL, item_id uuid NOT NULL, version_id uuid NOT NULL,
  target_id text NOT NULL CHECK(target_id IN ('python-state-update-v1','python-kc-binding-v1','sqlite-predicate-order-v1')),
  target_definition_hash text NOT NULL CHECK(target_definition_hash ~ '^[0-9a-f]{64}$'),
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  mode text NOT NULL DEFAULT 'live' CHECK(mode='live'),
  source_json jsonb NOT NULL CHECK(jsonb_typeof(source_json)='object' AND octet_length(source_json::text)<=1048576 AND (source_json->>'schema_version') IS NOT DISTINCT FROM 'learning_item_source_v1'),
  request_json jsonb NOT NULL CHECK(jsonb_typeof(request_json)='object' AND octet_length(request_json::text)<=1048576 AND (request_json->>'schema_version') IS NOT DISTINCT FROM 'item_generation_request_v2'),
  receipt_json jsonb NOT NULL CHECK(jsonb_typeof(receipt_json)='object' AND octet_length(receipt_json::text)<=65536 AND (receipt_json->>'schema_version') IS NOT DISTINCT FROM 'item_generation_receipt_v2'),
  artifact_hash text GENERATED ALWAYS AS (item_supply_internal.shared_generation_hash(source_json,receipt_json,request_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_key),
  UNIQUE(job_id,candidate_id),
  UNIQUE(id,job_id,lease_generation,item_id,version_id,source_hash,content_hash),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT,
  FOREIGN KEY(reservation_id,job_id) REFERENCES tutor_item_supply_shared_reservations(id,job_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_pipeline_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES tutor_item_supply_shared_jobs(id) ON DELETE RESTRICT,
  lease_owner text NOT NULL CHECK(lease_owner ~ '^[A-Za-z0-9._:-]{3,160}$'),
  lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  generation_artifact_id uuid NOT NULL, item_id uuid NOT NULL, version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  artifact_key text NOT NULL CHECK(artifact_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  artifact_kind text NOT NULL CHECK(artifact_kind IN ('validation','blind_solve','review_bundle','admission_evaluation')),
  schema_version text NOT NULL CHECK(length(schema_version) BETWEEN 1 AND 160),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=1048576 AND (payload_json->>'schema_version') IS NOT DISTINCT FROM schema_version),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  mode text NOT NULL DEFAULT 'live' CHECK(mode='live'),
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,artifact_kind,artifact_key),
  FOREIGN KEY(generation_artifact_id,job_id,lease_generation,item_id,version_id,source_hash,content_hash)
    REFERENCES tutor_item_supply_shared_generation_artifacts(id,job_id,lease_generation,item_id,version_id,source_hash,content_hash) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION enforce_item_supply_shared_pipeline_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE control record; facts record; root_facts record; reservation record;
  scope jsonb; snapshot jsonb; material jsonb; source_receipt jsonb; expected_content text; expected_schema text; i integer;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared pipeline outside B1d';
  END IF;
  SELECT * INTO control FROM tutor_item_supply_shared_job_controls WHERE job_id=NEW.job_id FOR UPDATE;
  IF NOT FOUND OR control.state<>'leased' OR control.lease_generation<>NEW.lease_generation
    OR control.state_version<>NEW.lease_state_version OR control.lease_owner IS DISTINCT FROM NEW.lease_owner
    OR control.lease_expires_at IS NULL OR control.lease_expires_at<=clock_timestamp()
    OR control.parent_deadline<=clock_timestamp() THEN
    RAISE check_violation USING MESSAGE='stale shared pipeline lease';
  END IF;
  snapshot:=CASE WHEN control.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN control.profile_snapshot_json->'profile' ELSE control.profile_snapshot_json END;
  IF TG_TABLE_NAME='tutor_item_supply_shared_generation_artifacts' THEN
    SELECT b.snapshot_json,o.obligation_json,o.provider_key,r.canonical_key INTO root_facts
      FROM tutor_item_supply_shared_budget_roots r
      JOIN tutor_item_supply_shared_blueprints b ON b.id=r.blueprint_id
      JOIN tutor_item_supply_shared_obligations o ON o.root_id=r.id
      WHERE r.id=NEW.root_id AND b.id=NEW.blueprint_id FOR SHARE OF r,b,o;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline root unavailable'; END IF;
    scope:=root_facts.snapshot_json->'scope';
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=NEW.reservation_id;
    IF NOT FOUND OR reservation.root_id<>NEW.root_id OR reservation.job_id<>NEW.job_id
      OR reservation.lease_generation<>NEW.lease_generation
      OR reservation.reservation_key IS DISTINCT FROM 'gen.' || replace(NEW.candidate_id::text,'-','')
      OR NOT EXISTS(SELECT 1 FROM tutor_item_supply_shared_runtime_settlements
        WHERE reservation_id=NEW.reservation_id AND settlement_key='generation.' || replace(NEW.candidate_id::text,'-','')) THEN
      RAISE check_violation USING MESSAGE='shared pipeline reservation mismatch';
    END IF;
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',NEW.source_json->'public'->>'item_key','version',NEW.source_json->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(NEW.source_json->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(NEW.source_json->'public'),
      'private_hash',item_supply_internal.snapshot_hash(NEW.source_json->'private')));
    IF scope->>'visibility' IS DISTINCT FROM 'public' OR scope->>'owner_ref' IS NOT NULL
      OR NEW.request_json->>'demand_binding' IS NOT NULL
      OR NEW.request_json->'profile' IS DISTINCT FROM snapshot
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(scope)
      OR NEW.request_json->>'scope_hash' IS DISTINCT FROM root_facts.obligation_json->>'scope_hash'
      OR item_supply_internal.snapshot_hash(root_facts.obligation_json) IS DISTINCT FROM root_facts.canonical_key
      OR NEW.request_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'candidate_id' IS DISTINCT FROM NEW.candidate_id::text
      OR NEW.receipt_json->>'scope_hash' IS DISTINCT FROM NEW.request_json->>'scope_hash'
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.source_json)
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR NEW.receipt_json->>'source_hash' IS DISTINCT FROM NEW.source_hash
      OR NEW.receipt_json->>'content_hash' IS DISTINCT FROM NEW.content_hash
      OR NEW.request_json->'blueprint' IS DISTINCT FROM NEW.source_json->'blueprint'
      OR NEW.source_json->'public'->>'item_key' IS DISTINCT FROM NEW.request_json->>'item_key'
      OR NEW.source_json->'public'->>'version' IS DISTINCT FROM NEW.request_json->>'version'
      OR NEW.item_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('item',NEW.request_json->>'item_key')
      OR NEW.version_id IS DISTINCT FROM item_supply_internal.shared_future_item_uuid('version',NEW.request_json->>'item_key' || '@' || (NEW.request_json->>'version'))
      OR (NEW.request_json->>'public_template' IS NOT NULL AND NEW.request_json->'public_template' IS DISTINCT FROM NEW.source_json->'public')
      OR NEW.source_json->'blueprint'->>'knowledge_key' IS DISTINCT FROM scope->>'knowledge_key'
      OR NEW.source_json->'blueprint'->>'language_id' IS DISTINCT FROM scope->>'language_id'
      OR NEW.source_json->'blueprint'->>'item_kind' IS DISTINCT FROM scope->>'item_kind'
      OR NEW.source_json->'blueprint'->>'purpose' IS DISTINCT FROM scope->>'purpose'
      OR NEW.source_json->'blueprint'->'required_capabilities' IS DISTINCT FROM scope->'required_capabilities'
      OR NOT (NEW.source_json->'blueprint'->'allowed_interactions' @> jsonb_build_array(scope->>'interaction'))
      OR scope->>'assessment_contract_version' IS DISTINCT FROM NEW.target_id
      OR scope->>'runtime_profile_id' IS DISTINCT FROM (CASE NEW.target_id
        WHEN 'python-state-update-v1' THEN 'python-stdout-v1' WHEN 'sqlite-predicate-order-v1' THEN 'sqlite-query-v1' ELSE 'static-exact-v1' END)
      OR NEW.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
      OR NEW.receipt_json->'provider'->>'provider' IS DISTINCT FROM root_facts.provider_key
      OR NEW.receipt_json->'provider'->>'model' IS DISTINCT FROM NEW.receipt_json->'provider'->>'configured_model'
      OR NEW.receipt_json->'provider'->>'provider_version' IS DISTINCT FROM 'openai_compatible.v2'
      OR NEW.receipt_json->'provider'->>'prompt_version' IS DISTINCT FROM 'item_author.public_material.v2'
      OR jsonb_typeof(NEW.request_json->'materials') IS DISTINCT FROM 'array'
      OR jsonb_typeof(NEW.receipt_json->'sources') IS DISTINCT FROM 'array' THEN
      RAISE check_violation USING MESSAGE='shared pipeline generation identity mismatch';
    END IF;
    IF jsonb_array_length(NEW.request_json->'materials') NOT BETWEEN 1 AND 12
      OR jsonb_array_length(NEW.receipt_json->'sources')<>jsonb_array_length(NEW.request_json->'materials') THEN
      RAISE check_violation USING MESSAGE='shared pipeline source count mismatch';
    END IF;
    FOR i IN 0..jsonb_array_length(NEW.request_json->'materials')-1 LOOP
      material:=NEW.request_json->'materials'->i;
      source_receipt:=NEW.receipt_json->'sources'->i;
      IF material->'binding'->>'contract_version' IS DISTINCT FROM 'rag_public_course_binding_v1'
        OR material->'binding'->>'target_id' IS DISTINCT FROM NEW.target_id
        OR material->'binding'->>'target_definition_hash' IS DISTINCT FROM NEW.target_definition_hash
        OR material->'binding' ? 'draft' OR material->'binding' ? 'user_id'
        OR material->'access_request'->>'actor_id' IS DISTINCT FROM 'service.rag-public-course'
        OR source_receipt->>'mode' IS DISTINCT FROM 'current_authority'
        OR source_receipt->>'binding_digest' IS DISTINCT FROM material->'binding'->>'binding_digest'
        OR source_receipt->>'corpus_version_id' IS DISTINCT FROM material->'binding'->'evidence'->0->>'corpus_version_id'
        OR source_receipt->>'active_generation' IS DISTINCT FROM material->'binding'->'evidence'->0->>'active_generation'
        OR source_receipt->>'material_digest' IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
          'binding',material->'binding','access_request',material->'access_request','exact_claims',material->'exact_claims',
          'excerpt_hash',encode(digest(convert_to(material->>'excerpt','UTF8'),'sha256'),'hex'))) THEN
        RAISE check_violation USING MESSAGE='shared pipeline native source mismatch';
      END IF;
    END LOOP;
  ELSE
    SELECT * INTO facts FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id
      AND job_id=NEW.job_id AND lease_generation=NEW.lease_generation;
    IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared pipeline generation unavailable'; END IF;
    expected_schema:=CASE NEW.artifact_kind WHEN 'validation' THEN 'candidate_validation_v2'
      WHEN 'blind_solve' THEN 'item_supply_blind_receipt_v2' WHEN 'review_bundle' THEN 'item_supply_review_bundle_v2'
      WHEN 'admission_evaluation' THEN 'item_supply_admission_evaluation_v2' END;
    IF NEW.schema_version IS DISTINCT FROM expected_schema
      OR COALESCE(NEW.payload_json->>'content_hash',NEW.payload_json->'binding'->>'content_hash') IS DISTINCT FROM facts.content_hash
      OR COALESCE(NEW.payload_json->>'source_hash',NEW.payload_json->'binding'->>'source_hash') IS DISTINCT FROM facts.source_hash
      OR (NEW.artifact_kind<>'validation' AND (
        NEW.payload_json->'binding'->>'candidate_key' IS DISTINCT FROM facts.item_id::text
        OR NEW.payload_json->'binding'->>'version_key' IS DISTINCT FROM facts.version_id::text
        OR NEW.payload_json->'binding'->>'profile_hash' IS DISTINCT FROM snapshot->>'profile_hash'))
      OR (NEW.payload_json ? 'publication_enabled' AND NEW.payload_json->'publication_enabled'<>'false'::jsonb) THEN
      RAISE check_violation USING MESSAGE='shared pipeline receipt identity mismatch';
    END IF;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_pipeline_artifact() FROM PUBLIC;

DO $$ DECLARE table_name text; BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_shared_generation_artifacts','tutor_item_supply_shared_pipeline_receipts'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS supply_shared_pipeline ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_shared_pipeline BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_pipeline_artifact()',table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS supply_mutation ON %I',table_name);
    EXECUTE format('CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''shared'')',table_name);
  END LOOP;
END $$;
