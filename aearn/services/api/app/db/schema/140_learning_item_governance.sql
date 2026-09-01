-- Child 11 review/pilot/publication authority. All rows are shared immutable
-- governance evidence bound to one exact Learning Item content hash.

ALTER TABLE tutor_learning_item_versions
  ADD COLUMN IF NOT EXISTS creator_identity text NOT NULL DEFAULT 'curated.manual';
ALTER TABLE tutor_learning_item_versions
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_item_versions_creator_identity;
ALTER TABLE tutor_learning_item_versions
  ADD CONSTRAINT chk_tutor_learning_item_versions_creator_identity
  CHECK (creator_identity ~ '^[a-z0-9][a-z0-9._:-]{0,159}$');

ALTER TABLE tutor_learning_item_publication_events
  ADD COLUMN IF NOT EXISTS authority_reference_id uuid;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_tutor_exercise_versions_item_bank_scope') THEN
    ALTER TABLE tutor_exercise_versions ADD CONSTRAINT uq_tutor_exercise_versions_item_bank_scope
      UNIQUE (id,exercise_key,version,content_hash);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_tutor_exercise_private_rubrics_hash_scope') THEN
    ALTER TABLE tutor_exercise_private_rubrics ADD CONSTRAINT uq_tutor_exercise_private_rubrics_hash_scope
      UNIQUE (exercise_version_id,rubric_hash);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_learning_item_review_reports (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL,
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  role text NOT NULL CHECK (role IN ('curriculum','difficulty','technical','ambiguity','security','adversarial')),
  reviewer_identity text NOT NULL CHECK (reviewer_identity ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  review_key text NOT NULL CHECK (review_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  review_input_hash text NOT NULL CHECK (review_input_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version='learning_item_review_report_v1'),
  policy_version text NOT NULL CHECK (policy_version='learning_item_agent_review_policy_v1'),
  verdict text NOT NULL CHECK (verdict IN ('approved','changes_required','rejected')),
  highest_severity text NOT NULL CHECK (highest_severity IN ('none','info','minor','major','critical')),
  blocker_count integer NOT NULL CHECK (blocker_count BETWEEN 0 AND 24),
  blocker_kinds_json jsonb NOT NULL CHECK (
    jsonb_typeof(blocker_kinds_json)='array' AND jsonb_array_length(blocker_kinds_json)<=11
    AND blocker_kinds_json <@ '["deterministic_failure","security","unique_answer","rubric_mismatch","data_leakage","technical_failure","curriculum_mismatch","difficulty_mismatch","ambiguity","adversarial_exploit","review_changes_required"]'::jsonb
  ),
  findings_json jsonb NOT NULL CHECK (
    jsonb_typeof(findings_json)='array' AND jsonb_array_length(findings_json)<=24
    AND octet_length(findings_json::text)<=65536
  ),
  report_hash text NOT NULL UNIQUE CHECK (report_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  CONSTRAINT uq_tutor_learning_item_review_role UNIQUE (version_id,role,policy_version),
  CONSTRAINT uq_tutor_learning_item_review_reviewer UNIQUE (version_id,reviewer_identity,policy_version),
  CONSTRAINT uq_tutor_learning_item_review_key UNIQUE (version_id,review_key),
  CONSTRAINT uq_tutor_learning_item_review_scope UNIQUE (id,version_id,report_hash),
  CONSTRAINT fk_tutor_learning_item_review_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_review_adjudications (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL,
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  adjudication_key text NOT NULL CHECK (adjudication_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version='learning_item_review_adjudication_v1'),
  policy_version text NOT NULL CHECK (policy_version='learning_item_agent_review_policy_v1'),
  risk_tier text NOT NULL CHECK (risk_tier IN ('low','medium','high')),
  required_roles_json jsonb NOT NULL CHECK (
    required_roles_json='["curriculum","difficulty","technical","ambiguity","security","adversarial"]'::jsonb
  ),
  report_hashes_json jsonb NOT NULL CHECK (
    jsonb_typeof(report_hashes_json)='object' AND octet_length(report_hashes_json::text)<=2048
  ),
  verdict text NOT NULL CHECK (verdict IN ('approved','rejected')),
  highest_severity text NOT NULL CHECK (highest_severity IN ('none','info','minor','major','critical')),
  blocker_kinds_json jsonb NOT NULL CHECK (
    jsonb_typeof(blocker_kinds_json)='array' AND jsonb_array_length(blocker_kinds_json)<=11
    AND blocker_kinds_json <@ '["deterministic_failure","security","unique_answer","rubric_mismatch","data_leakage","technical_failure","curriculum_mismatch","difficulty_mismatch","ambiguity","adversarial_exploit","review_changes_required"]'::jsonb
  ),
  machine_execution_verified boolean NOT NULL,
  adjudication_hash text NOT NULL UNIQUE CHECK (adjudication_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL,
  CONSTRAINT uq_tutor_learning_item_adjudication_policy UNIQUE (version_id,policy_version),
  CONSTRAINT uq_tutor_learning_item_adjudication_key UNIQUE (version_id,adjudication_key),
  CONSTRAINT uq_tutor_learning_item_adjudication_scope UNIQUE (id,version_id,adjudication_hash),
  CONSTRAINT fk_tutor_learning_item_adjudication_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_pilot_receipts (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL,
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  predecessor_receipt_id uuid,
  pilot_sequence integer NOT NULL CHECK (pilot_sequence>=1),
  telemetry_key text NOT NULL CHECK (telemetry_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version='learning_item_pilot_receipt_v1'),
  policy_version text NOT NULL CHECK (policy_version='learning_item_pilot_policy_v1'),
  risk_tier text NOT NULL CHECK (risk_tier IN ('low','medium','high')),
  observation_window_hash text NOT NULL CHECK (observation_window_hash ~ '^[0-9a-f]{64}$'),
  sample_count integer NOT NULL CHECK (sample_count BETWEEN 1 AND 1000000),
  completed_count integer NOT NULL CHECK (completed_count BETWEEN 0 AND sample_count),
  ambiguity_count integer NOT NULL CHECK (ambiguity_count BETWEEN 0 AND sample_count),
  rubric_mismatch_count integer NOT NULL CHECK (rubric_mismatch_count BETWEEN 0 AND sample_count),
  technical_failure_count integer NOT NULL CHECK (technical_failure_count BETWEEN 0 AND sample_count),
  difficulty_mismatch_count integer NOT NULL CHECK (difficulty_mismatch_count BETWEEN 0 AND sample_count),
  unexpected_outcome_count integer NOT NULL CHECK (unexpected_outcome_count BETWEEN 0 AND sample_count),
  security_incident_count integer NOT NULL CHECK (security_incident_count BETWEEN 0 AND sample_count),
  leakage_incident_count integer NOT NULL CHECK (leakage_incident_count BETWEEN 0 AND sample_count),
  cohort_complete boolean NOT NULL,
  decision text NOT NULL CHECK (decision IN ('collecting','promote','awaiting_human_approval','quarantine','retire')),
  telemetry_hash text NOT NULL CHECK (telemetry_hash ~ '^[0-9a-f]{64}$'),
  receipt_hash text NOT NULL UNIQUE CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_item_pilot_sequence UNIQUE (version_id,pilot_sequence),
  CONSTRAINT uq_tutor_learning_item_pilot_key UNIQUE (version_id,telemetry_key),
  CONSTRAINT uq_tutor_learning_item_pilot_id_version UNIQUE (id,version_id),
  CONSTRAINT uq_tutor_learning_item_pilot_scope UNIQUE (id,version_id,receipt_hash),
  CONSTRAINT fk_tutor_learning_item_pilot_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_pilot_predecessor FOREIGN KEY (predecessor_receipt_id,version_id)
    REFERENCES tutor_learning_item_pilot_receipts(id,version_id) ON DELETE NO ACTION DEFERRABLE INITIALLY IMMEDIATE
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_human_approvals (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL,
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  pilot_receipt_id uuid NOT NULL,
  approval_key text NOT NULL CHECK (approval_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL CHECK (schema_version='learning_item_human_approval_v1'),
  policy_version text NOT NULL CHECK (policy_version='learning_item_human_approval_policy_v1'),
  approver_identity text NOT NULL CHECK (approver_identity ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  approval_code text NOT NULL CHECK (approval_code ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  approved boolean NOT NULL CHECK (approved),
  approval_hash text NOT NULL UNIQUE CHECK (approval_hash ~ '^[0-9a-f]{64}$'),
  approved_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_item_human_approval UNIQUE (version_id,policy_version),
  CONSTRAINT uq_tutor_learning_item_human_approval_key UNIQUE (version_id,approval_key),
  CONSTRAINT uq_tutor_learning_item_human_approval_scope UNIQUE (id,version_id,approval_hash),
  CONSTRAINT fk_tutor_learning_item_human_approval_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_human_approval_pilot FOREIGN KEY (pilot_receipt_id,version_id)
    REFERENCES tutor_learning_item_pilot_receipts(id,version_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_learning_item_practice_materializations (
  id uuid PRIMARY KEY,
  version_id uuid NOT NULL UNIQUE,
  item_handle text NOT NULL CHECK (item_handle ~ '^li:[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  exercise_version_id uuid NOT NULL,
  exercise_key text NOT NULL CHECK (exercise_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_version text NOT NULL CHECK (exercise_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_content_hash text NOT NULL CHECK (exercise_content_hash ~ '^[0-9a-f]{64}$'),
  rubric_hash text NOT NULL CHECK (rubric_hash ~ '^[0-9a-f]{64}$'),
  adapter_version text NOT NULL CHECK (adapter_version='learning_item_practice_adapter_v1'),
  receipt_hash text NOT NULL UNIQUE CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  materialized_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_item_materialization_scope UNIQUE (id,version_id,receipt_hash),
  CONSTRAINT fk_tutor_learning_item_materialization_version FOREIGN KEY (version_id,item_handle,content_hash)
    REFERENCES tutor_learning_item_versions(id,handle,content_hash) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_materialization_exercise
    FOREIGN KEY (exercise_version_id,exercise_key,exercise_version,exercise_content_hash)
    REFERENCES tutor_exercise_versions(id,exercise_key,version,content_hash) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_item_materialization_rubric
    FOREIGN KEY (exercise_version_id,rubric_hash)
    REFERENCES tutor_exercise_private_rubrics(exercise_version_id,rubric_hash) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_tutor_learning_item_review_reports_version
  ON tutor_learning_item_review_reports(version_id,role);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_item_pilot_receipts_current
  ON tutor_learning_item_pilot_receipts(version_id,pilot_sequence DESC);

CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_review_report_insert()
RETURNS trigger AS $$
DECLARE version_row record;
DECLARE blocker_total integer;
DECLARE highest_rank integer;
DECLARE listed_total integer;
DECLARE listed_unique integer;
BEGIN
  SELECT versions.creator_identity,blueprints.blueprint_json INTO version_row
  FROM tutor_learning_item_versions AS versions
  JOIN tutor_learning_item_blueprints AS blueprints ON blueprints.id=versions.blueprint_id
  WHERE versions.id=NEW.version_id FOR UPDATE OF versions;
  IF version_row.creator_identity IS NULL THEN
    RAISE EXCEPTION 'Learning Item review version is missing' USING ERRCODE='23514';
  END IF;
  IF NEW.reviewer_identity=version_row.creator_identity THEN
    RAISE EXCEPTION 'Learning Item creator cannot review their own item' USING ERRCODE='23514';
  END IF;
  IF NOT ((version_row.blueprint_json #> '{publication_policy,required_review_roles}') ? NEW.role) THEN
    RAISE EXCEPTION 'Learning Item review role is not required' USING ERRCODE='23514';
  END IF;
  IF (SELECT state FROM tutor_learning_item_publication_events WHERE version_id=NEW.version_id ORDER BY state_version DESC LIMIT 1)<>'machine_verified' THEN
    RAISE EXCEPTION 'Learning Item reviews require machine-verified state' USING ERRCODE='23514';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(NEW.findings_json) AS finding WHERE jsonb_typeof(finding)<>'object') THEN
    RAISE EXCEPTION 'Learning Item review finding shape is invalid' USING ERRCODE='23514';
  END IF;
  SELECT
    count(*) FILTER (WHERE COALESCE((finding->>'blocking')::boolean,false)),
    COALESCE(max(CASE finding->>'severity' WHEN 'critical' THEN 4 WHEN 'major' THEN 3 WHEN 'minor' THEN 2 WHEN 'info' THEN 1 ELSE 0 END),0)
  INTO blocker_total,highest_rank
  FROM jsonb_array_elements(NEW.findings_json) AS finding;
  SELECT count(*),count(DISTINCT blocker_kind) INTO listed_total,listed_unique
  FROM jsonb_array_elements_text(NEW.blocker_kinds_json) AS blocker_kind;
  IF blocker_total<>NEW.blocker_count OR listed_total<>listed_unique THEN
    RAISE EXCEPTION 'Learning Item review blocker summary is invalid' USING ERRCODE='23514';
  END IF;
  IF EXISTS (
    SELECT 1 FROM jsonb_array_elements(NEW.findings_json) AS finding
    WHERE (COALESCE((finding->>'blocking')::boolean,false) AND (
      finding->>'blocker_kind' IS NULL OR NOT (NEW.blocker_kinds_json ? (finding->>'blocker_kind'))
    )) OR (NOT COALESCE((finding->>'blocking')::boolean,false) AND finding->>'blocker_kind' IS NOT NULL)
  ) OR EXISTS (
    SELECT 1 FROM jsonb_array_elements_text(NEW.blocker_kinds_json) AS blocker_kind
    WHERE NOT EXISTS (
      SELECT 1 FROM jsonb_array_elements(NEW.findings_json) AS finding
      WHERE COALESCE((finding->>'blocking')::boolean,false) AND finding->>'blocker_kind'=blocker_kind
    )
  ) THEN
    RAISE EXCEPTION 'Learning Item review blocker findings are inconsistent' USING ERRCODE='23514';
  END IF;
  IF highest_rank<>(CASE NEW.highest_severity WHEN 'critical' THEN 4 WHEN 'major' THEN 3 WHEN 'minor' THEN 2 WHEN 'info' THEN 1 ELSE 0 END) THEN
    RAISE EXCEPTION 'Learning Item review severity summary is invalid' USING ERRCODE='23514';
  END IF;
  IF (NEW.verdict='approved' AND (NEW.blocker_count<>0 OR highest_rank>=3))
     OR (NEW.verdict='changes_required' AND (NEW.blocker_count<>0 OR highest_rank<3))
     OR (NEW.verdict='rejected' AND NEW.blocker_count=0) THEN
    RAISE EXCEPTION 'Learning Item review verdict is inconsistent' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_adjudication_insert()
RETURNS trigger AS $$
DECLARE version_risk text;
DECLARE report_total integer;
DECLARE bad_report_total integer;
BEGIN
  SELECT risk_tier INTO version_risk FROM tutor_learning_item_versions WHERE id=NEW.version_id FOR UPDATE;
  IF version_risk IS NULL OR version_risk<>NEW.risk_tier THEN
    RAISE EXCEPTION 'Learning Item adjudication risk tier is stale' USING ERRCODE='23514';
  END IF;
  IF (SELECT state FROM tutor_learning_item_publication_events WHERE version_id=NEW.version_id ORDER BY state_version DESC LIMIT 1)<>'machine_verified' THEN
    RAISE EXCEPTION 'Learning Item adjudication requires machine-verified state' USING ERRCODE='23514';
  END IF;
  SELECT count(*),count(*) FILTER (WHERE verdict<>'approved' OR blocker_count<>0 OR highest_severity IN ('major','critical'))
  INTO report_total,bad_report_total
  FROM tutor_learning_item_review_reports
  WHERE version_id=NEW.version_id AND policy_version=NEW.policy_version;
  IF report_total<>6
     OR (SELECT count(*) FROM jsonb_object_keys(NEW.report_hashes_json))<>6
     OR EXISTS (
       SELECT 1 FROM jsonb_object_keys(NEW.report_hashes_json) AS role
       WHERE role NOT IN ('curriculum','difficulty','technical','ambiguity','security','adversarial')
     )
     OR EXISTS (
       SELECT 1 FROM tutor_learning_item_review_reports AS reports
       WHERE reports.version_id=NEW.version_id AND reports.policy_version=NEW.policy_version
         AND NEW.report_hashes_json->>reports.role IS DISTINCT FROM reports.report_hash
     ) THEN
    RAISE EXCEPTION 'Learning Item adjudication report set is incomplete or stale' USING ERRCODE='23514';
  END IF;
  IF NEW.verdict='approved' THEN
    IF bad_report_total<>0 OR jsonb_array_length(NEW.blocker_kinds_json)<>0
       OR NEW.highest_severity IN ('major','critical')
       OR (NEW.risk_tier='medium' AND NOT NEW.machine_execution_verified) THEN
      RAISE EXCEPTION 'Learning Item adjudication cannot override review blockers' USING ERRCODE='23514';
    END IF;
  ELSIF jsonb_array_length(NEW.blocker_kinds_json)=0 THEN
    RAISE EXCEPTION 'Rejected Learning Item adjudication needs a blocker' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_pilot_insert()
RETURNS trigger AS $$
DECLARE version_risk text;
DECLARE current_receipt tutor_learning_item_pilot_receipts%ROWTYPE;
DECLARE expected_decision text;
BEGIN
  SELECT risk_tier INTO version_risk FROM tutor_learning_item_versions WHERE id=NEW.version_id FOR UPDATE;
  IF version_risk IS NULL OR version_risk<>NEW.risk_tier THEN
    RAISE EXCEPTION 'Learning Item pilot risk tier is stale' USING ERRCODE='23514';
  END IF;
  IF (SELECT state FROM tutor_learning_item_publication_events WHERE version_id=NEW.version_id ORDER BY state_version DESC LIMIT 1)<>'pilot' THEN
    RAISE EXCEPTION 'Learning Item pilot telemetry requires pilot state' USING ERRCODE='23514';
  END IF;
  SELECT * INTO current_receipt FROM tutor_learning_item_pilot_receipts
  WHERE version_id=NEW.version_id ORDER BY pilot_sequence DESC LIMIT 1;
  IF current_receipt.id IS NULL THEN
    IF NEW.pilot_sequence<>1 OR NEW.predecessor_receipt_id IS NOT NULL THEN
      RAISE EXCEPTION 'Learning Item pilot lineage must begin at one' USING ERRCODE='23514';
    END IF;
  ELSE
    IF NEW.pilot_sequence<>current_receipt.pilot_sequence+1 OR NEW.predecessor_receipt_id IS DISTINCT FROM current_receipt.id THEN
      RAISE EXCEPTION 'Learning Item pilot lineage is stale or forked' USING ERRCODE='23514';
    END IF;
    IF NEW.sample_count<current_receipt.sample_count OR NEW.completed_count<current_receipt.completed_count
       OR NEW.ambiguity_count<current_receipt.ambiguity_count OR NEW.rubric_mismatch_count<current_receipt.rubric_mismatch_count
       OR NEW.technical_failure_count<current_receipt.technical_failure_count OR NEW.difficulty_mismatch_count<current_receipt.difficulty_mismatch_count
       OR NEW.unexpected_outcome_count<current_receipt.unexpected_outcome_count OR NEW.security_incident_count<current_receipt.security_incident_count
       OR NEW.leakage_incident_count<current_receipt.leakage_incident_count THEN
      RAISE EXCEPTION 'Learning Item pilot cumulative telemetry cannot rewind' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.security_incident_count>0 OR NEW.leakage_incident_count>0 THEN
    expected_decision:='retire';
  ELSIF NEW.ambiguity_count>0 OR NEW.rubric_mismatch_count>0 OR NEW.technical_failure_count>0
     OR NEW.difficulty_mismatch_count>0 OR NEW.unexpected_outcome_count>0 THEN
    expected_decision:='quarantine';
  ELSIF NOT NEW.cohort_complete OR NEW.completed_count < (CASE WHEN NEW.risk_tier='low' THEN 1 ELSE 3 END) THEN
    expected_decision:='collecting';
  ELSIF NEW.risk_tier='high' THEN
    expected_decision:='awaiting_human_approval';
  ELSE
    expected_decision:='promote';
  END IF;
  IF NEW.decision<>expected_decision THEN
    RAISE EXCEPTION 'Learning Item pilot decision does not match policy' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_human_approval_insert()
RETURNS trigger AS $$
DECLARE version_risk text;
DECLARE current_pilot tutor_learning_item_pilot_receipts%ROWTYPE;
BEGIN
  SELECT risk_tier INTO version_risk FROM tutor_learning_item_versions WHERE id=NEW.version_id FOR UPDATE;
  IF version_risk<>'high' OR (SELECT state FROM tutor_learning_item_publication_events WHERE version_id=NEW.version_id ORDER BY state_version DESC LIMIT 1)<>'pilot' THEN
    RAISE EXCEPTION 'Human approval is limited to high-risk pilot items' USING ERRCODE='23514';
  END IF;
  SELECT * INTO current_pilot FROM tutor_learning_item_pilot_receipts
  WHERE version_id=NEW.version_id ORDER BY pilot_sequence DESC LIMIT 1;
  IF current_pilot.id IS NULL OR NEW.pilot_receipt_id IS DISTINCT FROM current_pilot.id
     OR current_pilot.decision<>'awaiting_human_approval' THEN
    RAISE EXCEPTION 'Human approval requires the current successful pilot receipt' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_item_materialization_insert()
RETURNS trigger AS $$
DECLARE version_row record;
DECLARE exercise_row record;
BEGIN
  SELECT item_kind,item_key,version INTO version_row FROM tutor_learning_item_versions WHERE id=NEW.version_id FOR UPDATE;
  IF version_row.item_kind IS NULL OR version_row.item_kind='demo'
     OR version_row.item_key<>NEW.exercise_key OR version_row.version<>NEW.exercise_version THEN
    RAISE EXCEPTION 'Learning Item practice materialization scope is invalid' USING ERRCODE='23514';
  END IF;
  IF (SELECT state FROM tutor_learning_item_publication_events WHERE version_id=NEW.version_id ORDER BY state_version DESC LIMIT 1)<>'pilot' THEN
    RAISE EXCEPTION 'Learning Item practice materialization requires pilot state' USING ERRCODE='23514';
  END IF;
  SELECT source_kind,validation_status INTO exercise_row FROM tutor_exercise_versions WHERE id=NEW.exercise_version_id;
  IF exercise_row.source_kind<>'curated_fixture' OR exercise_row.validation_status<>'ready' THEN
    RAISE EXCEPTION 'Learning Item practice authority is not ready' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

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
           AND receipts.receipt_hash=NEW.authority_hash AND receipts.passed
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

DROP TRIGGER IF EXISTS trg_tutor_learning_item_review_reports_insert ON tutor_learning_item_review_reports;
CREATE TRIGGER trg_tutor_learning_item_review_reports_insert
  BEFORE INSERT ON tutor_learning_item_review_reports
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_review_report_insert();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_review_reports_immutable ON tutor_learning_item_review_reports;
CREATE TRIGGER trg_tutor_learning_item_review_reports_immutable
  BEFORE UPDATE OR DELETE ON tutor_learning_item_review_reports
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();

DROP TRIGGER IF EXISTS trg_tutor_learning_item_adjudications_insert ON tutor_learning_item_review_adjudications;
CREATE TRIGGER trg_tutor_learning_item_adjudications_insert
  BEFORE INSERT ON tutor_learning_item_review_adjudications
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_adjudication_insert();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_adjudications_immutable ON tutor_learning_item_review_adjudications;
CREATE TRIGGER trg_tutor_learning_item_adjudications_immutable
  BEFORE UPDATE OR DELETE ON tutor_learning_item_review_adjudications
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();

DROP TRIGGER IF EXISTS trg_tutor_learning_item_pilot_receipts_insert ON tutor_learning_item_pilot_receipts;
CREATE TRIGGER trg_tutor_learning_item_pilot_receipts_insert
  BEFORE INSERT ON tutor_learning_item_pilot_receipts
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_pilot_insert();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_pilot_receipts_immutable ON tutor_learning_item_pilot_receipts;
CREATE TRIGGER trg_tutor_learning_item_pilot_receipts_immutable
  BEFORE UPDATE OR DELETE ON tutor_learning_item_pilot_receipts
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();

DROP TRIGGER IF EXISTS trg_tutor_learning_item_human_approvals_insert ON tutor_learning_item_human_approvals;
CREATE TRIGGER trg_tutor_learning_item_human_approvals_insert
  BEFORE INSERT ON tutor_learning_item_human_approvals
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_human_approval_insert();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_human_approvals_immutable ON tutor_learning_item_human_approvals;
CREATE TRIGGER trg_tutor_learning_item_human_approvals_immutable
  BEFORE UPDATE OR DELETE ON tutor_learning_item_human_approvals
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();

DROP TRIGGER IF EXISTS trg_tutor_learning_item_materializations_insert ON tutor_learning_item_practice_materializations;
CREATE TRIGGER trg_tutor_learning_item_materializations_insert
  BEFORE INSERT ON tutor_learning_item_practice_materializations
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_materialization_insert();
DROP TRIGGER IF EXISTS trg_tutor_learning_item_materializations_immutable ON tutor_learning_item_practice_materializations;
CREATE TRIGGER trg_tutor_learning_item_materializations_immutable
  BEFORE UPDATE OR DELETE ON tutor_learning_item_practice_materializations
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_bank_immutable();

-- Replace schema 130's permissive transition trigger with the governance-aware function above.
DROP TRIGGER IF EXISTS trg_tutor_learning_item_publication_events_lineage ON tutor_learning_item_publication_events;
CREATE TRIGGER trg_tutor_learning_item_publication_events_lineage
  BEFORE INSERT ON tutor_learning_item_publication_events
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_item_publication_insert();
