-- Child 09 conversation-native SQL workspace, structured public schema, and
-- Learning Item-owned Run Attempts without a counterfeit Lesson Gate.

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
    (artifact_kind = 'model_code_review' AND presentation_kind IN ('model_code_review_v1','model_code_review_v2')) OR
    (artifact_kind = 'sql_workspace' AND presentation_kind IN ('sql_workspace_v1','sql_workspace_v2')) OR
    (artifact_kind = 'demonstration' AND presentation_kind IN ('demonstration_v1','demonstration_v2')) OR
    (artifact_kind = 'source_inspector' AND presentation_kind = 'source_inspector_v1')
  );

ALTER TABLE tutor_exercise_attempts
  ADD COLUMN IF NOT EXISTS learning_item_version_id uuid;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid='tutor_exercise_attempts'::regclass
      AND conname='fk_tutor_exercise_attempt_learning_item_version'
  ) THEN
    ALTER TABLE tutor_exercise_attempts
      ADD CONSTRAINT fk_tutor_exercise_attempt_learning_item_version
      FOREIGN KEY (learning_item_version_id)
      REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT;
  END IF;
END $$;

ALTER TABLE tutor_exercise_attempts
  DROP CONSTRAINT IF EXISTS chk_tutor_exercise_attempts_owner_shape;
ALTER TABLE tutor_exercise_attempts
  ADD CONSTRAINT chk_tutor_exercise_attempts_owner_shape CHECK (
    (
      attempt_type IN ('run','submit')
      AND lesson_assignment_id IS NOT NULL AND document_id IS NOT NULL AND gate_binding_id IS NOT NULL
      AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
      AND review_session_id IS NULL AND review_item_id IS NULL
      AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
      AND expected_progress_version IS NOT NULL
      AND learning_item_version_id IS NULL
    )
    OR (
      attempt_type='diagnostic_submit'
      AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
      AND diagnostic_session_id IS NOT NULL AND diagnostic_item_id IS NOT NULL
      AND review_session_id IS NULL AND review_item_id IS NULL
      AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
      AND expected_progress_version IS NULL
      AND learning_item_version_id IS NULL
    )
    OR (
      attempt_type='review_submit'
      AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
      AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
      AND review_session_id IS NOT NULL AND review_item_id IS NOT NULL
      AND expected_review_session_version IS NOT NULL AND expected_review_session_version>=1
      AND expected_review_item_version IS NOT NULL AND expected_review_item_version=1
      AND expected_progress_version IS NULL
      AND learning_item_version_id IS NULL
    )
    OR (
      attempt_type='run'
      AND lesson_assignment_id IS NOT NULL AND document_id IS NOT NULL AND gate_binding_id IS NULL
      AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
      AND review_session_id IS NULL AND review_item_id IS NULL
      AND expected_review_session_version IS NULL AND expected_review_item_version IS NULL
      AND expected_progress_version IS NOT NULL
      AND learning_item_version_id IS NOT NULL
    )
  );

CREATE INDEX IF NOT EXISTS idx_tutor_exercise_attempts_learning_item
  ON tutor_exercise_attempts(learning_item_version_id,user_id,track_id,accepted_at DESC)
  WHERE learning_item_version_id IS NOT NULL;

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
    RETURN attempt_row.learning_item_version_id IS NULL
      AND attempt_row.attempt_type IN ('run','submit')
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
    RETURN attempt_row.learning_item_version_id IS NULL
      AND attempt_row.attempt_type='review_submit'
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
    RETURN attempt_row.learning_item_version_id IS NULL
      AND attempt_row.attempt_type IN ('run','submit')
      AND attempt_row.lesson_assignment_id=session_assignment_id;
  ELSIF target_owner_kind='learning_item' THEN
    SELECT materializations.exercise_version_id INTO item_exercise_id
    FROM tutor_learning_item_versions AS versions
    JOIN tutor_learning_item_practice_materializations AS materializations
      ON materializations.version_id=versions.id
    JOIN LATERAL (
      SELECT state,state_version
      FROM tutor_learning_item_publication_events AS publication
      WHERE publication.version_id=versions.id
      ORDER BY state_version DESC LIMIT 1
    ) AS publication ON publication.state='published'
    WHERE versions.id=target_owner_id
      AND versions.knowledge_key=target_knowledge_key;
    RETURN item_exercise_id IS NOT NULL
      AND attempt_row.attempt_type='run'
      AND attempt_row.learning_item_version_id=target_owner_id
      AND attempt_row.exercise_version_id=item_exercise_id
      AND attempt_row.lesson_assignment_id=session_assignment_id
      AND attempt_row.gate_binding_id IS NULL;
  END IF;
  RETURN false;
END;
$$ LANGUAGE plpgsql STABLE;
