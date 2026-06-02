CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL,
  learning_style text,
  teaching_preference text,
  encouragement_preference text,
  profession text,
  background_context text,
  preferred_time_slots jsonb NOT NULL DEFAULT '[]'::jsonb,
  reminder_preference jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS learner_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  weak_points jsonb NOT NULL DEFAULT '[]'::jsonb,
  error_patterns jsonb NOT NULL DEFAULT '[]'::jsonb,
  learning_preferences jsonb NOT NULL DEFAULT '{}'::jsonb,
  pace_indicators jsonb NOT NULL DEFAULT '{}'::jsonb,
  observations jsonb NOT NULL DEFAULT '[]'::jsonb,
  session_count integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT learner_profiles_user_id_key UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS runtime_profiles (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  runtime_tier text NOT NULL CHECK (runtime_tier IN ('browser_preview', 'python_stdout_test', 'compiled_sandbox_later')),
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'java', 'cpp', 'html_css')),
  runner text NOT NULL CHECK (runner IN ('browser', 'python', 'sandbox')),
  supports_realtime_preview boolean NOT NULL DEFAULT false,
  supports_stdout boolean NOT NULL DEFAULT false,
  supports_tests boolean NOT NULL DEFAULT false,
  compile_required boolean NOT NULL DEFAULT false,
  timeout_ms integer NOT NULL DEFAULT 5000 CHECK (timeout_ms BETWEEN 100 AND 60000),
  memory_limit_mb integer NOT NULL DEFAULT 128 CHECK (memory_limit_mb BETWEEN 16 AND 2048),
  sandbox_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz
);

CREATE TABLE IF NOT EXISTS language_courses (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE,
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'java', 'cpp', 'html_css')),
  title text NOT NULL,
  description text,
  level text NOT NULL CHECK (level IN ('beginner', 'intermediate', 'advanced')),
  runtime_profile_id uuid NOT NULL REFERENCES runtime_profiles(id) ON DELETE RESTRICT,
  supported_exercise_types_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz
);

CREATE TABLE IF NOT EXISTS learning_plans (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  language_course_id uuid NOT NULL REFERENCES language_courses(id) ON DELETE RESTRICT,
  goal_text text NOT NULL,
  language text NOT NULL CHECK (language IN ('javascript', 'python', 'java', 'cpp', 'html_css')),
  target_level text NOT NULL CHECK (target_level IN ('beginner', 'intermediate', 'advanced')),
  mode text NOT NULL CHECK (mode IN ('goal_based', 'material_based')),
  deadline date,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
  overall_progress numeric(5,4) NOT NULL DEFAULT 0 CHECK (overall_progress >= 0 AND overall_progress <= 1),
  current_module_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  archived_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS plan_modules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  title text NOT NULL,
  description text,
  order_index integer NOT NULL CHECK (order_index >= 0),
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'skipped')),
  is_skippable boolean NOT NULL DEFAULT true,
  is_adjustable boolean NOT NULL DEFAULT true,
  estimated_sessions integer NOT NULL DEFAULT 1 CHECK (estimated_sessions >= 1),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  archived_at timestamptz,
  deleted_at timestamptz
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'learning_plans_current_module_id_fkey'
  ) THEN
    ALTER TABLE learning_plans
      ADD CONSTRAINT learning_plans_current_module_id_fkey
      FOREIGN KEY (current_module_id) REFERENCES plan_modules(id) ON DELETE RESTRICT;
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS knowledge_points (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text UNIQUE,
  module_id uuid NOT NULL REFERENCES plan_modules(id) ON DELETE RESTRICT,
  language_course_id uuid NOT NULL REFERENCES language_courses(id) ON DELETE RESTRICT,
  title text NOT NULL,
  description text,
  order_index integer NOT NULL DEFAULT 0 CHECK (order_index >= 0),
  skill_tags_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  lesson_outline_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  lesson_sources_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'learning', 'reviewing', 'mastered')),
  mastery_score numeric(5,4) NOT NULL DEFAULT 0 CHECK (mastery_score >= 0 AND mastery_score <= 1),
  weak_points_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  effective_hint_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
  last_exercise_result text CHECK (last_exercise_result IN ('failed', 'partial', 'passed', 'easy')),
  last_exercise_score smallint CHECK (last_exercise_score BETWEEN 0 AND 8),
  last_exercise_breakdown_json jsonb,
  last_explanation_check_result jsonb,
  last_session_id uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS exercises (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text UNIQUE,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  runtime_profile_id uuid NOT NULL REFERENCES runtime_profiles(id) ON DELETE RESTRICT,
  title text NOT NULL,
  exercise_type text NOT NULL CHECK (exercise_type IN ('code_blank', 'fix_bug', 'implement_function', 'explain_code', 'review_ai_patch')),
  prompt_markdown text NOT NULL,
  starter_code text NOT NULL,
  solution_reference text,
  visible_test_policy text NOT NULL DEFAULT 'visible_and_hidden_summary'
    CHECK (visible_test_policy IN ('visible_only', 'visible_and_hidden_summary', 'hidden_only')),
  difficulty smallint NOT NULL DEFAULT 1 CHECK (difficulty BETWEEN 1 AND 5),
  estimated_minutes integer NOT NULL DEFAULT 10 CHECK (estimated_minutes BETWEEN 1 AND 240),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS code_blanks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_id uuid NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
  blank_key text NOT NULL,
  placeholder text NOT NULL,
  expected_concept text NOT NULL,
  acceptable_patterns_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  is_core boolean NOT NULL DEFAULT true,
  order_index integer NOT NULL CHECK (order_index >= 0),
  CONSTRAINT code_blanks_exercise_blank_key_key UNIQUE (exercise_id, blank_key),
  CONSTRAINT code_blanks_exercise_order_key UNIQUE (exercise_id, order_index)
);

CREATE TABLE IF NOT EXISTS test_cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  exercise_id uuid NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
  case_type text NOT NULL CHECK (case_type IN ('visible', 'hidden', 'preview_assertion')),
  input_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  expected_output_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  assertion_code text,
  weight numeric(6,2) NOT NULL DEFAULT 1 CHECK (weight > 0),
  is_critical boolean NOT NULL DEFAULT false,
  timeout_ms integer NOT NULL DEFAULT 5000 CHECK (timeout_ms BETWEEN 100 AND 60000),
  order_index integer NOT NULL CHECK (order_index >= 0),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  archived_at timestamptz,
  CONSTRAINT test_cases_exercise_order_key UNIQUE (exercise_id, order_index)
);

CREATE TABLE IF NOT EXISTS learning_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  session_type text NOT NULL CHECK (session_type IN ('learn', 'review')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'finished', 'abandoned')),
  started_at timestamptz NOT NULL DEFAULT now(),
  ended_at timestamptz,
  duration_seconds integer CHECK (duration_seconds >= 0),
  entry_point text NOT NULL,
  summary_text text,
  next_entry_point text,
  learning_stage text CHECK (learning_stage IS NULL OR learning_stage IN ('concept_intro', 'concept_check', 'concept_repair', 'practice_offer', 'concept_qna', 'readiness_check', 'practice_support')),
  learning_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  review_stage text CHECK (review_stage IS NULL OR review_stage IN ('warmup', 'warmup_repair', 'variant_practice', 'submitted')),
  review_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'knowledge_points_last_session_id_fkey'
  ) THEN
    ALTER TABLE knowledge_points
      ADD CONSTRAINT knowledge_points_last_session_id_fkey
      FOREIGN KEY (last_session_id) REFERENCES learning_sessions(id) ON DELETE SET NULL;
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  exercise_id uuid NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  attempt_type text NOT NULL CHECK (attempt_type IN ('run', 'submit', 'review_submit')),
  submit_version integer NOT NULL DEFAULT 1 CHECK (submit_version >= 1),
  submitted_code text NOT NULL,
  code_hash text NOT NULL,
  filled_blanks_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  runtime_status text NOT NULL CHECK (runtime_status IN ('success', 'runtime_error', 'timeout', 'unsupported')),
  test_pass_rate numeric(5,4) NOT NULL DEFAULT 0 CHECK (test_pass_rate >= 0 AND test_pass_rate <= 1),
  passed_test_count integer NOT NULL DEFAULT 0 CHECK (passed_test_count >= 0),
  total_test_count integer NOT NULL DEFAULT 0 CHECK (total_test_count >= 0),
  score smallint CHECK (score BETWEEN 0 AND 8),
  score_breakdown_json jsonb,
  code_completion_result jsonb,
  fsrs_rating text CHECK (fsrs_rating IN ('Again', 'Hard', 'Good', 'Easy')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_states (
  knowledge_point_id uuid PRIMARY KEY REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  card_state text NOT NULL DEFAULT 'new' CHECK (card_state IN ('new', 'learning', 'review', 'relearning')),
  stability numeric(10,4),
  difficulty numeric(10,4),
  due_at timestamptz,
  elapsed_days integer NOT NULL DEFAULT 0 CHECK (elapsed_days >= 0),
  scheduled_days integer NOT NULL DEFAULT 0 CHECK (scheduled_days >= 0),
  reps integer NOT NULL DEFAULT 0 CHECK (reps >= 0),
  lapses integer NOT NULL DEFAULT 0 CHECK (lapses >= 0),
  last_review_at timestamptz,
  last_attempt_id uuid REFERENCES attempts(id) ON DELETE RESTRICT,
  fsrs_parameters jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_seed_banks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  generator_version text NOT NULL,
  status text NOT NULL DEFAULT 'generating' CHECK (status IN ('generating', 'ready', 'failed')),
  seed_count integer NOT NULL DEFAULT 0 CHECK (seed_count >= 0),
  seeds_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  quality_report_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  failure_code text,
  failure_message text,
  generated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  plan_id uuid NOT NULL REFERENCES learning_plans(id) ON DELETE RESTRICT,
  attempt_id uuid NOT NULL REFERENCES attempts(id) ON DELETE RESTRICT,
  rating text NOT NULL CHECK (rating IN ('Again', 'Hard', 'Good', 'Easy')),
  previous_state_json jsonb NOT NULL,
  next_state_json jsonb NOT NULL,
  scheduled_due_at timestamptz NOT NULL,
  reviewed_at timestamptz NOT NULL DEFAULT now(),
  source text NOT NULL CHECK (source IN ('learn_submit', 'review_submit', 'manual_adjust')),
  request_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  title text NOT NULL,
  content_markdown text NOT NULL DEFAULT '',
  agent_draft_content text,
  is_user_edited boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS idempotency_records (
  key text PRIMARY KEY,
  operation text NOT NULL,
  request_hash text NOT NULL,
  response_json jsonb NOT NULL,
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  invalidated_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE idempotency_records
  ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS invalidated_at timestamptz;

ALTER TABLE exercises
  ADD COLUMN IF NOT EXISTS requires_explanation boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE knowledge_points
  ADD COLUMN IF NOT EXISTS lesson_outline_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS lesson_sources_json jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE learning_sessions
  ADD COLUMN IF NOT EXISTS request_id text,
  ADD COLUMN IF NOT EXISTS learning_stage text,
  ADD COLUMN IF NOT EXISTS learning_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS review_stage text,
  ADD COLUMN IF NOT EXISTS review_stage_state_json jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE attempts
  ADD COLUMN IF NOT EXISTS test_results_json jsonb NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN IF NOT EXISTS stdout text,
  ADD COLUMN IF NOT EXISTS stderr text,
  ADD COLUMN IF NOT EXISTS error_message text,
  ADD COLUMN IF NOT EXISTS error_cause text,
  ADD COLUMN IF NOT EXISTS hint_usage_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS error_count integer NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS explanation_text text,
  ADD COLUMN IF NOT EXISTS explanation_check_result jsonb,
  ADD COLUMN IF NOT EXISTS evaluation_status text NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS request_id text;

ALTER TABLE review_states
  ADD COLUMN IF NOT EXISTS last_fsrs_rating text,
  ADD COLUMN IF NOT EXISTS scheduler_version text NOT NULL DEFAULT 'fsrs_v1_default',
  ADD COLUMN IF NOT EXISTS suspended_at timestamptz;

DO $$
BEGIN
  ALTER TABLE exercises
    DROP CONSTRAINT IF EXISTS exercises_exercise_type_check;
  ALTER TABLE exercises
    ADD CONSTRAINT exercises_exercise_type_check
    CHECK (exercise_type IN ('code_blank', 'fix_bug', 'implement_function', 'explain_code', 'review_ai_patch'));
END;
$$;

DO $$
BEGIN
  ALTER TABLE learning_sessions
    DROP CONSTRAINT IF EXISTS learning_sessions_learning_stage_check;
  ALTER TABLE learning_sessions
    ADD CONSTRAINT learning_sessions_learning_stage_check
    CHECK (learning_stage IS NULL OR learning_stage IN ('concept_intro', 'concept_check', 'concept_repair', 'practice_offer', 'concept_qna', 'readiness_check', 'practice_support'));
END;
$$;

DO $$
BEGIN
  ALTER TABLE learning_sessions
    DROP CONSTRAINT IF EXISTS learning_sessions_review_stage_check;
  ALTER TABLE learning_sessions
    ADD CONSTRAINT learning_sessions_review_stage_check
    CHECK (review_stage IS NULL OR review_stage IN ('warmup', 'warmup_repair', 'variant_practice', 'submitted'));
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'attempts_evaluation_status_check'
  ) THEN
    ALTER TABLE attempts
      ADD CONSTRAINT attempts_evaluation_status_check
      CHECK (evaluation_status IN ('pending', 'evaluated', 'needs_manual_review'));
  END IF;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'review_states_last_fsrs_rating_check'
  ) THEN
    ALTER TABLE review_states
      ADD CONSTRAINT review_states_last_fsrs_rating_check
      CHECK (last_fsrs_rating IS NULL OR last_fsrs_rating IN ('Again', 'Hard', 'Good', 'Easy'));
  END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);
CREATE INDEX IF NOT EXISTS idx_runtime_profiles_language ON runtime_profiles(language);
CREATE INDEX IF NOT EXISTS idx_language_courses_language_level ON language_courses(language, level);
CREATE INDEX IF NOT EXISTS idx_learning_plans_user_status ON learning_plans(user_id, status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_plan_modules_plan_status ON plan_modules(plan_id, status);
CREATE INDEX IF NOT EXISTS idx_knowledge_points_module_status ON knowledge_points(module_id, status);
CREATE INDEX IF NOT EXISTS idx_exercises_knowledge_point ON exercises(knowledge_point_id);
CREATE INDEX IF NOT EXISTS idx_exercises_runtime_type ON exercises(runtime_profile_id, exercise_type);
CREATE INDEX IF NOT EXISTS idx_code_blanks_exercise ON code_blanks(exercise_id);
CREATE INDEX IF NOT EXISTS idx_test_cases_exercise_type ON test_cases(exercise_id, case_type);
CREATE INDEX IF NOT EXISTS idx_learning_sessions_user_plan ON learning_sessions(user_id, plan_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_sessions_request_id ON learning_sessions(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_attempts_user_exercise_created ON attempts(user_id, exercise_id, created_at);
CREATE INDEX IF NOT EXISTS idx_attempts_session_created ON attempts(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_attempts_exercise_created ON attempts(exercise_id, created_at DESC);
DROP INDEX IF EXISTS uq_attempts_submit_identity;
CREATE UNIQUE INDEX IF NOT EXISTS uq_attempts_request_id ON attempts(request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_review_states_user_due ON review_states(user_id, due_at);
CREATE INDEX IF NOT EXISTS idx_review_states_last_attempt ON review_states(last_attempt_id) WHERE last_attempt_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_seed_banks_scope ON review_seed_banks(user_id, knowledge_point_id, generator_version);
CREATE INDEX IF NOT EXISTS idx_review_seed_banks_status ON review_seed_banks(status, updated_at);

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

-- Onboarding conversation tables
CREATE TABLE IF NOT EXISTS onboarding_conversations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'plan_proposed', 'confirmed', 'abandoned')),
  extracted_context jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS onboarding_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES onboarding_conversations(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS review_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  review_session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learning_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES learning_sessions(id) ON DELETE RESTRICT,
  knowledge_point_id uuid NOT NULL REFERENCES knowledge_points(id) ON DELETE RESTRICT,
  role text NOT NULL CHECK (role IN ('user', 'agent')),
  content text NOT NULL,
  client_message_id text,
  metadata jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_conversations_user ON onboarding_conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_messages_conversation ON onboarding_messages(conversation_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_onboarding_messages_client_id ON onboarding_messages(client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_review_messages_session ON review_messages(review_session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_review_messages_client_id ON review_messages(client_message_id) WHERE client_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_learning_messages_kp_session_created ON learning_messages(knowledge_point_id, session_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_learning_messages_client_id ON learning_messages(client_message_id) WHERE client_message_id IS NOT NULL;

DROP TRIGGER IF EXISTS trg_onboarding_conversations_updated_at ON onboarding_conversations;
CREATE TRIGGER trg_onboarding_conversations_updated_at BEFORE UPDATE ON onboarding_conversations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
