-- Child 06 published demonstration descriptors and exactly-once completion receipts.

ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS tutor_learning_artifacts_presentation_kind_check;
ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifact_presentation_kind;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT chk_tutor_learning_artifact_presentation_kind CHECK (
    (artifact_kind = 'exercise_workspace' AND presentation_kind = 'exercise_workspace_v1') OR
    (artifact_kind = 'browser_preview' AND presentation_kind = 'browser_preview_v1') OR
    (artifact_kind = 'test_result' AND presentation_kind = 'test_result_v1') OR
    (artifact_kind = 'knowledge_check' AND presentation_kind = 'knowledge_check_v1') OR
    (artifact_kind = 'model_code_review' AND presentation_kind IN ('model_code_review_v1', 'model_code_review_v2')) OR
    (artifact_kind = 'sql_workspace' AND presentation_kind = 'sql_workspace_v1') OR
    (artifact_kind = 'demonstration' AND presentation_kind IN ('demonstration_v1', 'demonstration_v2')) OR
    (artifact_kind = 'source_inspector' AND presentation_kind = 'source_inspector_v1')
  );

ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS tutor_learning_artifacts_allowed_actions_json_check;
ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifacts_allowed_actions;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT chk_tutor_learning_artifacts_allowed_actions CHECK (
    jsonb_typeof(allowed_actions_json) = 'array'
    AND jsonb_array_length(allowed_actions_json) <= 6
    AND allowed_actions_json <@ '["request_hint","request_direct_answer","run","respond","complete_review","cancel","acknowledge_demo_event","complete_demo"]'::jsonb
  );

ALTER TABLE tutor_learning_artifact_events
  DROP CONSTRAINT IF EXISTS tutor_learning_artifact_events_action_kind_check;
ALTER TABLE tutor_learning_artifact_events
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifact_events_action_kind;
ALTER TABLE tutor_learning_artifact_events
  ADD CONSTRAINT chk_tutor_learning_artifact_events_action_kind CHECK (
    action_kind IS NULL OR action_kind IN (
      'request_hint', 'request_direct_answer', 'run', 'respond', 'complete_review', 'cancel',
      'acknowledge_demo_event', 'complete_demo'
    )
  );

CREATE TABLE IF NOT EXISTS tutor_demonstration_completion_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  artifact_version integer NOT NULL CHECK (artifact_version >= 1),
  descriptor_hash text NOT NULL CHECK (descriptor_hash ~ '^[0-9a-f]{64}$'),
  completion_kind text NOT NULL CHECK (
    completion_kind IN ('interactive_event', 'visible_clock')
  ),
  event_key text CHECK (
    event_key IS NULL OR event_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  event_payload_hash text CHECK (
    event_payload_hash IS NULL OR event_payload_hash ~ '^[0-9a-f]{64}$'
  ),
  source_nonce text NOT NULL CHECK (char_length(source_nonce) BETWEEN 1 AND 160),
  source_generation integer CHECK (source_generation IS NULL OR source_generation >= 1),
  source_sequence integer CHECK (source_sequence IS NULL OR source_sequence >= 1),
  visible_elapsed_ms integer CHECK (
    visible_elapsed_ms IS NULL OR visible_elapsed_ms BETWEEN 6000 AND 240000
  ),
  required_visible_ms integer CHECK (
    required_visible_ms IS NULL OR required_visible_ms BETWEEN 6000 AND 240000
  ),
  idempotency_key text NOT NULL CHECK (
    idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'
  ),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  completed_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_demo_completion_artifact UNIQUE (artifact_id),
  CONSTRAINT uq_tutor_demo_completion_idempotency
    UNIQUE (user_id, conversation_id, idempotency_key),
  CONSTRAINT uq_tutor_demo_completion_id_scope
    UNIQUE (id, user_id, conversation_id, artifact_id),
  CONSTRAINT fk_tutor_demo_completion_artifact_scope
    FOREIGN KEY (
      artifact_id, user_id, conversation_id, teaching_session_id, learning_track_id
    ) REFERENCES tutor_learning_artifacts(
      id, user_id, conversation_id, teaching_session_id, learning_track_id
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT chk_tutor_demo_completion_shape CHECK (
    (
      completion_kind = 'interactive_event'
      AND event_key IS NOT NULL AND event_payload_hash IS NOT NULL
      AND source_nonce ~ '^[0-9a-f]{64}$'
      AND source_generation IS NOT NULL AND source_sequence IS NOT NULL
      AND visible_elapsed_ms IS NULL AND required_visible_ms IS NULL
    )
    OR
    (
      completion_kind = 'visible_clock'
      AND event_key IS NULL AND event_payload_hash IS NULL
      AND source_nonce ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'
      AND source_generation IS NULL AND source_sequence IS NULL
      AND visible_elapsed_ms IS NOT NULL AND required_visible_ms IS NOT NULL
      AND visible_elapsed_ms >= required_visible_ms
      AND visible_elapsed_ms <= required_visible_ms + 2000
    )
  )
);

CREATE OR REPLACE FUNCTION tutor_demo_completion_continuation_valid(
  p_artifact_id uuid,
  p_user_id uuid,
  p_conversation_id uuid,
  p_source_kind text,
  p_source_id text,
  p_source_version integer,
  p_artifact_version integer
)
RETURNS boolean AS $$
  SELECT EXISTS (
    SELECT 1
    FROM tutor_demonstration_completion_receipts AS receipts
    JOIN tutor_learning_artifacts AS artifacts
      ON artifacts.id = receipts.artifact_id
     AND artifacts.user_id = receipts.user_id
     AND artifacts.conversation_id = receipts.conversation_id
    JOIN tutor_learning_artifact_events AS events
      ON events.artifact_id = artifacts.id
     AND events.user_id = artifacts.user_id
     AND events.conversation_id = artifacts.conversation_id
     AND events.teaching_session_id = artifacts.teaching_session_id
    WHERE artifacts.id = p_artifact_id
      AND artifacts.user_id = p_user_id
      AND artifacts.conversation_id = p_conversation_id
      AND artifacts.artifact_kind = 'demonstration'
      AND artifacts.presentation_kind = 'demonstration_v2'
      AND artifacts.state = 'completed'
      AND artifacts.version = p_artifact_version
      AND artifacts.version = events.to_version
      AND artifacts.presentation_hash = receipts.descriptor_hash
      AND receipts.completion_kind = CASE p_source_kind
        WHEN 'expected_interactive_event' THEN 'interactive_event'
        WHEN 'static_display_timer' THEN 'visible_clock'
        ELSE NULL
      END
      AND events.id::text = p_source_id
      AND events.event_sequence = p_source_version
      AND events.event_kind = 'action'
      AND events.action_kind = 'complete_demo'
      AND events.safe_payload_json->'owner_result'->>'completion_receipt_id' = receipts.id::text
      AND events.safe_payload_json->'owner_result'->>'completion_kind' = receipts.completion_kind
      AND events.safe_payload_json->'owner_result'->>'descriptor_hash' = receipts.descriptor_hash
  );
$$ LANGUAGE sql STABLE;

CREATE INDEX IF NOT EXISTS idx_tutor_demo_completion_user
  ON tutor_demonstration_completion_receipts(user_id, completed_at, id);

CREATE OR REPLACE FUNCTION enforce_tutor_demo_completion_receipt()
RETURNS trigger AS $$
DECLARE
  artifact_row tutor_learning_artifacts%ROWTYPE;
  session_row tutor_teaching_sessions%ROWTYPE;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Tutor demonstration completion receipt is append-only'
      USING ERRCODE = '23514';
  END IF;

  SELECT * INTO artifact_row
  FROM tutor_learning_artifacts
  WHERE id = NEW.artifact_id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND learning_track_id = NEW.learning_track_id
    AND teaching_session_id = NEW.teaching_session_id
    AND checkpoint_id = NEW.checkpoint_id;
  SELECT * INTO session_row
  FROM tutor_teaching_sessions
  WHERE id = NEW.teaching_session_id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND track_id = NEW.learning_track_id;

  IF artifact_row.id IS NULL OR session_row.id IS NULL
     OR artifact_row.artifact_kind <> 'demonstration'
     OR artifact_row.presentation_kind <> 'demonstration_v2'
     OR artifact_row.state NOT IN ('ready', 'active')
     OR artifact_row.version <> NEW.artifact_version
     OR artifact_row.presentation_hash <> NEW.descriptor_hash
     OR session_row.status NOT IN ('active', 'paused')
     OR session_row.current_checkpoint_id <> NEW.checkpoint_id THEN
    RAISE EXCEPTION 'Tutor demonstration completion authority is stale or mismatched'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_demo_completion_receipts_guard
  ON tutor_demonstration_completion_receipts;
CREATE TRIGGER trg_tutor_demo_completion_receipts_guard
BEFORE INSERT OR UPDATE OR DELETE ON tutor_demonstration_completion_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_demo_completion_receipt();