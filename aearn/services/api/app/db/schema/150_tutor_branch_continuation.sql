-- Child 02 durable clarification branches and continuation scheduling authority.
-- Timer/terminal producers persist intents only; provider dispatch remains a later,
-- separately fenced consumer of the deterministic priority arbiter.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_run_teaching_scopes'::regclass
      AND conname = 'uq_tutor_run_teaching_scopes_branch_scope'
  ) THEN
    ALTER TABLE tutor_run_teaching_scopes
      ADD CONSTRAINT uq_tutor_run_teaching_scopes_branch_scope
      UNIQUE (
        run_id, user_id, conversation_id, teaching_session_id,
        checkpoint_id, track_id, knowledge_key
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_run_teaching_scopes'::regclass
      AND conname = 'uq_tutor_run_teaching_scopes_branch_session_scope'
  ) THEN
    ALTER TABLE tutor_run_teaching_scopes
      ADD CONSTRAINT uq_tutor_run_teaching_scopes_branch_session_scope
      UNIQUE (
        run_id, user_id, conversation_id, teaching_session_id,
        track_id, knowledge_key
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_learning_artifacts'::regclass
      AND conname = 'uq_tutor_learning_artifacts_branch_scope'
  ) THEN
    ALTER TABLE tutor_learning_artifacts
      ADD CONSTRAINT uq_tutor_learning_artifacts_branch_scope
      UNIQUE (
        id, user_id, conversation_id, teaching_session_id,
        checkpoint_id, learning_track_id, knowledge_key
      );
  END IF;
END $$;

CREATE OR REPLACE FUNCTION tutor_teaching_checkpoint_descends_from(
  checkpoint_id_value uuid,
  ancestor_checkpoint_id_value uuid,
  teaching_session_id_value uuid,
  user_id_value uuid,
  conversation_id_value uuid
) RETURNS boolean AS $$
  WITH RECURSIVE lineage AS (
    SELECT checkpoints.id, checkpoints.predecessor_checkpoint_id
    FROM tutor_teaching_session_checkpoints AS checkpoints
    WHERE checkpoints.id = checkpoint_id_value
      AND checkpoints.teaching_session_id = teaching_session_id_value
      AND checkpoints.user_id = user_id_value
      AND checkpoints.conversation_id = conversation_id_value
    UNION ALL
    SELECT predecessor.id, predecessor.predecessor_checkpoint_id
    FROM tutor_teaching_session_checkpoints AS predecessor
    JOIN lineage ON lineage.predecessor_checkpoint_id = predecessor.id
    WHERE predecessor.teaching_session_id = teaching_session_id_value
      AND predecessor.user_id = user_id_value
      AND predecessor.conversation_id = conversation_id_value
  )
  SELECT EXISTS (
    SELECT 1 FROM lineage WHERE id = ancestor_checkpoint_id_value
  );
$$ LANGUAGE sql STABLE;

CREATE TABLE IF NOT EXISTS tutor_conversation_branches (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (
    knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  artifact_id uuid NOT NULL,
  predecessor_branch_id uuid,
  depth smallint NOT NULL DEFAULT 1 CHECK (depth = 1),
  state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'resolved')),
  current_event_id uuid NOT NULL,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  round_count integer NOT NULL DEFAULT 1 CHECK (round_count BETWEEN 1 AND 100),
  latest_disposition text CHECK (
    latest_disposition IS NULL OR latest_disposition IN (
      'answer_and_refocus', 'offer_switch', 'confirmed_switch'
    )
  ),
  opened_turn_id uuid NOT NULL,
  opened_message_id uuid NOT NULL,
  opened_input_revision integer NOT NULL CHECK (opened_input_revision >= 1),
  resolved_turn_id uuid,
  resolved_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversation_branches_id_scope
    UNIQUE (id, user_id, conversation_id, artifact_id),
  CONSTRAINT uq_tutor_conversation_branches_predecessor
    UNIQUE (predecessor_branch_id),
  CONSTRAINT fk_tutor_conversation_branch_artifact_scope
    FOREIGN KEY (
      artifact_id, user_id, conversation_id, teaching_session_id,
      checkpoint_id, learning_track_id, knowledge_key
    ) REFERENCES tutor_learning_artifacts(
      id, user_id, conversation_id, teaching_session_id,
      checkpoint_id, learning_track_id, knowledge_key
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_conversation_branch_open_input
    FOREIGN KEY (opened_turn_id, opened_message_id, opened_input_revision)
    REFERENCES tutor_run_input_events(run_id, message_id, input_revision)
    ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_conversation_branch_open_teaching_scope
    FOREIGN KEY (
      opened_turn_id, user_id, conversation_id, teaching_session_id,
      learning_track_id, knowledge_key
    ) REFERENCES tutor_run_teaching_scopes(
      run_id, user_id, conversation_id, teaching_session_id,
      track_id, knowledge_key
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_conversation_branch_resolved_turn
    FOREIGN KEY (resolved_turn_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_conversation_branch_resolution CHECK (
    (state = 'active' AND resolved_turn_id IS NULL AND resolved_at IS NULL)
    OR
    (state = 'resolved' AND resolved_turn_id IS NOT NULL AND resolved_at IS NOT NULL
      AND latest_disposition IS NOT NULL)
  )
);

ALTER TABLE tutor_conversation_branches
  DROP CONSTRAINT IF EXISTS fk_tutor_conversation_branch_open_teaching_scope;
ALTER TABLE tutor_conversation_branches
  ADD CONSTRAINT fk_tutor_conversation_branch_open_teaching_scope
  FOREIGN KEY (
    opened_turn_id, user_id, conversation_id, teaching_session_id,
    learning_track_id, knowledge_key
  ) REFERENCES tutor_run_teaching_scopes(
    run_id, user_id, conversation_id, teaching_session_id,
    track_id, knowledge_key
  ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE tutor_conversation_branches
  DROP CONSTRAINT IF EXISTS fk_tutor_conversation_branch_predecessor;
ALTER TABLE tutor_conversation_branches
  ADD CONSTRAINT fk_tutor_conversation_branch_predecessor
  FOREIGN KEY (predecessor_branch_id, user_id, conversation_id, artifact_id)
  REFERENCES tutor_conversation_branches(id, user_id, conversation_id, artifact_id)
  ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_conversation_branches_one_active_anchor
  ON tutor_conversation_branches(artifact_id)
  WHERE state = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_conversation_branches_snapshot
  ON tutor_conversation_branches(conversation_id, created_at, id);

CREATE TABLE IF NOT EXISTS tutor_conversation_branch_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  branch_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  artifact_id uuid NOT NULL,
  predecessor_event_id uuid,
  branch_version integer NOT NULL CHECK (branch_version >= 1),
  event_key text NOT NULL CHECK (
    event_key ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,199}$'
  ),
  event_kind text NOT NULL CHECK (
    event_kind IN ('opened', 'turn_bound', 'response_recorded')
  ),
  message_classification text NOT NULL CHECK (
    message_classification IN ('normal', 'control')
  ),
  control_kind text CHECK (
    control_kind IS NULL OR control_kind IN (
      'request_topic_switch', 'confirm_topic_switch', 'cancel_topic_switch'
    )
  ),
  disposition text CHECK (
    disposition IS NULL OR disposition IN (
      'answer_and_refocus', 'offer_switch', 'confirmed_switch'
    )
  ),
  source_turn_id uuid NOT NULL,
  source_message_id uuid NOT NULL,
  source_input_revision integer NOT NULL CHECK (source_input_revision >= 1),
  response_message_id uuid,
  assistance_kind text NOT NULL DEFAULT 'none' CHECK (
    assistance_kind IN ('none', 'hint', 'direct_answer')
  ),
  assistance_receipt_kind text CHECK (
    assistance_receipt_kind IS NULL OR assistance_receipt_kind IN (
      'exercise_hint', 'review_hint', 'teaching_action'
    )
  ),
  assistance_receipt_id uuid,
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversation_branch_events_scope
    UNIQUE (id, branch_id, user_id, conversation_id, artifact_id),
  CONSTRAINT uq_tutor_conversation_branch_events_version
    UNIQUE (branch_id, branch_version),
  CONSTRAINT uq_tutor_conversation_branch_events_key
    UNIQUE (branch_id, event_key),
  CONSTRAINT uq_tutor_conversation_branch_events_successor
    UNIQUE (predecessor_event_id),
  CONSTRAINT fk_tutor_conversation_branch_event_branch
    FOREIGN KEY (branch_id, user_id, conversation_id, artifact_id)
    REFERENCES tutor_conversation_branches(id, user_id, conversation_id, artifact_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_conversation_branch_event_predecessor
    FOREIGN KEY (
      predecessor_event_id, branch_id, user_id, conversation_id, artifact_id
    ) REFERENCES tutor_conversation_branch_events(
      id, branch_id, user_id, conversation_id, artifact_id
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_conversation_branch_event_source_input
    FOREIGN KEY (source_turn_id, source_message_id, source_input_revision)
    REFERENCES tutor_run_input_events(run_id, message_id, input_revision)
    ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_conversation_branch_event_response_message
    FOREIGN KEY (response_message_id, conversation_id)
    REFERENCES tutor_messages(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_conversation_branch_event_lineage CHECK (
    (branch_version = 1 AND event_kind = 'opened' AND predecessor_event_id IS NULL)
    OR
    (branch_version > 1 AND event_kind <> 'opened' AND predecessor_event_id IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_conversation_branch_event_control CHECK (
    (message_classification = 'normal' AND control_kind IS NULL)
    OR
    (message_classification = 'control' AND control_kind IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_conversation_branch_event_response CHECK (
    (
      event_kind IN ('opened', 'turn_bound')
      AND disposition IS NULL AND response_message_id IS NULL
      AND assistance_kind = 'none'
      AND assistance_receipt_kind IS NULL AND assistance_receipt_id IS NULL
    )
    OR
    (
      event_kind = 'response_recorded'
      AND disposition IS NOT NULL AND response_message_id IS NOT NULL
      AND (
        (assistance_kind = 'none'
          AND assistance_receipt_kind IS NULL AND assistance_receipt_id IS NULL)
        OR
        (assistance_kind <> 'none'
          AND assistance_receipt_kind IS NOT NULL AND assistance_receipt_id IS NOT NULL)
      )
    )
  )
);

ALTER TABLE tutor_conversation_branches
  DROP CONSTRAINT IF EXISTS fk_tutor_conversation_branch_current_event;
ALTER TABLE tutor_conversation_branches
  ADD CONSTRAINT fk_tutor_conversation_branch_current_event
  FOREIGN KEY (current_event_id, id, user_id, conversation_id, artifact_id)
  REFERENCES tutor_conversation_branch_events(
    id, branch_id, user_id, conversation_id, artifact_id
  ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX IF NOT EXISTS idx_tutor_conversation_branch_events_lineage
  ON tutor_conversation_branch_events(branch_id, branch_version);

CREATE TABLE IF NOT EXISTS tutor_run_branch_scopes (
  run_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  branch_id uuid NOT NULL,
  artifact_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (
    knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  branch_version integer NOT NULL CHECK (branch_version >= 1),
  branch_round integer NOT NULL CHECK (branch_round BETWEEN 1 AND 100),
  source_message_id uuid NOT NULL,
  source_input_revision integer NOT NULL CHECK (source_input_revision >= 1),
  message_classification text NOT NULL CHECK (
    message_classification IN ('normal', 'control')
  ),
  control_kind text CHECK (
    control_kind IS NULL OR control_kind IN (
      'request_topic_switch', 'confirm_topic_switch', 'cancel_topic_switch'
    )
  ),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_run_branch_scopes_exact
    UNIQUE (run_id, branch_id, user_id, conversation_id, artifact_id),
  CONSTRAINT uq_tutor_run_branch_scopes_round
    UNIQUE (branch_id, branch_round),
  CONSTRAINT fk_tutor_run_branch_scope_teaching_scope
    FOREIGN KEY (
      run_id, user_id, conversation_id, teaching_session_id,
      checkpoint_id, learning_track_id, knowledge_key
    ) REFERENCES tutor_run_teaching_scopes(
      run_id, user_id, conversation_id, teaching_session_id,
      checkpoint_id, track_id, knowledge_key
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_run_branch_scope_branch
    FOREIGN KEY (branch_id, user_id, conversation_id, artifact_id)
    REFERENCES tutor_conversation_branches(id, user_id, conversation_id, artifact_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_run_branch_scope_source_input
    FOREIGN KEY (run_id, source_message_id, source_input_revision)
    REFERENCES tutor_run_input_events(run_id, message_id, input_revision)
    ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_run_branch_scope_control CHECK (
    (message_classification = 'normal' AND control_kind IS NULL)
    OR
    (message_classification = 'control' AND control_kind IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_run_branch_scopes_branch
  ON tutor_run_branch_scopes(branch_id, branch_round, run_id);

CREATE TABLE IF NOT EXISTS tutor_conversation_branch_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  branch_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  artifact_id uuid NOT NULL,
  run_id uuid NOT NULL,
  branch_round integer NOT NULL CHECK (branch_round BETWEEN 1 AND 100),
  item_sequence integer NOT NULL CHECK (item_sequence BETWEEN 1 AND 400),
  item_kind text NOT NULL CHECK (item_kind IN ('message', 'process')),
  item_id uuid NOT NULL,
  item_role text NOT NULL CHECK (item_role IN ('learner', 'tutor', 'process')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_conversation_branch_items_sequence
    UNIQUE (branch_id, item_sequence),
  CONSTRAINT uq_tutor_conversation_branch_items_public_item
    UNIQUE (conversation_id, item_kind, item_id),
  CONSTRAINT fk_tutor_conversation_branch_item_branch
    FOREIGN KEY (branch_id, user_id, conversation_id, artifact_id)
    REFERENCES tutor_conversation_branches(id, user_id, conversation_id, artifact_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_conversation_branch_item_run_scope
    FOREIGN KEY (run_id, branch_id, user_id, conversation_id, artifact_id)
    REFERENCES tutor_run_branch_scopes(
      run_id, branch_id, user_id, conversation_id, artifact_id
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT chk_tutor_conversation_branch_item_kind_role CHECK (
    (item_kind = 'message' AND item_role IN ('learner', 'tutor'))
    OR
    (item_kind = 'process' AND item_role = 'process')
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_conversation_branch_items_grouping
  ON tutor_conversation_branch_items(branch_id, item_sequence);

CREATE TABLE IF NOT EXISTS tutor_continuation_intents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (
    knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  artifact_id uuid NOT NULL,
  branch_id uuid,
  source_kind text NOT NULL CHECK (source_kind IN (
    'learner_message', 'explicit_artifact_action', 'expected_interactive_event',
    'static_display_timer', 'background_continuation'
  )),
  source_id text NOT NULL CHECK (char_length(source_id) BETWEEN 1 AND 160),
  source_version integer NOT NULL CHECK (source_version >= 1),
  priority integer NOT NULL CHECK (priority IN (100, 200, 300, 400, 500)),
  session_version integer NOT NULL CHECK (session_version >= 1),
  artifact_version integer NOT NULL CHECK (artifact_version >= 1),
  track_version integer NOT NULL CHECK (track_version >= 1),
  progress_version integer NOT NULL CHECK (progress_version >= 1),
  assignment_version integer NOT NULL CHECK (assignment_version >= 1),
  idempotency_key text NOT NULL CHECK (
    idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,159}$'
  ),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  state text NOT NULL DEFAULT 'pending' CHECK (
    state IN ('pending', 'claimed', 'consumed', 'cancelled', 'superseded')
  ),
  current_event_id uuid NOT NULL,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  not_before timestamptz NOT NULL DEFAULT now(),
  claimed_by text CHECK (claimed_by IS NULL OR char_length(claimed_by) BETWEEN 1 AND 160),
  claim_generation integer NOT NULL DEFAULT 0 CHECK (claim_generation >= 0),
  claim_expires_at timestamptz,
  consumed_run_id uuid,
  terminal_reason text CHECK (
    terminal_reason IS NULL OR char_length(terminal_reason) BETWEEN 1 AND 160
  ),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_continuation_intents_id_scope
    UNIQUE (id, user_id, conversation_id, artifact_id),
  CONSTRAINT uq_tutor_continuation_intents_idempotency
    UNIQUE (user_id, conversation_id, idempotency_key),
  CONSTRAINT uq_tutor_continuation_intents_source
    UNIQUE (conversation_id, artifact_id, source_kind, source_id, source_version),
  CONSTRAINT uq_tutor_continuation_intents_consumed_run
    UNIQUE (consumed_run_id),
  CONSTRAINT fk_tutor_continuation_intent_artifact_scope
    FOREIGN KEY (
      artifact_id, user_id, conversation_id, teaching_session_id,
      checkpoint_id, learning_track_id, knowledge_key
    ) REFERENCES tutor_learning_artifacts(
      id, user_id, conversation_id, teaching_session_id,
      checkpoint_id, learning_track_id, knowledge_key
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_continuation_intent_branch_scope
    FOREIGN KEY (branch_id, user_id, conversation_id, artifact_id)
    REFERENCES tutor_conversation_branches(id, user_id, conversation_id, artifact_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_continuation_intent_consumed_run
    FOREIGN KEY (consumed_run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_continuation_intent_priority CHECK (
    (source_kind = 'learner_message' AND priority = 500)
    OR (source_kind = 'explicit_artifact_action' AND priority = 400)
    OR (source_kind = 'expected_interactive_event' AND priority = 300)
    OR (source_kind = 'static_display_timer' AND priority = 200)
    OR (source_kind = 'background_continuation' AND priority = 100)
  ),
  CONSTRAINT chk_tutor_continuation_intent_branch_shape CHECK (
    (source_kind = 'learner_message' AND branch_id IS NOT NULL)
    OR (source_kind <> 'learner_message' AND branch_id IS NULL)
  ),
  CONSTRAINT chk_tutor_continuation_intent_state_shape CHECK (
    (
      state = 'pending' AND claimed_by IS NULL
      AND claim_expires_at IS NULL AND consumed_run_id IS NULL
      AND terminal_reason IS NULL
    )
    OR
    (
      state = 'claimed' AND claimed_by IS NOT NULL AND claim_generation >= 1
      AND claim_expires_at IS NOT NULL AND consumed_run_id IS NULL
      AND terminal_reason IS NULL
    )
    OR
    (
      state = 'consumed' AND consumed_run_id IS NOT NULL AND terminal_reason IS NULL
      AND (
        (claimed_by IS NULL AND claim_expires_at IS NULL)
        OR
        (claimed_by IS NOT NULL AND claim_generation >= 1 AND claim_expires_at IS NOT NULL)
      )
    )
    OR
    (
      state IN ('cancelled', 'superseded') AND consumed_run_id IS NULL
      AND terminal_reason IS NOT NULL AND claimed_by IS NULL
      AND claim_expires_at IS NULL
    )
  )
);

ALTER TABLE tutor_continuation_intents
  DROP CONSTRAINT IF EXISTS chk_tutor_continuation_intent_state_shape;
ALTER TABLE tutor_continuation_intents
  ADD CONSTRAINT chk_tutor_continuation_intent_state_shape CHECK (
    (
      state = 'pending' AND claimed_by IS NULL
      AND claim_expires_at IS NULL AND consumed_run_id IS NULL
      AND terminal_reason IS NULL
    )
    OR
    (
      state = 'claimed' AND claimed_by IS NOT NULL AND claim_generation >= 1
      AND claim_expires_at IS NOT NULL AND consumed_run_id IS NULL
      AND terminal_reason IS NULL
    )
    OR
    (
      state = 'consumed' AND consumed_run_id IS NOT NULL AND terminal_reason IS NULL
      AND (
        (claimed_by IS NULL AND claim_expires_at IS NULL)
        OR
        (claimed_by IS NOT NULL AND claim_generation >= 1 AND claim_expires_at IS NOT NULL)
      )
    )
    OR
    (
      state IN ('cancelled', 'superseded') AND consumed_run_id IS NULL
      AND terminal_reason IS NOT NULL AND claimed_by IS NULL
      AND claim_expires_at IS NULL
    )
  );

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_continuation_intents_one_claimed_conversation
  ON tutor_continuation_intents(conversation_id)
  WHERE state = 'claimed';
CREATE INDEX IF NOT EXISTS idx_tutor_continuation_intents_priority
  ON tutor_continuation_intents(
    conversation_id, state, priority DESC, not_before, created_at, id
  );

CREATE TABLE IF NOT EXISTS tutor_continuation_intent_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  intent_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  artifact_id uuid NOT NULL,
  predecessor_event_id uuid,
  intent_version integer NOT NULL CHECK (intent_version >= 1),
  event_key text NOT NULL CHECK (
    event_key ~ '^[A-Za-z0-9][A-Za-z0-9._:@-]{0,199}$'
  ),
  event_kind text NOT NULL CHECK (
    event_kind IN ('created', 'claimed', 'released', 'consumed', 'cancelled', 'superseded')
  ),
  state text NOT NULL CHECK (
    state IN ('pending', 'claimed', 'consumed', 'cancelled', 'superseded')
  ),
  claimed_by text CHECK (claimed_by IS NULL OR char_length(claimed_by) BETWEEN 1 AND 160),
  claim_generation integer NOT NULL DEFAULT 0 CHECK (claim_generation >= 0),
  claim_expires_at timestamptz,
  consumed_run_id uuid,
  reason_code text CHECK (reason_code IS NULL OR char_length(reason_code) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_continuation_intent_events_scope
    UNIQUE (id, intent_id, user_id, conversation_id, artifact_id),
  CONSTRAINT uq_tutor_continuation_intent_events_version
    UNIQUE (intent_id, intent_version),
  CONSTRAINT uq_tutor_continuation_intent_events_key
    UNIQUE (intent_id, event_key),
  CONSTRAINT uq_tutor_continuation_intent_events_successor
    UNIQUE (predecessor_event_id),
  CONSTRAINT fk_tutor_continuation_intent_event_intent
    FOREIGN KEY (intent_id, user_id, conversation_id, artifact_id)
    REFERENCES tutor_continuation_intents(id, user_id, conversation_id, artifact_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_continuation_intent_event_predecessor
    FOREIGN KEY (
      predecessor_event_id, intent_id, user_id, conversation_id, artifact_id
    ) REFERENCES tutor_continuation_intent_events(
      id, intent_id, user_id, conversation_id, artifact_id
    ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_continuation_intent_event_consumed_run
    FOREIGN KEY (consumed_run_id, user_id, conversation_id)
    REFERENCES tutor_runs(id, user_id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_continuation_intent_event_lineage CHECK (
    (intent_version = 1 AND event_kind = 'created' AND predecessor_event_id IS NULL)
    OR
    (intent_version > 1 AND event_kind <> 'created' AND predecessor_event_id IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_continuation_intent_event_shape CHECK (
    (
      event_kind = 'created' AND state = 'pending'
      AND claimed_by IS NULL AND claim_generation = 0
      AND claim_expires_at IS NULL AND consumed_run_id IS NULL AND reason_code IS NULL
    )
    OR
    (
      event_kind = 'claimed' AND state = 'claimed'
      AND claimed_by IS NOT NULL AND claim_generation >= 1
      AND claim_expires_at IS NOT NULL AND consumed_run_id IS NULL AND reason_code IS NULL
    )
    OR
    (
      event_kind = 'released' AND state = 'pending'
      AND claimed_by IS NULL AND claim_generation >= 1
      AND claim_expires_at IS NULL AND consumed_run_id IS NULL AND reason_code IS NOT NULL
    )
    OR
    (
      event_kind = 'consumed' AND state = 'consumed'
      AND consumed_run_id IS NOT NULL AND reason_code IS NULL
    )
    OR
    (
      event_kind IN ('cancelled', 'superseded')
      AND state = event_kind AND consumed_run_id IS NULL AND reason_code IS NOT NULL
      AND claimed_by IS NULL AND claim_expires_at IS NULL
    )
  )
);

ALTER TABLE tutor_continuation_intent_events
  DROP CONSTRAINT IF EXISTS chk_tutor_continuation_intent_event_shape;
ALTER TABLE tutor_continuation_intent_events
  ADD CONSTRAINT chk_tutor_continuation_intent_event_shape CHECK (
    (
      event_kind = 'created' AND state = 'pending'
      AND claimed_by IS NULL AND claim_generation = 0
      AND claim_expires_at IS NULL AND consumed_run_id IS NULL AND reason_code IS NULL
    )
    OR
    (
      event_kind = 'claimed' AND state = 'claimed'
      AND claimed_by IS NOT NULL AND claim_generation >= 1
      AND claim_expires_at IS NOT NULL AND consumed_run_id IS NULL AND reason_code IS NULL
    )
    OR
    (
      event_kind = 'released' AND state = 'pending'
      AND claimed_by IS NULL AND claim_generation >= 1
      AND claim_expires_at IS NULL AND consumed_run_id IS NULL AND reason_code IS NOT NULL
    )
    OR
    (
      event_kind = 'consumed' AND state = 'consumed'
      AND consumed_run_id IS NOT NULL AND reason_code IS NULL
      AND (
        (claimed_by IS NULL AND claim_expires_at IS NULL)
        OR
        (claimed_by IS NOT NULL AND claim_generation >= 1 AND claim_expires_at IS NOT NULL)
      )
    )
    OR
    (
      event_kind IN ('cancelled', 'superseded')
      AND state = event_kind AND consumed_run_id IS NULL AND reason_code IS NOT NULL
      AND claimed_by IS NULL AND claim_expires_at IS NULL
    )
  );

ALTER TABLE tutor_continuation_intents
  DROP CONSTRAINT IF EXISTS fk_tutor_continuation_intent_current_event;
ALTER TABLE tutor_continuation_intents
  ADD CONSTRAINT fk_tutor_continuation_intent_current_event
  FOREIGN KEY (current_event_id, id, user_id, conversation_id, artifact_id)
  REFERENCES tutor_continuation_intent_events(
    id, intent_id, user_id, conversation_id, artifact_id
  ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX IF NOT EXISTS idx_tutor_continuation_intent_events_lineage
  ON tutor_continuation_intent_events(intent_id, intent_version);

CREATE OR REPLACE FUNCTION enforce_tutor_branch_root_lifecycle()
RETURNS trigger AS $$
DECLARE
  event_row tutor_conversation_branch_events%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor conversation branch cannot be deleted outside an authorized purge'
      USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id
     OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.conversation_id IS DISTINCT FROM NEW.conversation_id
     OR OLD.learning_track_id IS DISTINCT FROM NEW.learning_track_id
     OR OLD.knowledge_key IS DISTINCT FROM NEW.knowledge_key
     OR OLD.teaching_session_id IS DISTINCT FROM NEW.teaching_session_id
     OR OLD.checkpoint_id IS DISTINCT FROM NEW.checkpoint_id
     OR OLD.artifact_id IS DISTINCT FROM NEW.artifact_id
     OR OLD.predecessor_branch_id IS DISTINCT FROM NEW.predecessor_branch_id
     OR OLD.depth IS DISTINCT FROM NEW.depth
     OR OLD.opened_turn_id IS DISTINCT FROM NEW.opened_turn_id
     OR OLD.opened_message_id IS DISTINCT FROM NEW.opened_message_id
     OR OLD.opened_input_revision IS DISTINCT FROM NEW.opened_input_revision
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Tutor conversation branch identity is immutable'
      USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'resolved' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Resolved Tutor conversation branch is immutable'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.version <> OLD.version + 1 OR NEW.current_event_id = OLD.current_event_id THEN
    RAISE EXCEPTION 'Tutor conversation branch CAS must advance exactly once'
      USING ERRCODE = '23514';
  END IF;
  SELECT * INTO event_row
  FROM tutor_conversation_branch_events
  WHERE id = NEW.current_event_id
    AND branch_id = NEW.id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND artifact_id = NEW.artifact_id
    AND predecessor_event_id = OLD.current_event_id
    AND branch_version = NEW.version;
  IF event_row.id IS NULL THEN
    RAISE EXCEPTION 'Tutor conversation branch event lineage is missing'
      USING ERRCODE = '23514';
  END IF;
  IF event_row.event_kind = 'turn_bound' THEN
    IF NEW.state <> OLD.state OR NEW.round_count <> OLD.round_count + 1
       OR NEW.latest_disposition IS DISTINCT FROM OLD.latest_disposition THEN
      RAISE EXCEPTION 'Tutor conversation branch turn binding is inconsistent'
        USING ERRCODE = '23514';
    END IF;
  ELSIF event_row.event_kind = 'response_recorded' THEN
    IF NEW.latest_disposition IS DISTINCT FROM event_row.disposition
       OR NEW.round_count <> OLD.round_count THEN
      RAISE EXCEPTION 'Tutor conversation branch response projection is inconsistent'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.state = 'resolved' AND (
      NEW.resolved_turn_id IS DISTINCT FROM event_row.source_turn_id
      OR NEW.resolved_at IS DISTINCT FROM event_row.created_at
    ) THEN
      RAISE EXCEPTION 'Tutor conversation branch resolution is inconsistent'
        USING ERRCODE = '23514';
    END IF;
  ELSE
    RAISE EXCEPTION 'Tutor conversation branch update event kind is invalid'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_branch_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor conversation branch evidence is append-only'
    USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_run_branch_scope()
RETURNS trigger AS $$
DECLARE
  branch_row tutor_conversation_branches%ROWTYPE;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Tutor run branch scope is immutable' USING ERRCODE = '23514';
  END IF;
  SELECT * INTO branch_row
  FROM tutor_conversation_branches
  WHERE id = NEW.branch_id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND artifact_id = NEW.artifact_id;
  IF branch_row.id IS NULL OR branch_row.state <> 'active'
     OR branch_row.version <> NEW.branch_version
     OR branch_row.round_count <> NEW.branch_round
     OR branch_row.teaching_session_id <> NEW.teaching_session_id
     OR NOT tutor_teaching_checkpoint_descends_from(
       NEW.checkpoint_id, branch_row.checkpoint_id,
       NEW.teaching_session_id, NEW.user_id, NEW.conversation_id
     )
     OR branch_row.learning_track_id <> NEW.learning_track_id
     OR branch_row.knowledge_key <> NEW.knowledge_key THEN
    RAISE EXCEPTION 'Tutor run branch scope is stale or mismatched'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.control_kind = 'confirm_topic_switch'
     AND branch_row.latest_disposition IS DISTINCT FROM 'offer_switch' THEN
    RAISE EXCEPTION 'Tutor topic switch confirmation has no pending offer'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_branch_item_scope()
RETURNS trigger AS $$
DECLARE
  scope_row tutor_run_branch_scopes%ROWTYPE;
BEGIN
  SELECT * INTO scope_row
  FROM tutor_run_branch_scopes
  WHERE run_id = NEW.run_id
    AND branch_id = NEW.branch_id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND artifact_id = NEW.artifact_id;
  IF scope_row.run_id IS NULL OR scope_row.branch_round <> NEW.branch_round THEN
    RAISE EXCEPTION 'Tutor branch item run scope is mismatched'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.item_kind = 'process' THEN
    IF NEW.item_id <> NEW.run_id OR NOT EXISTS (
      SELECT 1 FROM tutor_run_public_processes
      WHERE run_id = NEW.run_id AND user_id = NEW.user_id
        AND conversation_id = NEW.conversation_id
    ) THEN
      RAISE EXCEPTION 'Tutor branch process item is mismatched'
        USING ERRCODE = '23514';
    END IF;
  ELSIF NEW.item_role = 'learner' THEN
    IF NEW.item_id <> scope_row.source_message_id OR NOT EXISTS (
      SELECT 1 FROM tutor_run_input_events
      WHERE run_id = NEW.run_id AND message_id = NEW.item_id
        AND input_revision = scope_row.source_input_revision
    ) THEN
      RAISE EXCEPTION 'Tutor branch learner message item is mismatched'
        USING ERRCODE = '23514';
    END IF;
  ELSIF NOT EXISTS (
    SELECT 1
    FROM tutor_run_public_processes AS processes
    JOIN tutor_messages AS messages
      ON messages.id = processes.tutor_message_id
     AND messages.conversation_id = processes.conversation_id
    WHERE processes.run_id = NEW.run_id
      AND processes.user_id = NEW.user_id
      AND processes.conversation_id = NEW.conversation_id
      AND messages.id = NEW.item_id
      AND messages.role = 'tutor'
  ) THEN
    RAISE EXCEPTION 'Tutor branch Tutor message item is mismatched'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_continuation_intent_lifecycle()
RETURNS trigger AS $$
DECLARE
  event_row tutor_continuation_intent_events%ROWTYPE;
  artifact_row tutor_learning_artifacts%ROWTYPE;
  session_row tutor_teaching_sessions%ROWTYPE;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor continuation intent cannot be deleted outside an authorized purge'
      USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id
     OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.conversation_id IS DISTINCT FROM NEW.conversation_id
     OR OLD.learning_track_id IS DISTINCT FROM NEW.learning_track_id
     OR OLD.knowledge_key IS DISTINCT FROM NEW.knowledge_key
     OR OLD.teaching_session_id IS DISTINCT FROM NEW.teaching_session_id
     OR OLD.checkpoint_id IS DISTINCT FROM NEW.checkpoint_id
     OR OLD.artifact_id IS DISTINCT FROM NEW.artifact_id
     OR OLD.branch_id IS DISTINCT FROM NEW.branch_id
     OR OLD.source_kind IS DISTINCT FROM NEW.source_kind
     OR OLD.source_id IS DISTINCT FROM NEW.source_id
     OR OLD.source_version IS DISTINCT FROM NEW.source_version
     OR OLD.priority IS DISTINCT FROM NEW.priority
     OR OLD.session_version IS DISTINCT FROM NEW.session_version
     OR OLD.artifact_version IS DISTINCT FROM NEW.artifact_version
     OR OLD.track_version IS DISTINCT FROM NEW.track_version
     OR OLD.progress_version IS DISTINCT FROM NEW.progress_version
     OR OLD.assignment_version IS DISTINCT FROM NEW.assignment_version
     OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
     OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
     OR OLD.not_before IS DISTINCT FROM NEW.not_before
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Tutor continuation intent identity is immutable'
      USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('consumed', 'cancelled', 'superseded') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal Tutor continuation intent is immutable'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.version <> OLD.version + 1 OR NEW.current_event_id = OLD.current_event_id THEN
    RAISE EXCEPTION 'Tutor continuation intent CAS must advance exactly once'
      USING ERRCODE = '23514';
  END IF;
  SELECT * INTO event_row
  FROM tutor_continuation_intent_events
  WHERE id = NEW.current_event_id
    AND intent_id = NEW.id
    AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND artifact_id = NEW.artifact_id
    AND predecessor_event_id = OLD.current_event_id
    AND intent_version = NEW.version
    AND state = NEW.state;
  IF event_row.id IS NULL THEN
    RAISE EXCEPTION 'Tutor continuation intent event lineage is missing'
      USING ERRCODE = '23514';
  END IF;
  IF NOT (
    (OLD.state = 'pending' AND NEW.state IN ('claimed', 'consumed', 'cancelled', 'superseded'))
    OR (OLD.state = 'claimed' AND NEW.state IN ('pending', 'consumed', 'cancelled', 'superseded'))
  ) THEN
    RAISE EXCEPTION 'Tutor continuation intent lifecycle transition is invalid'
      USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'pending' AND NEW.state = 'consumed'
     AND NEW.source_kind <> 'learner_message' THEN
    RAISE EXCEPTION 'Only learner-message continuation may be consumed without a claim'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.state = 'claimed' THEN
    SELECT * INTO artifact_row
    FROM tutor_learning_artifacts
    WHERE id = NEW.artifact_id AND user_id = NEW.user_id
      AND conversation_id = NEW.conversation_id
      AND teaching_session_id = NEW.teaching_session_id
      AND checkpoint_id = NEW.checkpoint_id
      AND learning_track_id = NEW.learning_track_id
      AND knowledge_key = NEW.knowledge_key;
    SELECT * INTO session_row
    FROM tutor_teaching_sessions
    WHERE id = NEW.teaching_session_id AND user_id = NEW.user_id
      AND conversation_id = NEW.conversation_id;
    IF artifact_row.id IS NULL OR session_row.id IS NULL
       OR artifact_row.version <> NEW.artifact_version
       OR (
         artifact_row.state IN ('completed', 'failed', 'cancelled', 'superseded')
         AND (
           NEW.source_kind IN ('learner_message', 'background_continuation')
           OR (
             NEW.source_kind IN ('expected_interactive_event', 'static_display_timer')
             AND NOT tutor_demo_completion_continuation_valid(
               NEW.artifact_id, NEW.user_id, NEW.conversation_id,
               NEW.source_kind, NEW.source_id, NEW.source_version,
               NEW.artifact_version
             )
           )
         )
       )
       OR session_row.status NOT IN ('active', 'paused')
       OR session_row.version < NEW.session_version
       OR (
         NEW.source_kind = 'learner_message'
         AND (
           session_row.version <> NEW.session_version
           OR session_row.current_checkpoint_id <> NEW.checkpoint_id
         )
       )
       OR (
         NEW.source_kind <> 'learner_message'
         AND NOT tutor_teaching_checkpoint_descends_from(
           session_row.current_checkpoint_id, NEW.checkpoint_id,
           NEW.teaching_session_id, NEW.user_id, NEW.conversation_id
         )
       )
       OR (
         NEW.source_kind IN ('static_display_timer', 'background_continuation')
         AND session_row.mode <> 'guided'
       )
       OR session_row.track_version <> NEW.track_version
       OR session_row.progress_version <> NEW.progress_version
       OR session_row.assignment_version <> NEW.assignment_version THEN
      RAISE EXCEPTION 'Tutor continuation intent authority is stale'
        USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
      SELECT 1 FROM tutor_queued_inputs
      WHERE user_id = NEW.user_id AND conversation_id = NEW.conversation_id
        AND state = 'pending'
    ) THEN
      RAISE EXCEPTION 'Pending learner input preempts Tutor continuation intent'
        USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
      SELECT 1 FROM tutor_conversation_branches
      WHERE user_id = NEW.user_id AND conversation_id = NEW.conversation_id
        AND state = 'active'
    ) THEN
      RAISE EXCEPTION 'Active Tutor branch must resolve before mainline continuation'
        USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
      SELECT 1 FROM tutor_runs
      WHERE user_id = NEW.user_id AND conversation_id = NEW.conversation_id
        AND origin = 'interactive' AND terminal_outcome IS NULL
        AND cancelled_at IS NULL AND superseded_by_run_id IS NULL
    ) THEN
      RAISE EXCEPTION 'Tutor conversation already has a publishable foreground Turn'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  IF NEW.state = 'consumed' THEN
    IF NOT EXISTS (
      SELECT 1
      FROM tutor_run_teaching_scopes
      WHERE run_id = NEW.consumed_run_id
        AND user_id = NEW.user_id
        AND conversation_id = NEW.conversation_id
        AND teaching_session_id = NEW.teaching_session_id
        AND track_id = NEW.learning_track_id
        AND knowledge_key = NEW.knowledge_key
        AND (
          (
            NEW.source_kind = 'learner_message'
            AND checkpoint_id = NEW.checkpoint_id
            AND session_version = NEW.session_version
          )
          OR
          (
            NEW.source_kind <> 'learner_message'
            AND session_version >= NEW.session_version
            AND tutor_teaching_checkpoint_descends_from(
              checkpoint_id, NEW.checkpoint_id, NEW.teaching_session_id,
              NEW.user_id, NEW.conversation_id
            )
          )
        )
    ) THEN
      RAISE EXCEPTION 'Tutor continuation consumed Turn scope is mismatched'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.branch_id IS NOT NULL AND NOT EXISTS (
      SELECT 1 FROM tutor_run_branch_scopes
      WHERE run_id = NEW.consumed_run_id AND branch_id = NEW.branch_id
        AND user_id = NEW.user_id AND conversation_id = NEW.conversation_id
        AND artifact_id = NEW.artifact_id
    ) THEN
      RAISE EXCEPTION 'Tutor branch continuation consumed Turn is not branch-scoped'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.branch_id IS NULL AND EXISTS (
      SELECT 1 FROM tutor_run_branch_scopes
      WHERE run_id = NEW.consumed_run_id
    ) THEN
      RAISE EXCEPTION 'Tutor mainline continuation Turn cannot remain in a branch'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_continuation_intent_insert_scope()
RETURNS trigger AS $$
DECLARE
  artifact_row tutor_learning_artifacts%ROWTYPE;
  session_row tutor_teaching_sessions%ROWTYPE;
BEGIN
  SELECT * INTO artifact_row
  FROM tutor_learning_artifacts
  WHERE id = NEW.artifact_id AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id
    AND teaching_session_id = NEW.teaching_session_id
    AND checkpoint_id = NEW.checkpoint_id
    AND learning_track_id = NEW.learning_track_id
    AND knowledge_key = NEW.knowledge_key;
  SELECT * INTO session_row
  FROM tutor_teaching_sessions
  WHERE id = NEW.teaching_session_id AND user_id = NEW.user_id
    AND conversation_id = NEW.conversation_id;
  IF artifact_row.id IS NULL OR session_row.id IS NULL
     OR artifact_row.version <> NEW.artifact_version
     OR session_row.status NOT IN ('active', 'paused')
     OR session_row.version <> NEW.session_version
     OR NOT tutor_teaching_checkpoint_descends_from(
       session_row.current_checkpoint_id, NEW.checkpoint_id,
       NEW.teaching_session_id, NEW.user_id, NEW.conversation_id
     )
     OR (
       NEW.source_kind IN ('static_display_timer', 'background_continuation')
       AND session_row.mode <> 'guided'
     )
     OR session_row.track_version <> NEW.track_version
     OR session_row.progress_version <> NEW.progress_version
     OR session_row.assignment_version <> NEW.assignment_version THEN
    RAISE EXCEPTION 'Tutor continuation intent authority is stale or mismatched'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_conversation_branches_lifecycle
  ON tutor_conversation_branches;
CREATE TRIGGER trg_tutor_conversation_branches_lifecycle
BEFORE UPDATE OR DELETE ON tutor_conversation_branches
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_branch_root_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_conversation_branches_updated_at
  ON tutor_conversation_branches;
CREATE TRIGGER trg_tutor_conversation_branches_updated_at
BEFORE UPDATE ON tutor_conversation_branches
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_conversation_branch_events_immutable
  ON tutor_conversation_branch_events;
CREATE TRIGGER trg_tutor_conversation_branch_events_immutable
BEFORE UPDATE OR DELETE ON tutor_conversation_branch_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_branch_append_only();

DROP TRIGGER IF EXISTS trg_tutor_run_branch_scopes_immutable
  ON tutor_run_branch_scopes;
CREATE TRIGGER trg_tutor_run_branch_scopes_immutable
BEFORE INSERT OR UPDATE OR DELETE ON tutor_run_branch_scopes
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_run_branch_scope();

DROP TRIGGER IF EXISTS trg_tutor_conversation_branch_items_scope
  ON tutor_conversation_branch_items;
CREATE TRIGGER trg_tutor_conversation_branch_items_scope
BEFORE INSERT ON tutor_conversation_branch_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_branch_item_scope();

DROP TRIGGER IF EXISTS trg_tutor_conversation_branch_items_immutable
  ON tutor_conversation_branch_items;
CREATE TRIGGER trg_tutor_conversation_branch_items_immutable
BEFORE UPDATE OR DELETE ON tutor_conversation_branch_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_branch_append_only();

DROP TRIGGER IF EXISTS trg_tutor_continuation_intents_insert_scope
  ON tutor_continuation_intents;
CREATE TRIGGER trg_tutor_continuation_intents_insert_scope
BEFORE INSERT ON tutor_continuation_intents
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_continuation_intent_insert_scope();

DROP TRIGGER IF EXISTS trg_tutor_continuation_intents_lifecycle
  ON tutor_continuation_intents;
CREATE TRIGGER trg_tutor_continuation_intents_lifecycle
BEFORE UPDATE OR DELETE ON tutor_continuation_intents
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_continuation_intent_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_continuation_intents_updated_at
  ON tutor_continuation_intents;
CREATE TRIGGER trg_tutor_continuation_intents_updated_at
BEFORE UPDATE ON tutor_continuation_intents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_continuation_intent_events_immutable
  ON tutor_continuation_intent_events;
CREATE TRIGGER trg_tutor_continuation_intent_events_immutable
BEFORE UPDATE OR DELETE ON tutor_continuation_intent_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_branch_append_only();
