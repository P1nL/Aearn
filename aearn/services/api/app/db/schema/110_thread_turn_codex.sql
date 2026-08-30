-- Child 08-13 Tutor Thread/Turn v2 foundation: versioned public event and durable dispatch authority.
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS next_public_event_sequence bigint NOT NULL DEFAULT 1;
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS control_version bigint NOT NULL DEFAULT 1;
ALTER TABLE tutor_conversations
  DROP CONSTRAINT IF EXISTS chk_tutor_conversations_next_public_event_sequence;
ALTER TABLE tutor_conversations
  ADD CONSTRAINT chk_tutor_conversations_next_public_event_sequence
  CHECK (next_public_event_sequence >= 1);
ALTER TABLE tutor_conversations
  DROP CONSTRAINT IF EXISTS chk_tutor_conversations_control_version;
ALTER TABLE tutor_conversations
  ADD CONSTRAINT chk_tutor_conversations_control_version
  CHECK (control_version >= 1);

ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS interaction_protocol_version text;
UPDATE tutor_runs
SET interaction_protocol_version = 'legacy_v1'
WHERE interaction_protocol_version IS NULL;
ALTER TABLE tutor_runs
  ALTER COLUMN interaction_protocol_version SET NOT NULL;
ALTER TABLE tutor_runs
  ALTER COLUMN interaction_protocol_version SET DEFAULT 'thread_turn_v2';
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS retry_of_turn_id uuid;
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS retry_root_turn_id uuid;
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_interaction_protocol_version;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_interaction_protocol_version
  CHECK (interaction_protocol_version IN ('legacy_v1', 'thread_turn_v2'));
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_retry_lineage_distinct;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_retry_lineage_distinct
  CHECK (
    (retry_of_turn_id IS NULL OR retry_of_turn_id <> id)
    AND (retry_root_turn_id IS NULL OR retry_root_turn_id <> id)
  );

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'uq_tutor_runs_id_user_conversation'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT uq_tutor_runs_id_user_conversation UNIQUE (id, user_id, conversation_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'fk_tutor_runs_retry_of_turn_scope'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT fk_tutor_runs_retry_of_turn_scope
      FOREIGN KEY (retry_of_turn_id, user_id, conversation_id)
      REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'fk_tutor_runs_retry_root_turn_scope'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT fk_tutor_runs_retry_root_turn_scope
      FOREIGN KEY (retry_root_turn_id, user_id, conversation_id)
      REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT;
  END IF;
END $$;

ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS tutor_run_public_processes_display_state_check;
ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_display_state;
ALTER TABLE tutor_run_public_processes
  ADD CONSTRAINT chk_tutor_public_process_display_state
  CHECK (display_state IN (
    'thinking', 'waiting_input', 'waiting_approval', 'waiting_authority',
    'completed', 'interrupted', 'superseded', 'unavailable', 'failed'
  ));
ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_finished_state;
ALTER TABLE tutor_run_public_processes
  ADD CONSTRAINT chk_tutor_public_process_finished_state CHECK (
    (display_state IN ('thinking', 'waiting_input', 'waiting_approval', 'waiting_authority') AND finished_at IS NULL)
    OR
    (display_state IN ('completed', 'interrupted', 'superseded', 'unavailable', 'failed') AND finished_at IS NOT NULL)
  );

CREATE TABLE IF NOT EXISTS tutor_conversation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  event_sequence bigint NOT NULL CHECK (event_sequence > 0),
  event_key text NOT NULL CHECK (char_length(event_key) BETWEEN 1 AND 160),
  kind text NOT NULL CHECK (kind IN (
    'turn_created', 'turn_updated', 'item_added', 'item_updated', 'turn_output',
    'control_updated', 'dispatch_delayed', 'dispatch_dead'
  )),
  turn_id uuid,
  item_id uuid,
  item_kind text CHECK (item_kind IS NULL OR item_kind IN (
    'message', 'process', 'elicitation', 'approval', 'error'
  )),
  projection_version text NOT NULL DEFAULT 'tutor_conversation_event_v2'
    CHECK (projection_version IN ('tutor_conversation_event_v1', 'tutor_conversation_event_v2')),
  payload_json jsonb NOT NULL CHECK (jsonb_typeof(payload_json) = 'object'),
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversation_events_sequence UNIQUE (conversation_id, event_sequence),
  CONSTRAINT uq_tutor_conversation_events_key UNIQUE (conversation_id, event_key),
  CONSTRAINT uq_tutor_conversation_events_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_conversation_event_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_conversation_event_turn_scope
    FOREIGN KEY (turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_conversation_event_item_shape CHECK (
    (item_id IS NULL AND item_kind IS NULL)
    OR (item_id IS NOT NULL AND item_kind IS NOT NULL)
  )
);

ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS tutor_conversation_events_kind_check;
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_events_kind;
ALTER TABLE tutor_conversation_events
  ADD CONSTRAINT chk_tutor_conversation_events_kind CHECK (kind IN (
    'turn_created', 'turn_updated', 'item_added', 'item_updated', 'turn_output',
    'control_updated', 'dispatch_delayed', 'dispatch_dead'
  ));
ALTER TABLE tutor_conversation_events
  ALTER COLUMN projection_version SET DEFAULT 'tutor_conversation_event_v2';
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS tutor_conversation_events_projection_version_check;
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_events_projection_version;
ALTER TABLE tutor_conversation_events
  ADD CONSTRAINT chk_tutor_conversation_events_projection_version CHECK (
    projection_version IN ('tutor_conversation_event_v1', 'tutor_conversation_event_v2')
  );

CREATE TABLE IF NOT EXISTS tutor_turn_public_thinking_streams (
  run_id uuid PRIMARY KEY REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  decision_iteration integer NOT NULL CHECK (decision_iteration >= 1),
  generation bigint NOT NULL CHECK (generation >= 1),
  provider_attempt integer NOT NULL CHECK (provider_attempt >= 1),
  state text NOT NULL CHECK (state IN ('active', 'complete', 'discarded', 'accepted')),
  thinking_text text NOT NULL DEFAULT '' CHECK (char_length(thinking_text) <= 1280),
  next_chunk_sequence bigint NOT NULL DEFAULT 1 CHECK (next_chunk_sequence >= 1),
  last_public_event_sequence bigint,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  discarded_at timestamptz,
  accepted_at timestamptz,
  CONSTRAINT uq_tutor_turn_public_thinking_streams_scope UNIQUE (run_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_turn_public_thinking_stream_run_scope
    FOREIGN KEY (run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_turn_public_thinking_stream_event
    FOREIGN KEY (conversation_id, last_public_event_sequence)
    REFERENCES tutor_conversation_events(conversation_id, event_sequence) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_turn_public_thinking_stream_timestamps CHECK (
    (state = 'active' AND completed_at IS NULL AND discarded_at IS NULL AND accepted_at IS NULL)
    OR (state = 'complete' AND completed_at IS NOT NULL AND discarded_at IS NULL AND accepted_at IS NULL)
    OR (state = 'discarded' AND discarded_at IS NOT NULL AND accepted_at IS NULL)
    OR (state = 'accepted' AND completed_at IS NOT NULL AND accepted_at IS NOT NULL AND discarded_at IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_interactive_dispatch_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL UNIQUE REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  state text NOT NULL DEFAULT 'pending' CHECK (state IN (
    'pending', 'leased', 'retry_wait', 'completed', 'dead'
  )),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts integer NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_owner_id text,
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_expires_at timestamptz,
  last_error_code text CHECK (
    last_error_code IS NULL OR char_length(last_error_code) BETWEEN 1 AND 120
  ),
  completed_at timestamptz,
  dead_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_interactive_dispatch_jobs_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_interactive_dispatch_job_run_scope
    FOREIGN KEY (run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_interactive_dispatch_job_lease CHECK (
    (state = 'leased' AND lease_owner_id IS NOT NULL AND lease_expires_at IS NOT NULL)
    OR (state <> 'leased' AND lease_owner_id IS NULL AND lease_expires_at IS NULL)
  ),
  CONSTRAINT chk_tutor_interactive_dispatch_job_terminal CHECK (
    (state = 'completed' AND completed_at IS NOT NULL AND dead_at IS NULL)
    OR (state = 'dead' AND dead_at IS NOT NULL AND completed_at IS NULL)
    OR (state NOT IN ('completed', 'dead') AND completed_at IS NULL AND dead_at IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_conversation_events_replay
  ON tutor_conversation_events(conversation_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_tutor_conversation_events_turn
  ON tutor_conversation_events(turn_id, event_sequence) WHERE turn_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_public_thinking_streams_conversation_state
  ON tutor_turn_public_thinking_streams(conversation_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_interactive_dispatch_jobs_claim
  ON tutor_interactive_dispatch_jobs(available_at, created_at, id)
  WHERE state IN ('pending', 'retry_wait', 'leased');
CREATE INDEX IF NOT EXISTS idx_tutor_interactive_dispatch_jobs_user_state
  ON tutor_interactive_dispatch_jobs(user_id, state, updated_at);

CREATE OR REPLACE FUNCTION enforce_tutor_conversation_event_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND current_setting('aearn.learning_track_purge_user_id', true) = OLD.user_id::text THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor conversation events are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_conversation_events_immutable ON tutor_conversation_events;
CREATE TRIGGER trg_tutor_conversation_events_immutable
BEFORE UPDATE OR DELETE ON tutor_conversation_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_conversation_event_append_only();

DROP TRIGGER IF EXISTS trg_tutor_public_thinking_streams_updated_at ON tutor_turn_public_thinking_streams;
CREATE TRIGGER trg_tutor_public_thinking_streams_updated_at
BEFORE UPDATE ON tutor_turn_public_thinking_streams
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_interactive_dispatch_jobs_updated_at ON tutor_interactive_dispatch_jobs;
CREATE TRIGGER trg_tutor_interactive_dispatch_jobs_updated_at
BEFORE UPDATE ON tutor_interactive_dispatch_jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Child 08-14 Tutor typed interaction requests and fresh authority turns.
CREATE TABLE IF NOT EXISTS tutor_interaction_requests (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  source_turn_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN (
    'clarification', 'planning_input', 'approval', 'capability_result', 'external_result'
  )),
  actor text NOT NULL CHECK (actor IN ('learner', 'authority')),
  schema_version text NOT NULL DEFAULT 'tutor_interaction_request_v1'
    CHECK (schema_version = 'tutor_interaction_request_v1'),
  catalog_version text,
  question_key text,
  descriptor_json jsonb NOT NULL CHECK (jsonb_typeof(descriptor_json) = 'object'),
  presentation_json jsonb NOT NULL CHECK (jsonb_typeof(presentation_json) = 'object'),
  descriptor_hash text NOT NULL CHECK (descriptor_hash ~ '^[0-9a-f]{64}$'),
  proposal_identity text,
  authority_key text,
  risk_level text CHECK (risk_level IS NULL OR risk_level IN ('low', 'medium', 'high')),
  authority_issuer text,
  authority_subject text,
  authority_scope_json jsonb,
  authority_request_hash text CHECK (authority_request_hash IS NULL OR authority_request_hash ~ '^[0-9a-f]{64}$'),
  authority_result_hash text CHECK (authority_result_hash IS NULL OR authority_result_hash ~ '^[0-9a-f]{64}$'),
  authority_verification_result text CHECK (
    authority_verification_result IS NULL OR authority_verification_result IN ('verified', 'ambiguous', 'rejected')
  ),
  receipt_identity text,
  receipt_hash text CHECK (receipt_hash IS NULL OR receipt_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN (
    'pending', 'answered', 'denied', 'cancelled', 'expired'
  )),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  response_hash text CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
  answer_turn_id uuid,
  answer_message_id uuid,
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_interaction_requests_item UNIQUE (item_id),
  CONSTRAINT uq_tutor_interaction_requests_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT uq_tutor_interaction_requests_item_scope UNIQUE (item_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_interaction_request_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_interaction_request_source_turn_scope
    FOREIGN KEY (source_turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE CASCADE,
  CONSTRAINT fk_tutor_interaction_request_answer_turn_scope
    FOREIGN KEY (answer_turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE SET NULL (answer_turn_id),
  CONSTRAINT fk_tutor_interaction_request_answer_message_scope
    FOREIGN KEY (answer_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE SET NULL (answer_message_id),
  CONSTRAINT chk_tutor_interaction_request_actor_kind CHECK (
    (actor = 'learner' AND kind IN ('clarification', 'planning_input', 'approval'))
    OR (actor = 'authority' AND kind IN ('capability_result', 'external_result'))
  ),
  CONSTRAINT chk_tutor_interaction_request_planning_shape CHECK (
    (kind = 'planning_input' AND question_key IN (
      'language_id', 'goal_text', 'target_level', 'weekly_minutes',
      'experience_level', 'teaching_preferences', 'pace_constraints'
    ) AND catalog_version = 'tutor_planning_questions_v1')
    OR (kind <> 'planning_input' AND question_key IS NULL AND catalog_version IS NULL)
  ),
  CONSTRAINT chk_tutor_interaction_request_approval_shape CHECK (
    (kind = 'approval' AND proposal_identity IS NOT NULL AND authority_key IS NOT NULL AND risk_level IS NOT NULL)
    OR (kind <> 'approval' AND proposal_identity IS NULL AND risk_level IS NULL)
  ),
  CONSTRAINT chk_tutor_interaction_request_authority_shape CHECK (
    (actor = 'authority' AND authority_request_hash IS NOT NULL)
    OR (actor = 'learner' AND authority_issuer IS NULL AND authority_subject IS NULL
      AND authority_scope_json IS NULL AND authority_result_hash IS NULL
      AND authority_verification_result IS NULL AND receipt_identity IS NULL AND receipt_hash IS NULL)
  ),
  CONSTRAINT chk_tutor_interaction_request_resolution CHECK (
    (state = 'pending' AND response_hash IS NULL AND receipt_hash IS NULL
      AND answer_turn_id IS NULL AND answer_message_id IS NULL AND resolved_at IS NULL)
    OR (state <> 'pending' AND resolved_at IS NOT NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_interaction_requests_pending_conversation
  ON tutor_interaction_requests(conversation_id)
  WHERE state = 'pending';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_interaction_requests_receipt_identity
  ON tutor_interaction_requests(user_id, receipt_identity)
  WHERE receipt_identity IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_interaction_requests_conversation_history
  ON tutor_interaction_requests(conversation_id, created_at DESC, item_id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_interaction_requests_source_turn
  ON tutor_interaction_requests(source_turn_id);

ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS response_to_request_id uuid;
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS completion_reason text;
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_completion_reason;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_completion_reason CHECK (
    completion_reason IS NULL OR completion_reason IN (
      'awaiting_user', 'awaiting_approval', 'awaiting_authority'
    )
  );
ALTER TABLE tutor_interaction_requests
  DROP CONSTRAINT IF EXISTS fk_tutor_interaction_request_answer_turn_scope;
ALTER TABLE tutor_interaction_requests
  ADD CONSTRAINT fk_tutor_interaction_request_answer_turn_scope
  FOREIGN KEY (answer_turn_id, user_id, conversation_id)
  REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE SET NULL (answer_turn_id);
ALTER TABLE tutor_interaction_requests
  DROP CONSTRAINT IF EXISTS fk_tutor_interaction_request_answer_message_scope;
ALTER TABLE tutor_interaction_requests
  ADD CONSTRAINT fk_tutor_interaction_request_answer_message_scope
  FOREIGN KEY (answer_message_id, conversation_id)
  REFERENCES tutor_messages(id, conversation_id) ON DELETE SET NULL (answer_message_id);
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS fk_tutor_runs_response_request_scope;
ALTER TABLE tutor_runs
  ADD CONSTRAINT fk_tutor_runs_response_request_scope
  FOREIGN KEY (response_to_request_id, user_id, conversation_id)
  REFERENCES tutor_interaction_requests(id, user_id, conversation_id)
  ON DELETE SET NULL (response_to_request_id);
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_request_lineage_shape;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_request_lineage_shape CHECK (
    (response_to_request_id IS NULL OR interaction_protocol_version = 'thread_turn_v2')
    AND (completion_reason IS NULL OR terminal_outcome = 'completed')
  );

DROP TRIGGER IF EXISTS trg_tutor_interaction_requests_updated_at ON tutor_interaction_requests;
CREATE TRIGGER trg_tutor_interaction_requests_updated_at
BEFORE UPDATE ON tutor_interaction_requests
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_interaction_requests_source_turn
  ON tutor_interaction_requests(source_turn_id);

-- Child 08-13 Tutor Queue, Steer, Interrupt, Resume, Execute, and Retry control.
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS queue_paused boolean NOT NULL DEFAULT false;
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS queue_pause_reason text;
ALTER TABLE tutor_conversations
  DROP CONSTRAINT IF EXISTS chk_tutor_conversations_queue_pause;
ALTER TABLE tutor_conversations
  ADD CONSTRAINT chk_tutor_conversations_queue_pause CHECK (
    (queue_paused = false AND queue_pause_reason IS NULL)
    OR (queue_paused = true AND queue_pause_reason IN ('pending_request', 'interrupted', 'failed'))
  );

CREATE TABLE IF NOT EXISTS tutor_queued_inputs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  content text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 16000),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'claimed', 'cancelled')),
  position integer NOT NULL CHECK (position >= 1),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  enqueue_key text NOT NULL CHECK (char_length(enqueue_key) BETWEEN 1 AND 160),
  claimed_turn_id uuid,
  claimed_input_revision integer CHECK (claimed_input_revision IS NULL OR claimed_input_revision >= 1),
  claimed_mode text CHECK (claimed_mode IS NULL OR claimed_mode IN ('drain', 'steer', 'execute')),
  claimed_at timestamptz,
  cancelled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_queued_inputs_id_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT uq_tutor_queued_inputs_enqueue UNIQUE (conversation_id, enqueue_key),
  CONSTRAINT fk_tutor_queued_input_conversation_user
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_queued_input_claimed_turn_scope
    FOREIGN KEY (claimed_turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_queued_input_resolution CHECK (
    (state = 'pending' AND claimed_turn_id IS NULL AND claimed_input_revision IS NULL
      AND claimed_mode IS NULL AND claimed_at IS NULL AND cancelled_at IS NULL)
    OR (state = 'claimed' AND claimed_turn_id IS NOT NULL AND claimed_input_revision IS NOT NULL
      AND claimed_mode IS NOT NULL AND claimed_at IS NOT NULL AND cancelled_at IS NULL)
    OR (state = 'cancelled' AND claimed_turn_id IS NULL AND claimed_input_revision IS NULL
      AND claimed_mode IS NULL AND claimed_at IS NULL AND cancelled_at IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_queued_inputs_pending_position
  ON tutor_queued_inputs(conversation_id, position) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS idx_tutor_queued_inputs_pending
  ON tutor_queued_inputs(conversation_id, position, created_at, id) WHERE state = 'pending';
DROP TRIGGER IF EXISTS trg_tutor_queued_inputs_updated_at ON tutor_queued_inputs;
CREATE TRIGGER trg_tutor_queued_inputs_updated_at
BEFORE UPDATE ON tutor_queued_inputs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE tutor_effects
  ADD COLUMN IF NOT EXISTS logical_action_key text;
ALTER TABLE tutor_effects
  DROP CONSTRAINT IF EXISTS chk_tutor_effects_logical_action_key;
ALTER TABLE tutor_effects
  ADD CONSTRAINT chk_tutor_effects_logical_action_key CHECK (
    logical_action_key IS NULL OR logical_action_key ~ '^[0-9a-f]{64}$'
  );
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_effects_committed_logical_action
  ON tutor_effects(logical_action_key)
  WHERE logical_action_key IS NOT NULL AND status = 'committed';
ALTER TABLE tutor_queued_inputs
  ADD COLUMN IF NOT EXISTS input_metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tutor_queued_inputs
  DROP CONSTRAINT IF EXISTS chk_tutor_queued_inputs_metadata;
ALTER TABLE tutor_queued_inputs
  ADD CONSTRAINT chk_tutor_queued_inputs_metadata CHECK (jsonb_typeof(input_metadata_json) = 'object');


-- Child 08-14 Tutor thread/turn v2 global protocol cutover authority.
CREATE TABLE IF NOT EXISTS tutor_thread_turn_cutovers (
  cutover_version text PRIMARY KEY CHECK (char_length(cutover_version) BETWEEN 1 AND 120),
  state text NOT NULL DEFAULT 'idle' CHECK (state IN ('idle','preparing','blocked','ready','enabled')),
  generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
  summary_hash text CHECK (summary_hash IS NULL OR summary_hash ~ '^[0-9a-f]{64}$'),
  counts_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts_json) = 'object'),
  block_code text CHECK (block_code IS NULL OR char_length(block_code) BETWEEN 1 AND 160),
  last_operation text CHECK (last_operation IS NULL OR last_operation IN ('prepare','enable','rollback')),
  last_idempotency_key text CHECK (last_idempotency_key IS NULL OR char_length(last_idempotency_key) BETWEEN 1 AND 160),
  last_request_hash text CHECK (last_request_hash IS NULL OR last_request_hash ~ '^[0-9a-f]{64}$'),
  prepared_at timestamptz,
  ready_at timestamptz,
  enabled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT chk_tutor_thread_turn_cutover_block CHECK ((state = 'blocked') = (block_code IS NOT NULL)),
  CONSTRAINT chk_tutor_thread_turn_cutover_ready_hash CHECK (state NOT IN ('ready','enabled') OR summary_hash IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS tutor_thread_turn_cutover_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cutover_version text NOT NULL REFERENCES tutor_thread_turn_cutovers(cutover_version) ON DELETE RESTRICT,
  generation bigint NOT NULL CHECK (generation >= 0),
  event_key text NOT NULL CHECK (char_length(event_key) BETWEEN 1 AND 160),
  kind text NOT NULL CHECK (kind IN ('preparing','preflight','enabled','rollback')),
  state text NOT NULL CHECK (state IN ('preparing','blocked','ready','enabled')),
  counts_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(counts_json) = 'object'),
  block_code text CHECK (block_code IS NULL OR char_length(block_code) BETWEEN 1 AND 160),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (cutover_version, event_key)
);

INSERT INTO tutor_thread_turn_cutovers (cutover_version)
VALUES ('tutor_thread_turn_v2_global_v1')
ON CONFLICT (cutover_version) DO NOTHING;

DROP TRIGGER IF EXISTS trg_tutor_thread_turn_cutovers_updated_at ON tutor_thread_turn_cutovers;
CREATE TRIGGER trg_tutor_thread_turn_cutovers_updated_at
BEFORE UPDATE ON tutor_thread_turn_cutovers FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_thread_turn_cutover_event_append_only()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Tutor thread/turn cutover events are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_thread_turn_cutover_events_immutable ON tutor_thread_turn_cutover_events;
CREATE TRIGGER trg_tutor_thread_turn_cutover_events_immutable
BEFORE UPDATE OR DELETE ON tutor_thread_turn_cutover_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_thread_turn_cutover_event_append_only();


-- Child 08-17 Codex runtime durable correlation and safe public projection.
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS runtime_kind text NOT NULL DEFAULT 'harness_v1';
ALTER TABLE tutor_runs
  DROP CONSTRAINT IF EXISTS chk_tutor_runs_runtime_kind;
ALTER TABLE tutor_runs
  ADD CONSTRAINT chk_tutor_runs_runtime_kind
  CHECK (runtime_kind IN ('harness_v1', 'codex_sidecar_v1'));

CREATE OR REPLACE FUNCTION enforce_tutor_run_runtime_kind_immutable()
RETURNS trigger AS $$
BEGIN
  IF NEW.runtime_kind IS DISTINCT FROM OLD.runtime_kind THEN
    RAISE EXCEPTION 'Tutor run runtime kind is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runs_runtime_kind_immutable ON tutor_runs;
CREATE TRIGGER trg_tutor_runs_runtime_kind_immutable
BEFORE UPDATE ON tutor_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_runtime_kind_immutable();

CREATE TABLE IF NOT EXISTS tutor_codex_runtime_health (
  worker_id text PRIMARY KEY CHECK (char_length(worker_id) BETWEEN 1 AND 160),
  status text NOT NULL CHECK (status IN ('stopped', 'starting', 'ready', 'unavailable', 'failed')),
  generation bigint NOT NULL DEFAULT 0 CHECK (generation >= 0),
  runtime_version text CHECK (runtime_version IS NULL OR char_length(runtime_version) BETWEEN 1 AND 120),
  model text CHECK (model IS NULL OR char_length(model) BETWEEN 1 AND 120),
  model_provider text CHECK (model_provider IS NULL OR char_length(model_provider) BETWEEN 1 AND 120),
  protocol text CHECK (protocol IS NULL OR char_length(protocol) BETWEEN 1 AND 40),
  safe_error_code text CHECK (
    safe_error_code IS NULL OR safe_error_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$'
  ),
  observed_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tutor_codex_runtime_health_observed
  ON tutor_codex_runtime_health(observed_at DESC, updated_at DESC);
DROP TRIGGER IF EXISTS trg_tutor_codex_runtime_health_updated_at ON tutor_codex_runtime_health;
CREATE TRIGGER trg_tutor_codex_runtime_health_updated_at
BEFORE UPDATE ON tutor_codex_runtime_health
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS tutor_conversation_runtime_threads (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  runtime_kind text NOT NULL CHECK (runtime_kind = 'codex_sidecar_v1'),
  runtime_version text NOT NULL CHECK (char_length(runtime_version) BETWEEN 1 AND 120),
  protocol_version text NOT NULL CHECK (char_length(protocol_version) BETWEEN 1 AND 120),
  model text NOT NULL CHECK (model = 'deepseek-v4-flash'),
  model_provider text NOT NULL CHECK (model_provider = 'aearn_deepseek'),
  external_thread_id text NOT NULL UNIQUE CHECK (char_length(external_thread_id) BETWEEN 1 AND 240),
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'unavailable', 'retired')),
  migration_mode text NOT NULL DEFAULT 'native' CHECK (migration_mode IN ('native', 'adopted_legacy', 'legacy_reseed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  last_resumed_at timestamptz,
  last_compacted_at timestamptz,
  CONSTRAINT uq_tutor_conversation_runtime_threads_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_conversation_runtime_thread_conversation_scope
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_conversation_runtime_threads_active
  ON tutor_conversation_runtime_threads(user_id, conversation_id, runtime_kind)
  WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_conversation_runtime_threads_owner
  ON tutor_conversation_runtime_threads(user_id, conversation_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS tutor_run_runtime_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL UNIQUE REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  conversation_runtime_thread_id uuid,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  runtime_kind text NOT NULL CHECK (runtime_kind = 'codex_sidecar_v1'),
  runtime_version text NOT NULL CHECK (char_length(runtime_version) BETWEEN 1 AND 120),
  protocol_version text NOT NULL CHECK (char_length(protocol_version) BETWEEN 1 AND 120),
  external_thread_id text NOT NULL CHECK (char_length(external_thread_id) BETWEEN 1 AND 240),
  external_turn_id text CHECK (external_turn_id IS NULL OR char_length(external_turn_id) BETWEEN 1 AND 240),
  connection_generation bigint NOT NULL CHECK (connection_generation >= 1),
  state text NOT NULL CHECK (state IN (
    'thread_bound', 'running', 'completed', 'interrupted', 'unavailable', 'failed'
  )),
  final_message_id uuid,
  final_message_blocked boolean NOT NULL DEFAULT false,
  safe_error_code text CHECK (safe_error_code IS NULL OR safe_error_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$'),
  started_at timestamptz,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_runtime_bindings_scope UNIQUE (id, run_id, user_id, conversation_id),
  CONSTRAINT fk_tutor_runtime_binding_run_scope
    FOREIGN KEY (run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_runtime_binding_message_scope
    FOREIGN KEY (final_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_runtime_binding_terminal CHECK (
    (state IN ('thread_bound', 'running') AND terminal_at IS NULL)
    OR (state IN ('completed', 'interrupted', 'unavailable', 'failed') AND terminal_at IS NOT NULL)
  )
);
ALTER TABLE tutor_run_runtime_bindings
  ADD COLUMN IF NOT EXISTS conversation_runtime_thread_id uuid;
ALTER TABLE tutor_run_runtime_bindings
  DROP CONSTRAINT IF EXISTS uq_tutor_runtime_bindings_thread;
-- Existing installations may already have immutable/update-timestamp triggers from
-- a prior bootstrap. Disable them while the additive conversation-thread backfill runs;
-- both triggers are recreated below after all migration updates are complete.
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_lifecycle ON tutor_run_runtime_bindings;
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_updated_at ON tutor_run_runtime_bindings;

INSERT INTO tutor_conversation_runtime_threads (
  user_id, conversation_id, runtime_kind, runtime_version, protocol_version,
  model, model_provider, external_thread_id, state, migration_mode,
  created_at, updated_at, last_resumed_at
)
SELECT legacy.user_id, legacy.conversation_id, 'codex_sidecar_v1',
       min(legacy.runtime_version), min(legacy.protocol_version),
       'deepseek-v4-flash', 'aearn_deepseek', min(legacy.external_thread_id),
       'active', 'adopted_legacy', min(legacy.created_at), max(legacy.updated_at), max(legacy.updated_at)
FROM tutor_run_runtime_bindings AS legacy
WHERE NOT EXISTS (
  SELECT 1 FROM tutor_conversation_runtime_threads AS existing
  WHERE existing.user_id = legacy.user_id
    AND existing.conversation_id = legacy.conversation_id
    AND existing.runtime_kind = 'codex_sidecar_v1'
)
GROUP BY legacy.user_id, legacy.conversation_id
HAVING count(DISTINCT legacy.external_thread_id) = 1
ON CONFLICT DO NOTHING;

UPDATE tutor_run_runtime_bindings AS bindings
SET conversation_runtime_thread_id = threads.id
FROM tutor_conversation_runtime_threads AS threads
WHERE bindings.conversation_runtime_thread_id IS NULL
  AND threads.user_id = bindings.user_id
  AND threads.conversation_id = bindings.conversation_id
  AND threads.runtime_kind = bindings.runtime_kind
  AND threads.external_thread_id = bindings.external_thread_id;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'fk_tutor_runtime_binding_conversation_thread_scope'
  ) THEN
    ALTER TABLE tutor_run_runtime_bindings
      ADD CONSTRAINT fk_tutor_runtime_binding_conversation_thread_scope
      FOREIGN KEY (conversation_runtime_thread_id, user_id, conversation_id)
      REFERENCES tutor_conversation_runtime_threads(id, user_id, conversation_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
END;
$$;
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_bindings_conversation_thread
  ON tutor_run_runtime_bindings(conversation_runtime_thread_id, created_at, id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runtime_bindings_turn
  ON tutor_run_runtime_bindings(runtime_kind, external_turn_id)
  WHERE external_turn_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_bindings_run_state
  ON tutor_run_runtime_bindings(user_id, run_id, state, updated_at DESC);

CREATE TABLE IF NOT EXISTS tutor_runtime_text_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id uuid NOT NULL REFERENCES tutor_run_runtime_bindings(id) ON DELETE RESTRICT,
  conversation_runtime_thread_id uuid NOT NULL REFERENCES tutor_conversation_runtime_threads(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  external_item_hash text NOT NULL CHECK (external_item_hash ~ '^[0-9a-f]{64}$'),
  channel text NOT NULL CHECK (channel IN ('reasoning', 'final_answer')),
  state text NOT NULL CHECK (state IN ('streaming', 'completed', 'discarded', 'blocked')),
  text text NOT NULL DEFAULT '' CHECK (char_length(text) <= 1000000),
  last_event_sequence integer NOT NULL DEFAULT 0 CHECK (last_event_sequence >= 0),
  content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
  connection_generation bigint NOT NULL CHECK (connection_generation >= 1),
  public_message_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CONSTRAINT uq_tutor_runtime_text_items_identity UNIQUE (binding_id, external_item_hash, channel),
  CONSTRAINT uq_tutor_runtime_text_items_scope UNIQUE (id, user_id, conversation_id),
  CONSTRAINT fk_tutor_runtime_text_item_binding_scope
    FOREIGN KEY (binding_id, run_id, user_id, conversation_id)
    REFERENCES tutor_run_runtime_bindings(id, run_id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_runtime_text_item_conversation_thread_scope
    FOREIGN KEY (conversation_runtime_thread_id, user_id, conversation_id)
    REFERENCES tutor_conversation_runtime_threads(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_runtime_text_item_message_scope
    FOREIGN KEY (public_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_runtime_text_item_terminal CHECK (
    (state = 'streaming' AND completed_at IS NULL)
    OR (state IN ('completed', 'discarded', 'blocked') AND completed_at IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_text_items_active
  ON tutor_runtime_text_items(user_id, conversation_id, run_id, channel, state, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_text_items_message
  ON tutor_runtime_text_items(user_id, public_message_id, channel, created_at, id)
  WHERE public_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS tutor_runtime_item_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id uuid NOT NULL REFERENCES tutor_run_runtime_bindings(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  event_key text NOT NULL CHECK (event_key ~ '^[0-9a-f]{64}$'),
  event_kind text NOT NULL CHECK (event_kind IN (
    'turn_started', 'message_delta', 'message_completed', 'tool_started',
    'tool_completed', 'turn_completed', 'warning'
  )),
  external_item_hash text CHECK (external_item_hash IS NULL OR external_item_hash ~ '^[0-9a-f]{64}$'),
  event_sequence integer NOT NULL CHECK (event_sequence >= 1),
  projection_sequence integer NOT NULL CHECK (projection_sequence >= 1),
  source_sequence_start bigint,
  source_sequence_end bigint,
  source_delta_count integer,
  source_content_hash text CHECK (source_content_hash IS NULL OR source_content_hash ~ '^[0-9a-f]{64}$'),
  item_kind text CHECK (item_kind IS NULL OR item_kind IN ('turn', 'message', 'tool', 'warning')),
  item_status text CHECK (item_status IS NULL OR char_length(item_status) BETWEEN 1 AND 80),
  tool_name text CHECK (tool_name IS NULL OR tool_name ~ '^[A-Za-z0-9_-]{1,64}$'),
  input_hash text CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
  result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
  content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
  safe_code text CHECK (safe_code IS NULL OR safe_code ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,119}$'),
  projection_status text NOT NULL CHECK (projection_status IN (
    'applied', 'ignored_nonpublic', 'ignored_stale', 'blocked_unsafe'
  )),
  public_item_id uuid,
  public_item_kind text CHECK (public_item_kind IS NULL OR public_item_kind IN ('message', 'process', 'error', 'runtime_output')),
  occurred_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_runtime_item_receipts_event UNIQUE (binding_id, event_key),
  CONSTRAINT uq_tutor_runtime_item_receipts_sequence UNIQUE (binding_id, event_sequence),
  CONSTRAINT chk_tutor_runtime_receipt_projection_sequence
    CHECK (event_sequence = projection_sequence),
  CONSTRAINT chk_tutor_runtime_receipt_source_range CHECK (
    (
      source_sequence_start IS NULL
      AND source_sequence_end IS NULL
      AND source_delta_count IS NULL
      AND source_content_hash IS NULL
    )
    OR (
      source_sequence_start IS NOT NULL
      AND source_sequence_end IS NOT NULL
      AND source_delta_count IS NOT NULL
      AND source_content_hash IS NOT NULL
      AND source_sequence_start >= 1
      AND source_sequence_end >= source_sequence_start
      AND source_delta_count >= 1
      AND source_delta_count = source_sequence_end - source_sequence_start + 1
      AND source_content_hash ~ '^[0-9a-f]{64}$'
    )
  ),
  CONSTRAINT fk_tutor_runtime_receipt_binding_scope
    FOREIGN KEY (binding_id, run_id, user_id, conversation_id)
    REFERENCES tutor_run_runtime_bindings(id, run_id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_runtime_receipt_public_item CHECK (
    (public_item_id IS NULL AND public_item_kind IS NULL)
    OR (public_item_id IS NOT NULL AND public_item_kind IS NOT NULL)
  )
);
DROP TRIGGER IF EXISTS trg_tutor_runtime_receipts_immutable
  ON tutor_runtime_item_receipts;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS projection_sequence integer;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_sequence_start bigint;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_sequence_end bigint;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_delta_count integer;
ALTER TABLE tutor_runtime_item_receipts
  ADD COLUMN IF NOT EXISTS source_content_hash text;
UPDATE tutor_runtime_item_receipts
SET projection_sequence = event_sequence
WHERE projection_sequence IS NULL;
ALTER TABLE tutor_runtime_item_receipts
  ALTER COLUMN projection_sequence SET NOT NULL;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_receipt_projection_sequence;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_receipt_projection_sequence
  CHECK (event_sequence = projection_sequence);
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_receipt_source_range;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_receipt_source_range CHECK (
    (
      source_sequence_start IS NULL
      AND source_sequence_end IS NULL
      AND source_delta_count IS NULL
      AND source_content_hash IS NULL
    )
    OR (
      source_sequence_start IS NOT NULL
      AND source_sequence_end IS NOT NULL
      AND source_delta_count IS NOT NULL
      AND source_content_hash IS NOT NULL
      AND source_sequence_start >= 1
      AND source_sequence_end >= source_sequence_start
      AND source_delta_count >= 1
      AND source_delta_count = source_sequence_end - source_sequence_start + 1
      AND source_content_hash ~ '^[0-9a-f]{64}$'
    )
  );
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runtime_item_receipts_projection_sequence
  ON tutor_runtime_item_receipts(binding_id, projection_sequence);
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS tutor_runtime_item_receipts_event_kind_check;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_item_receipts_event_kind;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_item_receipts_event_kind CHECK (event_kind IN (
    'turn_started',
    'reasoning_started', 'reasoning_delta', 'reasoning_completed',
    'reasoning_summary_started', 'reasoning_summary_delta', 'reasoning_summary_completed',
    'message_started', 'message_delta', 'message_completed',
    'context_compaction_started', 'context_compaction_completed',
    'tool_started', 'tool_completed', 'turn_completed', 'warning'
  ));
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS tutor_runtime_item_receipts_public_item_kind_check;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_item_receipts_public_item_kind;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_item_receipts_public_item_kind CHECK (
    public_item_kind IS NULL OR public_item_kind IN ('message', 'process', 'error', 'runtime_output')
  );
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS tutor_runtime_item_receipts_item_kind_check;
ALTER TABLE tutor_runtime_item_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_runtime_item_receipts_item_kind;
ALTER TABLE tutor_runtime_item_receipts
  ADD CONSTRAINT chk_tutor_runtime_item_receipts_item_kind CHECK (
    item_kind IS NULL OR item_kind IN ('turn', 'reasoning', 'reasoning_summary', 'message', 'context_compaction', 'tool', 'warning')
  );
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_receipts_run_sequence
  ON tutor_runtime_item_receipts(user_id, run_id, projection_sequence, created_at);

CREATE TABLE IF NOT EXISTS tutor_runtime_public_errors (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  binding_id uuid NOT NULL UNIQUE REFERENCES tutor_run_runtime_bindings(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  code text NOT NULL CHECK (code ~ '^[A-Z][A-Z0-9_]{0,119}$'),
  recoverable boolean NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT fk_tutor_runtime_error_binding_scope
    FOREIGN KEY (binding_id, run_id, user_id, conversation_id)
    REFERENCES tutor_run_runtime_bindings(id, run_id, user_id, conversation_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_tutor_runtime_errors_conversation
  ON tutor_runtime_public_errors(user_id, conversation_id, created_at DESC);

CREATE OR REPLACE FUNCTION enforce_tutor_conversation_runtime_thread_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor conversation runtime threads are retained private state' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
     OR NEW.runtime_kind IS DISTINCT FROM OLD.runtime_kind
     OR NEW.runtime_version IS DISTINCT FROM OLD.runtime_version
     OR NEW.protocol_version IS DISTINCT FROM OLD.protocol_version
     OR NEW.model IS DISTINCT FROM OLD.model
     OR NEW.model_provider IS DISTINCT FROM OLD.model_provider
     OR NEW.external_thread_id IS DISTINCT FROM OLD.external_thread_id
     OR NEW.migration_mode IS DISTINCT FROM OLD.migration_mode THEN
    RAISE EXCEPTION 'Tutor conversation runtime thread identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'retired' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Retired Tutor conversation runtime thread is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_conversation_runtime_threads_lifecycle ON tutor_conversation_runtime_threads;
CREATE TRIGGER trg_tutor_conversation_runtime_threads_lifecycle
BEFORE UPDATE OR DELETE ON tutor_conversation_runtime_threads
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_conversation_runtime_thread_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_conversation_runtime_threads_updated_at ON tutor_conversation_runtime_threads;
CREATE TRIGGER trg_tutor_conversation_runtime_threads_updated_at
BEFORE UPDATE ON tutor_conversation_runtime_threads
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_runtime_text_item_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor runtime text items are private retained state' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id
     OR NEW.binding_id IS DISTINCT FROM OLD.binding_id
     OR NEW.conversation_runtime_thread_id IS DISTINCT FROM OLD.conversation_runtime_thread_id
     OR NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
     OR NEW.external_item_hash IS DISTINCT FROM OLD.external_item_hash
     OR NEW.channel IS DISTINCT FROM OLD.channel
     OR NEW.connection_generation IS DISTINCT FROM OLD.connection_generation
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Tutor runtime text item identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'completed'
     AND OLD.public_message_id IS NULL
     AND NEW.public_message_id IS NOT NULL
     AND NEW.state IS NOT DISTINCT FROM OLD.state
     AND NEW.text IS NOT DISTINCT FROM OLD.text
     AND NEW.last_event_sequence IS NOT DISTINCT FROM OLD.last_event_sequence
     AND NEW.content_hash IS NOT DISTINCT FROM OLD.content_hash
     AND NEW.completed_at IS NOT DISTINCT FROM OLD.completed_at THEN
    RETURN NEW;
  END IF;
  IF OLD.state IN ('completed', 'discarded', 'blocked') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal Tutor runtime text item is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runtime_text_items_lifecycle ON tutor_runtime_text_items;
CREATE TRIGGER trg_tutor_runtime_text_items_lifecycle
BEFORE UPDATE OR DELETE ON tutor_runtime_text_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_text_item_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_runtime_text_items_updated_at ON tutor_runtime_text_items;
CREATE TRIGGER trg_tutor_runtime_text_items_updated_at
BEFORE UPDATE ON tutor_runtime_text_items
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_runtime_binding_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor runtime bindings are retained audit state' USING ERRCODE = '23514';
  END IF;
  IF NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.conversation_runtime_thread_id IS DISTINCT FROM OLD.conversation_runtime_thread_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
     OR NEW.runtime_kind IS DISTINCT FROM OLD.runtime_kind
     OR NEW.runtime_version IS DISTINCT FROM OLD.runtime_version
     OR NEW.protocol_version IS DISTINCT FROM OLD.protocol_version
     OR NEW.external_thread_id IS DISTINCT FROM OLD.external_thread_id
     OR NEW.connection_generation IS DISTINCT FROM OLD.connection_generation THEN
    RAISE EXCEPTION 'Tutor runtime binding identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('completed', 'interrupted', 'unavailable', 'failed') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Tutor runtime terminal binding is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_lifecycle ON tutor_run_runtime_bindings;
CREATE TRIGGER trg_tutor_runtime_bindings_lifecycle
BEFORE UPDATE OR DELETE ON tutor_run_runtime_bindings
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_binding_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_runtime_bindings_updated_at ON tutor_run_runtime_bindings;
CREATE TRIGGER trg_tutor_runtime_bindings_updated_at
BEFORE UPDATE ON tutor_run_runtime_bindings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION enforce_tutor_runtime_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Tutor runtime receipts and public errors are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_tutor_runtime_receipts_immutable ON tutor_runtime_item_receipts;
CREATE TRIGGER trg_tutor_runtime_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_runtime_item_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_append_only();
DROP TRIGGER IF EXISTS trg_tutor_runtime_errors_immutable ON tutor_runtime_public_errors;
CREATE TRIGGER trg_tutor_runtime_errors_immutable
BEFORE UPDATE OR DELETE ON tutor_runtime_public_errors
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_append_only();

ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS tutor_run_public_processes_current_step_key_check;
ALTER TABLE tutor_run_public_processes
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_current_step_key;
ALTER TABLE tutor_run_public_processes
  ADD CONSTRAINT chk_tutor_public_process_current_step_key CHECK (current_step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'runtime_started', 'domain_tool_running', 'domain_tool_completed',
    'learning_reply_generated', 'replaced_by_newer_input'
  ));
ALTER TABLE tutor_run_public_process_steps
  DROP CONSTRAINT IF EXISTS tutor_run_public_process_steps_step_key_check;
ALTER TABLE tutor_run_public_process_steps
  DROP CONSTRAINT IF EXISTS chk_tutor_public_process_step_key;
ALTER TABLE tutor_run_public_process_steps
  ADD CONSTRAINT chk_tutor_public_process_step_key CHECK (step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'runtime_started', 'domain_tool_running', 'domain_tool_completed',
    'learning_reply_generated', 'replaced_by_newer_input'
  ));
