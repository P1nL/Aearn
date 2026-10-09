-- Native committed V2 validation DATA in the ORIGINAL immutable bank namespace.
-- No bank fork, V1-shaped receipt, execution authority, publication or Practice row.
-- Old V1 rows and source/compiler hashes remain unchanged. No data backfill.
ALTER TABLE tutor_learning_item_validation_receipts
  ALTER COLUMN passed DROP NOT NULL,
  ADD COLUMN IF NOT EXISTS native_generation_artifact_id uuid REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS native_validation_receipt_id uuid REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS native_validation_evidence_id uuid REFERENCES tutor_item_supply_shared_validation_evidence(id) ON DELETE RESTRICT,
  ADD COLUMN IF NOT EXISTS native_specification_hash text,
  ADD COLUMN IF NOT EXISTS native_import_lease_json jsonb;
ALTER TABLE tutor_learning_item_validation_receipts DROP CONSTRAINT IF EXISTS learning_item_validation_closed_type;
ALTER TABLE tutor_learning_item_validation_receipts ADD CONSTRAINT learning_item_validation_closed_type CHECK (
  (schema_version='learning_item_validation_v1' AND passed IS TRUE
    AND native_generation_artifact_id IS NULL AND native_validation_receipt_id IS NULL
    AND native_validation_evidence_id IS NULL AND native_specification_hash IS NULL AND native_import_lease_json IS NULL)
  OR (schema_version='candidate_validation_v2' AND passed IS NULL
    AND policy_version='learning_item_native_import_v2' AND compiler_version='learning_item_compiler_v1'
    AND native_generation_artifact_id IS NOT NULL AND native_validation_receipt_id IS NOT NULL
    AND native_validation_evidence_id IS NOT NULL AND native_specification_hash IS NOT NULL
    AND native_specification_hash ~ '^[0-9a-f]{64}$' AND native_import_lease_json IS NOT NULL
    AND jsonb_typeof(native_import_lease_json)='object' AND octet_length(native_import_lease_json::text)<=65536)
);
-- V1 keeps its exact deterministic policy/compiler and receipt-hash uniqueness.
-- Native V2 is operation provenance: an unchanged KC payload can legitimately
-- have the same hash in two independently committed validation operations.
ALTER TABLE tutor_learning_item_validation_receipts DROP CONSTRAINT IF EXISTS uq_tutor_learning_item_validation_policy;
ALTER TABLE tutor_learning_item_validation_receipts DROP CONSTRAINT IF EXISTS tutor_learning_item_validation_receipts_receipt_hash_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_learning_item_validation_v1_policy
  ON tutor_learning_item_validation_receipts(version_id,policy_version,compiler_version)
  WHERE schema_version='learning_item_validation_v1';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_learning_item_validation_v1_hash
  ON tutor_learning_item_validation_receipts(receipt_hash)
  WHERE schema_version='learning_item_validation_v1';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_learning_item_validation_v2_operation
  ON tutor_learning_item_validation_receipts(native_validation_receipt_id)
  WHERE schema_version='candidate_validation_v2';
ALTER TABLE tutor_learning_item_import_receipts DROP CONSTRAINT IF EXISTS tutor_learning_item_import_receipts_importer_version_check;
ALTER TABLE tutor_learning_item_import_receipts ADD CONSTRAINT tutor_learning_item_import_receipts_importer_version_check
  CHECK(importer_version IN ('learning_item_repository_v1','learning_item_native_repository_v2'));

CREATE OR REPLACE FUNCTION enforce_learning_item_native_validation_import() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE r record; p record; e record; a record; v record; c record; j record;
  lease jsonb:=NEW.native_import_lease_json; snapshot jsonb; scope jsonb; terminal jsonb;
BEGIN
  IF NEW.schema_version='learning_item_validation_v1' THEN RETURN NEW; END IF;
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NEW.schema_version<>'candidate_validation_v2' THEN
    RAISE check_violation USING MESSAGE='native bank import is B1d V2 only';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO r
    FROM tutor_item_supply_shared_pipeline_receipts x WHERE id=NEW.native_validation_receipt_id;
  IF NOT FOUND OR r.same_transaction OR r.artifact_kind<>'validation' OR r.mode<>'live' OR r.publication_enabled
    OR r.schema_version<>'candidate_validation_v2' OR r.payload_json IS DISTINCT FROM NEW.receipt_json
    OR r.receipt_hash IS DISTINCT FROM NEW.receipt_hash OR r.version_id IS DISTINCT FROM NEW.version_id
    OR r.content_hash IS DISTINCT FROM NEW.content_hash OR r.generation_artifact_id IS DISTINCT FROM NEW.native_generation_artifact_id
    OR r.payload_json->>'state' IS DISTINCT FROM 'machine_verified'
    OR r.payload_json->>'source_hash' IS DISTINCT FROM r.source_hash
    OR r.payload_json->>'content_hash' IS DISTINCT FROM r.content_hash THEN
    RAISE check_violation USING MESSAGE='native bank requires exact committed shared V2 validation';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO e
    FROM tutor_item_supply_shared_validation_evidence x WHERE id=NEW.native_validation_evidence_id;
  IF NOT FOUND OR e.same_transaction OR e.publication_enabled
    OR e.payload_json->'validation' IS DISTINCT FROM NEW.receipt_json THEN
    RAISE check_violation USING MESSAGE='native bank committed evidence mismatch';
  END IF;
  SELECT x.*,x.xmin::text::bigint=(txid_current() % 4294967296) AS same_transaction INTO p
    FROM tutor_item_supply_shared_validation_preparations x WHERE id=e.preparation_id;
  IF NOT FOUND OR p.same_transaction OR p.job_id IS DISTINCT FROM r.job_id OR p.lease_generation IS DISTINCT FROM r.lease_generation
    OR p.generation_artifact_id IS DISTINCT FROM r.generation_artifact_id OR p.item_id IS DISTINCT FROM r.item_id
    OR p.version_id IS DISTINCT FROM r.version_id OR p.source_hash IS DISTINCT FROM r.source_hash
    OR p.content_hash IS DISTINCT FROM r.content_hash OR p.profile_hash IS DISTINCT FROM lease->'profile'->>'profile_hash'
    OR r.artifact_key IS DISTINCT FROM 'validation.'||replace(p.id::text,'-','')
    OR NEW.native_specification_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(p.payload_json->'spec')
    OR p.payload_json->'inputs'->>'specification_hash' IS DISTINCT FROM NEW.native_specification_hash THEN
    RAISE check_violation USING MESSAGE='native bank exact finite preparation required';
  END IF;
  SELECT * INTO a FROM tutor_item_supply_shared_generation_artifacts WHERE id=r.generation_artifact_id;
  SELECT * INTO v FROM tutor_learning_item_versions WHERE id=NEW.version_id;
  IF a.id IS NULL OR v.id IS NULL OR a.item_id IS DISTINCT FROM v.item_id OR a.version_id IS DISTINCT FROM v.id
    OR a.source_hash IS DISTINCT FROM v.source_hash OR a.content_hash IS DISTINCT FROM v.content_hash
    OR NEW.item_handle IS DISTINCT FROM v.handle
    OR v.public_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'public')
    OR v.private_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'private')
    OR v.blueprint_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(a.source_json->'blueprint')
    OR p.payload_json->'request' IS DISTINCT FROM a.request_json
    OR p.payload_json->>'artifact_hash' IS DISTINCT FROM a.artifact_hash
    OR a.receipt_json->'provider'->>'mode' IS DISTINCT FROM 'provider'
    OR v.creator_identity IS DISTINCT FROM 'native.author.'||replace(a.receipt_json->'provider'->>'run_id','-','')
    OR item_supply_internal.shared_stage_original_matches(r.job_id,r.lease_generation,a.id,r.continuation_binding_hash) IS DISTINCT FROM true THEN
    RAISE check_violation USING MESSAGE='native bank original immutable content mismatch';
  END IF;
  SELECT * INTO j FROM tutor_item_supply_shared_jobs WHERE id=r.job_id;
  SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=r.job_id FOR UPDATE;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  IF j.root_id IS DISTINCT FROM a.root_id OR c.job_id IS NULL OR c.state<>'leased'
    OR c.lease_generation IS DISTINCT FROM r.lease_generation OR c.lease_expires_at IS NULL
    OR c.lease_expires_at<=clock_timestamp() OR c.parent_deadline<=clock_timestamp()
    OR lease->>'visibility' IS DISTINCT FROM 'public' OR lease->>'job_id' IS DISTINCT FROM r.job_id::text
    OR lease->>'generation' IS DISTINCT FROM c.lease_generation::text
    OR lease->>'state_version' IS DISTINCT FROM c.state_version::text
    OR lease->>'lease_owner' IS DISTINCT FROM c.lease_owner OR lease->'profile' IS DISTINCT FROM snapshot
    OR p.payload_json->'lease'->'profile' IS DISTINCT FROM snapshot THEN
    RAISE check_violation USING MESSAGE='native bank current operation lease required';
  END IF;
  scope:=p.payload_json->'spec'->'coverage_blueprint'->'scope';
  IF a.source_json->'public'->>'kind'='knowledge_check' THEN
    IF NEW.receipt_json->>'mode' IS DISTINCT FROM 'static'
      OR NEW.receipt_json IS DISTINCT FROM p.payload_json->'inputs'->'static_facts'->'validation'
      OR NEW.receipt_json->'execution_evidence' IS DISTINCT FROM 'null'::jsonb
      OR e.reservation_id IS NOT NULL OR e.payload_json->'terminals' IS DISTINCT FROM '[]'::jsonb THEN
      RAISE check_violation USING MESSAGE='native bank actual static proof required';
    END IF;
  ELSE
    IF a.source_json->'public'->>'kind' NOT IN ('code','sql') OR NEW.receipt_json->>'mode' IS DISTINCT FROM 'live'
      OR NEW.receipt_json->'legacy_receipt' IS DISTINCT FROM 'null'::jsonb
      OR NEW.receipt_json->'execution_evidence'->>'mode' IS DISTINCT FROM 'live'
      OR NEW.receipt_json->'execution_evidence'->>'isolation' IS DISTINCT FROM 'approved_os_boundary'
      OR NEW.receipt_json->'execution_evidence'->>'runtime_profile_id' IS DISTINCT FROM v.runtime_profile_key
      OR NEW.receipt_json->'execution_evidence'->>'scorer_version' IS DISTINCT FROM scope->>'scorer_version'
      OR e.reservation_id IS NULL OR jsonb_typeof(e.payload_json->'terminals') IS DISTINCT FROM 'array'
      OR jsonb_array_length(e.payload_json->'terminals')<1 THEN
      RAISE check_violation USING MESSAGE='native bank execution binding required';
    END IF;
    FOR terminal IN SELECT value FROM jsonb_array_elements(e.payload_json->'terminals') LOOP
      IF terminal->>'lock_fingerprint' IS DISTINCT FROM scope->>'runtime_profile_hash'
        OR terminal->>'run_id' IS DISTINCT FROM NEW.receipt_json->'execution_evidence'->>'run_id'
        OR terminal->>'mode' IS DISTINCT FROM 'live' OR terminal->>'isolation' IS DISTINCT FROM 'approved_os_boundary' THEN
        RAISE check_violation USING MESSAGE='native bank stored terminal binding mismatch';
      END IF;
    END LOOP;
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_learning_item_native_validation_import() FROM PUBLIC;
DROP TRIGGER IF EXISTS learning_item_native_validation_import ON tutor_learning_item_validation_receipts;
CREATE TRIGGER learning_item_native_validation_import BEFORE INSERT ON tutor_learning_item_validation_receipts
  FOR EACH ROW EXECUTE FUNCTION enforce_learning_item_native_validation_import();

CREATE OR REPLACE FUNCTION enforce_learning_item_native_import_receipt() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE v tutor_learning_item_validation_receipts;
BEGIN
  SELECT * INTO v FROM tutor_learning_item_validation_receipts WHERE id=NEW.validation_receipt_id;
  IF NEW.importer_version='learning_item_native_repository_v2' THEN
    IF v.schema_version IS DISTINCT FROM 'candidate_validation_v2' OR v.version_id IS DISTINCT FROM NEW.version_id
      OR NEW.source_hash IS DISTINCT FROM v.receipt_json->>'source_hash'
      OR NEW.source_file_hash IS DISTINCT FROM NEW.source_hash
      OR NEW.source_path IS DISTINCT FROM 'native/shared-generation/'||v.native_generation_artifact_id::text||'.json' THEN
      RAISE check_violation USING MESSAGE='native bank import provenance mismatch';
    END IF;
  ELSIF v.schema_version IS DISTINCT FROM 'learning_item_validation_v1' THEN
    RAISE check_violation USING MESSAGE='V1 importer cannot relabel V2 validation';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS learning_item_native_import_receipt ON tutor_learning_item_import_receipts;
CREATE TRIGGER learning_item_native_import_receipt BEFORE INSERT ON tutor_learning_item_import_receipts
  FOR EACH ROW EXECUTE FUNCTION enforce_learning_item_native_import_receipt();

-- Same 140 governance function, changing ONLY the initial validation alternative.
-- Later review/pilot/human/materialization rules are deliberately not V2-enabled.
CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_publication_insert()
RETURNS trigger AS $$
DECLARE current_event tutor_learning_item_publication_events%ROWTYPE;
DECLARE version_row tutor_learning_item_versions%ROWTYPE;
BEGIN
  SELECT * INTO version_row FROM tutor_learning_item_versions WHERE id=NEW.version_id FOR UPDATE;
  IF version_row.id IS NULL THEN
    RAISE EXCEPTION 'Learning Item publication version is missing' USING ERRCODE='23514';
  END IF;
  SELECT * INTO current_event FROM tutor_learning_item_publication_events
  WHERE version_id=NEW.version_id ORDER BY state_version DESC LIMIT 1;
  IF current_event.id IS NULL THEN
    IF NEW.state_version<>1 OR NEW.predecessor_event_id IS NOT NULL
       OR NEW.state<>'machine_verified' OR NEW.authority_kind<>'validation'
       OR NEW.authority_reference_id IS NULL
       OR NOT EXISTS (
         SELECT 1 FROM tutor_learning_item_validation_receipts AS receipts
         WHERE receipts.id=NEW.authority_reference_id AND receipts.version_id=NEW.version_id
           AND receipts.receipt_hash=NEW.authority_hash AND (
             (receipts.schema_version='learning_item_validation_v1' AND receipts.passed)
             OR (receipts.schema_version='candidate_validation_v2' AND receipts.passed IS NULL
               AND receipts.native_validation_receipt_id IS NOT NULL AND receipts.native_validation_evidence_id IS NOT NULL
               AND receipts.receipt_json->>'state'='machine_verified'
               AND NEW.policy_version=receipts.policy_version))
       ) THEN
      RAISE EXCEPTION 'Learning Item publication must begin with exact validation authority' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.predecessor_event_id IS DISTINCT FROM current_event.id
     OR NEW.state_version<>current_event.state_version+1 THEN
    RAISE EXCEPTION 'Learning Item publication lineage is stale or forked' USING ERRCODE='23514';
  END IF;
  IF current_event.state='retired' OR current_event.state=NEW.state THEN
    RAISE EXCEPTION 'Learning Item publication state cannot advance' USING ERRCODE='23514';
  END IF;
  IF NOT (
    (current_event.state='machine_verified' AND NEW.state IN ('agent_reviewed','quarantined','retired'))
    OR (current_event.state='agent_reviewed' AND NEW.state IN ('pilot','quarantined','retired'))
    OR (current_event.state='pilot' AND NEW.state IN ('published','quarantined','retired'))
    OR (current_event.state='published' AND NEW.state IN ('quarantined','retired'))
    OR (current_event.state='quarantined' AND NEW.state='retired')
  ) THEN
    RAISE EXCEPTION 'Learning Item publication transition is invalid' USING ERRCODE='23514';
  END IF;

  IF NEW.state IN ('agent_reviewed','pilot') THEN
    IF NEW.authority_kind<>'agent_review' OR NEW.authority_reference_id IS NULL
       OR NOT EXISTS (
         SELECT 1 FROM tutor_learning_item_review_adjudications AS adjudications
         WHERE adjudications.id=NEW.authority_reference_id AND adjudications.version_id=NEW.version_id
           AND adjudications.verdict='approved' AND adjudications.adjudication_hash=NEW.authority_hash
       ) THEN
      RAISE EXCEPTION 'Learning Item review transition lacks approved adjudication' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.state='published' THEN
    IF version_row.risk_tier='high' THEN
      IF NEW.authority_kind<>'human_approval' OR NEW.authority_reference_id IS NULL
         OR NOT EXISTS (
           SELECT 1 FROM tutor_learning_item_human_approvals AS approvals
           WHERE approvals.id=NEW.authority_reference_id AND approvals.version_id=NEW.version_id
             AND approvals.approved AND approvals.approval_hash=NEW.authority_hash
         ) THEN
        RAISE EXCEPTION 'High-risk Learning Item publication requires human approval' USING ERRCODE='23514';
      END IF;
    ELSIF NEW.authority_kind<>'pilot' OR NEW.authority_reference_id IS NULL
       OR NOT EXISTS (
         SELECT 1 FROM tutor_learning_item_pilot_receipts AS pilots
         WHERE pilots.id=NEW.authority_reference_id AND pilots.version_id=NEW.version_id
           AND pilots.decision='promote' AND pilots.receipt_hash=NEW.authority_hash
       ) THEN
      RAISE EXCEPTION 'Learning Item publication requires successful pilot authority' USING ERRCODE='23514';
    END IF;
    IF version_row.item_kind<>'demo' AND NOT EXISTS (
      SELECT 1 FROM tutor_learning_item_practice_materializations AS materializations
      WHERE materializations.version_id=NEW.version_id
    ) THEN
      RAISE EXCEPTION 'Published Learning Item is missing Practice authority' USING ERRCODE='23514';
    END IF;
  ELSIF NEW.state IN ('quarantined','retired') THEN
    IF NEW.authority_kind='pilot' THEN
      IF NEW.authority_reference_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM tutor_learning_item_pilot_receipts AS pilots
        WHERE pilots.id=NEW.authority_reference_id AND pilots.version_id=NEW.version_id
          AND pilots.receipt_hash=NEW.authority_hash
          AND pilots.decision=CASE WHEN NEW.state='quarantined' THEN 'quarantine' ELSE 'retire' END
      ) THEN
        RAISE EXCEPTION 'Learning Item safety transition lacks pilot authority' USING ERRCODE='23514';
      END IF;
    ELSIF NEW.authority_kind<>'operator' OR NEW.authority_reference_id IS NOT NULL THEN
      RAISE EXCEPTION 'Learning Item quarantine/retirement authority is invalid' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
