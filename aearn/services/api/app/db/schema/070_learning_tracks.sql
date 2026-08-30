-- Child 08-04 LearningTrack domain: additive track-scoped teaching authority.
-- This state is isolated from retired learning_* tables and the user-level tutor_plan_revisions contract.
CREATE TABLE IF NOT EXISTS tutor_learning_tracks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  language_id text NOT NULL CHECK (char_length(language_id) BETWEEN 1 AND 80),
  goal_text text NOT NULL CHECK (char_length(goal_text) BETWEEN 1 AND 2000),
  target_level text NOT NULL CHECK (char_length(target_level) BETWEEN 1 AND 120),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
  current_knowledge_key text CHECK (
    current_knowledge_key IS NULL OR current_knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  last_learned_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  CONSTRAINT uq_tutor_learning_tracks_id_user UNIQUE (id, user_id),
  CONSTRAINT chk_tutor_learning_tracks_archive_state CHECK (
    (status = 'archived') = (archived_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_track_plan_revisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  predecessor_revision_id uuid,
  status text NOT NULL CHECK (status IN ('proposed', 'active', 'superseded', 'rejected')),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  target_level text NOT NULL CHECK (char_length(target_level) BETWEEN 1 AND 120),
  plan_json jsonb NOT NULL CHECK (jsonb_typeof(plan_json) = 'object'),
  generator_version text NOT NULL CHECK (char_length(generator_version) BETWEEN 1 AND 160),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  change_reason text NOT NULL CHECK (char_length(change_reason) BETWEEN 1 AND 600),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  activated_at timestamptz,
  CONSTRAINT uq_tutor_track_plan_revisions_id_scope UNIQUE (id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_revision_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_revision_predecessor_scope
    FOREIGN KEY (predecessor_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_track_plan_revision_predecessor_distinct CHECK (
    predecessor_revision_id IS NULL OR predecessor_revision_id <> id
  ),
  CONSTRAINT chk_tutor_track_plan_revision_activation CHECK (
    (status IN ('active', 'superseded')) = (activated_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_track_active_plans (
  track_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_track_active_plans_scope UNIQUE (track_id, user_id),
  CONSTRAINT fk_tutor_track_active_plan_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_active_plan_revision_scope
    FOREIGN KEY (revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_track_plan_modules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  revision_id uuid NOT NULL,
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  module_key text NOT NULL CHECK (module_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
  order_index integer NOT NULL CHECK (order_index >= 0),
  is_core boolean NOT NULL DEFAULT true,
  is_skippable boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_track_plan_modules_revision_key UNIQUE (revision_id, module_key),
  CONSTRAINT uq_tutor_track_plan_modules_revision_order UNIQUE (revision_id, order_index),
  CONSTRAINT uq_tutor_track_plan_modules_id_scope UNIQUE (id, revision_id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_module_revision_scope
    FOREIGN KEY (revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_track_plan_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  module_id uuid NOT NULL,
  revision_id uuid NOT NULL,
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  description text NOT NULL DEFAULT '' CHECK (char_length(description) <= 2000),
  order_index integer NOT NULL CHECK (order_index >= 0),
  is_core boolean NOT NULL DEFAULT true,
  prerequisite_keys_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(prerequisite_keys_json) = 'array'),
  required_capabilities_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_track_plan_nodes_revision_key UNIQUE (revision_id, knowledge_key),
  CONSTRAINT uq_tutor_track_plan_nodes_revision_scope_key UNIQUE (revision_id, track_id, user_id, knowledge_key),
  CONSTRAINT uq_tutor_track_plan_nodes_module_order UNIQUE (module_id, order_index),
  CONSTRAINT uq_tutor_track_plan_nodes_id_scope UNIQUE (id, revision_id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_node_module_scope
    FOREIGN KEY (module_id, revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_modules(id, revision_id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_node_revision_scope
    FOREIGN KEY (revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_track_node_progress (
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  status text NOT NULL CHECK (status IN (
    'locked', 'available', 'in_progress', 'completed', 'review_due', 'diagnostic_skipped'
  )),
  source_plan_revision_id uuid NOT NULL,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, knowledge_key),
  CONSTRAINT uq_tutor_track_node_progress_scope UNIQUE (track_id, user_id, knowledge_key),
  CONSTRAINT fk_tutor_track_node_progress_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_node_progress_revision_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_node_progress_source_node
    FOREIGN KEY (source_plan_revision_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_track_node_progress_times CHECK (
    (status IN ('in_progress', 'completed', 'review_due', 'diagnostic_skipped')) = (started_at IS NOT NULL)
    AND (status IN ('completed', 'review_due', 'diagnostic_skipped')) = (completed_at IS NOT NULL)
  )
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_learning_tracks'::regclass
      AND conname = 'fk_tutor_learning_track_current_progress'
  ) THEN
    ALTER TABLE tutor_learning_tracks
      ADD CONSTRAINT fk_tutor_learning_track_current_progress
      FOREIGN KEY (id, user_id, current_knowledge_key)
      REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key)
      ON DELETE RESTRICT;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_track_plan_revisions'::regclass
      AND conname = 'chk_tutor_track_plan_revision_predecessor_distinct'
  ) THEN
    ALTER TABLE tutor_track_plan_revisions
      ADD CONSTRAINT chk_tutor_track_plan_revision_predecessor_distinct CHECK (
        predecessor_revision_id IS NULL OR predecessor_revision_id <> id
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_track_plan_nodes'::regclass
      AND conname = 'uq_tutor_track_plan_nodes_revision_scope_key'
  ) THEN
    ALTER TABLE tutor_track_plan_nodes
      ADD CONSTRAINT uq_tutor_track_plan_nodes_revision_scope_key
      UNIQUE (revision_id, track_id, user_id, knowledge_key);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_track_node_progress'::regclass
      AND conname = 'fk_tutor_track_node_progress_source_node'
  ) THEN
    ALTER TABLE tutor_track_node_progress
      ADD CONSTRAINT fk_tutor_track_node_progress_source_node
      FOREIGN KEY (source_plan_revision_id, track_id, user_id, knowledge_key)
      REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key)
      ON DELETE RESTRICT;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_track_plan_migrations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  from_revision_id uuid NOT NULL,
  to_revision_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'rejected', 'applied')),
  impact_json jsonb NOT NULL CHECK (jsonb_typeof(impact_json) = 'object'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  applied_at timestamptz,
  CONSTRAINT uq_tutor_track_plan_migrations_track_key UNIQUE (track_id, idempotency_key),
  CONSTRAINT uq_tutor_track_plan_migrations_revision UNIQUE (track_id, to_revision_id),
  CONSTRAINT uq_tutor_track_plan_migrations_id_scope UNIQUE (id, track_id, user_id),
  CONSTRAINT fk_tutor_track_plan_migration_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_migration_from_scope
    FOREIGN KEY (from_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_track_plan_migration_to_scope
    FOREIGN KEY (to_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_track_plan_migration_distinct CHECK (from_revision_id <> to_revision_id),
  CONSTRAINT chk_tutor_track_plan_migration_times CHECK (
    (status IN ('confirmed', 'applied')) = (confirmed_at IS NOT NULL)
    AND ((status = 'applied') = (applied_at IS NOT NULL))
  )
);

DO $$
BEGIN
  -- Upgrade databases bootstrapped by an earlier draft whose implication-only
  -- checks did not require lifecycle timestamps for progressed/applied rows.
  ALTER TABLE tutor_track_node_progress
    DROP CONSTRAINT IF EXISTS chk_tutor_track_node_progress_times;
  ALTER TABLE tutor_track_node_progress
    ADD CONSTRAINT chk_tutor_track_node_progress_times CHECK (
      (status IN ('in_progress', 'completed', 'review_due', 'diagnostic_skipped')) = (started_at IS NOT NULL)
      AND (status IN ('completed', 'review_due', 'diagnostic_skipped')) = (completed_at IS NOT NULL)
    );

  ALTER TABLE tutor_track_plan_migrations
    DROP CONSTRAINT IF EXISTS chk_tutor_track_plan_migration_times;
  ALTER TABLE tutor_track_plan_migrations
    ADD CONSTRAINT chk_tutor_track_plan_migration_times CHECK (
      (status IN ('confirmed', 'applied')) = (confirmed_at IS NOT NULL)
      AND ((status = 'applied') = (applied_at IS NOT NULL))
    );
END $$;

CREATE TABLE IF NOT EXISTS tutor_mastery_evidence (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  evidence_kind text NOT NULL CHECK (evidence_kind IN (
    'gate', 'module_diagnostic', 'review', 'model_code_review', 'trusted_import'
  )),
  evidence_effect text NOT NULL DEFAULT 'reinforcing' CHECK (evidence_effect IN (
    'reinforcing', 'observational_non_degrading'
  )),
  source_receipt_id text NOT NULL CHECK (char_length(source_receipt_id) BETWEEN 1 AND 160),
  source_receipt_hash text NOT NULL CHECK (source_receipt_hash ~ '^[0-9a-f]{64}$'),
  independence text NOT NULL CHECK (independence IN ('independent', 'hinted', 'remediated')),
  score double precision NOT NULL CHECK (score >= 0 AND score <= 1),
  hint_count integer NOT NULL DEFAULT 0 CHECK (hint_count >= 0),
  attempt_count integer NOT NULL DEFAULT 1 CHECK (attempt_count >= 1),
  evidence_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(evidence_summary_json) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_mastery_evidence_receipt UNIQUE (track_id, evidence_kind, source_receipt_id),
  CONSTRAINT uq_tutor_mastery_evidence_id_scope UNIQUE (id, track_id, user_id, knowledge_key),
  CONSTRAINT fk_tutor_mastery_evidence_progress_scope
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_mastery_states (
  track_id uuid NOT NULL,
  user_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  confidence double precision NOT NULL DEFAULT 0 CHECK (confidence >= 0 AND confidence <= 1),
  mastery_level text NOT NULL DEFAULT 'unseen' CHECK (mastery_level IN (
    'unseen', 'emerging', 'developing', 'proficient', 'durable'
  )),
  strengths_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(strengths_json) = 'array'),
  weaknesses_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(weaknesses_json) = 'array'),
  evidence_count integer NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
  last_evidence_id uuid,
  observation_count integer NOT NULL DEFAULT 0 CHECK (observation_count >= 0),
  last_observation_id uuid,
  projector_version text NOT NULL CHECK (char_length(projector_version) BETWEEN 1 AND 160),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, knowledge_key),
  CONSTRAINT uq_tutor_mastery_states_scope UNIQUE (track_id, user_id, knowledge_key),
  CONSTRAINT fk_tutor_mastery_state_progress_scope
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_mastery_state_last_evidence_scope
    FOREIGN KEY (last_evidence_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_mastery_evidence(id, track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_mastery_state_evidence CHECK (
    (evidence_count = 0) = (last_evidence_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_conversation_learning_scopes (
  conversation_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  scope_kind text NOT NULL DEFAULT 'general' CHECK (scope_kind IN ('general', 'plan_drafting', 'learning_track')),
  learning_track_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversation_learning_scopes_scope UNIQUE (conversation_id, user_id),
  CONSTRAINT fk_tutor_conversation_learning_scope_conversation_user
    FOREIGN KEY (conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_conversation_learning_scope_track_user
    FOREIGN KEY (learning_track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_conversation_learning_scope_shape CHECK (
    (scope_kind = 'learning_track' AND learning_track_id IS NOT NULL)
    OR (scope_kind IN ('general', 'plan_drafting') AND learning_track_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_run_learning_scopes (
  run_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  scope_kind text NOT NULL CHECK (scope_kind IN ('general', 'plan_drafting', 'learning_track')),
  learning_track_id uuid,
  task_kind text NOT NULL CHECK (task_kind IN (
    'general_tutor', 'plan_drafting', 'lesson_teaching', 'exercise_feedback',
    'review_coaching', 'model_code_review', 'remediation'
  )),
  knowledge_key text CHECK (knowledge_key IS NULL OR knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  scope_version integer NOT NULL CHECK (scope_version >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_run_learning_scopes_scope UNIQUE (run_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_run_learning_scope_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_conversation_user
    FOREIGN KEY (conversation_id, user_id) REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_track_user
    FOREIGN KEY (learning_track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_learning_scope_progress
    FOREIGN KEY (learning_track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_run_learning_scope_shape CHECK (
    (scope_kind = 'general' AND learning_track_id IS NULL AND knowledge_key IS NULL AND task_kind = 'general_tutor')
    OR (scope_kind = 'plan_drafting' AND learning_track_id IS NULL AND knowledge_key IS NULL AND task_kind = 'plan_drafting')
    OR (
      scope_kind = 'learning_track'
      AND learning_track_id IS NOT NULL
      AND task_kind IN ('lesson_teaching', 'exercise_feedback', 'review_coaching', 'model_code_review', 'remediation')
    )
  )
);

CREATE TABLE IF NOT EXISTS tutor_learning_plan_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'collecting' CHECK (status IN ('collecting', 'draft_ready', 'confirmed', 'cancelled')),
  preferred_language_id text CHECK (
    preferred_language_id IS NULL OR char_length(preferred_language_id) BETWEEN 1 AND 80
  ),
  current_draft_id uuid,
  confirmed_track_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  last_error_code text CHECK (
    last_error_code IS NULL OR last_error_code ~ '^[A-Z][A-Z0-9_]{2,79}$'
  ),
  last_error_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  cancelled_at timestamptz,
  CONSTRAINT uq_tutor_learning_plan_sessions_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_learning_plan_sessions_conversation_user UNIQUE (conversation_id, user_id),
  CONSTRAINT fk_tutor_learning_plan_session_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_plan_session_confirmed_track_user
    FOREIGN KEY (confirmed_track_id, user_id)
    REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_learning_plan_session_error_shape CHECK (
    (last_error_code IS NULL) = (last_error_at IS NULL)
  ),
  CONSTRAINT chk_tutor_learning_plan_session_status_shape CHECK (
    (status = 'collecting' AND current_draft_id IS NULL AND confirmed_track_id IS NULL
      AND confirmed_at IS NULL AND cancelled_at IS NULL)
    OR (status = 'draft_ready' AND current_draft_id IS NOT NULL AND confirmed_track_id IS NULL
      AND confirmed_at IS NULL AND cancelled_at IS NULL)
    OR (status = 'confirmed' AND current_draft_id IS NOT NULL AND confirmed_track_id IS NOT NULL
      AND confirmed_at IS NOT NULL AND cancelled_at IS NULL)
    OR (status = 'cancelled' AND confirmed_track_id IS NULL AND confirmed_at IS NULL
      AND cancelled_at IS NOT NULL)
  )
);

ALTER TABLE tutor_learning_plan_sessions
  ADD COLUMN IF NOT EXISTS facts_policy_version text CHECK (
    facts_policy_version IS NULL OR char_length(facts_policy_version) BETWEEN 1 AND 160
  );

CREATE TABLE IF NOT EXISTS tutor_planning_intake_facts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  field_key text NOT NULL CHECK (field_key IN (
    'language_id', 'goal_text', 'target_level', 'weekly_minutes',
    'experience_level', 'teaching_preferences', 'pace_constraints'
  )),
  value_json jsonb NOT NULL,
  value_hash text NOT NULL CHECK (value_hash ~ '^[0-9a-f]{64}$'),
  revision integer NOT NULL CHECK (revision >= 1),
  state text NOT NULL CHECK (state IN ('answered_unconfirmed', 'confirmed', 'withdrawn')),
  source_kind text NOT NULL CHECK (source_kind IN ('deterministic_input', 'explicit_input', 'explicit_confirmation')),
  source_message_id uuid NOT NULL,
  source_run_id uuid NOT NULL,
  source_input_revision integer NOT NULL CHECK (source_input_revision >= 1),
  supersedes_fact_id uuid,
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_planning_intake_facts_id_scope UNIQUE (id, session_id, user_id),
  CONSTRAINT uq_tutor_planning_intake_facts_session_field_revision UNIQUE (session_id, field_key, revision),
  CONSTRAINT uq_tutor_planning_intake_facts_source_value
    UNIQUE (session_id, field_key, source_run_id, source_input_revision, value_hash),
  CONSTRAINT fk_tutor_planning_intake_fact_session_user
    FOREIGN KEY (session_id, user_id)
    REFERENCES tutor_learning_plan_sessions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_message_conversation
    FOREIGN KEY (source_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_input_evidence
    FOREIGN KEY (source_run_id, source_message_id, source_input_revision)
    REFERENCES tutor_run_input_events(run_id, message_id, input_revision) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_intake_fact_predecessor_scope
    FOREIGN KEY (supersedes_fact_id, session_id, user_id)
    REFERENCES tutor_planning_intake_facts(id, session_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_planning_intake_fact_predecessor_distinct CHECK (
    supersedes_fact_id IS NULL OR supersedes_fact_id <> id
  ),
  CONSTRAINT chk_tutor_planning_intake_fact_revision_shape CHECK (
    (revision = 1 AND supersedes_fact_id IS NULL)
    OR (revision > 1 AND supersedes_fact_id IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_planning_intake_facts_user_session
  ON tutor_planning_intake_facts(user_id, session_id, field_key, revision DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_planning_intake_facts_message
  ON tutor_planning_intake_facts(source_message_id);

CREATE TABLE IF NOT EXISTS tutor_planning_question_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  field_key text NOT NULL CHECK (field_key IN (
    'language_id', 'goal_text', 'target_level', 'weekly_minutes',
    'experience_level', 'teaching_preferences', 'pace_constraints'
  )),
  question_key text NOT NULL CHECK (question_key = field_key),
  status text NOT NULL CHECK (status IN (
    'unasked', 'asked', 'answered_unconfirmed', 'confirmed',
    'superseded', 'reopened', 'withdrawn', 'reasked_blocked'
  )),
  source_run_id uuid,
  source_message_id uuid,
  source_input_revision integer CHECK (source_input_revision IS NULL OR source_input_revision >= 1),
  fact_id uuid,
  previous_event_id uuid,
  reason_code text NOT NULL CHECK (char_length(reason_code) BETWEEN 1 AND 120),
  event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_planning_question_events_session_hash UNIQUE (session_id, event_hash),
  CONSTRAINT uq_tutor_planning_question_events_id_scope UNIQUE (id, session_id, user_id),
  CONSTRAINT fk_tutor_planning_question_event_session_user
    FOREIGN KEY (session_id, user_id)
    REFERENCES tutor_learning_plan_sessions(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_message_conversation
    FOREIGN KEY (source_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_fact_scope
    FOREIGN KEY (fact_id, session_id, user_id)
    REFERENCES tutor_planning_intake_facts(id, session_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_planning_question_event_previous_scope
    FOREIGN KEY (previous_event_id, session_id, user_id)
    REFERENCES tutor_planning_question_events(id, session_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_planning_question_event_source_shape CHECK (
    (source_run_id IS NULL AND source_message_id IS NULL AND source_input_revision IS NULL)
    OR (source_run_id IS NOT NULL AND source_input_revision IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_planning_question_events_session_field
  ON tutor_planning_question_events(session_id, field_key, created_at DESC, id DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_planning_question_events_previous
  ON tutor_planning_question_events(previous_event_id)
  WHERE previous_event_id IS NOT NULL;

ALTER TABLE tutor_planning_question_events
  DROP CONSTRAINT IF EXISTS tutor_planning_question_events_status_check;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_planning_question_events'::regclass
      AND conname = 'chk_tutor_planning_question_events_status'
  ) THEN
    ALTER TABLE tutor_planning_question_events
      ADD CONSTRAINT chk_tutor_planning_question_events_status CHECK (status IN (
        'unasked', 'asked', 'answered_unconfirmed', 'confirmed',
        'superseded', 'reopened', 'withdrawn', 'reasked_blocked'
      ));
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION enforce_tutor_planning_fact_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('aearn.learning_track_purge_user_id', true) = OLD.user_id::text THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor planning intake facts are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_planning_question_event_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('aearn.learning_track_purge_user_id', true) = OLD.user_id::text THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor planning question events are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_planning_intake_facts_immutable ON tutor_planning_intake_facts;
CREATE TRIGGER trg_tutor_planning_intake_facts_immutable
BEFORE UPDATE OR DELETE ON tutor_planning_intake_facts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_planning_fact_append_only();

DROP TRIGGER IF EXISTS trg_tutor_planning_question_events_immutable ON tutor_planning_question_events;
CREATE TRIGGER trg_tutor_planning_question_events_immutable
BEFORE UPDATE OR DELETE ON tutor_planning_question_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_planning_question_event_append_only();

CREATE TABLE IF NOT EXISTS tutor_learning_plan_drafts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  draft_version integer NOT NULL CHECK (draft_version >= 1),
  predecessor_draft_id uuid,
  language_id text NOT NULL CHECK (char_length(language_id) BETWEEN 1 AND 80),
  goal_text text NOT NULL CHECK (char_length(goal_text) BETWEEN 1 AND 2000),
  target_level text NOT NULL CHECK (char_length(target_level) BETWEEN 1 AND 120),
  weekly_minutes integer NOT NULL CHECK (weekly_minutes BETWEEN 15 AND 10080),
  experience_level text NOT NULL CHECK (experience_level IN ('new', 'beginner', 'intermediate', 'advanced')),
  teaching_preferences_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
    jsonb_typeof(teaching_preferences_json) = 'array'
    AND jsonb_array_length(teaching_preferences_json) <= 4
  ),
  pace_summary text NOT NULL CHECK (char_length(pace_summary) BETWEEN 1 AND 240),
  profile_json jsonb NOT NULL CHECK (jsonb_typeof(profile_json) = 'object'),
  plan_json jsonb NOT NULL CHECK (jsonb_typeof(plan_json) = 'object'),
  source_summary_json jsonb NOT NULL CHECK (
    jsonb_typeof(source_summary_json) = 'array'
    AND jsonb_array_length(source_summary_json) BETWEEN 1 AND 8
  ),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  generator_version text NOT NULL CHECK (char_length(generator_version) BETWEEN 1 AND 160),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  change_reason text NOT NULL CHECK (char_length(change_reason) BETWEEN 1 AND 600),
  source_run_id uuid NOT NULL,
  source_input_revision integer NOT NULL CHECK (source_input_revision >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_plan_drafts_id_scope UNIQUE (id, session_id, user_id),
  CONSTRAINT uq_tutor_learning_plan_drafts_session_version UNIQUE (session_id, draft_version),
  CONSTRAINT uq_tutor_learning_plan_drafts_source_revision UNIQUE (source_run_id, source_input_revision),
  CONSTRAINT fk_tutor_learning_plan_draft_session_user
    FOREIGN KEY (session_id, user_id)
    REFERENCES tutor_learning_plan_sessions(id, user_id) ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_learning_plan_draft_predecessor_scope
    FOREIGN KEY (predecessor_draft_id, session_id, user_id)
    REFERENCES tutor_learning_plan_drafts(id, session_id, user_id) ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_learning_plan_draft_run_user
    FOREIGN KEY (source_run_id, user_id)
    REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_learning_plan_draft_predecessor_distinct CHECK (
    predecessor_draft_id IS NULL OR predecessor_draft_id <> id
  ),
  CONSTRAINT chk_tutor_learning_plan_draft_version_shape CHECK (
    (draft_version = 1 AND predecessor_draft_id IS NULL)
    OR (draft_version > 1 AND predecessor_draft_id IS NOT NULL)
  )
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_tutor_learning_plan_session_current_draft_scope'
  ) THEN
    ALTER TABLE tutor_learning_plan_sessions
      ADD CONSTRAINT fk_tutor_learning_plan_session_current_draft_scope
      FOREIGN KEY (current_draft_id, id, user_id)
      REFERENCES tutor_learning_plan_drafts(id, session_id, user_id) ON DELETE RESTRICT
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_learning_plan_sessions_one_active
  ON tutor_learning_plan_sessions(user_id)
  WHERE status IN ('collecting', 'draft_ready');
CREATE INDEX IF NOT EXISTS idx_tutor_learning_plan_sessions_user_updated
  ON tutor_learning_plan_sessions(user_id, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_plan_drafts_session_version
  ON tutor_learning_plan_drafts(session_id, draft_version DESC);
ALTER TABLE tutor_learning_plan_drafts
  ADD COLUMN IF NOT EXISTS facts_fingerprint text CHECK (
    facts_fingerprint IS NULL OR facts_fingerprint ~ '^[0-9a-f]{64}$'
  );
ALTER TABLE tutor_learning_plan_drafts
  ADD COLUMN IF NOT EXISTS facts_revision integer NOT NULL DEFAULT 0 CHECK (facts_revision >= 0);


CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_track_plan_revisions_one_active
  ON tutor_track_plan_revisions(track_id) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_learning_tracks_user_updated
  ON tutor_learning_tracks(user_id, updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_track_plan_revisions_track_created
  ON tutor_track_plan_revisions(track_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_track_plan_nodes_revision_order
  ON tutor_track_plan_nodes(revision_id, module_id, order_index);
CREATE INDEX IF NOT EXISTS idx_tutor_track_node_progress_user_status
  ON tutor_track_node_progress(user_id, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_track_plan_migrations_track_created
  ON tutor_track_plan_migrations(track_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_mastery_evidence_track_key_created
  ON tutor_mastery_evidence(track_id, knowledge_key, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tutor_conversation_learning_scopes_user_track
  ON tutor_conversation_learning_scopes(user_id, learning_track_id);
CREATE INDEX IF NOT EXISTS idx_tutor_run_learning_scopes_user_track
  ON tutor_run_learning_scopes(user_id, learning_track_id, created_at DESC);

CREATE OR REPLACE FUNCTION tutor_learning_track_purge_allowed(target_user_id uuid)
RETURNS boolean AS $$
BEGIN
  RETURN current_setting('aearn.learning_track_purge_user_id', true) = target_user_id::text;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_plan_draft_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor learning plan drafts are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_learning_plan_sessions_updated_at ON tutor_learning_plan_sessions;
CREATE TRIGGER trg_tutor_learning_plan_sessions_updated_at
BEFORE UPDATE ON tutor_learning_plan_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_learning_plan_drafts_immutable ON tutor_learning_plan_drafts;
CREATE TRIGGER trg_tutor_learning_plan_drafts_immutable
BEFORE UPDATE OR DELETE ON tutor_learning_plan_drafts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_plan_draft_immutable();

CREATE OR REPLACE FUNCTION enforce_tutor_track_plan_revision_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'active' AND NEW.predecessor_revision_id IS NULL AND NEW.activated_at IS NOT NULL THEN
      RETURN NEW;
    END IF;
    IF NEW.status = 'proposed' AND NEW.predecessor_revision_id IS NOT NULL AND NEW.activated_at IS NULL THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Tutor track plan revision initial lifecycle is invalid' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF NOT tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RAISE EXCEPTION 'Tutor track plan revisions are immutable' USING ERRCODE = '23514';
    END IF;
    RETURN OLD;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.predecessor_revision_id IS DISTINCT FROM OLD.predecessor_revision_id
     OR NEW.title IS DISTINCT FROM OLD.title
     OR NEW.target_level IS DISTINCT FROM OLD.target_level
     OR NEW.plan_json IS DISTINCT FROM OLD.plan_json
     OR NEW.generator_version IS DISTINCT FROM OLD.generator_version
     OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
     OR NEW.change_reason IS DISTINCT FROM OLD.change_reason
     OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Tutor track plan revision content is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status IN ('proposed', 'active', 'rejected') THEN
    NULL;
  ELSIF OLD.status = 'active' AND NEW.status IN ('active', 'superseded') THEN
    NULL;
  ELSIF OLD.status = NEW.status AND OLD.status IN ('superseded', 'rejected') THEN
    NULL;
  ELSE
    RAISE EXCEPTION 'Tutor track plan revision lifecycle transition is invalid' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = NEW.status AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
    RAISE EXCEPTION 'Tutor track plan revision activation timestamp is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'active'
     AND (OLD.activated_at IS NOT NULL OR NEW.activated_at IS NULL) THEN
    RAISE EXCEPTION 'Tutor track plan revision activation timestamp is invalid' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'rejected'
     AND NEW.activated_at IS NOT NULL THEN
    RAISE EXCEPTION 'Rejected Tutor track plan revision cannot be activated' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'active' AND NEW.status = 'superseded'
     AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
    RAISE EXCEPTION 'Superseded Tutor track plan revision must preserve activation time' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_track_plan_structure_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor track plan structure is immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_track_plan_migration_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.status = 'proposed' AND NEW.confirmed_at IS NULL AND NEW.applied_at IS NULL THEN
      RETURN NEW;
    END IF;
    RAISE EXCEPTION 'Tutor track plan migration initial lifecycle is invalid' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Tutor track plan migration evidence is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.from_revision_id IS DISTINCT FROM OLD.from_revision_id
     OR NEW.to_revision_id IS DISTINCT FROM OLD.to_revision_id
     OR NEW.impact_json IS DISTINCT FROM OLD.impact_json
     OR NEW.expected_track_version IS DISTINCT FROM OLD.expected_track_version
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Tutor track plan migration evidence is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = NEW.status
     AND (
       NEW.confirmed_at IS DISTINCT FROM OLD.confirmed_at
       OR NEW.applied_at IS DISTINCT FROM OLD.applied_at
     ) THEN
    RAISE EXCEPTION 'Tutor track plan migration timestamps are immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'proposed' THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'confirmed'
     AND OLD.confirmed_at IS NULL AND NEW.confirmed_at IS NOT NULL AND NEW.applied_at IS NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'applied'
     AND OLD.confirmed_at IS NULL AND NEW.confirmed_at IS NOT NULL AND NEW.applied_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'rejected'
     AND NEW.confirmed_at IS NULL AND NEW.applied_at IS NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'confirmed' AND NEW.status = 'confirmed' THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'confirmed' AND NEW.status = 'applied'
     AND NEW.confirmed_at IS NOT DISTINCT FROM OLD.confirmed_at AND NEW.applied_at IS NOT NULL THEN
    RETURN NEW;
  END IF;
  IF OLD.status = NEW.status AND OLD.status IN ('applied', 'rejected') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Tutor track plan migration lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_mastery_evidence_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor mastery evidence is append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_run_learning_scope_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor run learning scope is immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_track_current_key_active()
RETURNS trigger AS $$
BEGIN
  IF NEW.current_knowledge_key IS NULL THEN
    RETURN NEW;
  END IF;
  IF NOT EXISTS (
    SELECT 1
    FROM tutor_track_active_plans AS active
    JOIN tutor_track_plan_nodes AS nodes
      ON (nodes.revision_id, nodes.track_id, nodes.user_id) =
         (active.revision_id, active.track_id, active.user_id)
    JOIN tutor_track_node_progress AS progress
      ON (progress.track_id, progress.user_id, progress.knowledge_key) =
         (nodes.track_id, nodes.user_id, nodes.knowledge_key)
    WHERE active.track_id = NEW.id
      AND active.user_id = NEW.user_id
      AND nodes.knowledge_key = NEW.current_knowledge_key
  ) THEN
    RAISE EXCEPTION 'Tutor learning track current key must belong to the active plan' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_track_active_plan_consistency()
RETURNS trigger AS $$
DECLARE
  target_track_id uuid;
  target_user_id uuid;
  target_revision_id uuid;
  target_status text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Tutor track active pointer cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF TG_TABLE_NAME = 'tutor_track_active_plans' THEN
    target_track_id := NEW.track_id;
    target_user_id := NEW.user_id;
    target_revision_id := NEW.revision_id;
    SELECT status INTO target_status
    FROM tutor_track_plan_revisions
    WHERE id = target_revision_id AND track_id = target_track_id AND user_id = target_user_id;
    IF target_status IS DISTINCT FROM 'active' THEN
      RAISE EXCEPTION 'Tutor track active pointer must reference an active revision' USING ERRCODE = '23514';
    END IF;
  ELSE
    target_track_id := NEW.track_id;
    target_user_id := NEW.user_id;
    target_revision_id := NEW.id;
    target_status := NEW.status;
    IF target_status = 'active' AND NOT EXISTS (
      SELECT 1 FROM tutor_track_active_plans
      WHERE track_id = target_track_id AND user_id = target_user_id AND revision_id = target_revision_id
    ) THEN
      RAISE EXCEPTION 'Active Tutor track revision must be the active pointer' USING ERRCODE = '23514';
    END IF;
    IF target_status <> 'active' AND EXISTS (
      SELECT 1 FROM tutor_track_active_plans
      WHERE track_id = target_track_id AND user_id = target_user_id AND revision_id = target_revision_id
    ) THEN
      RAISE EXCEPTION 'Tutor track active pointer cannot reference a non-active revision' USING ERRCODE = '23514';
    END IF;
  END IF;
  IF target_status = 'active' AND EXISTS (
    SELECT 1
    FROM tutor_learning_tracks AS tracks
    WHERE tracks.id = target_track_id
      AND tracks.user_id = target_user_id
      AND tracks.current_knowledge_key IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM tutor_track_plan_nodes AS nodes
        WHERE nodes.revision_id = target_revision_id
          AND nodes.track_id = target_track_id
          AND nodes.user_id = target_user_id
          AND nodes.knowledge_key = tracks.current_knowledge_key
      )
  ) THEN
    RAISE EXCEPTION 'Tutor learning track current key must belong to the active revision' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_learning_tracks_updated_at ON tutor_learning_tracks;
CREATE TRIGGER trg_tutor_learning_tracks_updated_at BEFORE UPDATE ON tutor_learning_tracks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_learning_tracks_current_key_active ON tutor_learning_tracks;
CREATE TRIGGER trg_tutor_learning_tracks_current_key_active
BEFORE INSERT OR UPDATE OF current_knowledge_key ON tutor_learning_tracks
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_track_current_key_active();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_revisions_immutable ON tutor_track_plan_revisions;
CREATE TRIGGER trg_tutor_track_plan_revisions_immutable
BEFORE INSERT OR UPDATE OR DELETE ON tutor_track_plan_revisions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_revision_immutable();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_revisions_active_consistency ON tutor_track_plan_revisions;
CREATE CONSTRAINT TRIGGER trg_tutor_track_plan_revisions_active_consistency
AFTER INSERT OR UPDATE ON tutor_track_plan_revisions
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_active_plan_consistency();

DROP TRIGGER IF EXISTS trg_tutor_track_active_plans_updated_at ON tutor_track_active_plans;
CREATE TRIGGER trg_tutor_track_active_plans_updated_at BEFORE UPDATE ON tutor_track_active_plans
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_track_active_plans_consistency ON tutor_track_active_plans;
CREATE CONSTRAINT TRIGGER trg_tutor_track_active_plans_consistency
AFTER INSERT OR UPDATE OR DELETE ON tutor_track_active_plans
DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_active_plan_consistency();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_modules_immutable ON tutor_track_plan_modules;
CREATE TRIGGER trg_tutor_track_plan_modules_immutable
BEFORE UPDATE OR DELETE ON tutor_track_plan_modules
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_structure_immutable();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_nodes_immutable ON tutor_track_plan_nodes;
CREATE TRIGGER trg_tutor_track_plan_nodes_immutable
BEFORE UPDATE OR DELETE ON tutor_track_plan_nodes
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_structure_immutable();

DROP TRIGGER IF EXISTS trg_tutor_track_node_progress_updated_at ON tutor_track_node_progress;
CREATE TRIGGER trg_tutor_track_node_progress_updated_at BEFORE UPDATE ON tutor_track_node_progress
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_track_plan_migrations_lifecycle ON tutor_track_plan_migrations;
CREATE TRIGGER trg_tutor_track_plan_migrations_lifecycle
BEFORE INSERT OR UPDATE OR DELETE ON tutor_track_plan_migrations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_track_plan_migration_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_mastery_evidence_immutable ON tutor_mastery_evidence;
CREATE TRIGGER trg_tutor_mastery_evidence_immutable
BEFORE UPDATE OR DELETE ON tutor_mastery_evidence
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_mastery_evidence_immutable();

DROP TRIGGER IF EXISTS trg_tutor_mastery_states_updated_at ON tutor_mastery_states;
CREATE TRIGGER trg_tutor_mastery_states_updated_at BEFORE UPDATE ON tutor_mastery_states
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_conversation_learning_scopes_updated_at ON tutor_conversation_learning_scopes;
CREATE TRIGGER trg_tutor_conversation_learning_scopes_updated_at BEFORE UPDATE ON tutor_conversation_learning_scopes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_run_learning_scopes_immutable ON tutor_run_learning_scopes;
CREATE TRIGGER trg_tutor_run_learning_scopes_immutable
BEFORE UPDATE OR DELETE ON tutor_run_learning_scopes
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_learning_scope_immutable();
