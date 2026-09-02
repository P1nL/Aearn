-- Child 01 Learning Artifact authority: learner-safe inline interaction state,
-- append-only evidence, scoped Attempt links, and conversation references.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_teaching_sessions'::regclass
      AND conname = 'uq_tutor_teaching_sessions_artifact_scope'
  ) THEN
    ALTER TABLE tutor_teaching_sessions
      ADD CONSTRAINT uq_tutor_teaching_sessions_artifact_scope
      UNIQUE (id, user_id, conversation_id, track_id, knowledge_key);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_exercise_attempts'::regclass
      AND conname = 'uq_tutor_exercise_attempts_artifact_scope'
  ) THEN
    ALTER TABLE tutor_exercise_attempts
      ADD CONSTRAINT uq_tutor_exercise_attempts_artifact_scope
      UNIQUE (id, user_id, track_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_exercise_attempts'::regclass
      AND conname = 'uq_tutor_exercise_attempts_artifact_exact_scope'
  ) THEN
    ALTER TABLE tutor_exercise_attempts
      ADD CONSTRAINT uq_tutor_exercise_attempts_artifact_exact_scope
      UNIQUE (id, user_id, track_id, knowledge_key);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_learning_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  turn_id uuid,
  learning_track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  track_version integer NOT NULL CHECK (track_version >= 1),
  progress_version integer NOT NULL CHECK (progress_version >= 1),
  assignment_version integer NOT NULL CHECK (assignment_version >= 1),
  owner_kind text NOT NULL CHECK (owner_kind IN (
    'lesson_gate', 'review_item', 'teaching_practice', 'learning_item'
  )),
  owner_id uuid NOT NULL,
  owner_version integer NOT NULL CHECK (owner_version >= 1),
  owner_context_version integer CHECK (owner_context_version IS NULL OR owner_context_version >= 1),
  artifact_schema_version text NOT NULL DEFAULT 'tutor_learning_artifact_v1'
    CHECK (artifact_schema_version = 'tutor_learning_artifact_v1'),
  artifact_kind text NOT NULL CHECK (artifact_kind IN (
    'exercise_workspace', 'browser_preview', 'test_result', 'knowledge_check',
    'model_code_review', 'sql_workspace', 'demonstration', 'source_inspector'
  )),
  purpose text NOT NULL CHECK (purpose IN (
    'exercise', 'demonstration', 'knowledge_check', 'remediation',
    'transfer_check', 'code_review', 'sql_exploration', 'result'
  )),
  state text NOT NULL CHECK (state IN (
    'pending', 'ready', 'active', 'running',
    'completed', 'failed', 'cancelled', 'superseded'
  )),
  blocking boolean NOT NULL DEFAULT true,
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  instruction_markdown text NOT NULL CHECK (char_length(instruction_markdown) BETWEEN 1 AND 8000),
  difficulty text CHECK (difficulty IS NULL OR difficulty IN ('D1', 'D2', 'D3', 'D4', 'D5')),
  presentation_kind text NOT NULL CHECK (presentation_kind IN (
    'exercise_workspace_v1', 'browser_preview_v1', 'test_result_v1', 'knowledge_check_v1',
    'model_code_review_v1', 'model_code_review_v2', 'sql_workspace_v1', 'demonstration_v1', 'source_inspector_v1'
  )),
  presentation_json jsonb NOT NULL CHECK (
    jsonb_typeof(presentation_json) = 'object'
    AND octet_length(presentation_json::text) <= 65536
  ),
  presentation_hash text NOT NULL CHECK (presentation_hash ~ '^[0-9a-f]{64}$'),
  allowed_actions_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
    jsonb_typeof(allowed_actions_json) = 'array'
    AND jsonb_array_length(allowed_actions_json) <= 6
    AND allowed_actions_json <@ '["request_hint","run","respond","complete_review","cancel","acknowledge_demo_event"]'::jsonb
  ),
  active_attempt_id uuid,
  active_attempt_summary_json jsonb CHECK (
    active_attempt_summary_json IS NULL OR (
      jsonb_typeof(active_attempt_summary_json) = 'object'
      AND octet_length(active_attempt_summary_json::text) <= 8192
    )
  ),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_artifacts_id_scope
    UNIQUE (id, user_id, conversation_id, teaching_session_id),
  CONSTRAINT uq_tutor_learning_artifacts_exact_scope
    UNIQUE (id, user_id, conversation_id, teaching_session_id, learning_track_id),
  CONSTRAINT fk_tutor_learning_artifact_conversation
    FOREIGN KEY (conversation_id, user_id)
    REFERENCES tutor_conversations(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_artifact_turn
    FOREIGN KEY (turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_artifact_track
    FOREIGN KEY (learning_track_id, user_id)
    REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_artifact_progress
    FOREIGN KEY (learning_track_id, user_id, knowledge_key)
    REFERENCES tutor_track_node_progress(track_id, user_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_artifact_session
    FOREIGN KEY (teaching_session_id, user_id, conversation_id, learning_track_id, knowledge_key)
    REFERENCES tutor_teaching_sessions(id, user_id, conversation_id, track_id, knowledge_key)
    ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_artifact_checkpoint
    FOREIGN KEY (checkpoint_id, teaching_session_id, user_id, conversation_id)
    REFERENCES tutor_teaching_session_checkpoints(id, teaching_session_id, user_id, conversation_id)
    ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_artifact_active_attempt
    FOREIGN KEY (active_attempt_id, user_id, learning_track_id, knowledge_key)
    REFERENCES tutor_exercise_attempts(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_learning_artifact_presentation_kind CHECK (
    (artifact_kind = 'exercise_workspace' AND presentation_kind = 'exercise_workspace_v1') OR
    (artifact_kind = 'browser_preview' AND presentation_kind = 'browser_preview_v1') OR
    (artifact_kind = 'test_result' AND presentation_kind = 'test_result_v1') OR
    (artifact_kind = 'knowledge_check' AND presentation_kind = 'knowledge_check_v1') OR
    (artifact_kind = 'model_code_review' AND presentation_kind IN ('model_code_review_v1', 'model_code_review_v2')) OR
    (artifact_kind = 'sql_workspace' AND presentation_kind = 'sql_workspace_v1') OR
    (artifact_kind = 'demonstration' AND presentation_kind = 'demonstration_v1') OR
    (artifact_kind = 'source_inspector' AND presentation_kind = 'source_inspector_v1')
  ),
  CONSTRAINT chk_tutor_learning_artifact_attempt_shape CHECK (
    (active_attempt_id IS NULL) = (active_attempt_summary_json IS NULL)
  ),
  CONSTRAINT chk_tutor_learning_artifact_terminal CHECK (
    (state IN ('completed', 'failed', 'cancelled', 'superseded')) = (terminal_at IS NOT NULL)
    AND (
      state NOT IN ('completed', 'failed', 'cancelled', 'superseded')
      OR allowed_actions_json = '[]'::jsonb
    )
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_learning_artifacts_one_blocking_conversation
  ON tutor_learning_artifacts(conversation_id)
  WHERE blocking AND state IN ('pending', 'ready', 'active', 'running');
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_learning_artifacts_one_blocking_session
  ON tutor_learning_artifacts(teaching_session_id)
  WHERE blocking AND state IN ('pending', 'ready', 'active', 'running');
CREATE INDEX IF NOT EXISTS idx_tutor_learning_artifacts_conversation_timeline
  ON tutor_learning_artifacts(conversation_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_artifacts_owner
  ON tutor_learning_artifacts(user_id, owner_kind, owner_id, owner_version);

CREATE TABLE IF NOT EXISTS tutor_learning_artifact_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  event_sequence integer NOT NULL CHECK (event_sequence >= 1),
  event_key text NOT NULL CHECK (char_length(event_key) BETWEEN 1 AND 200),
  event_kind text NOT NULL CHECK (event_kind IN (
    'created', 'action', 'state_changed', 'attempt_linked', 'terminal'
  )),
  from_version integer CHECK (from_version IS NULL OR from_version >= 1),
  to_version integer NOT NULL CHECK (to_version >= 1),
  state text NOT NULL CHECK (state IN (
    'pending', 'ready', 'active', 'running',
    'completed', 'failed', 'cancelled', 'superseded'
  )),
  action_kind text CHECK (action_kind IS NULL OR action_kind IN (
    'request_hint', 'run', 'respond', 'complete_review', 'cancel', 'acknowledge_demo_event'
  )),
  client_action_id text CHECK (
    client_action_id IS NULL OR client_action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'
  ),
  request_hash text CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$'),
  safe_payload_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (
    jsonb_typeof(safe_payload_json) = 'object'
    AND octet_length(safe_payload_json::text) <= 8192
  ),
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_artifact_events_sequence UNIQUE (artifact_id, event_sequence),
  CONSTRAINT uq_tutor_learning_artifact_events_key UNIQUE (artifact_id, event_key),
  CONSTRAINT uq_tutor_learning_artifact_events_action UNIQUE (artifact_id, client_action_id),
  CONSTRAINT fk_tutor_learning_artifact_event_scope
    FOREIGN KEY (artifact_id, user_id, conversation_id, teaching_session_id)
    REFERENCES tutor_learning_artifacts(id, user_id, conversation_id, teaching_session_id)
    ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_learning_artifact_event_versions CHECK (
    (event_sequence = 1 AND event_kind = 'created' AND from_version IS NULL AND to_version = 1)
    OR (
      event_sequence > 1 AND event_kind <> 'created'
      AND from_version IS NOT NULL AND to_version = from_version + 1
    )
  ),
  CONSTRAINT chk_tutor_learning_artifact_event_action_shape CHECK (
    (
      event_kind = 'action'
      AND action_kind IS NOT NULL AND client_action_id IS NOT NULL AND request_hash IS NOT NULL
    )
    OR (
      event_kind <> 'action'
      AND action_kind IS NULL AND client_action_id IS NULL
    )
  )
);

CREATE TABLE IF NOT EXISTS tutor_learning_artifact_references (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  reference_index integer NOT NULL CHECK (reference_index BETWEEN 0 AND 11),
  reference_kind text NOT NULL CHECK (reference_kind IN (
    'lesson_document', 'exercise_version', 'attempt_result', 'review_session',
    'teaching_checkpoint', 'source_citation', 'artifact'
  )),
  reference_id text NOT NULL CHECK (char_length(reference_id) BETWEEN 1 AND 160),
  reference_version integer CHECK (reference_version IS NULL OR reference_version >= 1),
  content_hash text CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$'),
  label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 240),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_artifact_references_index UNIQUE (artifact_id, reference_index),
  CONSTRAINT fk_tutor_learning_artifact_reference_scope
    FOREIGN KEY (artifact_id, user_id, conversation_id, teaching_session_id)
    REFERENCES tutor_learning_artifacts(id, user_id, conversation_id, teaching_session_id)
    ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_learning_artifact_attempt_links (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  artifact_version integer NOT NULL CHECK (artifact_version >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_learning_artifact_attempt_links_attempt UNIQUE (artifact_id, attempt_id),
  CONSTRAINT fk_tutor_learning_artifact_attempt_link_scope
    FOREIGN KEY (artifact_id, user_id, conversation_id, teaching_session_id, learning_track_id)
    REFERENCES tutor_learning_artifacts(
      id, user_id, conversation_id, teaching_session_id, learning_track_id
    )
    ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_learning_artifact_attempt_link_attempt
    FOREIGN KEY (attempt_id, user_id, learning_track_id)
    REFERENCES tutor_exercise_attempts(id, user_id, track_id) ON DELETE RESTRICT
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_learning_artifacts'::regclass
      AND conname = 'uq_tutor_learning_artifacts_exact_scope'
  ) THEN
    ALTER TABLE tutor_learning_artifacts
      ADD CONSTRAINT uq_tutor_learning_artifacts_exact_scope
      UNIQUE (id, user_id, conversation_id, teaching_session_id, learning_track_id);
  END IF;
END $$;

ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS fk_tutor_learning_artifact_active_attempt;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT fk_tutor_learning_artifact_active_attempt
  FOREIGN KEY (active_attempt_id, user_id, learning_track_id, knowledge_key)
  REFERENCES tutor_exercise_attempts(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT;

ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifact_terminal;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT chk_tutor_learning_artifact_terminal CHECK (
    (state IN ('completed', 'failed', 'cancelled', 'superseded')) = (terminal_at IS NOT NULL)
    AND (
      state NOT IN ('completed', 'failed', 'cancelled', 'superseded')
      OR allowed_actions_json = '[]'::jsonb
    )
  );

ALTER TABLE tutor_learning_artifact_events
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifact_event_versions;
ALTER TABLE tutor_learning_artifact_events
  ADD CONSTRAINT chk_tutor_learning_artifact_event_versions CHECK (
    (event_sequence = 1 AND event_kind = 'created' AND from_version IS NULL AND to_version = 1)
    OR (
      event_sequence > 1 AND event_kind <> 'created'
      AND from_version IS NOT NULL AND to_version = from_version + 1
    )
  );
ALTER TABLE tutor_learning_artifact_events
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifact_event_action_shape;
ALTER TABLE tutor_learning_artifact_events
  ADD CONSTRAINT chk_tutor_learning_artifact_event_action_shape CHECK (
    (
      event_kind = 'action'
      AND action_kind IS NOT NULL AND client_action_id IS NOT NULL AND request_hash IS NOT NULL
    )
    OR (
      event_kind <> 'action'
      AND action_kind IS NULL AND client_action_id IS NULL
    )
  );

ALTER TABLE tutor_learning_artifact_attempt_links
  DROP CONSTRAINT IF EXISTS fk_tutor_learning_artifact_attempt_link_scope;
ALTER TABLE tutor_learning_artifact_attempt_links
  ADD CONSTRAINT fk_tutor_learning_artifact_attempt_link_scope
  FOREIGN KEY (artifact_id, user_id, conversation_id, teaching_session_id, learning_track_id)
  REFERENCES tutor_learning_artifacts(
    id, user_id, conversation_id, teaching_session_id, learning_track_id
  ) ON DELETE RESTRICT;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM tutor_learning_artifact_attempt_links AS links
    JOIN tutor_learning_artifacts AS artifacts ON artifacts.id = links.artifact_id
    JOIN tutor_exercise_attempts AS attempts ON attempts.id = links.attempt_id
    WHERE artifacts.knowledge_key IS DISTINCT FROM attempts.knowledge_key
  ) THEN
    RAISE EXCEPTION 'Existing Learning Artifact Attempt link scope is mismatched'
      USING ERRCODE = '23514';
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tutor_learning_artifact_events_artifact
  ON tutor_learning_artifact_events(artifact_id, event_sequence);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_artifact_references_artifact
  ON tutor_learning_artifact_references(artifact_id, reference_index);
CREATE INDEX IF NOT EXISTS idx_tutor_learning_artifact_attempt_links_attempt
  ON tutor_learning_artifact_attempt_links(user_id, attempt_id);

CREATE OR REPLACE FUNCTION tutor_learning_artifact_attempt_owner_matches(
  target_user_id uuid,
  target_conversation_id uuid,
  target_track_id uuid,
  target_knowledge_key text,
  target_teaching_session_id uuid,
  target_owner_kind text,
  target_owner_id uuid,
  target_attempt_id uuid
)
RETURNS boolean AS $$
DECLARE
  attempt_row tutor_exercise_attempts%ROWTYPE;
  session_assignment_id uuid;
BEGIN
  SELECT * INTO attempt_row
  FROM tutor_exercise_attempts
  WHERE id = target_attempt_id
    AND user_id = target_user_id
    AND track_id = target_track_id
    AND knowledge_key = target_knowledge_key;
  IF attempt_row.id IS NULL THEN RETURN false; END IF;

  SELECT lesson_assignment_id INTO session_assignment_id
  FROM tutor_teaching_sessions
  WHERE id = target_teaching_session_id
    AND user_id = target_user_id
    AND conversation_id = target_conversation_id
    AND track_id = target_track_id
    AND knowledge_key = target_knowledge_key;
  IF session_assignment_id IS NULL THEN RETURN false; END IF;

  IF target_owner_kind = 'lesson_gate' THEN
    RETURN attempt_row.attempt_type IN ('run', 'submit')
      AND attempt_row.lesson_assignment_id = session_assignment_id
      AND EXISTS (
        SELECT 1
        FROM tutor_lesson_gate_states AS states
        WHERE states.id = target_owner_id
          AND states.user_id = target_user_id
          AND states.track_id = target_track_id
          AND states.knowledge_key = target_knowledge_key
          AND states.lesson_assignment_id = session_assignment_id
          AND states.gate_binding_id = attempt_row.gate_binding_id
      );
  ELSIF target_owner_kind = 'review_item' THEN
    RETURN attempt_row.attempt_type = 'review_submit'
      AND attempt_row.review_item_id = target_owner_id
      AND EXISTS (
        SELECT 1
        FROM tutor_review_items AS items
        WHERE items.id = target_owner_id
          AND items.user_id = target_user_id
          AND items.track_id = target_track_id
          AND items.knowledge_key = target_knowledge_key
          AND items.session_id = attempt_row.review_session_id
      );
  ELSIF target_owner_kind = 'teaching_practice' THEN
    RETURN attempt_row.attempt_type IN ('run', 'submit')
      AND attempt_row.lesson_assignment_id = session_assignment_id;
  END IF;

  -- Learning Item Bank authority is owned by Child 11. Until that immutable
  -- owner exists, do not counterfeit it with a Teaching checkpoint identity.
  RETURN false;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_artifact_owner_scope()
RETURNS trigger AS $$
DECLARE
  session_row tutor_teaching_sessions%ROWTYPE;
  gate_row tutor_lesson_gate_states%ROWTYPE;
  review_item_row tutor_review_items%ROWTYPE;
  review_session_row tutor_review_sessions%ROWTYPE;
BEGIN
  SELECT * INTO session_row
  FROM tutor_teaching_sessions
  WHERE id = NEW.teaching_session_id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND track_id = NEW.learning_track_id
    AND knowledge_key = NEW.knowledge_key;
  IF session_row.id IS NULL
     OR session_row.current_checkpoint_id IS DISTINCT FROM NEW.checkpoint_id
     OR session_row.track_version <> NEW.track_version
     OR session_row.progress_version <> NEW.progress_version
     OR session_row.assignment_version <> NEW.assignment_version
     OR session_row.status NOT IN ('active', 'paused') THEN
    RAISE EXCEPTION 'Learning Artifact teaching authority is stale or mismatched'
      USING ERRCODE = '23514';
  END IF;

  IF NEW.turn_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM tutor_run_teaching_scopes AS scopes
    WHERE scopes.run_id = NEW.turn_id
      AND scopes.user_id = NEW.user_id
      AND scopes.conversation_id = NEW.conversation_id
      AND scopes.teaching_session_id = NEW.teaching_session_id
      AND scopes.checkpoint_id = NEW.checkpoint_id
      AND scopes.track_id = NEW.learning_track_id
      AND scopes.knowledge_key = NEW.knowledge_key
      AND scopes.track_version = NEW.track_version
      AND scopes.progress_version = NEW.progress_version
      AND scopes.assignment_version = NEW.assignment_version
  ) THEN
    RAISE EXCEPTION 'Learning Artifact Turn scope is stale or mismatched'
      USING ERRCODE = '23514';
  END IF;

  IF NEW.active_attempt_id IS NOT NULL AND NOT tutor_learning_artifact_attempt_owner_matches(
    NEW.user_id,
    NEW.conversation_id,
    NEW.learning_track_id,
    NEW.knowledge_key,
    NEW.teaching_session_id,
    NEW.owner_kind,
    NEW.owner_id,
    NEW.active_attempt_id
  ) THEN
    RAISE EXCEPTION 'Learning Artifact active Attempt owner scope is mismatched'
      USING ERRCODE = '23514';
  END IF;

  IF NEW.owner_kind = 'lesson_gate' THEN
    SELECT * INTO gate_row
    FROM tutor_lesson_gate_states
    WHERE id = NEW.owner_id
      AND user_id = NEW.user_id
      AND track_id = NEW.learning_track_id
      AND knowledge_key = NEW.knowledge_key
      AND lesson_assignment_id = session_row.lesson_assignment_id;
    IF gate_row.id IS NULL
       OR gate_row.version <> NEW.owner_version
       OR NEW.owner_context_version IS NOT NULL THEN
      RAISE EXCEPTION 'Learning Artifact Lesson Gate owner is stale or mismatched'
        USING ERRCODE = '23514';
    END IF;
  ELSIF NEW.owner_kind = 'review_item' THEN
    SELECT * INTO review_item_row
    FROM tutor_review_items
    WHERE id = NEW.owner_id
      AND user_id = NEW.user_id
      AND track_id = NEW.learning_track_id
      AND knowledge_key = NEW.knowledge_key;
    IF review_item_row.id IS NULL OR review_item_row.version <> NEW.owner_version THEN
      RAISE EXCEPTION 'Learning Artifact Review Item owner is stale or mismatched'
        USING ERRCODE = '23514';
    END IF;
    SELECT * INTO review_session_row
    FROM tutor_review_sessions
    WHERE id = review_item_row.session_id
      AND user_id = NEW.user_id
      AND track_id = NEW.learning_track_id
      AND knowledge_key = NEW.knowledge_key;
    IF review_session_row.id IS NULL
       OR NEW.owner_context_version IS NULL
       OR review_session_row.version <> NEW.owner_context_version THEN
      RAISE EXCEPTION 'Learning Artifact Review Session owner context is stale or mismatched'
        USING ERRCODE = '23514';
    END IF;
  ELSIF NEW.owner_kind = 'teaching_practice' THEN
    IF NEW.owner_id IS DISTINCT FROM NEW.checkpoint_id
       OR NEW.owner_version <> session_row.version
       OR NEW.owner_context_version IS DISTINCT FROM session_row.version THEN
      RAISE EXCEPTION 'Learning Artifact teaching owner is stale or mismatched'
        USING ERRCODE = '23514';
    END IF;
  ELSIF NEW.owner_kind = 'learning_item' THEN
    RAISE EXCEPTION 'Learning Artifact Learning Item owner is not available'
      USING ERRCODE = '23514';
  ELSE
    RAISE EXCEPTION 'Learning Artifact owner kind is invalid' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_artifact_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Learning Artifact cannot be deleted outside an authorized purge'
      USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id
     OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.conversation_id IS DISTINCT FROM NEW.conversation_id
     OR OLD.turn_id IS DISTINCT FROM NEW.turn_id
     OR OLD.learning_track_id IS DISTINCT FROM NEW.learning_track_id
     OR OLD.knowledge_key IS DISTINCT FROM NEW.knowledge_key
     OR OLD.teaching_session_id IS DISTINCT FROM NEW.teaching_session_id
     OR OLD.checkpoint_id IS DISTINCT FROM NEW.checkpoint_id
     OR OLD.track_version IS DISTINCT FROM NEW.track_version
     OR OLD.progress_version IS DISTINCT FROM NEW.progress_version
     OR OLD.assignment_version IS DISTINCT FROM NEW.assignment_version
     OR OLD.owner_kind IS DISTINCT FROM NEW.owner_kind
     OR OLD.owner_id IS DISTINCT FROM NEW.owner_id
     OR OLD.artifact_schema_version IS DISTINCT FROM NEW.artifact_schema_version
     OR OLD.artifact_kind IS DISTINCT FROM NEW.artifact_kind
     OR OLD.purpose IS DISTINCT FROM NEW.purpose
     OR OLD.blocking IS DISTINCT FROM NEW.blocking
     OR OLD.title IS DISTINCT FROM NEW.title
     OR OLD.instruction_markdown IS DISTINCT FROM NEW.instruction_markdown
     OR OLD.difficulty IS DISTINCT FROM NEW.difficulty
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Learning Artifact identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('completed', 'failed', 'cancelled', 'superseded') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal Learning Artifact is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.version <> OLD.version + 1 THEN
    RAISE EXCEPTION 'Learning Artifact version must advance exactly once' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = NEW.state THEN RETURN NEW; END IF;
  IF OLD.state = 'pending' AND NEW.state IN ('ready', 'failed', 'cancelled', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.state = 'ready' AND NEW.state IN ('active', 'running', 'completed', 'failed', 'cancelled', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.state = 'active' AND NEW.state IN ('running', 'completed', 'failed', 'cancelled', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('active', 'completed', 'failed', 'cancelled', 'superseded') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Learning Artifact lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_artifact_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Learning Artifact evidence rows are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_learning_artifact_attempt_link_scope()
RETURNS trigger AS $$
DECLARE
  artifact_row tutor_learning_artifacts%ROWTYPE;
BEGIN
  SELECT * INTO artifact_row
  FROM tutor_learning_artifacts
  WHERE id = NEW.artifact_id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND teaching_session_id = NEW.teaching_session_id
    AND learning_track_id = NEW.learning_track_id;
  IF artifact_row.id IS NULL
     OR NEW.artifact_version <> artifact_row.version
     OR NOT tutor_learning_artifact_attempt_owner_matches(
       artifact_row.user_id,
       artifact_row.conversation_id,
       artifact_row.learning_track_id,
       artifact_row.knowledge_key,
       artifact_row.teaching_session_id,
       artifact_row.owner_kind,
       artifact_row.owner_id,
       NEW.attempt_id
     ) THEN
    RAISE EXCEPTION 'Learning Artifact Attempt link scope is mismatched'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_learning_artifacts_owner_scope ON tutor_learning_artifacts;
CREATE TRIGGER trg_tutor_learning_artifacts_owner_scope
BEFORE INSERT OR UPDATE ON tutor_learning_artifacts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_artifact_owner_scope();

DROP TRIGGER IF EXISTS trg_tutor_learning_artifacts_lifecycle ON tutor_learning_artifacts;
CREATE TRIGGER trg_tutor_learning_artifacts_lifecycle
BEFORE UPDATE OR DELETE ON tutor_learning_artifacts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_artifact_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_learning_artifacts_updated_at ON tutor_learning_artifacts;
CREATE TRIGGER trg_tutor_learning_artifacts_updated_at
BEFORE UPDATE ON tutor_learning_artifacts
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_learning_artifact_events_immutable ON tutor_learning_artifact_events;
CREATE TRIGGER trg_tutor_learning_artifact_events_immutable
BEFORE UPDATE OR DELETE ON tutor_learning_artifact_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_artifact_append_only();

DROP TRIGGER IF EXISTS trg_tutor_learning_artifact_references_immutable ON tutor_learning_artifact_references;
CREATE TRIGGER trg_tutor_learning_artifact_references_immutable
BEFORE UPDATE OR DELETE ON tutor_learning_artifact_references
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_artifact_append_only();

DROP TRIGGER IF EXISTS trg_tutor_learning_artifact_attempt_links_immutable ON tutor_learning_artifact_attempt_links;
CREATE TRIGGER trg_tutor_learning_artifact_attempt_links_immutable
BEFORE UPDATE OR DELETE ON tutor_learning_artifact_attempt_links
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_artifact_append_only();

DROP TRIGGER IF EXISTS trg_tutor_learning_artifact_attempt_links_scope
  ON tutor_learning_artifact_attempt_links;
CREATE TRIGGER trg_tutor_learning_artifact_attempt_links_scope
BEFORE INSERT OR UPDATE ON tutor_learning_artifact_attempt_links
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_artifact_attempt_link_scope();

ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS tutor_conversation_events_item_kind_check;
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_events_item_kind;
ALTER TABLE tutor_conversation_events
  ADD CONSTRAINT chk_tutor_conversation_events_item_kind CHECK (
    item_kind IS NULL OR item_kind IN (
      'message', 'process', 'elicitation', 'approval', 'error', 'artifact'
    )
  );
-- Reassert the final shape idempotently; fragment 110 already admits v3 before
-- this artifact fragment executes during repeat bootstrap.
ALTER TABLE tutor_conversation_events
  ALTER COLUMN projection_version SET DEFAULT 'tutor_conversation_event_v3';
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS tutor_conversation_events_projection_version_check;
ALTER TABLE tutor_conversation_events
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_events_projection_version;
ALTER TABLE tutor_conversation_events
  ADD CONSTRAINT chk_tutor_conversation_events_projection_version CHECK (
    projection_version IN (
      'tutor_conversation_event_v1', 'tutor_conversation_event_v2',
      'tutor_conversation_event_v3'
    )
  );
