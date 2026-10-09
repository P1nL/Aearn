-- B1d-only immutable native PER-ITEM facts. Never family/inventory or publication.
-- JSON is audit only. Consumers must retain the original live concrete issuer.
CREATE TABLE IF NOT EXISTS tutor_item_supply_shared_admission_facts (
  id uuid PRIMARY KEY,
  root_id uuid NOT NULL, job_id uuid NOT NULL,
  lease_owner text NOT NULL, lease_generation integer NOT NULL CHECK(lease_generation>0),
  lease_state_version bigint NOT NULL CHECK(lease_state_version>0),
  profile_hash text NOT NULL CHECK(profile_hash ~ '^[0-9a-f]{64}$'),
  generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  item_id uuid NOT NULL, version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  continuation_binding_hash text CHECK(continuation_binding_hash ~ '^[0-9a-f]{64}$'),
  validation_preparation_id uuid NOT NULL REFERENCES tutor_item_supply_shared_validation_preparations(id) ON DELETE RESTRICT,
  validation_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  blind_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  review_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object' AND octet_length(payload_json::text)<=2097152),
  payload_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(job_id,lease_generation,generation_artifact_id), UNIQUE(review_receipt_id),
  FOREIGN KEY(job_id,root_id) REFERENCES tutor_item_supply_shared_jobs(id,root_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION enforce_item_supply_shared_admission_facts() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=NEW.payload_json; a record; c record; prep record; v record; b record; r record;
  usage record; reservation record; budget jsonb; snapshot jsonb; t timestamptz; kind text; rid uuid;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN
    RAISE check_violation USING MESSAGE='shared facts B1d only';
  END IF;
  SELECT co.*,j.root_id,pr.profile_hash INTO c FROM tutor_item_supply_shared_job_controls co
    JOIN tutor_item_supply_shared_jobs j ON j.id=co.job_id
    JOIN tutor_item_supply_parameter_profiles pr ON pr.id=co.profile_id
    WHERE co.job_id=NEW.job_id FOR SHARE OF co;
  t:=clock_timestamp();
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='shared facts current job missing'; END IF;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  IF c.state<>'leased' OR c.root_id<>NEW.root_id OR c.profile_hash<>NEW.profile_hash
    OR c.lease_owner IS DISTINCT FROM NEW.lease_owner OR c.lease_generation<>NEW.lease_generation
    OR c.state_version<>NEW.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR p->'lease'->'profile' IS DISTINCT FROM snapshot
    OR (p->>'checked_at')::timestamptz>t OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(snapshot->>'parent_deadline_at')::timestamptz)
    OR (p->>'checked_at')::timestamptz>=(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts current lease expired or mismatched';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  IF NOT FOUND OR a.root_id<>NEW.root_id OR a.item_id<>NEW.item_id OR a.version_id<>NEW.version_id
    OR a.source_hash<>NEW.source_hash OR a.content_hash<>NEW.content_hash
    OR item_supply_internal.shared_stage_original_matches(NEW.job_id,NEW.lease_generation,
      NEW.generation_artifact_id,NEW.continuation_binding_hash) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='shared facts original generation/adoption mismatch';
  END IF;
  IF p->>'schema_version' IS DISTINCT FROM 'issued_shared_admission_facts_v1'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->>'receipt_id' IS DISTINCT FROM NEW.id::text OR p->>'root_id' IS DISTINCT FROM NEW.root_id::text
    OR p->>'generation_artifact_id' IS DISTINCT FROM a.id::text OR p->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR p->>'item_id' IS DISTINCT FROM NEW.item_id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
    OR p->>'continuation_binding_hash' IS DISTINCT FROM NEW.continuation_binding_hash
    OR p->'lease'->>'visibility' IS DISTINCT FROM 'public' OR p->'lease'->>'job_id' IS DISTINCT FROM NEW.job_id::text
    OR p->'lease'->>'lease_owner' IS DISTINCT FROM NEW.lease_owner
    OR p->'lease'->>'generation' IS DISTINCT FROM NEW.lease_generation::text
    OR p->'lease'->>'state_version' IS DISTINCT FROM NEW.lease_state_version::text
    OR p->>'target_id' IS DISTINCT FROM a.target_id OR p->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR a.target_id NOT IN ('python-state-update-v1','sqlite-predicate-order-v1','python-kc-binding-v1')
    OR p->'evidence'->'binding'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'evidence'->'binding'->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR p->'evidence'->'binding'->>'candidate_key' IS DISTINCT FROM NEW.item_id::text
    OR p->'evidence'->'binding'->>'version_key' IS DISTINCT FROM NEW.version_id::text
    OR p->'evidence'->'binding'->>'profile_hash' IS DISTINCT FROM NEW.profile_hash
    OR p->'evaluation'->'binding' IS DISTINCT FROM p->'evidence'->'binding'
    OR p->'evaluation'->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'evaluation'->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'evidence') THEN
    RAISE check_violation USING MESSAGE='shared facts payload identity mismatch';
  END IF;
  SELECT * INTO prep FROM tutor_item_supply_shared_validation_preparations WHERE id=NEW.validation_preparation_id;
  IF NOT FOUND OR prep.job_id<>NEW.job_id OR prep.lease_generation<>NEW.lease_generation
    OR prep.generation_artifact_id<>a.id OR prep.profile_hash<>NEW.profile_hash
    OR p->>'validation_preparation_id' IS DISTINCT FROM prep.id::text
    OR p->>'specification_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'spec')
    OR p->>'inputs_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(prep.payload_json->'inputs')
    OR p->>'public_task_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'public_task_hash'
    OR p->>'instance_hash' IS DISTINCT FROM prep.payload_json->'inputs'->>'instance_hash'
    OR p->>'scorer_version' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'scorer_version'
    OR p->>'runtime_profile_hash' IS DISTINCT FROM prep.payload_json->'spec'->'coverage_blueprint'->'scope'->>'runtime_profile_hash' THEN
    RAISE check_violation USING MESSAGE='shared facts finite preparation mismatch';
  END IF;
  FOR kind,rid IN SELECT * FROM (VALUES ('validation',NEW.validation_receipt_id),
      ('blind_solve',NEW.blind_receipt_id),('review_bundle',NEW.review_receipt_id)) AS stages(kind,rid) LOOP
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO r
      FROM tutor_item_supply_shared_pipeline_receipts s WHERE s.id=rid;
    IF NOT FOUND OR r.same_transaction OR r.job_id<>NEW.job_id OR r.lease_generation<>NEW.lease_generation
      OR r.lease_owner<>NEW.lease_owner OR r.generation_artifact_id<>a.id OR r.mode<>'live'
      OR r.item_id<>NEW.item_id OR r.version_id<>NEW.version_id OR r.source_hash<>NEW.source_hash OR r.content_hash<>NEW.content_hash
      OR r.artifact_kind<>kind OR r.continuation_binding_hash IS DISTINCT FROM NEW.continuation_binding_hash THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed exact stages required';
    END IF;
    IF kind='validation' THEN
      v:=r;
      IF p->>'validation_receipt_id' IS DISTINCT FROM r.id::text OR p->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR p->'evidence'->>'validation_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts validation receipt mismatch';
      END IF;
    ELSIF kind='blind_solve' THEN
      b:=r;
      IF p->>'blind_receipt_id' IS DISTINCT FROM r.id::text OR p->>'blind_receipt_hash' IS DISTINCT FROM r.receipt_hash THEN
        RAISE check_violation USING MESSAGE='shared facts blind receipt mismatch';
      END IF;
    ELSE
      IF p->>'review_receipt_id' IS DISTINCT FROM r.id::text OR p->>'review_receipt_hash' IS DISTINCT FROM r.receipt_hash
        OR r.payload_json->'blind_solve' IS DISTINCT FROM b.payload_json THEN
        RAISE check_violation USING MESSAGE='shared facts review receipt mismatch';
      END IF;
    END IF;
  END LOOP;
  FOR kind,budget IN SELECT * FROM (VALUES ('validation',p->'validation_budget'),('review',p->'review_budget')) AS budgets(kind,budget) LOOP
    IF kind='validation' AND a.target_id='python-kc-binding-v1' THEN
      IF budget IS DISTINCT FROM 'null'::jsonb THEN RAISE check_violation USING MESSAGE='static facts have no execution budget'; END IF;
      CONTINUE;
    END IF;
    SELECT * INTO reservation FROM tutor_item_supply_shared_reservations WHERE id=(budget->>'reservation_id')::uuid;
    IF NOT FOUND OR reservation.job_id<>NEW.job_id OR reservation.root_id<>NEW.root_id
      OR reservation.lease_generation<>NEW.lease_generation OR reservation.reservation_key IS DISTINCT FROM budget->>'settlement_key'
      OR reservation.reservation_key<>(CASE WHEN kind='review' THEN 'review.'||replace(a.id::text,'-','') ELSE prep.reservation_key END) THEN
      RAISE check_violation USING MESSAGE='shared facts reservation identity mismatch';
    END IF;
    SELECT s.*,s.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO usage
      FROM tutor_item_supply_shared_runtime_settlements s WHERE s.id=(budget->>'settlement_id')::uuid;
    IF NOT FOUND OR usage.same_transaction OR usage.reservation_id<>reservation.id
      OR usage.settlement_key<>reservation.reservation_key OR usage.usage_state IS DISTINCT FROM budget->>'usage_state'
      OR usage.receipt_hash IS DISTINCT FROM budget->>'receipt_hash'
      OR usage.usage_state<>(CASE WHEN kind='review' THEN 'unknown' ELSE 'known' END) THEN
      RAISE check_violation USING MESSAGE='shared facts separately committed usage required';
    END IF;
    IF kind='review' AND (budget->'actual' IS DISTINCT FROM 'null'::jsonb OR budget->'receipt_hash' IS DISTINCT FROM 'null'::jsonb) THEN
      RAISE check_violation USING MESSAGE='unknown provider usage cannot become zero';
    END IF;
  END LOOP;
  IF p->'ambiguity'->'plan'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'ambiguity'->'plan'->>'specification_hash' IS DISTINCT FROM p->>'specification_hash'
    OR p->'ambiguity'->'plan'->>'inputs_hash' IS DISTINCT FROM p->>'inputs_hash'
    OR (p->'ambiguity'->>'parent_deadline_at')::timestamptz<(p->>'valid_until')::timestamptz THEN
    RAISE check_violation USING MESSAGE='shared facts finite interpretation mismatch';
  END IF;
  IF a.target_id='python-kc-binding-v1' THEN
    IF p->'validation_terminals' IS DISTINCT FROM '[]'::jsonb OR p->'blind_terminals' IS DISTINCT FROM '[]'::jsonb
      OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'static_options'
      OR p->'evidence'->'runner_available' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_isolated' IS DISTINCT FROM 'false'::jsonb
      OR p->'evidence'->'execution_receipt_hash' IS DISTINCT FROM 'null'::jsonb THEN
      RAISE check_violation USING MESSAGE='static facts cannot claim OS execution';
    END IF;
  ELSIF jsonb_array_length(p->'validation_terminals') NOT BETWEEN 1 AND 32
    OR jsonb_array_length(p->'blind_terminals')<>1 OR p->'ambiguity'->>'mode' IS DISTINCT FROM 'sealed_pair'
    OR p->'evidence'->>'execution_receipt_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(v.payload_json->'execution_evidence') THEN
    RAISE check_violation USING MESSAGE='runtime facts original terminal projection missing';
  END IF;
  IF p->'target_proof'<>'null'::jsonb AND (p->'target_proof'->>'claim_scope' IS DISTINCT FROM 'per_item_registered_target_not_inventory'
    OR p->'target_proof'->>'source_hash' IS DISTINCT FROM NEW.source_hash
    OR p->'target_proof'->>'target_definition_hash' IS DISTINCT FROM a.target_definition_hash
    OR p->'evidence'->>'coverage_proof_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(p->'target_proof')) THEN
    RAISE check_violation USING MESSAGE='shared facts per-item proof mismatch';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_shared_admission_facts() FROM PUBLIC;
DROP TRIGGER IF EXISTS supply_shared_admission_facts ON tutor_item_supply_shared_admission_facts;
CREATE TRIGGER supply_shared_admission_facts BEFORE INSERT ON tutor_item_supply_shared_admission_facts
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_shared_admission_facts();
DROP TRIGGER IF EXISTS supply_mutation ON tutor_item_supply_shared_admission_facts;
CREATE TRIGGER supply_mutation BEFORE UPDATE OR DELETE ON tutor_item_supply_shared_admission_facts
  FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable('shared');
