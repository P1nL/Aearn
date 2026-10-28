-- Completion-driven Sidecar attempts reuse the existing binding authority.
-- No historical row is retagged and no additional table is introduced.
ALTER TABLE tutor_run_runtime_bindings
  ADD COLUMN IF NOT EXISTS step_attempt_id uuid;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_run_runtime_bindings'::regclass
      AND conname = 'fk_tutor_runtime_binding_step_scope'
  ) THEN
    ALTER TABLE tutor_run_runtime_bindings
      ADD CONSTRAINT fk_tutor_runtime_binding_step_scope
      FOREIGN KEY (step_attempt_id, run_id, user_id, conversation_id)
      REFERENCES tutor_run_step_attempts(id, run_id, user_id, conversation_id)
      ON DELETE RESTRICT;
  END IF;
END;
$$;

ALTER TABLE tutor_run_runtime_bindings
  DROP CONSTRAINT IF EXISTS tutor_run_runtime_bindings_run_id_key;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runtime_binding_legacy_run
  ON tutor_run_runtime_bindings(run_id) WHERE step_attempt_id IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runtime_binding_step
  ON tutor_run_runtime_bindings(step_attempt_id) WHERE step_attempt_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_runtime_binding_active_run
  ON tutor_run_runtime_bindings(run_id) WHERE state IN ('thread_bound', 'running');

CREATE OR REPLACE FUNCTION enforce_tutor_runtime_binding_lifecycle()
RETURNS trigger AS $$
DECLARE
  run_profile text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor runtime bindings are retained audit state' USING ERRCODE = '23514';
  END IF;
  IF TG_OP = 'INSERT' THEN
    SELECT policy_json->>'execution_profile' INTO run_profile
    FROM tutor_runs WHERE id = NEW.run_id AND user_id = NEW.user_id
      AND conversation_id = NEW.conversation_id FOR UPDATE;
    IF (NEW.step_attempt_id IS NOT NULL) IS DISTINCT FROM
       (COALESCE(run_profile, '') = 'completion_driven_v1') THEN
      RAISE EXCEPTION 'Tutor runtime step binding requires the frozen completion profile'
        USING ERRCODE = '23514';
    END IF;
    IF EXISTS (
      SELECT 1 FROM tutor_run_runtime_bindings
      WHERE run_id = NEW.run_id
        AND (step_attempt_id IS NULL) IS DISTINCT FROM (NEW.step_attempt_id IS NULL)
    ) THEN
      RAISE EXCEPTION 'Legacy and completion runtime bindings cannot be mixed'
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.run_id IS DISTINCT FROM OLD.run_id
     OR NEW.step_attempt_id IS DISTINCT FROM OLD.step_attempt_id
     OR NEW.conversation_runtime_thread_id IS DISTINCT FROM OLD.conversation_runtime_thread_id
     OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
     OR NEW.runtime_kind IS DISTINCT FROM OLD.runtime_kind
     OR NEW.runtime_version IS DISTINCT FROM OLD.runtime_version
     OR NEW.protocol_version IS DISTINCT FROM OLD.protocol_version
     OR NEW.external_thread_id IS DISTINCT FROM OLD.external_thread_id
     OR NEW.connection_generation IS DISTINCT FROM OLD.connection_generation
     OR NEW.created_at IS DISTINCT FROM OLD.created_at
     OR (OLD.external_turn_id IS NOT NULL AND NEW.external_turn_id IS DISTINCT FROM OLD.external_turn_id) THEN
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
BEFORE INSERT OR UPDATE OR DELETE ON tutor_run_runtime_bindings
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_runtime_binding_lifecycle();
