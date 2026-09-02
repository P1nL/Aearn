-- Child 08 conversation-native model review v2 and immutable submission receipts.

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

ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS tutor_learning_artifacts_presentation_json_check;
ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifacts_presentation_json;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT chk_tutor_learning_artifacts_presentation_json CHECK (
    jsonb_typeof(presentation_json)='object'
    AND octet_length(presentation_json::text)<=196608
  );

CREATE TABLE IF NOT EXISTS tutor_model_review_artifact_receipts (
  id uuid PRIMARY KEY,
  artifact_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  learning_item_version_id uuid NOT NULL REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  artifact_version integer NOT NULL CHECK (artifact_version>=1),
  presentation_hash text NOT NULL CHECK (presentation_hash ~ '^[0-9a-f]{64}$'),
  submission_json jsonb NOT NULL CHECK (
    jsonb_typeof(submission_json)='object' AND octet_length(submission_json::text)<=65536
  ),
  submission_hash text NOT NULL CHECK (submission_hash ~ '^[0-9a-f]{64}$'),
  verdict text NOT NULL CHECK (verdict IN ('correctness_issue','no_correctness_issue','improvement_only','uncertain')),
  outcome text NOT NULL CHECK (outcome IN ('passed','failed')),
  score double precision NOT NULL CHECK (score BETWEEN 0 AND 1),
  assistance_kind text NOT NULL CHECK (assistance_kind IN ('independent','hinted','validation_evidence_viewed','remediated')),
  safe_feedback_json jsonb NOT NULL CHECK (
    jsonb_typeof(safe_feedback_json)='object' AND octet_length(safe_feedback_json::text)<=16384
  ),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  remediation_handle text CHECK (remediation_handle IS NULL OR remediation_handle ~ '^li:[0-9a-f]{64}$'),
  policy_version text NOT NULL CHECK (policy_version='model_code_review_score_v2'),
  receipt_hash text NOT NULL UNIQUE CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_model_review_artifact_receipt_artifact UNIQUE (artifact_id),
  CONSTRAINT uq_tutor_model_review_artifact_receipt_scope UNIQUE (id,user_id,conversation_id,teaching_session_id),
  CONSTRAINT fk_tutor_model_review_artifact_receipt_artifact
    FOREIGN KEY (artifact_id,user_id,conversation_id,teaching_session_id,learning_track_id)
    REFERENCES tutor_learning_artifacts(id,user_id,conversation_id,teaching_session_id,learning_track_id)
    ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_model_review_artifact_receipt_result CHECK (
    (outcome='passed' AND remediation_handle IS NULL)
    OR (outcome='failed' AND remediation_handle IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_model_review_artifact_receipt_submission CHECK (
    submission_json->>'schema_version'='model_code_review_submission_v2'
    AND submission_json->>'presentation_hash'=presentation_hash
  )
);

CREATE OR REPLACE FUNCTION enforce_tutor_model_review_artifact_receipt_scope()
RETURNS trigger AS $$
DECLARE artifact_row tutor_learning_artifacts%ROWTYPE;
DECLARE materialization_row tutor_learning_item_practice_materializations%ROWTYPE;
BEGIN
  SELECT * INTO artifact_row FROM tutor_learning_artifacts
  WHERE id=NEW.artifact_id AND user_id=NEW.user_id AND conversation_id=NEW.conversation_id
    AND teaching_session_id=NEW.teaching_session_id AND learning_track_id=NEW.learning_track_id
    AND knowledge_key=NEW.knowledge_key FOR UPDATE;
  SELECT * INTO materialization_row FROM tutor_learning_item_practice_materializations
  WHERE version_id=NEW.learning_item_version_id;
  IF artifact_row.id IS NULL
     OR artifact_row.artifact_kind<>'model_code_review'
     OR artifact_row.presentation_kind<>'model_code_review_v2'
     OR artifact_row.state NOT IN ('ready','active')
     OR artifact_row.version<>NEW.artifact_version
     OR artifact_row.owner_kind<>'learning_item'
     OR artifact_row.owner_id<>NEW.learning_item_version_id
     OR artifact_row.checkpoint_id<>NEW.checkpoint_id
     OR materialization_row.version_id IS NULL
     OR materialization_row.exercise_version_id<>NEW.exercise_version_id
     OR materialization_row.item_handle IS NULL THEN
    RAISE EXCEPTION 'Model review Artifact receipt scope is stale or mismatched' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_model_review_artifact_receipt_scope
  ON tutor_model_review_artifact_receipts;
CREATE TRIGGER trg_tutor_model_review_artifact_receipt_scope
BEFORE INSERT ON tutor_model_review_artifact_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_model_review_artifact_receipt_scope();

DROP TRIGGER IF EXISTS trg_tutor_model_review_artifact_receipt_immutable
  ON tutor_model_review_artifact_receipts;
CREATE TRIGGER trg_tutor_model_review_artifact_receipt_immutable
BEFORE UPDATE OR DELETE ON tutor_model_review_artifact_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_learning_artifact_append_only();

CREATE INDEX IF NOT EXISTS idx_tutor_model_review_artifact_receipts_user
  ON tutor_model_review_artifact_receipts(user_id,learning_track_id,knowledge_key,created_at DESC);
