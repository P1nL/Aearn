-- Child 02 atomic teaching Artifact commit authority. This fragment binds the
-- selected published Learning Item, source teaching Turn, v3 action receipt,
-- Artifact event, and next checkpoint without creating score or mastery state.

ALTER TABLE tutor_teaching_action_receipts
  ADD COLUMN IF NOT EXISTS interaction_intent text;
ALTER TABLE tutor_teaching_action_receipts
  ADD COLUMN IF NOT EXISTS artifact_handle text;
ALTER TABLE tutor_teaching_action_receipts
  ADD COLUMN IF NOT EXISTS artifact_id uuid;
ALTER TABLE tutor_teaching_action_receipts
  ADD COLUMN IF NOT EXISTS artifact_event_id uuid;
ALTER TABLE tutor_teaching_action_receipts
  ADD COLUMN IF NOT EXISTS artifact_event_sequence integer;

ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_response_mode;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_response_mode CHECK (
    learner_response_mode IN ('none','composer','artifact')
  );
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_interaction;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_interaction CHECK (
    interaction_intent IS NULL OR interaction_intent IN (
      'none','text_answer','structured_answer','edit_code','run_code',
      'review_diff','execute_query','interact_with_demo'
    )
  );
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_artifact_handle;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_artifact_handle CHECK (
    artifact_handle IS NULL OR artifact_handle ~ '^li:[0-9a-f]{64}$'
  );
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_artifact_event_sequence;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_artifact_event_sequence CHECK (
    artifact_event_sequence IS NULL OR artifact_event_sequence = 1
  );
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_version_shape;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_version_shape CHECK (
    (
      schema_version='teaching_action_receipt_v1'
      AND policy_version='lesson_teaching_policy_v1'
      AND teaching_moves_json='[]'::jsonb
      AND learner_response_mode='none'
      AND interaction_intent IS NULL
      AND artifact_handle IS NULL
      AND artifact_id IS NULL
      AND artifact_event_id IS NULL
      AND artifact_event_sequence IS NULL
    )
    OR
    (
      schema_version='teaching_action_receipt_v2'
      AND policy_version='lesson_teaching_policy_v2'
      AND jsonb_array_length(teaching_moves_json) BETWEEN 2 AND 4
      AND learner_response_mode IN ('none','composer')
      AND interaction_intent IS NULL
      AND artifact_handle IS NULL
      AND artifact_id IS NULL
      AND artifact_event_id IS NULL
      AND artifact_event_sequence IS NULL
    )
    OR
    (
      schema_version='teaching_action_receipt_v3'
      AND policy_version='lesson_teaching_policy_v3'
      AND jsonb_array_length(teaching_moves_json) BETWEEN 2 AND 4
      AND learner_response_mode='artifact'
      AND interaction_intent IN (
        'structured_answer','edit_code','run_code','review_diff',
        'execute_query','interact_with_demo'
      )
      AND artifact_handle IS NOT NULL
      AND artifact_id IS NOT NULL
      AND artifact_event_id IS NOT NULL
      AND artifact_event_sequence = 1
    )
  );

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='tutor_learning_artifacts'::regclass
      AND conname='uq_tutor_learning_artifacts_teaching_receipt_scope'
  ) THEN
    ALTER TABLE tutor_learning_artifacts
      ADD CONSTRAINT uq_tutor_learning_artifacts_teaching_receipt_scope
      UNIQUE (
        id,turn_id,user_id,conversation_id,teaching_session_id,checkpoint_id
      );
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='tutor_learning_artifact_events'::regclass
      AND conname='uq_tutor_learning_artifact_events_receipt_scope'
  ) THEN
    ALTER TABLE tutor_learning_artifact_events
      ADD CONSTRAINT uq_tutor_learning_artifact_events_receipt_scope
      UNIQUE (id,artifact_id,event_sequence);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='tutor_teaching_action_receipts'::regclass
      AND conname='fk_tutor_teaching_action_receipt_artifact'
  ) THEN
    ALTER TABLE tutor_teaching_action_receipts
      ADD CONSTRAINT fk_tutor_teaching_action_receipt_artifact
      FOREIGN KEY (
        artifact_id,run_id,user_id,conversation_id,teaching_session_id,checkpoint_id
      ) REFERENCES tutor_learning_artifacts(
        id,turn_id,user_id,conversation_id,teaching_session_id,checkpoint_id
      ) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='tutor_teaching_action_receipts'::regclass
      AND conname='fk_tutor_teaching_action_receipt_artifact_event'
  ) THEN
    ALTER TABLE tutor_teaching_action_receipts
      ADD CONSTRAINT fk_tutor_teaching_action_receipt_artifact_event
      FOREIGN KEY (artifact_event_id,artifact_id,artifact_event_sequence)
      REFERENCES tutor_learning_artifact_events(id,artifact_id,event_sequence)
      ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
  END IF;
END $$;

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
  item_exercise_id uuid;
BEGIN
  SELECT * INTO attempt_row
  FROM tutor_exercise_attempts
  WHERE id=target_attempt_id
    AND user_id=target_user_id
    AND track_id=target_track_id
    AND knowledge_key=target_knowledge_key;
  IF attempt_row.id IS NULL THEN RETURN false; END IF;

  SELECT lesson_assignment_id INTO session_assignment_id
  FROM tutor_teaching_sessions
  WHERE id=target_teaching_session_id
    AND user_id=target_user_id
    AND conversation_id=target_conversation_id
    AND track_id=target_track_id
    AND knowledge_key=target_knowledge_key;
  IF session_assignment_id IS NULL THEN RETURN false; END IF;

  IF target_owner_kind='lesson_gate' THEN
    RETURN attempt_row.attempt_type IN ('run','submit')
      AND attempt_row.lesson_assignment_id=session_assignment_id
      AND EXISTS (
        SELECT 1 FROM tutor_lesson_gate_states AS states
        WHERE states.id=target_owner_id
          AND states.user_id=target_user_id
          AND states.track_id=target_track_id
          AND states.knowledge_key=target_knowledge_key
          AND states.lesson_assignment_id=session_assignment_id
          AND states.gate_binding_id=attempt_row.gate_binding_id
      );
  ELSIF target_owner_kind='review_item' THEN
    RETURN attempt_row.attempt_type='review_submit'
      AND attempt_row.review_item_id=target_owner_id
      AND EXISTS (
        SELECT 1 FROM tutor_review_items AS items
        WHERE items.id=target_owner_id
          AND items.user_id=target_user_id
          AND items.track_id=target_track_id
          AND items.knowledge_key=target_knowledge_key
          AND items.session_id=attempt_row.review_session_id
      );
  ELSIF target_owner_kind='teaching_practice' THEN
    RETURN attempt_row.attempt_type IN ('run','submit')
      AND attempt_row.lesson_assignment_id=session_assignment_id;
  ELSIF target_owner_kind='learning_item' THEN
    SELECT materializations.exercise_version_id INTO item_exercise_id
    FROM tutor_learning_item_versions AS versions
    JOIN tutor_learning_item_practice_materializations AS materializations
      ON materializations.version_id=versions.id
    WHERE versions.id=target_owner_id
      AND versions.knowledge_key=target_knowledge_key;
    IF item_exercise_id IS NULL
       OR attempt_row.exercise_version_id IS DISTINCT FROM item_exercise_id THEN
      RETURN false;
    END IF;
    IF attempt_row.attempt_type IN ('run','submit') THEN
      RETURN attempt_row.lesson_assignment_id=session_assignment_id;
    END IF;
    IF attempt_row.attempt_type='review_submit' THEN
      RETURN EXISTS (
        SELECT 1 FROM tutor_review_items AS items
        WHERE items.id=attempt_row.review_item_id
          AND items.user_id=target_user_id
          AND items.track_id=target_track_id
          AND items.knowledge_key=target_knowledge_key
          AND items.exercise_version_id=item_exercise_id
          AND items.session_id=attempt_row.review_session_id
      );
    END IF;
  END IF;
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
  item_version_row tutor_learning_item_versions%ROWTYPE;
  item_publication_row tutor_learning_item_publication_events%ROWTYPE;
BEGIN
  SELECT * INTO session_row
  FROM tutor_teaching_sessions
  WHERE id=NEW.teaching_session_id
    AND user_id=NEW.user_id
    AND conversation_id=NEW.conversation_id
    AND track_id=NEW.learning_track_id
    AND knowledge_key=NEW.knowledge_key;
  IF session_row.id IS NULL
     OR session_row.current_checkpoint_id IS DISTINCT FROM NEW.checkpoint_id
     OR session_row.track_version<>NEW.track_version
     OR session_row.progress_version<>NEW.progress_version
     OR session_row.assignment_version<>NEW.assignment_version
     OR session_row.status NOT IN ('active','paused') THEN
    RAISE EXCEPTION 'Learning Artifact teaching authority is stale or mismatched'
      USING ERRCODE='23514';
  END IF;

  IF NEW.turn_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM tutor_run_teaching_scopes AS scopes
    WHERE scopes.run_id=NEW.turn_id
      AND scopes.user_id=NEW.user_id
      AND scopes.conversation_id=NEW.conversation_id
      AND scopes.teaching_session_id=NEW.teaching_session_id
      AND scopes.track_id=NEW.learning_track_id
      AND scopes.knowledge_key=NEW.knowledge_key
      AND scopes.track_version=NEW.track_version
      AND scopes.progress_version=NEW.progress_version
      AND scopes.assignment_version=NEW.assignment_version
      AND (
        scopes.checkpoint_id=NEW.checkpoint_id
        OR EXISTS (
          SELECT 1
          FROM tutor_teaching_session_checkpoints AS produced
          WHERE produced.id=NEW.checkpoint_id
            AND produced.teaching_session_id=NEW.teaching_session_id
            AND produced.user_id=NEW.user_id
            AND produced.conversation_id=NEW.conversation_id
            AND produced.source_run_id=NEW.turn_id
            AND produced.predecessor_checkpoint_id=scopes.checkpoint_id
            AND produced.session_version=scopes.session_version+1
        )
      )
  ) THEN
    RAISE EXCEPTION 'Learning Artifact Turn scope is stale or mismatched'
      USING ERRCODE='23514';
  END IF;

  IF NEW.active_attempt_id IS NOT NULL
     AND NOT tutor_learning_artifact_attempt_owner_matches(
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
      USING ERRCODE='23514';
  END IF;

  IF NEW.owner_kind='lesson_gate' THEN
    SELECT * INTO gate_row
    FROM tutor_lesson_gate_states
    WHERE id=NEW.owner_id
      AND user_id=NEW.user_id
      AND track_id=NEW.learning_track_id
      AND knowledge_key=NEW.knowledge_key
      AND lesson_assignment_id=session_row.lesson_assignment_id;
    IF gate_row.id IS NULL
       OR gate_row.version<>NEW.owner_version
       OR NEW.owner_context_version IS NOT NULL THEN
      RAISE EXCEPTION 'Learning Artifact Lesson Gate owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
  ELSIF NEW.owner_kind='review_item' THEN
    SELECT * INTO review_item_row
    FROM tutor_review_items
    WHERE id=NEW.owner_id
      AND user_id=NEW.user_id
      AND track_id=NEW.learning_track_id
      AND knowledge_key=NEW.knowledge_key;
    IF review_item_row.id IS NULL OR review_item_row.version<>NEW.owner_version THEN
      RAISE EXCEPTION 'Learning Artifact Review Item owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
    SELECT * INTO review_session_row
    FROM tutor_review_sessions
    WHERE id=review_item_row.session_id
      AND user_id=NEW.user_id
      AND track_id=NEW.learning_track_id
      AND knowledge_key=NEW.knowledge_key;
    IF review_session_row.id IS NULL
       OR NEW.owner_context_version IS NULL
       OR review_session_row.version<>NEW.owner_context_version THEN
      RAISE EXCEPTION 'Learning Artifact Review Session owner context is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
  ELSIF NEW.owner_kind='teaching_practice' THEN
    IF NEW.owner_id IS DISTINCT FROM NEW.checkpoint_id
       OR NEW.owner_version<>session_row.version
       OR NEW.owner_context_version IS DISTINCT FROM session_row.version THEN
      RAISE EXCEPTION 'Learning Artifact teaching owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
  ELSIF NEW.owner_kind='learning_item' THEN
    SELECT * INTO item_version_row
    FROM tutor_learning_item_versions
    WHERE id=NEW.owner_id
      AND knowledge_key=NEW.knowledge_key;
    IF item_version_row.id IS NULL
       OR NEW.owner_context_version IS DISTINCT FROM session_row.version
       OR item_version_row.purpose IS DISTINCT FROM NEW.purpose
       OR item_version_row.difficulty IS DISTINCT FROM NEW.difficulty
       OR (item_version_row.item_kind='code' AND NEW.artifact_kind<>'exercise_workspace')
       OR (item_version_row.item_kind='sql' AND NEW.artifact_kind<>'sql_workspace')
       OR (item_version_row.item_kind='demo' AND NEW.artifact_kind<>'demonstration')
       OR (item_version_row.item_kind='knowledge_check' AND NEW.artifact_kind<>'knowledge_check')
       OR (item_version_row.item_kind='model_review' AND NEW.artifact_kind<>'model_code_review') THEN
      RAISE EXCEPTION 'Learning Artifact Learning Item owner is stale or mismatched'
        USING ERRCODE='23514';
    END IF;
    IF item_version_row.item_kind<>'demo' AND NOT EXISTS (
      SELECT 1
      FROM tutor_learning_item_practice_materializations AS materializations
      WHERE materializations.version_id=item_version_row.id
        AND materializations.item_handle=item_version_row.handle
        AND materializations.content_hash=item_version_row.content_hash
    ) THEN
      RAISE EXCEPTION 'Learning Artifact Learning Item lacks Practice authority'
        USING ERRCODE='23514';
    END IF;
    IF TG_OP='UPDATE'
       AND NEW.state IN ('completed','failed','cancelled','superseded') THEN
      IF NEW.owner_version IS DISTINCT FROM OLD.owner_version
         OR NEW.owner_context_version IS DISTINCT FROM OLD.owner_context_version
         OR NOT EXISTS (
           SELECT 1
           FROM tutor_learning_item_publication_events AS publication
           WHERE publication.version_id=item_version_row.id
             AND publication.state_version=NEW.owner_version
             AND publication.state='published'
         ) THEN
        RAISE EXCEPTION 'Learning Artifact terminal Learning Item owner is stale'
          USING ERRCODE='23514';
      END IF;
    ELSE
      SELECT * INTO item_publication_row
      FROM tutor_learning_item_publication_events
      WHERE version_id=item_version_row.id
      ORDER BY state_version DESC
      LIMIT 1;
      IF item_publication_row.id IS NULL
         OR item_publication_row.state<>'published'
         OR item_publication_row.state_version<>NEW.owner_version
         OR item_publication_row.item_handle<>item_version_row.handle
         OR item_publication_row.content_hash<>item_version_row.content_hash THEN
        RAISE EXCEPTION 'Learning Artifact Learning Item publication is stale'
          USING ERRCODE='23514';
      END IF;
    END IF;
  ELSE
    RAISE EXCEPTION 'Learning Artifact owner kind is invalid' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
