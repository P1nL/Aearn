-- Approved B only. No backfill, legacy conversion, history rewrite, or public cutover.
ALTER TABLE tutor_lesson_authoring_runs
  ADD COLUMN IF NOT EXISTS completion_contract_version text;
ALTER TABLE tutor_lesson_source_snapshots
  ADD COLUMN IF NOT EXISTS evidence_schema_version text,
  ADD COLUMN IF NOT EXISTS evidence_units_json jsonb NOT NULL DEFAULT '[]'::jsonb;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_lesson_authoring_runs'::regclass
    AND conname = 'chk_lesson_completion_version') THEN
    ALTER TABLE tutor_lesson_authoring_runs ADD CONSTRAINT chk_lesson_completion_version
      CHECK (completion_contract_version IS NULL OR completion_contract_version = 'lesson_completion_v1');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_lesson_source_snapshots'::regclass
    AND conname = 'chk_lesson_evidence_units_version') THEN
    ALTER TABLE tutor_lesson_source_snapshots ADD CONSTRAINT chk_lesson_evidence_units_version CHECK (
      (evidence_schema_version IS NULL AND evidence_units_json = '[]'::jsonb)
      OR (evidence_schema_version IS NOT DISTINCT FROM 'lesson_evidence_units_v1'
          AND jsonb_typeof(evidence_units_json) = 'array' AND jsonb_array_length(evidence_units_json) = 1)
    );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_lesson_authoring_stage_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  contract_version text NOT NULL DEFAULT 'lesson_completion_v1' CHECK (contract_version = 'lesson_completion_v1'),
  stage_kind text NOT NULL CHECK (stage_kind IN ('standard', 'personalized')),
  attempt_index integer NOT NULL CHECK (attempt_index > 0),
  stage_attempt_index integer NOT NULL CHECK (stage_attempt_index > 0),
  lease_generation integer NOT NULL CHECK (lease_generation > 0),
  state text NOT NULL DEFAULT 'intent' CHECK (state IN ('intent', 'result_saved', 'accepted', 'rejected', 'outcome_unknown')),
  dependency_hash text NOT NULL CHECK (dependency_hash ~ '^[0-9a-f]{64}$'),
  dependency_json jsonb NOT NULL CHECK (jsonb_typeof(dependency_json) = 'object' AND octet_length(dependency_json::text) <= 3000000),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  standard_attempt_id uuid REFERENCES tutor_lesson_authoring_stage_attempts(id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  execution_outcome text NOT NULL DEFAULT 'pending' CHECK (execution_outcome IN ('pending', 'known', 'not_started', 'unknown')),
  usage_status text NOT NULL DEFAULT 'pending' CHECK (usage_status IN ('pending', 'known', 'not_started', 'unknown')),
  result_json jsonb CHECK (jsonb_typeof(result_json) = 'object' AND octet_length(result_json::text) <= 600000),
  feedback_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(feedback_json) = 'object' AND octet_length(feedback_json::text) <= 16000),
  document_json jsonb CHECK (jsonb_typeof(document_json) = 'object' AND octet_length(document_json::text) <= 600000),
  document_hash text CHECK (document_hash ~ '^[0-9a-f]{64}$'),
  quality_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(quality_json) = 'object'),
  request_deadline_at timestamptz NOT NULL,
  result_deadline_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  result_saved_at timestamptz,
  result_transaction_id xid8,
  decision_lease_generation integer,
  decided_at timestamptz,
  UNIQUE (run_id, attempt_index),
  FOREIGN KEY (run_id, user_id) REFERENCES tutor_lesson_authoring_runs(id, user_id) ON DELETE RESTRICT,
  FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_lesson_stage_window CHECK (
    result_deadline_at = request_deadline_at + interval '60 seconds'
    AND request_deadline_at > created_at - interval '5 seconds'
    AND request_deadline_at <= created_at + interval '600 seconds'
  ),
  CONSTRAINT chk_lesson_stage_standard CHECK ((stage_kind = 'standard') = (standard_attempt_id IS NULL)),
  CONSTRAINT chk_lesson_stage_usage CHECK (
    (usage_status <> 'known' OR (
      jsonb_typeof(result_json #> '{usage,input_tokens}') IS NOT DISTINCT FROM 'number'
      AND jsonb_typeof(result_json #> '{usage,output_tokens}') IS NOT DISTINCT FROM 'number'
      AND (result_json #>> '{usage,input_tokens}')::bigint >= 0
      AND (result_json #>> '{usage,output_tokens}')::bigint >= 0))
    AND (execution_outcome <> 'not_started' OR usage_status = 'not_started')
  ),
  CONSTRAINT chk_lesson_stage_state_shape CHECK (
    (state = 'intent' AND execution_outcome = 'pending' AND usage_status = 'pending'
      AND result_json IS NULL AND feedback_json = '{}'::jsonb AND result_saved_at IS NULL
      AND result_transaction_id IS NULL AND decision_lease_generation IS NULL AND decided_at IS NULL)
    OR (state = 'outcome_unknown' AND execution_outcome = 'unknown' AND usage_status IN ('known', 'unknown')
      AND result_json IS NOT NULL AND result_saved_at IS NOT NULL AND result_transaction_id IS NOT NULL
      AND decision_lease_generation IS NULL AND decided_at IS NULL)
    OR (state = 'result_saved' AND execution_outcome IN ('known', 'not_started')
      AND usage_status IN ('known', 'unknown', 'not_started') AND result_json IS NOT NULL
      AND result_saved_at IS NOT NULL AND result_transaction_id IS NOT NULL
      AND decision_lease_generation IS NULL AND decided_at IS NULL)
    OR (state IN ('accepted', 'rejected') AND execution_outcome IN ('known', 'not_started')
      AND usage_status IN ('known', 'unknown', 'not_started') AND result_json IS NOT NULL
      AND result_saved_at IS NOT NULL AND result_transaction_id IS NOT NULL
      AND decision_lease_generation IS NOT NULL AND decided_at IS NOT NULL)
  ),
  CONSTRAINT chk_lesson_stage_acceptance CHECK (
    (state = 'accepted' AND document_json IS NOT NULL AND document_hash IS NOT NULL
      AND (quality_json -> 'passed') IS NOT DISTINCT FROM 'true'::jsonb AND feedback_json = '{}'::jsonb
      AND execution_outcome = 'known' AND jsonb_typeof(result_json -> 'candidate') IS NOT DISTINCT FROM 'object')
    OR (state <> 'accepted' AND document_json IS NULL AND document_hash IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_lesson_stage_reuse ON tutor_lesson_authoring_stage_attempts
  (user_id, track_id, knowledge_key, stage_kind, dependency_hash, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_lesson_stage_unclosed ON tutor_lesson_authoring_stage_attempts
  (user_id, track_id, knowledge_key, stage_kind, dependency_hash)
  WHERE state IN ('intent', 'outcome_unknown');

CREATE OR REPLACE FUNCTION enforce_lesson_evidence_units_597() RETURNS trigger AS $$
DECLARE unit jsonb; raw_bytes bytea;
BEGIN
  IF NEW.evidence_schema_version IS NULL THEN RETURN NEW; END IF;
  IF NEW.evidence_schema_version <> 'lesson_evidence_units_v1'
     OR jsonb_typeof(NEW.evidence_units_json) <> 'array'
     OR jsonb_array_length(NEW.evidence_units_json) <> 1 THEN
    RAISE EXCEPTION 'Invalid versioned Lesson evidence' USING ERRCODE = '23514';
  END IF;
  unit := NEW.evidence_units_json -> 0;
  raw_bytes := convert_to(unit ->> 'text', 'UTF8');
  IF jsonb_typeof(unit) <> 'object' OR unit - ARRAY['text','content_hash','start_byte','end_byte'] <> '{}'::jsonb
     OR jsonb_typeof(unit -> 'text') IS DISTINCT FROM 'string'
     OR jsonb_typeof(unit -> 'start_byte') IS DISTINCT FROM 'number'
     OR jsonb_typeof(unit -> 'end_byte') IS DISTINCT FROM 'number'
     OR (unit ->> 'start_byte')::integer IS DISTINCT FROM 0
     OR octet_length(raw_bytes) NOT BETWEEN 1 AND 64000
     OR (unit ->> 'end_byte')::integer IS DISTINCT FROM octet_length(raw_bytes)
     OR (unit ->> 'content_hash') IS DISTINCT FROM NEW.chunk_content_hash
     OR encode(digest(raw_bytes, 'sha256'), 'hex') IS DISTINCT FROM NEW.chunk_content_hash THEN
    RAISE EXCEPTION 'Lesson evidence bytes/hash/scope mismatch' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_lesson_evidence_units_597 ON tutor_lesson_source_snapshots;
CREATE TRIGGER trg_lesson_evidence_units_597 BEFORE INSERT OR UPDATE ON tutor_lesson_source_snapshots
  FOR EACH ROW EXECUTE FUNCTION enforce_lesson_evidence_units_597();

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_authoring_stage_attempt() RETURNS trigger AS $$
DECLARE owner_row tutor_lesson_authoring_runs%ROWTYPE; standard_row tutor_lesson_authoring_stage_attempts%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Private Lesson stages require confirmed user purge' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'INSERT' THEN
    PERFORM pg_advisory_xact_lock(
      hashtext('lesson-stage:' || NEW.user_id::text || ':' || NEW.track_id::text || ':' || NEW.knowledge_key || ':' || NEW.stage_kind),
      hashtext(NEW.dependency_hash));
    IF EXISTS (SELECT 1 FROM tutor_lesson_authoring_stage_attempts
      WHERE user_id = NEW.user_id AND track_id = NEW.track_id AND knowledge_key = NEW.knowledge_key
        AND stage_kind = NEW.stage_kind AND dependency_hash = NEW.dependency_hash
        AND state IN ('intent','outcome_unknown','result_saved','accepted')) THEN
      RAISE EXCEPTION 'Lesson dependency already has in-flight, unresolved, or accepted work' USING ERRCODE = '23514';
    END IF;
  END IF;
  SELECT * INTO owner_row FROM tutor_lesson_authoring_runs WHERE id = NEW.run_id FOR UPDATE;
  IF owner_row.id IS NULL OR owner_row.completion_contract_version IS DISTINCT FROM 'lesson_completion_v1'
     OR (NEW.user_id, NEW.track_id, NEW.knowledge_key) IS DISTINCT FROM (owner_row.user_id, owner_row.track_id, owner_row.knowledge_key) THEN
    RAISE EXCEPTION 'Lesson stage owner scope mismatch' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.state <> 'intent' OR owner_row.state <> 'running' OR NEW.lease_generation <> owner_row.lease_generation
       OR owner_row.lease_expires_at <= clock_timestamp() OR NEW.attempt_index <> owner_row.attempt_count + 1
       OR NEW.dependency_json ->> 'schema_version' IS DISTINCT FROM 'lesson_completion_v1'
       OR NEW.dependency_json ->> 'user_id' IS DISTINCT FROM NEW.user_id::text
       OR NEW.dependency_json ->> 'track_id' IS DISTINCT FROM NEW.track_id::text
       OR NEW.dependency_json ->> 'knowledge_key' IS DISTINCT FROM NEW.knowledge_key
       OR NEW.dependency_json ->> 'stage_kind' IS DISTINCT FROM NEW.stage_kind
       OR NEW.dependency_json #>> '{evidence,schema_version}' IS DISTINCT FROM 'lesson_evidence_units_v1'
       OR NEW.dependency_json #>> '{evidence,legacy_source_set_hash}' IS DISTINCT FROM owner_row.source_set_hash
       OR jsonb_typeof(NEW.dependency_json #> '{evidence,selected_units}') IS DISTINCT FROM 'array'
       OR jsonb_array_length(NEW.dependency_json #> '{evidence,selected_units}') = 0 THEN
      RAISE EXCEPTION 'Lesson intent requires a live explicit owner and complete dependency' USING ERRCODE = '23514';
    END IF;
    IF NEW.stage_kind = 'personalized' THEN
      SELECT * INTO standard_row FROM tutor_lesson_authoring_stage_attempts WHERE id = NEW.standard_attempt_id;
      IF standard_row.state IS DISTINCT FROM 'accepted' OR standard_row.stage_kind IS DISTINCT FROM 'standard'
         OR (standard_row.user_id, standard_row.track_id, standard_row.knowledge_key) IS DISTINCT FROM (NEW.user_id, NEW.track_id, NEW.knowledge_key)
         OR NEW.dependency_json ->> 'standard_dependency_hash' IS DISTINCT FROM standard_row.dependency_hash
         OR NEW.dependency_json ->> 'standard_document_hash' IS DISTINCT FROM standard_row.document_hash
         OR NEW.dependency_json ->> 'profile_hash' IS DISTINCT FROM owner_row.profile_hash THEN
        RAISE EXCEPTION 'Personalization requires an exact accepted private standard' USING ERRCODE = '23514';
      END IF;
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.state IN ('accepted', 'rejected', 'outcome_unknown') OR
     (to_jsonb(NEW) - ARRAY['state','execution_outcome','usage_status','result_json','feedback_json','result_saved_at','result_transaction_id','decision_lease_generation','document_json','document_hash','quality_json','decided_at'])
       IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['state','execution_outcome','usage_status','result_json','feedback_json','result_saved_at','result_transaction_id','decision_lease_generation','document_json','document_hash','quality_json','decided_at']) THEN
    RAISE EXCEPTION 'Lesson stage identity/terminal result is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'intent' AND NEW.state IN ('result_saved', 'outcome_unknown') THEN
    -- Real late results can be saved, but this does not accept them or renew authority.
    NEW.result_transaction_id := pg_current_xact_id();
    RETURN NEW;
  END IF;
  IF OLD.state = 'result_saved' AND NEW.state IN ('accepted', 'rejected') THEN
    IF (NEW.execution_outcome, NEW.usage_status, NEW.result_json, NEW.feedback_json, NEW.result_saved_at, NEW.result_transaction_id)
        IS DISTINCT FROM (OLD.execution_outcome, OLD.usage_status, OLD.result_json, OLD.feedback_json, OLD.result_saved_at, OLD.result_transaction_id)
       OR owner_row.state <> 'running' OR owner_row.lease_expires_at <= clock_timestamp()
       OR NEW.decision_lease_generation IS DISTINCT FROM owner_row.lease_generation
       OR OLD.result_transaction_id = pg_current_xact_id()
       OR OLD.result_saved_at > OLD.result_deadline_at THEN
      RAISE EXCEPTION 'Lesson decision cannot alter result DATA or consume an expired owner' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Illegal Lesson completion stage transition' USING ERRCODE = '23514';
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_lesson_completion_stage_597 ON tutor_lesson_authoring_stage_attempts;
CREATE TRIGGER trg_lesson_completion_stage_597 BEFORE INSERT OR UPDATE OR DELETE ON tutor_lesson_authoring_stage_attempts
  FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_authoring_stage_attempt();

CREATE OR REPLACE FUNCTION enforce_lesson_completion_run_597() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.completion_contract_version IS NOT NULL AND (NEW.state <> 'pending' OR NEW.lease_generation <> 0 OR NEW.attempt_count <> 0) THEN
      RAISE EXCEPTION 'Completion Lesson runs must start pending and unconsumed' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.completion_contract_version IS DISTINCT FROM OLD.completion_contract_version THEN
    RAISE EXCEPTION 'Legacy Lesson rows cannot be converted or reopened' USING ERRCODE = '23514';
  END IF;
  IF OLD.completion_contract_version IS NULL THEN RETURN NEW; END IF;
  IF OLD.state IN ('completed', 'failed', 'cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal completion Lesson run is immutable' USING ERRCODE = '23514';
  END IF;
  IF (to_jsonb(NEW) - ARRAY['state','attempt_count','lease_generation','lease_owner','lease_expires_at','failure_code','failure_message','source_set_hash','standard_document_id','personalized_document_id','assignment_id','updated_at','terminal_at'])
       IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['state','attempt_count','lease_generation','lease_owner','lease_expires_at','failure_code','failure_message','source_set_hash','standard_document_id','personalized_document_id','assignment_id','updated_at','terminal_at'])
     OR (OLD.source_set_hash IS NOT NULL AND NEW.source_set_hash IS DISTINCT FROM OLD.source_set_hash)
     OR NEW.attempt_count < OLD.attempt_count
     OR (OLD.state = 'running' AND NEW.state = 'claimed')
     OR (OLD.state = 'claimed' AND NEW.state = 'pending') THEN
    RAISE EXCEPTION 'Completion Lesson identity cannot be rewritten' USING ERRCODE = '23514';
  END IF;
  IF NEW.lease_generation IS DISTINCT FROM OLD.lease_generation THEN
    IF NEW.lease_generation <> OLD.lease_generation + 1
       OR NOT ((OLD.state = 'pending' AND NEW.state = 'claimed')
               OR (OLD.state = 'claimed' AND NEW.state = 'claimed' AND OLD.lease_expires_at <= clock_timestamp())
               OR (OLD.state = 'running' AND NEW.state = 'running' AND OLD.lease_expires_at <= clock_timestamp()))
       OR EXISTS (SELECT 1 FROM tutor_lesson_authoring_stage_attempts WHERE run_id = OLD.id AND state IN ('intent','outcome_unknown')) THEN
      RAISE EXCEPTION 'Reclaim requires generation CAS and known step closure, never expiry alone' USING ERRCODE = '23514';
    END IF;
  ELSIF NEW.lease_owner IS DISTINCT FROM OLD.lease_owner AND NEW.state NOT IN ('completed','failed','cancelled') THEN
    RAISE EXCEPTION 'Lesson owner change requires generation CAS' USING ERRCODE = '23514';
  END IF;
  IF NEW.lease_generation = OLD.lease_generation AND NEW.lease_expires_at > OLD.lease_expires_at
     AND OLD.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'Heartbeat cannot revive an expired Lesson lease' USING ERRCODE = '23514';
  END IF;
  IF NEW.lease_expires_at IS DISTINCT FROM OLD.lease_expires_at
     AND NEW.lease_expires_at > clock_timestamp() + interval '120 seconds' THEN
    RAISE EXCEPTION 'Lesson liveness lease is bounded to 120 seconds' USING ERRCODE = '23514';
  END IF;
  IF NEW.state = 'failed' AND OLD.state <> 'failed' AND OLD.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'Expired Lesson owner cannot terminalize recoverable work' USING ERRCODE = '23514';
  END IF;
  IF NEW.state = 'failed' AND OLD.state <> 'failed' AND EXISTS (
    SELECT 1 FROM tutor_lesson_authoring_stage_attempts WHERE run_id = OLD.id AND state = 'result_saved'
  ) THEN
    RAISE EXCEPTION 'Committed Lesson results require reconciliation before failure' USING ERRCODE = '23514';
  END IF;
  IF NEW.state = 'completed' AND OLD.state <> 'completed' THEN
    IF OLD.lease_expires_at <= clock_timestamp()
       OR EXISTS (SELECT 1 FROM tutor_lesson_authoring_stage_attempts WHERE run_id = OLD.id AND state IN ('intent','outcome_unknown','result_saved'))
       OR NOT EXISTS (
         SELECT 1 FROM tutor_lesson_authoring_stage_attempts personal
         JOIN tutor_lesson_authoring_stage_attempts standard ON standard.id = personal.standard_attempt_id
         JOIN tutor_lesson_documents pd ON pd.id = NEW.personalized_document_id AND pd.content_hash = personal.document_hash
         JOIN tutor_lesson_documents sd ON sd.id = NEW.standard_document_id AND sd.content_hash = standard.document_hash
         JOIN tutor_lesson_assignments assignment ON assignment.id = NEW.assignment_id AND assignment.document_id = pd.id
         WHERE personal.state = 'accepted' AND standard.state = 'accepted'
           AND personal.stage_kind = 'personalized' AND standard.stage_kind = 'standard'
           AND (personal.user_id, personal.track_id, personal.knowledge_key) = (NEW.user_id, NEW.track_id, NEW.knowledge_key)
           AND personal.dependency_json ->> 'profile_hash' = NEW.profile_hash
           AND personal.dependency_json #>> '{evidence,legacy_source_set_hash}' = NEW.source_set_hash
           AND (pd.user_id, pd.track_id, pd.knowledge_key, pd.profile_hash, pd.source_set_hash) =
               (NEW.user_id, NEW.track_id, NEW.knowledge_key, NEW.profile_hash, NEW.source_set_hash)
           AND (assignment.user_id, assignment.track_id, assignment.knowledge_key) =
               (NEW.user_id, NEW.track_id, NEW.knowledge_key)
           AND sd.source_set_hash = NEW.source_set_hash
           AND pd.standard_document_id = sd.id
       ) THEN
      RAISE EXCEPTION 'Lesson publication requires complete accepted stages in original atomic publish' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_lesson_completion_run_597 ON tutor_lesson_authoring_runs;
CREATE TRIGGER trg_lesson_completion_run_597 BEFORE INSERT OR UPDATE ON tutor_lesson_authoring_runs
  FOR EACH ROW EXECUTE FUNCTION enforce_lesson_completion_run_597();
