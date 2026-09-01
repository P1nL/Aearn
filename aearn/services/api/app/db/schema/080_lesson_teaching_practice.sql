-- Child 08-04 LessonDocument authority: immutable documents, evidence snapshots,
-- user-scoped assignments, and recoverable server-owned authoring lifecycle.
CREATE TABLE IF NOT EXISTS tutor_lesson_documents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_kind text NOT NULL CHECK (document_kind IN ('standard', 'personalized')),
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  language_id text NOT NULL CHECK (char_length(language_id) BETWEEN 1 AND 80),
  active_plan_revision_id uuid,
  standard_document_id uuid,
  predecessor_document_id uuid,
  schema_version text NOT NULL CHECK (schema_version = 'lesson_document_v1'),
  content_standard_version text NOT NULL CHECK (content_standard_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  generator_version text NOT NULL CHECK (char_length(generator_version) BETWEEN 1 AND 160),
  policy_version text NOT NULL CHECK (char_length(policy_version) BETWEEN 1 AND 160),
  source_set_hash text NOT NULL CHECK (source_set_hash ~ '^[0-9a-f]{64}$'),
  profile_hash text CHECK (profile_hash IS NULL OR profile_hash ~ '^[0-9a-f]{64}$'),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  coverage_keys_json jsonb NOT NULL CHECK (jsonb_typeof(coverage_keys_json) = 'array'),
  blocks_json jsonb NOT NULL CHECK (jsonb_typeof(blocks_json) = 'array'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  change_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(change_summary_json) = 'object'),
  quality_summary_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(quality_summary_json) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_documents_id_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_document_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_revision_scope
    FOREIGN KEY (active_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_standard FOREIGN KEY (standard_document_id) REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_document_predecessor FOREIGN KEY (predecessor_document_id) REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_document_scope_shape CHECK (
    (document_kind = 'standard' AND user_id IS NULL AND track_id IS NULL
      AND active_plan_revision_id IS NULL AND standard_document_id IS NULL AND profile_hash IS NULL)
    OR
    (document_kind = 'personalized' AND user_id IS NOT NULL AND track_id IS NOT NULL
      AND active_plan_revision_id IS NOT NULL AND standard_document_id IS NOT NULL AND profile_hash IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_lesson_document_predecessor_distinct CHECK (
    predecessor_document_id IS NULL OR predecessor_document_id <> id
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_lesson_documents_standard_identity
  ON tutor_lesson_documents(
    language_id, knowledge_key, content_standard_version,
    generator_version, policy_version, source_set_hash, content_hash
  ) WHERE document_kind = 'standard';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_lesson_documents_personalized_identity
  ON tutor_lesson_documents(
    user_id, track_id, knowledge_key, standard_document_id,
    profile_hash, generator_version, policy_version, source_set_hash, content_hash
  ) WHERE document_kind = 'personalized';
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_documents_track_key_created
  ON tutor_lesson_documents(track_id, knowledge_key, created_at DESC)
  WHERE document_kind = 'personalized';

CREATE TABLE IF NOT EXISTS tutor_lesson_source_snapshots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  citation_id text NOT NULL CHECK (citation_id ~ '^cite_[0-9a-f]{16}$'),
  source_id text NOT NULL CHECK (char_length(source_id) BETWEEN 1 AND 160),
  display_name text NOT NULL CHECK (char_length(display_name) BETWEEN 1 AND 240),
  provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 240),
  trust_tier text NOT NULL CHECK (trust_tier IN ('official', 'trusted_de_facto', 'internal')),
  source_type text NOT NULL CHECK (source_type IN ('tutorial', 'reference', 'spec', 'platform_docs', 'vendor_docs')),
  source_version_label text NOT NULL CHECK (char_length(source_version_label) BETWEEN 1 AND 160),
  source_version_kind text NOT NULL CHECK (source_version_kind IN ('fixed', 'rolling')),
  canonical_url text NOT NULL CHECK (canonical_url ~ '^https?://'),
  section_path_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(section_path_json) = 'array'),
  grounding_chunk_id text NOT NULL CHECK (char_length(grounding_chunk_id) BETWEEN 1 AND 160),
  document_content_hash text NOT NULL CHECK (document_content_hash ~ '^[0-9a-f]{64}$'),
  chunk_content_hash text NOT NULL CHECK (chunk_content_hash ~ '^[0-9a-f]{64}$'),
  fetched_at timestamptz NOT NULL,
  snapshotted_at timestamptz NOT NULL,
  evidence_excerpt text NOT NULL CHECK (char_length(evidence_excerpt) BETWEEN 1 AND 1200),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_source_snapshots_document_citation UNIQUE (document_id, citation_id),
  CONSTRAINT uq_tutor_lesson_source_snapshots_id_scope UNIQUE (id, document_id, user_id, track_id, knowledge_key)
);
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_source_snapshots_document
  ON tutor_lesson_source_snapshots(document_id, citation_id);

CREATE TABLE IF NOT EXISTS tutor_lesson_block_citations (
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  block_id text NOT NULL CHECK (block_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  citation_id text NOT NULL CHECK (citation_id ~ '^cite_[0-9a-f]{16}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (document_id, block_id, citation_id),
  CONSTRAINT fk_tutor_lesson_block_citation_snapshot
    FOREIGN KEY (document_id, citation_id)
    REFERENCES tutor_lesson_source_snapshots(document_id, citation_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_lesson_gate_slots (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid,
  track_id uuid,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  block_id text NOT NULL CHECK (block_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  gate_key text NOT NULL CHECK (gate_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  gate_kind text NOT NULL CHECK (gate_kind IN ('knowledge_check', 'guided_practice', 'independent_practice')),
  assessment_contract_version text NOT NULL CHECK (assessment_contract_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  required_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  learner_prompt_hash text NOT NULL CHECK (learner_prompt_hash ~ '^[0-9a-f]{64}$'),
  learner_prompt text NOT NULL CHECK (char_length(learner_prompt) BETWEEN 1 AND 1200),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_gate_slots_document_key UNIQUE (document_id, gate_key),
  CONSTRAINT uq_tutor_lesson_gate_slots_document_block UNIQUE (document_id, block_id)
);

CREATE TABLE IF NOT EXISTS tutor_lesson_assignments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  document_id uuid NOT NULL,
  source_plan_revision_id uuid NOT NULL,
  predecessor_assignment_id uuid,
  assignment_version integer NOT NULL CHECK (assignment_version >= 1),
  status text NOT NULL CHECK (status IN ('active', 'proposed', 'superseded')),
  impact_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(impact_json) = 'object'),
  expected_progress_version integer NOT NULL CHECK (expected_progress_version >= 1),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  started_at timestamptz,
  activated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_assignments_id_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_assignment_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_assignment_document_scope
    FOREIGN KEY (document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_documents(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_assignment_revision_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_assignment_predecessor FOREIGN KEY (predecessor_assignment_id) REFERENCES tutor_lesson_assignments(id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_assignment_predecessor_distinct CHECK (
    predecessor_assignment_id IS NULL OR predecessor_assignment_id <> id
  ),
  CONSTRAINT chk_tutor_lesson_assignment_activation CHECK (
    (status = 'proposed' AND activated_at IS NULL)
    OR (status IN ('active', 'superseded') AND activated_at IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_lesson_assignments_one_active
  ON tutor_lesson_assignments(track_id, knowledge_key) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_assignments_track_key_created
  ON tutor_lesson_assignments(track_id, knowledge_key, created_at DESC);

CREATE TABLE IF NOT EXISTS tutor_lesson_authoring_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  run_kind text NOT NULL CHECK (run_kind IN ('prepare', 'refresh')),
  state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'claimed', 'running', 'completed', 'failed', 'cancelled')),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_progress_version integer NOT NULL CHECK (expected_progress_version >= 1),
  active_plan_revision_id uuid NOT NULL,
  source_set_hash text CHECK (source_set_hash IS NULL OR source_set_hash ~ '^[0-9a-f]{64}$'),
  profile_hash text NOT NULL CHECK (profile_hash ~ '^[0-9a-f]{64}$'),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  lease_generation integer NOT NULL DEFAULT 0 CHECK (lease_generation >= 0),
  lease_owner text,
  lease_expires_at timestamptz,
  failure_code text,
  failure_message text,
  standard_document_id uuid REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  personalized_document_id uuid REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  assignment_id uuid REFERENCES tutor_lesson_assignments(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  terminal_at timestamptz,
  CONSTRAINT uq_tutor_lesson_authoring_runs_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_lesson_authoring_runs_idempotency UNIQUE (user_id, run_kind, idempotency_key),
  CONSTRAINT fk_tutor_lesson_authoring_run_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_authoring_run_revision_scope
    FOREIGN KEY (active_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_authoring_run_lease CHECK (
    (state IN ('claimed', 'running')) = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
  ),
  CONSTRAINT chk_tutor_lesson_authoring_run_terminal CHECK (
    (state IN ('completed', 'failed', 'cancelled')) = (terminal_at IS NOT NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_authoring_runs_claim
  ON tutor_lesson_authoring_runs(state, lease_expires_at, created_at)
  WHERE state IN ('pending', 'claimed', 'running');
CREATE INDEX IF NOT EXISTS idx_tutor_lesson_authoring_runs_track_key
  ON tutor_lesson_authoring_runs(track_id, knowledge_key, created_at DESC);

CREATE TABLE IF NOT EXISTS tutor_lesson_authoring_attempt_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL,
  user_id uuid NOT NULL,
  attempt_index integer NOT NULL CHECK (attempt_index >= 1),
  provider text NOT NULL CHECK (char_length(provider) BETWEEN 1 AND 120),
  model text NOT NULL CHECK (char_length(model) BETWEEN 1 AND 160),
  protocol text NOT NULL CHECK (char_length(protocol) BETWEEN 1 AND 80),
  outcome text NOT NULL CHECK (outcome IN ('success', 'unavailable', 'invalid', 'failed')),
  diagnostic_code text,
  usage_available boolean NOT NULL DEFAULT false,
  input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
  total_tokens integer CHECK (total_tokens IS NULL OR total_tokens >= 0),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  response_hash text CHECK (response_hash IS NULL OR response_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_authoring_attempt_identity UNIQUE (run_id, attempt_index),
  CONSTRAINT fk_tutor_lesson_authoring_attempt_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_lesson_authoring_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_authoring_attempt_usage CHECK (
    (usage_available AND input_tokens IS NOT NULL AND output_tokens IS NOT NULL)
    OR (NOT usage_available AND input_tokens IS NULL AND output_tokens IS NULL AND total_tokens IS NULL)
  )
);

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_document_lineage()
RETURNS trigger AS $$
DECLARE
  standard_row tutor_lesson_documents%ROWTYPE;
  predecessor_row tutor_lesson_documents%ROWTYPE;
BEGIN
  IF NEW.document_kind = 'personalized' THEN
    SELECT * INTO standard_row FROM tutor_lesson_documents WHERE id = NEW.standard_document_id;
    IF standard_row.id IS NULL OR standard_row.document_kind <> 'standard'
       OR standard_row.language_id <> NEW.language_id
       OR standard_row.knowledge_key <> NEW.knowledge_key THEN
      RAISE EXCEPTION 'Personalized LessonDocument must reference a matching standard document' USING ERRCODE = '23514';
    END IF;
  END IF;
  IF NEW.predecessor_document_id IS NOT NULL THEN
    SELECT * INTO predecessor_row FROM tutor_lesson_documents WHERE id = NEW.predecessor_document_id;
    IF predecessor_row.id IS NULL OR predecessor_row.document_kind <> NEW.document_kind
       OR predecessor_row.language_id <> NEW.language_id
       OR predecessor_row.knowledge_key <> NEW.knowledge_key
       OR predecessor_row.user_id IS DISTINCT FROM NEW.user_id
       OR predecessor_row.track_id IS DISTINCT FROM NEW.track_id THEN
      RAISE EXCEPTION 'LessonDocument predecessor scope is invalid' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_immutable()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.user_id IS NOT NULL AND tutor_learning_track_purge_allowed(OLD.user_id) THEN
      RETURN OLD;
    END IF;
    RAISE EXCEPTION 'Lesson authority rows are append-only' USING ERRCODE = '23514';
  END IF;
  RAISE EXCEPTION 'Lesson authority rows are immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_assignment_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Lesson assignments cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.document_id IS DISTINCT FROM OLD.document_id OR NEW.source_plan_revision_id IS DISTINCT FROM OLD.source_plan_revision_id
     OR NEW.predecessor_assignment_id IS DISTINCT FROM OLD.predecessor_assignment_id
     OR NEW.assignment_version IS DISTINCT FROM OLD.assignment_version
     OR NEW.impact_json IS DISTINCT FROM OLD.impact_json OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
     OR NEW.expected_progress_version IS DISTINCT FROM OLD.expected_progress_version
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Lesson assignment identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.started_at IS NOT NULL AND NEW.started_at IS DISTINCT FROM OLD.started_at THEN
    RAISE EXCEPTION 'Started Lesson assignment is frozen' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'proposed' AND NEW.status = 'active'
     AND (OLD.activated_at IS NOT NULL OR NEW.activated_at IS NULL) THEN
    RAISE EXCEPTION 'Activated Lesson assignment requires a new activation timestamp' USING ERRCODE = '23514';
  END IF;
  IF OLD.status <> 'proposed' AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
    RAISE EXCEPTION 'Lesson assignment activation timestamp is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'active' AND NEW.status IN ('active', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.status = 'proposed' AND NEW.status IN ('proposed', 'active', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.status = NEW.status AND OLD.status = 'superseded' THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Lesson assignment lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_authoring_run_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Lesson authoring runs cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('completed', 'failed', 'cancelled') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal Lesson authoring run is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'pending' AND NEW.state IN ('pending', 'claimed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'claimed' AND NEW.state IN ('claimed', 'running', 'pending', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  IF OLD.state = 'running' AND NEW.state IN ('running', 'completed', 'failed', 'cancelled') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Lesson authoring run lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_lesson_documents_lineage ON tutor_lesson_documents;
CREATE TRIGGER trg_tutor_lesson_documents_lineage
BEFORE INSERT ON tutor_lesson_documents
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_document_lineage();

DROP TRIGGER IF EXISTS trg_tutor_lesson_documents_immutable ON tutor_lesson_documents;
CREATE TRIGGER trg_tutor_lesson_documents_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_documents
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_source_snapshots_immutable ON tutor_lesson_source_snapshots;
CREATE TRIGGER trg_tutor_lesson_source_snapshots_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_source_snapshots
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_block_citations_immutable ON tutor_lesson_block_citations;
CREATE TRIGGER trg_tutor_lesson_block_citations_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_block_citations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_slots_immutable ON tutor_lesson_gate_slots;
CREATE TRIGGER trg_tutor_lesson_gate_slots_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_gate_slots
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

DROP TRIGGER IF EXISTS trg_tutor_lesson_assignments_updated_at ON tutor_lesson_assignments;
CREATE TRIGGER trg_tutor_lesson_assignments_updated_at
BEFORE UPDATE ON tutor_lesson_assignments
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_lesson_assignments_lifecycle ON tutor_lesson_assignments;
CREATE TRIGGER trg_tutor_lesson_assignments_lifecycle
BEFORE UPDATE OR DELETE ON tutor_lesson_assignments
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_assignment_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_lesson_authoring_runs_updated_at ON tutor_lesson_authoring_runs;
CREATE TRIGGER trg_tutor_lesson_authoring_runs_updated_at
BEFORE UPDATE ON tutor_lesson_authoring_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_tutor_lesson_authoring_runs_lifecycle ON tutor_lesson_authoring_runs;
CREATE TRIGGER trg_tutor_lesson_authoring_runs_lifecycle
BEFORE UPDATE OR DELETE ON tutor_lesson_authoring_runs
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_authoring_run_lifecycle();

DROP TRIGGER IF EXISTS trg_tutor_lesson_authoring_attempt_receipts_immutable ON tutor_lesson_authoring_attempt_receipts;
CREATE TRIGGER trg_tutor_lesson_authoring_attempt_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_authoring_attempt_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_immutable();

-- Child 08-22 durable teaching-session authority and structured Turn stimulus.
CREATE TABLE IF NOT EXISTS tutor_teaching_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  track_version integer NOT NULL CHECK (track_version >= 1),
  active_plan_revision_id uuid NOT NULL,
  progress_version integer NOT NULL CHECK (progress_version >= 1),
  lesson_assignment_id uuid NOT NULL,
  assignment_version integer NOT NULL CHECK (assignment_version >= 1),
  document_id uuid NOT NULL,
  document_content_hash text NOT NULL CHECK (document_content_hash ~ '^[0-9a-f]{64}$'),
  predecessor_session_id uuid,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','completed','blocked')),
  mode text NOT NULL DEFAULT 'guided' CHECK (mode IN ('guided','free_reading')),
  current_checkpoint_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  last_mutation_key text CHECK (last_mutation_key IS NULL OR char_length(last_mutation_key) BETWEEN 1 AND 160),
  last_mutation_hash text CHECK (last_mutation_hash IS NULL OR last_mutation_hash ~ '^[0-9a-f]{64}$'),
  paused_at timestamptz,
  completed_at timestamptz,
  last_activity_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_teaching_sessions_id_scope UNIQUE (id,user_id,conversation_id),
  CONSTRAINT fk_tutor_teaching_session_track_user FOREIGN KEY (track_id,user_id)
    REFERENCES tutor_learning_tracks(id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_session_conversation_user FOREIGN KEY (conversation_id,user_id)
    REFERENCES tutor_conversations(id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_session_progress FOREIGN KEY (track_id,user_id,knowledge_key)
    REFERENCES tutor_track_node_progress(track_id,user_id,knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_session_revision FOREIGN KEY (active_plan_revision_id,track_id,user_id)
    REFERENCES tutor_track_plan_revisions(id,track_id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_session_assignment FOREIGN KEY (lesson_assignment_id,user_id,track_id,knowledge_key)
    REFERENCES tutor_lesson_assignments(id,user_id,track_id,knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_session_document FOREIGN KEY (document_id,user_id,track_id,knowledge_key)
    REFERENCES tutor_lesson_documents(id,user_id,track_id,knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_session_predecessor FOREIGN KEY (predecessor_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_sessions(id,user_id,conversation_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT chk_tutor_teaching_session_timestamps CHECK (
    (status='paused')=(paused_at IS NOT NULL) AND (status='completed')=(completed_at IS NOT NULL)
  )
);
ALTER TABLE tutor_teaching_sessions ADD COLUMN IF NOT EXISTS track_version integer;
ALTER TABLE tutor_teaching_sessions ALTER COLUMN track_version SET NOT NULL;
ALTER TABLE tutor_teaching_sessions DROP CONSTRAINT IF EXISTS chk_tutor_teaching_sessions_track_version;
ALTER TABLE tutor_teaching_sessions ADD CONSTRAINT chk_tutor_teaching_sessions_track_version CHECK (track_version>=1);
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE schemaname='public' AND indexname='uq_tutor_teaching_sessions_one_current'
      AND indexdef LIKE '%blocked%'
  ) THEN
    DROP INDEX uq_tutor_teaching_sessions_one_current;
  END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_teaching_sessions_one_current
  ON tutor_teaching_sessions(user_id,track_id,conversation_id,knowledge_key)
  WHERE status IN ('active','paused');
CREATE INDEX IF NOT EXISTS idx_tutor_teaching_sessions_track_activity
  ON tutor_teaching_sessions(user_id,track_id,last_activity_at DESC,id DESC);

CREATE TABLE IF NOT EXISTS tutor_teaching_session_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  teaching_session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  predecessor_checkpoint_id uuid,
  session_version integer NOT NULL CHECK (session_version >= 1),
  state_json jsonb NOT NULL CHECK (jsonb_typeof(state_json)='object' AND octet_length(state_json::text)<=16384),
  authority_snapshot_json jsonb NOT NULL CHECK (jsonb_typeof(authority_snapshot_json)='object' AND octet_length(authority_snapshot_json::text)<=4096),
  source_run_id uuid,
  source_stimulus_id uuid,
  schema_version text NOT NULL DEFAULT 'teaching_checkpoint_v1' CHECK (schema_version='teaching_checkpoint_v1'),
  policy_version text NOT NULL DEFAULT 'teaching_authority_v1' CHECK (policy_version='teaching_authority_v1'),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_teaching_checkpoints_id_scope UNIQUE (id,teaching_session_id,user_id,conversation_id),
  CONSTRAINT uq_tutor_teaching_checkpoints_session_version UNIQUE (teaching_session_id,session_version),
  CONSTRAINT uq_tutor_teaching_checkpoints_successor UNIQUE (predecessor_checkpoint_id),
  CONSTRAINT fk_tutor_teaching_checkpoint_session FOREIGN KEY (teaching_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_sessions(id,user_id,conversation_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_teaching_checkpoint_predecessor FOREIGN KEY (predecessor_checkpoint_id,teaching_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_session_checkpoints(id,teaching_session_id,user_id,conversation_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_teaching_checkpoint_run FOREIGN KEY (source_run_id,user_id)
    REFERENCES tutor_runs(id,user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_teaching_checkpoint_lineage CHECK (
    (session_version=1 AND predecessor_checkpoint_id IS NULL) OR
    (session_version>1 AND predecessor_checkpoint_id IS NOT NULL)
  )
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='uq_tutor_input_events_run_message_revision') THEN
    ALTER TABLE tutor_run_input_events ADD CONSTRAINT uq_tutor_input_events_run_message_revision
      UNIQUE (run_id,message_id,input_revision);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_run_stimulus_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  stimulus_kind text NOT NULL CHECK (stimulus_kind IN ('learner_message','teaching_control','domain_event')),
  message_id uuid,
  input_revision integer CHECK (input_revision IS NULL OR input_revision>=1),
  control_key text CHECK (control_key IS NULL OR control_key IN ('open_session','continue','return_focus','switch_mode','pause','resume','enter_next_knowledge')),
  client_action_id text CHECK (client_action_id IS NULL OR char_length(client_action_id) BETWEEN 1 AND 160),
  expected_session_version integer CHECK (expected_session_version IS NULL OR expected_session_version>=1),
  expected_track_version integer CHECK (expected_track_version IS NULL OR expected_track_version>=1),
  expected_progress_version integer CHECK (expected_progress_version IS NULL OR expected_progress_version>=1),
  expected_assignment_version integer CHECK (expected_assignment_version IS NULL OR expected_assignment_version>=1),
  domain_event_kind text CHECK (domain_event_kind IS NULL OR domain_event_kind IN ('gate_terminal','review_terminal','progress_changed','assignment_changed','authority_refresh')),
  source_id text CHECK (source_id IS NULL OR char_length(source_id) BETWEEN 1 AND 160),
  source_version integer CHECK (source_version IS NULL OR source_version>=1),
  safe_payload_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(safe_payload_json)='object' AND octet_length(safe_payload_json::text)<=2048),
  payload_hash text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_run_stimuli_id_scope UNIQUE (id,run_id,user_id,conversation_id,teaching_session_id),
  CONSTRAINT fk_tutor_run_stimulus_run_user FOREIGN KEY (run_id,user_id)
    REFERENCES tutor_runs(id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_stimulus_run_conversation FOREIGN KEY (run_id,conversation_id)
    REFERENCES tutor_runs(id,conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_stimulus_session FOREIGN KEY (teaching_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_sessions(id,user_id,conversation_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_run_stimulus_message FOREIGN KEY (run_id,message_id,input_revision)
    REFERENCES tutor_run_input_events(run_id,message_id,input_revision) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_run_stimulus_exact_one CHECK (
    (stimulus_kind='learner_message' AND message_id IS NOT NULL AND input_revision IS NOT NULL
      AND control_key IS NULL AND client_action_id IS NULL AND expected_session_version IS NULL
      AND expected_track_version IS NULL AND expected_progress_version IS NULL AND expected_assignment_version IS NULL
      AND domain_event_kind IS NULL AND source_id IS NULL AND source_version IS NULL)
    OR
    (stimulus_kind='teaching_control' AND message_id IS NULL AND input_revision IS NULL
      AND control_key IS NOT NULL AND client_action_id IS NOT NULL AND expected_session_version IS NOT NULL
      AND expected_track_version IS NOT NULL AND expected_progress_version IS NOT NULL AND expected_assignment_version IS NOT NULL
      AND domain_event_kind IS NULL AND source_id IS NULL AND source_version IS NULL)
    OR
    (stimulus_kind='domain_event' AND message_id IS NULL AND input_revision IS NULL
      AND control_key IS NULL AND client_action_id IS NULL AND expected_session_version IS NULL
      AND expected_track_version IS NULL AND expected_progress_version IS NULL AND expected_assignment_version IS NULL
      AND domain_event_kind IS NOT NULL AND source_id IS NOT NULL AND source_version IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_run_stimuli_control
  ON tutor_run_stimulus_events(teaching_session_id,client_action_id) WHERE stimulus_kind='teaching_control';
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_run_stimuli_domain
  ON tutor_run_stimulus_events(teaching_session_id,domain_event_kind,source_id,source_version) WHERE stimulus_kind='domain_event';

CREATE TABLE IF NOT EXISTS tutor_run_teaching_scopes (
  run_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  stimulus_id uuid NOT NULL UNIQUE,
  session_version integer NOT NULL CHECK (session_version>=1),
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  track_version integer NOT NULL CHECK (track_version>=1),
  active_plan_revision_id uuid NOT NULL,
  progress_version integer NOT NULL CHECK (progress_version>=1),
  mode text NOT NULL CHECK (mode IN ('guided','free_reading')),
  lesson_assignment_id uuid NOT NULL,
  assignment_version integer NOT NULL CHECK (assignment_version>=1),
  document_id uuid NOT NULL,
  document_content_hash text NOT NULL CHECK (document_content_hash ~ '^[0-9a-f]{64}$'),
  schema_version text NOT NULL DEFAULT 'run_teaching_scope_v1' CHECK (schema_version='run_teaching_scope_v1'),
  policy_version text NOT NULL DEFAULT 'teaching_authority_v1' CHECK (policy_version='teaching_authority_v1'),
  source_hash text NOT NULL CHECK (source_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_run_teaching_scopes_scope UNIQUE (run_id,user_id,conversation_id),
  CONSTRAINT fk_tutor_run_teaching_scope_run_user FOREIGN KEY (run_id,user_id) REFERENCES tutor_runs(id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_teaching_scope_run_conversation FOREIGN KEY (run_id,conversation_id) REFERENCES tutor_runs(id,conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_teaching_scope_session FOREIGN KEY (teaching_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_sessions(id,user_id,conversation_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_run_teaching_scope_checkpoint FOREIGN KEY (checkpoint_id,teaching_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_session_checkpoints(id,teaching_session_id,user_id,conversation_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_run_teaching_scope_stimulus FOREIGN KEY (stimulus_id,run_id,user_id,conversation_id,teaching_session_id)
    REFERENCES tutor_run_stimulus_events(id,run_id,user_id,conversation_id,teaching_session_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_run_teaching_scope_revision FOREIGN KEY (active_plan_revision_id,track_id,user_id)
    REFERENCES tutor_track_plan_revisions(id,track_id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_teaching_scope_progress FOREIGN KEY (track_id,user_id,knowledge_key)
    REFERENCES tutor_track_node_progress(track_id,user_id,knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_teaching_scope_assignment FOREIGN KEY (lesson_assignment_id,user_id,track_id,knowledge_key)
    REFERENCES tutor_lesson_assignments(id,user_id,track_id,knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_run_teaching_scope_document FOREIGN KEY (document_id,user_id,track_id,knowledge_key)
    REFERENCES tutor_lesson_documents(id,user_id,track_id,knowledge_key) ON DELETE RESTRICT
);
ALTER TABLE tutor_run_teaching_scopes ADD COLUMN IF NOT EXISTS track_version integer;
ALTER TABLE tutor_run_teaching_scopes ADD COLUMN IF NOT EXISTS active_plan_revision_id uuid;
ALTER TABLE tutor_run_teaching_scopes ADD COLUMN IF NOT EXISTS progress_version integer;
ALTER TABLE tutor_run_teaching_scopes ALTER COLUMN track_version SET NOT NULL;
ALTER TABLE tutor_run_teaching_scopes ALTER COLUMN active_plan_revision_id SET NOT NULL;
ALTER TABLE tutor_run_teaching_scopes ALTER COLUMN progress_version SET NOT NULL;
ALTER TABLE tutor_run_teaching_scopes DROP CONSTRAINT IF EXISTS chk_tutor_run_teaching_scope_versions;
ALTER TABLE tutor_run_teaching_scopes ADD CONSTRAINT chk_tutor_run_teaching_scope_versions CHECK (track_version>=1 AND progress_version>=1);
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_tutor_run_teaching_scope_revision') THEN
    ALTER TABLE tutor_run_teaching_scopes ADD CONSTRAINT fk_tutor_run_teaching_scope_revision
      FOREIGN KEY (active_plan_revision_id,track_id,user_id)
      REFERENCES tutor_track_plan_revisions(id,track_id,user_id) ON DELETE RESTRICT;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_tutor_run_teaching_scopes_session_created
  ON tutor_run_teaching_scopes(teaching_session_id,created_at DESC,run_id);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_tutor_teaching_session_current_checkpoint') THEN
    ALTER TABLE tutor_teaching_sessions ADD CONSTRAINT fk_tutor_teaching_session_current_checkpoint
      FOREIGN KEY (current_checkpoint_id,id,user_id,conversation_id)
      REFERENCES tutor_teaching_session_checkpoints(id,teaching_session_id,user_id,conversation_id)
      ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='fk_tutor_teaching_checkpoint_source_stimulus') THEN
    ALTER TABLE tutor_teaching_session_checkpoints ADD CONSTRAINT fk_tutor_teaching_checkpoint_source_stimulus
      FOREIGN KEY (source_stimulus_id,source_run_id,user_id,conversation_id,teaching_session_id)
      REFERENCES tutor_run_stimulus_events(id,run_id,user_id,conversation_id,teaching_session_id)
      ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
  END IF;
END $$;

ALTER TABLE tutor_run_stimulus_events
  DROP CONSTRAINT IF EXISTS tutor_run_stimulus_events_control_key_check;
ALTER TABLE tutor_run_stimulus_events
  ADD CONSTRAINT tutor_run_stimulus_events_control_key_check CHECK (
    control_key IS NULL OR control_key IN (
      'open_session','continue','return_focus','change_example','escalate_guided',
      'switch_mode','pause','resume','enter_next_knowledge'
    )
  );

CREATE TABLE IF NOT EXISTS tutor_teaching_action_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  conversation_id uuid NOT NULL,
  teaching_session_id uuid NOT NULL,
  checkpoint_id uuid NOT NULL,
  stimulus_id uuid NOT NULL,
  action text NOT NULL CHECK (action IN (
    'orient','explain_concept','answer_question','show_example','compare_examples',
    'check_understanding','recommend_practice','explain_feedback','remediate_prerequisite',
    'summarize_progress','recommend_pause','wait_for_input'
  )),
  objective_id text NOT NULL CHECK (objective_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  focus_id text NOT NULL CHECK (focus_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  focus_resolution text NOT NULL CHECK (focus_resolution IN (
    'stay','push_child','resolve_and_resume_parent','replace_objective','abandon_branch','wait'
  )),
  pause_kind text NOT NULL CHECK (pause_kind IN (
    'soft_pause','evidence_pause','authority_pause','session_pause','completion_pause'
  )),
  source_handles_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
    jsonb_typeof(source_handles_json)='array' AND jsonb_array_length(source_handles_json)<=8
    AND octet_length(source_handles_json::text)<=2048
  ),
  public_message_hash text NOT NULL CHECK (public_message_hash ~ '^[0-9a-f]{64}$'),
  context_source_ids_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
    jsonb_typeof(context_source_ids_json)='array' AND jsonb_array_length(context_source_ids_json)<=64
    AND octet_length(context_source_ids_json::text)<=8192
  ),
  context_source_hashes_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
    jsonb_typeof(context_source_hashes_json)='array' AND jsonb_array_length(context_source_hashes_json)<=64
    AND octet_length(context_source_hashes_json::text)<=8192
  ),
  teaching_moves_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  learner_response_mode text NOT NULL DEFAULT 'none',
  schema_version text NOT NULL DEFAULT 'teaching_action_receipt_v1',
  policy_version text NOT NULL DEFAULT 'lesson_teaching_policy_v1',
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_teaching_action_receipts_scope
    UNIQUE (id,run_id,user_id,conversation_id,teaching_session_id),
  CONSTRAINT fk_tutor_teaching_action_receipt_run_user FOREIGN KEY (run_id,user_id)
    REFERENCES tutor_runs(id,user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_action_receipt_run_conversation FOREIGN KEY (run_id,conversation_id)
    REFERENCES tutor_runs(id,conversation_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_teaching_action_receipt_session FOREIGN KEY (teaching_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_sessions(id,user_id,conversation_id) ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_teaching_action_receipt_checkpoint
    FOREIGN KEY (checkpoint_id,teaching_session_id,user_id,conversation_id)
    REFERENCES tutor_teaching_session_checkpoints(id,teaching_session_id,user_id,conversation_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED,
  CONSTRAINT fk_tutor_teaching_action_receipt_stimulus
    FOREIGN KEY (stimulus_id,run_id,user_id,conversation_id,teaching_session_id)
    REFERENCES tutor_run_stimulus_events(id,run_id,user_id,conversation_id,teaching_session_id)
    ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED
);
ALTER TABLE tutor_teaching_action_receipts
  ADD COLUMN IF NOT EXISTS teaching_moves_json jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE tutor_teaching_action_receipts
  ADD COLUMN IF NOT EXISTS learner_response_mode text NOT NULL DEFAULT 'none';
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS tutor_teaching_action_receipts_schema_version_check;
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS tutor_teaching_action_receipts_policy_version_check;
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_moves;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_moves CHECK (
    jsonb_typeof(teaching_moves_json)='array'
    AND jsonb_array_length(teaching_moves_json)<=4
    AND octet_length(teaching_moves_json::text)<=1024
    AND teaching_moves_json <@ '["targeted_explanation","worked_example","counterexample","misconception_contrast","guided_derivation","prediction","error_detection","micro_transfer","learner_feedback"]'::jsonb
    AND (jsonb_array_length(teaching_moves_json)<2 OR teaching_moves_json->>0<>teaching_moves_json->>1)
    AND (jsonb_array_length(teaching_moves_json)<3 OR (
      teaching_moves_json->>0<>teaching_moves_json->>2 AND teaching_moves_json->>1<>teaching_moves_json->>2
    ))
    AND (jsonb_array_length(teaching_moves_json)<4 OR (
      teaching_moves_json->>0<>teaching_moves_json->>3 AND teaching_moves_json->>1<>teaching_moves_json->>3
      AND teaching_moves_json->>2<>teaching_moves_json->>3
    ))
  );
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_response_mode;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_response_mode
  CHECK (learner_response_mode IN ('none','composer','artifact'));
ALTER TABLE tutor_teaching_action_receipts
  DROP CONSTRAINT IF EXISTS chk_tutor_teaching_action_receipts_version_shape;
ALTER TABLE tutor_teaching_action_receipts
  ADD CONSTRAINT chk_tutor_teaching_action_receipts_version_shape CHECK (
    (
      schema_version='teaching_action_receipt_v1'
      AND policy_version='lesson_teaching_policy_v1'
      AND teaching_moves_json='[]'::jsonb
      AND learner_response_mode='none'
    )
    OR
    (
      schema_version='teaching_action_receipt_v2'
      AND policy_version='lesson_teaching_policy_v2'
      AND jsonb_array_length(teaching_moves_json) BETWEEN 2 AND 4
    )
    OR
    (
      schema_version='teaching_action_receipt_v3'
      AND policy_version='lesson_teaching_policy_v3'
      AND jsonb_array_length(teaching_moves_json) BETWEEN 2 AND 4
      AND learner_response_mode='artifact'
    )
  );
CREATE INDEX IF NOT EXISTS idx_tutor_teaching_action_receipts_session_created
  ON tutor_teaching_action_receipts(teaching_session_id,created_at DESC,id DESC);
-- Repair early local bootstrap variants that used immediate RESTRICT on deferred teaching lineage.
ALTER TABLE tutor_teaching_sessions DROP CONSTRAINT IF EXISTS fk_tutor_teaching_session_current_checkpoint;
ALTER TABLE tutor_teaching_sessions ADD CONSTRAINT fk_tutor_teaching_session_current_checkpoint
  FOREIGN KEY (current_checkpoint_id,id,user_id,conversation_id)
  REFERENCES tutor_teaching_session_checkpoints(id,teaching_session_id,user_id,conversation_id)
  ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE tutor_teaching_session_checkpoints DROP CONSTRAINT IF EXISTS fk_tutor_teaching_checkpoint_predecessor;
ALTER TABLE tutor_teaching_session_checkpoints ADD CONSTRAINT fk_tutor_teaching_checkpoint_predecessor
  FOREIGN KEY (predecessor_checkpoint_id,teaching_session_id,user_id,conversation_id)
  REFERENCES tutor_teaching_session_checkpoints(id,teaching_session_id,user_id,conversation_id)
  ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE tutor_teaching_session_checkpoints DROP CONSTRAINT IF EXISTS fk_tutor_teaching_checkpoint_source_stimulus;
ALTER TABLE tutor_teaching_session_checkpoints ADD CONSTRAINT fk_tutor_teaching_checkpoint_source_stimulus
  FOREIGN KEY (source_stimulus_id,source_run_id,user_id,conversation_id,teaching_session_id)
  REFERENCES tutor_run_stimulus_events(id,run_id,user_id,conversation_id,teaching_session_id)
  ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;

CREATE OR REPLACE FUNCTION enforce_tutor_teaching_session_lifecycle() RETURNS trigger AS $$
BEGIN
  IF TG_OP='DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor teaching sessions cannot be deleted' USING ERRCODE='23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
    OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.conversation_id IS DISTINCT FROM OLD.conversation_id
    OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
    OR NEW.active_plan_revision_id IS DISTINCT FROM OLD.active_plan_revision_id
    OR NEW.progress_version IS DISTINCT FROM OLD.progress_version
    OR NEW.lesson_assignment_id IS DISTINCT FROM OLD.lesson_assignment_id
    OR NEW.assignment_version IS DISTINCT FROM OLD.assignment_version
    OR NEW.document_id IS DISTINCT FROM OLD.document_id
    OR NEW.document_content_hash IS DISTINCT FROM OLD.document_content_hash
    OR NEW.predecessor_session_id IS DISTINCT FROM OLD.predecessor_session_id
    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Tutor teaching session authority is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.version NOT IN (OLD.version,OLD.version+1) THEN
    RAISE EXCEPTION 'Tutor teaching session version must advance by one' USING ERRCODE='23514';
  END IF;
  IF NEW IS DISTINCT FROM OLD AND NEW.version=OLD.version
    AND NOT (OLD.current_checkpoint_id IS NULL AND NEW.current_checkpoint_id IS NOT NULL AND OLD.version=1) THEN
    RAISE EXCEPTION 'Tutor teaching session mutation requires version advance' USING ERRCODE='23514';
  END IF;
  IF OLD.status='completed' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Completed Tutor teaching session is immutable' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_teaching_append_only() RETURNS trigger AS $$
BEGIN
  IF TG_OP='DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Tutor teaching authority evidence is append-only' USING ERRCODE='23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_teaching_sessions_updated_at ON tutor_teaching_sessions;
CREATE TRIGGER trg_tutor_teaching_sessions_updated_at BEFORE UPDATE ON tutor_teaching_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_teaching_sessions_lifecycle ON tutor_teaching_sessions;
CREATE TRIGGER trg_tutor_teaching_sessions_lifecycle BEFORE UPDATE OR DELETE ON tutor_teaching_sessions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_teaching_session_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_teaching_checkpoints_immutable ON tutor_teaching_session_checkpoints;
CREATE TRIGGER trg_tutor_teaching_checkpoints_immutable BEFORE UPDATE OR DELETE ON tutor_teaching_session_checkpoints
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_teaching_append_only();
DROP TRIGGER IF EXISTS trg_tutor_run_stimuli_immutable ON tutor_run_stimulus_events;
CREATE TRIGGER trg_tutor_run_stimuli_immutable BEFORE UPDATE OR DELETE ON tutor_run_stimulus_events
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_teaching_append_only();
DROP TRIGGER IF EXISTS trg_tutor_run_teaching_scopes_immutable ON tutor_run_teaching_scopes;
CREATE TRIGGER trg_tutor_run_teaching_scopes_immutable BEFORE UPDATE OR DELETE ON tutor_run_teaching_scopes
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_teaching_append_only();

DROP TRIGGER IF EXISTS trg_tutor_teaching_action_receipts_immutable ON tutor_teaching_action_receipts;
CREATE TRIGGER trg_tutor_teaching_action_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_teaching_action_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_teaching_append_only();

-- Lesson exercise Gate, append-only attempt, and module diagnostic authority.
ALTER TABLE tutor_mastery_evidence
  ADD COLUMN IF NOT EXISTS evidence_effect text NOT NULL DEFAULT 'reinforcing';
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_mastery_evidence'::regclass
      AND conname = 'chk_tutor_mastery_evidence_effect'
  ) THEN
    ALTER TABLE tutor_mastery_evidence
      ADD CONSTRAINT chk_tutor_mastery_evidence_effect
      CHECK (evidence_effect IN ('reinforcing', 'observational_non_degrading'));
  END IF;
END $$;

ALTER TABLE tutor_mastery_states
  ADD COLUMN IF NOT EXISTS observation_count integer NOT NULL DEFAULT 0;
ALTER TABLE tutor_mastery_states
  ADD COLUMN IF NOT EXISTS last_observation_id uuid;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'tutor_mastery_states'::regclass
      AND conname = 'chk_tutor_mastery_states_observation_count'
  ) THEN
    ALTER TABLE tutor_mastery_states
      ADD CONSTRAINT chk_tutor_mastery_states_observation_count CHECK (observation_count >= 0);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_exercise_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_key text NOT NULL CHECK (exercise_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_type text NOT NULL CHECK (exercise_type IN (
    'code_completion', 'sql_query', 'browser_preview', 'static_code_reasoning'
  )),
  version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  source_kind text NOT NULL CHECK (source_kind IN ('curated_fixture', 'registered_author')),
  title text NOT NULL CHECK (char_length(title) BETWEEN 1 AND 240),
  learner_prompt_json jsonb NOT NULL CHECK (jsonb_typeof(learner_prompt_json) = 'object'),
  starter_artifact_json jsonb NOT NULL CHECK (jsonb_typeof(starter_artifact_json) = 'object'),
  required_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(required_capabilities_json) = 'array'),
  runtime_profile_key text CHECK (
    runtime_profile_key IS NULL OR runtime_profile_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  execution_required boolean NOT NULL,
  public_feedback_policy_version text NOT NULL CHECK (
    public_feedback_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'
  ),
  validation_status text NOT NULL CHECK (validation_status IN ('ready', 'rejected')),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_versions_key_version UNIQUE (exercise_key, version),
  CONSTRAINT uq_tutor_exercise_versions_id_identity UNIQUE (id, language_id, exercise_key, version),
  CONSTRAINT chk_tutor_exercise_versions_execution_shape CHECK (
    execution_required = (runtime_profile_key IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_exercise_private_rubrics (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_version_id uuid NOT NULL UNIQUE REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  rubric_version text NOT NULL CHECK (rubric_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  private_test_bundle_json jsonb NOT NULL CHECK (jsonb_typeof(private_test_bundle_json) = 'array'),
  reference_answer_json jsonb NOT NULL CHECK (jsonb_typeof(reference_answer_json) = 'object'),
  score_policy_json jsonb NOT NULL CHECK (jsonb_typeof(score_policy_json) = 'object'),
  rubric_hash text NOT NULL CHECK (rubric_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_private_rubrics_id_exercise UNIQUE (id, exercise_version_id)
);

CREATE TABLE IF NOT EXISTS tutor_lesson_gate_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slot_id uuid NOT NULL REFERENCES tutor_lesson_gate_slots(id) ON DELETE RESTRICT,
  document_id uuid NOT NULL REFERENCES tutor_lesson_documents(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  gate_key text NOT NULL CHECK (gate_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  requirement_kind text NOT NULL CHECK (requirement_kind IN ('required', 'recommended', 'diagnostic')),
  pass_policy_version text NOT NULL CHECK (pass_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  pass_threshold double precision NOT NULL CHECK (pass_threshold > 0 AND pass_threshold <= 1),
  execution_requirement text NOT NULL CHECK (execution_requirement IN ('required', 'optional', 'forbidden')),
  remediation_exercise_version_id uuid REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  slot_contract_hash text NOT NULL CHECK (slot_contract_hash ~ '^[0-9a-f]{64}$'),
  binding_contract_hash text NOT NULL CHECK (binding_contract_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_gate_bindings_document_key UNIQUE (document_id, gate_key),
  CONSTRAINT uq_tutor_lesson_gate_bindings_id_scope UNIQUE (id, document_id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_gate_binding_slot
    FOREIGN KEY (document_id, gate_key)
    REFERENCES tutor_lesson_gate_slots(document_id, gate_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_gate_binding_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_lesson_gate_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid NOT NULL,
  document_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL,
  state text NOT NULL CHECK (state IN ('available', 'in_progress', 'passed', 'remediation_required')),
  attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  best_score double precision NOT NULL DEFAULT 0 CHECK (best_score >= 0 AND best_score <= 1),
  latest_attempt_id uuid,
  passing_attempt_id uuid,
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  passed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_lesson_gate_states_assignment_binding UNIQUE (lesson_assignment_id, gate_binding_id),
  CONSTRAINT uq_tutor_lesson_gate_states_id_scope UNIQUE (id, user_id, track_id, knowledge_key),
  CONSTRAINT fk_tutor_lesson_gate_state_assignment_scope
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_lesson_gate_state_binding_scope
    FOREIGN KEY (gate_binding_id, document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_gate_bindings(id, document_id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_lesson_gate_states_passed CHECK (
    (state = 'passed') = (passed_at IS NOT NULL AND passing_attempt_id IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS tutor_module_diagnostic_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  language_id text NOT NULL CHECK (language_id ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  module_key text NOT NULL CHECK (module_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  version text NOT NULL CHECK (version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  policy_version text NOT NULL CHECK (policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  core_capabilities_json jsonb NOT NULL CHECK (jsonb_typeof(core_capabilities_json) = 'array'),
  pass_threshold double precision NOT NULL CHECK (pass_threshold > 0 AND pass_threshold <= 1),
  require_all_core boolean NOT NULL DEFAULT true,
  independent_only boolean NOT NULL DEFAULT true,
  cooldown_seconds integer NOT NULL CHECK (cooldown_seconds >= 0 AND cooldown_seconds <= 2678400),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  published_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_module_diagnostic_versions_identity UNIQUE (language_id, module_key, version),
  CONSTRAINT uq_tutor_module_diagnostic_versions_id_identity UNIQUE (id, language_id, module_key, version)
);

CREATE TABLE IF NOT EXISTS tutor_module_diagnostic_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  module_key text NOT NULL CHECK (module_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  diagnostic_version_id uuid NOT NULL REFERENCES tutor_module_diagnostic_versions(id) ON DELETE RESTRICT,
  source_plan_revision_id uuid NOT NULL,
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  state text NOT NULL CHECK (state IN ('active', 'failed', 'passed_pending_confirmation', 'confirmed', 'expired')),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  proposed_plan_revision_id uuid,
  impact_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(impact_json) = 'object'),
  weak_capabilities_json jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(weak_capabilities_json) = 'array'),
  version integer NOT NULL DEFAULT 1 CHECK (version >= 1),
  started_at timestamptz NOT NULL,
  terminal_at timestamptz,
  cooldown_until timestamptz,
  confirmed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_module_diagnostic_sessions_id_scope UNIQUE (id, user_id, track_id),
  CONSTRAINT uq_tutor_module_diagnostic_sessions_idempotency UNIQUE (user_id, track_id, module_key, idempotency_key),
  CONSTRAINT fk_tutor_module_diagnostic_session_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_module_diagnostic_session_revision_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_module_diagnostic_session_proposed_scope
    FOREIGN KEY (proposed_plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_module_diagnostic_sessions_terminal CHECK (
    (state = 'active') = (terminal_at IS NULL)
  ),
  CONSTRAINT chk_tutor_module_diagnostic_sessions_confirmation CHECK (
    (state = 'confirmed') = (confirmed_at IS NOT NULL)
  )
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_module_diagnostic_sessions_active
  ON tutor_module_diagnostic_sessions(user_id, track_id, module_key)
  WHERE state IN ('active', 'passed_pending_confirmation');

CREATE TABLE IF NOT EXISTS tutor_module_diagnostic_items (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL,
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  source_plan_revision_id uuid NOT NULL,
  item_key text NOT NULL CHECK (item_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  order_index integer NOT NULL CHECK (order_index >= 0),
  capability_key text NOT NULL CHECK (capability_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  threshold double precision NOT NULL CHECK (threshold > 0 AND threshold <= 1),
  item_hash text NOT NULL CHECK (item_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_module_diagnostic_items_session_key UNIQUE (session_id, item_key),
  CONSTRAINT uq_tutor_module_diagnostic_items_session_order UNIQUE (session_id, order_index),
  CONSTRAINT uq_tutor_module_diagnostic_items_id_scope UNIQUE (id, session_id, user_id, track_id),
  CONSTRAINT fk_tutor_module_diagnostic_item_session_scope
    FOREIGN KEY (session_id, user_id, track_id)
    REFERENCES tutor_module_diagnostic_sessions(id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_module_diagnostic_item_node_scope
    FOREIGN KEY (source_plan_revision_id, track_id, user_id, knowledge_key)
    REFERENCES tutor_track_plan_nodes(revision_id, track_id, user_id, knowledge_key) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_exercise_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_type text NOT NULL CHECK (attempt_type IN ('run', 'submit', 'diagnostic_submit')),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  plan_revision_id uuid NOT NULL,
  expected_track_version integer NOT NULL CHECK (expected_track_version >= 1),
  expected_progress_version integer CHECK (expected_progress_version IS NULL OR expected_progress_version >= 1),
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid,
  document_id uuid,
  gate_binding_id uuid,
  diagnostic_session_id uuid,
  diagnostic_item_id uuid,
  exercise_version_id uuid NOT NULL REFERENCES tutor_exercise_versions(id) ON DELETE RESTRICT,
  submission_hash text NOT NULL CHECK (submission_hash ~ '^[0-9a-f]{64}$'),
  hint_state_hash text NOT NULL CHECK (hint_state_hash ~ '^[0-9a-f]{64}$'),
  independence text NOT NULL CHECK (independence IN ('independent', 'hinted', 'remediated')),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  accepted_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_attempts_id_user UNIQUE (id, user_id),
  CONSTRAINT uq_tutor_exercise_attempts_id_exercise UNIQUE (id, user_id, exercise_version_id),
  CONSTRAINT uq_tutor_exercise_attempts_id_scope UNIQUE (id, user_id, track_id, exercise_version_id),
  CONSTRAINT uq_tutor_exercise_attempts_idempotency UNIQUE (user_id, attempt_type, idempotency_key),
  CONSTRAINT fk_tutor_exercise_attempt_track_user
    FOREIGN KEY (track_id, user_id) REFERENCES tutor_learning_tracks(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_revision_scope
    FOREIGN KEY (plan_revision_id, track_id, user_id)
    REFERENCES tutor_track_plan_revisions(id, track_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_assignment_scope
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_binding_scope
    FOREIGN KEY (gate_binding_id, document_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_gate_bindings(id, document_id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_attempt_diagnostic_item_scope
    FOREIGN KEY (diagnostic_item_id, diagnostic_session_id, user_id, track_id)
    REFERENCES tutor_module_diagnostic_items(id, session_id, user_id, track_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_exercise_attempts_owner_shape CHECK (
    (
      attempt_type IN ('run', 'submit')
      AND lesson_assignment_id IS NOT NULL AND document_id IS NOT NULL AND gate_binding_id IS NOT NULL
      AND diagnostic_session_id IS NULL AND diagnostic_item_id IS NULL
      AND expected_progress_version IS NOT NULL
    )
    OR (
      attempt_type = 'diagnostic_submit'
      AND lesson_assignment_id IS NULL AND document_id IS NULL AND gate_binding_id IS NULL
      AND diagnostic_session_id IS NOT NULL AND diagnostic_item_id IS NOT NULL
      AND expected_progress_version IS NULL
    )
  )
);

CREATE TABLE IF NOT EXISTS tutor_exercise_attempt_submissions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  exercise_version_id uuid NOT NULL,
  submission_kind text NOT NULL CHECK (submission_kind IN ('code', 'sql', 'structured_answer')),
  content_text text NOT NULL CHECK (char_length(content_text) BETWEEN 1 AND 48000),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_attempt_submissions_id_scope UNIQUE (id, attempt_id, user_id, exercise_version_id),
  CONSTRAINT fk_tutor_exercise_attempt_submission_scope
    FOREIGN KEY (attempt_id, user_id, exercise_version_id)
    REFERENCES tutor_exercise_attempts(id, user_id, exercise_version_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_exercise_attempt_results (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  attempt_id uuid NOT NULL UNIQUE,
  user_id uuid NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('passed', 'failed', 'timed_out', 'cancelled', 'unavailable', 'invalid')),
  score double precision NOT NULL CHECK (score >= 0 AND score <= 1),
  safe_feedback_json jsonb NOT NULL CHECK (jsonb_typeof(safe_feedback_json) = 'object'),
  capability_scores_json jsonb NOT NULL CHECK (jsonb_typeof(capability_scores_json) = 'object'),
  execution_receipt_hash text CHECK (execution_receipt_hash IS NULL OR execution_receipt_hash ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL CHECK (policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  terminal_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_attempt_results_id_scope UNIQUE (id, attempt_id, user_id),
  CONSTRAINT fk_tutor_exercise_attempt_result_scope
    FOREIGN KEY (attempt_id, user_id) REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tutor_exercise_hint_receipts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  track_id uuid NOT NULL,
  knowledge_key text NOT NULL CHECK (knowledge_key ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  lesson_assignment_id uuid NOT NULL,
  gate_binding_id uuid NOT NULL,
  hint_level integer NOT NULL CHECK (hint_level BETWEEN 1 AND 3),
  hint_policy_version text NOT NULL CHECK (hint_policy_version ~ '^[a-z0-9][a-z0-9._:-]{0,159}$'),
  safe_hint_json jsonb NOT NULL CHECK (jsonb_typeof(safe_hint_json) = 'object'),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_exercise_hint_receipts_idempotency UNIQUE (user_id, lesson_assignment_id, gate_binding_id, idempotency_key),
  CONSTRAINT fk_tutor_exercise_hint_assignment_scope
    FOREIGN KEY (lesson_assignment_id, user_id, track_id, knowledge_key)
    REFERENCES tutor_lesson_assignments(id, user_id, track_id, knowledge_key) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_hint_binding
    FOREIGN KEY (gate_binding_id) REFERENCES tutor_lesson_gate_bindings(id) ON DELETE RESTRICT
);

-- Add the Gate source/owner to the existing executor queue without weakening the legacy path.
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS source_kind text NOT NULL DEFAULT 'tutor_message';
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS exercise_attempt_id uuid;
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS exercise_submission_id uuid;
ALTER TABLE tutor_execution_intents ADD COLUMN IF NOT EXISTS exercise_version_id uuid;
ALTER TABLE tutor_execution_intents ALTER COLUMN conversation_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN run_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN source_message_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN exercise_id DROP NOT NULL;
ALTER TABLE tutor_execution_intents ALTER COLUMN input_revision DROP NOT NULL;
ALTER TABLE tutor_execution_intents DROP CONSTRAINT IF EXISTS tutor_execution_intents_origin_check;
ALTER TABLE tutor_execution_intents
  ADD CONSTRAINT tutor_execution_intents_origin_check CHECK (origin IN ('interactive', 'proactive', 'exercise_gate'));

DO $$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT conname FROM pg_constraint
    WHERE conrelid = 'tutor_execution_intents'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%consumed_at IS NULL%consumed_by_effect_id IS NULL%'
  LOOP
    EXECUTE format('ALTER TABLE tutor_execution_intents DROP CONSTRAINT %I', item.conname);
  END LOOP;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'chk_tutor_execution_intents_source_shape'
  ) THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT chk_tutor_execution_intents_source_shape CHECK (
      (
        source_kind = 'tutor_message'
        AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND source_message_id IS NOT NULL
        AND exercise_id IS NOT NULL AND input_revision IS NOT NULL
        AND exercise_attempt_id IS NULL AND exercise_submission_id IS NULL AND exercise_version_id IS NULL
        AND origin IN ('interactive', 'proactive')
        AND ((consumed_at IS NULL) = (consumed_by_effect_id IS NULL))
      )
      OR (
        source_kind = 'exercise_submission'
        AND conversation_id IS NULL AND run_id IS NULL AND source_message_id IS NULL AND exercise_id IS NULL
        AND input_revision IS NULL AND origin = 'exercise_gate'
        AND exercise_attempt_id IS NOT NULL AND exercise_submission_id IS NOT NULL AND exercise_version_id IS NOT NULL
        AND consumed_by_effect_id IS NULL
      )
    ) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'uq_tutor_execution_intents_gate_scope'
  ) THEN
    ALTER TABLE tutor_execution_intents
      ADD CONSTRAINT uq_tutor_execution_intents_gate_scope UNIQUE (id, exercise_attempt_id, user_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'fk_tutor_execution_intent_gate_attempt'
  ) THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_gate_attempt
      FOREIGN KEY (exercise_attempt_id, user_id)
      REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_intents'::regclass
      AND conname = 'fk_tutor_execution_intent_gate_submission'
  ) THEN
    ALTER TABLE tutor_execution_intents ADD CONSTRAINT fk_tutor_execution_intent_gate_submission
      FOREIGN KEY (exercise_submission_id, exercise_attempt_id, user_id, exercise_version_id)
      REFERENCES tutor_exercise_attempt_submissions(id, attempt_id, user_id, exercise_version_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

ALTER TABLE tutor_execution_jobs ADD COLUMN IF NOT EXISTS owner_kind text NOT NULL DEFAULT 'tutor_effect';
ALTER TABLE tutor_execution_jobs ADD COLUMN IF NOT EXISTS exercise_attempt_id uuid;
ALTER TABLE tutor_execution_jobs ALTER COLUMN effect_record_id DROP NOT NULL;
ALTER TABLE tutor_execution_jobs ALTER COLUMN effect_key DROP NOT NULL;
ALTER TABLE tutor_execution_jobs ALTER COLUMN conversation_id DROP NOT NULL;
ALTER TABLE tutor_execution_jobs ALTER COLUMN run_id DROP NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'chk_tutor_execution_jobs_owner_shape'
  ) THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT chk_tutor_execution_jobs_owner_shape CHECK (
      (
        owner_kind = 'tutor_effect'
        AND effect_record_id IS NOT NULL AND effect_key IS NOT NULL
        AND conversation_id IS NOT NULL AND run_id IS NOT NULL AND exercise_attempt_id IS NULL
      )
      OR (
        owner_kind = 'exercise_attempt'
        AND effect_record_id IS NULL AND effect_key IS NULL
        AND conversation_id IS NULL AND run_id IS NULL AND exercise_attempt_id IS NOT NULL
      )
    ) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'uq_tutor_execution_jobs_gate_scope'
  ) THEN
    ALTER TABLE tutor_execution_jobs
      ADD CONSTRAINT uq_tutor_execution_jobs_gate_scope UNIQUE (id, exercise_attempt_id, user_id);
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'fk_tutor_execution_job_gate_intent_scope'
  ) THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_gate_intent_scope
      FOREIGN KEY (intent_id, exercise_attempt_id, user_id)
      REFERENCES tutor_execution_intents(id, exercise_attempt_id, user_id)
      ON DELETE RESTRICT NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conrelid = 'tutor_execution_jobs'::regclass
      AND conname = 'fk_tutor_execution_job_gate_attempt'
  ) THEN
    ALTER TABLE tutor_execution_jobs ADD CONSTRAINT fk_tutor_execution_job_gate_attempt
      FOREIGN KEY (exercise_attempt_id, user_id)
      REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT NOT VALID;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tutor_exercise_execution_links (
  attempt_id uuid PRIMARY KEY,
  user_id uuid NOT NULL,
  execution_intent_id uuid NOT NULL UNIQUE REFERENCES tutor_execution_intents(id) ON DELETE RESTRICT,
  execution_job_id uuid NOT NULL UNIQUE REFERENCES tutor_execution_jobs(id) ON DELETE RESTRICT,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_exercise_execution_link_attempt
    FOREIGN KEY (attempt_id, user_id) REFERENCES tutor_exercise_attempts(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_execution_link_intent_scope
    FOREIGN KEY (execution_intent_id, attempt_id, user_id)
    REFERENCES tutor_execution_intents(id, exercise_attempt_id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_exercise_execution_link_job_scope
    FOREIGN KEY (execution_job_id, attempt_id, user_id)
    REFERENCES tutor_execution_jobs(id, exercise_attempt_id, user_id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION enforce_tutor_practice_shared_immutable()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Practice shared authority rows are immutable' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_practice_user_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
  RAISE EXCEPTION 'Practice user facts are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_lesson_gate_state_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Lesson Gate state cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.knowledge_key IS DISTINCT FROM OLD.knowledge_key
     OR NEW.lesson_assignment_id IS DISTINCT FROM OLD.lesson_assignment_id
     OR NEW.document_id IS DISTINCT FROM OLD.document_id OR NEW.gate_binding_id IS DISTINCT FROM OLD.gate_binding_id
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Lesson Gate state identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'passed' AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Passed Lesson Gate state is immutable' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_module_diagnostic_session_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_learning_track_purge_allowed(OLD.user_id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Module diagnostic session cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.user_id IS DISTINCT FROM OLD.user_id
     OR NEW.track_id IS DISTINCT FROM OLD.track_id OR NEW.module_key IS DISTINCT FROM OLD.module_key
     OR NEW.diagnostic_version_id IS DISTINCT FROM OLD.diagnostic_version_id
     OR NEW.source_plan_revision_id IS DISTINCT FROM OLD.source_plan_revision_id
     OR NEW.expected_track_version IS DISTINCT FROM OLD.expected_track_version
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key OR NEW.request_hash IS DISTINCT FROM OLD.request_hash
     OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'Module diagnostic session identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state IN ('failed', 'confirmed', 'expired') AND NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'Terminal module diagnostic session is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.state = 'active' AND NEW.state IN ('active', 'failed', 'passed_pending_confirmation', 'expired') THEN RETURN NEW; END IF;
  IF OLD.state = 'passed_pending_confirmation' AND NEW.state IN ('passed_pending_confirmation', 'confirmed', 'expired') THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Module diagnostic session transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_exercise_versions_immutable ON tutor_exercise_versions;
CREATE TRIGGER trg_tutor_exercise_versions_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_versions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_shared_immutable();
DROP TRIGGER IF EXISTS trg_tutor_exercise_private_rubrics_immutable ON tutor_exercise_private_rubrics;
CREATE TRIGGER trg_tutor_exercise_private_rubrics_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_private_rubrics
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_shared_immutable();
DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_bindings_immutable ON tutor_lesson_gate_bindings;
CREATE TRIGGER trg_tutor_lesson_gate_bindings_immutable
BEFORE UPDATE OR DELETE ON tutor_lesson_gate_bindings
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_versions_immutable ON tutor_module_diagnostic_versions;
CREATE TRIGGER trg_tutor_module_diagnostic_versions_immutable
BEFORE UPDATE OR DELETE ON tutor_module_diagnostic_versions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_shared_immutable();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_items_immutable ON tutor_module_diagnostic_items;
CREATE TRIGGER trg_tutor_module_diagnostic_items_immutable
BEFORE UPDATE OR DELETE ON tutor_module_diagnostic_items
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_attempts_immutable ON tutor_exercise_attempts;
CREATE TRIGGER trg_tutor_exercise_attempts_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_attempts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_attempt_submissions_immutable ON tutor_exercise_attempt_submissions;
CREATE TRIGGER trg_tutor_exercise_attempt_submissions_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_attempt_submissions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_attempt_results_immutable ON tutor_exercise_attempt_results;
CREATE TRIGGER trg_tutor_exercise_attempt_results_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_attempt_results
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_hint_receipts_immutable ON tutor_exercise_hint_receipts;
CREATE TRIGGER trg_tutor_exercise_hint_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_hint_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_exercise_execution_links_immutable ON tutor_exercise_execution_links;
CREATE TRIGGER trg_tutor_exercise_execution_links_immutable
BEFORE UPDATE OR DELETE ON tutor_exercise_execution_links
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_practice_user_append_only();
DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_states_updated_at ON tutor_lesson_gate_states;
CREATE TRIGGER trg_tutor_lesson_gate_states_updated_at BEFORE UPDATE ON tutor_lesson_gate_states
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_lesson_gate_states_lifecycle ON tutor_lesson_gate_states;
CREATE TRIGGER trg_tutor_lesson_gate_states_lifecycle BEFORE UPDATE OR DELETE ON tutor_lesson_gate_states
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_lesson_gate_state_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_sessions_updated_at ON tutor_module_diagnostic_sessions;
CREATE TRIGGER trg_tutor_module_diagnostic_sessions_updated_at BEFORE UPDATE ON tutor_module_diagnostic_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
DROP TRIGGER IF EXISTS trg_tutor_module_diagnostic_sessions_lifecycle ON tutor_module_diagnostic_sessions;
CREATE TRIGGER trg_tutor_module_diagnostic_sessions_lifecycle BEFORE UPDATE OR DELETE ON tutor_module_diagnostic_sessions
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_module_diagnostic_session_lifecycle();

CREATE INDEX IF NOT EXISTS idx_tutor_lesson_gate_states_assignment
  ON tutor_lesson_gate_states(lesson_assignment_id, state, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_exercise_attempts_gate
  ON tutor_exercise_attempts(lesson_assignment_id, gate_binding_id, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_exercise_attempts_diagnostic
  ON tutor_exercise_attempts(diagnostic_session_id, diagnostic_item_id, accepted_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_module_diagnostic_sessions_track
  ON tutor_module_diagnostic_sessions(track_id, module_key, created_at DESC);


-- Unified controlled Action Runtime: orchestration metadata only. Domain truth remains in capability,
-- plan, effect, and execution owner tables referenced by authority_kind/authority_id.
CREATE TABLE IF NOT EXISTS tutor_action_invocations (
  id text PRIMARY KEY CHECK (char_length(id) BETWEEN 1 AND 160),
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  lease_owner_id text NOT NULL,
  lease_generation integer NOT NULL CHECK (lease_generation > 0),
  action_generation integer NOT NULL CHECK (action_generation > 0),
  idempotency_key text NOT NULL CHECK (char_length(idempotency_key) BETWEEN 1 AND 160),
  stable_action_key text NOT NULL CHECK (char_length(stable_action_key) BETWEEN 1 AND 160),
  action_id text NOT NULL CHECK (char_length(action_id) BETWEEN 1 AND 120),
  action_version text NOT NULL CHECK (char_length(action_version) BETWEEN 1 AND 80),
  descriptor_hash text NOT NULL CHECK (descriptor_hash ~ '^[0-9a-f]{64}$'),
  owner_adapter_id text NOT NULL CHECK (char_length(owner_adapter_id) BETWEEN 1 AND 120),
  task_kind text NOT NULL CHECK (char_length(task_kind) BETWEEN 1 AND 120),
  origin text NOT NULL CHECK (origin IN ('interactive', 'proactive', 'exercise_gate')),
  catalog_digest text NOT NULL CHECK (catalog_digest ~ '^[0-9a-f]{64}$'),
  policy_fingerprint text NOT NULL CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  selected_skill_reference text CHECK (selected_skill_reference IS NULL OR char_length(selected_skill_reference) BETWEEN 1 AND 160),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  resource_profile_hash text NOT NULL CHECK (resource_profile_hash ~ '^[0-9a-f]{64}$'),
  resource_request_hash text NOT NULL CHECK (resource_request_hash ~ '^[0-9a-f]{64}$'),
  parent_invocation_id text,
  retry_index integer NOT NULL DEFAULT 0 CHECK (retry_index >= 0),
  status text NOT NULL CHECK (status IN (
    'requested', 'admitted', 'running', 'succeeded_unverified', 'verified',
    'retryable_failed', 'permanent_failed', 'denied', 'cancel_requested',
    'cancelled', 'timed_out', 'superseded'
  )),
  requested_at timestamptz NOT NULL,
  admitted_at timestamptz,
  started_at timestamptz,
  terminal_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_action_invocations_run_key UNIQUE (run_id, idempotency_key),
  CONSTRAINT uq_tutor_action_invocations_id_run UNIQUE (id, run_id),
  CONSTRAINT fk_tutor_action_invocation_parent_run
    FOREIGN KEY (parent_invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_invocation_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_invocation_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_invocations_parent_distinct CHECK (parent_invocation_id IS NULL OR parent_invocation_id <> id),
  CONSTRAINT chk_tutor_action_invocations_terminal CHECK (
    (status IN ('verified', 'retryable_failed', 'permanent_failed', 'denied', 'cancelled', 'timed_out', 'superseded'))
      = (terminal_at IS NOT NULL)
  )
);

ALTER TABLE tutor_action_invocations
  ADD COLUMN IF NOT EXISTS lease_owner_id text;
UPDATE tutor_action_invocations AS invocations
SET lease_owner_id = COALESCE(runs.active_lease_owner_id, 'legacy-action-owner')
FROM tutor_runs AS runs
WHERE invocations.run_id = runs.id AND invocations.lease_owner_id IS NULL;
ALTER TABLE tutor_action_invocations
  ALTER COLUMN lease_owner_id SET NOT NULL;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'chk_tutor_action_invocations_lease_owner'
  ) THEN
    ALTER TABLE tutor_action_invocations
      ADD CONSTRAINT chk_tutor_action_invocations_lease_owner
      CHECK (char_length(lease_owner_id) BETWEEN 1 AND 160);
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS tutor_action_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invocation_id text NOT NULL REFERENCES tutor_action_invocations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  attempt_index integer NOT NULL CHECK (attempt_index >= 1),
  status text NOT NULL CHECK (status IN (
    'succeeded', 'retryable_failed', 'permanent_failed', 'denied',
    'cancelled', 'timed_out', 'superseded'
  )),
  authority_kind text CHECK (authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result'
  )),
  authority_id text CHECK (authority_id IS NULL OR char_length(authority_id) BETWEEN 1 AND 160),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  result_hash text NOT NULL CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  safe_result_json jsonb NOT NULL,
  diagnostic_code text CHECK (diagnostic_code IS NULL OR char_length(diagnostic_code) BETWEEN 1 AND 160),
  duration_ms integer NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT uq_tutor_action_attempts_identity UNIQUE (invocation_id, attempt_index),
  CONSTRAINT fk_tutor_action_attempt_invocation_run
    FOREIGN KEY (invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_attempt_authority CHECK ((authority_kind IS NULL) = (authority_id IS NULL))
);

CREATE TABLE IF NOT EXISTS tutor_action_verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  invocation_id text NOT NULL UNIQUE REFERENCES tutor_action_invocations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  status text NOT NULL CHECK (status IN ('pending', 'verified', 'failed', 'not_required')),
  verifier_id text NOT NULL CHECK (char_length(verifier_id) BETWEEN 1 AND 120),
  verifier_version text NOT NULL CHECK (char_length(verifier_version) BETWEEN 1 AND 80),
  authority_kind text CHECK (authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result'
  )),
  authority_id text CHECK (authority_id IS NULL OR char_length(authority_id) BETWEEN 1 AND 160),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  verification_hash text NOT NULL CHECK (verification_hash ~ '^[0-9a-f]{64}$'),
  safe_verification_json jsonb NOT NULL,
  diagnostic_code text CHECK (diagnostic_code IS NULL OR char_length(diagnostic_code) BETWEEN 1 AND 160),
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_action_verification_invocation_run
    FOREIGN KEY (invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_verification_authority CHECK ((authority_kind IS NULL) = (authority_id IS NULL))
);

CREATE TABLE IF NOT EXISTS tutor_action_receipts (
  invocation_id text PRIMARY KEY REFERENCES tutor_action_invocations(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL REFERENCES tutor_runs(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  conversation_id uuid NOT NULL REFERENCES tutor_conversations(id) ON DELETE RESTRICT,
  input_revision integer NOT NULL CHECK (input_revision >= 0),
  stable_action_key text NOT NULL CHECK (char_length(stable_action_key) BETWEEN 1 AND 160),
  action_id text NOT NULL CHECK (char_length(action_id) BETWEEN 1 AND 120),
  action_version text NOT NULL CHECK (char_length(action_version) BETWEEN 1 AND 80),
  status text NOT NULL CHECK (status IN (
    'verified', 'retryable_failed', 'permanent_failed', 'denied',
    'cancelled', 'timed_out', 'superseded'
  )),
  authority_kind text CHECK (authority_kind IS NULL OR authority_kind IN (
    'capability_invocation', 'plan_draft', 'execution_job', 'effect_receipt', 'grounding_result'
  )),
  authority_id text CHECK (authority_id IS NULL OR char_length(authority_id) BETWEEN 1 AND 160),
  authority_hash text CHECK (authority_hash IS NULL OR authority_hash ~ '^[0-9a-f]{64}$'),
  safe_summary text NOT NULL CHECK (char_length(safe_summary) <= 160),
  result_hash text CHECK (result_hash IS NULL OR result_hash ~ '^[0-9a-f]{64}$'),
  verification_status text NOT NULL CHECK (verification_status IN ('pending', 'verified', 'failed', 'not_required')),
  verification_hash text CHECK (verification_hash IS NULL OR verification_hash ~ '^[0-9a-f]{64}$'),
  diagnostic_code text CHECK (diagnostic_code IS NULL OR char_length(diagnostic_code) BETWEEN 1 AND 160),
  recovery_kind text NOT NULL CHECK (recovery_kind IN ('none', 'retry', 'rebuild_context', 'request_clarification', 'safe_stop')),
  recovery_code text NOT NULL CHECK (char_length(recovery_code) BETWEEN 1 AND 160),
  retry_after_seconds integer NOT NULL DEFAULT 0 CHECK (retry_after_seconds BETWEEN 0 AND 300),
  receipt_json jsonb NOT NULL,
  receipt_hash text NOT NULL CHECK (receipt_hash ~ '^[0-9a-f]{64}$'),
  terminal_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT fk_tutor_action_receipt_invocation_run
    FOREIGN KEY (invocation_id, run_id) REFERENCES tutor_action_invocations(id, run_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_receipt_run_user
    FOREIGN KEY (run_id, user_id) REFERENCES tutor_runs(id, user_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tutor_action_receipt_run_conversation
    FOREIGN KEY (run_id, conversation_id) REFERENCES tutor_runs(id, conversation_id) ON DELETE RESTRICT,
  CONSTRAINT chk_tutor_action_receipt_authority CHECK ((authority_kind IS NULL) = (authority_id IS NULL)),
  CONSTRAINT chk_tutor_action_receipt_retry CHECK (
    (recovery_kind = 'retry' AND retry_after_seconds >= 0)
    OR (recovery_kind <> 'retry' AND retry_after_seconds = 0)
  )
);

CREATE INDEX IF NOT EXISTS idx_tutor_action_invocations_run_created
  ON tutor_action_invocations(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tutor_action_invocations_state_created
  ON tutor_action_invocations(status, created_at);
CREATE INDEX IF NOT EXISTS idx_tutor_action_receipts_run_terminal
  ON tutor_action_receipts(run_id, terminal_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_tutor_action_receipts_current_verified
  ON tutor_action_receipts(run_id, input_revision, stable_action_key)
  WHERE status = 'verified';

CREATE OR REPLACE FUNCTION tutor_action_purge_allowed(target_invocation_id text)
RETURNS boolean AS $$
DECLARE
  target_user_id uuid;
BEGIN
  SELECT user_id INTO target_user_id
  FROM tutor_action_invocations
  WHERE id = target_invocation_id;
  RETURN target_user_id IS NOT NULL AND tutor_learning_track_purge_allowed(target_user_id);
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_action_append_only()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' AND tutor_action_purge_allowed(OLD.invocation_id) THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'Tutor action attempt, verification, and receipt rows are append-only' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION enforce_tutor_action_invocation_lifecycle()
RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF tutor_action_purge_allowed(OLD.id) THEN RETURN OLD; END IF;
    RAISE EXCEPTION 'Tutor action invocations cannot be deleted' USING ERRCODE = '23514';
  END IF;
  IF OLD.id IS DISTINCT FROM NEW.id
     OR OLD.run_id IS DISTINCT FROM NEW.run_id
     OR OLD.conversation_id IS DISTINCT FROM NEW.conversation_id
     OR OLD.user_id IS DISTINCT FROM NEW.user_id
     OR OLD.input_revision IS DISTINCT FROM NEW.input_revision
     OR OLD.lease_owner_id IS DISTINCT FROM NEW.lease_owner_id
     OR OLD.lease_generation IS DISTINCT FROM NEW.lease_generation
     OR OLD.action_generation IS DISTINCT FROM NEW.action_generation
     OR OLD.idempotency_key IS DISTINCT FROM NEW.idempotency_key
     OR OLD.stable_action_key IS DISTINCT FROM NEW.stable_action_key
     OR OLD.action_id IS DISTINCT FROM NEW.action_id
     OR OLD.action_version IS DISTINCT FROM NEW.action_version
     OR OLD.descriptor_hash IS DISTINCT FROM NEW.descriptor_hash
     OR OLD.owner_adapter_id IS DISTINCT FROM NEW.owner_adapter_id
     OR OLD.task_kind IS DISTINCT FROM NEW.task_kind
     OR OLD.origin IS DISTINCT FROM NEW.origin
     OR OLD.catalog_digest IS DISTINCT FROM NEW.catalog_digest
     OR OLD.policy_fingerprint IS DISTINCT FROM NEW.policy_fingerprint
     OR OLD.selected_skill_reference IS DISTINCT FROM NEW.selected_skill_reference
     OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
     OR OLD.resource_profile_hash IS DISTINCT FROM NEW.resource_profile_hash
     OR OLD.resource_request_hash IS DISTINCT FROM NEW.resource_request_hash
     OR OLD.parent_invocation_id IS DISTINCT FROM NEW.parent_invocation_id
     OR OLD.retry_index IS DISTINCT FROM NEW.retry_index
     OR OLD.requested_at IS DISTINCT FROM NEW.requested_at
     OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
    RAISE EXCEPTION 'Tutor action invocation identity is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status IN ('verified', 'retryable_failed', 'permanent_failed', 'denied', 'cancelled', 'timed_out', 'superseded') THEN
    RAISE EXCEPTION 'Terminal Tutor action invocation is immutable' USING ERRCODE = '23514';
  END IF;
  IF OLD.status = 'requested' AND NEW.status IN ('admitted', 'denied') THEN RETURN NEW; END IF;
  IF OLD.status = 'admitted' AND NEW.status IN ('running', 'cancel_requested', 'superseded') THEN RETURN NEW; END IF;
  IF OLD.status = 'running' AND NEW.status IN (
    'succeeded_unverified', 'retryable_failed', 'permanent_failed', 'denied',
    'timed_out', 'cancel_requested', 'superseded'
  ) THEN RETURN NEW; END IF;
  IF OLD.status = 'cancel_requested' AND NEW.status IN ('cancelled', 'succeeded_unverified') THEN RETURN NEW; END IF;
  IF OLD.status = 'succeeded_unverified' AND NEW.status IN (
    'verified', 'retryable_failed', 'permanent_failed', 'cancel_requested', 'superseded'
  ) THEN RETURN NEW; END IF;
  RAISE EXCEPTION 'Tutor action invocation lifecycle transition is invalid' USING ERRCODE = '23514';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_tutor_action_attempts_immutable ON tutor_action_attempts;
CREATE TRIGGER trg_tutor_action_attempts_immutable
BEFORE UPDATE OR DELETE ON tutor_action_attempts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_append_only();
DROP TRIGGER IF EXISTS trg_tutor_action_verifications_immutable ON tutor_action_verifications;
CREATE TRIGGER trg_tutor_action_verifications_immutable
BEFORE UPDATE OR DELETE ON tutor_action_verifications
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_append_only();
DROP TRIGGER IF EXISTS trg_tutor_action_receipts_immutable ON tutor_action_receipts;
CREATE TRIGGER trg_tutor_action_receipts_immutable
BEFORE UPDATE OR DELETE ON tutor_action_receipts
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_append_only();
DROP TRIGGER IF EXISTS trg_tutor_action_invocations_lifecycle ON tutor_action_invocations;
CREATE TRIGGER trg_tutor_action_invocations_lifecycle
BEFORE UPDATE OR DELETE ON tutor_action_invocations
FOR EACH ROW EXECUTE FUNCTION enforce_tutor_action_invocation_lifecycle();
DROP TRIGGER IF EXISTS trg_tutor_action_invocations_updated_at ON tutor_action_invocations;
CREATE TRIGGER trg_tutor_action_invocations_updated_at
BEFORE UPDATE ON tutor_action_invocations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
