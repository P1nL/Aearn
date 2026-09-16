-- Authority retirement is not a provider response or a resolved clarification.
-- Reentrant, caller-owned transaction; no historical data is rewritten.
ALTER TABLE tutor_conversation_branches
  ADD COLUMN IF NOT EXISTS superseded_by_session_id uuid,
  ADD COLUMN IF NOT EXISTS superseded_at timestamptz;
ALTER TABLE tutor_conversation_branches
  DROP CONSTRAINT IF EXISTS tutor_conversation_branches_state_check,
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_branch_resolution,
  DROP CONSTRAINT IF EXISTS fk_tutor_branch_superseding_session;
ALTER TABLE tutor_conversation_branches
  ADD CONSTRAINT tutor_conversation_branches_state_check
    CHECK (state IN ('active', 'resolved', 'superseded')),
  ADD CONSTRAINT chk_tutor_conversation_branch_resolution CHECK (
    (state = 'active' AND resolved_turn_id IS NULL AND resolved_at IS NULL
      AND superseded_by_session_id IS NULL AND superseded_at IS NULL)
    OR (state = 'resolved' AND resolved_turn_id IS NOT NULL AND resolved_at IS NOT NULL
      AND latest_disposition IS NOT NULL
      AND superseded_by_session_id IS NULL AND superseded_at IS NULL)
    OR (state = 'superseded' AND resolved_turn_id IS NULL AND resolved_at IS NULL
      AND superseded_by_session_id IS NOT NULL AND superseded_at IS NOT NULL
      AND superseded_by_session_id <> teaching_session_id)
  ),
  ADD CONSTRAINT fk_tutor_branch_superseding_session
    FOREIGN KEY (superseded_by_session_id, user_id, conversation_id)
    REFERENCES tutor_teaching_sessions(id, user_id, conversation_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE tutor_conversation_branch_events
  ADD COLUMN IF NOT EXISTS superseding_session_id uuid,
  ALTER COLUMN source_turn_id DROP NOT NULL,
  ALTER COLUMN source_message_id DROP NOT NULL,
  ALTER COLUMN source_input_revision DROP NOT NULL,
  DROP CONSTRAINT IF EXISTS tutor_conversation_branch_events_event_kind_check,
  DROP CONSTRAINT IF EXISTS chk_tutor_conversation_branch_event_response,
  DROP CONSTRAINT IF EXISTS chk_tutor_branch_event_authority_source,
  DROP CONSTRAINT IF EXISTS fk_tutor_branch_event_superseding_session;
ALTER TABLE tutor_conversation_branch_events
  ADD CONSTRAINT tutor_conversation_branch_events_event_kind_check CHECK (
    event_kind IN ('opened', 'turn_bound', 'response_recorded', 'authority_superseded')
  ),
  ADD CONSTRAINT chk_tutor_branch_event_authority_source CHECK (
    (event_kind = 'authority_superseded' AND superseding_session_id IS NOT NULL
      AND source_turn_id IS NULL AND source_message_id IS NULL AND source_input_revision IS NULL
      AND message_classification = 'normal' AND control_kind IS NULL)
    OR (event_kind <> 'authority_superseded' AND superseding_session_id IS NULL
      AND source_turn_id IS NOT NULL AND source_message_id IS NOT NULL
      AND source_input_revision IS NOT NULL)
  ),
  ADD CONSTRAINT chk_tutor_conversation_branch_event_response CHECK (
    (event_kind IN ('opened', 'turn_bound', 'authority_superseded')
      AND disposition IS NULL AND response_message_id IS NULL AND assistance_kind = 'none'
      AND assistance_receipt_kind IS NULL AND assistance_receipt_id IS NULL)
    OR (event_kind = 'response_recorded'
      AND disposition IS NOT NULL AND response_message_id IS NOT NULL
      AND ((assistance_kind = 'none' AND assistance_receipt_kind IS NULL AND assistance_receipt_id IS NULL)
        OR (assistance_kind <> 'none' AND assistance_receipt_kind IS NOT NULL AND assistance_receipt_id IS NOT NULL)))
  ),
  ADD CONSTRAINT fk_tutor_branch_event_superseding_session
    FOREIGN KEY (superseding_session_id, user_id, conversation_id)
    REFERENCES tutor_teaching_sessions(id, user_id, conversation_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

-- The session owner and the database both require a real, direct replacement.
CREATE OR REPLACE FUNCTION tutor_branch_authority_replacement_valid(
  branch_user uuid, branch_conversation uuid, branch_track uuid, branch_knowledge text,
  old_session uuid, new_session uuid
) RETURNS boolean AS $$
  SELECT EXISTS (
    SELECT 1 FROM tutor_teaching_sessions AS old
    JOIN tutor_teaching_sessions AS successor ON successor.predecessor_session_id = old.id
    WHERE old.id = old_session AND successor.id = new_session AND old.status = 'blocked'
      AND (old.user_id, old.conversation_id, old.track_id, old.knowledge_key)
        = (branch_user, branch_conversation, branch_track, branch_knowledge)
      AND (successor.user_id, successor.conversation_id, successor.track_id, successor.knowledge_key)
        = (old.user_id, old.conversation_id, old.track_id, old.knowledge_key)
      AND ROW(old.track_version, old.active_plan_revision_id, old.progress_version,
              old.lesson_assignment_id, old.assignment_version, old.document_id, old.document_content_hash)
        IS DISTINCT FROM
          ROW(successor.track_version, successor.active_plan_revision_id, successor.progress_version,
              successor.lesson_assignment_id, successor.assignment_version, successor.document_id, successor.document_content_hash)
      AND NOT EXISTS (
        SELECT 1 FROM tutor_runs AS runs
        JOIN tutor_run_teaching_scopes AS scopes ON scopes.run_id = runs.id
        WHERE scopes.teaching_session_id = old.id AND runs.user_id = old.user_id
          AND runs.terminal_outcome IS NULL AND runs.cancelled_at IS NULL
          AND runs.superseded_by_run_id IS NULL
      )
  );
$$ LANGUAGE sql STABLE;

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
  IF OLD.state IN ('resolved', 'superseded') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal Tutor conversation branch is immutable'
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
    IF NEW.state NOT IN ('active', 'resolved')
       OR NEW.latest_disposition IS DISTINCT FROM event_row.disposition
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
  ELSIF event_row.event_kind = 'authority_superseded' THEN
    IF NEW.state <> 'superseded' OR NEW.round_count <> OLD.round_count
       OR NEW.latest_disposition IS DISTINCT FROM OLD.latest_disposition
       OR NEW.superseded_at IS DISTINCT FROM event_row.created_at
       OR NEW.superseded_by_session_id IS DISTINCT FROM event_row.superseding_session_id
       OR NOT tutor_branch_authority_replacement_valid(
         OLD.user_id, OLD.conversation_id, OLD.learning_track_id, OLD.knowledge_key,
         OLD.teaching_session_id, NEW.superseded_by_session_id
       ) THEN
      RAISE EXCEPTION 'Tutor conversation branch authority replacement is invalid'
        USING ERRCODE = '23514';
    END IF;
  ELSE
    RAISE EXCEPTION 'Tutor conversation branch update event kind is invalid'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_branch_authority_insert()
RETURNS trigger AS $$
DECLARE
  branch_row tutor_conversation_branches%ROWTYPE;
BEGIN
  IF TG_TABLE_NAME = 'tutor_conversation_branches' THEN
    IF NEW.state <> 'active' THEN
      RAISE EXCEPTION 'Tutor branch must open active' USING ERRCODE = '23514';
    END IF;
  ELSIF NEW.event_kind = 'authority_superseded' THEN
    SELECT * INTO branch_row FROM tutor_conversation_branches
      WHERE id = NEW.branch_id AND user_id = NEW.user_id
        AND conversation_id = NEW.conversation_id AND artifact_id = NEW.artifact_id;
    IF branch_row.id IS NULL OR branch_row.state <> 'active'
       OR NEW.predecessor_event_id IS DISTINCT FROM branch_row.current_event_id
       OR NEW.branch_version <> branch_row.version + 1
       OR NOT tutor_branch_authority_replacement_valid(
         branch_row.user_id, branch_row.conversation_id, branch_row.learning_track_id,
         branch_row.knowledge_key, branch_row.teaching_session_id, NEW.superseding_session_id
       ) THEN
      RAISE EXCEPTION 'Tutor branch authority event requires an exact replacement'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_branch_authority_insert ON tutor_conversation_branches;
CREATE TRIGGER trg_tutor_branch_authority_insert BEFORE INSERT ON tutor_conversation_branches
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_branch_authority_insert();
DROP TRIGGER IF EXISTS trg_tutor_branch_authority_event_insert ON tutor_conversation_branch_events;
CREATE TRIGGER trg_tutor_branch_authority_event_insert BEFORE INSERT ON tutor_conversation_branch_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_branch_authority_insert();
