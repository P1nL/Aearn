CREATE TABLE IF NOT EXISTS teaching_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE CASCADE,
  chunk_type text NOT NULL CHECK (chunk_type IN ('outline', 'example', 'explanation', 'source_note')),
  title text NOT NULL,
  content text NOT NULL,
  source_url text,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(content, '')), 'B')
  ) STORED,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_teaching_chunks_kp ON teaching_chunks(knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_teaching_chunks_search ON teaching_chunks USING GIN(search_vector);

CREATE TABLE IF NOT EXISTS grounding_chunks (
  chunk_id text PRIMARY KEY,
  source_id text NOT NULL,
  language_id text NOT NULL,
  title text NOT NULL,
  section_path_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  canonical_url text NOT NULL,
  source_type text NOT NULL CHECK (source_type IN ('tutorial', 'reference', 'spec', 'platform_docs', 'vendor_docs')),
  source_trust_tier text NOT NULL CHECK (source_trust_tier IN ('official', 'trusted_de_facto', 'internal')),
  fetched_at timestamptz NOT NULL,
  source_version_label text NOT NULL DEFAULT 'unversioned' CHECK (char_length(source_version_label) BETWEEN 1 AND 160),
  source_version_kind text NOT NULL DEFAULT 'rolling' CHECK (source_version_kind IN ('fixed', 'rolling')),
  document_content_hash text NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000' CHECK (document_content_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL,
  content text NOT NULL,
  topic_tags_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(content, '')), 'B')
  ) STORED,
  metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);


ALTER TABLE grounding_chunks
  ADD COLUMN IF NOT EXISTS source_version_label text NOT NULL DEFAULT 'unversioned',
  ADD COLUMN IF NOT EXISTS source_version_kind text NOT NULL DEFAULT 'rolling',
  ADD COLUMN IF NOT EXISTS document_content_hash text NOT NULL DEFAULT '0000000000000000000000000000000000000000000000000000000000000000';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_grounding_chunks_source_version_kind') THEN
    ALTER TABLE grounding_chunks ADD CONSTRAINT chk_grounding_chunks_source_version_kind
      CHECK (source_version_kind IN ('fixed', 'rolling'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chk_grounding_chunks_document_content_hash') THEN
    ALTER TABLE grounding_chunks ADD CONSTRAINT chk_grounding_chunks_document_content_hash
      CHECK (document_content_hash ~ '^[0-9a-f]{64}$');
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS grounding_reindex_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mode text NOT NULL CHECK (mode IN ('fixture', 'fetch')),
  status text NOT NULL CHECK (status IN ('completed', 'completed_with_failures', 'failed')),
  total_sources integer NOT NULL DEFAULT 0 CHECK (total_sources >= 0),
  total_documents integer NOT NULL DEFAULT 0 CHECK (total_documents >= 0),
  total_chunks integer NOT NULL DEFAULT 0 CHECK (total_chunks >= 0),
  total_failures integer NOT NULL DEFAULT 0 CHECK (total_failures >= 0),
  source_reports_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_grounding_chunks_language ON grounding_chunks(language_id);
CREATE INDEX IF NOT EXISTS idx_grounding_chunks_source ON grounding_chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_grounding_chunks_search ON grounding_chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_grounding_reindex_runs_created ON grounding_reindex_runs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_review_logs_kp_reviewed ON review_logs(knowledge_point_id, reviewed_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_logs_request_id ON review_logs(request_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_logs_attempt_rating_source ON review_logs(attempt_id, rating, source);
CREATE INDEX IF NOT EXISTS idx_notes_user_updated ON notes(user_id, updated_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_notes_knowledge_point ON notes(knowledge_point_id) WHERE deleted_at IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_notes_user_knowledge_point_active ON notes(user_id, knowledge_point_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_idempotency_records_operation ON idempotency_records(operation);
CREATE INDEX IF NOT EXISTS idx_idempotency_records_user_active ON idempotency_records(user_id) WHERE invalidated_at IS NULL;

DROP TRIGGER IF EXISTS trg_users_updated_at ON users;
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_runtime_profiles_updated_at ON runtime_profiles;
CREATE TRIGGER trg_runtime_profiles_updated_at BEFORE UPDATE ON runtime_profiles
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_language_courses_updated_at ON language_courses;
CREATE TRIGGER trg_language_courses_updated_at BEFORE UPDATE ON language_courses
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_learning_plans_updated_at ON learning_plans;
CREATE TRIGGER trg_learning_plans_updated_at BEFORE UPDATE ON learning_plans
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_plan_modules_updated_at ON plan_modules;
CREATE TRIGGER trg_plan_modules_updated_at BEFORE UPDATE ON plan_modules
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_knowledge_points_updated_at ON knowledge_points;
CREATE TRIGGER trg_knowledge_points_updated_at BEFORE UPDATE ON knowledge_points
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_exercises_updated_at ON exercises;
CREATE TRIGGER trg_exercises_updated_at BEFORE UPDATE ON exercises
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_test_cases_updated_at ON test_cases;
CREATE TRIGGER trg_test_cases_updated_at BEFORE UPDATE ON test_cases
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_learning_sessions_updated_at ON learning_sessions;
CREATE TRIGGER trg_learning_sessions_updated_at BEFORE UPDATE ON learning_sessions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_review_states_updated_at ON review_states;
CREATE TRIGGER trg_review_states_updated_at BEFORE UPDATE ON review_states
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_review_seed_banks_updated_at ON review_seed_banks;
CREATE TRIGGER trg_review_seed_banks_updated_at BEFORE UPDATE ON review_seed_banks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_notes_updated_at ON notes;
CREATE TRIGGER trg_notes_updated_at BEFORE UPDATE ON notes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_grounding_chunks_updated_at ON grounding_chunks;
CREATE TRIGGER trg_grounding_chunks_updated_at BEFORE UPDATE ON grounding_chunks
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
