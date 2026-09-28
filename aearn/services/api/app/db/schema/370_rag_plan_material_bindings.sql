-- D internal consumer receipts. No corpus, active-plan, or public-source authority.
CREATE UNIQUE INDEX IF NOT EXISTS uq_rag_d_draft_exact_scope
  ON tutor_learning_plan_drafts
  (id, session_id, user_id, draft_version, content_hash, source_run_id, source_input_revision);

CREATE TABLE IF NOT EXISTS rag_material_selections (
  handle text PRIMARY KEY CHECK (handle ~ '^selection\.[0-9a-f]{32}$'),
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  session_id uuid NOT NULL,
  draft_id uuid NOT NULL,
  draft_version integer NOT NULL CHECK (draft_version >= 1),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  source_run_id uuid NOT NULL,
  source_input_revision integer NOT NULL CHECK (source_input_revision >= 1),
  selection_digest text NOT NULL CHECK (selection_digest ~ '^[0-9a-f]{64}$'),
  snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(snapshot_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 3 AND 160),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  target_run_id uuid,
  target_input_revision integer CHECK (target_input_revision >= 1),
  expected_session_version integer CHECK (expected_session_version >= 1),
  assignment_digest text CHECK (assignment_digest ~ '^[0-9a-f]{64}$'),
  assigned_at timestamptz,
  CONSTRAINT uq_rag_d_selection_exact UNIQUE
    (handle, draft_id, session_id, user_id, selection_digest),
  CONSTRAINT uq_rag_d_selection_retry UNIQUE (draft_id, idempotency_key),
  CONSTRAINT uq_rag_d_selection_draft_digest UNIQUE (draft_id, selection_digest),
  CONSTRAINT uq_rag_d_selection_target UNIQUE (target_run_id, target_input_revision),
  CONSTRAINT chk_rag_d_assignment_atomic CHECK (
    (target_run_id IS NULL AND target_input_revision IS NULL AND expected_session_version IS NULL
     AND assignment_digest IS NULL AND assigned_at IS NULL)
    OR (target_run_id IS NOT NULL AND target_input_revision IS NOT NULL
        AND expected_session_version IS NOT NULL AND assignment_digest IS NOT NULL
        AND assigned_at IS NOT NULL)
  ),
  CONSTRAINT fk_rag_d_selection_session
    FOREIGN KEY (session_id, user_id) REFERENCES tutor_learning_plan_sessions(id, user_id)
    ON DELETE RESTRICT,
  CONSTRAINT fk_rag_d_selection_conversation
    FOREIGN KEY (conversation_id, user_id) REFERENCES tutor_conversations(id, user_id)
    ON DELETE RESTRICT,
  CONSTRAINT fk_rag_d_selection_draft
    FOREIGN KEY (draft_id, session_id, user_id, draft_version, content_hash,
                 source_run_id, source_input_revision)
    REFERENCES tutor_learning_plan_drafts
      (id, session_id, user_id, draft_version, content_hash, source_run_id, source_input_revision)
    ON DELETE RESTRICT,
  CONSTRAINT fk_rag_d_selection_target_run
    FOREIGN KEY (target_run_id, user_id, conversation_id)
    REFERENCES tutor_run_learning_scopes(run_id, user_id, conversation_id)
    ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_rag_d_selections_user ON rag_material_selections(user_id, session_id);

CREATE TABLE IF NOT EXISTS rag_plan_material_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  selection_handle text NOT NULL,
  selection_digest text NOT NULL CHECK (selection_digest ~ '^[0-9a-f]{64}$'),
  user_id uuid NOT NULL,
  session_id uuid NOT NULL,
  draft_id uuid NOT NULL,
  node_id text NOT NULL CHECK (node_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  goal_hash text NOT NULL CHECK (goal_hash ~ '^[0-9a-f]{64}$'),
  purpose text NOT NULL CHECK (purpose IN
    ('main_teaching', 'supplementary_explanation', 'assessment_evidence')),
  binding_digest text NOT NULL CHECK (binding_digest ~ '^[0-9a-f]{64}$'),
  binding_json jsonb NOT NULL CHECK (jsonb_typeof(binding_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 3 AND 160),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT uq_rag_d_binding_natural UNIQUE (draft_id, node_id, goal_hash, purpose),
  CONSTRAINT uq_rag_d_binding_retry UNIQUE (draft_id, idempotency_key),
  CONSTRAINT fk_rag_d_binding_selection
    FOREIGN KEY (selection_handle, draft_id, session_id, user_id, selection_digest)
    REFERENCES rag_material_selections(handle, draft_id, session_id, user_id, selection_digest)
    ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_rag_d_bindings_user ON rag_plan_material_bindings(user_id, session_id);

CREATE OR REPLACE FUNCTION enforce_rag_d_selection_append_only() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  ELSIF TG_OP = 'UPDATE' THEN
    IF OLD.target_run_id IS NULL AND NEW.target_run_id IS NOT NULL
       AND (NEW.handle, NEW.user_id, NEW.conversation_id, NEW.session_id, NEW.draft_id,
            NEW.draft_version, NEW.content_hash, NEW.source_run_id, NEW.source_input_revision,
            NEW.selection_digest, NEW.snapshot_json, NEW.idempotency_key, NEW.created_at)
           IS NOT DISTINCT FROM
           (OLD.handle, OLD.user_id, OLD.conversation_id, OLD.session_id, OLD.draft_id,
            OLD.draft_version, OLD.content_hash, OLD.source_run_id, OLD.source_input_revision,
            OLD.selection_digest, OLD.snapshot_json, OLD.idempotency_key, OLD.created_at)
       THEN RETURN NEW;
    END IF;
  END IF;
  RAISE EXCEPTION 'RAG D selection is immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_rag_d_selection_append_only ON rag_material_selections;
CREATE TRIGGER trg_rag_d_selection_append_only
BEFORE UPDATE OR DELETE ON rag_material_selections
FOR EACH ROW EXECUTE FUNCTION enforce_rag_d_selection_append_only();

CREATE OR REPLACE FUNCTION enforce_rag_d_binding_append_only() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'RAG D binding is immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_rag_d_binding_append_only ON rag_plan_material_bindings;
CREATE TRIGGER trg_rag_d_binding_append_only
BEFORE UPDATE OR DELETE ON rag_plan_material_bindings
FOR EACH ROW EXECUTE FUNCTION enforce_rag_d_binding_append_only();
