-- Child 07 immutable knowledge-check responses and exactly-once assistance receipts.

ALTER TABLE tutor_learning_artifacts
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifacts_allowed_actions;
ALTER TABLE tutor_learning_artifacts
  ADD CONSTRAINT chk_tutor_learning_artifacts_allowed_actions CHECK (
    jsonb_typeof(allowed_actions_json) = 'array'
    AND jsonb_array_length(allowed_actions_json) <= 6
    AND allowed_actions_json <@ '["request_hint","request_direct_answer","run","respond","complete_review","cancel","acknowledge_demo_event","complete_demo"]'::jsonb
  );

ALTER TABLE tutor_learning_artifact_events
  DROP CONSTRAINT IF EXISTS chk_tutor_learning_artifact_events_action_kind;
ALTER TABLE tutor_learning_artifact_events
  ADD CONSTRAINT chk_tutor_learning_artifact_events_action_kind CHECK (
    action_kind IS NULL OR action_kind IN (
      'request_hint', 'request_direct_answer', 'run', 'respond', 'complete_review',
      'cancel', 'acknowledge_demo_event', 'complete_demo'
    )
  );

CREATE TABLE IF NOT EXISTS tutor_knowledge_check_response_receipts (
  id uuid PRIMARY KEY,
  artifact_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  learning_item_version_id uuid NOT NULL,
  artifact_version integer NOT NULL CHECK (artifact_version >= 1),
  response_kind text NOT NULL CHECK (response_kind IN (
    'single_select','multi_select','prediction','ordering','code_range','short_text','direct_answer'
  )),
  response_json jsonb NOT NULL CHECK (jsonb_typeof(response_json)='object' AND octet_length(response_json::text)<=8192),
  response_hash text NOT NULL CHECK (response_hash ~ '^[0-9a-f]{64}$'),
  outcome text NOT NULL CHECK (outcome IN ('correct','incorrect')),
  assistance_kind text NOT NULL CHECK (assistance_kind IN ('independent','hinted','direct_answer','remediated')),
  independent_mastery_eligible boolean NOT NULL,
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  score_policy_version text NOT NULL CHECK (score_policy_version='knowledge_check_score_v1'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_knowledge_check_response_artifact
    FOREIGN KEY (artifact_id,user_id,conversation_id,teaching_session_id,learning_track_id)
    REFERENCES tutor_learning_artifacts(id,user_id,conversation_id,teaching_session_id,learning_track_id)
    ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_knowledge_check_response_item
    FOREIGN KEY (learning_item_version_id) REFERENCES tutor_learning_item_versions(id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_knowledge_check_response_mastery CHECK (
    independent_mastery_eligible = (outcome='correct' AND assistance_kind='independent')
  ),
  CONSTRAINT chk_tutor_knowledge_check_direct_answer_response CHECK (
    (response_kind='direct_answer') = (assistance_kind='direct_answer')
    AND (response_kind<>'direct_answer' OR response_json='{"kind":"direct_answer"}'::jsonb)
  )
);

CREATE TABLE IF NOT EXISTS tutor_knowledge_check_assistance_receipts (
  id uuid PRIMARY KEY,
  artifact_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  learning_track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  artifact_version integer NOT NULL CHECK (artifact_version >= 1),
  assistance_kind text NOT NULL CHECK (assistance_kind IN ('hint','direct_answer')),
  hint_level integer CHECK (hint_level BETWEEN 1 AND 3),
  assistance_hash text NOT NULL CHECK (assistance_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_knowledge_check_assistance_artifact
    FOREIGN KEY (artifact_id,user_id,conversation_id,teaching_session_id,learning_track_id)
    REFERENCES tutor_learning_artifacts(id,user_id,conversation_id,teaching_session_id,learning_track_id)
    ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_knowledge_check_assistance_shape CHECK (
    (assistance_kind='hint' AND hint_level IS NOT NULL)
    OR (assistance_kind='direct_answer' AND hint_level IS NULL)
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_knowledge_check_hint_receipt
  ON tutor_knowledge_check_assistance_receipts(artifact_id,hint_level)
  WHERE hint_level IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_knowledge_check_direct_answer
  ON tutor_knowledge_check_assistance_receipts(artifact_id,assistance_kind)
  WHERE assistance_kind='direct_answer';

CREATE OR REPLACE FUNCTION enforce_tutor_knowledge_check_receipt_scope()
RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM tutor_learning_artifacts AS artifacts
    WHERE artifacts.id=NEW.artifact_id
      AND artifacts.user_id=NEW.user_id
      AND artifacts.conversation_id=NEW.conversation_id
      AND artifacts.learning_track_id=NEW.learning_track_id
      AND artifacts.knowledge_key=NEW.knowledge_key
      AND artifacts.teaching_session_id=NEW.teaching_session_id
      AND artifacts.checkpoint_id=NEW.checkpoint_id
      AND artifacts.version=NEW.artifact_version
      AND artifacts.owner_kind='learning_item'
      AND artifacts.artifact_kind='knowledge_check'
      AND artifacts.state IN ('active','ready')
  ) THEN
    RAISE EXCEPTION 'Knowledge check receipt scope is stale or mismatched' USING ERRCODE='23514';
  END IF;
  IF TG_TABLE_NAME='tutor_knowledge_check_response_receipts' THEN
    IF NEW.learning_item_version_id<>(
      SELECT owner_id FROM tutor_learning_artifacts WHERE id=NEW.artifact_id
    ) THEN
      RAISE EXCEPTION 'Knowledge check response owner is stale or mismatched' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_knowledge_check_receipt_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP='DELETE' AND current_setting('aearn.learning_track_purge_user_id',true)=OLD.user_id::text THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Knowledge check receipts are append-only' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_knowledge_check_responses_scope ON tutor_knowledge_check_response_receipts;
CREATE TRIGGER trg_tutor_knowledge_check_responses_scope
BEFORE INSERT ON tutor_knowledge_check_response_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_knowledge_check_receipt_scope();

DROP TRIGGER IF EXISTS trg_tutor_knowledge_check_assistance_scope ON tutor_knowledge_check_assistance_receipts;
CREATE TRIGGER trg_tutor_knowledge_check_assistance_scope
BEFORE INSERT ON tutor_knowledge_check_assistance_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_knowledge_check_receipt_scope();

DROP TRIGGER IF EXISTS trg_tutor_knowledge_check_responses_immutable ON tutor_knowledge_check_response_receipts;
CREATE TRIGGER trg_tutor_knowledge_check_responses_immutable
BEFORE UPDATE OR DELETE ON tutor_knowledge_check_response_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_knowledge_check_receipt_immutable();

DROP TRIGGER IF EXISTS trg_tutor_knowledge_check_assistance_immutable ON tutor_knowledge_check_assistance_receipts;
CREATE TRIGGER trg_tutor_knowledge_check_assistance_immutable
BEFORE UPDATE OR DELETE ON tutor_knowledge_check_assistance_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_knowledge_check_receipt_immutable();
