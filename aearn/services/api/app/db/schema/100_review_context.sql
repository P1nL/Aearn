-- Track-scoped spaced review and finite ReviewSession authority.
-- This is additive and does not reopen the retired review_states/review_logs runtime.
CREATE TABLE IF NOT EXISTS tutor_review_schedule_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_plan_revision_id uuid NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
  card_state text NOT NULL CHECK (card_state IN ('new', 'learning', 'review', 'relearning', 'suspended')),
  stability double precision NOT NULL CHECK (stability >= 0.1 AND stability <= 3650),
  difficulty double precision NOT NULL CHECK (difficulty BETWEEN 1 AND 10),
  due_at timestamptz NOT NULL,
  last_review_at timestamptz,
  review_count integer NOT NULL DEFAULT 0 CHECK (review_count >= 0),
  lapse_count integer NOT NULL DEFAULT 0 CHECK (lapse_count >= 0),
  last_rating text CHECK (last_rating IS NULL OR last_rating IN ('again', 'hard', 'good', 'easy')),
  risk_level text NOT NULL DEFAULT 'normal' CHECK (risk_level IN ('low', 'normal', 'high', 'critical')),
  scheduler_version text NOT NULL CHECK (scheduler_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_schedule_track_key UNIQUE (track_id, knowledge_key),
  CONSTRAINT uq_tutor_review_schedule_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_review_schedule_progress
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_schedule_revision
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_review_schedule_suspend_shape CHECK (
    (status = 'suspended') = (card_state = 'suspended')
  )
);

CREATE TABLE IF NOT EXISTS tutor_review_schedule_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  schedule_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  source_kind text NOT NULL CHECK (source_kind IN ('mastery_seed', 'diagnostic_skip', 'session_finalization', 'plan_migration')),
  source_receipt_id text NOT NULL CHECK (char_length(source_receipt_id) BETWEEN 1 AND 160),
  reason_codes_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reason_codes_json) = 'array'),
  previous_state_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(previous_state_json) = 'object'),
  next_state_json jsonb NOT NULL CHECK (jsonb_typeof(next_state_json) = 'object'),
  event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  scheduler_version text NOT NULL CHECK (scheduler_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_schedule_event_source UNIQUE (schedule_id, source_kind, source_receipt_id),
  CONSTRAINT uq_tutor_review_schedule_event_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_review_schedule_event_scope
    FOREIGN KEY (schedule_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_review_schedule_states(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_review_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  plan_revision_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_schedule_version integer NOT NULL CHECK (expected_schedule_version >= 1),
  state text NOT NULL CHECK (state IN ('blocked', 'active', 'ready_to_finalize', 'finalized', 'cancelled')),
  stage text NOT NULL CHECK (stage IN ('warmup', 'practice', 'final_summary')),
  failure_code text CHECK (failure_code IS NULL OR failure_code ~ '^[A-Z][A-Z0-9_]{0,79}$'),
  context_snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(context_snapshot_json) = 'object'),
  context_snapshot_hash text NOT NULL CHECK (context_snapshot_hash ~ '^[0-9a-f]{64}$'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  started_at timestamptz NOT NULL,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_sessions_id_scope UNIQUE (id, user_id, track_id),
  CONSTRAINT uq_tutor_review_sessions_idempotency UNIQUE (user_id, track_id, idempotency_key),
  CONSTRAINT fk_tutor_review_session_track
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_session_revision
    FOREIGN KEY (plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_session_progress
    FOREIGN KEY (track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_review_session_terminal CHECK (
    (state IN ('finalized', 'cancelled')) = (terminal_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_review_session_failure CHECK (
    (state = 'blocked') = (failure_code IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_review_session_stage CHECK (
    (state = 'finalized') = (stage = 'final_summary')
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_review_sessions_one_active
  ON tutor_review_sessions(user_id, track_id)
  WHERE state IN ('blocked', 'active', 'ready_to_finalize');

CREATE TABLE IF NOT EXISTS tutor_review_warmup_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  response_kind text NOT NULL CHECK (response_kind IN ('answered', 'skipped')),
  response_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(response_summary_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_warmup_session UNIQUE (session_id),
  CONSTRAINT uq_tutor_review_warmup_idempotency UNIQUE (user_id, session_id, idempotency_key),
  CONSTRAINT fk_tutor_review_warmup_session
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_review_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  plan_revision_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  order_index integer NOT NULL CHECK (order_index >= 0),
  selection_reason_json jsonb NOT NULL CHECK (jsonb_typeof(selection_reason_json) = 'object'),
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  version integer NOT NULL DEFAULT 1 CHECK (version = 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_items_session_order UNIQUE (session_id, order_index),
  CONSTRAINT uq_tutor_review_items_session_exercise UNIQUE (session_id, exercise_version_id),
  CONSTRAINT uq_tutor_review_items_scope UNIQUE (
    id, session_id, user_id, track_id, knowledge_key, exercise_version_id
  ),
  CONSTRAINT fk_tutor_review_item_session
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_item_node
    FOREIGN KEY (plan_revision_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_review_hint_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  item_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  exercise_version_id uuid NOT NULL,
  hint_level integer NOT NULL CHECK (hint_level BETWEEN 1 AND 3),
  hint_policy_version text NOT NULL CHECK (hint_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  safe_hint_json jsonb NOT NULL CHECK (jsonb_typeof(safe_hint_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_hint_idempotency UNIQUE (user_id, item_id, idempotency_key),
  CONSTRAINT fk_tutor_review_hint_item
    FOREIGN KEY (item_id, session_id, user_id, track_id, knowledge_key, exercise_version_id)
    REFERENCES tutor_review_items(id, session_id, user_id, track_id, knowledge_key, exercise_version_id)
    ON DELETE RESTRICT
);

ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS review_session_id uuid;
ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS review_item_id uuid;
ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS expected_review_session_version integer;
ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS expected_review_item_version integer;
-- Declared here so repeat bootstrap can preserve later Learning Item-owned Run rows
-- before fragment 200 reasserts the complete SQL workspace constraints.
ALTER TABLE tutor_exercise_attempts ADD COLUMN IF NOT EXISTS learning_item_version_id uuid;

ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS tutor_exercise_attempts_attempt_type_check;
ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS chk_tutor_exercise_attempts_type;
ALTER TABLE tutor_exercise_attempts ADD CONSTRAINT chk_tutor_exercise_attempts_type CHECK (
  attempt_type IN ('run', 'submit', 'diagnostic_submit', 'review_submit')
);
ALTER TABLE tutor_exercise_attempts DROP CONSTRAINT IF EXISTS chk_tutor_exercise_attempts_owner_shape;
ALTER TABLE tutor_exercise_attempts ADD CONSTRAINT chk_tutor_exercise_attempts_owner_shape CHECK (
  (
    attempt_type IN ('run', 'submit')
    AND lesson_assignment_id IS NOT NULL AND document_id IS NOT NULL AND gate_binding_id IS NOT NULL
    AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
    AND review_session_id IS NULL AND review_item_id IS NULL
    AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
    AND expected_progress_version IS NOT NULL
    AND learning_item_version_id IS NULL
  )
  OR (
    attempt_type = 'diagnostic_submit'
    AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
    AND diagnostic_session_id IS NOT NULL AND diagnostic_item_id IS NOT NULL
    AND review_session_id IS NULL AND review_item_id IS NULL
    AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
    AND expected_progress_version IS NULL
    AND learning_item_version_id IS NULL
  )
  OR (
    attempt_type = 'review_submit'
    AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
    AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
    AND review_session_id IS NOT NULL AND review_item_id IS NOT NULL
    AND expected_review_session_version IS NOT NULL AND expected_review_session_version >= 1
    AND expected_review_item_version IS NOT NULL AND expected_review_item_version = 1
    AND expected_progress_version IS NULL
    AND learning_item_version_id IS NULL
  )
  OR (
    attempt_type = 'run'
    AND lesson_assignment_id IS NOT NULL AND document_id IS NOT NULL AND gate_binding_id IS NULL
    AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
    AND review_session_id IS NULL AND review_item_id IS NULL
    AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
    AND expected_progress_version IS NOT NULL
    AND learning_item_version_id IS NOT NULL
  )
);
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_exercise_attempts'::regclass
      AND conname = 'fk_tutor_exercise_attempt_review_item_scope'
  ) THEN
    ALTER TABLE tutor_exercise_attempts
      ADD CONSTRAINT fk_tutor_exercise_attempt_review_item_scope
      FOREIGN KEY (
        review_item_id, review_session_id, user_id, track_id, knowledge_key, exercise_version_id
      ) REFERENCES tutor_review_items(
        id, session_id, user_id, track_id, knowledge_key, exercise_version_id
      ) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_tutor_exercise_attempts_review
  ON tutor_exercise_attempts(review_session_id, review_item_id, accepted_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_exercise_attempts_review_item
  ON tutor_exercise_attempts(review_item_id) WHERE attempt_type = 'review_submit';

CREATE TABLE IF NOT EXISTS tutor_review_finalizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL,
  mastery_evidence_id uuid NOT NULL,
  schedule_event_id uuid NOT NULL,
  rating text NOT NULL CHECK (rating IN ('again', 'hard', 'good', 'easy')),
  aggregate_json jsonb NOT NULL CHECK (jsonb_typeof(aggregate_json) = 'object'),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_review_finalization_session UNIQUE (session_id),
  CONSTRAINT uq_tutor_review_finalization_idempotency UNIQUE (user_id, session_id, idempotency_key),
  CONSTRAINT fk_tutor_review_finalization_session
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_finalization_mastery
    FOREIGN KEY (mastery_evidence_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_mastery_evidence(id, track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_review_finalization_schedule_event
    FOREIGN KEY (schedule_event_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_review_schedule_events(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT
);

-- Upgrade databases that bootstrapped an earlier draft of the ReviewSession schema.
ALTER TABLE tutor_review_sessions DROP CONSTRAINT IF EXISTS chk_tutor_review_session_terminal;
ALTER TABLE tutor_review_sessions ADD CONSTRAINT chk_tutor_review_session_terminal CHECK (
  (state IN ('finalized', 'cancelled')) = (terminal_at IS NOT NULL)
);
DROP INDEX IF EXISTS uq_tutor_review_sessions_one_active;
CREATE UNIQUE INDEX uq_tutor_review_sessions_one_active
  ON tutor_review_sessions(user_id, track_id)
  WHERE state IN ('blocked', 'active', 'ready_to_finalize');
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_review_schedule_events'::regclass
      AND conname = 'uq_tutor_review_schedule_event_scope'
  ) THEN
    ALTER TABLE tutor_review_schedule_events
      ADD CONSTRAINT uq_tutor_review_schedule_event_scope
      UNIQUE (id, user_id, track_id, knowledge_key);
  END IF;
END $$;
ALTER TABLE tutor_review_finalizations
  DROP CONSTRAINT IF EXISTS tutor_review_finalizations_schedule_event_id_fkey;
ALTER TABLE tutor_review_finalizations
  DROP CONSTRAINT IF EXISTS fk_tutor_review_finalization_schedule_event;
ALTER TABLE tutor_review_finalizations
  ADD CONSTRAINT fk_tutor_review_finalization_schedule_event
  FOREIGN KEY (schedule_event_id, user_id, track_id, knowledge_key)
  REFERENCES tutor_review_schedule_events(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION enforce_tutor_review_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Review receipts and items are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_review_schedule_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Review schedule cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Review schedule identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.version <> OLD.version + 1 THEN
    RAISE EXCEPTION 'Review schedule version must advance exactly once' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_review_session_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Review session cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.plan_revision_id IS DISTINCT FROM OLD.plan_revision_id
     OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.expected_track_version IS DISTINCT FROM OLD.expected_track_version
     OR NEW.expected_schedule_version IS DISTINCT FROM OLD.expected_schedule_version
     OR NEW.context_snapshot_json IS DISTINCT FROM OLD.context_snapshot_json
     OR NEW.context_snapshot_hash IS DISTINCT FROM OLD.context_snapshot_hash
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
     OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Review session identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('finalized', 'cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal review session is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.version <> OLD.version + 1 THEN
    RAISE EXCEPTION 'Review session version must advance exactly once' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'blocked' AND NEW.state IN ('blocked', 'active', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'active' AND NEW.state IN ('active', 'ready_to_finalize', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'ready_to_finalize' AND NEW.state IN ('active', 'ready_to_finalize', 'finalized', 'cancelled') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Review session transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_review_schedule_states_updated_at ON tutor_review_schedule_states;
CREATE TRIGGER trg_tutor_review_schedule_states_updated_at
BEFORE UPDATE ON tutor_review_schedule_states FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_review_schedule_states_lifecycle ON tutor_review_schedule_states;
CREATE TRIGGER trg_tutor_review_schedule_states_lifecycle
BEFORE UPDATE OR DELETE ON tutor_review_schedule_states
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_schedule_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_review_sessions_updated_at ON tutor_review_sessions;
CREATE TRIGGER trg_tutor_review_sessions_updated_at
BEFORE UPDATE ON tutor_review_sessions FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_review_sessions_lifecycle ON tutor_review_sessions;
CREATE TRIGGER trg_tutor_review_sessions_lifecycle
BEFORE UPDATE OR DELETE ON tutor_review_sessions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_session_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_review_schedule_events_immutable ON tutor_review_schedule_events;
CREATE TRIGGER trg_tutor_review_schedule_events_immutable
BEFORE UPDATE OR DELETE ON tutor_review_schedule_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_warmups_immutable ON tutor_review_warmup_receipts;
CREATE TRIGGER trg_tutor_review_warmups_immutable
BEFORE UPDATE OR DELETE ON tutor_review_warmup_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_items_immutable ON tutor_review_items;
CREATE TRIGGER trg_tutor_review_items_immutable
BEFORE UPDATE OR DELETE ON tutor_review_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_hints_immutable ON tutor_review_hint_receipts;
CREATE TRIGGER trg_tutor_review_hints_immutable
BEFORE UPDATE OR DELETE ON tutor_review_hint_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();
DROP TRIGGER IF EXISTS trg_tutor_review_finalizations_immutable ON tutor_review_finalizations;
CREATE TRIGGER trg_tutor_review_finalizations_immutable
BEFORE UPDATE OR DELETE ON tutor_review_finalizations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_review_append_only();

CREATE INDEX IF NOT EXISTS idx_tutor_review_schedule_due
  ON tutor_review_schedule_states(user_id, track_id, status, due_at, knowledge_key);
CREATE INDEX IF NOT EXISTS idx_tutor_review_schedule_events_created
  ON tutor_review_schedule_events(schedule_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tutor_review_sessions_scope
  ON tutor_review_sessions(user_id, track_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_review_items_session
  ON tutor_review_items(session_id, order_index);
CREATE INDEX IF NOT EXISTS idx_tutor_review_hints_item
  ON tutor_review_hint_receipts(item_id, created_at, id);

-- Child 08-04 workspace context references: immutable learner-safe snapshots
-- bound to one accepted learner message and exact TurnRun input revision.
CREATE TABLE IF NOT EXISTS tutor_message_context_references (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  run_id uuid NOT NULL,
  message_id uuid NOT NULL,
  input_revision integer NOT NULL CHECK (input_revision > 0),
  reference_index integer NOT NULL CHECK (reference_index BETWEEN 0 AND 5),
  reference_kind text NOT NULL CHECK (reference_kind IN (
    'lesson_selection', 'exercise_feedback', 'execution_result', 'review_feedback',
    'teaching_session_message'
  )),
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  document_id uuid,
  attempt_id uuid,
  review_session_id uuid,
  exercise_version_id uuid,
  source_version text NOT NULL CHECK (char_length(source_version) BETWEEN 1 AND 160),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  safe_payload_json jsonb NOT NULL CHECK (jsonb_typeof(safe_payload_json) = 'object'),
  safe_payload_hash text NOT NULL CHECK (safe_payload_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_message_context_references_input_index
    UNIQUE (run_id, input_revision, reference_index),
  CONSTRAINT uq_tutor_message_context_references_message_index
    UNIQUE (message_id, reference_index),
  CONSTRAINT uq_tutor_message_context_references_id_user UNIQUE (id, user_id),
  CONSTRAINT fk_tutor_context_reference_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_message_conversation
    FOREIGN KEY (message_id, conversation_id) REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_input_revision
    FOREIGN KEY (run_id, input_revision) REFERENCES tutor_run_input_events(run_id, input_revision) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_document_scope
    FOREIGN KEY (document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_documents(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_attempt_scope
    FOREIGN KEY (attempt_id, user_id, track_id, exercise_version_id)
    REFERENCES tutor_exercise_attempts(id, user_id, track_id, exercise_version_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_context_reference_review_scope
    FOREIGN KEY (review_session_id, user_id, track_id)
    REFERENCES tutor_review_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_message_context_reference_shape CHECK (
    (reference_kind = 'lesson_selection'
      AND document_id IS NOT NULL AND attempt_id IS NULL
      AND review_session_id IS NULL AND exercise_version_id IS NULL)
    OR
    (reference_kind IN ('exercise_feedback', 'execution_result')
      AND document_id IS NULL AND attempt_id IS NOT NULL
      AND review_session_id IS NULL AND exercise_version_id IS NOT NULL)
    OR
    (reference_kind = 'review_feedback'
      AND document_id IS NULL AND attempt_id IS NOT NULL
      AND review_session_id IS NOT NULL AND exercise_version_id IS NOT NULL)
    OR
    (reference_kind = 'teaching_session_message'
      AND document_id IS NULL AND attempt_id IS NULL
      AND review_session_id IS NULL AND exercise_version_id IS NULL)
  )
);

ALTER TABLE tutor_message_context_references
  DROP CONSTRAINT IF EXISTS tutor_message_context_references_reference_kind_check;
ALTER TABLE tutor_message_context_references
  DROP CONSTRAINT IF EXISTS chk_tutor_message_context_reference_kind;
ALTER TABLE tutor_message_context_references
  ADD CONSTRAINT chk_tutor_message_context_reference_kind CHECK (reference_kind IN (
    'lesson_selection', 'exercise_feedback', 'execution_result', 'review_feedback',
    'teaching_session_message'
  ));
ALTER TABLE tutor_message_context_references
  DROP CONSTRAINT IF EXISTS chk_tutor_message_context_reference_shape;
ALTER TABLE tutor_message_context_references
  ADD CONSTRAINT chk_tutor_message_context_reference_shape CHECK (
    (reference_kind = 'lesson_selection'
      AND document_id IS NOT NULL AND attempt_id IS NULL
      AND review_session_id IS NULL AND exercise_version_id IS NULL)
    OR
    (reference_kind IN ('exercise_feedback', 'execution_result')
      AND document_id IS NULL AND attempt_id IS NOT NULL
      AND review_session_id IS NULL AND exercise_version_id IS NOT NULL)
    OR
    (reference_kind = 'review_feedback'
      AND document_id IS NULL AND attempt_id IS NOT NULL
      AND review_session_id IS NOT NULL AND exercise_version_id IS NOT NULL)
    OR
    (reference_kind = 'teaching_session_message'
      AND document_id IS NULL AND attempt_id IS NULL
      AND review_session_id IS NULL AND exercise_version_id IS NULL)
  );

CREATE OR REPLACE FUNCTION enforce_tutor_message_context_reference_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Tutor message context references are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_message_context_references_immutable
  ON tutor_message_context_references;
CREATE TRIGGER trg_tutor_message_context_references_immutable
BEFORE UPDATE OR DELETE ON tutor_message_context_references
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_message_context_reference_immutable();

CREATE INDEX IF NOT EXISTS idx_tutor_message_context_references_message
  ON tutor_message_context_references(user_id, conversation_id, message_id, reference_index);
CREATE INDEX IF NOT EXISTS idx_tutor_message_context_references_input
  ON tutor_message_context_references(user_id, run_id, input_revision, reference_index);
