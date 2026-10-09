-- Original Learning Item Bank, explicit autonomous_evidence_policy_v2 branch.
-- B1d internal publication only; no V1 pilot/review/human receipt fabrication.
CREATE TABLE IF NOT EXISTS tutor_learning_item_native_publication_proofs (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  generation_artifact_id uuid NOT NULL REFERENCES tutor_item_supply_shared_generation_artifacts(id) ON DELETE RESTRICT,
  facts_receipt_id uuid NOT NULL UNIQUE REFERENCES tutor_item_supply_shared_admission_facts(id) ON DELETE RESTRICT,
  evaluation_receipt_id uuid NOT NULL REFERENCES tutor_item_supply_shared_pipeline_receipts(id) ON DELETE RESTRICT,
  materialization_id uuid NOT NULL REFERENCES tutor_learning_item_practice_materializations(id) DEFERRABLE INITIALLY DEFERRED,
  publication_event_id uuid NOT NULL UNIQUE REFERENCES tutor_learning_item_publication_events(id) DEFERRABLE INITIALLY DEFERRED,
  proof_json jsonb NOT NULL CHECK(jsonb_typeof(proof_json)='object' AND octet_length(proof_json::text)<=2097152
    AND (proof_json->>'schema_version') IS NOT DISTINCT FROM 'native_learning_item_publication_v1'),
  proof_hash text GENERATED ALWAYS AS (item_supply_internal.snapshot_hash(proof_json)) STORED,
  runner_material_json jsonb NOT NULL CHECK(jsonb_typeof(runner_material_json)='object' AND octet_length(runner_material_json::text)<=2097152),
  publication_txid bigint NOT NULL DEFAULT txid_current(),
  publication_enabled boolean NOT NULL DEFAULT false CHECK(publication_enabled=false),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- No DEFAULT/backfill: historical and V1 materializations keep NULL. Native
-- publication explicitly records the top-level caller transaction, not a
-- savepoint's xmin. The original immutable-row guard protects this marker too.
ALTER TABLE tutor_learning_item_practice_materializations
  ADD COLUMN IF NOT EXISTS native_publication_txid bigint;

CREATE OR REPLACE FUNCTION enforce_learning_item_native_materialization_txid() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
BEGIN
  IF NEW.native_publication_txid IS NOT NULL AND (
    NEW.native_publication_txid IS DISTINCT FROM txid_current()
    OR NOT EXISTS(SELECT 1 FROM tutor_learning_item_native_publication_proofs p
      WHERE p.materialization_id=NEW.id AND p.version_id=NEW.version_id
        AND p.publication_txid=NEW.native_publication_txid)
  ) THEN
    RAISE check_violation USING MESSAGE='native materialization parent transaction proof required';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_learning_item_native_materialization_txid() FROM PUBLIC;
DROP TRIGGER IF EXISTS native_materialization_parent_tx ON tutor_learning_item_practice_materializations;
CREATE TRIGGER native_materialization_parent_tx BEFORE INSERT ON tutor_learning_item_practice_materializations
  FOR EACH ROW EXECUTE FUNCTION enforce_learning_item_native_materialization_txid();

CREATE OR REPLACE FUNCTION enforce_learning_item_native_publication_proof() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p jsonb:=NEW.proof_json; f record; e record; g record; v record; c record; snapshot jsonb; t timestamptz;
  clause_data jsonb;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR NEW.publication_txid<>txid_current() THEN
    RAISE check_violation USING MESSAGE='native publication isolated caller transaction required';
  END IF;
  SELECT * INTO f FROM tutor_item_supply_shared_admission_facts WHERE id=NEW.facts_receipt_id FOR SHARE;
  SELECT * INTO e FROM tutor_item_supply_shared_pipeline_receipts WHERE id=NEW.evaluation_receipt_id FOR SHARE;
  SELECT * INTO g FROM tutor_item_supply_shared_generation_artifacts WHERE id=NEW.generation_artifact_id;
  SELECT r.*,v1.handle,v1.content_hash AS version_content_hash,v1.risk_tier INTO v
    FROM tutor_learning_item_validation_receipts r JOIN tutor_learning_item_versions v1 ON v1.id=r.version_id
    WHERE r.id=(p->>'bank_validation_id')::uuid AND r.version_id=NEW.version_id;
  IF f.id IS NULL OR e.id IS NULL OR g.id IS NULL OR v.id IS NULL THEN
    RAISE check_violation USING MESSAGE='native publication typed authority missing';
  END IF;
  IF f.version_id<>NEW.version_id OR f.generation_artifact_id<>g.id OR g.version_id<>NEW.version_id
    OR e.generation_artifact_id<>g.id OR e.job_id<>f.job_id OR e.lease_generation<>f.lease_generation
    OR e.artifact_kind<>'admission_evaluation' OR e.schema_version<>'item_supply_admission_evaluation_v2'
    OR e.payload_json IS DISTINCT FROM f.payload_json->'evaluation'
    OR e.payload_json->>'disposition' IS DISTINCT FROM 'eligible_internal'
    OR e.payload_json->>'policy_version' IS DISTINCT FROM 'autonomous_evidence_policy_v2'
    OR e.payload_json->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR f.payload_json->'target_proof' IS NULL OR f.payload_json->'target_proof'='null'::jsonb
    OR v.schema_version<>'candidate_validation_v2' OR v.passed IS NOT NULL
    OR v.native_generation_artifact_id<>g.id OR v.native_validation_receipt_id<>f.validation_receipt_id
    OR v.receipt_hash IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR v.native_specification_hash IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR e.payload_json->'binding'->>'risk_tier' IS DISTINCT FROM v.risk_tier
    OR p->>'proof_id' IS DISTINCT FROM NEW.id::text OR p->>'version_id' IS DISTINCT FROM NEW.version_id::text
    OR p->>'item_handle' IS DISTINCT FROM v.handle OR p->>'content_hash' IS DISTINCT FROM v.version_content_hash
    OR p->>'source_hash' IS DISTINCT FROM g.source_hash OR p->>'content_hash' IS DISTINCT FROM g.content_hash
    OR p->>'generation_artifact_id' IS DISTINCT FROM g.id::text
    OR p->>'facts_receipt_id' IS DISTINCT FROM f.id::text OR p->>'facts_hash' IS DISTINCT FROM f.payload_hash
    OR p->>'evaluation_receipt_id' IS DISTINCT FROM e.id::text OR p->>'evaluation_hash' IS DISTINCT FROM e.receipt_hash
    OR p->>'evidence_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(f.payload_json->'evidence')
    OR p->>'evidence_hash' IS DISTINCT FROM e.payload_json->>'evidence_hash'
    OR p->>'validation_receipt_id' IS DISTINCT FROM f.validation_receipt_id::text
    OR p->>'validation_hash' IS DISTINCT FROM f.payload_json->>'validation_receipt_hash'
    OR p->>'review_receipt_id' IS DISTINCT FROM f.review_receipt_id::text
    OR p->>'review_hash' IS DISTINCT FROM f.payload_json->>'review_receipt_hash'
    OR p->'lease' IS DISTINCT FROM f.payload_json->'lease'
    OR p->>'specification_hash' IS DISTINCT FROM f.payload_json->>'specification_hash'
    OR p->>'target_id' IS DISTINCT FROM g.target_id OR p->>'target_definition_hash' IS DISTINCT FROM g.target_definition_hash
    OR p->'materials' IS DISTINCT FROM g.request_json->'materials'
    OR p->'source_receipts' IS DISTINCT FROM g.receipt_json->'sources'
    OR p->'runtime'->>'runtime_profile_hash' IS DISTINCT FROM f.payload_json->>'runtime_profile_hash'
    OR p->'runtime'->>'scorer_version' IS DISTINCT FROM f.payload_json->>'scorer_version'
    OR p->>'policy_hash' IS DISTINCT FROM e.payload_json->'binding'->>'policy_hash'
    OR p->>'materialization_id' IS DISTINCT FROM NEW.materialization_id::text
    OR p->>'publication_event_id' IS DISTINCT FROM NEW.publication_event_id::text
    OR p->>'runner_material_hash' IS DISTINCT FROM item_supply_internal.snapshot_hash(NEW.runner_material_json)
    OR p->>'origin' IS DISTINCT FROM 'native_internal_b1d'
    OR p->'publication_enabled' IS DISTINCT FROM 'false'::jsonb
    OR p->'inventory_ready' IS DISTINCT FROM 'false'::jsonb OR p->>'family_independence_status' IS DISTINCT FROM 'pending' THEN
    RAISE check_violation USING MESSAGE='native publication exact V2 provenance mismatch';
  END IF;
  SELECT jsonb_agg(jsonb_build_object('clause_id',m->>'clause_id','clause_hash',m->>'clause_hash',
    'interpretation_hash',m->>'interpretation_hash') ORDER BY n) INTO clause_data
    FROM jsonb_array_elements(f.payload_json->'target_proof'->'mappings') WITH ORDINALITY AS clauses(m,n);
  IF p->'clauses' IS DISTINCT FROM clause_data OR jsonb_array_length(clause_data)<>3 THEN
    RAISE check_violation USING MESSAGE='native publication target clauses missing';
  END IF;
  IF v.risk_tier='high' AND (jsonb_array_length(e.payload_json->'bundle_hashes')<2
      OR jsonb_array_length(f.payload_json->'evidence'->'risk_evidence')=0) THEN
    RAISE check_violation USING MESSAGE='native high risk requires actual V2 adapters and independent bundle';
  END IF;
  IF g.target_id='python-kc-binding-v1' THEN
    IF p->'runtime'->'runtime_lock' IS DISTINCT FROM 'null'::jsonb
      OR p->'runtime'->'runner_version' IS DISTINCT FROM 'null'::jsonb
      OR f.payload_json->'validation_terminals' IS DISTINCT FROM '[]'::jsonb THEN
      RAISE check_violation USING MESSAGE='native static publication cannot claim OS authority';
    END IF;
  ELSIF jsonb_typeof(p->'runtime'->'runtime_lock') IS DISTINCT FROM 'object'
      OR jsonb_array_length(f.payload_json->'validation_terminals')=0 THEN
    RAISE check_violation USING MESSAGE='native runtime publication requires actual sealed evidence';
  END IF;
  SELECT * INTO c FROM tutor_item_supply_shared_job_controls WHERE job_id=f.job_id FOR SHARE;
  snapshot:=CASE WHEN c.profile_snapshot_json->>'schema_version'='item_supply_job_snapshot_v1'
    THEN c.profile_snapshot_json->'profile' ELSE c.profile_snapshot_json END;
  t:=clock_timestamp();
  IF c.id IS NULL OR c.state<>'leased' OR c.lease_owner<>f.lease_owner OR c.lease_generation<>f.lease_generation
    OR c.state_version<>f.lease_state_version OR c.lease_expires_at<=t OR c.parent_deadline<=t
    OR snapshot IS DISTINCT FROM p->'lease'->'profile' OR (p->>'checked_at')::timestamptz>t
    OR (p->>'valid_until')::timestamptz<=t
    OR (p->>'valid_until')::timestamptz>LEAST(c.lease_expires_at,c.parent_deadline,(f.payload_json->>'valid_until')::timestamptz) THEN
    RAISE check_violation USING MESSAGE='native publication current facts/lease expired';
  END IF;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION enforce_learning_item_native_publication_proof() FROM PUBLIC;
DROP TRIGGER IF EXISTS native_publication_proof ON tutor_learning_item_native_publication_proofs;
CREATE TRIGGER native_publication_proof BEFORE INSERT ON tutor_learning_item_native_publication_proofs
  FOR EACH ROW EXECUTE FUNCTION enforce_learning_item_native_publication_proof();
DROP TRIGGER IF EXISTS native_publication_immutable ON tutor_learning_item_native_publication_proofs;
CREATE TRIGGER native_publication_immutable BEFORE UPDATE OR DELETE ON tutor_learning_item_native_publication_proofs
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();

CREATE OR REPLACE FUNCTION item_supply_internal.native_publication_event_allowed(ev tutor_learning_item_publication_events)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p record; previous record; expected uuid; required_state text; required_version integer;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' OR ev.authority_kind<>'native_v2'
    OR ev.policy_version<>'autonomous_evidence_policy_v2' THEN RETURN false; END IF;
  SELECT q.* INTO p
    FROM tutor_learning_item_native_publication_proofs q WHERE id=ev.authority_reference_id AND version_id=ev.version_id;
  IF NOT FOUND OR p.publication_txid<>txid_current() OR ev.authority_hash<>p.proof_hash
    OR ev.content_hash IS DISTINCT FROM p.proof_json->>'content_hash' OR ev.item_handle IS DISTINCT FROM p.proof_json->>'item_handle'
    OR ev.occurred_at<(p.proof_json->>'checked_at')::timestamptz
    OR ev.occurred_at>=(p.proof_json->>'valid_until')::timestamptz OR ev.occurred_at>clock_timestamp()
    OR ev.transition_key IS DISTINCT FROM 'native.'||ev.state||'.'||replace(p.facts_receipt_id::text,'-','')
    OR ev.request_hash IS DISTINCT FROM item_supply_internal.snapshot_hash(jsonb_build_object(
      'proof_hash',p.proof_hash,'state',ev.state,'predecessor',ev.predecessor_event_id::text))
    OR clock_timestamp()>=(p.proof_json->>'valid_until')::timestamptz THEN RETURN false; END IF;
  CASE ev.state
    WHEN 'agent_reviewed' THEN expected:=(p.proof_json->>'review_event_id')::uuid; required_state:='machine_verified'; required_version:=2;
    WHEN 'pilot' THEN expected:=(p.proof_json->>'pilot_event_id')::uuid; required_state:='agent_reviewed'; required_version:=3;
    WHEN 'published' THEN expected:=p.publication_event_id; required_state:='pilot'; required_version:=4;
    ELSE RETURN false;
  END CASE;
  SELECT * INTO previous FROM tutor_learning_item_publication_events WHERE version_id=ev.version_id ORDER BY state_version DESC LIMIT 1;
  IF NOT FOUND OR previous.state<>required_state OR ev.id<>expected OR ev.state_version<>required_version
    OR previous.state_version+1<>ev.state_version OR ev.predecessor_event_id IS DISTINCT FROM previous.id THEN RETURN false; END IF;
  IF ev.state='published' AND NOT EXISTS(SELECT 1 FROM tutor_learning_item_practice_materializations m
    WHERE m.id=p.materialization_id AND m.version_id=ev.version_id AND m.receipt_hash=p.proof_json->>'materialization_hash'
      AND m.native_publication_txid=p.publication_txid) THEN RETURN false; END IF;
  RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.native_publication_event_allowed(tutor_learning_item_publication_events) FROM PUBLIC;

CREATE OR REPLACE FUNCTION item_supply_internal.native_materialization_allowed(m tutor_learning_item_practice_materializations)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,item_supply_internal,pg_temp AS $$
DECLARE p record; e record; rubric record; version_row record; current_state text; expected_goal jsonb;
  source_private jsonb; expected_tests jsonb; expected_reference jsonb;
BEGIN
  IF current_database()<>'aearn_b1d_sandbox_20261001' THEN RETURN false; END IF;
  SELECT q.* INTO p
    FROM tutor_learning_item_native_publication_proofs q WHERE materialization_id=m.id AND version_id=m.version_id;
  IF NOT FOUND OR p.publication_txid<>txid_current()
    OR m.native_publication_txid IS DISTINCT FROM p.publication_txid
    OR m.receipt_hash IS DISTINCT FROM p.proof_json->>'materialization_hash'
    OR m.exercise_version_id::text IS DISTINCT FROM p.proof_json->>'exercise_version_id'
    OR m.content_hash IS DISTINCT FROM p.proof_json->>'content_hash' OR m.item_handle IS DISTINCT FROM p.proof_json->>'item_handle'
    OR clock_timestamp()>=(p.proof_json->>'valid_until')::timestamptz THEN RETURN false; END IF;
  SELECT state INTO current_state FROM tutor_learning_item_publication_events WHERE version_id=m.version_id ORDER BY state_version DESC LIMIT 1;
  SELECT * INTO e FROM tutor_exercise_versions WHERE id=m.exercise_version_id;
  SELECT * INTO rubric FROM tutor_exercise_private_rubrics WHERE exercise_version_id=m.exercise_version_id;
  SELECT * INTO version_row FROM tutor_learning_item_versions WHERE id=m.version_id;
  IF current_state<>'pilot' OR e.id IS NULL OR rubric.id IS NULL OR version_row.id IS NULL OR e.source_kind<>'registered_author'
    OR e.exercise_key<>version_row.item_key OR e.version<>version_row.version OR e.language_id<>version_row.language_id
    OR m.exercise_key<>e.exercise_key OR m.exercise_version<>e.version
    OR e.validation_status<>'ready' OR e.content_hash<>m.exercise_content_hash OR rubric.rubric_hash<>m.rubric_hash
    OR m.receipt_hash<>item_supply_internal.snapshot_hash(jsonb_build_object(
      'adapter_version',m.adapter_version,'learning_item_version_id',m.version_id::text,
      'learning_item_handle',m.item_handle,'learning_item_content_hash',m.content_hash,
      'exercise_version_id',m.exercise_version_id::text,'exercise_content_hash',m.exercise_content_hash,'rubric_hash',m.rubric_hash)) THEN RETURN false; END IF;
  SELECT prep.payload_json->'spec'->'python_goal' INTO expected_goal
    FROM tutor_item_supply_shared_admission_facts f JOIN tutor_item_supply_shared_validation_preparations prep
      ON prep.id=f.validation_preparation_id WHERE f.id=p.facts_receipt_id;
  SELECT source_json->'private'->'content' INTO source_private FROM tutor_item_supply_shared_generation_artifacts
    WHERE id=p.generation_artifact_id;
  expected_tests:=source_private->'tests';
  IF p.proof_json->>'target_id'='python-state-update-v1' THEN
    SELECT jsonb_agg(t||jsonb_build_object('input_json',jsonb_build_object('goal_contract',expected_goal)) ORDER BY n)
      INTO expected_tests FROM jsonb_array_elements(expected_tests) WITH ORDINALITY AS cases(t,n);
    expected_reference:=jsonb_build_object('content',source_private->>'standard_answer');
  ELSIF p.proof_json->>'target_id'='sqlite-predicate-order-v1' THEN
    expected_reference:=jsonb_build_object('content',source_private->>'standard_query');
  ELSE
    expected_reference:=jsonb_build_object('accepted_answers',source_private->'accepted_answers',
      'answer_explanation_markdown',source_private->>'answer_explanation_markdown');
  END IF;
  IF jsonb_array_length(expected_tests)<1 OR rubric.private_test_bundle_json IS DISTINCT FROM expected_tests
    OR rubric.reference_answer_json IS DISTINCT FROM expected_reference
    OR rubric.score_policy_json IS DISTINCT FROM source_private->'score_policy' THEN RETURN false; END IF;
  IF p.proof_json->>'target_id'='python-state-update-v1' AND (
    p.runner_material_json->'test_cases' IS DISTINCT FROM rubric.private_test_bundle_json
    OR EXISTS(SELECT 1 FROM jsonb_array_elements(rubric.private_test_bundle_json) t
      WHERE t->'input_json'->'goal_contract' IS DISTINCT FROM expected_goal
        OR t->'input_json'->'goal_contract'->>'goal_contract_id' IS DISTINCT FROM 'python-state-update-v1')) THEN RETURN false; END IF;
  RETURN true;
END $$;
REVOKE ALL ON FUNCTION item_supply_internal.native_materialization_allowed(tutor_learning_item_practice_materializations) FROM PUBLIC;

-- Add an authority alternative, not a replacement of V1 rules or event history.
ALTER TABLE tutor_learning_item_publication_events DROP CONSTRAINT IF EXISTS tutor_learning_item_publication_events_authority_kind_check;
ALTER TABLE tutor_learning_item_publication_events ADD CONSTRAINT tutor_learning_item_publication_events_authority_kind_check
  CHECK(authority_kind IN ('validation','agent_review','pilot','human_approval','operator','native_v2'));
DO $$ DECLARE definition text; marker text; injected text; BEGIN
  definition:=pg_get_functiondef('enforce_tutor_learning_item_publication_insert()'::regprocedure);
  marker:='  IF NEW.predecessor_event_id IS DISTINCT FROM current_event.id';
  injected:='  -- native_v2_current_publication_branch'||chr(10)||
    '  IF EXISTS(SELECT 1 FROM tutor_learning_item_validation_receipts WHERE version_id=NEW.version_id AND schema_version=''candidate_validation_v2'') AND NEW.state IN (''agent_reviewed'',''pilot'',''published'') THEN'||chr(10)||
    '    IF item_supply_internal.native_publication_event_allowed(NEW) IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE=''native V2 publication requires current same-transaction proof''; END IF;'||chr(10)||
    '    RETURN NEW;'||chr(10)||'  END IF;'||chr(10)||marker;
  IF strpos(definition,'native_v2_current_publication_branch')>0 THEN NULL;
  ELSIF strpos(definition,marker)=0 THEN RAISE check_violation USING MESSAGE='494 publication lineage transition shape changed';
  ELSE EXECUTE replace(definition,marker,injected); END IF;
  definition:=pg_get_functiondef('enforce_tutor_learning_item_materialization_insert()'::regprocedure);
  marker:='  SELECT item_kind,item_key,version INTO version_row FROM tutor_learning_item_versions WHERE id=NEW.version_id FOR UPDATE;';
  injected:='  -- native_v2_current_materialization_branch'||chr(10)||
    '  IF EXISTS(SELECT 1 FROM tutor_learning_item_validation_receipts WHERE version_id=NEW.version_id AND schema_version=''candidate_validation_v2'') THEN'||chr(10)||
    '    IF item_supply_internal.native_materialization_allowed(NEW) IS DISTINCT FROM true THEN RAISE check_violation USING MESSAGE=''native V2 materialization requires current same-transaction proof''; END IF;'||chr(10)||
    '    RETURN NEW;'||chr(10)||'  END IF;'||chr(10)||marker;
  IF strpos(definition,'native_v2_current_materialization_branch')>0 THEN NULL;
  ELSIF strpos(definition,marker)=0 THEN RAISE check_violation USING MESSAGE='494 materialization transition shape changed';
  ELSE EXECUTE replace(definition,marker,injected); END IF;
END $$;
