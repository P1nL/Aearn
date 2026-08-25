-- Child 08-02 conversation TurnRun/history contract: additive and repeatable.
-- Legacy messages remain readable; only new interactive turns receive a public-process projection.
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS title text;
ALTER TABLE tutor_conversations
  ADD COLUMN IF NOT EXISTS last_public_activity_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS superseded_by_run_id uuid;
ALTER TABLE tutor_runs
  ADD COLUMN IF NOT EXISTS continuation_kind text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_runs'::regclass
      AND conname = 'fk_tutor_runs_superseded_by_run'
  ) THEN
    ALTER TABLE tutor_runs
      ADD CONSTRAINT fk_tutor_runs_superseded_by_run
      FOREIGN KEY (superseded_by_run_id) REFERENCES tutor_runs(id) ON DELETE RESTRICT;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_conversations'::regclass
      AND conname = 'chk_tutor_conversations_title'
  ) THEN
    ALTER TABLE tutor_conversations
      ADD CONSTRAINT chk_tutor_conversations_title
      CHECK (title IS NULL OR (char_length(title) BETWEEN 1 AND 48 AND title !~ '[\r\n\t]'));
  END IF;

  ALTER TABLE tutor_runs
    DROP CONSTRAINT IF EXISTS chk_tutor_runs_continuation_kind;
  ALTER TABLE tutor_runs
    ADD CONSTRAINT chk_tutor_runs_continuation_kind
    CHECK (
      continuation_kind IS NULL OR continuation_kind IN (
        'clarification', 'planning_input', 'approval', 'capability_result', 'external_result'
      )
    );
END $$;

CREATE TABLE IF NOT EXISTS tutor_run_public_processes (
  run_id uuid PRIMARY KEY REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  projection_version text NOT NULL DEFAULT 'tutor_public_process_v1'
    CHECK (projection_version = 'tutor_public_process_v1'),
  display_state text NOT NULL CHECK (display_state IN ('thinking', 'completed', 'superseded', 'unavailable')),
  current_step_key text NOT NULL CHECK (current_step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'learning_reply_generated', 'replaced_by_newer_input'
  )),
  tutor_message_id uuid REFERENCES tutor_messages(id) ON DELETE RESTRICT,
  started_at timestamptz NOT NULL,
  last_public_activity_at timestamptz NOT NULL,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_public_process_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_public_process_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_public_process_message_conversation
    FOREIGN KEY (tutor_message_id, conversation_id) REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_public_process_finished_state CHECK (
    (display_state = 'thinking' AND finished_at IS NULL)
    OR (display_state IN ('completed', 'superseded', 'unavailable') AND finished_at IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_run_public_process_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  ordinal integer NOT NULL CHECK (ordinal >= 1),
  step_key text NOT NULL CHECK (step_key IN (
    'input_received', 'context_prepared', 'authorized_resource_checked',
    'learning_reply_generated', 'replaced_by_newer_input'
  )),
  state text NOT NULL CHECK (state IN ('completed', 'current')),
  occurred_at timestamptz NOT NULL,
  UNIQUE (run_id, ordinal)
);

-- One live foreground interactive run is allowed per learner conversation.
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runs_interactive_foreground
  ON tutor_runs (conversation_id)
  WHERE origin = 'interactive'
    AND terminal_outcome IS NULL
    AND cancelled_at IS NULL
    AND superseded_by_run_id IS NULL;
CREATE INDEX IF NOT EXISTS idx_tutor_conversations_public_activity
  ON tutor_conversations (user_id, last_public_activity_at DESC, id DESC)
  WHERE visibility = 'learner' AND kind = 'interactive' AND status = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_public_processes_conversation_activity
  ON tutor_run_public_processes (conversation_id, last_public_activity_at DESC, run_id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_public_process_steps_run_ordinal
  ON tutor_run_public_process_steps (run_id, ordinal);

DROP TRIGGER IF EXISTS trg_tutor_public_processes_updated_at ON tutor_run_public_processes;
CREATE TRIGGER trg_tutor_public_processes_updated_at BEFORE UPDATE ON tutor_run_public_processes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
