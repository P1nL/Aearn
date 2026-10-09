-- P7 internal private snapshots; no shared payload, grant, score or bootstrap publication.
-- Existing 440-484 definitions stay unchanged. Parent cascades use existing reset permits.
CREATE UNIQUE INDEX IF NOT EXISTS idx_p7_generation_exact
  ON tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,version_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_p7_facts_exact
  ON tutor_item_supply_private_admission_facts(id,user_id,epoch,scope_id,version_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_p7_evaluation_exact
  ON tutor_item_supply_private_pipeline_receipts(id,user_id,epoch,scope_id,version_id);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_materializations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, version_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  version_payload_hash text NOT NULL CHECK(version_payload_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=1048576
    AND payload_json->'materialization'->>'schema_version' IS NOT DISTINCT FROM 'private_practice_materialization_v1'),
  receipt_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL,
  UNIQUE(user_id,epoch,scope_id,version_id),
  UNIQUE(id,user_id,epoch,scope_id,version_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,version_payload_hash,scope_id)
    REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,payload_hash,scope_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_publication_events (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, version_id uuid NOT NULL,
  generation_artifact_id uuid NOT NULL, facts_receipt_id uuid NOT NULL,
  evaluation_receipt_id uuid NOT NULL, materialization_id uuid NOT NULL,
  -- Expected proof, not an FK: insertion is materialization -> event -> proof.
  proof_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  version_payload_hash text NOT NULL CHECK(version_payload_hash ~ '^[0-9a-f]{64}$'),
  transition_key text NOT NULL CHECK(transition_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  predecessor_event_id uuid, state_version bigint NOT NULL CHECK(state_version>=1),
  state text NOT NULL CHECK(state IN ('published','quarantined','retired')),
  checked_at timestamptz NOT NULL, admission_valid_until timestamptz NOT NULL,
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=65536
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'private_publication_receipt_v1'),
  request_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK((state='published' AND state_version=1 AND predecessor_event_id IS NULL AND checked_at<admission_valid_until)
    OR (state IN ('quarantined','retired') AND state_version>1 AND predecessor_event_id IS NOT NULL)),
  UNIQUE(user_id,epoch,scope_id,version_id,transition_key),
  UNIQUE(user_id,epoch,scope_id,version_id,state_version),
  UNIQUE(predecessor_event_id),
  UNIQUE(id,user_id,epoch,scope_id,version_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,version_payload_hash,scope_id)
    REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,payload_hash,scope_id) ON DELETE CASCADE,
  FOREIGN KEY(materialization_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_materializations(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(facts_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_admission_facts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(evaluation_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_pipeline_receipts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(predecessor_event_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_publication_events(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tutor_item_supply_private_publication_proofs (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  epoch bigint NOT NULL CHECK(epoch>=1), scope_id uuid NOT NULL, version_id uuid NOT NULL,
  publication_id uuid NOT NULL, materialization_id uuid NOT NULL,
  generation_artifact_id uuid NOT NULL, facts_receipt_id uuid NOT NULL, evaluation_receipt_id uuid NOT NULL,
  demand_id uuid NOT NULL,
  source_hash text NOT NULL CHECK(source_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK(content_hash ~ '^[0-9a-f]{64}$'),
  version_payload_hash text NOT NULL CHECK(version_payload_hash ~ '^[0-9a-f]{64}$'),
  payload_json jsonb NOT NULL CHECK(jsonb_typeof(payload_json)='object'
    AND octet_length(payload_json::text)<=1048576
    AND payload_json->>'schema_version' IS NOT DISTINCT FROM 'private_published_coverage_v1'
    AND jsonb_typeof(payload_json->'sources')='array'
    AND jsonb_array_length(payload_json->'sources') BETWEEN 1 AND 12
    AND jsonb_typeof(payload_json->'clauses')='array'
    AND jsonb_array_length(payload_json->'clauses') BETWEEN 1 AND 64),
  proof_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(payload_json)) STORED,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(publication_id),
  UNIQUE(id,user_id,epoch,scope_id,version_id),
  FOREIGN KEY(scope_id,user_id,epoch) REFERENCES tutor_item_supply_private_scopes(id,user_id,epoch) ON DELETE RESTRICT,
  FOREIGN KEY(version_id,user_id,epoch,version_payload_hash,scope_id)
    REFERENCES tutor_item_supply_private_versions(id,user_id,epoch,payload_hash,scope_id) ON DELETE CASCADE,
  FOREIGN KEY(publication_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_publication_events(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(materialization_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_materializations(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(generation_artifact_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_generation_artifacts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(facts_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_admission_facts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(evaluation_receipt_id,user_id,epoch,scope_id,version_id)
    REFERENCES tutor_item_supply_private_pipeline_receipts(id,user_id,epoch,scope_id,version_id) ON DELETE CASCADE,
  FOREIGN KEY(demand_id,user_id,epoch,scope_id)
    REFERENCES tutor_item_supply_private_demands(id,user_id,epoch,scope_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_p7_proof_demand
  ON tutor_item_supply_private_publication_proofs(user_id,epoch,scope_id,demand_id,version_id);

CREATE OR REPLACE FUNCTION enforce_item_supply_private_publication() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE version_row record; previous record; material record; generation record; facts record;
        evaluation record; control record; event_row record; demand_row record;
        body jsonb; scope_body jsonb; expected_content text; stamped timestamptz;
BEGIN
  -- Match reset's user -> epoch -> active-plan order before version/latest locks.
  PERFORM 1 FROM users WHERE id=NEW.user_id AND deleted_at IS NULL FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='private publication owner stale'; END IF;
  PERFORM 1 FROM tutor_item_supply_user_epochs
    WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND enabled FOR SHARE;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='private publication epoch stale'; END IF;
  SELECT s.snapshot_json INTO scope_body FROM tutor_item_supply_private_scopes s
    JOIN tutor_track_active_plans p ON p.track_id=s.track_id AND p.user_id=s.user_id AND p.revision_id=s.revision_id
    WHERE s.id=NEW.scope_id AND s.user_id=NEW.user_id AND s.epoch=NEW.epoch FOR SHARE OF s,p;
  IF NOT FOUND THEN RAISE check_violation USING MESSAGE='private publication scope stale'; END IF;
  SELECT * INTO version_row FROM tutor_item_supply_private_versions
    WHERE id=NEW.version_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
  IF NOT FOUND OR version_row.payload_hash IS DISTINCT FROM NEW.version_payload_hash THEN
    RAISE check_violation USING MESSAGE='private publication version stale';
  END IF;
  body:=CASE WHEN TG_TABLE_NAME='tutor_item_supply_private_materializations'
    THEN NEW.payload_json->'materialization' ELSE NEW.payload_json END;
  IF body->>'user_id' IS DISTINCT FROM NEW.user_id::text OR body->>'epoch' IS DISTINCT FROM NEW.epoch::text
    OR body->>'scope_id' IS DISTINCT FROM NEW.scope_id::text OR body->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR body->>'source_hash' IS DISTINCT FROM NEW.source_hash OR body->>'content_hash' IS DISTINCT FROM NEW.content_hash
    OR body->>'version_payload_hash' IS DISTINCT FROM NEW.version_payload_hash THEN
    RAISE check_violation USING MESSAGE='private publication snapshot identity mismatch';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_materializations' THEN
    expected_content:=item_supply_internal.snapshot_hash(jsonb_build_object(
      'item_key',body->'source'->'public'->>'item_key','version',body->'source'->'public'->>'version',
      'blueprint_hash',item_supply_internal.snapshot_hash(body->'source'->'blueprint'),
      'public_hash',item_supply_internal.snapshot_hash(body->'source'->'public'),
      'private_hash',item_supply_internal.snapshot_hash(body->'source'->'private')));
    IF body->>'materialization_id' IS DISTINCT FROM NEW.id::text
      OR body->'source'->'public' IS DISTINCT FROM version_row.public_json
      OR body->'source'->'private' IS DISTINCT FROM version_row.private_json
      OR NEW.source_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(body->'source')
      OR NEW.content_hash IS DISTINCT FROM expected_content
      OR body->>'runtime_profile_id' IS DISTINCT FROM scope_body->>'runtime_profile_id'
      OR body->>'runtime_profile_hash' IS DISTINCT FROM scope_body->>'runtime_profile_hash'
      OR body->>'scorer_version' IS DISTINCT FROM scope_body->>'scorer_version'
      OR body->>'adapter_version' IS DISTINCT FROM 'learning_item_practice_adapter_v1'
      OR (body->>'created_at')::timestamptz IS DISTINCT FROM NEW.created_at THEN
      RAISE check_violation USING MESSAGE='private materialization snapshot mismatch';
    END IF;
    RETURN NEW;
  END IF;
  SELECT * INTO material FROM tutor_item_supply_private_materializations
    WHERE id=NEW.materialization_id AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND scope_id=NEW.scope_id AND version_id=NEW.version_id;
  SELECT * INTO generation FROM tutor_item_supply_private_generation_artifacts
    WHERE id=NEW.generation_artifact_id AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND scope_id=NEW.scope_id AND version_id=NEW.version_id;
  SELECT * INTO facts FROM tutor_item_supply_private_admission_facts
    WHERE id=NEW.facts_receipt_id AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND scope_id=NEW.scope_id AND version_id=NEW.version_id;
  SELECT * INTO evaluation FROM tutor_item_supply_private_pipeline_receipts
    WHERE id=NEW.evaluation_receipt_id AND user_id=NEW.user_id AND epoch=NEW.epoch
      AND scope_id=NEW.scope_id AND version_id=NEW.version_id;
  IF material.id IS NULL OR generation.id IS NULL OR facts.id IS NULL OR evaluation.id IS NULL
    OR generation.mode IS DISTINCT FROM 'live' OR evaluation.mode IS DISTINCT FROM 'live'
    OR generation.source_hash IS DISTINCT FROM NEW.source_hash OR generation.content_hash IS DISTINCT FROM NEW.content_hash
    OR material.source_hash IS DISTINCT FROM NEW.source_hash OR material.content_hash IS DISTINCT FROM NEW.content_hash
    OR facts.generation_artifact_id IS DISTINCT FROM NEW.generation_artifact_id
    OR evaluation.generation_artifact_id IS DISTINCT FROM NEW.generation_artifact_id
    OR facts.job_id IS DISTINCT FROM evaluation.job_id
    OR facts.lease_generation IS DISTINCT FROM evaluation.lease_generation
    OR facts.lease_state_version IS DISTINCT FROM evaluation.lease_state_version
    OR evaluation.artifact_kind IS DISTINCT FROM 'admission_evaluation'
    OR evaluation.payload_json->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR evaluation.payload_json->>'publication_enabled' IS DISTINCT FROM 'false'
    OR evaluation.payload_json->'binding' IS DISTINCT FROM facts.payload_json->'evidence'->'binding'
    OR evaluation.payload_json->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(facts.payload_json->'evidence')
    OR body->>'materialization_id' IS DISTINCT FROM NEW.materialization_id::text
    OR body->>'generation_artifact_id' IS DISTINCT FROM NEW.generation_artifact_id::text
    OR body->>'facts_receipt_id' IS DISTINCT FROM NEW.facts_receipt_id::text
    OR body->>'evaluation_receipt_id' IS DISTINCT FROM NEW.evaluation_receipt_id::text THEN
    RAISE check_violation USING MESSAGE='private publication parents mismatch';
  END IF;
  IF TG_TABLE_NAME='tutor_item_supply_private_publication_events' THEN
    IF body->>'publication_id' IS DISTINCT FROM NEW.id::text OR body->>'proof_id' IS DISTINCT FROM NEW.proof_id::text
      OR body->>'handle' IS DISTINCT FROM version_row.handle OR body->>'transition_key' IS DISTINCT FROM NEW.transition_key
      OR body->>'predecessor_event_id' IS DISTINCT FROM NEW.predecessor_event_id::text
      OR body->>'state_version' IS DISTINCT FROM NEW.state_version::text OR body->>'state' IS DISTINCT FROM NEW.state
      OR (body->>'checked_at')::timestamptz IS DISTINCT FROM NEW.checked_at
      OR (body->>'admission_valid_until')::timestamptz IS DISTINCT FROM NEW.admission_valid_until THEN
      RAISE check_violation USING MESSAGE='private publication event mismatch';
    END IF;
    -- Exact immutable replay does not renew expiry or resurrect state.
    SELECT * INTO previous FROM tutor_item_supply_private_publication_events
      WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id
        AND version_id=NEW.version_id AND transition_key=NEW.transition_key;
    IF FOUND THEN
      IF previous.id=NEW.id AND previous.payload_json=NEW.payload_json THEN RETURN NEW; END IF;
      RAISE check_violation USING MESSAGE='private publication replay conflict';
    END IF;
    SELECT * INTO previous FROM tutor_item_supply_private_publication_events
      WHERE user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id AND version_id=NEW.version_id
      ORDER BY state_version DESC LIMIT 1;
    IF previous.id IS NOT NULL THEN
      IF NEW.predecessor_event_id IS DISTINCT FROM previous.id OR NEW.state_version<>previous.state_version+1
        OR previous.state='retired' OR NEW.state='published'
        OR (previous.state='quarantined' AND NEW.state<>'retired')
        OR NEW.checked_at<previous.checked_at
        OR (NEW.payload_json - ARRAY['publication_id','transition_key','predecessor_event_id','state_version','state','checked_at'])
          IS DISTINCT FROM (previous.payload_json - ARRAY['publication_id','transition_key','predecessor_event_id','state_version','state','checked_at']) THEN
        RAISE check_violation USING MESSAGE='private publication successor conflict';
      END IF;
      RETURN NEW;
    END IF;
    IF NEW.state<>'published' OR NEW.state_version<>1 OR NEW.predecessor_event_id IS NOT NULL THEN
      RAISE check_violation USING MESSAGE='private publication initial state invalid';
    END IF;
    SELECT * INTO control FROM tutor_item_supply_private_job_controls
      WHERE job_id=facts.job_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id FOR UPDATE;
    stamped:=clock_timestamp();
    IF NOT FOUND OR control.lease_generation<>facts.lease_generation OR control.state_version<>facts.lease_state_version
      OR control.lease_owner IS DISTINCT FROM facts.lease_owner
      OR control.state NOT IN ('leased','reviewing','simulating','admitting')
      OR control.lease_expires_at IS NULL OR control.lease_expires_at<=stamped OR control.parent_deadline<=stamped
      OR NEW.checked_at>stamped OR NEW.admission_valid_until<=stamped
      OR NEW.admission_valid_until>LEAST(control.lease_expires_at,control.parent_deadline)
      OR NEW.checked_at IS DISTINCT FROM (facts.payload_json->'coverage'->>'checked_at')::timestamptz
      OR NEW.admission_valid_until IS DISTINCT FROM (facts.payload_json->'coverage'->>'valid_until')::timestamptz THEN
      RAISE check_violation USING MESSAGE='private publication current admission stale';
    END IF;
  ELSE
    SELECT * INTO event_row FROM tutor_item_supply_private_publication_events
      WHERE id=NEW.publication_id AND user_id=NEW.user_id AND epoch=NEW.epoch
        AND scope_id=NEW.scope_id AND version_id=NEW.version_id;
    SELECT * INTO demand_row FROM tutor_item_supply_private_demands
      WHERE id=NEW.demand_id AND user_id=NEW.user_id AND epoch=NEW.epoch AND scope_id=NEW.scope_id;
    IF event_row.id IS NULL OR demand_row.id IS NULL OR event_row.state<>'published'
      OR event_row.proof_id IS DISTINCT FROM NEW.id
      OR event_row.materialization_id IS DISTINCT FROM NEW.materialization_id
      OR event_row.generation_artifact_id IS DISTINCT FROM NEW.generation_artifact_id
      OR event_row.facts_receipt_id IS DISTINCT FROM NEW.facts_receipt_id
      OR event_row.evaluation_receipt_id IS DISTINCT FROM NEW.evaluation_receipt_id
      OR body->>'proof_id' IS DISTINCT FROM NEW.id::text OR body->>'publication_id' IS DISTINCT FROM NEW.publication_id::text
      OR body->>'demand_id' IS DISTINCT FROM NEW.demand_id::text
      OR body->'demand' IS DISTINCT FROM demand_row.snapshot_json
      OR body->'demand' IS DISTINCT FROM facts.payload_json->'coverage'->'demand'
      OR body->'blueprint' IS DISTINCT FROM facts.payload_json->'coverage'->'coverage_blueprint'
      OR body->'demand'->'scope' IS DISTINCT FROM scope_body
      OR (body->>'checked_at')::timestamptz IS DISTINCT FROM event_row.checked_at
      OR (body->>'valid_until')::timestamptz IS DISTINCT FROM event_row.admission_valid_until
      OR (NOT EXISTS(SELECT 1 FROM tutor_item_supply_private_publication_proofs p WHERE p.id=NEW.id)
          AND event_row.admission_valid_until<=clock_timestamp())
      OR EXISTS(SELECT 1 FROM tutor_item_supply_private_publication_events e WHERE e.predecessor_event_id=event_row.id)
      OR (SELECT jsonb_agg(s->'material' ORDER BY ord) FROM jsonb_array_elements(body->'sources') WITH ORDINALITY b(s,ord))
        IS DISTINCT FROM generation.request_json->'materials'
      OR (SELECT jsonb_agg(s->'receipt' ORDER BY ord) FROM jsonb_array_elements(body->'sources') WITH ORDINALITY b(s,ord))
        IS DISTINCT FROM generation.receipt_json->'sources' THEN
      RAISE check_violation USING MESSAGE='private published coverage mismatch';
    END IF;
  END IF;
  -- Structural guards do not authenticate P5 seals. The concrete publisher must
  -- also invoke the actual same-connection facts owner before these writes.
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_item_supply_private_publication() FROM PUBLIC;

DO $$ DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY['tutor_item_supply_private_materializations',
    'tutor_item_supply_private_publication_events','tutor_item_supply_private_publication_proofs'] LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS p7_00_epoch ON %I',table_name);
    EXECUTE format('CREATE TRIGGER p7_00_epoch BEFORE INSERT OR UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_epoch()',table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS p7_10_insert ON %I',table_name);
    EXECUTE format('CREATE TRIGGER p7_10_insert BEFORE INSERT ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_private_publication()',table_name);
    EXECUTE format('DROP TRIGGER IF EXISTS p7_20_immutable ON %I',table_name);
    EXECUTE format('CREATE TRIGGER p7_20_immutable BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION enforce_item_supply_immutable(''private'')',table_name);
  END LOOP;
END $$;

-- Existing purge first deletes pipeline receipts/generation: cascade events and
-- proofs (including successors) under the already-issued permit. Demand cascade
-- also cleans proofs; later version deletion cleans materializations. No new
-- permit/grant, TRUNCATE, trigger bypass, or replacement of historical purge SQL.
