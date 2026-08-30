-- Model code-review exercise authoring and pre-publication validation authority.
-- Private candidate/rubric/test payloads stay in these user-scoped tables and are never public projections.
DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'tutor_exercise_versions'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%exercise_type%'
  LOOP
    EXECUTE format('ALTER TABLE tutor_exercise_versions DROP CONSTRAINT %I', item.conname);
  END LOOP;
  ALTER TABLE tutor_exercise_versions
    ADD CONSTRAINT chk_tutor_exercise_versions_type CHECK (exercise_type IN (
      'code_completion', 'sql_query', 'browser_preview', 'static_code_reasoning', 'model_code_review'
    ));
END $$;

CREATE TABLE IF NOT EXISTS tutor_model_review_authoring_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  plan_revision_id uuid NOT NULL,
  lesson_assignment_id uuid NOT NULL,
  document_id uuid NOT NULL,
  slot_id uuid NOT NULL REFERENCES tutor_lesson_gate_slots(id) ON DELETE RESTRICT,
  gate_key text NOT NULL CHECK (gate_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_progress_version integer NOT NULL CHECK (expected_progress_version >= 1),
  expected_assignment_version integer NOT NULL CHECK (expected_assignment_version >= 1),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  required_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  mastery_level text NOT NULL CHECK (mastery_level ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  mastery_confidence double precision NOT NULL CHECK (mastery_confidence BETWEEN 0 AND 1),
  misconception_tags_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(misconception_tags_json) = 'array'),
  validation_profile_version text NOT NULL CHECK (validation_profile_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('pending', 'claimed', 'running', 'validating', 'completed', 'failed', 'cancelled')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  internal_conversation_id uuid,
  internal_run_id uuid,
  candidate_id uuid,
  validation_run_id uuid,
  publication_id uuid,
  failure_code text CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{2,79}$'),
  failure_message text CHECK (failure_message IS NULL OR char_length(failure_message) BETWEEN 1 AND 320),
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_authoring_scope UNIQUE (user_id, lesson_assignment_id, gate_key, request_hash),
  CONSTRAINT uq_tutor_model_review_authoring_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_model_review_authoring_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_authoring_assignment
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_authoring_slot
    FOREIGN KEY (document_id, gate_key) REFERENCES tutor_lesson_gate_slots(document_id, gate_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_model_review_authoring_terminal CHECK (
    (state IN ('completed', 'failed', 'cancelled')) = (terminal_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_model_review_authoring_lease CHECK (
    (lease_owner_id IS NULL) = (lease_expires_at IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_model_review_authoring_attempt_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  attempt_index integer NOT NULL CHECK (attempt_index >= 1),
  provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 160),
  model text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 160),
  protocol text NOT NULL CHECK (char_length(protocol) BETWEEN 1 AND 80),
  outcome text NOT NULL CHECK (outcome IN ('success', 'invalid', 'unavailable')),
  diagnostic_code text CHECK (diagnostic_code IS NULL OR diagnostic_code ~ '^[A-Z][A-Z0-9_]{2,79}$'),
  input_tokens bigint CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens bigint CHECK (output_tokens IS NULL OR output_tokens >= 0),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  response_hash text CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_authoring_attempt UNIQUE (authoring_run_id, attempt_index),
  CONSTRAINT fk_tutor_model_review_authoring_attempt_run
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_candidates (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  public_payload_json jsonb NOT NULL CHECK (jsonb_typeof(public_payload_json) = 'object'),
  private_payload_json jsonb NOT NULL CHECK (jsonb_typeof(private_payload_json) = 'object'),
  public_hash text NOT NULL CHECK (public_hash ~ '^[0-9a-f]{64}$'),
  private_hash text NOT NULL CHECK (private_hash ~ '^[0-9a-f]{64}$'),
  candidate_hash text NOT NULL CHECK (candidate_hash ~ '^[0-9a-f]{64}$'),
  generator_version text NOT NULL CHECK (generator_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  prompt_schema_version text NOT NULL CHECK (prompt_schema_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  validation_profile_version text NOT NULL CHECK (validation_profile_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  state text NOT NULL CHECK (state IN ('draft', 'validating', 'verified', 'rejected', 'published')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_candidates_scope UNIQUE (user_id, candidate_hash),
  CONSTRAINT uq_tutor_model_review_candidates_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_model_review_candidate_run
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_candidate_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_validation_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  validation_profile_version text NOT NULL CHECK (validation_profile_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  candidate_hash text NOT NULL CHECK (candidate_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL CHECK (state IN ('pending', 'running', 'verified', 'failed', 'stale')),
  action_invocation_id text,
  action_receipt_hash text CHECK (action_receipt_hash IS NULL OR action_receipt_hash ~ '^[0-9a-f]{64}$'),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  check_summary_code text CHECK (check_summary_code IS NULL OR check_summary_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'),
  failure_code text CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{2,79}$'),
  safe_summary text CHECK (safe_summary IS NULL OR char_length(safe_summary) BETWEEN 1 AND 320),
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_validation_candidate UNIQUE (candidate_id, validation_profile_version),
  CONSTRAINT uq_tutor_model_review_validation_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_model_review_validation_authoring
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_validation_candidate
    FOREIGN KEY (candidate_id, user_id)
    REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_validation_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_model_review_validation_terminal CHECK (
    (state IN ('verified', 'failed', 'stale')) = (terminal_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_model_review_validation_checks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  validation_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  check_type text NOT NULL CHECK (check_type IN (
    'schema', 'parser', 'compile_or_typecheck', 'visible_tests', 'hidden_tests',
    'finding_reachability', 'rubric_consistency', 'coverage', 'redaction'
  )),
  status text NOT NULL CHECK (status IN ('passed', 'failed', 'not_applicable')),
  execution_job_id uuid REFERENCES tutor_execution_jobs(id) ON DELETE RESTRICT,
  proof_hash text NOT NULL CHECK (proof_hash ~ '^[0-9a-f]{64}$'),
  safe_code text NOT NULL CHECK (safe_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_validation_check UNIQUE (validation_run_id, check_type),
  CONSTRAINT fk_tutor_model_review_validation_check_run
    FOREIGN KEY (validation_run_id, user_id)
    REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_publications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  authoring_run_id uuid NOT NULL,
  candidate_id uuid NOT NULL,
  validation_run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL REFERENCES tutor_lesson_gate_bindings(id) ON DELETE RESTRICT,
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  validation_authority_hash text NOT NULL CHECK (validation_authority_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_publication_candidate UNIQUE (candidate_id),
  CONSTRAINT uq_tutor_model_review_publication_gate UNIQUE (user_id, lesson_assignment_id, gate_binding_id),
  CONSTRAINT uq_tutor_model_review_publication_evidence_scope UNIQUE (id, user_id, lesson_assignment_id, gate_binding_id),
  CONSTRAINT fk_tutor_model_review_publication_authoring
    FOREIGN KEY (authoring_run_id, user_id)
    REFERENCES tutor_model_review_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_candidate
    FOREIGN KEY (candidate_id, user_id)
    REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_validation
    FOREIGN KEY (validation_run_id, user_id)
    REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_model_review_publication_assignment
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_model_review_evidence_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  publication_id uuid NOT NULL REFERENCES tutor_model_review_publications(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL,
  lesson_assignment_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL,
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  evidence_json jsonb NOT NULL CHECK (jsonb_typeof(evidence_json) = 'object'),
  evidence_hash text NOT NULL CHECK (evidence_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_evidence_idempotency UNIQUE (user_id, gate_binding_id, idempotency_key),
  CONSTRAINT fk_tutor_model_review_evidence_publication_scope
    FOREIGN KEY (publication_id, user_id, lesson_assignment_id, gate_binding_id)
    REFERENCES tutor_model_review_publications(id, user_id, lesson_assignment_id, gate_binding_id)
    ON DELETE RESTRICT
);

-- Add deferred circular references only after all model-review authority tables exist.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_candidate') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_candidate
      FOREIGN KEY (candidate_id, user_id) REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE NO ACTION
      DEFERRABLE INITIALLY IMMEDIATE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_validation') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_validation
      FOREIGN KEY (validation_run_id, user_id) REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE NO ACTION
      DEFERRABLE INITIALLY IMMEDIATE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_publication') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_publication
      FOREIGN KEY (publication_id) REFERENCES tutor_model_review_publications(id) ON DELETE NO ACTION
      DEFERRABLE INITIALLY IMMEDIATE;
  END IF;
  ALTER TABLE tutor_model_review_authoring_runs
    ALTER CONSTRAINT fk_tutor_model_review_authoring_candidate DEFERRABLE INITIALLY IMMEDIATE;
  ALTER TABLE tutor_model_review_authoring_runs
    ALTER CONSTRAINT fk_tutor_model_review_authoring_validation DEFERRABLE INITIALLY IMMEDIATE;
  ALTER TABLE tutor_model_review_authoring_runs
    ALTER CONSTRAINT fk_tutor_model_review_authoring_publication DEFERRABLE INITIALLY IMMEDIATE;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_internal_conversation') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_internal_conversation
      FOREIGN KEY (internal_conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_model_review_authoring_internal_run') THEN
    ALTER TABLE tutor_model_review_authoring_runs ADD CONSTRAINT fk_tutor_model_review_authoring_internal_run
      FOREIGN KEY (internal_run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT;
  END IF;
END $$;

ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS model_review_candidate_id uuid;
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS model_review_validation_id uuid;
ALTER TABLE tutor_execution_jobs ADD COLUMN IF NOT EXISTS model_review_validation_id uuid;

ALTER TABLE tutor_execution_intents DROP CONSTRAINT IF EXISTS chk_tutor_execution_intents_source_shape;
ALTER TABLE tutor_execution_intents ADD CONSTRAINT chk_tutor_execution_intents_source_shape CHECK (
  (
    source_kind = 'tutor_message'
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND source_message_id IS NOT NULL
    AND exercise_id IS NOT NULL AND input_revision IS NOT NULL
    AND exercise_attempt_id IS NULL AND exercise_submission_id IS NULL AND exercise_version_id IS NULL
    AND model_review_candidate_id IS NULL AND model_review_validation_id IS NULL
    AND origin IN ('interactive', 'proactive')
    AND ((consumed_at IS NULL) = (consumed_by_effect_id IS NULL))
  )
  OR (
    source_kind = 'exercise_submission'
    AND conversation_id IS NULL AND run_id IS NULL AND source_message_id IS NULL AND exercise_id IS NULL
    AND input_revision IS NULL AND origin = 'exercise_gate'
    AND exercise_attempt_id IS NOT NULL AND exercise_submission_id IS NOT NULL AND exercise_version_id IS NOT NULL
    AND model_review_candidate_id IS NULL AND model_review_validation_id IS NULL
    AND consumed_by_effect_id IS NULL
  )
  OR (
    source_kind = 'model_review_candidate'
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND source_message_id IS NULL AND exercise_id IS NULL
    AND input_revision IS NOT NULL AND origin = 'proactive'
    AND exercise_attempt_id IS NULL AND exercise_submission_id IS NULL AND exercise_version_id IS NULL
    AND model_review_candidate_id IS NOT NULL AND model_review_validation_id IS NOT NULL
    AND consumed_by_effect_id IS NULL
  )
) NOT VALID;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tutor_execution_intents_model_review_scope') THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT uq_tutor_execution_intents_model_review_scope
      UNIQUE (id, model_review_validation_id, user_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_intent_model_review_candidate') THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_model_review_candidate
      FOREIGN KEY (model_review_candidate_id, user_id)
      REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_intent_model_review_validation') THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_model_review_validation
      FOREIGN KEY (model_review_validation_id, user_id)
      REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

ALTER TABLE tutor_execution_jobs DROP CONSTRAINT IF EXISTS chk_tutor_execution_jobs_owner_shape;
ALTER TABLE tutor_execution_jobs ADD CONSTRAINT chk_tutor_execution_jobs_owner_shape CHECK (
  (
    owner_kind = 'tutor_effect'
    AND effect_record_id IS NOT NULL AND effect_key IS NOT NULL
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL
    AND exercise_attempt_id IS NULL AND model_review_validation_id IS NULL
  )
  OR (
    owner_kind = 'exercise_attempt'
    AND effect_record_id IS NULL AND effect_key IS NULL
    AND conversation_id IS NULL AND run_id IS NULL
    AND exercise_attempt_id IS NOT NULL AND model_review_validation_id IS NULL
  )
  OR (
    owner_kind = 'model_review_validation'
    AND effect_record_id IS NULL AND effect_key IS NULL
    AND conversation_id IS NOT NULL AND run_id IS NOT NULL
    AND exercise_attempt_id IS NULL AND model_review_validation_id IS NOT NULL
  )
) NOT VALID;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_tutor_execution_jobs_model_review_scope') THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT uq_tutor_execution_jobs_model_review_scope
      UNIQUE (id, model_review_validation_id, user_id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_job_model_review_intent_scope') THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_model_review_intent_scope
      FOREIGN KEY (intent_id, model_review_validation_id, user_id)
      REFERENCES tutor_execution_intents(id, model_review_validation_id, user_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_execution_job_model_review_validation') THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_model_review_validation
      FOREIGN KEY (model_review_validation_id, user_id)
      REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

-- Extend existing Action receipt authority without changing the lifecycle state machine.
ALTER TABLE tutor_action_attempts DROP CONSTRAINT IF EXISTS tutor_action_attempts_authority_kind_check;
ALTER TABLE tutor_action_attempts ADD CONSTRAINT tutor_action_attempts_authority_kind_check CHECK (
  authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result',
    'model_review_validation'
  )
);
ALTER TABLE tutor_action_verifications DROP CONSTRAINT IF EXISTS tutor_action_verifications_authority_kind_check;
ALTER TABLE tutor_action_verifications ADD CONSTRAINT tutor_action_verifications_authority_kind_check CHECK (
  authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result',
    'model_review_validation'
  )
);
ALTER TABLE tutor_action_receipts DROP CONSTRAINT IF EXISTS tutor_action_receipts_authority_kind_check;
ALTER TABLE tutor_action_receipts ADD CONSTRAINT tutor_action_receipts_authority_kind_check CHECK (
  authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result',
    'model_review_validation'
  )
);

CREATE OR REPLACE FUNCTION tutor_model_review_purge_allowed(target_user_id uuid)
RETURNS boolean AS $$
BEGIN
  RETURN tutor_learning_track_purge_allowed(target_user_id);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Model review receipt and publication rows are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_authoring_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Model review authoring run cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.track_id IS DISTINCT FROM NEW.track_id OR OLD.knowledge_key IS DISTINCT FROM NEW.knowledge_key
     OR OLD.plan_revision_id IS DISTINCT FROM NEW.plan_revision_id
     OR OLD.lesson_assignment_id IS DISTINCT FROM NEW.lesson_assignment_id
     OR OLD.document_id IS DISTINCT FROM NEW.document_id OR OLD.slot_id IS DISTINCT FROM NEW.slot_id
     OR OLD.gate_key IS DISTINCT FROM NEW.gate_key
     OR OLD.expected_track_version IS DISTINCT FROM NEW.expected_track_version
     OR OLD.expected_progress_version IS DISTINCT FROM NEW.expected_progress_version
     OR OLD.expected_assignment_version IS DISTINCT FROM NEW.expected_assignment_version
     OR OLD.language_id IS DISTINCT FROM NEW.language_id
     OR OLD.required_capabilities_json IS DISTINCT FROM NEW.required_capabilities_json
     OR OLD.mastery_level IS DISTINCT FROM NEW.mastery_level
     OR OLD.mastery_confidence IS DISTINCT FROM NEW.mastery_confidence
     OR OLD.misconception_tags_json IS DISTINCT FROM NEW.misconception_tags_json
     OR OLD.validation_profile_version IS DISTINCT FROM NEW.validation_profile_version
     OR OLD.request_hash IS DISTINCT FROM NEW.request_hash OR OLD.profile_hash IS DISTINCT FROM NEW.profile_hash
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Model review authoring identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('completed', 'failed', 'cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal model review authoring run is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'pending' AND NEW.state IN ('claimed', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'claimed' AND NEW.state IN ('running', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('validating', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'validating' AND NEW.state IN ('completed', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Model review authoring transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_candidate_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Model review candidate cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id OR OLD.authoring_run_id IS DISTINCT FROM NEW.authoring_run_id
     OR OLD.user_id IS DISTINCT FROM NEW.user_id OR OLD.track_id IS DISTINCT FROM NEW.track_id
     OR OLD.knowledge_key IS DISTINCT FROM NEW.knowledge_key
     OR OLD.public_payload_json IS DISTINCT FROM NEW.public_payload_json
     OR OLD.private_payload_json IS DISTINCT FROM NEW.private_payload_json
     OR OLD.public_hash IS DISTINCT FROM NEW.public_hash OR OLD.private_hash IS DISTINCT FROM NEW.private_hash
     OR OLD.candidate_hash IS DISTINCT FROM NEW.candidate_hash
     OR OLD.generator_version IS DISTINCT FROM NEW.generator_version
     OR OLD.prompt_schema_version IS DISTINCT FROM NEW.prompt_schema_version
     OR OLD.validation_profile_version IS DISTINCT FROM NEW.validation_profile_version
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Model review candidate payload is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('rejected', 'published') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal model review candidate is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'draft' AND NEW.state IN ('validating', 'rejected') THEN RETURN NEW; END IF;
  IF OLD.state = 'validating' AND NEW.state IN ('verified', 'rejected') THEN RETURN NEW; END IF;
  IF OLD.state = 'verified' AND NEW.state IN ('published', 'rejected') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Model review candidate transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_validation_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_model_review_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Model review validation run cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id OR OLD.authoring_run_id IS DISTINCT FROM NEW.authoring_run_id
     OR OLD.candidate_id IS DISTINCT FROM NEW.candidate_id OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.track_id IS DISTINCT FROM NEW.track_id
     OR OLD.validation_profile_version IS DISTINCT FROM NEW.validation_profile_version
     OR OLD.candidate_hash IS DISTINCT FROM NEW.candidate_hash OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Model review validation identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'verified' AND NEW.state = 'verified'
     AND OLD.action_receipt_hash IS NULL AND NEW.action_receipt_hash IS NOT NULL
     AND OLD.id IS NOT DISTINCT FROM NEW.id
     AND OLD.authoring_run_id IS NOT DISTINCT FROM NEW.authoring_run_id
     AND OLD.candidate_id IS NOT DISTINCT FROM NEW.candidate_id
     AND OLD.user_id IS NOT DISTINCT FROM NEW.user_id
     AND OLD.track_id IS NOT DISTINCT FROM NEW.track_id
     AND OLD.validation_profile_version IS NOT DISTINCT FROM NEW.validation_profile_version
     AND OLD.candidate_hash IS NOT DISTINCT FROM NEW.candidate_hash
     AND OLD.action_invocation_id IS NOT DISTINCT FROM NEW.action_invocation_id
     AND OLD.authority_hash IS NOT DISTINCT FROM NEW.authority_hash
     AND OLD.check_summary_code IS NOT DISTINCT FROM NEW.check_summary_code
     AND OLD.failure_code IS NOT DISTINCT FROM NEW.failure_code
     AND OLD.safe_summary IS NOT DISTINCT FROM NEW.safe_summary
     AND OLD.terminal_at IS NOT DISTINCT FROM NEW.terminal_at
     AND OLD.created_at IS NOT DISTINCT FROM NEW.created_at THEN
    RETURN NEW;
  END IF;
  IF OLD.state IN ('verified', 'failed', 'stale') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal model review validation run is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'pending' AND NEW.state IN ('running', 'failed', 'stale') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('verified', 'failed', 'stale') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Model review validation transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_model_review_authoring_runs_lifecycle ON tutor_model_review_authoring_runs;
CREATE TRIGGER trg_tutor_model_review_authoring_runs_lifecycle
BEFORE UPDATE OR DELETE ON tutor_model_review_authoring_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_authoring_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_model_review_authoring_runs_updated_at ON tutor_model_review_authoring_runs;
CREATE TRIGGER trg_tutor_model_review_authoring_runs_updated_at
BEFORE UPDATE ON tutor_model_review_authoring_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_model_review_candidates_lifecycle ON tutor_model_review_candidates;
CREATE TRIGGER trg_tutor_model_review_candidates_lifecycle
BEFORE UPDATE OR DELETE ON tutor_model_review_candidates
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_candidate_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_model_review_candidates_updated_at ON tutor_model_review_candidates;
CREATE TRIGGER trg_tutor_model_review_candidates_updated_at
BEFORE UPDATE ON tutor_model_review_candidates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_model_review_validation_runs_lifecycle ON tutor_model_review_validation_runs;
CREATE TRIGGER trg_tutor_model_review_validation_runs_lifecycle
BEFORE UPDATE OR DELETE ON tutor_model_review_validation_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_validation_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_model_review_validation_runs_updated_at ON tutor_model_review_validation_runs;
CREATE TRIGGER trg_tutor_model_review_validation_runs_updated_at
BEFORE UPDATE ON tutor_model_review_validation_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_model_review_authoring_attempts_immutable ON tutor_model_review_authoring_attempt_receipts;
CREATE TRIGGER trg_tutor_model_review_authoring_attempts_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_authoring_attempt_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_model_review_validation_checks_immutable ON tutor_model_review_validation_checks;
CREATE TRIGGER trg_tutor_model_review_validation_checks_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_validation_checks
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_model_review_publications_immutable ON tutor_model_review_publications;
CREATE TRIGGER trg_tutor_model_review_publications_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_publications
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_model_review_evidence_immutable ON tutor_model_review_evidence_receipts;
CREATE TRIGGER trg_tutor_model_review_evidence_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_evidence_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_append_only();

CREATE INDEX IF NOT EXISTS idx_tutor_model_review_authoring_active
  ON tutor_model_review_authoring_runs(user_id, track_id, knowledge_key, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_model_review_candidates_authoring
  ON tutor_model_review_candidates(authoring_run_id, state, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_model_review_validation_state
  ON tutor_model_review_validation_runs(state, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_execution_intents_model_review_validation
  ON tutor_execution_intents(model_review_validation_id)
  WHERE model_review_validation_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_execution_jobs_model_review_validation
  ON tutor_execution_jobs(model_review_validation_id)
  WHERE model_review_validation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_model_review_publications_scope
  ON tutor_model_review_publications(user_id, track_id, knowledge_key, published_at DESC);


-- Detailed assistance records whether a model-review learner viewed prepublication evidence.
ALTER TABLE tutor_exercise_attempts
  ADD COLUMN IF NOT EXISTS assistance_kind text NOT NULL DEFAULT 'independent';
ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS tutor_exercise_attempts_assistance_kind_check;
ALTER TABLE tutor_exercise_attempts ADD CONSTRAINT tutor_exercise_attempts_assistance_kind_check CHECK (
  assistance_kind IN ('independent', 'hinted', 'validation_evidence_viewed', 'remediated')
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_model_review_publications'::regclass
      AND conname = 'uq_tutor_model_review_publications_id_user'
  ) THEN
    ALTER TABLE tutor_model_review_publications
      ADD CONSTRAINT uq_tutor_model_review_publications_id_user UNIQUE (id, user_id);
  END IF;
END $$;
ALTER TABLE tutor_model_review_authoring_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_model_review_authoring_candidate;
ALTER TABLE tutor_model_review_authoring_runs
  ADD CONSTRAINT fk_tutor_model_review_authoring_candidate
  FOREIGN KEY (candidate_id, user_id)
  REFERENCES tutor_model_review_candidates(id, user_id) ON DELETE NO ACTION
  DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE tutor_model_review_authoring_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_model_review_authoring_validation;
ALTER TABLE tutor_model_review_authoring_runs
  ADD CONSTRAINT fk_tutor_model_review_authoring_validation
  FOREIGN KEY (validation_run_id, user_id)
  REFERENCES tutor_model_review_validation_runs(id, user_id) ON DELETE NO ACTION
  DEFERRABLE INITIALLY IMMEDIATE;
ALTER TABLE tutor_model_review_authoring_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_model_review_authoring_publication;
ALTER TABLE tutor_model_review_authoring_runs
  ADD CONSTRAINT fk_tutor_model_review_authoring_publication
  FOREIGN KEY (publication_id, user_id)
  REFERENCES tutor_model_review_publications(id, user_id) ON DELETE NO ACTION
  DEFERRABLE INITIALLY IMMEDIATE;
